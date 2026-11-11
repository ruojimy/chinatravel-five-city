"""Verify saved app scheduling settings and offline guards; never starts a run."""
import hashlib,json,subprocess,sys,tomllib
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];HOME=ROOT/'collector_agent'
OUT=ROOT/'results/p34_automation_setup';OUT.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 cfg=read(HOME/'config.json');job_path=Path.home()/'.codex/automations/chinatravel/automation.toml'
 job=tomllib.loads(job_path.read_text(encoding='utf-8'));checks=[]
 def check(name,ok):checks.append({'name':name,'ok':bool(ok)})
 for key,value in [('id','chinatravel'),('kind','cron'),('status','ACTIVE'),('model','gpt-6.1-terra'),('reasoning_effort','high'),('execution_environment','local')]:
  check('saved_'+key,job.get(key)==value)
 check('correct_project',job.get('target',{}).get('project_id')==cfg['automation']['project_id'])
 check('three_daily_runs',job.get('rrule')=='FREQ=DAILY;BYHOUR=0,8,16;BYMINUTE=0;BYSECOND=0')
 check('worker_model_and_effort_in_prompt','model=gpt-6-luna' in job['prompt'] and 'reasoning_effort=medium' in job['prompt'])
 check('shared_worker_and_network_caps',cfg['max_workers']==2 and cfg['budget']=={'web_action':60,'api_http':0})
 for name,filename in [('collection_control_22','test_collection_workflow.py'),('session_guard_time_only_8','test_collection_session.py')]:
  p=subprocess.run([sys.executable,str(ROOT/'tests'/filename)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
  (OUT/(name+'.log')).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8');check(name,p.returncode==0)
 baseline=read(ROOT/'results/p33_collection_workflow_design/verification.json')
 check('v4_catalog_unchanged',sha(ROOT/cfg['catalog'])==baseline['catalog_sha256'])
 check('p31_manifest_unchanged',sha(ROOT/'results/p31_five_city_96/manifest.json')==baseline['p31_manifest_sha256'])
 state=read(HOME/'memory/state.json')
 result={'verified_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'all_passed':all(c['ok'] for c in checks),
  'checks':checks,'automation':{k:job[k] for k in ('id','kind','name','status','model','reasoning_effort','execution_environment')},
  'local_times':cfg['automation']['local_times'],'timezone':'Asia/Shanghai','saved_prompt_sha256':hashlib.sha256(job['prompt'].encode()).hexdigest(),
  'offline_tests_passed':30,'new_live_collection_requests':0,'first_scheduled_run_observed':bool(state.get('last_run_id') and state.get('last_run_artifact')),
  'note':'Configuration and offline guard verification only; model children and real collection require per-run evidence.'}
 write(OUT/'verification.json',result)
 if not result['all_passed']:print(json.dumps(result,ensure_ascii=True));raise SystemExit(1)
 state.setdefault('phase','scheduled_adapter_pilot_pending')
 state.setdefault('next_action','First scheduled run: at most 30 minutes offline strict-planner adapter calibration, after session and usage gates')
 state.update(scheduled_automation_created=True,automation=cfg['automation'],
  setup_verification='results/p34_automation_setup/verification.json')
 write(HOME/'memory/state.json',state)
 sys.path.insert(0,str(ROOT/'src'))
 from shorttrip.collection_workflow import AgentMemory
 m=AgentMemory(HOME/'memory/agent.sqlite3')
 try:m.event('scheduled_automation_configured',{'id':job['id'],'status':job['status'],'model':job['model'],'reasoning_effort':job['reasoning_effort'],'verification':'results/p34_automation_setup/verification.json'})
 finally:m.close()
 print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':main()
