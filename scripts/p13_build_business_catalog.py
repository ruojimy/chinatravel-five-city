"""Create a new business-enriched snapshot without changing P12 source data."""
from __future__ import annotations
import collections,copy,gzip,hashlib,json,math,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_completion import api_restaurant,complete_native,validate_room_offer,validate_operator_field
from shorttrip.business_archives import name_aliases
from shorttrip.expansion_contract import validate_record
from shorttrip.expansion_store import ExpansionStore
from shorttrip.freshness import canonical,field_policy,utcnow
from shorttrip.travel_catalog import digest_file
from shorttrip.dynamic.opendata import gcj02_to_wgs84
SOURCE=ROOT/'data/expansion_catalog_v1_1_20261022/catalog.sqlite3'
OUT=ROOT/'data/business_catalog_v1_2_20261022';RESULT=ROOT/'results/p13_business_completion'

def evidence(sid,url,raw,at,*,observed=None,authority='structured_provider',licence='api_terms'):
    text=canonical(raw)
    return {'evidence_id':'business:'+hashlib.sha256((sid+url+at+text).encode()).hexdigest(),
      'source_id':sid,'source_url':url,'raw_text':text,'raw_sha256':hashlib.sha256(text.encode()).hexdigest(),
      'retrieved_at':at,'observed_at':observed,'source_published_at':None,'source_updated_at':None,
      'authority':authority,'licence_status':licence}
def set_field(record,key,value,ev,*,status='source_value',until=None,note=None):
    record['data'][key]=value
    record['field_provenance'][key]={'source_id':ev['source_id'],'source_url':ev['source_url'],
       'observed_at':ev['observed_at'],'status':status,'evidence_id':ev['evidence_id'],'valid_until':until,
       'source_note':note}
