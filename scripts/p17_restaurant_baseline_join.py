"""Offline original ChinaTravel restaurant association; no fact clock renewal."""
import collections,csv,gzip,hashlib,json,math,shutil,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_archives import normalize_name as norm
from shorttrip.source_identity import language_aliases
from shorttrip.dynamic.opendata import gcj02_to_wgs84
OUT=ROOT/'results/p17_continuous/restaurants'
def sha(b):return hashlib.sha256(b).hexdigest()
def dist(a,b):return 111195*math.hypot(a[1]-b[1],(a[0]-b[0])*math.cos(math.radians(a[1])))
def main(label):
 folder=OUT/label;folder.mkdir(exist_ok=False);(folder/'raw').mkdir();(folder/'csv').mkdir()
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
 live=sqlite3.connect(ROOT/pointer['catalog']);base=sqlite3.connect(ROOT/'data/catalog_v1_1_20261022/catalog.sqlite3')
 originals={};byname=collections.defaultdict(list);files={}
 for payload, in base.execute("SELECT payload FROM records WHERE kind='restaurant' AND lang='zh'"):
  b=json.loads(payload);originals[b['record_id']]=b;byname[norm(b['name'])].append(b);files[b['source_locator']['file']]=b['source_locator']['file_sha256']
 baseline_rows={}
 for filename,digest in files.items():
  p=ROOT/filename;blob=p.read_bytes()
  if sha(blob)!=digest:raise ValueError('Baseline CSV changed '+filename)
  shutil.copyfile(p,folder/'csv'/p.name)
  with p.open(encoding='utf-8-sig',newline='') as stream:
   for ordinal,row in enumerate(csv.DictReader(stream)):baseline_rows[(filename,ordinal)]=row
 candidates=[];wanted=collections.defaultdict(dict);rs={};audit=[]
 for payload, in live.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload);loc=r.get('source_locator',{})
  if not r['record_id'].startswith('overture:') or not loc.get('raw_file'):continue
  rs[r['record_id']]=r;wanted[loc['raw_file']][loc['raw_line']]=r['record_id']
 for filename,lines in wanted.items():
  with gzip.open(ROOT/filename,'rb') as stream:
   for ordinal,line in enumerate(stream,1):
    rid=lines.get(ordinal)
    if rid is None:continue
    raw=line.rstrip(b'\r\n');r=rs[rid];loc=r['source_locator']
    if sha(raw)!=loc['raw_sha256']:raise ValueError('GERS row changed')
    obj=json.loads(raw)
    if obj['id']!=rid.removeprefix('overture:') or obj['names']['primary']!=r['name']:raise ValueError('GERS identity changed')
    aliases=language_aliases(obj);options={}
    for name,alias in aliases.items():
     for b in byname.get(name,[]):
      a=(float(b['data']['lon']),float(b['data']['lat']));target=(r['data']['lon'],r['data']['lat']);ds=[dist(a,target),dist(gcj02_to_wgs84(*a),target)]
      if min(ds)<=150:options[b['record_id']]=(b,alias,ds)
    if not options:continue
    record_raw_file=folder/'raw'/(rid.replace(':','_')+'.json');record_raw_file.write_bytes(raw)
    for b,alias,ds in options.values():
     addresses=obj.get('addresses') or [];localities=[a.get('locality') for a in addresses if a.get('locality')]
     item={'entity_id':rid,'entity_name':r['name'],'catalogue_city_window':r['city'],'provider_localities':localities,'provider_addresses':addresses,'baseline_id':b['record_id'],'baseline_city':b['city'],'baseline_name':b['name'],'literal_alias':alias,'distances_metres':{'baseline_as_wgs84':ds[0],'baseline_as_gcj02_converted_wgs84':ds[1]},'coordinate_system_unconfirmed':True,'baseline_address_available':False,'address_review':'Original baseline CSV does not provide a street address; strict street-address corroboration unavailable.','original_source_locator':loc,'original_raw_file':str(record_raw_file.relative_to(ROOT)),'original_raw_sha256':sha(raw),'cross_provider_numeric_ids_used':False}
     candidates.append((r,b,item))
 by_entity=collections.Counter(r['record_id'] for r,b,x in candidates);by_base=collections.Counter(b['record_id'] for r,b,x in candidates)
 sources=[];assertions=[]
 for r,b,item in candidates:
  unique=by_entity[r['record_id']]==1 and by_base[b['record_id']]==1;item['both_unique']=unique;item['binding_status']='historical_same_venue_candidate_unverified';audit.append(item)
  if not unique:continue
  loc=b['source_locator'];row=baseline_rows[(loc['file'],loc['row_index_0based'])]
  for key in ['name','price','cuisine','opentime','endtime','lat','lon']:
   if str(row.get(key,''))!=str(b['data'].get(key,'')):raise ValueError('Baseline payload not exact CSV row '+key)
  sid='p17-chinatravel-baseline:'+b['record_id'];name='baseline_'+b['record_id']+'.json';content=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();(folder/name).write_bytes(content)
  (folder/('baseline_record_'+b['record_id']+'.json')).write_text(json.dumps(b,ensure_ascii=False,sort_keys=True),encoding='utf-8')
  sources.append({'source_id':sid,'source_url':'https://github.com/LAMDA-NeSy/ChinaTravel','publisher':'Original ChinaTravel frozen benchmark CSV; upstream repository URL not independently revisited in this offline association','authority':'research_benchmark_not_live_operator','independent_source_group':'chinatravel_original_frozen_dataset','representation':'saved_csv_row_serialized','content_file':name,'content_sha256':sha(content),'retrieved_at':None,'observed_at':None,'source_published_at':None,'source_updated_at':None,'valid_from':None,'valid_until':None,'licence_status':b.get('licence_status'),'source_locator':{**loc,'retained_csv_file':str((folder/'csv'/Path(loc['file']).name).relative_to(ROOT)),'source_record_id':b['record_id'],'source_coordinate_system':'unknown','serialized_row_is_not_original_byte_span':True}})
  for field,key,unit in [('average_price_reference','price','original_benchmark_price_unit_unconfirmed'),('cuisine_reference','cuisine',None),('opening_start_reference','opentime','local_clock_Asia/Shanghai'),('opening_end_reference','endtime','local_clock_Asia/Shanghai')]:
   if row.get(key) in (None,''):continue
   quote=json.dumps({key:row[key]},ensure_ascii=False,separators=(',',':'))[1:-1]
   assertions.append({'entity_id':r['record_id'],'entity_name':r['name'],'city':r['city'],'field':field,'value':row[key],'unit':unit,'quote':quote,'source_id':sid,'scope':'Historical original frozen ChinaTravel field, reused through a literal-name and near-coordinate candidate. No independent live validation, source observation time, street-address corroboration or current applicability. Does not count as expanded unique coverage.','status':'historical_frozen_dataset_candidate','identity_match_basis':item,'native_projection_permitted':False,'entity_verified':False,'planning_ready':False})
 result={'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'identity_audit':audit,'catalogue_basis':pointer,'baseline_records_scanned':len(originals),'expanded_overture_restaurants_scanned':len(rs),'candidate_pairs':len(candidates),'unique_candidates':len(sources),'network_requests':0,'new_entities':0,'independent_live_validations':0,'source_clocks_refreshed':0,'native_projection_permitted':False,'full_completion':False}
 (folder/'field_assertions.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if not isinstance(v,(dict,list))},ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])

