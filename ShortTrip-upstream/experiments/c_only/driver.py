"""Three-worker bounded process coordinator; never retries a paid run silently."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import json,os,subprocess,sys,time

ROOT=Path(__file__).resolve().parent

def read(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def write(path,data):
    from worker import save
    save(path,data)

def stop_tree(process):
    # A Windows venv executable can spawn a second interpreter: stop both.
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:process.kill()
    process.wait(timeout=20)

def finalize(case):
    from worker import evaluate,save
    from rules import audit
    manifest=read(ROOT/'manifest.json')
    entry=next(c for c in manifest['cases'] if c['case']==case)
    status=read(ROOT/'status'/f'{case}.json',dict(case=case,group=entry['group'],base_case=entry['base_case'],repetition=entry['repetition']))
    candidates=read(ROOT/'candidates'/f'{case}.json',[])
    if candidates:
        best=min(candidates,key=lambda c:(c['score']['total_penalty'],c['ordinal']))
        selected=best['plan']
        save(ROOT/'results'/f'{case}.json',selected)
        save(ROOT/'selection'/f'{case}.json',dict(candidate_target=20,candidate_count=len(candidates),complete=len(candidates)==20,stop_reason='external_wall_limit',selected_ordinal=best['ordinal'],minimum_penalty=best['score']['total_penalty']))
        query=read(ROOT/entry['query'])
        status['evaluation']=evaluate(case,query,selected)
        status['new_rule_audit']=audit(selected,query['days'])
        status['combined_pass']=bool(status['evaluation'].get('all_pass') and status['new_rule_audit'].get('all_pass'))
    status.update(state='timed_out_with_candidates' if candidates else 'timed_out_no_candidates',candidate_count=len(candidates),stop_reason='external_wall_limit',finished_at=datetime.now(timezone.utc).isoformat())
    save(ROOT/'status'/f'{case}.json',status)

def main():
    if '--finalize' in sys.argv:
        finalize(sys.argv[-1]);return
    manifest=read(ROOT/'manifest.json')
    config=read(ROOT/'config.json')
    (ROOT/'logs').mkdir(exist_ok=True)
    active={}
    def launch(entry):
        case=entry['case']
        if (ROOT/'status'/f'{case}.json').exists() or (ROOT/'traces'/f'{case}.jsonl').exists():
            print(f'{case}: existing artifacts; not rerunning',flush=True)
            return case,{'exit':'preserved'}
        print(f'{case}: starting',flush=True)
        started=time.monotonic()
        with (ROOT/'logs'/f'{case}.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-B','-X','utf8',str(ROOT/'worker.py'),'--case',case],cwd=manifest['project'],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',PYTHONUTF8='1',PYTHONUNBUFFERED='1'))
            active[case]=process
            try:
                code=process.wait(timeout=manifest['wall_seconds'])
            except subprocess.TimeoutExpired:
                stop_tree(process)
                code='wall_timeout'
                with (ROOT/'logs'/f'{case}.finalize.log').open('w',encoding='utf-8') as final_log:
                    subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'driver.py'),'--finalize',case],cwd=manifest['project'],stdout=final_log,stderr=subprocess.STDOUT,timeout=120)
            finally:active.pop(case,None)
        status=read(ROOT/'status'/f'{case}.json',{})
        if status.get('state') in {None,'running'}:
            status.update(case=case,group=entry['group'],base_case=entry['base_case'],repetition=entry['repetition'],state='failed',error_type='WorkerExitedWithoutFinalStatus',finished_at=datetime.now(timezone.utc).isoformat())
            write(ROOT/'status'/f'{case}.json',status)
        print(f'{case}: finished {code}',flush=True)
        return case,dict(exit=code,elapsed_seconds=time.monotonic()-started)
    exits={}
    with ThreadPoolExecutor(max_workers=config['workers']) as executor:
        futures=[executor.submit(launch,entry) for entry in manifest['cases']]
        try:
            for future in as_completed(futures):
                try:
                    case,result=future.result()
                    exits[case]=result
                    write(ROOT/'process_exits.json',exits)
                    subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'report.py')],cwd=manifest['project'],stdout=subprocess.DEVNULL,timeout=120)
                except Exception as exc:
                    print('Coordinator error: '+repr(exc),flush=True)
        except KeyboardInterrupt:
            for process in list(active.values()):stop_tree(process)
            for future in futures:future.cancel()
            raise
    subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'report.py')],cwd=manifest['project'],check=True)

if __name__=='__main__':
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    if not kernel.SetThreadExecutionState(0x80000001):raise ctypes.WinError(ctypes.get_last_error())
    try:main()
    finally:kernel.SetThreadExecutionState(0x80000000)
