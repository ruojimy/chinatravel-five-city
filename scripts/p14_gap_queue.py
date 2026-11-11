"""Export all remaining work and a resumable next restaurant batch; no network."""
import collections,gzip,hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow
RES=ROOT/'results/p14_targeted_completion'
def main():
    db=sqlite3.connect((ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    baseline=sqlite3.connect((ROOT/'data/business_catalog_v1_2_20261022/catalog.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    offers=collections.defaultdict(list)
    for rid,payload in db.execute('SELECT entity_id,payload FROM room_offers'):offers[rid].append(json.loads(payload))
    coverage=collections.defaultdict(collections.Counter);needs=collections.Counter();enriched=collections.Counter();candidates=collections.defaultdict(list)
    api_cached={x.stem for x in (RES/'private_api_raw').glob('*.json')};at=utcnow();work=0
    with gzip.open(RES/'remaining_business_gaps.jsonl.gz','wt',encoding='utf-8') as out:
      for rid,payload in db.execute('SELECT id,payload FROM records ORDER BY city,id'):
        x=json.loads(payload);kind=x['kind'];data=x['data'];c=coverage[kind];c['records']+=1
        original=json.loads(baseline.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0])
        newly_present=[k for k,v in data.items() if v is not None and original['data'].get(k) is None]
        enriched[kind]+=bool(newly_present)
        if kind=='restaurant':
            h=x.get('today_hours_structured') or {};flags={'price':data['price'] is not None,'cuisine':bool(data['cuisine']),
               'opening_hours':bool(h.get('segments')) or bool(data['opentime'] and data['endtime'])}
        elif kind=='attraction':flags={'ticket':data['price'] is not None,'opening_hours':bool(data['opentime'] and data['endtime']),
              'recommended_duration':data['recommendmintime'] is not None and data['recommendmaxtime'] is not None}
        else:flags={'room_price_reference':bool(offers[rid]),'room_type':any(z.get('room_type_name') for z in offers[rid]),
              'bed_count':data['numbed'] is not None}
        for key,value in flags.items():c['has:'+key]+=bool(value)
        c['all_requested_values_or_scoped_references']+=all(flags.values())
        missing=[k for k,value in flags.items() if not value]
        for key in missing:needs[kind+':'+key]+=1
        # Real-world freshness and verified identity are separate work, even if values exist.
        task={'entity_id':rid,'kind':kind,'city':x['city'],'name':x['name'],'missing_business_fields':missing,
           'needs_identity_or_time_verification':True,'city_assignment_verified':bool(x['source_locator'].get('provider_city_match')),
           'source_record_status':x['trust_status'],'planned_at':at,'network_executed_by_export':False,
           'next_action':'verify_city_and_identity_first' if not x['source_locator'].get('provider_city_match') else
              'date_room_context_via_normal_ui' if kind=='accommodation' else 'targeted_business_field_lookup',
           'no_defaults_no_source_clock_renewal':True}
        out.write(json.dumps(task,ensure_ascii=False,separators=(',',':'))+'\n');work+=1
        key=hashlib.sha256(rid.encode()).hexdigest()[:20]
        if kind=='restaurant' and rid.startswith('overture:') and x['source_locator'].get('provider_city_match') and missing and key not in api_cached:
            candidates[x['city']].append({'entity_id':rid,'city':x['city'],'name':x['name'],'kind':kind,
               'longitude_wgs84':data['lon'],'latitude_wgs84':data['lat'],'keywords':x['name'],'missing':missing})
    # Round-robin cities, so a dense city does not consume every first batch.
    selected=[]
    while len(selected)<60 and any(candidates.values()):
        for city in sorted(candidates):
            if candidates[city] and len(selected)<60:selected.append(candidates[city].pop(0))
    (RES/'next_restaurant_jobs.json').write_text(json.dumps({'prepared_at':at,'jobs':selected},ensure_ascii=False,indent=2),encoding='utf-8')
    report={'prepared_at':at,'records_in_gap_queue':work,'coverage':{k:dict(v) for k,v in coverage.items()},
       'remaining_missing_fields':dict(needs),'entities_with_at_least_one_new_nonnull_native_value':dict(enriched),
       'next_restaurant_jobs':len(selected),'never_queried_restaurant_entities_after_next_batch':sum(map(len,candidates.values())),
       'all_current_planning_ready':False,'counts_include_historical_or_conditional_references':True,'no_network_calls':True}
    (RES/'coverage_and_remaining.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));db.close();baseline.close()
if __name__=='__main__':main()
