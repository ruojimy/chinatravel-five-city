"""Persistent whole-catalog work inventory; observations never imply completion."""
import collections, hashlib, json, math, sqlite3
from pathlib import Path
from .freshness import canonical, utcnow
from .business_archives import name_aliases
from .scoped_business import today_hours, match_target, matching_aliases, provider_aliases
from .dynamic.opendata import gcj02_to_wgs84

TYPE_PREFIX = {'restaurant':'餐饮服务;', 'attraction':'风景名胜;', 'accommodation':'住宿服务;'}
API_TYPES = {'restaurant':'050000','attraction':'110000|140100|140200|140400','accommodation':'100000'}

def gaps(record, offers=()):
    d=record['data']; kind=record['kind']
    if kind=='restaurant':
        h=record.get('today_hours_structured') or {}
        flags={'average_price':d.get('price') is not None,'cuisine':bool(d.get('cuisine')),
               'opening_hours':bool(h.get('segments')) or bool(d.get('opentime') and d.get('endtime'))}
    elif kind=='attraction':
        h=record.get('today_hours_structured') or {}
        flags={'admission_price':d.get('price') is not None,
               'opening_hours':bool(h.get('segments')) or bool(d.get('opentime') and d.get('endtime')),
               'recommended_duration':d.get('recommendmintime') is not None and d.get('recommendmaxtime') is not None}
    else:
        flags={'dated_room_price_reference':bool(offers),'room_type':any(o.get('room_type_name') for o in offers) or
               any(a.get('field')=='room_type_name' and isinstance(a.get('value'),str) and a['value'].strip() for a in record.get('operator_assertions',[])),
               'bed_count':d.get('numbed') is not None}
    return [k for k,v in flags.items() if not v]

def match_business(target, pois):
    # Preserve the separately reviewed restaurant variants and distance thresholds.
    if target['kind']=='restaurant':return match_target(target,pois)
    good=[];rejected=[]
    for p in pois:
        if not p.get('id') or not p.get('name'):continue
        try:
            lon,lat=map(float,p['location'].split(','));lon,lat=gcj02_to_wgs84(lon,lat)
            distance=111195*math.hypot(lat-target['latitude_wgs84'],
                       (lon-target['longitude_wgs84'])*math.cos(math.radians(lat)))
        except (KeyError,TypeError,ValueError):continue
        exact=bool(matching_aliases(target['name']) & provider_aliases(p))
        city=p.get('cityname','').removesuffix('市')==target['city']
        kind=p.get('type','').startswith(TYPE_PREFIX[target['kind']])
        if target['kind']=='attraction':
            kind=kind or str(p.get('typecode','')) in ('140100','140200','140400')
        binding={'poi_id':p['id'],'name':p['name'],'distance_metres':round(distance,3),
                 'same_city':city,'same_kind':kind,'exact_alias':exact}
        if exact and city and kind and distance<=150:good.append((p,binding))
        elif exact or distance<=150:rejected.append(binding)
    if len(good)==1:
        return {'matched':True,'poi':good[0][0],'binding':good[0][1],'entity_verified':False,
                'method':'unique_exact_name_city_kind_near_coordinate_candidate','rejected':rejected}
    return {'matched':False,'entity_verified':False,'reason':'ambiguous' if good else 'no_safe_entity_match',
            'candidate_count':len(good),'rejected':rejected}

