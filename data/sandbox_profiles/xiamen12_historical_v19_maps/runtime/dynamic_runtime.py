"""Read-only replay of the pre-run dynamic snapshot; no credentials or network."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json,os

if not os.environ.get('CT_SANDBOX_PROFILE_ROOT'):
    raise ValueError('CT_SANDBOX_PROFILE_ROOT must identify an immutable evidence profile')
ROOT=Path(os.environ['CT_SANDBOX_PROFILE_ROOT']).resolve()
SNAPSHOT=ROOT/'data_integration/dynamic_snapshot_v2.json'

@lru_cache(maxsize=1)
def load_snapshot():
    raw=SNAPSHOT.read_bytes();data=json.loads(raw)
    if data.get('schema')!='chinatravel-dynamic-snapshot-v4.2':raise ValueError('unsupported snapshot')
    for entry in data['evidence_files']:
        p=(SNAPSHOT.parent/entry['path']).resolve()
        if not p.is_relative_to(SNAPSHOT.parent.resolve()) or sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('dynamic evidence changed: '+entry['path'])
    for entry in data['changed_direct_files']:
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT.resolve()) or sha256(p.read_bytes()).hexdigest()!=entry['after_sha256']:
            raise ValueError('dynamic data changed: '+entry['path'])
    data['snapshot_sha256']=sha256(raw).hexdigest()
    return data

def price_overlay(record_id,city,name):
    hits=[x for x in load_snapshot()['attraction_prices']
          if x['record_id']==record_id and x['city']==city and x['name']==name]
    if len(hits)>1:raise ValueError('ambiguous dynamic price')
    if not hits or hits[0].get('conflict_unresolved'):return None
    scope=hits[0].get('field_validity') or {}
    if scope and (os.environ.get('CT_TRAVEL_START_DATE')!=scope.get('trip_start_date') or
                  os.environ.get('CT_TRAVEL_END_DATE')!=scope.get('trip_end_date')):return None
    return dict(hits[0])

def entity_overlay(record_id,city,name,source_csv_sha256):
    hits=[x for x in load_snapshot().get('entity_overlays',[])
          if x['record_id']==record_id and x['city']==city and x['name']==name
          and x['source_csv_sha256']==source_csv_sha256]
    if len(hits)>1:raise ValueError('ambiguous dynamic entity overlay')
    if not hits:return None
    result=dict(hits[0]);fields=dict(result.get('fields') or {});inactive=[]
    for field,scope in (result.get('field_validity') or {}).items():
        if (os.environ.get('CT_TRAVEL_START_DATE')!=scope.get('trip_start_date') or
            os.environ.get('CT_TRAVEL_END_DATE')!=scope.get('trip_end_date')):
            fields.pop(field,None);inactive.append(field)
    result['fields']=fields;result['inactive_date_scoped_fields']=inactive
    return result

def recovered_lodging_grade(row_id,name,source_csv_sha256):
    snapshot=load_snapshot()
    grade_path=snapshot.get('recovered_lodging_grade_evidence')
    if not grade_path:return None
    if grade_path not in {x['path'] for x in snapshot['evidence_files']}:
        raise ValueError('recovered grade evidence is not hash-pinned')
    audit=json.loads((SNAPSHOT.parent/grade_path).read_text(encoding='utf-8'))
    if audit['csv_sha256']!=source_csv_sha256:return None
    hits=[r for r in audit['records'] if r['csv_id']==row_id and r['name']==name
          and r['source_name_matches']==1 and r['source_name_and_coordinate_matches']==1
          and r['historic_grade']=='L3']
    if len(hits)>1:raise ValueError('ambiguous recovered grade')
    return dict(hits[0]) if hits else None

def entity_access(payload):
    snapshot=load_snapshot();access=payload['access'];overlay=price_overlay(payload['record_id'],payload['city'],payload['name'])
    fields=access.get('dynamic_field_evidence')
    needed=(access.get('needs_time_evidence', False) or access.get('historical_segmented_hours', False) or bool(access.get('historical_price_context')) or access.get('grade') in ('L2','L3') or overlay is not None or (
        payload['kind']=='attraction' and payload['data'].get('price') is None))
    if needed and os.environ.get('CT_DYNAMIC_MODE','snapshot')=='live':
        import dynamic_live
        return dynamic_live.lookup(payload)
    return {'triggered':needed,'trigger':'catalog_entity_or_preflight',
            'mode':'frozen_snapshot_replay','status':('prefetched' if overlay or fields else 'not_prefetched_budget_exhausted') if needed else 'not_required',
            'provider_calls_used':snapshot['provider_calls_used'],'provider_budget':snapshot['provider_budget'],
            'provider_stages':snapshot.get('provider_stages',[]),'provider_total_calls_used':snapshot.get('provider_total_calls_used'),
            'snapshot_sha256':snapshot['snapshot_sha256'],'price_evidence':overlay,'field_evidence':fields,
            'notice':'No live fetch during this evaluation. Unprefetched fields remain unknown; no zero assumption without an actual search.'}

def transport_access(from_city,to_city,mode):
    snapshot=load_snapshot()
    if os.environ.get('CT_DYNAMIC_MODE','snapshot')=='live':
        import dynamic_live
        return dynamic_live.lookup_route(from_city,to_city,mode)
    direct=[x for x in snapshot['direct_trains'] if x['from_city']==from_city and x['to_city']==to_city]
    return {'triggered':True,'mode':'frozen_snapshot_replay',
            'status':'prefetched' if direct else 'not_prefetched_budget_exhausted',
            'requested_mode':mode,'provider':'amap','provider_calls_used':snapshot['provider_calls_used'],
            'provider_budget':snapshot['provider_budget'],'snapshot_sha256':snapshot['snapshot_sha256'],
            'provider_stages':snapshot.get('provider_stages',[]),'provider_total_calls_used':snapshot.get('provider_total_calls_used'),
            'direct_train_count':len(direct),'trip_date':None,'availability':'unknown',
            'notice':'Airfare is not inferred from a public-transport route; unprefetched fields remain unknown.'}

def direct_train(from_city,to_city,data):
    result=[x for x in load_snapshot()['direct_trains'] if x['from_city']==from_city and x['to_city']==to_city
            and x['record'].get('TrainID')==data.get('TrainID') and x['record'].get('From')==data.get('From')
            and x['record'].get('To')==data.get('To') and x['record'].get('BeginTime')==data.get('BeginTime')
            and x['record'].get('EndTime')==data.get('EndTime')]
    if len(result)>1:raise ValueError('ambiguous dynamic train')
    return dict(result[0]) if result else None
