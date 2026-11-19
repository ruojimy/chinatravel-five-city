"""Opt-in on-access Amap lookup for future unfrozen runs; no key rotation.

The benchmark defaults to read-only snapshot replay. Live mode requires an
explicit new run directory and maintains a durable shared budget/cache ledger.
"""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json,os,sqlite3,time,urllib.parse,urllib.request

HERE=Path(__file__).resolve().parent
WORKSPACE=Path(os.environ.get('CT_WORKSPACE_ROOT',Path(__file__).resolve().parents[3])).resolve()
def now():return datetime.now(timezone.utc).isoformat()
def safe_value(v):return str(v or '').replace('（','(').replace('）',')').replace(' ','').lower()

def lookup(payload, *, run_dir=None, budget=4, opener=urllib.request.urlopen, key_path=None,
           endpoint=None, request_params=None):
    root=Path(run_dir or os.environ.get('CT_DYNAMIC_LIVE_DIR','')).resolve()
    if not (run_dir or os.environ.get('CT_DYNAMIC_LIVE_DIR')):
        raise ValueError('live lookups require an explicit CT_DYNAMIC_LIVE_DIR')
    profile=os.environ.get('CT_SANDBOX_PROFILE_ROOT')
    if root==HERE.parent.resolve() or (profile and (root==Path(profile).resolve() or root.is_relative_to(Path(profile).resolve()))):
        raise ValueError('live journal must not overwrite frozen snapshot root')
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
    profile=os.environ.get('CT_SANDBOX_PROFILE_ROOT')
    if not profile:
        return {'triggered':True,'mode':'live','status':'verified_endpoint_not_prefetched',
                'notice':'No verified endpoint evidence profile configured.'}
    anchors=load_anchors(Path(profile))
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

def load_anchors(profile):
    """Load only pinned, identity-matched and recent station observations."""
    import dynamic_runtime
    snapshot=dynamic_runtime.load_snapshot()
    base=profile.resolve()/'data_integration'
    pinned={x['path']:x['sha256'] for x in snapshot.get('evidence_files',[])}
    anchors={}
    def recent(text):
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(text)).total_seconds()
            return 0<=age<=30*24*3600
        except (ValueError,TypeError):return False
    old=base/'amap_sample_prefetch_20261115.json'
    if old.name in pinned and old.is_file() and sha256(old.read_bytes()).hexdigest()==pinned[old.name]:
        data=json.loads(old.read_text(encoding='utf-8-sig'))
        for city,anchor in data.get('endpoints',{}).items():
            for event in data.get('events',[]):
                params=event.get('params') or {}
                if (params.get('region')!=city or params.get('keywords')!=anchor.get('name')
                    or str(event.get('status'))!='1' or not recent(event.get('retrieved_at_utc'))):continue
                hits=[p for p in (event.get('response') or {}).get('pois',[])
                      if p.get('name')==anchor.get('name') and city in str(p.get('cityname') or '')
                      and p.get('location')==anchor.get('location') and p.get('citycode')==anchor.get('code') and p.get('id')]
                if len(hits)==1:anchors[city]=dict(anchor,source='pinned_legacy_amap_observation')
    for name,digest in pinned.items():
        if not Path(name).name.startswith('amap_anchors_') or not name.endswith('.json'):continue
        file=(base/name).resolve()
        if not file.is_relative_to(base) or not file.is_file() or sha256(file.read_bytes()).hexdigest()!=digest:continue
        data=json.loads(file.read_text(encoding='utf-8-sig'))
        if data.get('schema')!='amap-verified-anchor-v1':continue
        for city,a in data.get('anchors',{}).items():
            journal_name=a.get('source_journal');journal=(base/str(journal_name or '')).resolve()
            if (a.get('city')!=city or a.get('coordinate_system')!='GCJ02' or not recent(a.get('observed_at_utc'))
                or not journal.is_relative_to(base) or not journal.is_file()
                or pinned.get(journal_name)!=a.get('source_journal_sha256')
                or sha256(journal.read_bytes()).hexdigest()!=a.get('source_journal_sha256')):continue
            db=sqlite3.connect('file:'+journal.as_posix()+'?mode=ro',uri=True)
            try:r=db.execute('SELECT status,raw_sha256,response_json FROM calls WHERE id=?',(a.get('source_call_id'),)).fetchone()
            finally:db.close()
            if not r or r[0]!='ok' or not r[2] or r[1]!=a.get('source_raw_sha256') or sha256(r[2].encode('utf-8')).hexdigest()!=r[1]:continue
            response=json.loads(r[2])
            if str(response.get('status'))!='1' or str(response.get('infocode'))!='10000':continue
            hits=[p for p in response.get('pois',[]) if p.get('name')==a.get('name')
                  and city in str(p.get('cityname') or '') and p.get('id')==a.get('provider_poi_id')
                  and p.get('location')==a.get('location') and p.get('citycode')==a.get('code')]
            if len(hits)==1:anchors[city]=dict(a)
    return anchors
