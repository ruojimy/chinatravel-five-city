"""Summarize field-level retrieval feedback, without replacing model outputs."""
import csv,json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    rows=[];reports=[];by_level={}
    for level in ('easy','hard','human'):
        records=read(OUT/'evaluations'/(level+'.json'));by_level[level]={}
        responses={r['uid']:r['events'] for r in read(OUT/'responses_v2'/(level+'.json'))}
        for stage in ('static','dynamic'):
            subset=[r[stage] for r in records];metrics=Counter()
            for r in subset:
                for k,v in r['metrics'].items():
                    if isinstance(v,(int,float)) and k not in ('gap_recall','request_field_coverage','useful_request_precision'):metrics[k]+=v
            fields=metrics['required_fields']
            data=dict(queries=len(records),schema_pass=sum(r['schema_ok'] for r in subset),protocol_pass=sum(r['protocol_ok'] for r in subset),
                evidence_state_pass=sum(r['safe'] for r in subset),complete=sum(r['complete'] for r in subset),
                gap_recall=sum(r['metrics'].get('gap_recall',0) for r in subset)/len(records),
                request_coverage=sum(r['metrics'].get('request_field_coverage',0) for r in subset)/len(records),
                metrics=dict(metrics),issues=dict(Counter(v for r in subset for v in r.get('issues',[]))),
                evidence_errors=[{'uid':rec['uid'],'errors':rec[stage].get('unsupported',[])} for rec in records if not rec[stage]['safe']])
            by_level[level][stage]=data
            for rec in records:
                r=rec[stage];uid=rec['uid'];events=responses[uid]
                rows.append(dict(level=level,uid=uid,case_id=level+'/'+uid,stage=stage,schema_ok=r['schema_ok'],protocol_ok=r['protocol_ok'],evidence_state_ok=r['safe'],
                    complete=r['complete'],gap_recall=r['metrics'].get('gap_recall'),request_coverage=r['metrics'].get('request_field_coverage'),
                    resolved_fields=r['metrics'].get('resolved_fields'),reference_fields=r['metrics'].get('reference_fields'),estimate_fields=r['metrics'].get('estimate_fields'),
                    reviewed_evidence=r['metrics'].get('reviewed_evidence'),wrongly_used_evidence=r['metrics'].get('wrongly_used_evidence'),
                    itinerary_changed=r['metrics'].get('itinerary_changed'),gateway_requests=len(events),returned_events=sum(e['status']=='returned' for e in events),
                    issues=';'.join(r.get('issues',[])),evidence_errors=';'.join(r.get('unsupported',[]))))
        before={r['uid']:r for r in read(OUT/'participants'/(level+'_static.json'))}
        after={r['uid']:r for r in read(OUT/'participants'/(level+'_dynamic.json'))}
        def times(plan):return [(d['day'],d['date'],d['city'],[(a['type'],a['entity_id'],a['start_time'],a['end_time']) for a in d['activities']]) for d in plan['itinerary']]
        by_level[level]['actual_time_or_order_changes']=sum(times(before[u])!=times(after[u]) for u in before)
        by_level[level]['price_value_changes']=sum([a['price']['value'] for d in before[u]['itinerary'] for a in d['activities']] != [a['price']['value'] for d in after[u]['itinerary'] for a in d['activities']] for u in before)
        reports.extend({'level':level,**r} for r in records)
    episodes=[(level,r) for level in ('easy','hard','human') for r in read(OUT/'responses_v2'/(level+'.json'))]
    all_events=[e for level,r in episodes for e in r['events']]
    returned_evidence=[e for ev in all_events for e in ev['evidence']]
    corpus=read(OUT/'private/evidence_corpus.json')
    totals={}
    for stage in ('static','dynamic'):
        sub=[r[stage] for r in reports];m=Counter()
        for r in sub:
            for k,v in r['metrics'].items():
                if isinstance(v,(int,float)) and k not in ('gap_recall','request_field_coverage','useful_request_precision'):m[k]+=v
        totals[stage]=dict(queries=len(sub),schema_pass=sum(r['schema_ok'] for r in sub),protocol_pass=sum(r['protocol_ok'] for r in sub),
            evidence_state_pass=sum(r['safe'] for r in sub),complete=sum(r['complete'] for r in sub),metrics=dict(m),
            gap_recall=sum(r['metrics'].get('gap_recall',0) for r in sub)/len(sub),
            request_coverage=sum(r['metrics'].get('request_field_coverage',0) for r in sub)/len(sub))
    summary={'cases':96,'stages':2,'proposals':192,'identity_scope':'(level, uid) is the unique case key; hard/human share H UID prefix',
        'new_cities':30,'mixed_city_chains':6,'levels':by_level,'total':totals,
        'gateway':{'requests':len(all_events),'statuses':dict(Counter(e['status'] for e in all_events)),
            'cases_with_any_evidence':sum(any(e['evidence'] for e in r['events']) for l,r in episodes),
            'evidence_deliveries':len(returned_evidence),'distinct_evidence_ids_returned':len({e['evidence_id'] for e in returned_evidence}),
            'new_http_calls':0,'mode':'Exact-context replay of root captured source corpus, driven by participant requests'},
        'source_capture':{'amap_calls':corpus['new_weather_calls'],'operator_page_attempts':8,'search_queries':4,
            'corpus_evidence':len(corpus['evidence']),'cached_quarantined':corpus['cached_rows'],'frozen_at':corpus['captured_at'],
            'no_new_routes':'Precise origin coordinates missing','no_intercity_inventory_source':True},
        'limits':['human tasks are authored human-style, not human-collected','Shared30 cities acrosslevels are correlated, not96 independent information needs',
            'Model semantic decisions and direct plan revision; Python serialization reused for structure, no existing itinerary optimizer',
            'Root source capture curated and partly prefetched, not autonomous LLM web search','Only6cities received fresh weather and3cities reviewed operator references',
            'Source fields resolved to reference/estimate are not certified facts; all-real-feasibility remains incomplete']}
    save(OUT/'summary.json',summary);save(OUT/'evaluations/all_96.json',reports)
    with (OUT/'case_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('levels','limits')},ensure_ascii=True))
if __name__=='__main__':main()