class BulkQueue:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30);self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,kind TEXT,city TEXT,name TEXT,
          missing TEXT,city_supported INTEGER,target TEXT);
        CREATE INDEX IF NOT EXISTS entities_city ON entities(city);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,entity_id TEXT REFERENCES entities(id),
          adapter TEXT,status TEXT,priority INTEGER,attempts INTEGER DEFAULT 0,packet_path TEXT,
          result TEXT,started_at TEXT,finished_at TEXT);
        CREATE INDEX IF NOT EXISTS jobs_next ON jobs(adapter,status,priority,id);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS provider_state(provider TEXT PRIMARY KEY,status TEXT,reason TEXT,at TEXT);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,payload TEXT);
        ''')
    def close(self):self.db.close()
    def seed(self,catalog,old_cache):
        existing=self.db.execute('SELECT value FROM metadata WHERE key=?',('source_catalog',)).fetchone()
        if existing:
            if json.loads(existing[0])!=str(Path(catalog).resolve()):raise ValueError('Different immutable source')
            return self.status()
        source=sqlite3.connect(Path(catalog).resolve().as_uri()+'?mode=ro',uri=True)
        offers=collections.defaultdict(list)
        for rid,payload in source.execute('SELECT entity_id,payload FROM room_offers'):offers[rid].append(json.loads(payload))
        cache={p.stem:p for p in Path(old_cache).glob('*.json')}
        count=collections.Counter()
        with self.db:
            for payload, in source.execute('SELECT payload FROM records ORDER BY city,id'):
                r=json.loads(payload);rid=r['record_id'];missing=gaps(r,offers[rid]);supported=bool(r['source_locator'].get('provider_city_match'))
                target={'entity_id':rid,'city':r['city'],'kind':r['kind'],'name':r['name'],'keywords':r['name'],
                        'longitude_wgs84':r['data']['lon'],'latitude_wgs84':r['data']['lat'],'missing':missing}
                self.db.execute('INSERT INTO entities VALUES(?,?,?,?,?,?,?)',
                     (rid,r['kind'],r['city'],r['name'],canonical(missing),supported,canonical(target)))
                # Every entity has an explicit independent/temporal verification job.
                base='needs_room_date_ui' if r['kind']=='accommodation' else 'needs_primary_source'
                if not supported:base='needs_city_identity'
                self.db.execute('INSERT INTO jobs(id,entity_id,adapter,status,priority) VALUES(?,?,?,?,?)',
                     (rid+'|verify',rid,'independent_verification',base,9))
                if missing and supported and rid.startswith('overture:'):
                    key=hashlib.sha256(rid.encode()).hexdigest()[:20]
                    cached=cache.get(key);status='cached' if cached else 'pending'
                    self.db.execute('INSERT INTO jobs(id,entity_id,adapter,status,priority,packet_path) VALUES(?,?,?,?,?,?)',
                       (rid+'|amap',rid,'amap_place',status,{'restaurant':1,'attraction':2,'accommodation':3}[r['kind']],str(cached) if cached else None))
                count[r['kind']]+=1
            for key,value in {'source_catalog':str(Path(catalog).resolve()),'seeded_at':utcnow(),'entity_counts':dict(count)}.items():
                self.db.execute('INSERT INTO metadata VALUES(?,?)',(key,canonical(value)))
        source.close();return self.status()
    def sync_cache(self,folder):
        # Import completed old batches without a second request, including late arrivals.
        changed=0
        with self.db:
            for p in Path(folder).glob('*.json'):
                x=json.loads(p.read_text(encoding='utf-8'));rid=x['target']['entity_id']
                changed+=self.db.execute("UPDATE jobs SET status='cached',packet_path=? WHERE id=? AND status='pending'",
                                      (str(p.resolve()),rid+'|amap')).rowcount
        return changed
    def status(self):
        return {'at':utcnow(),'entities':self.db.execute('SELECT count(*) FROM entities').fetchone()[0],
                'jobs':[dict(x) for x in self.db.execute('SELECT adapter,status,count(*) AS count FROM jobs GROUP BY adapter,status')],
                'provider_state':[dict(x) for x in self.db.execute('SELECT * FROM provider_state')],
                'complete_whole_catalog':False,'queried_is_not_completed':True}
    def claim_next(self):
        # Round robin cities within each kind, ordered by least city work already spent.
        with self.db:
            row=self.db.execute('''WITH spent AS (SELECT de.city,count(*) AS n FROM jobs done
              JOIN entities de ON de.id=done.entity_id WHERE done.adapter='amap_place' AND done.status!='pending' GROUP BY de.city)
              SELECT j.*,e.target FROM jobs j JOIN entities e ON e.id=j.entity_id LEFT JOIN spent s ON s.city=e.city
              WHERE j.adapter='amap_place' AND j.status='pending'
              ORDER BY j.priority,coalesce(s.n,0),e.city,j.id LIMIT 1''').fetchone()
            if not row:return None
            self.db.execute("UPDATE jobs SET status='inflight',started_at=?,attempts=attempts+1 WHERE id=?",(utcnow(),row['id']))
        return dict(row)
    def finish(self,job,path,assessment):
        with self.db:self.db.execute("UPDATE jobs SET status=?,packet_path=?,result=?,finished_at=? WHERE id=?",
               ('matched_candidate' if assessment['matched'] else 'unmatched',str(path.resolve()),canonical(assessment),utcnow(),job['id']))
    def pause(self,reason,job=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO provider_state VALUES(?,?,?,?)',('amap','paused',reason,utcnow()))
            if job:self.db.execute("UPDATE jobs SET status='provider_stopped',result=?,finished_at=? WHERE id=?",
                                  (canonical({'reason':reason}),utcnow(),job['id']))
    def assert_provider_ready(self):
        if self.db.execute("SELECT 1 FROM provider_state WHERE provider='amap' AND status='paused'").fetchone():
            raise RuntimeError('Provider remains paused; no automatic reset or credential rotation')

def assess(packet):
    matched=match_business(packet['target'],packet['response'].get('pois',[]))
    result={k:v for k,v in matched.items() if k!='poi'}
    if matched['matched']:
        b=matched['poi'].get('business') or {}
        result['available_business_keys']=sorted(k for k,v in b.items() if v)
        result['parsed_today_hours']=bool(today_hours(b.get('opentime_today'))['segments'])
        result['hotel_or_admission_price_from_cost_forbidden']=True
    return result
