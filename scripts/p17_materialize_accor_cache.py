"""Recover scoped room configurations from already retained operator HTML, offline."""
import gzip,hashlib,json,math,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/hotels/accor_cached_001'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.operator_room_dom import accor_rooms
from shorttrip.freshness import utcnow
def distance(lat,lon,r):return 111195*math.hypot(lat-r['data']['lat'],(lon-r['data']['lon'])*math.cos(math.radians(lat)))
def main():
 OUT.mkdir(exist_ok=True);out=OUT/'field_assertions.json'
 if out.exists():raise FileExistsError('Immutable cache extraction batch')
 web=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3');links=sqlite3.connect(ROOT/'results/p15_whole_catalog/source_links.sqlite3')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));catalog=sqlite3.connect(ROOT/pointer['catalog'])
 sources=[];assertions=[];audit=[];selected=set()
 for url,result in web.execute("SELECT url,result FROM jobs WHERE status='captured' AND url LIKE 'https://all.accor.com/%'"):
  ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read();digest=hashlib.sha256(raw).hexdigest()
  if digest!=ev['sha256']:raise ValueError('Retained operator HTML changed')
  parsed=accor_rooms(raw);rooms=[];seen_cards=set();gps=parsed['gps']
  for room in parsed['room_configurations']:
   key=(room['room_type_name'],room['bed_quote'],room['quote'])
   if key not in seen_cards:rooms.append(room);seen_cards.add(key)
  ids=[x[0] for x in links.execute("SELECT entity_id FROM links WHERE url=? AND kind='accommodation'",(url,))]
  audit.append({'url':url,'hotel_name':parsed['hotel_name'],'room_configurations':len(rooms),'linked_entities':len(ids),'gps':gps})
  if not rooms or not ids:continue
  text='\n'.join([parsed['hotel_name'] or '',gps['quote'] if gps else '']+[x['quote'] for x in rooms]);file=OUT/(digest+'.txt');file.write_bytes(text.encode())
  sid='p17-accor-cached:'+hashlib.sha256(url.encode()).hexdigest()
  sources.append({'source_id':sid,'source_url':url,'retrieved_at':ev['retrieved_at'],'observed_at':None,
    'source_published_at':None,'source_updated_at':None,'authority':'primary_operator','licence_status':'public_operator_web_reuse_unverified',
    'content_file':file.name,'content_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'representation':'public_html_dom_text',
    'source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':digest,'dom_parser':'shorttrip.operator_room_dom.accor_rooms',
      'gps':gps,'hotel_name':parsed['hotel_name'],'scope':'Retained original response; offline parser time is not a source update'}})
  for rid in ids:
   r=json.loads(catalog.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);d=distance(gps['lat'],gps['lon'],r) if gps else None
   for room in rooms:
    scope={'room_type_name':room['room_type_name'],'provider_room_type_id':room['provider_room_type_id'],'room_count':room['room_count'],
      'bed_quote':room['bed_quote'],'bed_alternatives':room['alternatives'],'multiroom':room['multiroom'],
      'source_property_name':parsed['hotel_name'],'gps_distance_metres':round(d,2) if d is not None else None,
      'location_assumption':'public GPS compared as WGS84 candidate only; no independent coordinate certificate','current_availability':None}
    base={'entity_id':rid,'scope':json.dumps(scope,ensure_ascii=False),'quote':room['quote'],'source_id':sid,
      'identity_match_basis':'Existing exact raw website association plus explicit visible operator GPS; unresolved location differences retained.',
      'entity_verified':False,'status':'operator_room_reference_unknown_fact_age'}
    assertions.append({**base,'field':'room_type_name','value':room['room_type_name'],'unit':None})
    value=room['bed_count'] if room['bed_count'] is not None else {'components':room['bed_configuration'],'count':None,'bed_quote':room['bed_quote']}
    choose=rid not in selected and room['room_count']==1 and room['bed_count'] is not None and d is not None and d<=150
    assertions.append({**base,'field':'bed_configuration','value':value,'unit':'physical_beds_per_named_room_configuration',
      'root_projection_review':'accor_visible_gps_150m_named_single_room' if choose else None})
    if choose:selected.add(rid)
  print(json.dumps({'url':url,'rooms':len(rooms),'linked_entities':len(ids),'selected_entities':len(selected)}),flush=True)
 report={'created_at':utcnow(),'sources':sources,'assertions':assertions,'audit':audit,'network_requests':0,
  'new_source_observation_times':0,'eligible_named_room_bed_projection_candidates':len(selected),'source_properties_with_rooms':len(sources)}
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'sources':len(sources),'assertions':len(assertions),'eligible_selected_configurations':len(selected)}))
if __name__=='__main__':main()
