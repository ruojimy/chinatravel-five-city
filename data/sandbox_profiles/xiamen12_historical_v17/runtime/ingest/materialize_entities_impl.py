"""Materialize safely extracted HTML entity fields in a new snapshot copy."""
from collections import defaultdict
from datetime import date,datetime,timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
import argparse,csv,json,shutil,sqlite3
from entity_evidence import parse
from materialize_live import CITIES,digest,finite_price

WEEK={'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'}
def time_ok(s):
    try:
        h,m=map(int,str(s).split(':'));return 0<=h<=23 and 0<=m<=59
    except (TypeError,ValueError):return False
def canonical_time(s):
    h,m=map(int,str(s).split(':'));return f'{h:02}:{m:02}'
def read_journal(path):
    db=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
    try:rows=db.execute('SELECT id,at_utc,status,request_json,raw_sha256,response_text,error_type FROM calls ORDER BY id').fetchall()
    finally:db.close()
    result=[]
    for id,at,status,request,h,body,error in rows:
        e={'id':id,'at':at,'status':status,'request':json.loads(request),'raw_sha256':h,'body':body,'error':error}
        if status!='ok' or body is None:e['reject']='request_failed'
        elif digest(body.encode('utf-8'))!=h:e['reject']='raw_hash_mismatch'
        else:
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(at)).total_seconds()
                if not 0<=age<=72*3600:e['reject']='stale_or_future_observation'
            except ValueError:e['reject']='invalid_observation_time'
        result.append(e)
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--journal',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--trip-date');ap.add_argument('--stage-budget',type=int,default=12);args=ap.parse_args()
    base=args.base.resolve();out=args.output.resolve();journal=args.journal.resolve()
    if out.exists() or out==base or base in out.parents:raise ValueError('output must be a new directory outside the parent snapshot')
    trip=date.fromisoformat(args.trip_date) if args.trip_date else None
    snapshot=json.loads((base/'data_integration/dynamic_snapshot_v2.json').read_text(encoding='utf-8'))
    for e in snapshot['evidence_files']:
        path=(base/'data_integration'/e['path']).resolve()
        if not path.is_relative_to((base/'data_integration').resolve()) or digest(path.read_bytes())!=e['sha256']:raise ValueError('parent evidence invalid')
    for e in snapshot['changed_direct_files']:
        path=(base/e['path']).resolve()
        if not path.is_relative_to(base) or digest(path.read_bytes())!=e['after_sha256']:raise ValueError('parent data invalid')
    events=read_journal(journal);groups=defaultdict(list);audit=[]
    used=sum(1 for e in events if e['status'] not in ('budget_exhausted','provider_paused'))
    if args.stage_budget<1 or used>args.stage_budget:raise ValueError('entity stage budget inconsistent')
    if not any(e.get('sha256')==digest(journal.read_bytes()) for e in snapshot['evidence_files']):
        snapshot.setdefault('retrieval_stages',[]).append({'stage':'entity_public_detail','provider_calls_used':used,
            'budget':args.stage_budget,'notice':'Direct HTTPS source retrieval; independent of Amap phase budgets.'})
    for e in events:
        q=e['request'];identity=(q.get('record_id'),q.get('city'),q.get('kind'),q.get('name'))
        if e.get('reject'):audit.append({'call_id':e['id'],'reason':e['reject']});continue
        if (q.get('city') not in CITIES or q.get('kind') not in ('attraction','restaurant','accommodation')
                or not isinstance(q.get('name'),str) or not q['name']):
            audit.append({'call_id':e['id'],'reason':'invalid_identity'});continue
        url=urlparse(q.get('url') or '')
        if url.scheme!='https' or not url.hostname:audit.append({'call_id':e['id'],'reason':'untrusted_url'});continue
        slug=CITIES[q['city']][0];directory={'attraction':'attractions','restaurant':'restaurants','accommodation':'accommodations'}[q['kind']]
        filename=(f'restaurants_{slug}.csv' if q['kind']=='restaurant' else directory+'.csv')
        csvpath=base/'expanded/G3_ext11/chinatravel/environment/database'/directory/slug/filename
        with csvpath.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        matches=[r for r in rows if f"{q['kind']}:{slug}:{r.get('id')}"==q['record_id'] and r.get('name')==q['name']]
        if len(matches)!=1:audit.append({'call_id':e['id'],'reason':'source_record_not_unique'});continue
        extracted=parse(e['body'],q['name'],q['city'],q['kind'],q['url'])
        if extracted['status']!='identity_matched':audit.append({'call_id':e['id'],'reason':extracted['status']});continue
        e.update(row=matches[0],csv_sha=digest(csvpath.read_bytes()),extracted=extracted,host=url.hostname)
        groups[identity].append(e)
    out.mkdir(parents=True)
    shutil.copytree(base/'expanded',out/'expanded',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    dat=out/'data_integration';dat.mkdir()
    for x in snapshot['evidence_files']:
        src=base/'data_integration'/x['path'];dst=dat/x['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for src in (base/'data_integration').glob('*.py'):shutil.copy2(src,dat/src.name)
    number=1
    while (dat/f'entity_capture_{number}.sqlite3').exists():number+=1
    capture=dat/f'entity_capture_{number}.sqlite3';shutil.copy2(journal,capture)
    snapshot['evidence_files'].append({'path':capture.name,'sha256':digest(capture.read_bytes())})
    changes=[]
    for (rid,city,kind,name),evs in groups.items():
        row=evs[0]['row'];csv_sha=evs[0]['csv_sha']
        existing=next((x for x in snapshot.get('entity_overlays',[]) if x.get('record_id')==rid),None)
        overlay=existing or {'record_id':rid,'city':city,'name':name,'source_csv_sha256':csv_sha,'fields':{},'field_provenance':{},'status':'conditional_reference'}
        overlay.setdefault('fields',{});overlay.setdefault('field_provenance',{});overlay.setdefault('field_conflicts',[])
        obs=[]
        for e in evs:
            obs.append({'call_id':e['id'],'url':e['request']['url'],'host':e['host'],'source_group':e['request'].get('source_group'),
                        'independence_status':'not_established','at_utc':e['at'],
                        'raw_sha256':e['raw_sha256'],'purpose':e['request'].get('purpose'),'extracted':e['extracted']})
        reference={'schema':'chinatravel-entity-evidence-v1','record_id':rid,'city':city,'kind':kind,'name':name,
                   'journal':capture.name,'journal_sha256':digest(capture.read_bytes()),'observations':obs}
        safe=rid.replace(':','_');proof=dat/f'entity_evidence_{safe}_{number}.json'
        proof.write_text(json.dumps(reference,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        ph=digest(proof.read_bytes());snapshot['evidence_files'].append({'path':proof.name,'sha256':ph})
        outcomes=[]
        values={x['price'] for e in evs if e['request'].get('purpose') in ('ticket_price','hotel_price')
                for x in e['extracted']['offers']}
        discarded=[v for e in evs for v in e['extracted']['discarded']]
        if len(values)>1:outcomes.append({'field':'price','status':'conflict_between_sources','values':sorted(values)})
        elif len(values)==1 and discarded:outcomes.append({'field':'price','status':'ambiguous_offer_or_category'})
        elif len(values)==1:
            value=next(iter(values));old=finite_price(row.get('price'))
            if kind=='accommodation' and str(row.get('price_status') or '').lower().startswith('estimated'):
                old=None
            offers=[x['offer'] for e in evs for x in e['extracted']['offers'] if x['price']==value]
            restricted=any(x.get('validFrom') or x.get('validThrough') or x.get('priceValidUntil') for x in offers)
            if restricted and trip is not None and any((x.get('validFrom') and args.trip_date<x['validFrom']) or
                    (x.get('validThrough') and args.trip_date>x['validThrough']) or
                    (x.get('priceValidUntil') and args.trip_date>x['priceValidUntil']) for x in offers):
                outcomes.append({'field':'price','status':'outside_source_validity'});value=None
            if kind=='accommodation':
                matching=[x for e in evs for x in e['extracted']['offers'] if x['price']==value]
                beds=finite_price(row.get('numbed'))
                dates_ok=(trip is not None and all(e['request'].get('trip_date')==args.trip_date and
                          isinstance(e['request'].get('checkout_date'),str) and
                          e['request']['checkout_date']>args.trip_date for e in evs)
                          and len({e['request']['checkout_date'] for e in evs})==1)
                room_ok=all(finite_price(((x['offer'].get('itemOffered') or {}).get('occupancy') or {}).get('value'))==beds for x in matching)
                if not dates_ok or not room_ok:
                    outcomes.append({'field':'price','status':'unmatched_trip_date_or_room_occupancy'});value=None
            elif kind!='attraction':
                outcomes.append({'field':'price','status':'not_proven_per_person'});value=None
            prior_price=next((x for x in snapshot.get('attraction_prices',[]) if x.get('record_id')==rid),None)
            if value is not None and kind=='attraction' and prior_price and finite_price(prior_price.get('price')) is not None and abs(float(prior_price['price'])-value)>0.1:
                prior_price['conflict_unresolved']=True
                overlay['field_conflicts'].append({'field':'price','prior_dynamic':prior_price['price'],'observed':value,'evidence_path':proof.name})
                outcomes.append({'field':'price','status':'conflict_with_prior_dynamic_evidence'});value=None
            if value is not None and old is not None and abs(old-value)>0.1:
                overlay['field_conflicts'].append({'field':'price','benchmark':old,'observed':value,'evidence_path':proof.name})
                outcomes.append({'field':'price','status':'conflict_with_benchmark'})
            elif value is not None and old is not None:
                outcomes.append({'field':'price','status':'matches_benchmark_source_reference'})
            elif value is not None and kind=='attraction':
                if not any(x.get('record_id')==rid for x in snapshot.get('attraction_prices',[])):
                    snapshot.setdefault('attraction_prices',[]).append({'record_id':rid,'city':city,'name':name,'price':value,
                      'status':'source_reference_no_trip_date' if trip is None else 'dated_single_source_reference',
                      'evidence_path':proof.name,'evidence_sha256':ph,'trip_date':args.trip_date,
                      'field_validity':({'trip_start_date':args.trip_date,'trip_end_date':args.trip_date} if trip is not None else None)})
                    outcomes.append({'field':'price','status':'conditional_source_reference'})
            elif value is not None and kind=='accommodation' and old is None:
                overlay['fields']['price']=value;overlay['field_provenance']['price']='dated_room_occupancy_matched_source'
                overlay.setdefault('field_validity',{})['price']={'trip_start_date':args.trip_date,
                    'trip_end_date':evs[0]['request']['checkout_date']}
                outcomes.append({'field':'price','status':'conditional_dated_room_reference'})
        elif kind=='attraction':
            searched=[e for e in evs if e['request'].get('purpose')=='ticket_price' and not e['extracted']['discarded']]
            old=finite_price(row.get('price'))
            groups_found={e['request'].get('source_group') for e in searched if e['request'].get('source_group')}
            if old is not None:
                outcomes.append({'field':'price','status':'benchmark_price_already_present'})
            elif len({e['host'] for e in searched})>=2 and len(groups_found)>=2:
                if not any(x.get('record_id')==rid for x in snapshot.get('attraction_prices',[])):
                    snapshot.setdefault('attraction_prices',[]).append({'record_id':rid,'city':city,'name':name,'price':0,
                      'status':'user_authorized_zero_assumption_after_search','evidence_path':proof.name,'evidence_sha256':ph})
                    outcomes.append({'field':'price','status':'zero_assumption_after_two_source_searches',
                                     'independence_status':'not_established'})
            else:outcomes.append({'field':'price','status':'insufficient_price_searches'})
        # A city authority may publish seasonal hours in a non-JSON table.
        # Preserve conflicting observations without flattening their seasons
        # or silently overwriting the benchmark's hours.
        for e in evs:
            if e['request'].get('purpose')!='opening_hours':continue
            extracted=e['extracted']
            if extracted.get('parser')!='xian_culture_bureau_museum_table':continue
            observed=[[canonical_time(a),canonical_time(b)] for a,b in extracted.get('time_ranges',[])
                      if time_ok(a) and time_ok(b)]
            old=[row.get('opentime'),row.get('endtime')]
            if observed and all(old) and any(pair!=old for pair in observed):
                conflict={'field':'opening_hours','state':'unresolved_source_conflict',
                          'benchmark':old,'observed_ranges':observed,
                          'source_schedule':extracted.get('noncanonical_hours'),
                          'evidence_path':proof.name,'evidence_sha256':ph}
                if conflict not in overlay['field_conflicts']:overlay['field_conflicts'].append(conflict)
                outcomes.append({'field':'opening_hours','status':'conflict_with_seasonal_government_table'})
        ranges=[]
        for e in evs:
            if e['request'].get('purpose')!='opening_hours' and e['extracted'].get('parser')!='beilin_museum_notice_4627':continue
            for h in e['extracted']['hours']:
                if not time_ok(h['opens']) or not time_ok(h['closes']):continue
                h=dict(h);h['opens']=canonical_time(h['opens']);h['closes']=canonical_time(h['closes'])
                if set(h['days'])!=WEEK:
                    if (row.get('opentime'),row.get('endtime'))==(h['opens'],h['closes']):
                        outcomes.append({'field':'opening_hours','status':'matches_benchmark_days_unconfirmed'})
                    else:outcomes.append({'field':'opening_hours','status':'unresolved_day_scope'})
                    continue
                if h['validFrom'] or h['validThrough']:
                    if trip is None or h['validFrom'] and args.trip_date<h['validFrom'] or h['validThrough'] and args.trip_date>h['validThrough']:continue
                ranges.append((h['opens'],h['closes']))
        if len(set(ranges))>1:outcomes.append({'field':'opening_hours','status':'conflict_between_sources'})
        elif ranges:
            start,end=ranges[0];old=(row.get('opentime'),row.get('endtime'))
            if all(old) and old!=(start,end):
                overlay['field_conflicts'].append({'field':'opening_hours','benchmark':old,'observed':[start,end],'evidence_path':proof.name})
                outcomes.append({'field':'opening_hours','status':'conflict_with_benchmark'})
            elif not any(old):
                overlay['fields'].update(opentime=start,endtime=end);overlay['field_provenance'].update(opentime='weekly_source_reference',endtime='weekly_source_reference')
                if trip is not None:
                    for field in ('opentime','endtime'):
                        overlay.setdefault('field_validity',{})[field]={'trip_start_date':args.trip_date,'trip_end_date':args.trip_date}
                outcomes.append({'field':'opening_hours','status':'weekly_conditional_source_reference'})
        overlay.setdefault('observations',[]).append({'evidence_path':proof.name,'evidence_sha256':ph,'outcomes':outcomes})
        if existing is None:snapshot.setdefault('entity_overlays',[]).append(overlay)
        changes.append({'record_id':rid,'outcomes':outcomes,'evidence':proof.name})
    report={'schema':'entity-materialization-audit-v1','trip_date':args.trip_date,'entities':changes,'rejections':audit,
            'boundary':'Schema.org values are source observations, not confirmed bookings; field conflicts remain unresolved.'}
    report_path=dat/f'entity_materialization_audit_{number}.json';report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    snapshot['evidence_files'].append({'path':report_path.name,'sha256':digest(report_path.read_bytes())})
    (dat/'dynamic_snapshot_v2.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Apply the reader contract in this new copy. The application must set the
    # explicit trip bounds, otherwise date-bound fields remain unavailable.
    runtime=out/'expanded/dynamic_runtime.py';text=runtime.read_text(encoding='utf-8')
    old="""    if len(hits)>1:raise ValueError('ambiguous dynamic entity overlay')
    return dict(hits[0]) if hits else None
"""
    new="""    if len(hits)>1:raise ValueError('ambiguous dynamic entity overlay')
    if not hits:return None
    result=dict(hits[0]);fields=dict(result.get('fields') or {});inactive=[]
    for field,scope in (result.get('field_validity') or {}).items():
        if (os.environ.get('CT_TRAVEL_START_DATE')!=scope.get('trip_start_date') or
            os.environ.get('CT_TRAVEL_END_DATE')!=scope.get('trip_end_date')):
            fields.pop(field,None);inactive.append(field)
    result['fields']=fields;result['inactive_date_scoped_fields']=inactive
    return result
"""
    if text.count(old)==1:text=text.replace(old,new)
    elif new not in text:raise ValueError('runtime reader shape changed; refusing unsafe patch')
    old="""    if len(hits)>1:raise ValueError('ambiguous dynamic price')
    return dict(hits[0]) if hits else None
"""
    new="""    if len(hits)>1:raise ValueError('ambiguous dynamic price')
    if not hits:return None
    if hits[0].get('conflict_unresolved'):return None
    scope=hits[0].get('field_validity') or {}
    if scope and (os.environ.get('CT_TRAVEL_START_DATE')!=scope.get('trip_start_date') or
                  os.environ.get('CT_TRAVEL_END_DATE')!=scope.get('trip_end_date')):return None
    return dict(hits[0])
"""
    prior=new.replace("    if hits[0].get('conflict_unresolved'):return None\n",'')
    if text.count(old)==1:text=text.replace(old,new)
    elif prior in text and new not in text:text=text.replace(prior,new)
    elif new not in text:raise ValueError('runtime price reader shape changed')
    old="""            'provider_calls_used':snapshot['provider_calls_used'],'provider_budget':snapshot['provider_budget'],
"""
    new="""            'provider_calls_used':snapshot['provider_calls_used'],'provider_budget':snapshot['provider_budget'],
            'provider_stages':snapshot.get('provider_stages',[]),'provider_total_calls_used':snapshot.get('provider_total_calls_used'),
"""
    if old in text and new not in text:text=text.replace(old,new)
    elif new not in text:raise ValueError('runtime provider accounting shape changed')
    old="""            'provider_budget':snapshot['provider_budget'],'snapshot_sha256':snapshot['snapshot_sha256'],
"""
    new="""            'provider_budget':snapshot['provider_budget'],'snapshot_sha256':snapshot['snapshot_sha256'],
            'provider_stages':snapshot.get('provider_stages',[]),'provider_total_calls_used':snapshot.get('provider_total_calls_used'),
"""
    if old in text and new not in text:text=text.replace(old,new)
    elif new not in text:raise ValueError('runtime route accounting shape changed')
    runtime.write_text(text,encoding='utf-8')
    adapter=out/'expanded/sandbox_adapter.py';text=adapter.read_text(encoding='utf-8')
    old="""        if source_status.startswith('estimated'):
            if data.get('price') is not None:
                price_reference = data.get('price')
            data['price'] = None
"""
    new="""        if source_status.startswith('estimated'):
            price_reference = _clean_numeric(row.get('price'))
            if (dynamic_fields and 'price' in dynamic_fields.get('fields',{})
                    and dynamic_fields.get('field_provenance',{}).get('price')=='dated_room_occupancy_matched_source'):
                data['price'] = dynamic_fields['fields']['price']
            else:
                data['price'] = None
"""
    prior="""        if source_status.startswith('estimated'):
            price_reference = _clean_numeric(row.get('price'))
            if not (dynamic_fields and 'price' in dynamic_fields.get('fields',{})
                    and dynamic_fields.get('field_provenance',{}).get('price')=='dated_room_occupancy_matched_source'):
                data['price'] = None
"""
    if text.count(old)==1:text=text.replace(old,new)
    elif prior in text:text=text.replace(prior,new)
    elif new not in text:raise ValueError('adapter price gate shape changed')
    old="""        raw_time_ok = kind == 'accommodation' or (
            _time_valid(row.get('opentime')) and _time_valid(row.get('endtime')))
        main = bool(poi_ok and position_ok and raw_time_ok and grade != 'L4')
"""
    new="""        main = bool(poi_ok and position_ok and time_ok and grade != 'L4')
"""
    if text.count(old)==1:text=text.replace(old,new)
    elif new not in text:raise ValueError('adapter hours gate shape changed')
    adapter.write_text(text,encoding='utf-8')
    print(json.dumps({'entities':len(changes),'rejections':len(audit),'snapshot':str(dat/'dynamic_snapshot_v2.json')},ensure_ascii=False))

if __name__=='__main__':main()
