"""Bounded source-linked restaurant listings; shared source pauses are respected."""
import gzip,json,sqlite3,sys,time,argparse,os,re,hashlib
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
OUT=ROOT/'results/p17_continuous/restaurants';URLROOT='https://www.feinfood.com'
CITIES={'天津','大连','厦门','西安','长沙','郑州'}
def norm(s):return re.sub(r'[^\w\u4e00-\u9fff]','',s).casefold()
def main(max_requests=1500,max_hours=12):
 c=BusinessCrawler(OUT/'crawler',minimum_interval=6);start=time.monotonic();events=[];processed=set()
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
 records=sqlite3.connect(ROOT/pointer['catalog']);lookup={};cities=set()
 for (payload,) in records.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload);cities.add(r['city']);lookup.setdefault((r['city'],norm(r['name'])),[]).append(r['record_id'])
 records.close()
 ix=sqlite3.connect(OUT/'feinfood_entities.sqlite3');ix.executescript('CREATE TABLE IF NOT EXISTS listings(url TEXT,entity_id TEXT,city TEXT,name TEXT,source_url TEXT,raw_sha256 TEXT,dom_text TEXT,detail_url TEXT,PRIMARY KEY(url,entity_id,name)); CREATE TABLE IF NOT EXISTS parsed(url TEXT PRIMARY KEY,raw_sha256 TEXT,result TEXT);')
 def review_pages():
  for url,result in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'"):
   if url in processed:continue
   capture=json.loads(result);soup=BeautifulSoup(gzip.open(capture['raw_file'],'rb').read(),'html.parser');processed.add(url)
   links=[];path=unquote(urlsplit(url).path);city=path.split('/')[3].removesuffix('.xhtml') if len(path.split('/'))>3 else None
   for h in soup.find_all('h2'):
    li=h.find_parent('li');link=h.find_parent('a',href=True)
    if not li or not link or '/restaurant/' not in link['href']:continue
    names=[h.get_text(' ',strip=True)]
    if h.b:names.append(h.b.get_text(strip=True).strip('()（）'))
    names.append(''.join(str(t) for t in h.contents if isinstance(t,str)).strip())
    candidates=set(rid for name in names for rid in lookup.get((city,norm(name)),[]))
    if len(candidates)!=1:continue
    rid=next(iter(candidates));dest=urljoin(url,link['href']);text=li.get_text(' ',strip=True)
    with ix:ix.execute('INSERT OR IGNORE INTO listings VALUES(?,?,?,?,?,?,?,?)',(url,rid,city,h.get_text(' ',strip=True),url,capture['sha256'],text,dest))
    if urlsplit(dest).scheme=='https' and urlsplit(dest).hostname=='www.feinfood.com':links.append({'url':dest,'kind':'restaurant','entity_id':rid})
   with ix:ix.execute('INSERT OR IGNORE INTO parsed VALUES(?,?,?)',(url,capture['sha256'],json.dumps({'city':city,'source_url':url,'retrieved_at':capture['retrieved_at'],'raw_file':capture['raw_file'],'visible_text':soup.get_text(' ',strip=True),'observed_at':None},ensure_ascii=False)))
   # First city list and visible pagination only, bounded to research catalogue cities.
   for a in soup.find_all('a',href=True):
    dest=urljoin(url,a['href']);parts=urlsplit(dest);decoded=unquote(parts.path)
    if parts.netloc!='www.feinfood.com' or not decoded.startswith('/restaurants/中国/'):continue
    city=decoded.removeprefix('/restaurants/中国/').removesuffix('.xhtml')
    if city not in cities:continue
    if not parts.query or a.get_text(strip=True).startswith('下一页'):links.append({'url':dest,'kind':'restaurant'})
   # Continue the observed list frontier, with a finite whole-run request budget.
   existing={x[0] for x in c.db.execute('SELECT url FROM jobs')}
   c.enqueue([x for x in links if x['url'] not in existing][:max(0,max_requests-len(existing))])
 review_pages()
 while time.monotonic()-start<max_hours*3600 and c.requests_made<max_requests:
  shared=sqlite3.connect((ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
  state=shared.execute('SELECT status,reason FROM hosts WHERE host=?',(URLROOT,)).fetchone();shared.close()
  if state and state[0]=='paused':
   events.append({'status':'shared_source_pause','reason':state[1]});break
  if not c.db.execute("SELECT 1 FROM jobs WHERE status='pending'").fetchone():break
  if (OUT/'FEINFOOD_STOP').exists():break
  result=c.run(max_requests=max_requests,max_seconds=12);events.append(result)
  (OUT/'feinfood_progress.json').write_text(json.dumps({'at':result['executed_at'],'requests':c.requests_made,'job_counts':result['job_counts'],'pid':__import__('os').getpid()},indent=2),encoding='utf-8')
  review_pages()
  if c.db.execute("SELECT 1 FROM hosts WHERE status='paused'").fetchone():break
  time.sleep(2)
 summary={'requests':c.requests_made,'elapsed_seconds':round(time.monotonic()-start,2),'events':events,'job_counts':dict(c.db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))}
 (OUT/'feinfood_run.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 pauses=[dict(x) for x in c.db.execute("SELECT host,status,reason FROM hosts WHERE status='paused'")]
 (OUT/'source_pauses.json').write_text(json.dumps({'pauses':pauses},ensure_ascii=False,indent=2),encoding='utf-8');ix.close();c.close();print(json.dumps({k:v for k,v in summary.items() if k!='events'}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--max-requests',type=int,default=1500);a.add_argument('--max-hours',type=float,default=12);v=a.parse_args();main(v.max_requests,v.max_hours)
