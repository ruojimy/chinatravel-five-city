"""Opt-in on-access Amap lookup for future unfrozen runs; no key rotation.

The benchmark defaults to read-only snapshot replay. Live mode requires an
explicit new run directory and maintains a durable shared budget/cache ledger.
"""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json,os,sqlite3,time,urllib.parse,urllib.request

HERE=Path(__file__).resolve().parent
WORKSPACE=Path(__file__).resolve().parents[4]
def now():return datetime.now(timezone.utc).isoformat()
def safe_value(v):return str(v or '').replace('（','(').replace('）',')').replace(' ','').lower()

def lookup(payload, *, run_dir=None, budget=4, opener=urllib.request.urlopen, key_path=None,
           endpoint=None, request_params=None):
    root=Path(run_dir or os.environ.get('CT_DYNAMIC_LIVE_DIR','')).resolve()
    if not (run_dir or os.environ.get('CT_DYNAMIC_LIVE_DIR')):
        raise ValueError('live lookups require an explicit CT_DYNAMIC_LIVE_DIR')
    if root==HERE.parent.resolve():raise ValueError('live journal must not overwrite frozen snapshot root')
    root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'dynamic_live.sqlite3',timeout=30,isolation_level=None)
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY,cache_key TEXT NOT NULL,at_utc TEXT NOT NULL,status TEXT NOT NULL,meta_json TEXT NOT NULL,raw_sha256 TEXT,response_json TEXT)')
    ident=payload['record_id']; city=payload['city'];kind=payload['kind'];name=payload['name']
    key=json.dumps([ident,city,kind,name],ensure_ascii=False,separators=(',',':'))
    db.execute('BEGIN IMMEDIATE')
    try:
        cached=db.execute("SELECT at_utc,status,meta_json,raw_sha256 FROM calls WHERE cache_key=? AND status='ok' ORDER BY id DESC LIMIT 1",(key,)).fetchone()
        if cached:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached[0])).total_seconds()
            ttl=72*3600 if kind=='attraction' else 168*3600 if kind=='restaurant' else 24*3600
            if age<=ttl:
                db.commit();return {'triggered':True,'mode':'live','status':'cache_hit','evidence':json.loads(cached[2]),'raw_sha256':cached[3]}
        count=int((db.execute("SELECT value FROM meta WHERE key='count'").fetchone() or ['0'])[0])
        paused=db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()
        if paused or count>=budget:
            reason='provider_paused' if paused else 'budget_exhausted'
            db.execute('INSERT INTO calls(cache_key,at_utc,status,meta_json) VALUES(?,?,?,?)',(key,now(),reason,'{}'))
            db.commit();return {'triggered':True,'mode':'live','status':reason,'provider_calls_used':count,'budget':budget}
        # The key is loaded only locally and omitted from logs and error messages.
        secret=Path(key_path or WORKSPACE/'reproduction/.secrets/amap.key').read_text(encoding='ascii').strip()
        endpoint=endpoint or 'https://restapi.amap.com/v5/place/text'
        params=(dict(request_params) if request_params is not None else
                {'keywords':name,'region':city,'city_limit':'true','page_size':'5','show_fields':'business','output':'JSON'})
        request=urllib.request.Request(endpoint+'?'+urllib.parse.urlencode(dict(params,key=secret)),
                                       headers={'User-Agent':'ChinaTravel-Research/1.0'})
        # Serialise requests, including delay, across processes via the SQLite write lock.
        last=db.execute("SELECT value FROM meta WHERE key='last_request_epoch'").fetchone()
        if last:
            delay=1.1-(time.time()-float(last[0]))
            if delay>0:time.sleep(delay)
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_request_epoch',?)",(str(time.time()),))
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('count',?)",(str(count+1),))
        try:
            with opener(request,timeout=15) as response:raw=response.read(2_000_000)
            if secret.encode() in raw:raise ValueError('secret in response')
            data=json.loads(raw.decode('utf-8'))
            code=str(data.get('infocode'));status='ok' if str(data.get('status'))=='1' else 'provider_error'
            if status!='ok':db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('paused',?)",(code,))
            matches=[x for x in data.get('pois',[]) if safe_value(x.get('name'))==safe_value(name)
                     and city in str(x.get('cityname') or '')]
            observed=None
            if len(matches)==1:
                p=matches[0];observed={'name':p.get('name'),'city':city,'location':p.get('location'),
                    'business':p.get('business'),'source_url':'https://www.amap.com/place/'+str(p.get('id') or ''),
                    'retrieved_at_utc':now(),'status':'single_provider_reference'}
            if kind=='transport':
                observed={'route':data.get('route'),'retrieved_at_utc':now(),'status':'single_provider_reference',
                          'trip_date':None,'availability':'unknown'}
            meta={'endpoint':endpoint,'params':params,'infocode':code,
                  'same_name_city_matches':len(matches),'observation':observed,
                  'boundary':'Amap business cost is not proven to be attraction ticket price.'}
            db.execute('INSERT INTO calls(cache_key,at_utc,status,meta_json,raw_sha256,response_json) VALUES(?,?,?,?,?,?)',
                       (key,now(),status,json.dumps(meta,ensure_ascii=False),sha256(raw).hexdigest(),raw.decode('utf-8')))
            db.commit();return {'triggered':True,'mode':'live','status':status,'provider_calls_used':count+1,
                               'budget':budget,'evidence':meta,'raw_sha256':sha256(raw).hexdigest()}
        except Exception as exc:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('paused',?)",('transport_error',))
            db.execute('INSERT INTO calls(cache_key,at_utc,status,meta_json) VALUES(?,?,?,?)',
                       (key,now(),'transport_error',json.dumps({'error_type':type(exc).__name__})))
            db.commit();return {'triggered':True,'mode':'live','status':'transport_error','provider_calls_used':count+1,'budget':budget,'error_type':type(exc).__name__}
    except Exception:
        db.rollback();raise
    finally:db.close()

def lookup_route(from_city,to_city,mode,**kwargs):
    if mode=='airplane':
        return {'triggered':True,'mode':'live','status':'amap_airfare_not_supported',
                'notice':'Do not infer airfare from public-transport routes.'}
    evidence=HERE.parent.parent/'tier_policy_v3/amap_sample_prefetch_20261115.json'
    anchors=json.loads(evidence.read_text(encoding='utf-8'))['endpoints']
    if from_city not in anchors or to_city not in anchors:
        return {'triggered':True,'mode':'live','status':'verified_endpoint_not_prefetched',
                'notice':'Need identity-confirmed GCJ02 station anchors; no coordinates were guessed.'}
    a,b=anchors[from_city],anchors[to_city]
    params={'origin':a['location'],'destination':b['location'],'city1':a['code'],'city2':b['code'],
            'strategy':'0','show_fields':'cost','output':'JSON'}
    payload={'record_id':f'transport:{from_city}:{to_city}:{mode}','city':from_city,
             'kind':'transport','name':f'{from_city}->{to_city}'}
    return lookup(payload,endpoint='https://restapi.amap.com/v5/direction/transit/integrated',
                  request_params=params,**kwargs)
