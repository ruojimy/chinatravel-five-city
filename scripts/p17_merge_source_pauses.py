"""Conservatively merge private crawler pauses; never reset a paused source."""
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow

def main():
 shared=(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3').resolve();inherited=[];failures=[]
 for area in ('p15_whole_catalog','p16_multiworker','p17_continuous'):
  for file in sorted((ROOT/'results'/area).rglob('queue.sqlite3')):
   if file.resolve()==shared:continue
   try:
    db=sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosts'").fetchone():
     for host,status,last_at,delay,robots,reason in db.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE status='paused'"):
      inherited.append({'host':host,'reason':reason,'origin_queue':str(file.relative_to(ROOT)),'last_at':last_at,'delay':delay,'robots':robots})
    db.close()
   except sqlite3.Error as exc:failures.append({'file':str(file.relative_to(ROOT)),'error_type':type(exc).__name__})
 c=sqlite3.connect(shared,timeout=30);changes=[]
 with c:
  for row in inherited:
   old=c.execute('SELECT status,reason FROM hosts WHERE host=?',(row['host'],)).fetchone()
   if old and old[0]=='paused':continue
   reason='inherited_private_source_pause:'+str(row['reason'])
   if old:c.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(reason,row['host']))
   else:c.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',(row['host'],'paused',row['last_at'],row['delay'],row['robots'],reason))
   changes.append({k:v for k,v in row.items() if k!='robots'})
 total=c.execute("SELECT count(*) FROM hosts WHERE status='paused'").fetchone()[0];c.close()
 report={'at':utcnow(),'private_pause_observations':len(inherited),'new_or_upgraded_shared_pauses':changes,'shared_paused_hosts':total,'failures':failures,'source_pauses_restored_or_cleared':0,'network_requests':0}
 output=ROOT/'results/p17_continuous'/('source_pause_merge_'+report['at'].replace(':','').replace('+','_')+'.json')
 if output.exists():raise FileExistsError('Immutable pause audit already exists')
 output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
