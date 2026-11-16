"""Four-call Amap evidence collection; no key rotation and no secret in logs."""
from pathlib import Path
import importlib.util,json,sqlite3

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
spec=importlib.util.spec_from_file_location('v5_dynamic_live',ROOT/'expanded/dynamic_live.py')
live=importlib.util.module_from_spec(spec);spec.loader.exec_module(live)
run=HERE/'live_capture'
if run.exists():raise FileExistsError('preserve previous capture')
run.mkdir()
events=[]
def call(payload,**kwargs):
    result=live.lookup(payload,run_dir=run,budget=4,**kwargs)
    events.append({'kind':payload['kind'],'name':payload['name'],'status':result['status'],
                   'raw_sha256':result.get('raw_sha256'),'evidence':result.get('evidence')})
    return result

# Reuse previously verified same-provider station anchors; no guessed coords.
old=ROOT.parent/'tier_policy_v3/amap_sample_prefetch_20261115.json'
anchors=json.loads(old.read_text(encoding='utf-8'))['endpoints']
call({'record_id':'attraction:xian:8','city':'西安','kind':'attraction','name':'回民街'})
if anchors.get('西安') and anchors.get('重庆'):
    a,b=anchors['西安'],anchors['重庆']
    call({'record_id':'transport:西安:重庆:any','city':'西安','kind':'transport','name':'西安->重庆'},
         endpoint='https://restapi.amap.com/v5/direction/transit/integrated',
         request_params={'origin':a['location'],'destination':b['location'],'city1':a['code'],
                         'city2':b['code'],'strategy':'0','show_fields':'cost','output':'JSON'})
station=call({'record_id':'station:chengdu:成都东站','city':'成都','kind':'station','name':'成都东站'})
obs=(station.get('evidence') or {}).get('observation') or {}
if station['status']=='ok' and obs.get('location') and anchors.get('西安'):
    target=anchors['西安']
    call({'record_id':'transport:成都:西安:any','city':'成都','kind':'transport','name':'成都->西安'},
         endpoint='https://restapi.amap.com/v5/direction/transit/integrated',
         request_params={'origin':obs['location'],'destination':target['location'],'city1':'028',
                         'city2':target['code'],'strategy':'0','show_fields':'cost','output':'JSON'})

db=sqlite3.connect(run/'dynamic_live.sqlite3')
try:
    rows=db.execute('SELECT id,cache_key,at_utc,status,meta_json,raw_sha256,response_json FROM calls ORDER BY id').fetchall()
    meta=dict(db.execute('SELECT key,value FROM meta'))
finally:db.close()
data={'budget':4,'events':events,'provider_meta':meta,'rows':[{'id':r[0],'key':json.loads(r[1]),
      'at_utc':r[2],'status':r[3],'meta':json.loads(r[4]),'raw_sha256':r[5],
      'raw':json.loads(r[6]) if r[6] else None} for r in rows]}
out=HERE/'live_capture_evidence.json'
with out.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'calls':len(rows),'statuses':[r['status'] for r in data['rows']],
                  'provider_meta':meta,'output':str(out)},ensure_ascii=False))
