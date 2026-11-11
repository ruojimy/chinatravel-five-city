"""Expand observed public hotel links for existing entities, one paced publisher worker."""
import argparse,gzip,hashlib,json,os,re,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/hotels'
sys.path[:0]=[str(ROOT/'src'),str(OUT)]
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.freshness import utcnow
from trip_detail_parser import parse_trip_html
def norm(s):return re.sub(r'[^\w\u4e00-\u9fff]','',s).casefold()
def write(p,v):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(t,p)
def main(max_requests,max_hours):
 start=time.monotonic();directory=OUT/'trip_crawler';c=BusinessCrawler(directory,minimum_interval=8,max_bytes=8*1024*1024)
 ix=sqlite3.connect(OUT/'trip_entity_queue.sqlite3');ix.row_factory=sqlite3.Row
 ix.executescript('''CREATE TABLE IF NOT EXISTS links(url TEXT,entity_id TEXT,name TEXT,city TEXT,parent_url TEXT,parent_sha256 TEXT,PRIMARY KEY(url,entity_id));
 CREATE TABLE IF NOT EXISTS parsed(url TEXT PRIMARY KEY,packet TEXT);
 CREATE TABLE IF NOT EXISTS entities(entity_id TEXT PRIMARY KEY,city TEXT,name TEXT,status TEXT DEFAULT 'source_discovery_pending');''')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/pointer['catalog']);lookup={};slugs={}
 with ix:
  for (payload,) in db.execute("SELECT payload FROM records WHERE kind='accommodation'"):
   r=json.loads(payload);slugs[r['city_slug'].replace('-','')]=r['city'];lookup.setdefault((r['city'],norm(r['name'])),[]).append(r['record_id'])
   ix.execute('INSERT OR IGNORE INTO entities(entity_id,city,name) VALUES(?,?,?)',(r['record_id'],r['city'],r['name']))
 db.close()
 def shared_pauses():
  shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3')
  # All aliases of this publisher stop when a known Trip host is restricted.
  rows=shared.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE host LIKE '%trip.com'").fetchall();shared.close()
  local=c.db.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE host LIKE '%trip.com'").fetchall()
  for row in rows:
   if row[1]=='paused':return row[0]+':'+row[5]
  for row in local:
   if row['status']=='paused':return row['host']+':'+row['reason']
  return None
 def parse_captured():
  for url,result in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'").fetchall():
   previous=ix.execute('SELECT packet FROM parsed WHERE url=?',(url,)).fetchone()
   if previous and json.loads(previous[0]).get('parser_version')=='p17-public-city-list-v2':continue
   ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read();digest=hashlib.sha256(raw).hexdigest()
   if digest!=ev['sha256']:raise ValueError('Source bytes changed')
   soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser');parsed=parse_trip_html(raw)
   ids=[x[0] for x in ix.execute('SELECT entity_id FROM links WHERE url=?',(url,))]
   for a in soup.find_all('a',href=True):
    dest=urljoin(url,a['href']);p=urlsplit(dest);m=re.search(r'/hotels/(?:v2/)?([\w-]+?)-hotel-detail-\d+',p.path)
    if p.scheme!='https' or p.hostname not in ('www.trip.com','us.trip.com'):continue
    citylist=re.fullmatch(r'/hotels/([a-z-]+)-hotels-list-\d+/?',p.path)
    if citylist and slugs.get(citylist[1].replace('-','')):
     c.enqueue([{'url':dest,'kind':'hotel_city_link_discovery'}]);continue
    if p.path.rstrip('/')=='/hotels/all-cities':
     c.enqueue([{'url':dest,'kind':'hotel_city_directory_discovery'}]);continue
    if not m:continue
    city=slugs.get(m[1].replace('-',''));heading=a.find(['h2','h3','h4']);name=heading.get_text(' ',strip=True) if heading else a.get_text(' ',strip=True);matches=lookup.get((city,norm(name)),[])
    if len(matches)!=1:continue
    # Use the actual observed href; never substitute another host or fabricate IDs.
    with ix:ix.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?,?,?)',(dest,matches[0],name,city,url,digest))
    c.enqueue([{'url':dest,'kind':'accommodation','entity_id':matches[0]}])
   packet={'parser_version':'p17-public-city-list-v2','source_url':url,'retrieved_at':ev['retrieved_at'],'observed_at':None,'source_updated_at':None,
     'source_published_at':None,'raw_file':ev['raw_file'],'raw_sha256':digest,'source_property_name':parsed['hotel_name'],
     'source_addresses':parsed['addresses'],'candidate_entity_ids':ids,'room_configurations':parsed['room_configurations'],
     'identity_verified':False,'price_usable':False,'source_scope':'public HTML room cards; exact visible-link name and city candidate, address review still required'}
   with ix:
    ix.execute('INSERT OR REPLACE INTO parsed VALUES(?,?)',(url,json.dumps(packet,ensure_ascii=False)))
    for rid in ids:ix.execute('UPDATE entities SET status=? WHERE entity_id=?',('room_reference_pending_address_review' if parsed['room_configurations'] else 'public_page_missing_rooms',rid))
 while time.monotonic()-start<max_hours*3600 and c.requests_made<max_requests:
  if (OUT/'TRIP_STOP').exists():reason='local_stop';break
  blocked=shared_pauses()
  if blocked:reason='publisher_paused:'+blocked;break
  parse_captured()
  if not c.db.execute("SELECT 1 FROM jobs WHERE status='pending'").fetchone():reason='observed_link_frontier_exhausted_requires_new_source_discovery';break
  result=c.run(max_requests=max_requests,max_seconds=12);parse_captured()
  # One sequential publisher request even when a public recommendation uses another locale hostname.
  with c.db:
   last=c.db.execute("SELECT max(last_at) FROM hosts WHERE host LIKE '%trip.com'").fetchone()[0] or 0
   c.db.execute("UPDATE hosts SET last_at=max(last_at,?) WHERE host LIKE '%trip.com'",(last,))
  write(OUT/'trip_expand_status.json',{'at':utcnow(),'pid':os.getpid(),'running':True,'requests':c.requests_made,
    'jobs':dict(c.db.execute('SELECT status,count(*) FROM jobs GROUP BY status')),
    'entities':dict(ix.execute('SELECT status,count(*) FROM entities GROUP BY status')),'elapsed_seconds':round(time.monotonic()-start,1)})
  time.sleep(2)
 else:reason='request_or_time_budget_checkpoint'
 write(OUT/'trip_expand_status.json',{'at':utcnow(),'pid':os.getpid(),'running':False,'reason':reason,'requests':c.requests_made,
  'jobs':dict(c.db.execute('SELECT status,count(*) FROM jobs GROUP BY status')),'entities':dict(ix.execute('SELECT status,count(*) FROM entities GROUP BY status'))})
 ix.close();c.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=4000);p.add_argument('--max-hours',type=float,default=12);a=p.parse_args();main(a.max_requests,a.max_hours)