def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'catalog.sqlite3').exists():raise FileExistsError('Use a new immutable business version')
    source=sqlite3.connect(SOURCE.resolve().as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    before=digest_file(SOURCE);evs={};updates=collections.defaultdict(list);counts=collections.Counter();field_counts=collections.Counter()
    def keep(ev):evs[ev['evidence_id']]=ev;return ev
    # History is attached as dated reference, never relabelled as a current fact.
    with gzip.open(RESULT/'archive_enrichment.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            item=json.loads(line);ev=keep(evidence(item['source_id'],item['source_url'],item['raw_facts'],
               item['retrieved_at'],authority='historical_third_party_archive',licence='upstream_reuse_unverified'))
            updates[item['record_id']].append(('archive',item,ev))
    hotels=json.loads((RESULT/'hotel_source_probe.json').read_text(encoding='utf-8'))
    by_hotel={h['entity_id']:h for h in hotels['hotels']}
    offers=[];identity_checks=[]
    for offer in hotels['room_offers']:
        verdict=validate_room_offer(offer,now=utcnow())
        if not verdict['ok']:raise ValueError({'offer':offer['offer_id'],'errors':verdict['errors']})
        for item in offer['screenshot_evidence']:
            if digest_file(RESULT/item['path'])!=item['sha256']:raise ValueError('Screenshot hash mismatch')
        ev=keep(evidence(offer['source_id'],offer['source_url'],offer,offer['retrieved_at'],
             observed=offer['observed_at'],authority='primary_operator'))
        h=by_hotel[offer['entity_id']];feature=h.get('hotel_level_features') or {}
        feature_ev=keep(evidence('hotel_official_amenities',feature['source_url'],feature,
             feature.get('retrieved_at') or offer['retrieved_at'],observed=feature.get('observed_at'),authority='primary_operator'))
        updates[offer['entity_id']].append(('hotel',{'offer':offer,'hotel':h,'gate':verdict,'feature_evidence':feature_ev},ev))
        offers.append((offer,verdict,ev))
        slug={'XMNHIHI':'xiamen','XIYHIHI':'xian'}.get(offer.get('official_property_code'))
        if slug:
            packet=json.loads((RESULT/'private_api_raw'/(slug+'_hilton_identity.json')).read_text(encoding='utf-8'))
            row=packet['response']['pois'][0];lon,lat=map(float,row['location'].split(','));wl,wa=gcj02_to_wgs84(lon,lat)
            prior=h['candidate_coordinates'];distance=111195*math.hypot(wa-prior['lat'],(wl-prior['lon'])*math.cos(math.radians(wa)))
            identity_checks.append({'entity_id':offer['entity_id'],'official_name':offer['hotel_name'],
              'amap_name':row['name'],'amap_address':row['address'],'prior_address':h.get('candidate_original_address'),
              'official_address':h.get('official_address'),'coordinate_distance_metres_after_conversion':round(distance,3),
              'coordinate_transform':'gcj02_to_wgs84 four-iteration numerical inverse; uncertainty retained',
              'source_clock':packet['meta']['retrieved_at'],'manual_identity_status':'name_street_number_city_and_near_coordinates_support_binding',
              'independent_upstream_lineage_confirmed':False,'not_a_current_room_quote_refresh':True})
    # Match map restaurant rows to existing exact aliases, else retain a separate
    # provider entity. No fuzzy-name joining or hotel/restaurant conflation.
    index=collections.defaultdict(set)
    for row in source.execute("SELECT id,city,name FROM records WHERE kind='restaurant' AND provider_city_match=1"):
        for alias in name_aliases(row['name']):index[(row['city'],alias)].add(row['id'])
    new={};api_rows={};api_evidence={}
    names=['xian_restaurants','xiamen_restaurants','xiamen_local_restaurants']
    names += [p.stem for p in sorted((RESULT/'private_api_raw').glob('*_restaurants_page*.json'))]
    for name in names:
        packet=json.loads((RESULT/'private_api_raw'/(name+'.json')).read_text(encoding='utf-8'));meta=packet['meta']
        for raw in packet['response'].get('pois',[]):
            record=api_restaurant(raw,meta)
            if record is None:counts['excluded_non_restaurant_api_rows']+=1;continue
            rid=record['record_id'];api_rows[rid]=(record,raw,meta)
    for rid,(record,raw,meta) in api_rows.items():
        ev=keep(evidence('amap_business_snapshot',meta['endpoint'],raw,meta['retrieved_at']))
        hits=set()
        for alias in name_aliases(record['name']):hits|=index.get((record['city'],alias),set())
        if len(hits)==1:
            target=next(iter(hits));updates[target].append(('restaurant',record,ev));counts['matched_existing_restaurants']+=1
        else:
            record['source_locator']['evidence_id']=ev['evidence_id'];new[rid]=record;counts['new_provider_restaurant_records']+=1
        api_evidence[rid]=ev
    store=ExpansionStore(OUT/'catalog.sqlite3',create=True)
    store.db.executescript('''CREATE TABLE field_assertions(entity_id TEXT,field TEXT,value TEXT,scope TEXT,evidence_id TEXT);
        CREATE TABLE room_offers(offer_id TEXT PRIMARY KEY,entity_id TEXT,payload TEXT,gate TEXT,evidence_id TEXT);
        CREATE TABLE identity_checks(entity_id TEXT,payload TEXT);
        CREATE TABLE historical_references(entity_id TEXT,payload TEXT,evidence_id TEXT);
        CREATE TABLE official_operator_fields(entity_scope TEXT,field TEXT,payload TEXT);''')
    store.load_evidence(evs.values(),[],registry={})
    complete=collections.Counter();changed_ids=set();snapshot_at=utcnow()
    def records():
        with gzip.open(OUT/'records.jsonl.gz','wt',encoding='utf-8',newline='\n') as target:
            for row in source.execute('SELECT payload FROM records ORDER BY id'):
                r=json.loads(row['payload'])
                for kind,item,ev in updates.get(r['record_id'],[]):
                    changed_ids.add(r['record_id'])
                    if kind=='archive':
                        r.setdefault('historical_reference_ids',[]).append(ev['evidence_id'])
                        for field,value in item['native_values'].items():
                            if r['data'].get(field) is None:
                                set_field(r,field,value,ev,note='2023 archive reference; unknown fact observation age; refresh before real travel')
                                field_counts['historical:'+field]+=1
                        r['uncertainty_flags']+=['historical_business_values_not_current','upstream_archive_reuse_unverified']
                    elif kind=='hotel':
                        offer=item['offer'];gate=item['gate'];h=item['hotel'];f=h['hotel_level_features'];fe=item['feature_evidence']
                        set_field(r,'featurehoteltype',f['featurehoteltype'],fe,until=f.get('valid_until'))
                        set_field(r,'numbed',offer['bed_count'],ev,note='Only for room_type_id '+str(offer.get('room_type_id')))
                        field_counts['hotel:numbed']+=1;field_counts['hotel:featurehoteltype']+=1
                        if gate['native_price_per_room_night'] is not None:
                            set_field(r,'price',gate['native_price_per_room_night'],ev,until=offer['valid_until'],
                                note='Date/occupancy/rate/room/tax bound offer; stored value can be expired, recheck gate')
                            field_counts['hotel:price']+=1
                        r['selected_room_offer_id']=offer['offer_id'];r['room_offer_context']=gate['context']
                        r['hotel_name_aliases']=[r['name'],offer['hotel_name']]
                        r['uncertainty_flags']+=['price_room_date_context_required','quote_not_a_booking',
                            'current_price_requires_requery','identity_link_review_recorded_separately']
                    else:
                        for field in ('price','cuisine','recommendedfood','opentime','endtime'):
                            value=item['data'].get(field)
                            if value is not None:
                                set_field(r,field,value,ev,note='AMap provider snapshot, unknown fact update time')
                                field_counts['restaurant:'+field]+=1
                        r['business_rules']=item['business_rules'];r['uncertainty_flags']+=item['uncertainty_flags']
                r['catalogued_at']=snapshot_at
                v=validate_record(r,now=snapshot_at)
                if not v['discovery_ok']:raise ValueError(v)
                counts['records']+=1;counts['planning_ready']+=v['planning_ready']
                if complete_native(r):complete[r['kind']]+=1
                target.write(canonical(r)+'\n');yield r
            for r in new.values():
                for key in r['field_provenance']:r['field_provenance'][key]['evidence_id']=api_evidence[r['record_id']]['evidence_id']
                counts['records']+=1;counts['planning_ready']+=validate_record(r,now=snapshot_at)['planning_ready']
                if complete_native(r):complete[r['kind']]+=1
                target.write(canonical(r)+'\n');yield r
    store.load(records(),now=snapshot_at)
    with store.db:
        for offer,gate,ev in offers:
            store.db.execute('INSERT INTO room_offers VALUES(?,?,?,?,?)',(offer['offer_id'],offer['entity_id'],canonical(offer),canonical(gate),ev['evidence_id']))
            for field in ('bed_count','room_type_name','price_breakdown'):
                store.db.execute('INSERT INTO field_assertions VALUES(?,?,?,?,?)',(offer['entity_id'],field,canonical(offer[field]),'same_date_room_offer',ev['evidence_id']))
        for rid,items in updates.items():
            for kind,item,ev in items:
                if kind=='archive':store.db.execute('INSERT INTO historical_references VALUES(?,?,?)',(rid,canonical(item),ev['evidence_id']))
        for item in identity_checks:store.db.execute('INSERT INTO identity_checks VALUES(?,?)',(item['entity_id'],canonical(item)))
        for rid,(record,raw,meta) in api_rows.items():
            for field,value in record['business_rules'].items():
                if value is not None:store.db.execute('INSERT INTO field_assertions VALUES(?,?,?,?,?)',
                    (rid,field,canonical(value),'map_provider_snapshot_2026-10-22',api_evidence[rid]['evidence_id']))
        official=json.loads((RESULT/'official_attraction_fields.json').read_text(encoding='utf-8'))
        for item in official['captured_fields']:
            gate=validate_operator_field(item)
            if not gate['ok']:raise ValueError(gate)
            store.db.execute('INSERT INTO official_operator_fields VALUES(?,?,?)',(item['entity_scope'],item['field'],canonical(item)))
    integrity=store.db.execute('PRAGMA integrity_check').fetchone()[0]
    store.close();source.close()
    if digest_file(SOURCE)!=before:raise ValueError('P12 baseline changed')
    report={'built_at':snapshot_at,'version':'business-catalog-v1.2-20261022','counts':dict(counts),
       'existing_records_enriched':len(changed_ids),'concrete_field_updates':dict(field_counts),
       'all_native_business_keys_nonmissing_by_kind':dict(complete),'note_completeness':'Values may be historical or expired; complete keys are not planning-ready/fresh facts.',
       'evidence_snapshots':len(evs),'room_offers':len(offers),'unambiguous_itemized_room_offers':sum(not g['budget_use_blockers'] for _,g,_ in offers),
       'room_offers_current_fresh':sum(g['current_quote_fresh'] for _,g,_ in offers),'original_p12_unchanged':True,
       'official_operator_field_assertions':len(official['captured_fields']),
       'original_p12_sha256':before,'sqlite_integrity':integrity,'identity_checks':identity_checks,
       'files':[{'file':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest_file(p)} for p in (OUT/'catalog.sqlite3',OUT/'records.jsonl.gz')],
       'online_dynamic_savings_measured':None,'doubling_completed':False,
       'distribution':'Includes map API/private browser evidence; local research version. Do not redistribute raw page/API payloads as an open dataset without source-specific rights.'}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (RESULT/'business_catalog_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('counts','existing_records_enriched','concrete_field_updates','all_native_business_keys_nonmissing_by_kind','room_offers','unambiguous_itemized_room_offers','sqlite_integrity')},ensure_ascii=False))
if __name__=='__main__':main()
