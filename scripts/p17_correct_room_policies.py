"""Atomically supersede old room-area/bed-description TTL classifications.

Unknown fact clocks remain unknown; no factual values or evidence bytes change.
"""
import copy,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow,POLICIES
from shorttrip.operator_assertions import validate_assertion

def main():
 folder=ROOT/'results/p17_continuous/approved_batches';lock=folder/'review.lock'
 fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 try:
  index=folder/'index.json';original=index.read_bytes();registry=json.loads(original);changes=[];next_entries=[]
  for entry in registry['batches']:
   file=ROOT/entry['file'];raw=file.read_bytes()
   if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Approval bytes changed')
   report=json.loads(raw);changed=[];revision=copy.deepcopy(report)
   for a in revision['assertions']:
    if a['field'].startswith('room_') and a['policy_id'] not in ('room_configuration','dynamic_price','price'):
     changed.append({'assertion_id':a['assertion_id'],'field':a['field'],'previous_policy_id':a['policy_id'],'previous_ttl_seconds':a['ttl_seconds']})
     a['policy_id']='room_configuration';a['ttl_seconds']=POLICIES['room_configuration'][0]
     if not validate_assertion(a)['ok']:raise ValueError('Revised assertion failed contract')
   if not changed:next_entries.append(entry);continue
   out=folder/(file.stem+'_room_policy_v3.json')
   if out.exists():raise FileExistsError('Immutable policy revision already exists')
   revision.update(reviewed_at=utcnow(),supersedes=entry,revision_reason='room attributes use room_configuration policy; old unknown source clocks are preserved',policy_changes=changed)
   out.write_text(json.dumps(revision,ensure_ascii=False,indent=2),encoding='utf-8')
   next_entries.append({'file':str(out.relative_to(ROOT)),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()})
   changes.append({'previous':entry,'replacement':next_entries[-1],'assertions_reclassified':len(changed)})
  if changes:
   history=folder/'index_history';history.mkdir(exist_ok=True);digest=hashlib.sha256(original).hexdigest();hist=history/(digest+'.json')
   if not hist.exists():hist.write_bytes(original)
   registry['batches']=next_entries;tmp=index.with_suffix('.policy.tmp');tmp.write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,index)
   receipt=folder/'room_policy_revision_20261023_0704.json'
   if receipt.exists():raise FileExistsError('Policy audit receipt exists')
   receipt.write_text(json.dumps({'at':utcnow(),'replacements':changes,'no_fact_clocks_or_values_changed':True,'old_evidence_preserved':True},ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({'batches_revised':len(changes),'assertions_reclassified':sum(c['assertions_reclassified'] for c in changes),'fact_clocks_refreshed':0}))
 finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
