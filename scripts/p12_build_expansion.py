"""Build a distinct snapshot from cached evidence only. No network requests."""
from __future__ import annotations
import collections, copy, gzip, hashlib, json, math, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_store import ExpansionStore
from shorttrip.expansion_contract import FIELDS, validate_record
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file

SOURCE=ROOT/'data/expansion_v1_20261022'
OUT=ROOT/'data/expansion_catalog_v1_1_20261022'
RESULT=ROOT/'results/p12_expansion'
def read_gzip(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)
def add_tags(record):
    record=copy.deepcopy(record)
    for tag in record['tags']:
        if tag.get('source_time_ref') is None:tag['source_time_ref']='record.observed_at'
    record['tags'].append({'tag':'kind','value':record['kind'],'basis':'source_taxonomy_mapping',
        'status':'derived_recall_hint','policy_id':'identity','source_time_ref':'record.observed_at','valid_until':None})
    category=record['tags'][0]['value']
    groups={'history':{'museum','history_museum','historic_site','monument','memorial','castle','palace','archaeological_site'},
            'nature':{'park','national_park','state_park','garden','botanical_garden','beach','viewpoint','scenic_overlook'},
            'art':{'art_gallery','art_museum','gallery'}}
    for tag,values in groups.items():
        if category in values:record['tags'].append({'tag':tag,'value':True,'basis':'taxonomy.primary:'+category,
            'status':'derived_recall_hint','policy_id':'theme','source_time_ref':'record.observed_at','valid_until':None})
    return record
