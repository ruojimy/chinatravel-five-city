"""Append immutable, evidence-checked P17 packets to the reviewed registry."""
import argparse, hashlib, json, os, sqlite3, sys
import re,gzip,math,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import POLICIES,utcnow,canonical,parse_time
from shorttrip.operator_assertions import VERSION,check_graph,exact_source_quote
from shorttrip.travel_catalog import digest_file
RES=ROOT/'results/p17_continuous'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _review(path, label):
    path=path.resolve()
    if not path.is_relative_to(RES.resolve()):raise ValueError('Packet outside P17')
    batch=json.loads(path.read_text(encoding='utf-8'))
    sources={s['source_id']:s for s in batch['sources']}
    audited_prefixes=('p17-healthy-operator-cached:','p17-niccolo-detail:','p17-pan-observed:',
        'p17-millennium-cached:','p17-ascott-public-schema:','p17-ctrip-alias-cache:',
        'p17-ctrip-intro:','p17-ctrip-card:','p17-http-review:','p17-feinfood-provider:','p17-langham-observed:','p17-ctrip-embedded-duration:','p17-pan-remaining:','p17-bingsheng:')
    if any(sid.startswith(audited_prefixes) for sid in sources):
        receipt_path=path.parent/'root_capture_audit.json'
        if not receipt_path.exists():raise ValueError('Original-capture root audit receipt required before approval')
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if not receipt.get('passed') or receipt.get('packet_sha256')!=sha(path):raise ValueError('Root audit receipt does not cover these packet bytes')
    pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
    db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
    mapping=json.loads((RES/'restaurants/taxonomy_mapping.json').read_text(encoding='utf-8'))
    approved=[];operator_cache={};seen_assertions={};csv_cache={}
    duration_names={}
    if any(sid.startswith('p17-ctrip-embedded-duration:') for sid in sources):
        from opencc import OpenCC
        from collections import Counter
        from shorttrip.business_archives import normalize_name
        duration_cc=OpenCC('t2s')
        duration_key=lambda r:(r['city'],normalize_name(duration_cc.convert(r['name'])))
        duration_names=Counter(duration_key(json.loads(row[0])) for row in db.execute("SELECT payload FROM records WHERE kind='attraction'"))
    paper_sources=[s for s in sources.values() if s['source_id'].startswith('p17-triptailor:')]
    for filename in {s['source_locator']['csv_file'] for s in paper_sources}:
        entries=[s for s in paper_sources if s['source_locator']['csv_file']==filename];file=(ROOT/filename).resolve()
        if not file.is_relative_to((RES/'open_datasets/TripTailor_tables').resolve()):raise ValueError('Historical table outside retained archive')
        if any(digest_file(file)!=s['source_locator']['csv_sha256'] for s in entries[:1]):raise ValueError('Historical CSV changed')
        wanted={s['source_locator']['csv_data_row_ordinal'] for s in entries}
        with file.open(encoding='utf-8-sig',newline='') as stream:
            for ordinal,row in enumerate(csv.DictReader(stream),1):
                if ordinal in wanted:csv_cache[(filename,ordinal)]=row
    for a in batch['assertions']:
        s=sources[a['source_id']]
        file=(path.parent/s['content_file']).resolve()
        if not file.is_relative_to(RES.resolve()):raise ValueError('Capture escaped P17')
        digest=sha(file)
        if digest!=s['content_sha256']:raise ValueError('Capture digest mismatch')
        raw=file.read_bytes().decode('utf-8');quote=exact_source_quote(raw,a['quote'])
        row=db.execute('SELECT payload FROM records WHERE id=?',(a['entity_id'],)).fetchone()
        if not row:raise ValueError('Unknown existing entity')
        record=json.loads(row[0]);native={}
        if s['representation']=='saved_original_json_row':
            original_row=json.loads(raw)
            if original_row.get('id')!=a['entity_id'].removeprefix('overture:') or original_row.get('names',{}).get('primary')!=record['name'] or digest!=record['source_locator'].get('raw_sha256'):raise ValueError('Original source category is bound to another entity')
        context={k:v for k,v in a.items() if k not in ('quote','value','unit','scope')}
        context.update(entity_verified=False,reviewed_reference_only=True,
            upstream_source_metadata=s.get('upstream_source_metadata'),source_locator=s.get('source_locator'))
        field=a['field'];policy='theme' if field in ('cuisine','food_category') or 'duration' in field else 'room_configuration' if field.startswith('room_') or field in ('bed_configuration','bed_type') else 'dynamic_price' if field=='dated_price' else 'price' if field.startswith('admission') or field in ('average_price','avg_price','price') else 'opening_hours'
        if field=='dietary_category_unverified':policy='theme'
        if field=='cuisine_reference':policy='theme'
        if field.endswith('relevance_conflict'):policy='identity'
        if field=='source_property_address_conflict':policy='identity'
        if a.get('mapping_version')==mapping['version']:
            source=json.loads(raw);loc=s['source_locator'];rl=record['source_locator']
            if source['id']!=a['entity_id'].removeprefix('overture:') or source['names']['primary']!=record['name']:raise ValueError('Taxonomy identity mismatch')
            if loc['raw_file']!=rl['raw_file'] or loc['raw_line']!=rl['raw_line'] or digest!=rl['raw_sha256']:raise ValueError('Original row locator mismatch')
            category=source['taxonomy']['primary']
            if category!=a['mapping_input'] or mapping['mapping'].get(category)!=a['value']:raise ValueError('Unapproved taxonomy mapping')
            # Keep ambiguous South/Southern America spelling as a scoped reference.
            if record['data'].get('cuisine') is None and category!='southern_american_restaurant':native={'cuisine':a['value']}
            context.update(native_provenance_status='derived',cuisine_granularity='coarse',
                upstream_taxonomy_is_not_independent_verification=True)
        if s['source_id'].startswith('p17-ui:') and field=='bed_configuration' and a.get('native_projection_review')=='root_seen_room_modal':
            reviewed={'overture:362d1778-6a07-4a18-b9b5-8a02ef7c98ba':1,'overture:8d4f5f02-3f5f-42f6-a014-b94f1f2066c3':1}
            if reviewed.get(a['entity_id'])!=a['value'] or '1张1.8米大床' not in quote:raise ValueError('Unreviewed UI bed projection')
            native={'numbed':a['value']}
        if s['source_id'].startswith('p17-feinfood:') and a.get('root_projection_review')=='feinfood_exact_address_reference':
            basis=a['identity_match_basis'];original=(ROOT/basis['raw_row_file']).resolve()
            if not original.is_relative_to(RES.resolve()) or sha(original)!=record['source_locator']['raw_sha256']:raise ValueError('Restaurant original evidence changed')
            provider=json.loads(original.read_text(encoding='utf-8'));address=basis['matched_address']
            norm=lambda t:re.sub(r'[^\w\u4e00-\u9fff]','',t).casefold()
            if provider['id']!=a['entity_id'].removeprefix('overture:') or address not in [z.get('freeform') for z in provider.get('addresses') or []] or len(norm(address))<8 or norm(address) not in norm(raw):raise ValueError('Restaurant address mismatch')
            if field=='avg_price' and type(a['value']) in (int,float) and a['value']>=0:native={'price':a['value']}
            if field=='cuisine' and isinstance(a['value'],str) and a['value']:native={'cuisine':a['value']}
            context['address_reference_matched']=True
        if s['source_id'].startswith('p17-accor-cached:'):
            if s['source_id'] not in operator_cache:
                from shorttrip.operator_room_dom import accor_rooms
                capture=Path(s['source_locator']['original_html_file']);original=gzip.open(capture,'rb').read()
                if hashlib.sha256(original).hexdigest()!=s['source_locator']['original_response_sha256']:raise ValueError('Operator original HTML changed')
                operator_cache[s['source_id']]=accor_rooms(original)
            parsed=operator_cache[s['source_id']];scope=json.loads(a['scope'])
            room=next((z for z in parsed['room_configurations'] if z['room_type_name']==scope['room_type_name'] and z['bed_quote']==scope['bed_quote'] and z['quote']==quote),None)
            if not room:raise ValueError('Room assertion differs from original operator DOM')
            if a.get('root_projection_review')=='accor_visible_gps_150m_named_single_room':
                gps=parsed['gps'];links=sqlite3.connect(ROOT/'results/p15_whole_catalog/source_links.sqlite3')
                link=links.execute('SELECT 1 FROM links WHERE entity_id=? AND url=?',(a['entity_id'],s['source_url'])).fetchone();links.close()
                d=111195*math.hypot(gps['lat']-record['data']['lat'],(gps['lon']-record['data']['lon'])*math.cos(math.radians(gps['lat']))) if gps else None
                if not link or d is None or d>150 or room['room_count']!=1 or type(room['bed_count']) is not int or room['bed_count']!=a['value']:raise ValueError('Unreviewed operator room projection')
                native={'numbed':room['bed_count']};context['selected_named_room_configuration']=scope
        if s['source_id'].startswith('p17-triptailor:'):
            loc=s['source_locator'];row=csv_cache.get((loc['csv_file'],loc['csv_data_row_ordinal']))
            if row!=json.loads(raw):raise ValueError('Serialized paper row differs from original CSV')
            from shorttrip.source_identity import verify_historical_identity
            verify_historical_identity(row,record,a['identity_match_basis'],ROOT)
            policy='theme' if 'duration' in field or 'cuisine' in field or 'category' in field or 'segment' in field else 'price' if 'price' in field or 'admission' in field else 'opening_hours'
            context['currency_unconfirmed_no_native_price']=True
            if field=='recommended_duration_text' and a['identity_match_basis']['method']=='exact_name_city_unique_near_coordinate_candidate':
                text=row.get('reference_time','').strip();m=re.fullmatch(r'(\d+(?:\.\d+)?)(?:\s*[-–—~]\s*(\d+(?:\.\d+)?))?\s*hours?',text,re.I)
                if m:
                    low=float(m[1]);high=float(m[2] or m[1])
                    if 0<low<=high<=24:native={'recommendmintime':low,'recommendmaxtime':high};context['source_recommendation_unit']='hours; explicit historical range only'
        if s['source_id'].startswith('p17-ctrip-embedded-duration:'):
            from shorttrip.public_duration import verify_public_duration
            loc=s['source_locator'];original=gzip.open(loc['original_html_file'],'rb').read()
            if hashlib.sha256(original).hexdigest()!=loc['original_response_sha256']:raise ValueError('Public duration HTML changed')
            entity=(ROOT/loc['original_entity_row_file']).read_bytes()
            if hashlib.sha256(entity).hexdigest()!=record['source_locator']['raw_sha256'] or json.loads(entity)['id']!=record['record_id'].removeprefix('overture:'):raise ValueError('Duration entity evidence changed')
            projection=json.loads(raw)
            if field!='recommended_duration_raw' or a['value']!=projection['playSpendTime'] or duration_names[duration_key(record)]!=1:raise ValueError('Unapproved or ambiguous duration binding')
            native=verify_public_duration(original,projection,record,s['source_url'])
            context.update(source_recommendation_unit='hours; explicit published recommendation only',
                recommendation_is_not_measured_duration=True,independent_reality_verification=False)
        evidence_id='operator:'+hashlib.sha256(canonical([s['source_id'],s['source_url'],s['retrieved_at'],digest]).encode()).hexdigest()
        clocks={key:s.get(key) if parse_time(s.get(key)) else None for key in ('source_published_at','source_updated_at','observed_at','retrieved_at','valid_from','valid_until')}
        assertion={'schema_version':VERSION,'assertion_id':'operator-assertion:'+hashlib.sha256(canonical([a['entity_id'],field,a['value'],a['scope'],evidence_id]).encode()).hexdigest(),
            'entity_id':a['entity_id'],'field':field,'value':a['value'],'unit':a.get('unit'),
            'scope':a['scope'] if isinstance(a['scope'],str) else canonical(a['scope']),
            'quote':quote,'context':context,'source_id':s['source_id'],'source_url':s['source_url'],
            **clocks,'source_date_text':s.get('source_published_at'),'policy_id':policy,'ttl_seconds':POLICIES[policy][0],
            'authority':s.get('authority','public_publisher_unverified'),'licence_status':s.get('licence_status','public_source_reuse_unverified'),
            'capture':{'file':str(file.relative_to(ROOT)),'sha256':digest,'representation':s['representation']},
            'evidence_id':evidence_id,'native_values':native}
        evidence={**{k:assertion[k] for k in ('source_id','source_url','source_published_at','source_updated_at','observed_at','retrieved_at')},'raw_text':raw,'raw_sha256':digest}
        gate=check_graph(assertion,evidence)
        if not gate['ok']:raise ValueError(gate)
        aid=assertion['assertion_id']
        if aid in seen_assertions:
            if seen_assertions[aid]!=assertion:raise ValueError('Conflicting reviewed assertion identity before registration')
            continue
        seen_assertions[aid]=assertion;approved.append(assertion)
    db.close()
    folder=RES/'approved_batches';folder.mkdir(exist_ok=True)
    out=folder/(label+'.json')
    if out.exists():raise FileExistsError('Immutable reviewed batch already exists')
    report={'reviewed_at':utcnow(),'reviewer':'root_agent','assertions':approved,
        'source_packet':{'file':str(path.relative_to(ROOT)),'sha256':sha(path)},
        'existing_entities':len({a['entity_id'] for a in approved}),'planning_ready_certified':False}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    index=folder/'index.json';registry=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {'batches':[]}
    registry['batches'].append({'file':str(out.relative_to(ROOT)),'sha256':sha(out)})
    temp=index.with_suffix('.tmp');temp.write_text(json.dumps(registry,indent=2),encoding='utf-8');os.replace(temp,index)
    print(canonical({'label':label,'assertions':len(approved),'entities':report['existing_entities'],'native_projections':sum(bool(a['native_values']) for a in approved)}))
def review(path,label):
    if not re.fullmatch('[a-z0-9_]{1,100}',label):raise ValueError('Invalid immutable batch label')
    folder=RES/'approved_batches';folder.mkdir(exist_ok=True);lock=folder/'review.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:return _review(path,label)
    finally:lock.unlink(missing_ok=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('packet',type=Path);p.add_argument('label');args=p.parse_args();review(args.packet,args.label)
