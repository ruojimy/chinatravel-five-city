"""Read-only baseline + expansion recall, before any dynamic verification."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .expansion_store import ExpansionStore
from .freshness import field_policy, POLICIES, utcnow

def lookup(expansion,city,kind,*,baseline=None,tag=None,limit=6,now=None):
    if not isinstance(limit,int) or not 1<=limit<=40:raise ValueError('limit must be 1..40')
    store=ExpansionStore(expansion)
    try:
        matched=store.search(city,kind,tag=tag,limit=limit,now=now) if tag else []
        pool=store.search(city,kind,limit=40,now=now)
    finally:store.close()
    candidates=[dict(x,source_layer='expansion',tag_match=bool(tag)) for x in matched]
    # Unknown attributes remain candidates; they are not declared false.
    for x in pool:
        values=[t for t in x['record']['tags'] if t['tag']==tag] if tag else []
        if not tag or not values:candidates.append(dict(x,source_layer='expansion',tag_match=False))
    baseline_rows=0
    if baseline:
        path=Path(baseline)
        if not path.exists():raise FileNotFoundError(path)
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            baseline_rows=db.execute('SELECT count(*) FROM records WHERE lang=? AND city=? AND kind=?',('zh',city,kind)).fetchone()[0]
            for row in db.execute('SELECT payload FROM records WHERE lang=? AND city=? AND kind=? ORDER BY name LIMIT 40',('zh',city,kind)):
                r=json.loads(row[0]);match=bool(tag and any(t['tag']==tag and t['value'] is True for t in r['tags']))
                candidates.append({'record':r,'gate':{'planning_ready':False,'benchmark_only':True,
                    'planning_blockers':['unknown_source_time','legacy_frozen_benchmark_record']},
                    'source_layer':'baseline','tag_match':match})
        finally:db.close()
    # Reserve up to two unknown slots when matched candidates are available.
    known=[x for x in candidates if x['tag_match']];unknown=[x for x in candidates if not x['tag_match']]
    reserve=min(2,len(unknown),limit//3) if tag and known else 0
    selected=known[:limit-reserve]+unknown[:reserve]
    seen={x['record']['record_id'] for x in selected}
    for x in candidates:
        if len(selected)>=limit:break
        if x['record']['record_id'] not in seen:selected.append(x);seen.add(x['record']['record_id'])
    return {'checked_at':now or utcnow(),'city':city,'kind':kind,'requested_tag':tag,
        'candidates':selected,'baseline_city_kind_rows':baseline_rows,
        'uncovered_query_tags':([tag] if tag and not known else []),
        'ready_for_real_world_recommendation':False,'network_calls':0,
        'note':'Local recall only. Snapshot attributes and inferred recall tags do not certify current facts; mandatory weather/routes remain dynamic.'}

def verification_tasks(result,*,travel_date=None):
    tasks=[]
    for item in result['candidates']:
        r=item['record'];rid=r['record_id']
        for policy in ('identity','coordinates','opening_hours','price','closure'):
            tasks.append({'entity_id':rid,'field':policy,'reason':'missing_or_unverified_source_fact',
                'city':result['city'],'travel_date':travel_date,'provider':'bounded_multi_source'})
        if r['kind']=='accommodation':
            tasks.extend({'entity_id':rid,'field':f,'reason':'date_room_configuration_required',
                 'city':result['city'],'travel_date':travel_date,'provider':'bounded_multi_source'} for f in ('inventory','room_configuration','dynamic_price'))
    tasks.append({'entity_id':'weather:'+result['city'],'field':'weather_forecast' if travel_date else 'weather_now',
                  'city':result['city'],'travel_date':travel_date,'provider':'dynamic_weather','mandatory':True})
    tasks.append({'entity_id':'trip_routes','field':'route_duration_and_fare','city':result['city'],
         'travel_date':travel_date,'provider':'amap','mandatory':True,
         'missing_context':['verified_origin_destination_GCJ02','departure_at','citycode'],
         'note':'No static-speed substitution. Query actual transit segments once endpoints are chosen.'})
    return tasks
