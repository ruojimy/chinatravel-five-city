"""Preserve HTTP hints; register HTTPS transports without certifying operator identity."""
import argparse,hashlib,json,os,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
OUT=ROOT/'results/p17_continuous/restaurants';DATA=OUT/'http_transport_crawler';SHARED=ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3'
def family(host):
 p=host.lower().split('.');return '.'.join(p[-3:] if len(p)>=3 and '.'.join(p[-2:]) in ('com.cn','net.cn','org.cn','co.jp','com.tw','com.hk') else p[-2:])
EXCLUDED_FAMILIES={'amap.com','trip.com','ctrip.com','tripadvisor.com','overturemaps.org','booking.com','qunar.com','elong.com','ly.com',
 'hilton.com','hyatt.com','marriott.com','marriott.com.cn','shangri-la.com','langhamhotels.com','accor.com','accorhotels.com','alltheplaces.xyz',
 'fairmont.com','fairmont.cn','kempinski.com','ihg.com','ihg.com.cn','missionhillschina.com','stregis.com','spg.com',
 'alibaba.com','facebook.com','baidu.com','yahoo.com.hk','skyscrapercenter.com','dianping.com','weibo.cn'}
def main(max_requests,max_seconds):
 OUT.mkdir(parents=True,exist_ok=True);shared=sqlite3.connect(SHARED,timeout=30);links=sqlite3.connect(ROOT/'results/p15_whole_catalog/source_links.sqlite3')
 paused={family(urlsplit(h).hostname or '') for h, in shared.execute("select host from hosts where status='paused'")}
 c=BusinessCrawler(DATA,minimum_interval=6);c.db.execute('CREATE TABLE IF NOT EXISTS transport_hints(entity_id TEXT,original_url TEXT,candidate_url TEXT,city TEXT,role TEXT,PRIMARY KEY(entity_id,original_url))');skipped=[];jobs=[]
 for rid,original,city in links.execute("SELECT entity_id,url,city FROM links WHERE kind='restaurant' AND url LIKE 'http://%'"):
  p=urlsplit(original);base=family(p.hostname or '')
  if base in paused or base in EXCLUDED_FAMILIES or base.endswith(('.edu.cn','.gov.cn','.ac.cn')):
   skipped.append({'entity_id':rid,'original_url':original,'reason':'paused_operator_family_or_other_worker_or_nonvenue_domain'});continue
  candidate=urlunsplit(('https',p.netloc,p.path or '/',p.query,p.fragment))
  if p.username or p.password:continue
  with c.db:c.db.execute('INSERT OR IGNORE INTO transport_hints VALUES(?,?,?,?,?)',(rid,original,candidate,city,'same_host_same_path_transport_candidate_not_original_https_or_verified_operator'))
  jobs.append({'url':candidate,'kind':'restaurant','entity_id':rid})
  # Reuse existing same-host HTTPS rules and timing; a new queue cannot reset source rates.
  old=shared.execute('select * from hosts where host=?',('https://'+p.netloc,)).fetchone()
  if old:
   with c.db:c.db.execute('INSERT OR IGNORE INTO hosts VALUES(?,?,?,?,?,?)',old)
 c.enqueue(jobs);shared.close();links.close();(OUT/'http_transport_seed_audit.json').write_text(json.dumps({'registered_entity_hints':len(jobs),'skipped':skipped,'role':'transport discovery only, not identity verification'},ensure_ascii=False,indent=2),encoding='utf-8')
 started=time.monotonic();events=[]
 while time.monotonic()-started<max_seconds and c.requests_made<max_requests:
  shared=sqlite3.connect(SHARED,timeout=30);paused={family(urlsplit(h).hostname or '') for h, in shared.execute("select host from hosts where status='paused'")}
  # Persist newly signalled family pauses without requesting their candidates.
  for host, in c.db.execute("select host from hosts where status='ready'").fetchall():
   if family(urlsplit(host).hostname or '') in paused:
    with c.db:c.db.execute("update hosts set status='paused',reason='inherited_shared_operator_pause' where host=?",(host,))
  shared.close()
  if (OUT/'HTTP_TRANSPORT_STOP').exists() or not c.db.execute("select 1 from jobs where status='pending'").fetchone():break
  result=c.run(max_requests=max_requests,max_seconds=min(12,max_seconds-(time.monotonic()-started)));events.append(result)
  # New restrictions are shared so another worker cannot switch queues or aliases.
  shared=sqlite3.connect(SHARED,timeout=30)
  for row in c.db.execute("select host,status,last_at,delay,robots,reason from hosts where status='paused'"):
   old=shared.execute('select status,reason from hosts where host=?',(row[0],)).fetchone()
   with shared:
    if not old:shared.execute('insert into hosts values(?,?,?,?,?,?)',tuple(row))
    elif old[0]!='paused':shared.execute("update hosts set status='paused',reason=? where host=?",(row[5],row[0]))
  shared.close()
  (OUT/'http_transport_progress.json').write_text(json.dumps({'at':result['executed_at'],'pid':os.getpid(),'requests_this_run':c.requests_made,'job_counts':result['job_counts']},indent=2),encoding='utf-8')
  time.sleep(1)
 slug=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());report={'requests_this_run':c.requests_made,'elapsed_seconds':time.monotonic()-started,'job_counts':dict(c.db.execute('select status,count(*) from jobs group by status')),'events':events}
 (OUT/('http_transport_run_'+slug+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');c.close();print(json.dumps({k:v for k,v in report.items() if k!='events'}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=200);p.add_argument('--max-seconds',type=int,default=1200);a=p.parse_args();main(a.max_requests,a.max_seconds)