def build():
    OUT.mkdir(exist_ok=True);RESULT.mkdir(exist_ok=True)
    if (OUT/'catalog.sqlite3').exists():raise FileExistsError('Version already exists; use a new directory/version')
    receipts=[]; inputs=[]; raw_counts=collections.Counter()
    for p in sorted(SOURCE.glob('*.receipt.json')):
        if '.initial_strict.' in p.name:continue
        info=json.loads(p.read_text(encoding='utf-8'))
        if info['status']!='complete':continue
        for name,proof in info['files'].items():
            file=ROOT/name
            if digest_file(file)!=proof['sha256']:raise ValueError('Source file digest mismatch: '+name)
            inputs.append({'file':name,**proof})
        receipts.append(info);raw_counts.update(info['counts'])
    # An on-disk scratch table prevents retaining large record envelopes in RAM.
    stage=sqlite3.connect(OUT/'staging.sqlite3')
    stage.execute('CREATE TABLE staged(id TEXT PRIMARY KEY,payload TEXT,score INTEGER)')
    duplicates=[];raw_verified=0
    for info in receipts:
        slug=info['slug']
        with gzip.open(SOURCE/'raw'/(slug+'.jsonl.gz'),'rt',encoding='utf-8') as raw:
            for record in read_gzip(SOURCE/(slug+'.records.jsonl.gz')):
                line=raw.readline().rstrip('\n')
                if hashlib.sha256(line.encode()).hexdigest()!=record['source_locator']['raw_sha256']:
                    raise ValueError('Per-record raw evidence digest mismatch')
                raw_verified+=1;rid=record['record_id'];score=int(record['source_locator']['provider_city_match'])
                old=stage.execute('SELECT score FROM staged WHERE id=?',(rid,)).fetchone()
                if old:
                    duplicates.append({'record_id':rid,'reason':'same_gers_id_across_windows'})
                    if score<=old[0]:continue
                stage.execute('INSERT OR REPLACE INTO staged VALUES(?,?,?)',(rid,json.dumps(add_tags(record),ensure_ascii=False),score))
            if raw.readline():raise ValueError('Raw evidence has unmatched extra records')
        stage.commit()
    near_duplicates=[];name_index=collections.defaultdict(list)
    counts=collections.Counter();confirmed=collections.Counter();blockers=collections.Counter();missing=collections.Counter()
    city_counts=collections.defaultdict(collections.Counter);files=[]
    store=ExpansionStore(OUT/'catalog.sqlite3',create=True)
    def rows():
        with gzip.open(OUT/'records.jsonl.gz','wt',encoding='utf-8',newline='\n') as target:
            for row in stage.execute('SELECT payload FROM staged ORDER BY score DESC,id'):
                record=json.loads(row[0]);d=record['data']
                # Same normalized label within 30m: conservative exact-name merge.
                name=''.join(c for c in record['name'].casefold() if c.isalnum())
                key=(record['kind'],name)
                match=None
                for oldlat,oldlon,oldid in name_index[key]:
                    dy=(d['lat']-oldlat)*111195;dx=(d['lon']-oldlon)*111195*math.cos(math.radians(d['lat']))
                    if math.hypot(dx,dy)<=30:match=oldid;break
                if match:
                    near_duplicates.append({'record_id':record['record_id'],'kept':match,'reason':'exact_normalized_name_within_30m'})
                    continue
                name_index[key].append((d['lat'],d['lon'],record['record_id']))
                gate=validate_record(record)
                if not gate['discovery_ok']:raise ValueError(gate)
                counts[record['kind']]+=1;counts['records']+=1;counts['planning_ready']+=gate['planning_ready']
                if record['source_locator']['provider_city_match']:
                    confirmed[record['kind']]+=1;city_counts[record['city']][record['kind']]+=1
                blockers.update(gate['planning_blockers']);missing.update(gate['missing_planning_fields'])
                target.write(json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
                yield record
    result=store.load(rows());integrity=store.db.execute('PRAGMA integrity_check').fetchone()[0]
    tag_count=store.db.execute('SELECT count(*) FROM tags').fetchone()[0];store.close();stage.close()
    baseline=json.loads((ROOT/'data/catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    unchanged=[{'file':f['file'],'unchanged':digest_file(ROOT/f['file'])==f['sha256']} for f in baseline['source_files']]
    targets={k:baseline['counts']['zh:'+k] for k in ('attraction','restaurant','accommodation')}
    for p in (OUT/'catalog.sqlite3',OUT/'records.jsonl.gz'):
        files.append({'file':str(p.relative_to(ROOT)),'sha256':digest_file(p),'bytes':p.stat().st_size})
    report={'version':'expansion-catalog-v1.1-20261022','built_at':utcnow(),'counts':dict(counts),
       'raw_window_counts':dict(raw_counts),'dedup_by_gers_removed':len(duplicates),'dedup_by_name_30m_removed':len(near_duplicates),
       'provider_city_assertion_counts':dict(confirmed),'city_counts':dict(city_counts),'city_windows_completed':len(receipts),
       'city_attribution_unverified':counts['records']-sum(confirmed.values()),'tags':tag_count,
       'discovery_schema_all_valid':True,'per_record_raw_hashes_verified':raw_verified,'sqlite_integrity':integrity,
       'native_fields':{k:list(v) for k,v in FIELDS.items()},'baseline_unique_language_targets':targets,
       'strict_new_city_candidate_doubling':{k:confirmed[k]>=n for k,n in targets.items()},
       'real_planning_ready_doubling':False,'real_world_accuracy':None,'dynamic_calls_saved_observed':None,
       'planning_blockers':dict(blockers),'missing_planning_fields':dict(missing),'baseline_files_checked':len(unchanged),
       'baseline_all_unchanged':all(x['unchanged'] for x in unchanged),'files':files,'source_files':inputs,
       'network_source_paused':True,'counting_note':'Window-only location assignments excluded from strict city counts. No bilingual duplicates. Benchmark and real-world eligibility separate.'}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (RESULT/'deduplication.json').write_text(json.dumps({'same_gers':duplicates,'near_name':near_duplicates},ensure_ascii=False,indent=2),encoding='utf-8')
    (RESULT/'baseline_integrity.json').write_text(json.dumps(unchanged,ensure_ascii=False,indent=2),encoding='utf-8')
    (RESULT/'expansion_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('counts','provider_city_assertion_counts','tags','city_windows_completed','baseline_all_unchanged','sqlite_integrity')},ensure_ascii=False))
if __name__=='__main__':build()
