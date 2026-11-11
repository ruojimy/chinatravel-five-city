"""One immutable account-week budget campaign; no wall-clock deadline."""
import json,math,sqlite3
from datetime import datetime,timezone
from pathlib import Path

def weekly_snapshot(raw):
 if 'content' in raw and 'rateLimits' not in raw and 'rateLimitsByLimitId' not in raw:
  raw=json.loads(next(c['text'] for c in raw['content'] if c.get('type')=='text'))
 box=raw.get('rateLimitsByLimitId',{}).get('codex') or raw.get('rateLimits') or {}
 windows=[w for w in (box.get('primary'),box.get('secondary')) if isinstance(w,dict) and w.get('windowDurationMins')==10080]
 if len(windows)!=1:raise ValueError('A real 10080-minute weekly window is required; do not assume primary/secondary')
 w=windows[0];used=w.get('usedPercent');reset=w.get('resetsAt')
 if type(used) not in (int,float) or not math.isfinite(used) or not 0<=used<=100 or type(reset) is not int:
  raise ValueError('Weekly usage/reset unavailable; never fabricate a baseline')
 return {'used':used,'reset':reset,'window_minutes':10080}

class WeeklyBudgetCampaign:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(self.path,timeout=30,isolation_level=None);self.db.row_factory=sqlite3.Row
  self.db.executescript('''PRAGMA journal_mode=WAL;
   CREATE TABLE IF NOT EXISTS weekly_budget_campaigns(id TEXT PRIMARY KEY,baseline REAL,budget REAL,window_reset INTEGER,last_used REAL,status TEXT);
   CREATE TABLE IF NOT EXISTS weekly_budget_checks(id INTEGER PRIMARY KEY,campaign_id TEXT,at TEXT,snapshot TEXT,status TEXT);
  ''')
 def close(self):self.db.close()
 def status(self,campaign_id):
  row=self.db.execute('select * from weekly_budget_campaigns where id=?',(campaign_id,)).fetchone()
  if not row:raise ValueError('Initialize this campaign once before running')
  r=dict(row);r.update(target_used_percent=r['baseline']+r['budget'],spent_points=max(0,r['last_used']-r['baseline']),account_shared=True)
  r['allowed_to_start_more_work']=r['status']=='active'
  return r
 def initialize(self,campaign_id,raw,budget=20):
  w=weekly_snapshot(raw)
  if type(budget) not in (int,float) or not math.isfinite(budget) or budget<=0 or w['used']+budget>100:
   raise ValueError('Requested weekly budget must fit the current window')
  self.db.execute('begin immediate')
  try:
   if self.db.execute('select 1 from weekly_budget_campaigns where id=?',(campaign_id,)).fetchone():
    raise ValueError('Campaign baseline is immutable; resume/check it instead of allocating another 20 points')
   self.db.execute('insert into weekly_budget_campaigns values(?,?,?,?,?,?)',(campaign_id,w['used'],budget,w['reset'],w['used'],'active'))
   self._record(campaign_id,w,'initialized');self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
  return self.status(campaign_id)
 def _record(self,campaign_id,w,status):
  self.db.execute('insert into weekly_budget_checks(campaign_id,at,snapshot,status) values(?,?,?,?)',(campaign_id,datetime.now(timezone.utc).isoformat(timespec='seconds'),json.dumps(w),status))
 def check(self,campaign_id,raw):
  w=weekly_snapshot(raw);self.db.execute('begin immediate')
  try:
   r=self.status(campaign_id);status=r['status']
   if status=='active':
    # A small reset-time wobble with a nondecreasing counter is not a reset.
    if abs(w['reset']-r['window_reset'])>60 or w['used']<r['last_used']:
     status='weekly_window_changed'
    elif w['used']>=r['target_used_percent']:status='budget_reached'
    if status!='weekly_window_changed':
     self.db.execute('update weekly_budget_campaigns set last_used=? where id=?',(w['used'],campaign_id))
    self.db.execute('update weekly_budget_campaigns set status=? where id=?',(status,campaign_id))
   self._record(campaign_id,w,status);self.db.execute('commit')
  except BaseException:self.db.execute('rollback');raise
  return self.status(campaign_id)
