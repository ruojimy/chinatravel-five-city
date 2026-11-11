"""Collect directly visible store/contact/menu links from captured operator candidates."""
import argparse,gzip,hashlib,json,os,re,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urldefrag
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from p17_restaurant_http_frontier import family
OUT=ROOT/'results/p17_continuous/restaurants';DATA=OUT/'http_transport_crawler';SHARED=ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3'
ALLOW={'www.bluefrog.com.cn','www.tongqinglou.cn','www.bingsheng.com','www.taotaoju1880.com','www.thainarak.com','www.mengziyuan.com','www.mcdonalds.com.cn','www.bkchina.cn'}
def main(max_requests,max_seconds):
 c=BusinessCrawler(DATA,minimum_interval=6);started=time.monotonic();links=[];events=[]
 for url,result in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'"):
  if urlsplit(url).hostname not in ALLOW:continue
  ev=json.loads(result);raw=gzip.open(ev['raw_file'],'rb').read()
  if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Existing source changed')
  soup=BeautifulSoup(raw.decode('utf-8'),'html.parser')
  for a in soup.find_all('a',href=True):
   label=a.get_text(' ',strip=True);dest=urldefrag(urljoin(url,a['href']))[0];p=urlsplit(dest)
   if p.hostname!=urlsplit(url).hostname or p.scheme!='https' or p.path=='/' or '/news/' in p.path:continue
   if re.search(r'门店|地址|联系|餐厅|菜单|餐饮|Locations|Near Me|Menu|Contact',label,re.I) or re.search(r'/stores?/?|/shop/?|/locations?/?|/menus?/?|/restaurants?/?',p.path,re.I):
    links.append({'url':dest,'from_url':url,'source_text':label,'from_capture_sha256':ev['sha256'],'role':'visible_same_host_business_link_not_verified_entity'})
 (OUT/('operator_frontier_links_'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'.json')).write_text(json.dumps(links,ensure_ascii=False,indent=2),encoding='utf-8');c.enqueue([{'url':x['url'],'kind':'restaurant'} for x in links])
 while time.monotonic()-started<max_seconds and c.requests_made<max_requests:
  shared=sqlite3.connect(SHARED,timeout=30);paused={family(urlsplit(h).hostname or '') for h, in shared.execute("SELECT host FROM hosts WHERE status='paused'")};shared.close()
  for host, in c.db.execute("SELECT host FROM hosts WHERE status='ready'").fetchall():
   if family(urlsplit(host).hostname or '') in paused:
    with c.db:c.db.execute("UPDATE hosts SET status='paused',reason='inherited_shared_family_pause' WHERE host=?",(host,))
  if not c.db.execute("SELECT 1 FROM jobs WHERE status='pending'").fetchone():break
  result=c.run(max_requests=max_requests,max_seconds=min(12,max_seconds-(time.monotonic()-started)));events.append(result)
  shared=sqlite3.connect(SHARED,timeout=30)
  for row in c.db.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE status='paused'"):
   old=shared.execute('SELECT status FROM hosts WHERE host=?',(row[0],)).fetchone()
   with shared:
    if not old:shared.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',tuple(row))
    elif old[0]!='paused':shared.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(row[5],row[0]))
  shared.close();(OUT/'operator_frontier_progress.json').write_text(json.dumps({'at':result['executed_at'],'pid':os.getpid(),'requests_this_run':c.requests_made,'job_counts':result['job_counts']},indent=2),encoding='utf-8');time.sleep(2)
 slug=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());(OUT/('operator_frontier_run_'+slug+'.json')).write_text(json.dumps({'requests_this_run':c.requests_made,'events':events},ensure_ascii=False,indent=2),encoding='utf-8');c.close();print(json.dumps({'requests':len(events),'requests_this_run':c.requests_made}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=60);p.add_argument('--max-seconds',type=int,default=600);a=p.parse_args();main(a.max_requests,a.max_seconds)
