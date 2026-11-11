"""Follow only already-visible operator pagination and the named target shop map."""
import gzip,hashlib,json,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from p17_restaurant_http_frontier import family
OUT=ROOT/'results/p17_continuous/restaurants';DATA=OUT/'http_transport_crawler'
def main():
 c=BusinessCrawler(DATA,minimum_interval=6);links=[]
 for url,res in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'").fetchall():
  ev=json.loads(res)
  if url not in ['https://www.taotaoju1880.com/about/taotaojumendian','https://www.tongqinglou.cn/tql/index/storedisplay','https://www.bingsheng.com/']:continue
  raw=gzip.open(ev['raw_file'],'rb').read()
  if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Source capture changed')
  soup=BeautifulSoup(raw,'html.parser')
  for a in soup.find_all('a',href=True):
   text=a.get_text(' ',strip=True);dest=urljoin(url,a['href'])
   if urlsplit(dest).hostname!=urlsplit(url).hostname:continue
   if ('taotaoju' in url and text in ['2','3','4','5','6'] and '/about/taotaojumendian?' in dest) or ('tongqinglou' in url and text=='无锡' and '/storedisplay?' in dest):links.append({'url':dest,'from_url':url,'text':text,'parent_sha256':ev['sha256']})
   if 'bingsheng' in url and '/mapOffice_Detail_' in dest:links.append({'url':dest,'from_url':url,'text':text,'parent_sha256':ev['sha256']})
  if 'tongqinglou' in url:
   for div in soup.select('.store-chief'):
    if div.get_text(' ',strip=True)=='同庆楼合肥新站店':
     for a in div.find_all('a',href=True):links.append({'url':urljoin(url,a['href']),'from_url':url,'text':'同庆楼合肥新站店 visible map link','parent_sha256':ev['sha256']})
 label=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());(OUT/('branch_followup_links_'+label+'.json')).write_text(json.dumps(links,ensure_ascii=False,indent=2),encoding='utf-8');c.enqueue([{'url':l['url'],'kind':'restaurant'} for l in links])
 start=time.monotonic();events=[]
 while time.monotonic()-start<180 and c.requests_made<12 and c.db.execute("SELECT 1 FROM jobs WHERE status='pending'").fetchone():
  shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30);paused={family(urlsplit(h).hostname or '') for h, in shared.execute("SELECT host FROM hosts WHERE status='paused'")};shared.close()
  for host, in c.db.execute("SELECT host FROM hosts WHERE status='ready'").fetchall():
   if family(urlsplit(host).hostname or '') in paused:
    with c.db:c.db.execute("UPDATE hosts SET status='paused',reason='inherited_shared_family_pause' WHERE host=?",(host,))
  ev=c.run(max_requests=12,max_seconds=12);events.append(ev)
  shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30)
  for row in c.db.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE status='paused'"):
   old=shared.execute('SELECT status FROM hosts WHERE host=?',(row[0],)).fetchone()
   with shared:
    if not old:shared.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',tuple(row))
    elif old[0]!='paused':shared.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(row[5],row[0]))
  shared.close();time.sleep(2)
 (OUT/('branch_followup_run_'+label+'.json')).write_text(json.dumps({'requests_this_run':c.requests_made,'events':events},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'requests_this_run':c.requests_made,'states':dict(c.db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))}));c.close()
if __name__=='__main__':main()
