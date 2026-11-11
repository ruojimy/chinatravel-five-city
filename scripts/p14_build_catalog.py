"""Build a new immutable snapshot: enrich existing entities, never inflate counts."""
import collections,copy,gzip,hashlib,json,re,sqlite3,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from shorttrip.scoped_business import today_hours,validate_hours,qunar_fields,match_target
from shorttrip.business_archives import name_aliases
from shorttrip.business_completion import api_restaurant,validate_room_offer
from shorttrip.expansion_store import ExpansionStore
from shorttrip.expansion_contract import validate_record,validate_evidence
from shorttrip.freshness import canonical,utcnow
from shorttrip.travel_catalog import digest_file
from p13_build_business_catalog import evidence,set_field

SOURCE=ROOT/'data/business_catalog_v1_2_20261022/catalog.sqlite3'
OUT=ROOT/'data/business_catalog_v1_4_20261022';RES=ROOT/'results/p14_targeted_completion'

def room_offers():
    offers=[];folder=RES/'browser'
    old=ROOT/'results/p13_business_completion/browser_recovery_20261022/tongcheng_conditional_offer.json'
    existing=json.loads(old.read_text(encoding='utf-8'))
    for item in existing['screenshot_evidence']:
        item['path']=str((old.parent/item['path']).relative_to(ROOT))
    offers.append(existing)
    for slug in ('lanyue','kempinski'):
        data=json.loads((folder/(slug+'_rooms.json')).read_text(encoding='utf-8'))
        for index,room in enumerate(data['rooms']):
            beds=re.findall(r'(\d+)张([\d.]+)米([^\n]+床)',room['excerpt'])
            if len(beds)!=1:raise ValueError('Expected one explicit room bed description')
            number,width,bedtype=beds[0];at=room['observed_at'];png=folder/room['screenshot']
            offer={'offer_id':f"tongcheng-ui-{data['property_id']}-{slug}-{index}-20261024",
             'entity_id':data['entity_candidate'],'hotel_name':data['name'],'provider_property_id':data['property_id'],
             'hotel_address_quote':data['address'],'room_type_id':None,'room_type_name':room['room_type_name'],
             'room_type_id_status':'Unmapped supplier room ID; visible room label retained without invention',
             'bed_count':int(number),'bed_width_metres':float(width),'bed_type':bedtype,
             'bed_count_quote':beds[0][0]+'张'+beds[0][1]+'米'+beds[0][2],
             'rooms_reserved':1,'adults':2,'children':0,'checkin':'2026-10-24','checkout':'2026-10-25',
             'nights':1,'currency':'CNY','actual_user_trip':False,'rate_plan_id':None,
             'rate_plan_name':'无餐食套餐；'+data['discount_quote'],
             'membership_required':None,'breakfast_included':False,
             'price_breakdown':{'room_base':None,'service_charge':None,'tax_and_government_charge':None,
                 'displayed_stay_total':data['displayed_price']},
             'price_semantics':data['price_status'],'display_rounding_quote':'小数点向上取整展示',
             'quote_status':'conditional_discount_or_cashback_no_confirmed_tax_components',
             'not_an_upfront_payment_guarantee':True,'source_id':'tongcheng_normal_browser_ui','source_url':data['source_url'],
             'observed_at':at,'retrieved_at':at,'source_published_at':None,'source_updated_at':None,
             'valid_until':(datetime.fromisoformat(at.replace('Z','+00:00'))+timedelta(seconds=300)).isoformat(),
             'ttl_seconds':300,'screenshot_evidence':[{'path':str(png.relative_to(ROOT)),'sha256':digest_file(png)},
               {'path':str((folder/(slug+'_fees.png')).relative_to(ROOT)),'sha256':digest_file(folder/(slug+'_fees.png'))}],
             'authority':'travel_marketplace_display','independent_upstream_lineage_confirmed':False,
             'entity_binding_status':'agent_reviewed_name_and_same_street_number_not_full_identity_certificate',
             'reservations_submitted':0}
            gate=validate_room_offer(offer,now=utcnow())
            if not gate['ok'] or gate['native_price_per_room_night'] is not None:raise ValueError('Conditional offer gate mismatch')
            offers.append(offer)
    return offers

