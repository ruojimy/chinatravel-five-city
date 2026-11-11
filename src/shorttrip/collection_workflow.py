"""Offline control plane for an agent-operated collection/diagnosis loop.

No fetcher, arbitrary-code execution, LLM API, or implicit source recovery.
The agent performs collection with existing tools after reserving shared budget.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from .strict_source_access import _https_url

VERSION='collection-loop-v1'
DATA_REASONS={'missing_value','missing_evidence','identity_unresolved','scope_mismatch',
 'source_time_unknown','expired','conflicting_sources','unit_unknown','coordinate_system_unknown',
 'licence_unresolved','candidate_coverage_gap','unsupported_quote','tag_unverified'}
BLOCK_CLASSES={'data','context','access','adapter','solver','pipeline'}
FAMILIES={
 'trip_group':('ctrip.com','trip.com','c-ctrip.com'),
 'wikidata':('wikidata.org',),
 'osm_services':('openstreetmap.org','overpass-api.de','overpass.kumi.systems'),
 'amap':('amap.com',),
 'baidu':('baidu.com',),
}

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def host_of(url):
 h=urlsplit(url if '://' in url else 'https://'+url).hostname
 if not h or ' ' in h:raise ValueError('An exact host or URL is required')
 return h.lower().rstrip('.')
def family_of(url):
 h=host_of(url)
 for family,domains in FAMILIES.items():
  if any(h==d or h.endswith('.'+d) for d in domains):return family
 parts=h.split('.')
 public_second_level={'com.cn','org.cn','net.cn','gov.cn','edu.cn','co.uk','com.tw'}
 n=3 if '.'.join(parts[-2:]) in public_second_level else 2
 return '.'.join(parts[-n:])

def _connection_failure_detail(error):
 if not isinstance(error,str):return False
 detail=error.casefold()
 markers=(
  'connectionerror','connectionreseterror','connectionrefusederror','connectionabortederror',
  'connection error','connection reset','reset by peer','connection refused','connection aborted',
  'connection timed out','connect timeout','socket.timeout','timeouterror','read timed out',
  'failed to establish a new connection','max retries exceeded with url','newconnectionerror',
  'name or service not known','name resolution','getaddrinfo failed','dns lookup',
  'network is unreachable','network unreachable','remote end closed connection',
  'tls handshake','ssl handshake',
  'remote disconnected','forcibly closed','连接重置','连接被拒绝','连接超时','连接失败','连接异常',
  '域名解析失败','网络不可达','远端关闭连接',
 )
 return any(marker in detail for marker in markers)

def classify(report,*,proof_verifier=None):
 """Multi-axis diagnosis. Legacy status strings never establish completion."""
 if not report.get('uid') or report.get('level') not in ('easy','medium','human'):
  raise ValueError('uid and canonical easy/medium/human level required')
 axes={k:[] for k in BLOCK_CLASSES}
 for gap in report.get('gaps',[]):
  if gap.get('blocking') is not True or gap.get('required') is not True:continue
  cls=gap.get('blocker_class')
  if cls not in BLOCK_CLASSES:raise ValueError('Explicit blocker_class required')
  if not gap.get('gap_id') or not gap.get('reason'):raise ValueError('A gap needs id and reason')
  axes[cls].append(gap)
 checks=report.get('hard_checks',[])
 failures=[c for c in checks if c.get('state')=='fail']
 unknowns=[c for c in checks if c.get('state')=='unknown']
 planner=report.get('planner',{})
 if planner.get('error'):axes['pipeline'].append({'reason':str(planner['error'])})
 if planner.get('supported') is False:axes['adapter'].append({'reason':'planner_feature_unsupported'})
 # Unknown hard checks without an explicit data dependency are not a mandate
 # to scrape: they need diagnosis by the planner/adapter owner.
 if unknowns and not any(axes.values()):axes['solver'].append({'reason':'unexplained_unknown_checks'})
 proof=planner.get('infeasibility_proof') or {}
 certificate_reported=(planner.get('search_complete') is True and proof.get('validated') is True
         and proof.get('scope') in ('logical_contradiction','frozen_candidate_universe')
         and bool(proof.get('artifact_sha256')) and bool(proof.get('artifact_path'))
         and not any(axes.values()))
 proven=certificate_reported and callable(proof_verifier) and proof_verifier(proof,report) is True
 if axes['pipeline']:outcome='pipeline_error'
 elif axes['context']:outcome='context_block'
 elif axes['data']:outcome='data_block'
 elif axes['access']:outcome='source_block'
 elif axes['adapter']:outcome='adapter_block'
 elif axes['solver']:outcome='solver_incomplete'
 elif proven:outcome='infeasible_proven'
 elif certificate_reported:outcome='solver_incomplete'
 elif failures:outcome='candidate_constraint_fail'
 elif (report.get('plan_present') is True and report.get('required_checks_complete') is True
       and planner.get('supported') is True and checks and all(c.get('state')=='pass' for c in checks)):
  outcome='complete_under_declared_policy'
 else:outcome='solver_incomplete'
 repair=[]
 for g in axes['data']:
  # Runtime weather/route refresh cannot make a static catalogue permanently
  # complete. Keep it in diagnostics but route it to a separate runtime queue.
  if g.get('repairable') is True and g.get('lifecycle','static')=='static':repair.append(g)
 return {'schema_version':VERSION,'uid':report['uid'],'level':report['level'],
  'city':report.get('city','unknown'),'outcome':outcome,'axes':axes,
  'hard_failures':failures,'unknown_checks':unknowns,
  'passed_checks':[c for c in checks if c.get('state')=='pass'],'repair_queue':repair,
  'execution_confirmed':False,'proof_verified_by_controller':bool(proven),
  'infeasibility_certificate_pending':bool(certificate_reported and not proven)}

def aggregate(reports,*,freeze_id,policy_id,coverage_floor_met=False):
 if not reports:raise ValueError('An empty task batch cannot meet a threshold')
 diagnoses=[classify(r) for r in reports]
 keys=[(d['level'],d['uid']) for d in diagnoses]
 if len(set(keys))!=len(keys):raise ValueError('Duplicate (level,uid) task key')
 strata={};counts={};gapmap={};n=len(diagnoses)
 for d,original in zip(diagnoses,reports):
  counts[d['outcome']]=counts.get(d['outcome'],0)+1
  keys_to_count=[d['city']+'|'+d['level']]
  keys_to_count += [d['city']+'|kind:'+k for k in sorted(set(original.get('required_kinds',[])))]
  for key in keys_to_count:
   s=strata.setdefault(key,{'tasks':0,'data_blocked':0});s['tasks']+=1;s['data_blocked']+=bool(d['axes']['data'])
  for g in d['repair_queue']:
   # Same entity+field+scope reused by ten queries is one repair job, not ten.
   if not g.get('entity_id') or not g.get('field'):raise ValueError('Repair jobs require an entity and field')
   k=digest([g['entity_id'],g['field'],g.get('context',{}),g.get('evidence_policy',policy_id)])
   v=gapmap.setdefault(k,{'gap':g,'reasons':[],'gap_ids':[],'affected_tasks':[]})
   for name,value in [('reasons',g['reason']),('gap_ids',g['gap_id']),('affected_tasks',[d['level'],d['uid']])]:
    if value not in v[name]:v[name].append(value)
 for s in strata.values():s['data_block_rate']=s['data_blocked']/s['tasks']
 blocked=sum(bool(d['axes']['data']) for d in diagnoses)
 metrics={'freeze_id':freeze_id,'policy_id':policy_id,'task_keys_sha256':digest(sorted(keys)),
  'tasks':n,'outcomes':counts,'data_blocked':blocked,'data_block_rate':blocked/n,
  'unique_repair_jobs':len(gapmap),'coverage_floor_met':coverage_floor_met,'strata':strata,
  'pipeline_errors':counts.get('pipeline_error',0),'diagnoses':diagnoses,
  'repair_jobs':sorted(gapmap.values(),key=lambda x:len(x['affected_tasks']),reverse=True)}
 return metrics

def decide(history,config):
 if not history:raise ValueError('At least one frozen evaluation required')
 last=history[-1]
 for m in history:
  for k in ('freeze_id','policy_id','task_keys_sha256','tasks'):
   if m[k]!=last[k]:raise ValueError('Changed evaluation denominator/policy: '+k)
 if last.get('pipeline_errors',0):action,why='repair_pipeline','pipeline errors must not drive collection'
 else:
  stable=config['stable_rounds'];recent=history[-stable:]
  threshold=(len(recent)==stable and all(m['data_block_rate']<=config['global_block_rate'] and
    m['coverage_floor_met'] is True and m['strata'] and all(s['data_block_rate']<=config['stratum_block_rate'] for s in m['strata'].values()) for m in recent))
  plateau=(len(history)>=stable+1 and all(0<=history[i-1]['data_block_rate']-history[i]['data_block_rate']<config['min_block_rate_gain'] for i in range(len(history)-stable,len(history))))
  if threshold:action,why='rotate_batch_threshold','stable global and per-stratum thresholds with coverage floor'
  elif not last['unique_repair_jobs']:action,why='rotate_batch_saturated','no actionable static jobs; residual blocks remain unresolved'
  elif plateau:action,why='rotate_batch_saturated','marginal gain below policy; preserve residual queue'
  elif len(history)-1>=config['max_repair_rounds']:action,why='rotate_batch_budget','repair round cap reached; incomplete'
  else:action,why='targeted_repair','prioritize shared blockers with suitable accessible sources'
 return {'action':action,'reason':why,'full_dataset_complete':False,'residual_data_blocked':last['data_blocked'],
  'frozen_tasks':last['tasks'],'freeze_id':last['freeze_id']}

class AgentMemory:
 """Durable project memory and atomic global budget shared by all workers."""
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
  self.db.row_factory=sqlite3.Row
  self.db.executescript('''
  PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,payload TEXT);
  CREATE TABLE IF NOT EXISTS sources(family TEXT PRIMARY KEY,status TEXT,payload TEXT);
  CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,budget TEXT);
  CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,run_id TEXT,family TEXT,channel TEXT,status TEXT,payload TEXT);
  CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY,topic TEXT,text TEXT,evidence TEXT);
  ''')
 def close(self):self.db.close()
 def event(self,kind,payload):
  self.db.execute('insert into events(at,kind,payload) values(?,?,?)',(stamp(),kind,canonical(payload)))
 def merge_source(self,source):
  # Serialize read/merge/write as well as request reservations. Otherwise a
  # stale successful profile could overwrite another worker's fresh pause.
  owns_transaction=not self.db.in_transaction
  if owns_transaction:self.db.execute('begin immediate')
  try:
   family=source['family'];old=self.db.execute('select status,payload from sources where family=?',(family,)).fetchone()
   value=dict(source)
   if old:
    prior=json.loads(old['payload']);value={**prior,**source}
    value['pause_evidence']=list(dict.fromkeys(prior.get('pause_evidence',[])+source.get('pause_evidence',[])))
    if old['status']=='paused':value['status']='paused'
   self.db.execute('insert or replace into sources values(?,?,?)',(family,value.get('status','unknown'),canonical(value)))
   self.event('source_merged',{'family':family,'status':value.get('status','unknown')})
   if owns_transaction:self.db.execute('commit')
  except BaseException:
   if owns_transaction:self.db.execute('rollback')
   raise
 def source_check(self,url,field=None,action='fetch'):
  # A root URL alone does not prove that a later action is a search rather
  # than a business homepage fetch. Unknown sources allow robots preflight;
  # search needs an independently authorized source/tool binding.
  if action not in ('fetch','api','search','robots'):
   return {'allowed':False,'family':None,'reason':'source_action_invalid'}
  parsed=_https_url(url)
  if parsed is None:
   return {'allowed':False,'family':None,'reason':('preflight_url_out_of_scope' if action in ('robots','search') else 'source_url_invalid')}
  if action in ('robots','search') and (parsed.query or
     (parsed.path!='/robots.txt' if action=='robots' else parsed.path!='/')):
   return {'allowed':False,'family':None,'reason':'preflight_url_out_of_scope'}
  family=family_of(url);row=self.db.execute('select * from sources where family=?',(family,)).fetchone()
  if not row:return {'allowed':action=='robots','family':family,'reason':'source_preflight_required'}
  s=json.loads(row['payload'])
  if row['status']=='paused':return {'allowed':False,'family':family,'reason':'inherited_family_pause','evidence':s.get('pause_evidence',[])}
  if action=='search' and row['status']!='accessible':return {'allowed':False,'family':family,'reason':'source_preflight_required'}
  if action not in ('search','robots') and not field:return {'allowed':False,'family':family,'reason':'field_purpose_required'}
  if action not in ('search','robots') and row['status']!='accessible':return {'allowed':False,'family':family,'reason':'source_preflight_required'}
  if action!='robots':
   if s.get('live_fetch_authorized') is not True:
    return {'allowed':False,'family':family,'reason':'source_live_access_not_authorized'}
   domains=s.get('domains')
   if not isinstance(domains,list) or parsed.hostname not in domains:
    return {'allowed':False,'family':family,'reason':'source_host_not_explicitly_authorized'}
  if field and field not in s.get('supports',[]):return {'allowed':False,'family':family,'reason':'field_not_supported'}
  return {'allowed':True,'family':family,'reason':'access_permission_only_not_fact_acceptance'}
 def reference_access_check(self,url,field=None,action='fetch',*,channel='web_action',context=None):
  """User-authorized public Web reading, without source or claim certification.

  Pending policy review is not itself an origin access refusal. This explicit
  static-reference path never clears a pause or grants live/planning rights.
  """
  if channel!='web_action' or action not in ('search','fetch'):
   return {'allowed':False,'family':None,'reason':'reference_web_only'}
  context=context or {}
  expected='web.search_query' if action=='search' else 'web.open'
  if context.get('tool')!=expected:
   return {'allowed':False,'family':None,'reason':'reference_tool_binding_required'}
  if action=='search' and (not isinstance(context.get('query'),str) or not context['query'].strip()):
   return {'allowed':False,'family':None,'reason':'reference_search_query_required'}
  if action=='fetch' and not field:
   return {'allowed':False,'family':None,'reason':'field_purpose_required'}
  gate=self.source_check(url,field,action)
  if not gate['allowed'] and gate['reason'] not in ('source_preflight_required','source_live_access_not_authorized'):
   return gate
  row=self.db.execute('select status from sources where family=?',(gate['family'],)).fetchone()
  if row and row['status'] not in ('unknown','accessible'):
   return {'allowed':False,'family':gate['family'],'reason':'reference_source_status_blocked'}
  return {'allowed':True,'family':gate['family'],'reason':'user_authorized_public_web_reference_only',
    'reference_only':True,'claim_acceptance_granted':False,'source_approval_granted':False}
 def begin_run(self,run_id,budget):
  if any(type(v) is not int or v<0 for v in budget.values()):raise ValueError('Nonnegative integer channel caps required')
  self.db.execute('insert into runs values(?,?)',(run_id,canonical(budget)))
  self.event('run_started',{'run_id':run_id,'budget':budget})
 def reserve(self,run_id,request_id,url,channel,*,field=None,action='fetch',context=None,reference_only=False):
  self.db.execute('begin immediate')
  try:
   gate=(self.reference_access_check(url,field,action,channel=channel,context=context)
     if reference_only else self.source_check(url,field,action))
   if not gate['allowed']:raise ValueError(gate['reason'])
   active=self.db.execute("select id from requests where family=? and status='reserved' limit 1",(gate['family'],)).fetchone()
   if active:raise ValueError('Source family already leased: '+active[0])
   sr=self.db.execute('select payload from sources where family=?',(gate['family'],)).fetchone()
   interval=json.loads(sr[0]).get('min_interval_seconds',5) if sr else 5
   prior=self.db.execute('select payload from requests where family=? order by rowid desc limit 1',(gate['family'],)).fetchone()
   if prior:
    p=json.loads(prior[0]);last_at=p.get('finished_at') or p['reserved_at']
    if (datetime.now(timezone.utc)-datetime.fromisoformat(last_at)).total_seconds()<interval:
     raise ValueError('Source minimum interval; wait without issuing a request')
   row=self.db.execute('select budget from runs where id=?',(run_id,)).fetchone()
   if not row:raise ValueError('Unknown run')
   budget=json.loads(row[0])
   if channel not in budget:raise ValueError('Unbudgeted channel')
   used=self.db.execute('select count(*) from requests where run_id=? and channel=?',(run_id,channel)).fetchone()[0]
   if used>=budget[channel]:raise ValueError('Global channel budget exhausted')
   payload={'url':url,'field':field,'action':action,'context':context or {},'reserved_at':stamp()}
   if reference_only:payload.update(reference_only=True,claim_acceptance_granted=False,source_approval_granted=False)
   self.db.execute('insert into requests values(?,?,?,?,?,?)',(request_id,run_id,gate['family'],channel,'reserved',canonical(payload)))
   self.event('request_reserved',{'run_id':run_id,'request_id':request_id,'family':gate['family']})
   self.db.execute('commit');return {'allowed':True,'request_id':request_id,'remaining':budget[channel]-used-1}
  except BaseException:self.db.execute('rollback');raise
 def finish(self,request_id,status,*,evidence_file=None,error=None):
  if status not in ('success','failed','connection_error','challenge','denied','rate_limited','timeout','cancelled_before_send'):raise ValueError('Unknown request outcome')
  # Preserve compatibility with callers that still send generic `failed`,
  # while ensuring recognizable transport failures close the family gate.
  if status=='failed' and _connection_failure_detail(error):status='connection_error'
  self.db.execute('begin immediate')
  try:
   row=self.db.execute('select * from requests where id=?',(request_id,)).fetchone()
   if not row or row['status']!='reserved':raise ValueError('A reserved request is required, and may finish once')
   payload=json.loads(row['payload']);payload.update(evidence_file=evidence_file,error=error,finished_at=stamp())
   self.db.execute('update requests set status=?,payload=? where id=?',(status,canonical(payload),request_id))
   if status in ('connection_error','challenge','denied','rate_limited','timeout'):
    self.merge_source({'family':row['family'],'status':'paused','pause_evidence':[evidence_file or 'request:'+request_id],
      'last_pause_reason':status,'last_pause_at':stamp()})
   self.event('request_finished',{'request_id':request_id,'status':status});self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
 def add_lesson(self,lesson):
  if not lesson.get('id') or not lesson.get('evidence_paths'):raise ValueError('Lesson ID and evidence paths required')
  self.db.execute('insert or ignore into lessons values(?,?,?,?)',(lesson['id'],lesson['topic'],lesson['rule'],canonical(lesson['evidence_paths'])))
 def recall(self,term,limit=8):
  # Literal substring matching: no execution or SQL wildcard interpretation.
  return [dict(r) for r in self.db.execute('select * from lessons where instr(lower(topic||text),lower(?))>0 limit ?',(term,limit))]
 def export_sources(self):return [json.loads(r[0]) for r in self.db.execute('select payload from sources order by family')]
