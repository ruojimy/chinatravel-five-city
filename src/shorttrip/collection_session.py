"""Offline, durable wakeup lease and time checkpoints.

This is not an OS sandbox or a model-token hard cap. It gates cooperating
agents, retains stale leases for review, and never starts network requests.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from .collection_weekly_budget import WeeklyBudgetCampaign

class SessionLedger:
 def __init__(self,path,policy):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.policy=policy
  self.db=sqlite3.connect(self.path,timeout=30,isolation_level=None);self.db.row_factory=sqlite3.Row
  self.db.executescript('''PRAGMA journal_mode=WAL;
   CREATE TABLE IF NOT EXISTS scheduled_sessions(id TEXT PRIMARY KEY,state TEXT,started_at REAL,last_at REAL,start_usage TEXT,last_usage TEXT,reason TEXT);
   CREATE TABLE IF NOT EXISTS scheduled_usage(session_id TEXT,at REAL,weekly_reset INTEGER,primary_points REAL,weekly_points REAL,note TEXT);
  ''')
 def close(self):self.db.close()
 def _weekly(self,raw=None):
  campaign=WeeklyBudgetCampaign(self.path)
  try:
   cid=self.policy['weekly_campaign_id']
   return campaign.status(cid) if raw is None else campaign.check(cid,raw)
  finally:campaign.close()
 def begin(self,run_id,raw=None,*,now=None):
  # raw is ignored for compatibility with old callers. No usage lookup,
  # percentage, reset timestamp, missing snapshot or warning gates execution.
  now=now if now is not None else datetime.now(timezone.utc).timestamp();p=self.policy
  weekly=p.get('control_mode')=='weekly_budget'
  if weekly:
   if raw is None:raise ValueError('Fresh real weekly usage file required')
   quota=self._weekly(raw)
   if not quota['allowed_to_start_more_work']:raise ValueError('Weekly campaign stopped: '+quota['status'])
  self.db.execute('begin immediate')
  try:
   old=self.db.execute("select id,started_at from scheduled_sessions where state='active'").fetchone()
   if old:raise ValueError('Existing session requires checkpoint/worker review: '+old['id'])
   self.db.execute('insert into scheduled_sessions values(?,?,?,?,?,?,?)',(run_id,'active',now,now,'null','null',None))
   self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
  result={'allowed':True,'run_id':run_id,'network_called':False,'deadline_epoch':None if weekly else now+p['checkpoint_deadline_minutes']*60,'control_mode':'weekly_budget' if weekly else 'time_only'}
  if weekly:result['weekly_campaign']=quota
  return result
 def checkpoint(self,run_id,raw=None,*,now=None):
  now=now if now is not None else datetime.now(timezone.utc).timestamp();p=self.policy
  weekly=p.get('control_mode')=='weekly_budget'
  if weekly:
   if raw is None:raise ValueError('Fresh real weekly usage file required')
   quota=self._weekly(raw)
  self.db.execute('begin immediate')
  try:
   row=self.db.execute('select * from scheduled_sessions where id=?',(run_id,)).fetchone()
   if not row or row['state']!='active':raise ValueError('An active session is required')
   elapsed=(now-row['started_at'])/60;reasons=[]
   if weekly:
    if not quota['allowed_to_start_more_work']:reasons.append(quota['status'])
   else:
    if elapsed>=p['stop_starting_work_after_minutes']:reasons.append('time_to_checkpoint')
    if elapsed>=p['checkpoint_deadline_minutes']:reasons.append('checkpoint_deadline_reached')
   self.db.execute('update scheduled_sessions set last_at=?,reason=? where id=?',(now,json.dumps({'checkpoint_reasons':reasons,'control_mode':'weekly_budget' if weekly else 'time_only'}),run_id));self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
  result={'allowed_to_start_more_work':not reasons,'reasons':reasons,'elapsed_minutes':elapsed,'control_mode':'weekly_budget' if weekly else 'time_only','network_called':False}
  if weekly:result['weekly_campaign']=quota
  return result
 def end(self,run_id,reason,*,workers_stopped=False,stop_report=None,now=None):
  if workers_stopped is not True:raise ValueError('Confirm all this run workers have stopped before releasing the lease')
  now=now if now is not None else datetime.now(timezone.utc).timestamp()
  allowed={'time_budget_reached','weekly_budget_reached','batch_goal_complete','no_safe_work_remaining','runtime_blocked','user_requested'}
  if reason not in allowed:raise ValueError('A microtask checkpoint is not a session exit; use an evidence-backed stop reason')
  if reason=='time_budget_reached' and self.policy.get('control_mode')=='weekly_budget':raise ValueError('No wall-clock stop is configured for this campaign')
  if reason=='batch_goal_complete' and self.policy.get('control_mode')=='weekly_budget' and self._weekly()['status']=='active':
   raise ValueError('A completed small batch is a checkpoint; continue the same campaign budget')
  if reason=='weekly_budget_reached' and (self.policy.get('control_mode')!='weekly_budget' or self._weekly()['status']!='budget_reached'):
   raise ValueError('The immutable weekly campaign budget has not been reached')
  self.db.execute('begin immediate')
  try:
   row=self.db.execute('select * from scheduled_sessions where id=?',(run_id,)).fetchone()
   if not row or row['state']!='active':raise ValueError('An active session is required')
   if reason=='time_budget_reached':
    if (now-row['started_at'])/60<self.policy['stop_starting_work_after_minutes']:raise ValueError('Time budget not reached; continue ready work')
   elif reason=='user_requested':
    report=stop_report or {}
    artifact=Path(report.get('artifact_path') or '')
    if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=report.get('artifact_sha256'):
     raise ValueError('User-requested stop artifact missing or hash changed')
   elif reason!='weekly_budget_reached':
    # This verifies the report's shape and artifact integrity, not its factual
    # semantics. The coordinator still owns the milestone/queue assessment.
    report=stop_report or {}
    if type(report.get('pending_actionable_items')) is not int or report['pending_actionable_items']!=0:
     raise ValueError('Ready work remains or has not been inventoried; checkpoint and continue')
    if reason=='batch_goal_complete':
     if report.get('milestone_complete') is not True or report.get('milestone_id') not in {'strict_adapter_integrated','frozen_batch_evaluated','static_repair_batch_evaluated'}:
      raise ValueError('Small helpers/tests do not complete the batch milestone')
    elif not report.get('blocker_summary'):raise ValueError('A concrete blocker summary is required')
    artifact=Path(report.get('artifact_path') or '')
    if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=report.get('artifact_sha256'):
     raise ValueError('Stop artifact missing or hash changed')
   self.db.execute("update scheduled_sessions set state='ended',reason=? where id=?",(json.dumps({'exit_reason':reason,'stop_report':stop_report}),run_id));self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
  return {'ended':True,'run_id':run_id,'network_called':False}
