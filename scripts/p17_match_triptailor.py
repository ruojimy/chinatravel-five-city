"""Existing-entity matches only; paper averages are never current hotel quotations."""
import hashlib,json,math,re,sqlite3,sys,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'results/p17_continuous/open_datasets';OUT=BASE/'matched_batch_002'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.dynamic.opendata import gcj02_to_wgs84
from shorttrip.freshness import utcnow
def norm(s):return ''.join(x for x in unicodedata.normalize('NFKC',s or '').casefold() if x.isalnum())
def metres(a,b,r):return 111195*math.hypot(a-r['data']['lat'],(b-r['data']['lon'])*math.cos(math.radians(a)))
def main():
 OUT.mkdir(exist_ok=True);packet=OUT/'field_assertions.json'
 if packet.exists():raise FileExistsError('Matched data packet immutable')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/pointer['catalog']);records={};lookup={}
 for (payload,) in db.execute('SELECT payload FROM records'):
  r=json.loads(payload);records[r['record_id']]=r;lookup.setdefault((r['kind'],r['city'],norm(r['name'])),set()).add(r['record_id'])
  if r['data'].get('hotelname_en'):lookup.setdefault((r['kind'],r['city'],norm(r['data']['hotelname_en'])),set()).add(r['record_id'])
 db.close();index=sqlite3.connect(BASE/'triptailor_candidates.sqlite3');index.row_factory=sqlite3.Row
 sources_meta={x['kind']:dict(x) for x in index.execute('SELECT * FROM sources')};bridges={}
 pages=sqlite3.connect(ROOT/'results/p17_continuous/attractions/entity_source_queue.sqlite3')
 for (payload,) in pages.execute('SELECT result FROM parsed_pages'):
  p=json.loads(payload);m=re.search(r'/sight/[a-z0-9]+/(\d+)\.html',p['source_url'])
  if m and len(p['candidate_entity_ids'])==1:bridges[m[1]]=(p['candidate_entity_ids'][0],p['source_url'],p['raw_sha256'])
 pages.close();candidates={};audits=[]
 for row in index.execute('SELECT * FROM rows'):
  row=dict(row);ids=lookup.get((row['kind'],row['city'],row['normalized_name']),set()).copy()
  # Numeric IDs in the paper have not been shown to use the Ctrip URL-ID
  # namespace. Never treat equal integers as a bilingual identity mapping.
  bridge=None
  for rid in ids:
   r=records[rid];wgs=gcj02_to_wgs84(row['lon'],row['lat']);distances={'as_published_wgs84':metres(row['lat'],row['lon'],r),'if_gcj02_converted':metres(wgs[1],wgs[0],r)}
   direct=bool(bridge and bridge[0]==rid)
   if min(distances.values())>150:continue
   candidates.setdefault(rid,[]).append((row,{'method':'numeric_id_and_near_coordinate_candidate_namespace_not_verified' if direct else 'exact_name_city_unique_near_coordinate_candidate',
    'source_row':row['source_row'],'source_kind':row['kind'],'name':r['name'],'city':r['city'],'distances_metres':{k:round(v,2) for k,v in distances.items()},
    'coordinate_system_unconfirmed':True,'bridge_source_url':bridge[1] if direct else None,'bridge_response_sha256':bridge[2] if direct else None,'entity_verified':False}))
 capture=json.loads((BASE/'TripTailor_data_capture.json').read_text(encoding='utf-8'));sources={};assertions=[];matches=0;ambiguous=0;bykind={}
 for rid,options in candidates.items():
  direct=[x for x in options if x[1]['method'].startswith('numeric_id')]
  options=direct or options
  if len(options)!=1:audits.append({'entity_id':rid,'reason':'multiple_historical_rows_within_candidate_threshold','candidates':len(options)});ambiguous+=1;continue
  row,basis=options[0];values=json.loads(row['payload']);kind=row['kind'];ordinal=row['source_row'];matches+=1;bykind[kind]=bykind.get(kind,0)+1
  sourceid=f'p17-triptailor:{kind}:{ordinal}';raw=json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':'));file=OUT/f'{kind}_{ordinal}.json'
  file.write_bytes(raw.encode());meta=sources_meta[kind]
  sources[sourceid]={'source_id':sourceid,'source_url':capture['source_url'],'retrieved_at':capture['retrieved_at'],'observed_at':None,
   'source_published_at':None,'source_updated_at':None,'authority':'paper_author_released_historical_dataset','licence_status':'repository_licence_not_found_private_research_no_redistribution_claim',
   'representation':'saved_csv_row_serialized','content_file':file.name,'content_sha256':hashlib.sha256(raw.encode()).hexdigest(),
   'source_locator':{'csv_file':meta['file'],'csv_sha256':meta['sha256'],'csv_data_row_ordinal':ordinal,'kind':kind,
     'archive_sha256':capture['sha256'],'git_blob_sha1':capture['git_blob_sha1'],'archive_member_timestamp_is_not_fact_time':True}}
  def add(field,key,value=None,unit=None,scope=None):
   quote=json.dumps({key:values[key]},ensure_ascii=False,separators=(',',':'))[1:-1]
   assert quote in raw
   assertions.append({'entity_id':rid,'field':field,'value':values[key] if value is None else value,'unit':unit,
      'scope':scope or 'Historical released dataset field only; source observation time and current applicability unknown.',
      'quote':quote,'source_id':sourceid,'identity_match_basis':basis,'status':'historical_paper_dataset_reference',
      'root_projection_review':'explicit_historical_recommendation_in_hours' if field=='recommended_duration_text' else None,
      'native_projection_permitted':False,'entity_verified':False})
  if kind=='attraction':
   for field,key,unit in [('admission_reference','price','source_currency_not_explicit'),('opening_rules','opening_hours','local_clock_Asia/Shanghai'),('recommended_duration_text','reference_time','source_duration_text')]:
    if values.get(key) not in ('',None):add(field,key,unit=unit)
   if values.get('tagNameList'):add('experience_category_reference','tagNameList')
  elif kind=='restaurant':
   add('average_price_reference','avg_price',unit='source_average_per_person_currency_not_explicit')
   add('cuisine_reference','small_cate',scope='Explicit historical publisher category in English; source taxonomy, not current menu or dietary certification.')
  else:
   add('historical_average_nightly_price','avg_price',unit='source_average_per_night_currency_not_explicit',scope='Paper describes average hotel price per night; no stay dates, named room, beds or eligible rate plan, never a dated room quotation.')
   add('hotel_segment_reference','small_cate')
  audits.append({'entity_id':rid,**basis})
 report={'created_at':utcnow(),'sources':list(sources.values()),'assertions':assertions,'identity_audit':audits,'network_requests':0,
  'matched_existing_entities':matches,'ambiguous_entities_not_joined':ambiguous,'matched_by_kind':bykind,'new_entities':0,'no_dated_hotel_price_projection':True,
  'source_clocks_refreshed':0,'currency_not_explicitly_documented_no_native_price_projection':True}
 packet.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ('matched_existing_entities','ambiguous_entities_not_joined','matched_by_kind')}))
if __name__=='__main__':main()
