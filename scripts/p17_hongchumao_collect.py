"""Bounded source form and visible links, never synthetic venue identifiers."""
import argparse,gzip,hashlib,json,os,re,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlencode,parse_qs
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.scoped_business import matching_aliases
OUT=ROOT/'results/p17_continuous/restaurants';HOME='https://www.hongchumao.com';DATA=OUT/'hongchumao_crawler'
def main(max_requests,max_seconds):
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 names={};cities=set()
 for payload, in db.execute("select payload from records where kind='restaurant'"):
  r=json.loads(payload);cities.add(r['city'])
  for a in matching_aliases(r['name']):names.setdefault((r['city'],a),set()).add(r['record_id'])
 db.close();c=BusinessCrawler(DATA,minimum_interval=6);processed=set();started=time.monotonic();events=[]
 ix=sqlite3.connect(OUT/'hongchumao_candidates.sqlite3');ix.execute('CREATE TABLE IF NOT EXISTS candidates(detail_url TEXT, entity_id TEXT,source_name TEXT,source_city TEXT,list_url TEXT,PRIMARY KEY(detail_url,entity_id))')
 def discover():
  for url,result in c.db.execute("select url,result from jobs where status='captured'"):
   if url in processed:continue
   ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read()
   if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Cache changed')
   soup=BeautifulSoup(raw.decode('utf-8'),'html.parser');processed.add(url);new=[]
   if '/restaurant/' in url:continue
   selected_city=parse_qs(urlsplit(url).query).get('city',[None])[0]
   form=soup.find('form',action='/index.php',method='get')
   if form:
    select=form.find('select',attrs={'name':'city'})
    if select:
     for option in select.find_all('option',value=True):
      label=option.get_text(strip=True);base=label.removesuffix('市')
      if base in cities:
       dest=HOME+'/index.php?'+urlencode({'tab':'legacy','city':option['value'],'sort':'default'})
       new.append({'url':dest,'kind':'restaurant'})
   for a in soup.find_all('a',href=True):
    dest=urljoin(url,a['href']);parts=urlsplit(dest)
    if parts.netloc!='www.hongchumao.com':continue
    if '/restaurant/' in parts.path:
     h=a.find('h2')
     if not h:continue
     label=h.get_text(' ',strip=True);base=(selected_city or '').removesuffix('市');found=set()
     if base in cities:
      for alias in matching_aliases(label):found.update(names.get((base,alias),set()))
     # Substring is a discovery lead only; address/branch review happens later.
     if not found and base in cities:
      source_aliases=matching_aliases(label)
      for (candidate_city,alias),rids in names.items():
       if candidate_city!=base or len(alias)<4:continue
       if any(alias in other or other in alias for other in source_aliases if len(other)>=4):found.update(rids)
     if found:
      new.append({'url':dest,'kind':'restaurant','entity_id':next(iter(found)) if len(found)==1 else None})
      with ix:
       for rid in found:ix.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)',(dest,rid,label,base,url))
    elif a.get_text(strip=True)=='下一页' and selected_city and parse_qs(parts.query).get('city')==[selected_city]:
     new.append({'url':dest,'kind':'restaurant'})
   c.enqueue(new)
 discover()
 while time.monotonic()-started<max_seconds and c.requests_made<max_requests:
  shared=sqlite3.connect((ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
  paused=shared.execute("select reason from hosts where host=? and status='paused'",(HOME,)).fetchone();shared.close()
  if paused:break
  if (OUT/'HONGCHUMAO_STOP').exists() or not c.db.execute("select 1 from jobs where status='pending'").fetchone():break
  result=c.run(max_requests=max_requests,max_seconds=min(12,max_seconds-(time.monotonic()-started)));events.append(result)
  (OUT/'hongchumao_progress.json').write_text(json.dumps({'at':result['executed_at'],'pid':os.getpid(),'requests_this_run':c.requests_made,'job_counts':result['job_counts'],'candidate_links':ix.execute('select count(*) from candidates').fetchone()[0]},indent=2),encoding='utf-8')
  discover()
  if c.db.execute("select 1 from hosts where status='paused'").fetchone():break
  time.sleep(2)
 slug=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());report={'events':events,'requests_this_run':c.requests_made,'job_counts':dict(c.db.execute('select status,count(*) from jobs group by status')),'elapsed_seconds':time.monotonic()-started}
 (OUT/('hongchumao_run_'+slug+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 pauses=[dict(x) for x in c.db.execute("select host,status,reason from hosts where status='paused'")]
 (OUT/'hongchumao_source_pauses.json').write_text(json.dumps({'pauses':pauses},ensure_ascii=False,indent=2),encoding='utf-8');c.close();ix.close();print(json.dumps({k:v for k,v in report.items() if k!='events'}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=150);p.add_argument('--max-seconds',type=int,default=1500);a=p.parse_args();main(a.max_requests,a.max_seconds)
