"""Stream ChinaTravel into a provenance sidecar; never rewrite benchmark files."""
from __future__ import annotations
import csv,hashlib,json,sqlite3
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from .freshness import POLICIES,canonical,field_policy,sha,utcnow,retrieval_task

CITIES=dict(zip(('beijing','shanghai','nanjing','suzhou','hangzhou','shenzhen','chengdu','wuhan','guangzhou','chongqing'),
                ('北京','上海','南京','苏州','杭州','深圳','成都','武汉','广州','重庆')))
ADCODE=dict(zip(CITIES.values(),('110000','310000','320100','320500','330100','440300','510100','420100','440100','500000')))

def digest_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def iter_rows(path,base):
    """A single largest JSON file is loaded at a time; CSV/JSONL stream."""
    parts=path.relative_to(base).parts
    section=parts[0];city=CITIES.get(parts[1],parts[1]) if len(parts)>2 else ''
    kind={'attractions':'attraction','restaurants':'restaurant','accommodations':'accommodation',
          'poi':'poi'}.get(section)
    if path.suffix=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:
            for i,row in enumerate(csv.DictReader(f)):yield kind,city,i,row
    elif section=='poi':
        for i,row in enumerate(json.loads(path.read_text(encoding='utf-8-sig'))):yield 'poi',city,i,row
    elif section=='transportation':
        data=json.loads(path.read_text(encoding='utf-8-sig'));i=0
        for c,lines in data.items():
            for line in lines:
                for station in line['stations']:
                    yield 'metro_station',CITIES.get(c,c),i,{**station,'line':line['name']};i+=1
    elif section=='intercity_transport':
        if path.suffix=='.jsonl':
            with path.open(encoding='utf-8-sig') as f:
                for i,line in enumerate(f):
                    if line.strip():yield 'flight','',i,json.loads(line)
        else:
            for i,row in enumerate(json.loads(path.read_text(encoding='utf-8-sig'))):yield 'train','',i,row
    else:raise ValueError('Unclassified data file: '+str(path))

def static_tags(kind,row):
    tags=[{'tag':'kind','value':kind,'basis':'dataset_section','status':'benchmark_attribute'}]
    for key in ('type','cuisine','featurehoteltype','line','numbed'):
        if row.get(key) not in (None,''):
            tags.append({'tag':key,'value':row[key],'basis':key,'status':'benchmark_attribute'})
    # Themes are candidates for recall, not visitor-experience or identity proof.
    category=str(row.get('type','')).lower()
    for aspect,words in {'nature':('自然','风景','山岳','natural','scenic'),
                         'history':('历史','古迹','文物','historic'),
                         'indoor':('室内','indoor')}.items():
        if any(w in category for w in words):
            tags.append({'tag':aspect,'value':True,'basis':'type','status':'derived_recall_hint'})
    for tag in tags:
        tag['policy_id']=field_policy(tag['basis'],kind)
        tag['source_time_ref']='record.observed_at/source_updated_at'
        tag['valid_until']=None
    return tags

