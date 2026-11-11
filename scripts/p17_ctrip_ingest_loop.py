"""Continuously check new retained source bytes, register scoped rules, publish safely."""
import argparse,gzip,hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/attractions'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from p17_review_batch import review
from shorttrip.freshness import utcnow
def write(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
def one_batch(limit=50):
 registry=ROOT/'results/p17_continuous/approved_batches/index.json';seen=set()
 for entry in json.loads(registry.read_text(encoding='utf-8'))['batches']:
  if not Path(entry['file']).name.startswith('attractions_ctrip_'):continue
  for a in json.loads((ROOT/entry['file']).read_text(encoding='utf-8'))['assertions']:
   seen.add((a['source_url'],(a['context'].get('source_locator') or {}).get('original_response_sha256')))
 index=sqlite3.connect((OUT/'entity_source_queue.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
 todo=[]
 for (data,) in index.execute('SELECT result FROM parsed_pages'):
  p=json.loads(data)
  if len(p['candidate_entity_ids'])==1 and p['assertions'] and (p['source_url'],p['raw_sha256']) not in seen:todo.append(p)
  if len(todo)>=limit:break
 index.close()
 if not todo:return None
 parent=OUT/'ctrip_batches';parent.mkdir(exist_ok=True);number=len(list(parent.glob('batch_*')))+1;folder=parent/f'batch_{number:04}';folder.mkdir()
 sources=[];assertions=[]
 for p in todo:
  raw=gzip.open(p['raw_file'],'rb').read()
  if hashlib.sha256(raw).hexdigest()!=p['raw_sha256']:raise ValueError('Captured Ctrip HTML changed')
  soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
  for tag in soup(['script','style','noscript']):tag.decompose()
  # Whole retained visible text supports exact quotes and does not invent HTML.
  text=soup.get_text(' ',strip=True);file=folder/(p['raw_sha256']+'.txt');file.write_bytes(text.encode())
  sid='p17-ctrip-dom:'+hashlib.sha256(p['source_url'].encode()).hexdigest()
  sources.append({'source_id':sid,'source_url':p['source_url'],'content_file':file.name,'content_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
    'retrieved_at':p['retrieved_at'],'observed_at':None,'source_updated_at':None,'source_published_at':None,
    'authority':'online_travel_agency_public_guide','licence_status':'public_guide_reuse_unverified','representation':'public_html_dom_text',
    'source_locator':{'original_html_file':p['raw_file'],'original_response_sha256':p['raw_sha256'],'parser_version':p.get('parser_version'),
      'source_name':p['name'],'source_address':p.get('address'),'source_city_context':p['source_city_context']}})
  for a in p['assertions']:
   if a['quote'] not in text:raise ValueError('Room/module quote not present in retained visible DOM')
   assertions.append({**a,'entity_id':p['candidate_entity_ids'][0],'source_id':sid,'status':'scoped_source_reference_unknown_fact_age',
      'identity_match_basis':'Unique exact simplified/traditional name in explicitly observed city route; position and current operational status require independent verification.',
      'entity_verified':False,'native_projection_permitted':False})
 packet=folder/'field_assertions.json';write(packet,{'created_at':utcnow(),'sources':sources,'assertions':assertions,'network_requests':0})
 review(packet,f'attractions_ctrip_{number:04}')
 return {'batch':str(packet.relative_to(ROOT)),'sources':len(sources),'assertions':len(assertions),'at':utcnow()}
def publish():
 result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/p15_publish_catalog.py')],capture_output=True,text=True,encoding='utf-8')
 with (OUT/'ingest_publish.log').open('a',encoding='utf-8') as f:f.write(utcnow()+'\n'+result.stdout+'\n'+result.stderr+'\n')
 if result.returncode:raise RuntimeError('Publication failed; previous validated pointer retained')
 subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/p17_status.py')],capture_output=True,check=True)
def main(hours,once,interval_seconds=300):
 lock=OUT/'ingest.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 start=time.monotonic();batches=0
 try:
  while time.monotonic()-start<hours*3600 and not (OUT/'INGEST_STOP').exists():
   batch=one_batch()
   if batch:publish();batches+=1
   write(OUT/'ingest_status.json',{'at':utcnow(),'pid':os.getpid(),'running':True,'batches_this_run':batches,'latest':batch,
      'note':'No network in ingestion; facts remain scoped and unknown source clocks are not renewed','interval_seconds':interval_seconds,'full_completion':False})
   if once:break
   # Coalesce many small fetches into one full immutable snapshot.
   # Check the local stop file once per second without another dataset reload.
   for _ in range(interval_seconds):
    if (OUT/'INGEST_STOP').exists():break
    time.sleep(1)
 finally:
  write(OUT/'ingest_status.json',{'at':utcnow(),'pid':os.getpid(),'running':False,'batches_this_run':batches,'reason':'local_budget_stop_or_error_checkpoint','full_completion':False})
  lock.unlink(missing_ok=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--hours',type=float,default=12);p.add_argument('--once',action='store_true');p.add_argument('--interval-seconds',type=int,default=300);a=p.parse_args()
 if not 30<=a.interval_seconds<=3600:p.error('interval-seconds must be 30..3600')
 main(a.hours,a.once,a.interval_seconds)
