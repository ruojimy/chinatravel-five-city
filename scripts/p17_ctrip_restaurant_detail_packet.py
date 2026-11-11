"""Materialize cached public restaurant detail plus exact /person card evidence."""
import collections,gzip,hashlib,json,math,re,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.dynamic.opendata import gcj02_to_wgs84
from shorttrip.business_archives import normalize_name as norm
from opencc import OpenCC
CC=OpenCC('t2s');BASE=ROOT/'results/p17_continuous/restaurants';DISC=BASE/'ctrip_recommendations_001'
def sha(b):return hashlib.sha256(b).hexdigest()
def key(s):return norm(CC.convert(s))
def main(label):
 folder=BASE/label;folder.mkdir(exist_ok=False);ptr=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));catalog=sqlite3.connect(ROOT/ptr['catalog']);queue=sqlite3.connect(ROOT/'results/p17_continuous/attractions/ctrip_public_crawler/queue.sqlite3');front=json.loads((DISC/'observed_detail_frontier.json').read_text(encoding='utf-8'));jobs={x['url']:queue.execute('SELECT status,result FROM jobs WHERE url=?',(x['url'],)).fetchone() for x in front};queue.close();recdb=sqlite3.connect(DISC/'recommendations.sqlite3');sources=[];assertions=[];audit=[]
 for hint in front:
  status,result=jobs[hint['url']] or (None,None)
  if status!='captured':audit.append({'url':hint['url'],'status':status});continue
  ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read()
  if sha(raw)!=ev['sha256']:raise ValueError('Detail HTML changed')
  m=re.search(rb'<script\b[^>]*\bid=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>',raw,re.S);nextdata=json.loads(m[1]);detail=nextdata['props']['pageProps']['initialState']['restaurantDetail'];serialized=json.dumps(detail,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();stem=sha(hint['url'].encode())[:20];(folder/(stem+'.json')).write_bytes(serialized);sid='p17-ctrip-restaurant-detail:'+stem
  source={'source_id':sid,'source_url':hint['url'],'retrieved_at':ev['retrieved_at'],'observed_at':None,'source_published_at':None,'source_updated_at':None,'valid_from':None,'valid_until':None,'authority':'commercial_travel_platform_restaurant_detail','independent_source_group':'ctrip_public_site','representation':'saved_public_html_json_object_serialized','content_file':stem+'.json','content_sha256':sha(serialized),'licence_status':'public_web_reuse_unverified_private_research_only','source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':ev['sha256'],'json_pointer':'/props/pageProps/initialState/restaurantDetail','next_data_script_sha256':sha(m[1]),'detail_poi_id_not_joined_to_other_provider_ids':True}}
  for rid in hint['existing_entity_ids']:
   r=json.loads(catalog.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);sourcecoord=detail['gaodeCoord'];p=(sourcecoord['lon'],sourcecoord['lat']);target=(r['data']['lon'],r['data']['lat']);converted=gcj02_to_wgs84(*p);d=lambda p:111195*math.hypot(p[1]-target[1],(p[0]-target[0])*math.cos(math.radians(target[1])));distances={'gaodeCoord_as_GCJ02_converted_to_WGS84_vs_original':d(converted),'gaodeCoord_raw_vs_original':d(p)};distance=d(p) if r['coordinate_system']=='GCJ02' else d(converted)
   loc=r['source_locator'];original=None
   if rid.startswith('overture:'):
    with gzip.open(ROOT/loc['raw_file'],'rb') as stream:
     for n,line in enumerate(stream,1):
      if n==loc['raw_line']:original=line.rstrip(b'\r\n');break
    if original is None or sha(original)!=loc['raw_sha256']:raise ValueError('Original row changed')
    orig=json.loads(original);original_kind='exact_retained_overture_jsonl_bytes';aliases=[orig['names']['primary']]+[x.get('value','') for x in (orig.get('names',{}).get('rules') or []) if x.get('variant')=='language' and not any(x.get(a) for a in ['perspectives','between','side'])];phones=orig.get('phones') or [];addresses=[x.get('freeform') for x in orig.get('addresses') or [] if x.get('freeform')]
   else:
    orig=loc['raw_poi'];original=json.dumps(orig,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();original_kind='saved_original_provider_poi_object_serialized';aliases=[orig['name']];phones=(orig.get('business',{}).get('tel') or '').split(';');addresses=[orig['address']]
   if key(detail['name']) not in {key(a) for a in aliases}:raise ValueError('Full original name/alias not exact')
   normalizephone=lambda x:re.sub(r'\D','',x).removeprefix('86')
   # Local telephone normalization is recorded only as corroboration, while
   # WGS/GCJ proximity is separately mandatory for every admitted candidate.
   phone_match=next((x for x in detail.get('phones',[]) if normalizephone(x) in {normalizephone(y).lstrip('0') for y in phones} or normalizephone(x).lstrip('0') in {normalizephone(y).lstrip('0') for y in phones}),None)
   originalfile=rid.replace(':','_')+'.json';(folder/originalfile).write_bytes(original);basis={'method':'literal_original_full_name_or_language_alias_and_near_public_gaodeCoord','original_name':r['name'],'source_name':detail['name'],'source_address':detail.get('address'),'original_addresses':addresses,'source_coordinates':sourcecoord,'source_coordinate_property':'gaodeCoord','source_coordinate_semantics':'Public field explicitly labelled gaodeCoord, treated as GCJ02 hypothesis; googleCoord not assumed WGS84','original_coordinate_system':r['coordinate_system'],'distance_metres_using_original_coordinate_system':distance,'distances_under_both_hypotheses':distances,'coordinate_identity_threshold_metres':100,'matched_phone':phone_match,'source_city_context':'Coordinates evaluated directly against the original location; no city inferred from recommending attraction or initialState.districtName placeholder','catalogue_city_window':r['city'],'original_source_locator':loc,'raw_row_file':str((folder/originalfile).relative_to(ROOT)),'raw_row_sha256':sha(original),'original_evidence_representation':original_kind,'identity_detail_source_id':sid,'identity_detail_content_file':source['content_file'],'identity_detail_sha256':source['content_sha256'],'entity_verified':False};audit.append({'entity_id':rid,'entity_name':r['name'],'source_url':hint['url'],'status':'reference_match_candidate' if distance<=100 else 'coordinate_conflict_discovery_only',**basis})
   if distance>100:continue
   sources.append(source)
   # Retain exactly one explicit card from a grounded source, deduplicating
   # repeated cards and refusing cross-ID integer joins.
   options=[]
   for payload,evidence in recdb.execute('SELECT payload,evidence FROM objects WHERE item_url=?',(hint['url'],)):
    item=json.loads(payload);e=json.loads(evidence);pm=re.fullmatch(r'￥(\d+(?:\.\d+)?)/人',item.get('price') or '')
    if pm and float(pm[1])==detail.get('averagePrice') and key(item['name'])==key(detail['name']):options.append((item,e))
   if not options:continue
   item,e=min(options,key=lambda x:x[1]['source_url']);file='card_'+stem+'.json';b=(DISC/e['content_file']).read_bytes()
   if sha(b)!=e['content_sha256']:raise ValueError('Recommendation object changed')
   (folder/file).write_bytes(b);card_source={**e,'content_file':file};sources.append(card_source)
   quote=json.dumps({'price':item['price']},ensure_ascii=False,separators=(',',':'))[1:-1]
   common={'entity_id':rid,'entity_name':r['name'],'city':r['city'],'identity_match_basis':basis,'status':'public_platform_reference_unknown_fact_age','entity_verified':False,'native_projection_permitted':False,'planning_ready':False}
   assertions.append({**common,'field':'average_price','value':detail['averagePrice'],'unit':'CNY_per_person_reference','quote':quote,'source_id':e['source_id'],'scope':'Explicit /人 public recommendation-card amount agrees with same observed jumpUrl restaurantDetail.averagePrice. Average spend reference, not a guaranteed bill or current quote; unknown source fact time. Repeated cards are same platform, not independent validation.'})
   geographic={'粤菜','闽菜','东北菜','川菜','湘菜','江浙菜','鲁菜','西北菜','云南菜','贵州菜','北京菜','上海菜','湖北菜','徽菜','泰国菜','韩国料理','日本料理'}
   for cuisine in detail.get('cuisines') or []:
    label=cuisine.get('name')
    if not label:continue
    field='cuisine' if label in geographic else 'food_category_reference';quote=json.dumps(cuisine,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if quote not in serialized.decode():raise ValueError('Cuisine quote missing')
    assertions.append({**common,'field':field,'value':label,'unit':None,'quote':quote,'source_id':sid,'scope':'Explicit public restaurantDetail.cuisines label. Broad quick-meal/snack labels remain food category, not regional cuisine or dietary certification; actual menu, hours, validity date unknown.'})
 sources=list({s['source_id']:s for s in sources}.values());report={'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'identity_audit':audit,'catalogue_basis':ptr,'network_requests_by_this_materializer':0,'new_entities':0,'source_clocks_refreshed':0,'independent_validation_claimed':False,'matched_reference_entities':len({a['entity_id'] for a in assertions}),'field_counts':dict(collections.Counter(a['field'] for a in assertions)),'opening_hours_available':False,'full_completion':False};(folder/'field_assertions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ['created_at','matched_reference_entities','field_counts','source_clocks_refreshed','full_completion']},ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