class TravelCatalog:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS records(
         id TEXT PRIMARY KEY,lang TEXT,kind TEXT,city TEXT,name TEXT,payload TEXT);
         CREATE INDEX IF NOT EXISTS place_lookup ON records(lang,kind,city);
         CREATE TABLE IF NOT EXISTS tags(id TEXT,tag TEXT,value TEXT);
         CREATE INDEX IF NOT EXISTS tag_lookup ON tags(tag,value,id);
         CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
         CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,field TEXT,entity_id TEXT,payload TEXT);
         CREATE INDEX IF NOT EXISTS claim_lookup ON claims(field,entity_id);''')

    def close(self):self.db.close()

    def add_claim(self,claim):
        from .expansion_contract import validate_inline_claim
        gate=validate_inline_claim(claim)
        if not gate['ok']:raise ValueError({'new_claim_contract':gate})
        payload=canonical({**claim,'structural_verdict':gate})
        with self.db:
            old=self.db.execute('SELECT payload FROM claims WHERE id=?',(claim['claim_id'],)).fetchone()
            if old:
                if old[0]!=payload:raise ValueError('claim_id collision; preserve old evidence and use a new ID')
                return
            self.db.execute('INSERT INTO claims VALUES(?,?,?,?)',
                            (claim['claim_id'],claim['field'],claim['entity_id'],payload))

    def claims(self,entity_id,field):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM claims WHERE entity_id=? AND field=?',(entity_id,field))]

    def candidates(self,city,demands=(),*,limit=8,lang='zh'):
        if not 1<=limit<=40:raise ValueError('limit must be 1..40')
        desired=[(d.aspect,d.desired) for d in demands if d.scope=='poi' and d.relation=='eq']
        matches=[];unknown=[];mismatch=[]
        # One row decoded at a time; retain only bounded top lists.
        for dbrow in self.db.execute("SELECT payload FROM records WHERE lang=? AND kind='attraction' AND city=? ORDER BY id",(lang,city)):
            record=json.loads(dbrow[0]);score=0;known=0
            for aspect,wanted in desired:
                values=[t['value'] for t in record['tags'] if t['tag']==aspect]
                if values:known+=1;score+=1 if wanted in values else -1
            item={'record':record,'tag_match_score':score,'known_aspects':known,
                  'unknown_aspects':len(desired)-known,'real_world_verified':False}
            bucket=matches if score>0 else mismatch if score<0 else unknown
            bucket.append(item);bucket.sort(key=lambda r:(-r['tag_match_score'],r['record']['record_id']))
            del bucket[limit:]
        # Reserve exploration slots for unknown rather than equating absence to false.
        reserve=min(2,len(unknown),limit//3) if desired else 0
        chosen=matches[:limit-reserve]+unknown[:reserve]
        seen={x['record']['record_id'] for x in chosen}
        for item in matches+unknown+mismatch:
            if len(chosen)>=limit:break
            if item['record']['record_id'] not in seen:
                chosen.append(item);seen.add(item['record']['record_id'])
        return chosen

def annotate_dataset(root,output,registry,*,languages=('zh','en')):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    target=output/'catalog.sqlite3'
    if target.exists():raise FileExistsError('Use a new output directory for a new immutable catalogue snapshot')
    cat=TravelCatalog(target);at=utcnow();counts=Counter();files=[];sample=[]
    try:
        for lang in languages:
            base=root/'ChinaTravel/chinatravel/environment'/('database_en' if lang=='en' else 'database')
            for path in sorted(base.rglob('*')):
                if not path.is_file():continue
                if path.suffix not in ('.csv','.json','.jsonl'):raise ValueError('Unknown file needs explicit classification: '+str(path))
                before=digest_file(path);relative=path.relative_to(root).as_posix();n=0
                for kind,city,index,row in iter_rows(path,base):
                    rid=sha([lang,relative,index])[:24];name=str(row.get('name') or row.get('TrainID') or row.get('FlightID') or rid)
                    record={'schema_version':'travel-catalog-v1','record_id':rid,'language':lang,'kind':kind,'city':city,'name':name,
                     'data':row,'tags':static_tags(kind,row),'source_id':'chinatravel_sandbox',
                     'source_locator':{'file':relative,'row_index_0based':index,'file_sha256':before},
                     'source_published_at':None,'source_updated_at':None,'observed_at':None,'retrieved_at':None,
                     'catalogued_at':at,'local_file_modified_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                     'timestamp_note':'Local file modification/import are not source fact observation/publication times.',
                     'valid_from':None,'valid_until':None,'freshness_status':'unknown_source_time',
                     'field_policies':{k:field_policy(k,kind) for k in row},
                     'authority':'research_benchmark_not_live_operator','licence_status':'dataset_terms_unverified',
                     'coordinate_system':'unknown',
                     'coordinate_order':('longitude,latitude' if kind=='metro_station' else 'latitude,longitude' if kind=='poi' else 'named_lat_lon_columns'),
                     'trust_status':'benchmark_only','entity_verified':False,
                     'needs_live_verification':True,'uncertainty_flags':['unknown_source_time','not_live_inventory','entity_unverified']}
                    if kind=='flight':record['uncertainty_flags'].append('flight_id_pattern_requires_operator_resolution')
                    cat.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(rid,lang,kind,city,name,canonical(record)))
                    cat.db.executemany('INSERT INTO tags VALUES(?,?,?)',[(rid,t['tag'],canonical(t['value'])) for t in record['tags']])
                    counts[f'{lang}:{kind}']+=1;n+=1
                    if len(sample)<20 or kind=='metro_station' and not any(r['kind']==kind for r in sample):sample.append(record)
                cat.db.commit()
                after=digest_file(path)
                if before!=after:raise AssertionError('Input mutated during annotation: '+relative)
                files.append({'file':relative,'sha256':before,'bytes':path.stat().st_size,'records':n,'language':lang,'unchanged_during_read':True})
        summary={'schema_version':'travel-catalog-v1','catalogued_at':at,'languages':list(languages),
          'counts':dict(counts),'records':sum(counts.values()),'files':len(files),'source_files':files,
          'source_id':'chinatravel_sandbox','source_registry_sha256':sha(registry),
          'unknown_source_time_records':sum(counts.values()),'new_verified_real_world_records':0,
          'source_files_modified':0,'policy_note':'TTL starts at verified source observation; unknown clocks never renewed by import.',
          'policies':{k:{'ttl_seconds':v[0],'mandatory_dynamic':v[1]} for k,v in POLICIES.items()}}
        cat.db.execute('INSERT INTO metadata VALUES(?,?)',('manifest',canonical(summary)));cat.db.commit()
        (output/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'sample_records.jsonl').write_text(''.join(canonical(r)+'\n' for r in sample),encoding='utf-8')
        (output/'source_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
        return summary
    finally:cat.close()

def preflight(catalog,query,*,travel_date=None,limit=6):
    from .candidate_matching import query_demands
    city=query.get('target_city','');demands=query_demands(query.get('nature_language',''))
    candidates=catalog.candidates(city,demands,limit=limit)
    context={'adcode':ADCODE.get(city),'travel_date':travel_date} if travel_date else {'adcode':ADCODE.get(city)}
    tasks=[retrieval_task({'city':city},'weather_forecast' if travel_date else 'weather_now',
                          reasons=['mandatory_dynamic'],context=context)]
    if any(d.aspect=='nature' and d.desired is True for d in demands):
        tasks.append(retrieval_task({'city':city},'weather_alert',reasons=['outdoor_exposure'],context={'adcode':ADCODE.get(city)}))
    if query.get('start_city') and query['start_city']!=city:
        trip_context={'travel_date':travel_date,'party_size':query.get('people_number',query.get('people',query.get('person_number')))}
        journey={'origin_city':query['start_city'],'destination_city':city}
        for field in ('intercity_schedule','inventory','dynamic_price'):
            tasks.append(retrieval_task(journey,field,reasons=['actual_date_schedule_fare_and_availability'],context=trip_context))
    if int(query.get('days',1))>1:
        stay={'city':city,'kind':'accommodation'}
        for field in ('inventory','dynamic_price'):
            tasks.append(retrieval_task(stay,field,reasons=['hotel_dates_room_type_party_required'],
                         context={'travel_date':travel_date,'party_size':query.get('people_number',query.get('people',query.get('person_number')))}))
    for c in candidates:
        r=c['record'];entity={'entity_id':r['record_id'],'city':city,'name':r['name']}
        required=['identity','opening_hours','price','closure']
        if any(d.aspect=='stairs' and d.hard for d in demands):required.append('accessibility')
        for field in required:
            tasks.append(retrieval_task(entity,field,reasons=['unknown_source_time','benchmark_only'],
                context={'travel_date':travel_date} if travel_date else {},tags=r['tags']))
        route_task=retrieval_task(entity,'route_duration',reasons=['amap_api_required','resolve_coordinates_and_departure_first'],
           context={'travel_date':travel_date,'origin':query.get('local_origin'),'destination':r['name'],'mode':'metro',
                    'coord_system':'unknown','departure_at':None},tags=r['tags'])
        route_task['origin_resolution']='chosen arrival terminal/hotel/previous activity, never substitute the intercity origin city'
        route_task['co_retrieved_fields']=['route_fare'];tasks.append(route_task)
    unknown_demands=[{'aspect':d.aspect,'desired':d.desired,'scope':d.scope}
                     for d in demands if not any(t['tag']==d.aspect for c in candidates for t in c['record']['tags'])]
    if unknown_demands:
        tasks.append(retrieval_task({'city':city},'experience',reasons=['static_tags_missing'],context=context,tags=unknown_demands))
    return {'mode':'live_preflight','query':query,'travel_date':travel_date,'candidates':candidates,
            'retrieval_tasks':tasks,'uncovered_query_tags':unknown_demands,
            'pruning':{'limit':limit,'unknown_exploration_reserved':True,'rules':'city + category themes; no hard negative from unknown; expand search if evidence inadequate'},
            'execution_budget':{'max_total_source_requests':12,'max_api_calls':4,'max_sources_per_gap':3,
                                'pending_tasks_after_budget':'persist, mark unresolved, ask only if decision-relevant'},
            'ready_for_real_world_recommendation':False,'needs_user_confirmation':False,
            'pending_user_fields':([] if travel_date else ['travel_date']),
            'note':'Run skill to resolve tasks, then batch only unresolved decision-relevant uncertainties for the user. Static benchmark data are never silently served as live.'}
