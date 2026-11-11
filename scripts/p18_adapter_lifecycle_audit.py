"""Mock transport only: determine whether adapter stop survives a new client."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file

def main():
 out=ROOT/'results/p18_dynamic_eval/adapter_lifecycle_audit.json'
 if out.exists():raise FileExistsError('Immutable diagnostic already exists')
 calls=[]
 def failing_transport(endpoint,params):
  calls.append({'phase':'first_client','endpoint':endpoint,'synthetic':True});return {'status':'0','infocode':'10003'}
 def second_transport(endpoint,params):
  calls.append({'phase':'new_client','endpoint':endpoint,'synthetic':True})
  return {'status':'1','infocode':'10000','lives':[{'adcode':'430100','reporttime':'2026-10-23 10:16:00','weather':'SYNTHETIC NOT A WEATHER REPORT'}]}
 with tempfile.TemporaryDirectory() as root:
  first=LiveAmapClient(root,key='SYNTHETIC-NO-REAL-CREDENTIAL',budget=2,transport=failing_transport);errors=[]
  for _ in range(2):
   try:first.weather('430100')
   except LiveAmapError as exc:errors.append(str(exc))
  second=LiveAmapClient(root,key='SYNTHETIC-NO-REAL-CREDENTIAL',budget=2,transport=second_transport)
  second.weather('430100')
 result={'at':utcnow(),'synthetic_transport_only':True,'real_network_requests':0,'real_credentials_read':False,
  'implementation_sha256':digest_file(ROOT/'src/shorttrip/live_amap.py'),'first_instance_transport_calls':first.spent,
  'same_instance_second_attempt_was_blocked':first.spent==1,'first_errors':errors,
  'new_instance_transport_calls':second.spent,'provider_stop_shared_across_client_instances':False,
  'raw_mock_events':calls,'finding':'LiveAmapClient.stopped is per instance. The adapter does not read the collection source-pause ledger; an outer persistent guard is required before any future live invocation.',
  'scope':'Isolation diagnostic, not a real request to the paused Amap provider; no settings, source pauses or source records changed.'}
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
