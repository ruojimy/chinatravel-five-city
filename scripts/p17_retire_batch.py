"""Retire an unfit immutable approval while preserving all evidence/history."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow

def main():
 p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('reason');a=p.parse_args()
 folder=ROOT/'results/p17_continuous/approved_batches';lock=folder/'review.lock'
 fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 try:
  index=folder/'index.json';raw=index.read_bytes();data=json.loads(raw)
  removed=[e for e in data['batches'] if Path(e['file']).name==a.label+'.json']
  if len(removed)!=1:raise ValueError('Expected exactly one active approval')
  history=folder/'index_history';history.mkdir(exist_ok=True)
  digest=hashlib.sha256(raw).hexdigest();saved=history/(digest+'.json')
  if not saved.exists():saved.write_bytes(raw)
  data['batches']=[e for e in data['batches'] if e not in removed]
  tmp=index.with_suffix('.retire.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,index)
  receipt={'at':utcnow(),'retired':removed,'reason':a.reason,'previous_index_sha256':digest,'previous_index_file':str(saved.relative_to(ROOT)),
    'current_index_sha256':hashlib.sha256(index.read_bytes()).hexdigest(),'evidence_deleted':False}
  out=folder/(a.label+'.retired.json')
  if out.exists():raise FileExistsError('Retirement already recorded')
  out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(receipt))
 finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
