"""Follow observed room-page links on currently healthy independent operators."""
import gzip,hashlib,json,re,sqlite3,sys
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.freshness import utcnow
ALLOWED={'www.mandarinoriental.com','www.millenniumhotels.com','www.rosewoodhotels.com','www.niccolohotels.com',
 'www.panpacific.com','www.shangri-la.com','www.langhamhotels.com','www.wyndhamhotels.com'}
def main():
 c=BusinessCrawler(ROOT/'results/p15_whole_catalog/web_crawler',minimum_interval=8);links=sqlite3.connect(ROOT/'results/p15_whole_catalog/source_links.sqlite3')
 pauses=[h for h, in c.db.execute("SELECT host FROM hosts WHERE status='paused'")];audit=[]
 for url,result in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'").fetchall():
  host=urlsplit(url).hostname
  if host not in ALLOWED or 'https://'+host in pauses:continue
  # A pause on another hostname of this operator is never bypassed by this seed.
  brand=host.removeprefix('www.')
  if any(urlsplit(h).hostname==brand or (urlsplit(h).hostname or '').endswith('.'+brand) for h in pauses):continue
  parents=links.execute('SELECT entity_id,kind,city,raw_file,raw_line FROM links WHERE url=?',(url,)).fetchall()
  if not parents:continue
  ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read()
  if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Parent source changed')
  soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
  for a in soup.find_all('a',href=True):
   dest=urljoin(url,a['href']);p=urlsplit(dest);label=a.get_text(' ',strip=True)
   if p.scheme!='https' or p.hostname!=host or p.username or p.password:continue
   if not (re.search(r'/(?:rooms?|suites?|accommodations?|guest-rooms?)(?:/|$|\.)',p.path,re.I) or re.search(r'客房|住宿|客室|rooms?\s*(?:and|&|\+)?\s*suites?',label,re.I)):continue
   if re.search(r'/booking/|/reservation|/payment/|/search',p.path,re.I):continue
   for rid,kind,city,rawfile,line in parents:
    with links:links.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?,?,?,?,?)',(rid,dest,kind,city,'observed_operator_room_link',rawfile,line,'reference_pending_property_review'))
    c.enqueue([{'url':dest,'entity_id':rid,'kind':'accommodation'}]);audit.append({'entity_id':rid,'parent_url':url,'parent_sha256':ev['sha256'],'visible_link_label':label,'observed_href':a['href'],'room_url':dest,'identity_verified':False})
 out=ROOT/'results/p17_continuous/operator_room_links.json';out.write_text(json.dumps({'at':utcnow(),'network_calls':0,'links':audit,'no_source_pauses_cleared':True},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'observed_room_links':len(audit),'pending':c.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0]}));links.close();c.close()
if __name__=='__main__':main()
