"""Serial, provided-URL-only website collection; inherit persistent host stops."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.freshness import utcnow,canonical
RES=ROOT/'results/p15_whole_catalog'
def main():
    p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=60);p.add_argument('--max-seconds',type=int,default=600)
    a=p.parse_args()
    if not 1<=a.max_requests<=5000 or not 1<=a.max_seconds<=14400:raise ValueError('Finite collection budget required')
    lock=RES/'web_worker.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('A website worker lock exists; inspect before recovery')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    crawler=BusinessCrawler(RES/'web_crawler',minimum_interval=8);start=time.monotonic();runid=utcnow().replace(':','')
    requests=0;events=0;reason='queue_exhausted'
    try:
        while requests<a.max_requests and time.monotonic()-start<a.max_seconds:
            if (RES/'STOP').exists():reason='local_stop_requested';break
            left=crawler.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0]
            if not left:break
            # Small request slices let eligible pages load before checking more hosts.
            crawler.requests_made=0
            report=crawler.run(max_requests=min(2,a.max_requests-requests),max_seconds=min(25,a.max_seconds-(time.monotonic()-start)))
            requests+=report['requests_this_run'];events+=len(report['events'])
            for event in report['events']:
                if event['status']=='deferred_rate_limit':continue
                with (RES/'web_events.jsonl').open('a',encoding='utf-8') as f:f.write(canonical(event)+'\n')
            status={'at':utcnow(),'pid':os.getpid(),'running':True,'requests':requests,
                    'elapsed_seconds':round(time.monotonic()-start,1),
                    'job_counts':dict(crawler.db.execute('SELECT status,count(*) FROM jobs GROUP BY status')),
                    'paused_hosts':crawler.db.execute("SELECT count(*) FROM hosts WHERE status='paused'").fetchone()[0],
                    'budget':vars(a),'no_recursive_crawl':True,'source_link_is_not_identity_proof':True}
            tmp=RES/'web_status.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(RES/'web_status.json')
            print(canonical(status),flush=True)
            time.sleep(2)
        if left and reason=='queue_exhausted':reason='finite_run_budget_reached'
    except Exception:
        reason='worker_error_requires_review';raise
    finally:
        final={'at':utcnow(),'pid':os.getpid(),'running':False,'requests':requests,'reason':reason,
             'elapsed_seconds':round(time.monotonic()-start,1),
             'job_counts':dict(crawler.db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))}
        (RES/('web_run_'+runid+'.json')).write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
        (RES/'web_status.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
        crawler.close();lock.unlink(missing_ok=True)
    print(canonical(final),flush=True)
if __name__=='__main__':main()
