"""Stream captured public SSR restaurant recommendation objects, never fetch."""
import collections,gzip,hashlib,json,re,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_archives import normalize_name as norm
from shorttrip.source_identity import language_aliases
from opencc import OpenCC
CC=OpenCC('t2s');OUT=ROOT/'results/p17_continuous/restaurants';SOURCE=ROOT/'results/p17_continuous/attractions/ctrip_public_crawler'
def sha(b):return hashlib.sha256(b).hexdigest()
def key(s):return norm(CC.convert(s))
def main(label):
 folder=OUT/label;folder.mkdir(exist_ok=False);(folder/'objects').mkdir();(folder/'entity_rows').mkdir();db=sqlite3.connect(folder/'recommendations.sqlite3');db.executescript('PRAGMA cache_size=-4000; CREATE TABLE objects(source_url TEXT,pointer TEXT,item_url TEXT,name TEXT,price TEXT,payload TEXT,evidence TEXT,PRIMARY KEY(source_url,pointer)); CREATE INDEX named ON objects(name);')
 ptr=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));catalog=sqlite3.connect(ROOT/ptr['catalog']);rs={};wanted=collections.defaultdict(dict);names=collections.defaultdict(set);raws={}
 for payload, in catalog.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload);loc=r.get('source_locator',{});rid=r['record_id'];rs[rid]=r
  names[key(r['name'])].add(rid)
  if rid.startswith('overture:') and loc.get('raw_file'):wanted[loc['raw_file']][loc['raw_line']]=rid
 for filename,lines in wanted.items():
  with gzip.open(ROOT/filename,'rb') as f:
   for n,line in enumerate(f,1):
    rid=lines.get(n)
    if rid is None:continue
    raw=line.rstrip(b'\r\n');r=rs[rid]
    if sha(raw)!=r['source_locator']['raw_sha256']:raise ValueError('Original row changed')
    obj=json.loads(raw);raws[rid]=raw
    for alias in language_aliases(obj).values():names[key(alias['value'])].add(rid)
 crawler=sqlite3.connect(SOURCE/'queue.sqlite3',timeout=30);jobs=crawler.execute("SELECT url,result FROM jobs WHERE status='captured'").fetchall();crawler.close();counts=collections.Counter();frontier={};audits=[]
 for url,result in jobs:
  ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read();counts['html_captures_scanned']+=1
  if sha(raw)!=ev['sha256']:raise ValueError('Saved HTML changed')
  m=re.search(rb'<script\b[^>]*\bid=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>',raw,re.S)
  if not m:continue
  try:obj=json.loads(m[1])
  except (ValueError,UnicodeDecodeError):counts['invalid_next_data']+=1;continue
  poi=obj.get('props',{}).get('pageProps',{}).get('initialState',{}).get('poiDetail',{})
  items=(poi.get('restaurantRecommend') or {}).get('itemList') or []
  if items:counts['pages_with_restaurant_recommendations']+=1
  for i,item in enumerate(items):
   if not isinstance(item,dict) or not item.get('name'):continue
   counts['recommendation_objects']+=1;pointer=f'/props/pageProps/initialState/poiDetail/restaurantRecommend/itemList/{i}';text=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'));sid='p17-ctrip-recommendation:'+sha((url+'#'+pointer).encode())[:24];file='objects/'+sid.split(':')[-1]+'.json';(folder/file).write_bytes(text.encode())
   evidence={'source_id':sid,'source_url':url,'retrieved_at':ev['retrieved_at'],'observed_at':None,'source_published_at':None,'source_updated_at':None,'representation':'saved_public_html_json_object_serialized','content_file':file,'content_sha256':sha(text.encode()),'authority':'commercial_travel_platform_recommendation','independent_source_group':'ctrip_public_site','licence_status':'public_web_reuse_unverified_private_research_only','source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':ev['sha256'],'json_pointer':pointer,'next_data_script_sha256':sha(m[1]),'recommended_attraction_city_is_not_restaurant_city':True,'poiId_namespace_not_assumed_equal_to_jumpUrl_or_other_provider_ids':True}}
   db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?)',(url,pointer,item.get('jumpUrl'),key(item['name']),item.get('price'),text,json.dumps(evidence,ensure_ascii=False)))
   ids=names.get(key(item['name']),set())
   if not ids:continue
   dest=item.get('jumpUrl') or '';p=urlsplit(dest);eligible=p.scheme=='https' and p.hostname=='you.ctrip.com' and p.path.startswith('/food/') and not p.query and not p.fragment
   for rid in sorted(ids):
    r=rs[rid];original=raws.get(rid);rowfile=None
    if original:
     rowfile='entity_rows/'+rid.replace(':','_')+'.json';(folder/rowfile).write_bytes(original)
    a={'entity_id':rid,'entity_name':r['name'],'catalogue_city_window':r['city'],'provider_city_assertions':r['source_locator'].get('city_assertions'),'source_recommendation_name':item['name'],'source_price_raw':item.get('price'),'source_tags_raw':item.get('tags'),'actual_observed_jump_url':dest,'source_id':sid,'source_evidence':evidence,'source_name_normalization':'NFKC, casefold, alphanumeric retention, OpenCC t2s; full branch text retained','identity_match_status':'literal_full_name_or_source_language_alias_only_location_unresolved','native_projection_permitted':False,'raw_row_file':str((folder/rowfile).relative_to(ROOT)) if rowfile else None,'raw_row_sha256':sha(original) if original else None,'original_source_locator':r['source_locator'],'source_city':None,'source_coordinates':None,'source_address':None,'planning_ready':False};audits.append(a)
    if eligible:
     frontier.setdefault(dest,{'url':dest,'kind':'restaurant_observed_jumpurl_detail','entity_id':rid,'existing_entity_ids':set(),'discovered_from':[]})['existing_entity_ids'].add(rid)
     frontier[dest]['discovered_from'].append({'source_id':sid,'source_url':url,'json_pointer':pointer,'name':item['name'],'price_raw':item.get('price'),'raw_html_sha256':ev['sha256']})
  del obj,raw
 db.commit();db.close()
 queue=[]
 for x in frontier.values():x['existing_entity_ids']=sorted(x['existing_entity_ids']);queue.append(x)
 (folder/'observed_detail_frontier.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2),encoding='utf-8');(folder/'identity_candidates.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
 result={'created_at':datetime.now(timezone.utc).isoformat(),'catalogue_basis':ptr,'counts':dict(counts),'exact_name_candidate_pairs':len(audits),'candidate_existing_entities':len({x['entity_id'] for x in audits}),'observed_detail_urls':len(queue),'assertions':[],'network_requests':0,'formal_business_completions':0,'source_clocks_refreshed':0,'limitations':'Recommendation object has no address/city/coordinates. Price /person meaning explicit when present; names alone do not bind a branch. Read only retained public HTML, never private API or fabricated numeric URL.'};(folder/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
