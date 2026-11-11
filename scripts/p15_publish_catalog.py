"""Publish a validated immutable descendant of v1.4 from cached whole-catalog work."""
import collections,copy,gzip,hashlib,json,sqlite3,sys,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from shorttrip.bulk_business import BulkQueue,match_business,gaps
from shorttrip.business_completion import api_restaurant,validate_room_offer
from shorttrip.scoped_business import today_hours,validate_hours
from shorttrip.expansion_store import ExpansionStore
from shorttrip.expansion_contract import validate_record,validate_evidence
from shorttrip.freshness import utcnow,canonical
from shorttrip.travel_catalog import digest_file
from p13_build_business_catalog import evidence,set_field
from shorttrip.linked_page_business import extract as extract_linked_page
from shorttrip.operator_assertions import load_approved,load_approved_offers
RES=ROOT/'results/p15_whole_catalog';SOURCE=ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3'

def main():
    snapshot=utcnow();slug=snapshot.replace('-','').replace(':','').replace('+0000','Z')
    has_operator_batch=(ROOT/'results/p16_multiworker/approved_assertions.json').exists()
    has_p17=(ROOT/'results/p17_continuous/approved_batches/index.json').exists()
    out=ROOT/'data'/(('business_catalog_v1_7_' if has_p17 else 'business_catalog_v1_6_' if has_operator_batch else 'business_catalog_v1_5_')+slug);out.mkdir()
    source_hash=digest_file(SOURCE);source=sqlite3.connect(SOURCE.resolve().as_uri()+'?mode=ro',uri=True)
    q=BulkQueue(RES/'queue.sqlite3');q.sync_cache(ROOT/'results/p14_targeted_completion/private_api_raw')
    # Materialize just file references, not catalog rows or all provider responses.
    files=[(x['entity_id'],x['packet_path']) for x in q.db.execute("SELECT entity_id,packet_path FROM jobs WHERE adapter='amap_place' AND packet_path IS NOT NULL ORDER BY id")]
    updates={};evs={};audit=[]
    for rid,file in files:
        packet=json.loads(Path(file).read_text(encoding='utf-8'));match=match_business(packet['target'],packet['response'].get('pois',[]))
        entry={'entity_id':rid,'kind':packet['target']['kind'],'packet_file':str(Path(file).relative_to(ROOT)),
               'packet_sha256':digest_file(Path(file)),**{k:v for k,v in match.items() if k!='poi'}}
        audit.append(entry)
        if not match['matched']:continue
        poi=match['poi'];meta=packet['meta'];ev=evidence('amap_business_snapshot',meta['endpoint'],poi,meta['retrieved_at'])
        if not validate_evidence(ev)['ok']:raise ValueError('Invalid evidence')
        evs[ev['evidence_id']]=ev;updates[rid]=(poi,meta,match,ev)
    web_updates=collections.defaultdict(list);web_audit=[]
    web_db=RES/'web_crawler/queue.sqlite3';links_db=RES/'source_links.sqlite3'
    if web_db.exists() and links_db.exists():
        web=sqlite3.connect(web_db.resolve().as_uri()+'?mode=ro',uri=True)
        links=sqlite3.connect(links_db.resolve().as_uri()+'?mode=ro',uri=True)
        for url,result in web.execute("SELECT url,result FROM jobs WHERE status='captured'"):
            capture=json.loads(result);page=json.loads(Path(capture['extraction_file']).read_text(encoding='utf-8'))
            for rid, in links.execute('SELECT entity_id FROM links WHERE url=?',(url,)):
                row=source.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()
                if not row:continue
                r=json.loads(row[0]);t={'name':r['name'],'kind':r['kind'],'longitude_wgs84':r['data']['lon'],'latitude_wgs84':r['data']['lat']}
                facts=extract_linked_page(t,page['extraction']['jsonld'])
                web_audit.append({'entity_id':rid,'url':url,**{k:v for k,v in facts.items() if k!='source_object'}})
                if facts['matched'] and facts['native_values']:
                    ev=evidence('record_linked_public_venue_schema',url,facts,capture['retrieved_at'],authority='record_linked_publisher_operator_unverified',licence='public_page_reuse_unverified')
                    evs[ev['evidence_id']]=ev;web_updates[rid].append((facts,ev))
        web.close();links.close()
    operator_updates,operator_evidence=load_approved(ROOT);evs.update(operator_evidence)
    reviewed_offers=load_approved_offers(ROOT);offer_by_entity={x['entity_id']:x for x in reviewed_offers}
    store=ExpansionStore(out/'catalog.sqlite3',create=True)
    known={x[0] for x in source.execute('SELECT id FROM evidence')}
    store.load_evidence((json.loads(x[0]) for x in source.execute('SELECT payload FROM evidence')),[],registry={})
    store.load_evidence((v for k,v in evs.items() if k not in known),[],registry={})
    base_tables=('records','tags','evidence','claims','metadata')
    aux=[r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0] not in base_tables and not r[0].startswith('sqlite_')]
    for name in aux:store.db.execute(source.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()[0])
    changed=set();new_values=collections.Counter();coverage=collections.defaultdict(collections.Counter);issues=[]
    def put(r,key,value,ev,note):
        old=r['data'].get(key)
        if old==value:return
        r.setdefault('field_history',[]).append({'field':key,'value':old,'provenance':copy.deepcopy(r['field_provenance'][key])})
        set_field(r,key,value,ev,note=note);changed.add(r['record_id'])
        if old is None and value is not None:new_values[r['kind']+':'+key]+=1
        if value is not None and key in ('price','cuisine'):
            r['tags'].append({'tag':'price_reference_CNY' if key=='price' else key,'value':value,
                'basis':'explicit_provider_business_field','status':'source_attribute_unverified',
                'policy_id':r['field_policies'][key],'source_time_ref':'field_provenance.'+key+'.observed_at',
                'valid_until':None,'evidence_id':ev['evidence_id'],'scope':note})
    def rows():
      with gzip.open(out/'records.jsonl.gz','wt',encoding='utf-8',newline='\n') as f:
        for payload, in source.execute('SELECT payload FROM records ORDER BY id'):
            r=json.loads(payload);rid=r['record_id'];kind=r['kind']
            if rid in updates:
                poi,meta,match,ev=updates[rid];b=poi.get('business') or {}
                # Cached P14 evidence already present in v1.4 is never appended twice.
                already=any(z.get('poi_id')==poi['id'] for z in r.get('binding_reviews',[])) and ev['evidence_id'] in known
                if not already:
                    r.setdefault('binding_reviews',[]).append(match['binding'])
                    if kind=='restaurant':
                        api=api_restaurant(poi,meta)
                        if api is None:raise ValueError('Wrong restaurant type')
                        r['business_rules']=api['business_rules']
                        for key in ('price','cuisine','recommendedfood'):
                            if api['data'].get(key) not in (None,''):put(r,key,api['data'][key],ev,'Candidate name/city/near coordinates; provider per-person reference, update time unknown')
                    if kind in ('restaurant','attraction') and b.get('opentime_today'):
                        h=today_hours(b['opentime_today']);h.update(schema_version='business-hours-v1',entity_id=rid,
                          source_id=ev['source_id'],source_url=ev['source_url'],evidence_id=ev['evidence_id'],
                          observed_at=None,source_updated_at=None,retrieved_at=meta['retrieved_at'],
                          policy_id='opening_hours',ttl_seconds=86400,valid_until=None,
                          raw_rule_sha256=hashlib.sha256(h['raw'].encode()).hexdigest(),
                          provider_request_date=datetime.fromisoformat(meta['retrieved_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat(),
                          date_basis='today_relative_to_api_request_not_fact_update_time')
                        if not validate_hours(h,require_provenance=True)['ok']:raise ValueError('Invalid hours')
                        if r.get('today_hours_structured')!=h:changed.add(rid)
                        r['today_hours_structured']=h
                        if h['segments']:
                            for key in ('opentime','endtime'):
                                put(r,key,h['native_values'].get(key),ev,'Provider today only; split and midnight rules retained structurally')
                        r['tags'].append({'tag':'opening_pattern','value':'split_intervals' if len(h['segments'])>1 else
                            'overnight_or_midnight' if any(z['end_day_offset'] or z['end_minute']==1440 for z in h['segments']) else
                            'single_interval' if h['segments'] else 'unknown','basis':'explicit_provider_today_rule',
                            'status':'source_attribute_unverified','policy_id':'opening_hours',
                            'source_time_ref':'today_hours_structured.observed_at','valid_until':None,
                            'evidence_id':ev['evidence_id'],'scope':h['provider_request_date']})
                    r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['candidate_binding_not_identity_certificate','unknown_provider_fact_update_time']))
                    r['catalogued_at']=snapshot
            for facts,ev in web_updates.get(rid,[]):
                for key,value in facts['native_values'].items():
                    # Keep conflicting existing values. Independent source disagreement
                    # goes to evidence/audit rather than silently replacing the map.
                    if r['data'].get(key) is None:put(r,key,value,ev,facts['field_notes'][key])
                    elif r['data'][key]!=value:r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['linked_page_conflict:'+key]))
            if rid in operator_updates:
                r['operator_assertions']=operator_updates[rid]
                for assertion in r['operator_assertions']:
                    ev=evs[assertion['evidence_id']]
                    if assertion['field']=='source_website_relevance_conflict':
                        r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['untrusted_website_source_requires_review']))
                    if assertion['field']=='source_city_relevance_conflict':
                        r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['source_city_conflicts_with_research_window']))
                    if assertion['field']=='source_property_address_conflict':
                        r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['source_property_address_conflicts_require_review']))
                    binding=assertion['context'].get('identity_match_basis')
                    if isinstance(binding,dict) and binding.get('catalogue_city_supported') is False and (binding.get('source_city') or binding.get('operator_city')) and (binding.get('source_city') or binding.get('operator_city'))!=r['city']:
                        r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['source_city_conflicts_with_research_window']))
                    if assertion['context'].get('status')=='historical_reported_closure' or (assertion['context'].get('applicability') or {}).get('status')=='reported_closed':
                        r['exclude_from_static_planning']=True
                        r['operational_status']='reported_closed_reopening_unverified'
                        r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['reported_closure_requires_reopening_evidence']))
                    for key,value in assertion['native_values'].items():
                        if r['data'].get(key) is None:
                            put(r,key,value,ev,'Scoped operator assertion '+assertion['assertion_id']+'; '+assertion['scope'])
                            if assertion['context'].get('native_provenance_status')=='derived':r['field_provenance'][key]['status']='derived'
                            if key=='numbed':r['selected_room_configuration_assertion_id']=assertion['assertion_id']
                        elif key=='cuisine' and r['data'][key]!=value and r['field_provenance'][key].get('status')=='derived' and assertion['context'].get('cuisine_granularity')=='specific' and assertion['context'].get('address_reference_matched'):
                            put(r,key,value,ev,'Explicit finer publisher cuisine with exact retained branch address; source update time unknown')
                        elif r['data'][key]!=value:r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['operator_assertion_conflict:'+key]))
                    if assertion['value'] not in (None,[],{}):
                        r['tags'].append({'tag':assertion['field'],'value':assertion['value'],'scope':assertion['scope'],
                            'basis':'explicit_provider_taxonomy_mapping' if assertion['context'].get('native_provenance_status')=='derived' else 'exact_scoped_source_quote',
                            'status':'derived_source_reference' if assertion['context'].get('native_provenance_status')=='derived' else 'source_attribute_unverified',
                            'policy_id':assertion['policy_id'],'source_time_ref':'operator_assertion.observed_at',
                            'valid_until':assertion.get('valid_until'),'evidence_id':assertion['evidence_id']})
                r['uncertainty_flags']=sorted(set(r['uncertainty_flags']+['operator_rules_keep_calendar_room_and_product_scope']))
            if rid in offer_by_entity:
                offer=offer_by_entity[rid];r['selected_room_offer_id']=offer['offer_id']
                r['room_offer_context']=validate_room_offer(offer,now=snapshot)['context']
            gate=validate_record(r,now=snapshot)
            if not gate['discovery_ok']:raise ValueError({'record':rid,'errors':gate['errors']})
            coverage[kind]['records']+=1;coverage[kind]['planning_ready']+=gate['planning_ready']
            for key,val in r['data'].items():coverage[kind]['nonnull:'+key]+=val is not None
            if 'today_hours_structured' in r:coverage[kind]['parsed_structured_hours']+=bool(r['today_hours_structured']['segments'])
            f.write(canonical(r)+'\n');yield r
    store.load(rows(),now=snapshot)
    with store.db:
        for table in aux:
            cur=source.execute('SELECT * FROM '+table);n=len(cur.description)
            store.db.executemany('INSERT INTO '+table+' VALUES('+','.join('?'*n)+')',cur)
        # Keep non-import metadata and all old claim rows exactly; no generated claims used here.
        store.db.executemany('INSERT INTO metadata VALUES(?,?)',source.execute("SELECT key,value FROM metadata WHERE key!='imported_at'"))
        if source.execute('SELECT count(*) FROM claims').fetchone()[0]:raise ValueError('Claim copy needs explicit validation; current base expected no claims')
        for a in audit:
            store.db.execute('INSERT INTO enrichment_findings VALUES(?,?,?,?)',(a['entity_id'],'p15_map_candidate_audit',canonical(a),None))
        for a in web_audit:
            store.db.execute('INSERT INTO enrichment_findings VALUES(?,?,?,?)',(a['entity_id'],'p15_linked_page_candidate_audit',canonical(a),None))
        for offer in reviewed_offers:
            if offer['evidence_id'] not in evs or not store.db.execute('SELECT 1 FROM records WHERE id=?',(offer['entity_id'],)).fetchone():raise ValueError('Unresolved reviewed offer reference')
            store.db.execute('INSERT INTO room_offers VALUES(?,?,?,?,?)',(offer['offer_id'],offer['entity_id'],canonical(offer),canonical(validate_room_offer(offer,now=snapshot)),offer['evidence_id']))
    # Reload through the real graph validator, streaming each record; never trust cached gates.
    record_errors=0
    for payload, in store.db.execute('SELECT payload FROM records'):
        r=json.loads(payload);g=validate_record(r,now=snapshot)
        if not g['discovery_ok']:record_errors+=1
        for fp in r['field_provenance'].values():
            if fp.get('evidence_id'):
                e=store.db.execute('SELECT payload FROM evidence WHERE id=?',(fp['evidence_id'],)).fetchone()
                if not e or any(fp.get(k)!=json.loads(e[0]).get(k) for k in ('source_id','source_url','observed_at')):record_errors+=1
    integrity=store.db.execute('PRAGMA integrity_check').fetchone()[0];foreign=store.db.execute('PRAGMA foreign_key_check').fetchall()
    hotels=collections.defaultdict(list)
    for rid,payload in store.db.execute('SELECT entity_id,payload FROM room_offers'):
        offer=json.loads(payload)
        if not validate_room_offer(offer,now=snapshot)['ok']:raise ValueError('Invalid inherited offer')
        hotels[rid].append(offer)
    remaining=collections.Counter()
    with gzip.open(out/'remaining_gaps.jsonl.gz','wt',encoding='utf-8') as f:
        for rid,payload in store.db.execute('SELECT id,payload FROM records ORDER BY id'):
            r=json.loads(payload);missing=gaps(r,hotels[rid]);remaining.update(r['kind']+':'+k for k in missing)
            f.write(canonical({'entity_id':rid,'kind':r['kind'],'missing_business_fields':missing,
              'needs_identity_and_time_verification':True})+'\n')
    n=store.db.execute('SELECT count(*) FROM records').fetchone()[0];evcount=store.db.execute('SELECT count(*) FROM evidence').fetchone()[0]
    store.close();source.close();q.close()
    okay=n==14057 and not record_errors and not foreign and integrity=='ok' and digest_file(SOURCE)==source_hash
    manifest={'built_at':snapshot,'source_catalog':str(SOURCE.relative_to(ROOT)),'source_sha256':source_hash,
              'records':n,'evidence':evcount,'network_calls_in_publication':0,'cached_queries_reviewed':len(files),
              'safely_bound_candidates':len(updates),'linked_pages_reviewed':len(web_audit),'linked_entities_with_extractable_fields':len(web_updates),
              'operator_assertions':sum(map(len,operator_updates.values())),'entities_with_operator_assertions':len(operator_updates),
              'records_changed_vs_v1_4':len(changed),
              'new_nonnull_native_fields_vs_v1_4':dict(new_values),'coverage':{k:dict(v) for k,v in coverage.items()},
              'remaining_missing_business_fields':dict(remaining),'full_completion':False,'new_entities':0,
              'validation':{'all_checks_pass':okay,'record_or_reference_errors':record_errors,'integrity':integrity,'foreign_key_errors':len(foreign)},
              'files':[{'file':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest_file(p)} for p in
                       (out/'catalog.sqlite3',out/'records.jsonl.gz',out/'remaining_gaps.jsonl.gz')]}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'README.md').write_text('# 全库补齐增量快照\n\n继承v1.4，实际来源与缺口见manifest.json。查询不等于完成；未知事实时钟不续期，酒店人均不转房价。所有记录通过载入门，未证明现实规划可用。\n',encoding='utf-8')
    (out/'binding_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    if not okay:raise ValueError('Snapshot rejected; current pointer unchanged')
    pointer={'published_at':snapshot,'catalog':str((out/'catalog.sqlite3').relative_to(ROOT)),
             'manifest':str((out/'manifest.json').relative_to(ROOT)),'sha256':digest_file(out/'catalog.sqlite3'),
             'full_completion':False,'validated':True}
    tmp=RES/'current_catalog.tmp';tmp.write_text(json.dumps(pointer,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(RES/'current_catalog.json')
    print(canonical({**pointer,'new_values':dict(new_values),'remaining':dict(remaining)}))
if __name__=='__main__':
    lock=RES/'publish.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        print('Publication already running; existing validated pointer remains active');raise SystemExit(0)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:main()
    finally:lock.unlink(missing_ok=True)
