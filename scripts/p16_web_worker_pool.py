"""Shared-queue worker pool. One owner per hostname, one global finite budget."""
import argparse,concurrent.futures,hashlib,json,os,sqlite3,subprocess,sys,threading,time
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler,LocalCrawlBudget
from shorttrip.freshness import utcnow,canonical
RES=ROOT/'results/p15_whole_catalog';OUT=ROOT/'results/p16_multiworker'

class SharedBudget:
    def __init__(self,requests,seconds,stop_path):
        self.limit=requests;self.deadline=time.monotonic()+seconds;self.stop_path=stop_path
        self.spent=0;self.lock=threading.Lock();self.stop=threading.Event()
    def reserve(self,url):
        with self.lock:
            if self.stop.is_set() or self.stop_path.exists() or self.spent>=self.limit or time.monotonic()>=self.deadline:return False
            self.spent+=1;return True
    def reason(self):
        if self.stop_path.exists():return 'local_stop_requested'
        if time.monotonic()>=self.deadline:return 'finite_time_budget_reached'
        if self.spent>=self.limit:return 'shared_request_budget_reached'
        if self.stop.is_set():return 'coordinator_stop'
        return None

def pool_worker(index,count,budget,states,state_lock,runid):
    crawler=BusinessCrawler(RES/'web_crawler',minimum_interval=8,partition_index=index,
              partition_count=count,request_gate=budget.reserve)
    logfile=OUT/f'worker_{index}_{runid}.jsonl';reason='queue_exhausted';started=time.monotonic()
    try:
        while not budget.reason():
            owned=[url for url, in crawler.db.execute("SELECT url FROM jobs WHERE status='pending'") if crawler.owns_url(url)]
            if not owned:break
            crawler.requests_made=0
            try:report=crawler.run(max_requests=2,max_seconds=25)
            except LocalCrawlBudget:
                reason=budget.reason() or 'local_budget';break
            completed=[x for x in report['events'] if x['status']!='deferred_rate_limit']
            if completed:
                with logfile.open('a',encoding='utf-8') as f:
                    for event in completed:f.write(canonical(event)+'\n')
            with state_lock:
                state=states[index];state.update(at=utcnow(),running=True,
                     requests=state['requests']+report['requests_this_run'],owned_pending=len(owned),
                     completed_events=state['completed_events']+len(completed))
            # Empty/deferred work waits locally without changing the host's source delay.
            if budget.stop.wait(1):break
    except Exception as exc:
        reason='worker_error:'+type(exc).__name__
        with state_lock:states[index]['error']=str(exc)
        budget.stop.set()
        raise
    finally:
        with state_lock:states[index].update(at=utcnow(),running=False,reason=budget.reason() or reason,
              elapsed_seconds=round(time.monotonic()-started,1))
        crawler.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=3)
    p.add_argument('--max-requests',type=int,default=1800);p.add_argument('--max-seconds',type=int,default=10000)
    a=p.parse_args()
    if not 1<=a.workers<=4 or not 1<=a.max_requests<=5000 or not 1<=a.max_seconds<=14400:raise ValueError('Finite small pool budgets required')
    OUT.mkdir(exist_ok=True);lock=RES/'web_worker.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('Previous single worker or pool has not stopped; inspect PID')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    runid=utcnow().replace(':','');start=time.monotonic();states={i:{'worker':i,'requests':0,'completed_events':0,'running':True} for i in range(a.workers)}
    state_lock=threading.Lock();budget=SharedBudget(a.max_requests,a.max_seconds,RES/'STOP')
    db=sqlite3.connect(RES/'web_crawler/queue.sqlite3',timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    initial_counts=dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
    last_publish=initial_counts.get('captured',0);reason='queue_exhausted'
    def status(running=True):
        with state_lock:workers=[dict(v) for v in states.values()]
        hosts={urlsplit(r[0]).hostname for r in db.execute("SELECT url FROM jobs WHERE status='pending'")}
        owners={int(hashlib.sha256(h.encode()).hexdigest(),16)%a.workers for h in hosts}
        s={'at':utcnow(),'pid':os.getpid(),'running':running,'worker_count':a.workers,
          'active_host_partitions':len(owners),'pending_hosts':len(hosts),'workers':workers,
          'requests':budget.spent,'elapsed_seconds':round(time.monotonic()-start,1),'budget':vars(a),
          'job_counts':dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status')),
          'paused_hosts':db.execute("SELECT count(*) FROM hosts WHERE status='paused'").fetchone()[0],
          'same_hostname_concurrency':1,'shared_robots_rate_and_pause_state':True,
          'map_provider_remains_paused':True}
        tmp=RES/'web_status.tmp';tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(RES/'web_status.json')
        (OUT/'pool_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
        return s
    def publish():
        result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/p15_publish_catalog.py')],capture_output=True,text=True,encoding='utf-8')
        (OUT/f'publish_{runid}_{budget.spent}.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Publication failed; retained previous validated snapshot')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers,thread_name_prefix='venue-crawl') as executor:
            futures=[executor.submit(pool_worker,i,a.workers,budget,states,state_lock,runid) for i in range(a.workers)]
            while True:
                s=status();print(canonical(s),flush=True)
                if s['job_counts'].get('captured',0)-last_publish>=100:
                    publish();last_publish=s['job_counts'].get('captured',0)
                if all(f.done() for f in futures):
                    for f in futures:f.result()
                    break
                if budget.reason():budget.stop.set()
                concurrent.futures.wait(futures,timeout=5,return_when=concurrent.futures.ALL_COMPLETED)
        reason=budget.reason() or 'queue_exhausted'
        if dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status')).get('captured',0)>last_publish:publish()
    except Exception:
        reason='pool_error_requires_review';budget.stop.set();raise
    finally:
        final=status(False);final['reason']=reason
        (RES/('web_run_'+runid+'.json')).write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
        (RES/'web_status.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
        (OUT/'pool_status.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
        db.close();lock.unlink(missing_ok=True)
    print(canonical(final),flush=True)
if __name__=='__main__':main()
