"""Whole-catalog inventory and serial API worker, with durable stop/resume state."""
import argparse,hashlib,json,os,sys,time,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.bulk_business import BulkQueue,API_TYPES,assess
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.freshness import utcnow,canonical
from shorttrip.dynamic.opendata import wgs84_to_gcj02
from shorttrip.scoped_business import matching_aliases
RES=ROOT/'results/p15_whole_catalog';CAT=ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3'
OLD=ROOT/'results/p14_targeted_completion/private_api_raw'

def write_status(queue,extra=None):
    status=queue.status();status.update(extra or {})
    tmp=RES/'status.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(RES/'status.json');return status

def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare-only',action='store_true');p.add_argument('--status',action='store_true')
    p.add_argument('--max-calls',type=int,default=60);p.add_argument('--max-seconds',type=int,default=1800)
    p.add_argument('--publish-every',type=int,default=0);a=p.parse_args()
    if not 1<=a.max_calls<=10000 or not 1<=a.max_seconds<=43200:raise ValueError('Explicit finite run budget required')
    RES.mkdir(exist_ok=True);raw=RES/'private_api_raw';raw.mkdir(exist_ok=True)
    q=BulkQueue(RES/'queue.sqlite3');q.seed(CAT,OLD);q.sync_cache(OLD)
    if a.prepare_only or a.status:
        print(json.dumps(write_status(q),ensure_ascii=False));q.close();return
    with q.db:
        for row in q.db.execute("SELECT j.id,e.kind,e.name FROM jobs j JOIN entities e ON e.id=j.entity_id WHERE j.adapter='amap_place' AND j.status='pending'").fetchall():
            priority={'restaurant':1,'attraction':3,'accommodation':5}[row['kind']]+int(not re.search('[\u4e00-\u9fff]',row['name']))
            q.db.execute('UPDATE jobs SET priority=? WHERE id=?',(priority,row['id']))
    lock=RES/'worker.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('Single worker lock exists; inspect PID before any recovery')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    client=LiveAmapClient(ROOT,budget=a.max_calls);start=time.monotonic();run_id=utcnow().replace(':','')
    reason='queue_exhausted';run={'run_id':run_id,'pid':os.getpid(),'started_at':utcnow(),
          'budget':{'max_calls':a.max_calls,'max_seconds':a.max_seconds},'single_key_no_rotation':True}
    def publish():
        import subprocess
        result=subprocess.run([sys.executable,str(ROOT/'scripts/p15_publish_catalog.py')],capture_output=True,text=True,encoding='utf-8')
        (RES/('publish_'+str(client.spent)+'.log')).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Catalog publication failed; inspect saved diagnostic')
    try:
        q.assert_provider_ready()
        for pause in (ROOT/'results/p13_business_completion/AMAP_PAUSED.json',ROOT/'results/p14_targeted_completion/AMAP_PAUSED.json'):
            if pause.exists():q.pause('Inherited provider stop: '+str(pause.relative_to(ROOT)));q.assert_provider_ready()
        # A crash with an uncommitted request is not automatically retried or charged twice.
        if q.db.execute("SELECT 1 FROM jobs WHERE status='inflight'").fetchone():raise RuntimeError('Uncertain inflight request needs audit before resuming')
        while client.spent<a.max_calls and time.monotonic()-start<a.max_seconds:
            if (RES/'STOP').exists():reason='local_stop_requested';break
            job=q.claim_next()
            if not job:break
            target=json.loads(job['target']);key=hashlib.sha256(target['entity_id'].encode()).hexdigest()[:20]
            if len(target['keywords'])>80:
                with q.db:q.db.execute("UPDATE jobs SET status='needs_shorter_grounded_query',finished_at=? WHERE id=?",(utcnow(),job['id']))
                continue
            path=raw/(key+'.json')
            if path.exists():
                packet=json.loads(path.read_text(encoding='utf-8'));q.finish(job,path,assess(packet));continue
            try:
                # City-wide top results often return a far-away chain branch. Prune by
                # the stored public entity location; exact binding rules remain intact.
                lon,lat=wgs84_to_gcj02(target['longitude_wgs84'],target['latitude_wgs84'])
                params={'location':f'{lon:.6f},{lat:.6f}','radius':1000,'sortrule':'distance',
                    'types':API_TYPES[target['kind']],'region':target['city'],'city_limit':'true',
                    'page_num':1,'page_size':10,'show_fields':'business','output':'JSON'}
                # English-only source labels are kept for binding but not imposed on
                # a Chinese map's keyword recall. No model translation is invented.
                hanzi=re.search('[\u4e00-\u9fff]',target['keywords'])
                if hanzi:
                    query=target['keywords'];bilingual=re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'\-]+\s+([\u4e00-\u9fff].*)",query)
                    params['keywords']=bilingual[1] if bilingual else query
                response,meta=client._call('/v5/place/around',params)
            except LiveAmapError as exc:
                reason='provider_stopped';q.pause(str(exc),job);break
            packet={'target':target,'meta':meta,'response':response}
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
            q.finish(job,path,assess(packet))
            write_status(q,{'worker':{**run,'api_calls':client.spent,'elapsed_seconds':round(time.monotonic()-start,1),'running':True}})
            if client.spent%10==0:print(canonical({'calls':client.spent,'kind':target['kind'],'city':target['city']}),flush=True)
            if a.publish_every and client.spent%a.publish_every==0:publish()
            time.sleep(1.5)
        if reason=='queue_exhausted' and q.db.execute("SELECT 1 FROM jobs WHERE adapter='amap_place' AND status='pending'").fetchone():
            reason='finite_run_budget_reached'
        if a.publish_every and client.spent and client.spent%a.publish_every:publish()
    except Exception:
        reason='worker_error_requires_review'
        raise
    finally:
        run.update(finished_at=utcnow(),api_calls=client.spent,reason=reason,
                   elapsed_seconds=round(time.monotonic()-start,1),running=False,audit=client.audit)
        (RES/('run_'+run_id+'.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
        with q.db:q.db.execute('INSERT INTO runs VALUES(?,?)',(run_id,canonical(run)))
        write_status(q,{'worker':{k:v for k,v in run.items() if k!='audit'}})
        q.close();lock.unlink(missing_ok=True)
    print(canonical({k:v for k,v in run.items() if k!='audit'}),flush=True)
if __name__=='__main__':main()