def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'catalog.sqlite3').exists():raise FileExistsError('Use another immutable version')
    source=sqlite3.connect(SOURCE.resolve().as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    before=digest_file(SOURCE);known_evidence={r[0] for r in source.execute('SELECT id FROM evidence')}
    evs={};updates=collections.defaultdict(list);audit=[];counts=collections.Counter();changed=set();new_values=collections.Counter()
    def keep(ev):
        gate=validate_evidence(ev)
        if not gate['ok']:raise ValueError(gate)
        evs[ev['evidence_id']]=ev;return ev
    # A derived alias lookup preserves the original archive and fact clocks.
    with gzip.open(RES/'archive_enrichment.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            x=json.loads(line);ev=keep(evidence(x['source_id'],x['source_url'],x['raw_facts'],x['retrieved_at'],
                authority='historical_third_party_archive',licence='upstream_reuse_unverified'))
            updates[x['record_id']].append(('archive',x,ev))
    # Only safely linked existing entities are updated. Unmatched results are not new catalog rows.
    for path in sorted((RES/'private_api_raw').glob('*.json')):
        x=json.loads(path.read_text(encoding='utf-8'));result=match_target(x['target'],x['response'].get('pois',[]))
        audit.append({'entity_id':x['target']['entity_id'],'target_name':x['target']['name'],'city':x['target']['city'],
           **{k:v for k,v in result.items() if k!='poi'}})
        if not result['matched']:continue
        raw=result['poi'];meta=x['meta'];api=api_restaurant(raw,meta)
        if api is None:raise ValueError('Nonrestaurant passed matching')
        ev=keep(evidence('amap_business_snapshot',meta['endpoint'],raw,meta['retrieved_at']))
        updates[x['target']['entity_id']].append(('restaurant',{'record':api,'binding':result['binding']},ev));counts['matched_existing_restaurants']+=1
    crawler=sqlite3.connect(RES/'crawler/queue.sqlite3');crawler.row_factory=sqlite3.Row
    for row in crawler.execute("SELECT entity_id,result FROM jobs WHERE status='captured'"):
        event=json.loads(row['result']);raw=gzip.open(event['raw_file'],'rb').read();parsed=qunar_fields(raw.decode('utf-8','replace'))
        original=source.execute('SELECT name FROM records WHERE id=?',(row['entity_id'],)).fetchone()
        if not original or not(name_aliases(original[0])&name_aliases(parsed['name'])):
            counts['unbound_attraction_pages']+=1;continue
        parsed['raw_page_sha256']=hashlib.sha256(raw).hexdigest()
        ev=keep(evidence('qunar_public_venue_page',event['url'],parsed,event['retrieved_at'],authority='travel_guide_publisher',licence='public_page_reuse_unverified'))
        updates[row['entity_id']].append(('attraction_page',parsed,ev));counts['bound_attraction_pages']+=1
    crawler.close()
    offers=room_offers()
    for offer in offers:
        for item in offer['screenshot_evidence']:
            if digest_file(ROOT/item['path'])!=item['sha256']:raise ValueError('Screenshot missing or changed')
        ev=keep(evidence(offer['source_id'],offer['source_url'],offer,offer['retrieved_at'],observed=offer['observed_at'],authority='travel_marketplace_display'))
        updates[offer['entity_id']].append(('room_offer',offer,ev))
    store=ExpansionStore(OUT/'catalog.sqlite3',create=True)
    # Copy only explicit internal tables; all incoming primary rows still use validated loader.
    aux=('field_assertions','room_offers','identity_checks','historical_references','official_operator_fields')
    for table in aux:
        sql=source.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone()[0]
        store.db.execute(sql)
    store.db.executescript('CREATE TABLE enrichment_findings(entity_id TEXT,kind TEXT,payload TEXT,evidence_id TEXT);')
    store.load_evidence((json.loads(r[0]) for r in source.execute('SELECT payload FROM evidence')),[],registry={})
    store.load_evidence((v for k,v in evs.items() if k not in known_evidence),[],registry={})
    findings=[];snapshot=utcnow();before_fields=collections.Counter();after_fields=collections.Counter();structured=collections.Counter()
    requested={'attraction':('price','opentime','endtime','recommendmintime','recommendmaxtime'),
        'restaurant':('price','cuisine','opentime','endtime'),'accommodation':('price','numbed')}
    def put(r,key,value,ev,note):
        old=r['data'].get(key)
        if old!=value:
            r.setdefault('field_history',[]).append({'field':key,'value':old,'provenance':copy.deepcopy(r['field_provenance'][key])})
            if old is None and value is not None:new_values[r['kind']+':'+key]+=1
            changed.add(r['record_id'])
        set_field(r,key,value,ev,note=note)
        if value is not None and key in ('cuisine','price','recommendmintime','recommendmaxtime'):
            r['tags'].append({'tag':{'cuisine':'cuisine','price':'price_reference_CNY'}.get(key,key+'_reference_hours'),
                'value':value,'basis':'explicit_source_business_field','status':'source_attribute_unverified',
                'policy_id':r['field_policies'][key],'source_time_ref':'field_provenance.'+key+'.observed_at',
                'valid_until':None,'evidence_id':ev['evidence_id'],'scope':note})
    def records():
      with gzip.open(OUT/'records.jsonl.gz','wt',encoding='utf-8',newline='\n') as target:
        for row in source.execute('SELECT payload FROM records ORDER BY id'):
            r=json.loads(row[0]);kind=r['kind'];rid=r['record_id']
            for key in requested[kind]:before_fields[kind+':'+key]+=r['data'].get(key) is not None
            for mode,x,ev in updates.get(rid,[]):
                if mode=='archive':
                    for key,val in x['native_values'].items():
                        if r['data'].get(key) is None:put(r,key,val,ev,'2023 historical source; original unknown fact age preserved')
                    r.setdefault('historical_reference_ids',[])
                    if ev['evidence_id'] not in r['historical_reference_ids']:r['historical_reference_ids'].append(ev['evidence_id'])
                elif mode=='restaurant':
                    api=x['record'];r['business_rules']=api['business_rules'];r.setdefault('binding_reviews',[]).append(x['binding'])
                    for key in ('price','cuisine','recommendedfood'):
                        if api['data'].get(key) is not None:put(r,key,api['data'][key],ev,'Same reviewed entity; provider reference, fact update time unknown')
                    hours=today_hours(api['business_rules'].get('opentime_today'));hours['evidence_id']=ev['evidence_id'];r['today_hours_structured']=hours
                    for key in ('opentime','endtime'):put(r,key,hours['native_values'].get(key),ev,'Provider today only; gaps/midnight are not flattened')
                    r['uncertainty_flags']+=['same_entity_candidate_binding_not_identity_certificate','map_average_price_not_a_bill']
                elif mode=='attraction_page':
                    for key,val in x['native_values'].items():
                        if r['data'].get(key) is not None and r['data'][key]!=val:r['uncertainty_flags'].append('historical_vs_current_page_rule_conflict:'+key)
                        put(r,key,val,ev,'Labeled current public page; fact update time unknown, not a source age renewal')
                    r.setdefault('current_page_ticket_options',[]).extend(x['ticket_options'])
                    findings.append((rid,'public_attraction_page',x,ev['evidence_id']))
                elif mode=='room_offer':
                    r.setdefault('room_offer_ids',[]).append(x['offer_id'])
                    if r['data'].get('numbed') is None:
                        put(r,'numbed',x['bed_count'],ev,'Only for selected room '+x['room_type_name'])
                        r['selected_room_offer_id']=x['offer_id'];r['room_offer_context']=validate_room_offer(x,now=snapshot)['context']
                    # Conditional discounts/cashback never become exact native prices.
                    r['uncertainty_flags']+=['conditional_room_quote_requires_requery','room_qualifications_must_not_be_mixed']
                    for tag,val in (('room_type',x['room_type_name']),('bed_count',x['bed_count'])):
                        r['tags'].append({'tag':tag,'value':val,'basis':'explicit_rendered_room_description',
                         'status':'source_attribute_unverified','policy_id':'room_configuration','source_time_ref':'room_offer.observed_at',
                         'valid_until':None,'scope':'offer:'+x['offer_id'],'evidence_id':ev['evidence_id']})
                    if rid in ('overture:52156bd0-165a-4f4b-b442-7e88e759c25c','overture:5f1c22f9-2b60-432b-a30b-3533d4aafe7d'):
                        if r['data'].get('featurehoteltype') is None:
                            feature={'featurehoteltype':'室内泳池','quote':'室内泳池 免费','operator_excerpt':str((RES/'browser'/('lanyue_operator_fields.txt' if '52156' in rid else 'kempinski_operator_fields.txt')).relative_to(ROOT))}
                            feature_ev=keep(evidence('tongcheng_hotel_amenities',x['source_url'],feature,x['retrieved_at'],authority='travel_marketplace_display'))
                            # New evidence must exist before record load validates references.
                            if not store.db.execute('SELECT id FROM evidence WHERE id=?',(feature_ev['evidence_id'],)).fetchone():
                                store.db.execute('INSERT INTO evidence VALUES(?,?)',(feature_ev['evidence_id'],canonical(feature_ev)))
                            put(r,'featurehoteltype','室内泳池',feature_ev,'Marketplace facility assertion; original update clock unknown')
            if kind=='restaurant' and r.get('business_rules',{}).get('opentime_today') and 'today_hours_structured' not in r:
                hours=today_hours(r['business_rules']['opentime_today']);eid=r['field_provenance']['opentime'].get('evidence_id')
                if eid:hours['evidence_id']=eid
                r['today_hours_structured']=hours
                # Correct only the known unrepresentable P13 single-pair projections.
                for key in ('opentime','endtime'):
                    val=hours['native_values'].get(key)
                    if r['data'].get(key)!=val:
                        r.setdefault('field_history',[]).append({'field':key,'value':r['data'].get(key),'provenance':copy.deepcopy(r['field_provenance'][key])})
                        r['data'][key]=val;r['field_provenance'][key]['status']='unknown' if val is None else 'source_value'
                        changed.add(rid);counts['corrected_legacy_hours_projections']+=1
                r['uncertainty_flags']+=hours['issues']
            if 'today_hours_structured' in r:
                h=r['today_hours_structured'];eid=h.get('evidence_id')
                e=json.loads(store.db.execute('SELECT payload FROM evidence WHERE id=?',(eid,)).fetchone()[0])
                h.update(schema_version='business-hours-v1',entity_id=rid,source_id=e['source_id'],source_url=e['source_url'],
                    observed_at=e['observed_at'],source_updated_at=e['source_updated_at'],retrieved_at=e['retrieved_at'],
                    policy_id='opening_hours',ttl_seconds=86400,valid_until=None,
                    raw_rule_sha256=hashlib.sha256(h['raw'].encode()).hexdigest(),
                    provider_request_date=datetime.fromisoformat(e['retrieved_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat(),
                    date_basis='today_relative_to_api_request_not_fact_update_time')
                gate=validate_hours(h,require_provenance=True)
                if not gate['ok']:raise ValueError(gate)
                r['tags'].append({'tag':'opening_pattern','value':'split_intervals' if len(h['segments'])>1 else
                   'overnight_or_midnight' if any(s['end_day_offset'] or s['end_minute']==1440 for s in h['segments']) else
                   'single_interval' if h['segments'] else 'unknown','basis':'explicit_provider_today_rule',
                   'status':'source_attribute_unverified','policy_id':'opening_hours','source_time_ref':'today_hours_structured.observed_at',
                   'valid_until':None,'evidence_id':eid,'scope':h['provider_request_date']})
                structured['restaurant_today_rules']+=1;structured['parsed_rules']+=bool(h['segments'])
                structured['split_rules']+=len(h['segments'])>1
                structured['midnight_or_overnight_rules']+=any(s['end_day_offset'] or s['end_minute']==1440 for s in h['segments'])
            r['uncertainty_flags']=sorted(set(r['uncertainty_flags']));r['catalogued_at']=snapshot
            gate=validate_record(r,now=snapshot)
            if not gate['discovery_ok']:raise ValueError({'record':rid,'errors':gate['errors']})
            counts['records']+=1;counts['planning_ready']+=gate['planning_ready']
            for key in requested[kind]:after_fields[kind+':'+key]+=r['data'].get(key) is not None
            target.write(canonical(r)+'\n');yield r
    store.load(records(),now=snapshot)
    with store.db:
        for table in aux:
            rows=source.execute('SELECT * FROM '+table)
            size=len(rows.description);store.db.executemany('INSERT INTO '+table+' VALUES('+','.join('?'*size)+')',rows)
        for offer in offers:
            ev=next(x for x in evs.values() if x['source_id']==offer['source_id'] and x['raw_text']==canonical(offer))
            gate=validate_room_offer(offer,now=snapshot)
            store.db.execute('INSERT INTO room_offers VALUES(?,?,?,?,?)',(offer['offer_id'],offer['entity_id'],canonical(offer),canonical(gate),ev['evidence_id']))
        for rid,mode,x,eid in findings:store.db.execute('INSERT INTO enrichment_findings VALUES(?,?,?,?)',(rid,mode,canonical(x),eid))
        for entry in audit:store.db.execute('INSERT INTO enrichment_findings VALUES(?,?,?,?)',(entry['entity_id'],'map_identity_match',canonical(entry),None))
        for rid,items in updates.items():
            for mode,x,ev in items:
                if mode=='archive' and not store.db.execute('SELECT 1 FROM historical_references WHERE entity_id=? AND evidence_id=?',(rid,ev['evidence_id'])).fetchone():
                    store.db.execute('INSERT INTO historical_references VALUES(?,?,?)',(rid,canonical(x),ev['evidence_id']))
    integrity=store.db.execute('PRAGMA integrity_check').fetchone()[0]
    offer_total=store.db.execute('SELECT count(*) FROM room_offers').fetchone()[0]
    ev_count=store.db.execute('SELECT count(*) FROM evidence').fetchone()[0]
    store.close();source.close()
    if digest_file(SOURCE)!=before:raise ValueError('Immutable baseline changed')
    report={'built_at':snapshot,'version':'business-catalog-v1.4-20261022','counts':dict(counts),
       'existing_records_changed':len(changed),'new_nonnull_native_values':dict(new_values),
       'before_field_coverage':dict(before_fields),'after_field_coverage':dict(after_fields),
       'structured_hours':dict(structured),'room_offers_total':offer_total,'new_room_offers':len(offers),
       'new_hotel_entities_with_room_details':2,'hotel_offers_conditional_not_exact_budget':True,
       'evidence_snapshots':ev_count,'source_v1_2_sha256':before,'source_v1_2_unchanged':True,
       'sqlite_integrity':integrity,'new_entities_added':0,'doubling_completed':False,
       'online_call_savings_measured':None,'real_world_accuracy_certified':False,
       'files':[{'file':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest_file(p)} for p in (OUT/'catalog.sqlite3',OUT/'records.jsonl.gz')]}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (RES/'binding_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (RES/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (RES/'new_room_offers.json').write_text(json.dumps(offers,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
