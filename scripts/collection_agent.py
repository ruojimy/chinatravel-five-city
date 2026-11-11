"""Project collection-agent memory/queue CLI. Every command is offline."""
from __future__ import annotations
import argparse,ast,collections,hashlib,json,re,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_workflow import AgentMemory,aggregate,decide,family_of,stamp,digest
from shorttrip.collection_task_schema import validate_cohort
from shorttrip.strict_cohort_preflight import validate_freeze_readiness
HOME=ROOT/'collector_agent';MEM=HOME/'memory';RESULTS=ROOT/'results/p33_collection_workflow_design'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def reference_context(args):
 if not args.reference_only:return None
 cfg=read(HOME/'config.json')
 if cfg.get('mode')!='collection_static_reference' or cfg.get('public_web_reference_reads') is not True:
  raise ValueError('Public Web reference reading is not enabled in this project mode')
 return {'tool':'web.search_query' if args.action=='search' else 'web.open',
  'query':args.query,'discovery_only':args.action=='search'}
def seeded_profile(s,domain):
 fields=(s.get('field_capabilities') or {}).get('candidate_or_reference_only',[])
 return {**s,'family':family_of(domain),'status':'paused' if s.get('access_state')=='paused' else 'unknown',
  'domains':[domain],'supports':fields,'pause_evidence':s.get('access_evidence',[]) if s.get('access_state')=='paused' else [],
  'min_interval_seconds':5,'preflight_required':True,'network_permission_is_not_claim_acceptance':True}

