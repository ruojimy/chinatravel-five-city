"""Stream author-released CSVs; index only existing-name candidates and attraction IDs."""
import csv,hashlib,json,re,sqlite3,sys,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/open_datasets';TABLES=OUT/'TripTailor_tables'
sys.path.insert(0,str(ROOT/'src'));from shorttrip.freshness import utcnow
def norm(s):return ''.join(x for x in unicodedata.normalize('NFKC',s or '').casefold() if x.isalnum())
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def main():
 target=OUT/'triptailor_candidates.sqlite3'
 if target.exists():raise FileExistsError('Source index immutable; choose next explicit version')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));c=sqlite3.connect(ROOT/pointer['catalog']);names=set();slugs={}
 for payload, in c.execute('SELECT payload FROM records'):
  r=json.loads(payload)
  if r.get('city_slug'):slugs[norm(r['city_slug'])]=r['city']
  names.add((r['kind'],r['city'],norm(r['name'])))
  if r['data'].get('hotelname_en'):names.add((r['kind'],r['city'],norm(r['data']['hotelname_en'])))
 c.close();db=sqlite3.connect(target)
 db.executescript('PRAGMA cache_size=-8000; CREATE TABLE rows(kind TEXT,city TEXT,normalized_name TEXT,source_row INTEGER,poi_id TEXT,lon REAL,lat REAL,payload TEXT,PRIMARY KEY(kind,source_row)); CREATE INDEX named ON rows(kind,city,normalized_name); CREATE INDEX poi ON rows(poi_id); CREATE TABLE sources(kind TEXT PRIMARY KEY,file TEXT,sha256 TEXT,metadata TEXT);')
 summary={}
 for filename,kind in [('attractions.csv','attraction'),('accommodations.csv','accommodation'),('restaurants.csv','restaurant')]:
  file=TABLES/filename;total=0;kept=0;batch=[];cities={}
  with file.open(encoding='utf-8-sig',newline='') as f:
   for ordinal,row in enumerate(csv.DictReader(f),1):
    total+=1;city=slugs.get(norm(row.get('city') or row.get('real_city')));name=row.get('poiName') or row.get('name')
    if city is None:continue
    cities[city]=cities.get(city,0)+1
    if kind!='attraction' and (kind,city,norm(name)) not in names:continue
    try:lon=float(row['longitude']);lat=float(row['latitude'])
    except (ValueError,TypeError):continue
    batch.append((kind,city,norm(name),ordinal,row.get('poiId'),lon,lat,json.dumps(row,ensure_ascii=False,sort_keys=True)))
    kept+=1
    if len(batch)>=500:
     with db:db.executemany('INSERT INTO rows VALUES(?,?,?,?,?,?,?,?)',batch)
     batch=[]
  with db:
   if batch:db.executemany('INSERT INTO rows VALUES(?,?,?,?,?,?,?,?)',batch)
   meta={'rows_read_streaming':total,'rows_indexed':kept,'covered_existing_cities':cities,'source_observed_at':None,'licence_status':'not_found_no_redistribution_claim','file_hash_is_not_fact_clock':True}
   db.execute('INSERT INTO sources VALUES(?,?,?,?)',(kind,str(file.relative_to(ROOT)),digest(file),json.dumps(meta,ensure_ascii=False)))
  summary[kind]=meta;print(json.dumps({'kind':kind,'read':total,'indexed':kept}),flush=True)
 db.close();(OUT/'triptailor_index_summary.json').write_text(json.dumps({'at':utcnow(),'sources':summary,'new_entities':0,'network_requests':0,'no_full_csv_loaded_in_memory':True},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
