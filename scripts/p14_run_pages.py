"""Small serial crawler batch; persistent rules, no source resets or bypass."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler,stamp
def main():
    p=argparse.ArgumentParser();p.add_argument('--max-requests',type=int,default=30);p.add_argument('--max-seconds',type=int,default=210)
    a=p.parse_args()
    if not 1<=a.max_requests<=40 or not 1<=a.max_seconds<=300:raise ValueError('Bounded public batch required')
    root=ROOT/'results/p14_targeted_completion/crawler';c=BusinessCrawler(root,minimum_interval=6)
    start=time.monotonic();events=[];last_report=0
    try:
        while c.requests_made<a.max_requests and time.monotonic()-start<a.max_seconds:
            r=c.run(max_requests=a.max_requests,max_seconds=min(20,a.max_seconds-(time.monotonic()-start)))
            events += [x for x in r['events'] if x['status']!='deferred_rate_limit']
            pending=c.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0]
            if c.requests_made>=last_report+5:
                print(json.dumps({'requests':c.requests_made,'pending':pending,'statuses':r['job_counts']}),flush=True);last_report=c.requests_made
            if not pending:break
            if c.db.execute("SELECT count(*) FROM hosts WHERE status='ready'").fetchone()[0]==0:break
            time.sleep(2)
        report={'executed_at':stamp(),'requests':c.requests_made,'events':events,
           'job_counts':dict(c.db.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall()),
           'elapsed_seconds':round(time.monotonic()-start,1),'max_requests':a.max_requests,
           'no_credentials_no_proxy_no_hidden_api':True}
    finally:c.close()
    path=root/('batch_'+report['executed_at'].replace(':','').replace('+','_')+'.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('requests','job_counts','elapsed_seconds')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