def sync_legacy_pauses(m):
 for p in [ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3']:
  db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
  for host,status,reason in db.execute('select host,status,reason from hosts'):
   if status=='paused':m.merge_source({'family':family_of(host),'status':'paused','pause_evidence':[str(p.relative_to(ROOT))+':'+host], 'last_pause_reason':reason})
  db.close()
 pausetxt=ROOT/'results/p30_five_city_fill/paused_hosts_r3.txt'
 ignored=[]
 for token in ast.literal_eval(pausetxt.read_text(encoding='utf-8')):
  # Annotation in an old report is retained; it cannot become a malformed host.
  clean=token.split(' ')[0]
  if '.' not in clean:ignored.append(token);continue
  m.merge_source({'family':family_of(clean),'status':'paused','pause_evidence':[str(pausetxt.relative_to(ROOT))+':'+token],
    'last_pause_reason':'inherited_p30_pause_scope_review_required'})
 state=read(ROOT/'current_retrieval_state.json')
 for url in state.get('new_paused_urls',[]):m.merge_source({'family':family_of(url),'status':'paused','pause_evidence':['current_retrieval_state.json:'+url]})
 # The old P27 allow-call record predates the new P29 failure. Never let it
 # overwrite the later circuit breaker. There is no automatic unpause command.
 amap=ROOT/'results/p29_five_city_completion/capture/amap_ledger.json'
 if read(amap).get('stopped'):m.merge_source({'family':'amap','status':'paused','pause_evidence':[str(amap.relative_to(ROOT))],'last_pause_reason':'provider_10021'})
 return ignored

def bootstrap(m):
 cfg=read(HOME/'config.json');catalog=ROOT/cfg['catalog'];manifest=read(ROOT/cfg['manifest'])
 actual=sha(catalog);expected=manifest['files'].get('catalog.sqlite3')
 if actual!=expected:raise ValueError('Configured catalogue SHA differs from manifest')
 seed=read(RESULTS/'seed_sources.json')
 if seed['basis']['catalog_sha256']!=actual:raise ValueError('Seed registry refers to a different catalogue')
 for s in seed['sources']:
  for domain in s['domains']:m.merge_source(seeded_profile(s,domain))
 ignored=sync_legacy_pauses(m)
 for line in (MEM/'lessons.jsonl').read_text(encoding='utf-8').splitlines():
  if line.strip():m.add_lesson(json.loads(line))
 write(MEM/'sources_snapshot.json',{'reviewed_on':cfg['reviewed_on'],'sources':m.export_sources(),'ignored_legacy_tokens':ignored,
   'note':'Historical observations. No live accessibility test or automatic permission upgrade.'})
 db=sqlite3.connect(catalog.as_uri()+'?mode=ro',uri=True)
 counts=[{'city':c,'kind':k,'records':n} for c,k,n in db.execute('select city,kind,count(*) from records group by city,kind')]
 db.close()
 baseline={'catalog':cfg['catalog'],'catalog_sha256':actual,'manifest_verified':True,'manifest_validation':manifest['validation'],
   'coverage_by_city_kind':counts,'source_seed_groups':len(seed['sources']),'runtime_source_families':len(m.export_sources()),
   'live_network_requests_this_turn':0,'legacy_p31_labels':read(ROOT/'results/p31_five_city_96/summary_all_96.json')['status_total'],
   'legacy_labels_recertified':False,'mode':cfg['mode']}
 write(RESULTS/'baseline_verified.json',baseline)
 initial={'phase':'control_plane_ready','initialized_at':stamp(),'active_catalog':cfg['catalog'],'active_catalog_sha256':actual,
   'live_collection_started':False,'scheduled_automation_created':False,'next_action':'freeze a bounded cohort then diagnose with an adapted planner',
   'blocked_old_adapter':'P31 diagnostics require explicit policy/field gates; do not launch p31_retrieve as a shortcut'}
 prior=read(MEM/'state.json') if (MEM/'state.json').exists() else initial
 if prior.get('active_catalog_sha256')!=actual:raise ValueError('Active catalogue changed; review the checkpoint instead of resetting it')
 # Startup refreshes provenance without erasing an in-flight batch or claiming
 # that previously started live work never happened.
 write(MEM/'state.json',{**prior,'last_bootstrapped_at':stamp()})
 m.event('bootstrap_verified',{'catalog_sha256':actual,'checkpoint_preserved':True})
 return {'memory_database':str(m.path),'source_families':len(m.export_sources()),'catalog_hash_verified':True,'live_requests':0}

def main():
 ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='cmd',required=True)
 sub.add_parser('bootstrap');sub.add_parser('sources')
 p=sub.add_parser('recall');p.add_argument('term')
 p=sub.add_parser('check-source');p.add_argument('url');p.add_argument('--field');p.add_argument('--action',default='fetch',choices=['fetch','api','search','robots'])
 p.add_argument('--reference-only',action='store_true');p.add_argument('--query')
 p=sub.add_parser('begin-run');p.add_argument('run_id')
 p=sub.add_parser('reserve');p.add_argument('run_id');p.add_argument('request_id');p.add_argument('url');p.add_argument('--channel',required=True,choices=['web_action','api_http']);p.add_argument('--field');p.add_argument('--action',default='fetch')
 p.add_argument('--reference-only',action='store_true');p.add_argument('--query')
 p=sub.add_parser('finish');p.add_argument('request_id');p.add_argument('status');p.add_argument('--evidence-file');p.add_argument('--error')
 p=sub.add_parser('register-source');p.add_argument('profile')
 p=sub.add_parser('validate-tasks');p.add_argument('tasks')
 p=sub.add_parser('freeze');p.add_argument('tasks');p.add_argument('--evaluator',action='append',required=True);p.add_argument('--policy-id',required=True);p.add_argument('--output',required=True)
 p=sub.add_parser('diagnose');p.add_argument('input');p.add_argument('--freeze',required=True);p.add_argument('--output',required=True)
 p=sub.add_parser('decide');p.add_argument('history');p.add_argument('--output',required=True)
 args=ap.parse_args();sys.stdout.reconfigure(encoding='utf-8')
 m=AgentMemory(MEM/'agent.sqlite3')
 try:
  if args.cmd=='bootstrap':result=bootstrap(m)
  elif args.cmd=='sources':result=m.export_sources()
  elif args.cmd=='recall':result=m.recall(args.term)
  elif args.cmd=='check-source':
   sync_legacy_pauses(m);context=reference_context(args)
   result=(m.reference_access_check(args.url,args.field,args.action,context=context)
    if args.reference_only else m.source_check(args.url,args.field,args.action))
  elif args.cmd=='begin-run':m.begin_run(args.run_id,read(HOME/'config.json')['budget']);result={'run_id':args.run_id,'network_called':False}
  elif args.cmd=='reserve':
   sync_legacy_pauses(m);context=reference_context(args)
   result=m.reserve(args.run_id,args.request_id,args.url,args.channel,field=args.field,action=args.action,context=context,reference_only=args.reference_only)
  elif args.cmd=='finish':m.finish(args.request_id,args.status,evidence_file=args.evidence_file,error=args.error);result={'recorded':True}
  elif args.cmd=='register-source':
   profile=read(args.profile);review=profile.get('access_review',{})
   # Hashes only establish byte consistency, not that robots or terms permit
   # collection. Until an independently anchored policy-review verifier is
   # integrated, a registration may preserve a pending profile but cannot
   # manufacture the accessible state from caller-provided flags or files.
   if profile.get('status','unknown') not in ('unknown','paused') or profile.get('live_fetch_authorized') not in (None,False):
    raise ValueError('Source access review verifier unavailable; accessible registration is blocked')
   if not profile.get('supports') or not profile.get('domains'):raise ValueError('Field capabilities and exact domains required')
   for key in ('robots_artifact','terms_review_artifact'):
    artifact=review.get(key,{})
    if not artifact.get('path') or sha(ROOT/artifact['path'])!=artifact.get('sha256'):raise ValueError('Missing or changed policy artifact: '+key)
   if any(family_of(domain)!=profile['family'] for domain in profile['domains']):raise ValueError('All domains must match the declared family')
   profile['status']=profile.get('status','unknown')
   profile['live_fetch_authorized']=False
   profile['preflight_required']=True
   m.merge_source(profile);result=m.source_check(profile['domains'][0],profile['supports'][0])
  elif args.cmd=='validate-tasks':result=validate_cohort(read(args.tasks))
  elif args.cmd=='freeze':
   tasks=read(args.tasks);keys=sorted((t['level'],t['uid']) for t in tasks)
   if len(set(keys))!=len(keys) or any(k[0] not in ('easy','medium','human') for k in keys):raise ValueError('Duplicate or noncanonical task keys')
   fixture=bool(tasks) and all(t.get('task_origin')=='synthetic_fixture' for t in tasks)
   if not fixture:validate_freeze_readiness(tasks)
   capsule={'task_file':str(Path(args.tasks).resolve()),'task_spec_sha256':sha(args.tasks),'task_keys_sha256':digest(keys),
    'task_count':len(tasks),'synthetic_fixture':fixture,'policy_id':args.policy_id,'config_sha256':sha(HOME/'config.json'),
    'evaluators':{str(Path(p).resolve()):sha(p) for p in args.evaluator}}
   capsule['freeze_id']=digest(capsule)
   if Path(args.output).exists():raise FileExistsError('Preserve frozen cohort')
   write(args.output,capsule);m.event('cohort_frozen',capsule);result=capsule
  elif args.cmd=='diagnose':
   freeze=read(args.freeze);fid=freeze.pop('freeze_id')
   if digest(freeze)!=fid or sha(freeze['task_file'])!=freeze['task_spec_sha256']:raise ValueError('Task freeze changed')
   if sha(HOME/'config.json')!=freeze['config_sha256']:raise ValueError('Config changed; register a new experiment instead of comparing rounds')
   if any(sha(p)!=h for p,h in freeze['evaluators'].items()):raise ValueError('Evaluator changed; cannot compare under old freeze')
   payload=read(args.input);result=aggregate(payload['reports'],freeze_id=fid,policy_id=freeze['policy_id'],coverage_floor_met=payload.get('coverage_floor_met',False))
   if result['task_keys_sha256']!=freeze['task_keys_sha256'] or result['tasks']!=freeze['task_count']:raise ValueError('Missing or extra tasks in diagnosis')
   if Path(args.output).exists():raise FileExistsError('Preserve round diagnosis')
   write(args.output,result)
  else:result=decide(read(args.history),read(HOME/'config.json')['stop']);write(args.output,result)
  print(json.dumps(result,ensure_ascii=False,indent=2))
 finally:m.close()
if __name__=='__main__':main()
