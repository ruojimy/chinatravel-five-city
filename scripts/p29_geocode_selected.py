"""One-time fixed 16-object lookup; not a general geocoding service.

Policy: https://operations.osmfoundation.org/policies/nominatim/
Single machine/thread, <= 1 request/s, cache, no retries or instance switching.
Responses are candidates: exact branch/address matching is a separate review.
"""
import sys,json,time,hashlib,sqlite3
from pathlib import Path
from datetime import datetime,timezone
import requests
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/p29_five_city_completion'
HOST='https://nominatim.openstreetmap.org'
def main():
 rows=json.loads((OUT/'geocode_tasks.json').read_text(encoding='utf-8'))
 db=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3')
 old=db.execute('select status from hosts where host=?',(HOST,)).fetchone();db.close()
 if old and old[0]=='paused':raise SystemExit('Inherited provider pause')
 ledger={'source':'OpenStreetMap contributors','licence':'ODbL-1.0','policy':'https://operations.osmfoundation.org/policies/nominatim/','max_calls':16,'calls':[],'stopped':False,'provider_switching':False}
 lp=OUT/'capture/nominatim_ledger.json'
 if lp.exists():raise FileExistsError('Preserve one-time batch')
 cache=OUT/'capture/nominatim';cache.mkdir(exist_ok=True)
 for i,row in enumerate(rows[:16]):
  query=row['name']+' '+row['city'];fp=cache/(str(i).zfill(2)+'.json')
  cached=None
  # Reuse exact previously requested queries only, with original capture clock.
  for p in (ROOT/'data/open_data_cache').glob('osm_*.json'):
   v=json.loads(p.read_text(encoding='utf-8'))
   from urllib.parse import parse_qs,urlparse
   if parse_qs(urlparse(v.get('url','')).query).get('q')==[query]:cached=v;break
  event={'task':row,'query':query,'requested_at':datetime.now(timezone.utc).isoformat()}
  if cached is not None:
   fp.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8');event.update(status='reused_exact_local_cache',file=str(fp.relative_to(ROOT)))
  else:
   if ledger['calls']:time.sleep(1.15)
   try:
    response=requests.get(HOST+'/search',params={'q':query,'format':'jsonv2','limit':3,'addressdetails':1,'extratags':1,'accept-language':'zh','countrycodes':'cn'},headers={'User-Agent':'ShortTripResearch/1.0 (one-time 16 fixed travel-entity identity checks; local university reproducibility research)'},timeout=20)
    event.update(http_status=response.status_code,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(response.content).hexdigest())
    raw={'url':response.url,'_retrieved_at':event['retrieved_at'],'body':response.json() if response.status_code==200 else response.text[:2000]}
    fp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    event.update(status='candidate_response' if response.status_code==200 else 'paused_failure',file=str(fp.relative_to(ROOT)),count=len(raw['body']) if isinstance(raw['body'],list) else None)
    if response.status_code!=200:ledger['stopped']=True
   except Exception as exc:event.update(status='paused_failure',error_type=type(exc).__name__);ledger['stopped']=True
  ledger['calls'].append(event)
  lp.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in event.items() if k!='task'},ensure_ascii=True),flush=True)
  if ledger['stopped']:break
if __name__=='__main__':main()
