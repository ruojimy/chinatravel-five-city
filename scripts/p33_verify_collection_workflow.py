"""Offline verification and a labelled synthetic three-round controller demo."""
import copy,json,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_workflow import aggregate,decide,digest
HOME=ROOT/'collector_agent';OUT=ROOT/'results/p33_collection_workflow_design'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 cfg=read(HOME/'config.json');base=OUT/'verification';base.mkdir(exist_ok=True)
 source_before=sha(ROOT/cfg['catalog']);protected=ROOT/'results/p31_five_city_96/manifest.json'
 p31_before=sha(protected)
 tasks=[];reports=[]
 for uid,level in [('FIX-E','easy'),('FIX-M','medium'),('FIX-H','human')]:
  tasks.append({'uid':uid,'level':level,'synthetic':True,'task_origin':'synthetic_fixture','nature_language':'合成控制面例子，不计真实数据或论文成绩',
   'start_city':'合成城','target_city':'合成城','days':1,'people_number':2,'additional_constraints':[],
   'required_kinds':['accommodation'],'budget_CNY':500})
  reports.append({'uid':uid,'level':level,'city':'合成城','synthetic':True,'required_kinds':['accommodation'],'plan_present':True,
   'required_checks_complete':True,'hard_checks':[{'id':'budget','state':'fail' if level=='medium' else 'pass'}],
   'gaps':[],'planner':{'supported':True,'search_complete':False}})
 reports[0]['gaps']=[{'gap_id':'FIX-G','entity_id':'synthetic-hotel','field':'price','context':{'room':'twin'},'reason':'scope_mismatch',
   'required':True,'blocking':True,'repairable':True,'blocker_class':'data'}]
 example=HOME/'examples';write(example/'tasks.json',tasks)
 history=[]
 for i in range(3):
  rr=copy.deepcopy(reports)
  if i:rr[0]['gaps']=[]
  payload={'synthetic_fixture':True,'coverage_floor_met':True,'reports':rr};write(example/f'round{i}.json',payload)
  metrics=aggregate(rr,freeze_id='synthetic-fixture:'+digest(tasks),policy_id='synthetic-fixture-v1',coverage_floor_met=True)
  history.append(metrics);write(base/f'metrics{i}.json',metrics)
 write(base/'history.json',history);decision=decide(history,cfg['stop']);write(base/'decision.json',decision)
 checks=[]
 def check(name,ok):checks.append({'name':name,'ok':bool(ok)})
 check('round0_has_one_data_block',history[0]['data_blocked']==1)
 check('hard_failure_not_repair_target',all(j['gap']['gap_id']=='FIX-G' for j in history[0]['repair_jobs']))
 check('round2_stable_rotation',decision['action']=='rotate_batch_threshold')
 check('hard_failure_remains_without_forcing_more_collection',history[2]['outcomes'].get('candidate_constraint_fail')==1)
 # Exercise actual CLI freeze + diagnose. Preserve each execution in a new folder.
 demo=base/'cli_demo';n=1
 while demo.exists():demo=base/('cli_demo_'+str(n));n+=1
 demo.mkdir();freeze=demo/'freeze.json';metrics=demo/'metrics.json'
 cli=[sys.executable,str(ROOT/'scripts/collection_agent.py')]
 commands=[cli+['freeze',str(example/'tasks.json'),'--evaluator',str(ROOT/'src/shorttrip/collection_workflow.py'),'--policy-id','synthetic-fixture-v1','--output',str(freeze)],
   cli+['diagnose',str(example/'round0.json'),'--freeze',str(freeze),'--output',str(metrics)]]
 for i,cmd in enumerate(commands):
  p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'})
  (demo/f'command{i}.log').write_text(p.stdout+'\n'+p.stderr,encoding='utf-8');check('cli_'+str(i),p.returncode==0)
 # Same UID/level but altered task body must invalidate the saved freeze.
 original=(example/'tasks.json').read_bytes();changed=copy.deepcopy(tasks);changed[0]['budget_CNY']=999
 write(example/'tasks.json',changed)
 try:
  cmd=cli+['diagnose',str(example/'round0.json'),'--freeze',str(freeze),'--output',str(demo/'should_not_exist.json')]
  p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'})
  check('changed_constraint_same_uid_rejected',p.returncode!=0 and not (demo/'should_not_exist.json').exists())
 finally:(example/'tasks.json').write_bytes(original)
 tests=subprocess.run([sys.executable,str(ROOT/'tests/test_collection_workflow.py')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
 (base/'unit_tests.log').write_text(tests.stdout+'\n'+tests.stderr,encoding='utf-8');check('22_control_plane_tests',tests.returncode==0)
 check('v4_catalog_unchanged',sha(ROOT/cfg['catalog'])==source_before)
 check('p31_archive_manifest_unchanged',sha(protected)==p31_before)
 result={'verified_on':'2026-10-29','checks':checks,'all_passed':all(c['ok'] for c in checks),'synthetic_demo_only':True,
  'new_live_collection_requests':0,'new_official_benchmark_runs':0,'new_rule_planner_runs':0,'scheduled_automation_created':False,
  'demo_outcomes_round2':history[2]['outcomes'],'demo_decision':decision,
  'catalog_sha256':source_before,'p31_manifest_sha256':p31_before}
 write(OUT/'verification.json',result);print(json.dumps(result,ensure_ascii=True))
 if not result['all_passed']:raise SystemExit(1)
if __name__=='__main__':main()
