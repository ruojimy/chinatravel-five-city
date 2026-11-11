"""Join already saved POIs to all existing restaurants without new API calls."""
import collections,hashlib,json,sqlite3,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.scoped_business import matching_aliases,provider_aliases,match_target,today_hours
OUT=ROOT/'results/p17_continuous/restaurants'
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'cached_join').mkdir(exist_ok=True)
 now=datetime.now(timezone.utc).isoformat();pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 pois={};files=list((ROOT/'results/p15_whole_catalog/private_api_raw').glob('*.json'))+list((ROOT/'results/p14_targeted_completion/private_api_raw').glob('*.json'))
 for f in files:
  packet=json.loads(f.read_text(encoding='utf-8'))
  for poi in packet['response'].get('pois',[]):
   if not poi.get('type','').startswith('餐饮服务;'):continue
   previous=pois.get(poi['id'])
   if previous is None or packet['meta']['retrieved_at']>previous[2]['retrieved_at']:pois[poi['id']]=(poi,f,packet['meta'])
 names=collections.defaultdict(dict)
 for poi,f,m in pois.values():
  for name in provider_aliases(poi):names[(poi.get('cityname','').removesuffix('市'),name)][poi['id']]=poi
 sources=[];assertions=[];audit=[]
 for payload, in db.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload);candidates={}
  if r['record_id'].startswith('amap:'):
   audit.append({'entity_id':r['record_id'],'result':'already_provider_id_not_new_crossmatch'});continue
  for name in matching_aliases(r['name']):candidates.update(names[(r['city'],name)])
  target={'name':r['name'],'city':r['city'],'longitude_wgs84':r['data']['lon'],'latitude_wgs84':r['data']['lat']}
  match=match_target(target,list(candidates.values()));entry={'entity_id':r['record_id'],'name':r['name'],'city':r['city'],**{k:v for k,v in match.items() if k!='poi'}};audit.append(entry)
  if not match['matched']:continue
  poi,f,meta=pois[match['poi']['id']];b=poi.get('business') or {};fields=[]
  if r['data'].get('price') is None and b.get('cost'):
   try:
    price=float(b['cost'])
    if price>=0:fields.append(('average_price',price,'CNY/person','cost',b['cost']))
   except ValueError:pass
  cuisine=b.get('keytag') or b.get('rectag')
  if r['data'].get('cuisine') is None and cuisine:fields.append(('cuisine',cuisine,None,'keytag' if b.get('keytag') else 'rectag',cuisine))
  if not r.get('today_hours_structured') and b.get('opentime_today'):
   if today_hours(b['opentime_today'])['segments']:fields.append(('opening_rules',b['opentime_today'],'local_time','opentime_today',b['opentime_today']))
  entry['new_field_candidates']=[x[0] for x in fields]
  if not fields:continue
  sid='p17_cached_'+r['record_id'].replace(':','_');file='cached_join/'+r['record_id'].replace(':','_')+'.json'
  # Byte exact subset representation of preserved response; original packet stays referenced.
  content=json.dumps(poi,ensure_ascii=False,separators=(',',':')).encode('utf-8');(OUT/file).write_bytes(content)
  source={'source_id':sid,'source_url':meta['endpoint'],'publisher':'Amap saved provider response',
   'independent_source_group':'amap_same_original_provider_not_independent_validation','authority':'structured_provider',
   'representation':'saved_response_poi_object_serialized','content_file':file,'content_sha256':sha(content),
   'retrieved_at':meta['retrieved_at'],'source_published_at':None,'source_updated_at':None,'observed_at':None,'valid_from':None,'valid_until':None,
   'licence_status':'api_terms_research_only_not_open_redistribution','original_packet_file':str(f.relative_to(ROOT)),
   'original_packet_sha256':sha(f.read_bytes()),'source_locator':{'poi_id':poi['id'],'business_fields':True},
   'retrieval_clock_basis':'original API fetch; offline review does not renew facts'}
  sources.append(source)
  for field,value,unit,key,rawvalue in fields:
   quote=json.dumps({key:rawvalue},ensure_ascii=False,separators=(',',':'))[1:-1]
   if quote not in content.decode('utf-8'):raise ValueError('Quote not grounded')
   request_day=datetime.fromisoformat(meta['retrieved_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()
   scope='Provider average per-person cost reference, not bill or maximum.' if field=='average_price' else 'Provider cuisine label; no dietary certification.' if field=='cuisine' else 'Provider today rule relative to original request local date '+request_day+', not future opening guarantee.'
   assertions.append({'assertion_id':sid+'_'+field,'entity_id':r['record_id'],'entity_name':r['name'],'city':r['city'],
    'field':field,'value':value,'unit':unit,'source_id':sid,'source_url':meta['endpoint'],'evidence_sha256':source['content_sha256'],
    'evidence_file':file,'retrieved_at':meta['retrieved_at'],'source_published_at':None,'source_updated_at':None,'observed_at':None,
    'valid_from':None,'valid_until':None,'applicability':{'provider_request_date':request_day} if field=='opening_rules' else None,
    'scope':scope,'quote':quote,'status':'candidate_reference','entity_verified':False,
    'identity_match_basis':match['method']+'; '+json.dumps(match['binding'],ensure_ascii=False),
    'binding_review':match['binding'],'native_projection_permitted':False,'planning_ready':False,
    'ttl_seconds':15552000 if field=='cuisine' else 86400,'freshness_status':'unknown_provider_fact_clock',
    'evidence_locator':{'method':'exact_substring','quote':quote,'json_pointer':'/business/'+key},
    'notes':['Offline global entity join uses existing saved response; no new request to paused Amap.'],
    'tags':[{'tag':field,'value':value,'scope':scope,'source_id':sid,'evidence_sha256':source['content_sha256'],
       'status':'source_attribute_unverified','observed_at':None,'valid_until':None}]})
 dump(OUT/'cached_join_assertions.json',{'schema_version':'p16-field-assertions-v1','created_at':now,'catalogue_basis':pointer,
   'sources':sources,'assertions':assertions,'formal_database_modified':False,'network_requests':0})
 with (OUT/'cached_join_audit.jsonl').open('w',encoding='utf-8') as stream:
  for item in audit:stream.write(json.dumps(item,ensure_ascii=False)+'\n')
 summary={'at':now,'packets_read':len(files),'independent_restaurant_poi_ids':len(pois),'entities_examined':len(audit),
  'safe_candidate_matches':sum(a.get('matched',False) for a in audit),'new_reference_entities':len(sources),'new_reference_assertions':len(assertions),
  'field_counts':dict(collections.Counter(a['field'] for a in assertions)),'network_requests':0,'provider_still_paused':True}
 dump(OUT/'cached_join_summary.json',summary);print(json.dumps(summary))
if __name__=='__main__':main()
