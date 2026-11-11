"""Evidence-aware multi-city benchmark. No network and no hidden-label planning.

Keeps ChinaTravel's activity/transport vocabulary, while unknown quantities and
retrieval episodes are first-class. Source references are never hard facts.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from jsonschema import Draft202012Validator

VERSION='shorttrip-dynamic-v1'
FIELDS=['price','opening_hours','recommended_duration','room_configuration','inventory',
        'route_duration','route_fare','intercity_schedule','intercity_fare','weather_forecast','identity']

def quantity_schema():
    return {'type':'object','additionalProperties':False,'required':['value','status','evidence_ids'],
        'properties':{'value':{'type':['number','null'],'minimum':0},
            'status':{'enum':['unknown','reference','estimate','verified','decision','sandbox']},
            'evidence_ids':{'type':'array','uniqueItems':True,'items':{'type':'string'}}},
        'allOf':[{'if':{'properties':{'status':{'const':'unknown'}}},'then':{'properties':{'value':{'type':'null'}}}}]}

def schemas():
    text={'type':'string','minLength':1};refs={'type':'array','uniqueItems':True,'items':text}
    clock={'type':'string','pattern':r'^(?:[01]\d|2[0-3]):[0-5]\d$'}
    request={'type':'object','additionalProperties':False,'required':['request_id','target_id','city','fields','provider','context','reason'],
        'properties':{'request_id':text,'target_id':text,'city':text,'fields':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':FIELDS}},
            'provider':{'enum':['operator','amap','intercity','static']},'context':{'type':'object'},'reason':text}}
    gap={'type':'object','additionalProperties':False,'required':['target_id','field','reason','state','evidence_ids'],
        'properties':{'target_id':text,'field':{'enum':FIELDS},'reason':text,
            'state':{'enum':['pending','unavailable','reference','estimate','verified','conflict']},'evidence_ids':refs}}
    transport={'type':'object','additionalProperties':False,'required':['start','end','mode','start_time','end_time','cost','duration_minutes'],
        'properties':{'start':text,'end':text,'mode':{'enum':['walk','metro','taxi','public_transit']},
            'start_time':clock,'end_time':clock,'cost':quantity_schema(),'duration_minutes':quantity_schema()}}
    activity={'type':'object','additionalProperties':False,
        'required':['activity_id','type','city','entity_id','position','start_time','end_time','cost','price','transports','evidence_ids'],
        'properties':{'activity_id':text,'type':{'enum':['anchor','attraction','lunch','dinner','breakfast','accommodation','train','airplane','transfer']},
            'city':text,'entity_id':{'type':['string','null']},'position':text,'start_time':clock,'end_time':clock,
            'cost':quantity_schema(),'price':quantity_schema(),'transports':{'type':'array','items':transport},'evidence_ids':refs,
            'start_city':text,'end_city':text,'TrainID':{'type':['string','null']},'FlightID':{'type':['string','null']},
            'rooms':{'type':['integer','null'],'minimum':1},'room_type':{'type':['integer','null'],'minimum':1}}}
    plan={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':VERSION+'/plan',
        'type':'object','additionalProperties':False,
        'required':['schema_version','uid','stage','status','people_number','start_city','city_sequence','itinerary','gaps','retrieval_requests','feedback'],
        'properties':{'schema_version':{'const':VERSION},'uid':text,'stage':{'enum':['static','dynamic','revised']},
            'status':{'enum':['conditional','blocked','complete']},'people_number':{'type':'integer','minimum':1},'start_city':text,
            'city_sequence':{'type':'array','minItems':1,'items':text},
            'itinerary':{'type':'array','minItems':1,'items':{'type':'object','additionalProperties':False,
                'required':['day','date','city','activities'],'properties':{'day':{'type':'integer','minimum':1},'date':{'type':'string','format':'date'},
                    'city':text,'activities':{'type':'array','minItems':1,'items':activity}}}},
            'gaps':{'type':'array','items':gap},'retrieval_requests':{'type':'array','items':request},
            'feedback':{'type':'array','items':{'type':'object','additionalProperties':False,
                'required':['evidence_id','action','affected_ids','reason'],
                'properties':{'evidence_id':text,'action':{'enum':['use','reject','defer']},'affected_ids':refs,'reason':text}}}}}
    query={'$schema':plan['$schema'],'type':'object','additionalProperties':False,
        'required':['schema_version','uid','nature_language','people_number','city_sequence','dates','candidates','requirements','retrieval_budget'],
        'properties':{'schema_version':{'const':VERSION},'uid':text,'nature_language':text,'people_number':{'type':'integer','minimum':1},
            'city_sequence':{'type':'array','minItems':1,'items':text},'dates':{'type':'array','minItems':1,'items':text},
            'candidates':{'type':'array','items':{'type':'object'}},'requirements':{'type':'array','items':{'type':'object'}},
            'retrieval_budget':{'type':'integer','minimum':0}}}
    response={'$schema':plan['$schema'],'type':'object','required':['request_id','status','evidence','reason'],
        'additionalProperties':False,'properties':{'request_id':text,'status':{'enum':['returned','unavailable','budget_exhausted','provider_paused','invalid_context']},
            'evidence':{'type':'array','items':{'type':'object'}},'reason':text}}
    return {'plan':plan,'query':query,'response':response}

def target_key(target,field):return target+'|'+field
def same(a,b):
    if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):return abs(a-b)<1e-6
    return a==b

def city_matches(actual,requirement):
    if requirement.get('field') in ('intercity_schedule','intercity_fare'):
        context=requirement.get('context',{})
        return actual in {context.get('origin'),context.get('destination')}
    return actual==requirement.get('city')

def assess_evidence(e,requirement,now=None):
    """Registry is root-produced; participant cannot grant provenance to itself."""
    reasons=[]
    for k in ('target_id','field'):
        if e.get(k)!=requirement.get(k):reasons.append('wrong_'+k)
    if not city_matches(e.get('city'),requirement):reasons.append('wrong_city')
    for k,v in requirement.get('context',{}).items():
        if e.get('context',{}).get(k)!=v:reasons.append('context_mismatch:'+k)
    if e.get('level') not in ('reference','estimate','verified','sandbox'):reasons.append('unusable_level')
    if e.get('value') is None:reasons.append('missing_value')
    if e.get('rejected_reason'):reasons.append(e['rejected_reason'])
    if e.get('field') in ('route_duration','route_fare') and e.get('source_id')!='amap':reasons.append('amap_required')
    if e.get('raw_sha256')!=hashlib.sha256(e.get('raw_text','').encode()).hexdigest() or not e.get('quote') or e.get('quote') not in e.get('raw_text',''):
        reasons.append('raw_or_quote_invalid')
    # A deadline is a restriction, never permission to promote reference to fact.
    if now and e.get('valid_until'):
        from .freshness import parse_time
        deadline=parse_time(e['valid_until']);at=parse_time(now)
        if deadline is None or at is None or at>=deadline:reasons.append('expired')
    return {'usable':not reasons,'reasons':reasons,'level':e.get('level','unknown')}

def evaluate(query,plan,evidence=(),events=(),*,stage=None,previous=None,now=None):
    errors=sorted(Draft202012Validator(schemas()['plan']).iter_errors(plan),key=lambda x:str(x.path))
    structural=[{'path':list(e.path),'message':e.message} for e in errors]
    if errors:return {'schema_ok':False,'schema_errors':structural,'protocol_ok':False,'safe':False,'complete':False,'metrics':{}}
    issues=[];unknown=[];ledger={e['evidence_id']:e for e in evidence}
    required={target_key(r['target_id'],r['field']):r for r in query['requirements']}
    if plan['uid']!=query['uid']:issues.append('uid_mismatch')
    if stage and plan['stage']!=stage:issues.append('stage_mismatch')
    if plan['people_number']!=query['people_number']:issues.append('people_mismatch')
    if plan['city_sequence']!=query['city_sequence'] or plan['start_city']!=query['city_sequence'][0]:issues.append('city_sequence_mismatch')
    if len(plan['itinerary'])!=len(query['dates']):issues.append('day_count_mismatch')
    acts=[];ids=set()
    known={c['entity_id']:c for c in query['candidates']}
    for i,day in enumerate(plan['itinerary']):
        if day['day']!=i+1:issues.append('day_order')
        if i<len(query['dates']) and day['date']!=query['dates'][i]:issues.append('date_mismatch')
        if i<len(query['city_sequence']) and day['city']!=query['city_sequence'][i]:issues.append('day_city_mismatch')
        end='00:00'
        for a in day['activities']:
            acts.append(a)
            if a['activity_id'] in ids:issues.append('duplicate_activity_id')
            ids.add(a['activity_id'])
            if a['start_time']<end or a['end_time']<a['start_time']:issues.append('overlapping_or_reversed_time')
            end=a['end_time']
            if a['city']!=day['city']:issues.append('activity_city_mismatch')
            entity=a['entity_id']
            if entity and (entity not in known or known[entity]['city']!=a['city']):issues.append('unknown_or_wrong_city_entity')
            if entity and entity in known and a['position']!=known[entity]['name']:issues.append('entity_name_mismatch')
    for city,entity in query.get('required_entities',[]): # extension only in private wrapper, not query schema
        if not any(a['entity_id']==entity and a['city']==city for a in acts):issues.append('missing_required_entity:'+entity)
    for r in query['requirements']:
        if r.get('entity_required') and not any(a['entity_id']==r['target_id'] for a in acts):issues.append('missing_required_entity:'+r['target_id'])
    intercity=[a for a in acts if a['type'] in ('train','airplane','transfer') and a.get('start_city') and a.get('end_city')]
    for origin,dest in zip(query['city_sequence'],query['city_sequence'][1:]):
        if not any(a['start_city']==origin and a['end_city']==dest for a in intercity):issues.append('missing_city_link:'+origin+'>'+dest)
    cited=set();unsupported=[];used_valid=set()
    def quantity(q,target,field,allow_decision=False):
        if q['status']=='unknown':
            if q['value'] is not None:unsupported.append('unknown_nonnull')
            return
        if q['value'] is None:unsupported.append('nonnull_status_with_null');return
        if q['status']=='decision':
            if not allow_decision:unsupported.append('decision_used_as_factual_price')
            return
        if q['status']=='sandbox' and known.get(target,{}).get('dataset')=='legacy_frozen_sandbox' and field=='price' and same(q['value'],known[target].get('data',{}).get('price')):
            return
        matches=[]
        r=required.get(target_key(target,field),{'target_id':target,'city':known.get(target,{}).get('city'),'field':field,'context':{}})
        for eid in q['evidence_ids']:
            cited.add(eid);e=ledger.get(eid)
            if e is None:unsupported.append('unknown_evidence_id:'+eid);continue
            verdict=assess_evidence(e,r,now)
            if verdict['usable'] and same(e['value'],q['value']):
                allowed=e['level']==q['status'] or q['status']=='reference' and e['level'] in ('estimate','verified')
                if allowed:matches.append(eid);used_valid.add(eid)
        if not matches:unsupported.append('unsupported_quantity:'+target+'|'+field)
    for a in acts:
        if a['type'] not in ('anchor','transfer','train','airplane'):
            quantity(a['price'],a['entity_id'],'price')
            # Total is a decision allowance until all factual components are known.
            if a['cost']['status'] not in ('unknown','decision'):
                expected=a['price']['value']
                multiplier=a.get('rooms') if a['type']=='accommodation' else query['people_number']
                if expected is None or multiplier is None or not same(a['cost']['value'],expected*multiplier):unsupported.append('cost_multiplicity')
                if not set(a['cost']['evidence_ids'])<=set(a['price']['evidence_ids']):unsupported.append('cost_unlinked_evidence')
            else:quantity(a['cost'],a['entity_id'],'price',allow_decision=True)
        elif a['type'] in ('train','airplane','transfer'):
            link='leg:'+a.get('start_city','')+'>'+a.get('end_city','')
            quantity(a['price'],link,'intercity_fare')
            if a.get('TrainID') or a.get('FlightID'):
                schedule=[e for e in evidence if e['field']=='intercity_schedule' and e['target_id']==link and e['evidence_id'] in a['evidence_ids']]
                if not schedule:unsupported.append('unverified_intercity_identifier')
        for t in a['transports']:
            target='route:'+t['start']+'>'+t['end']
            quantity(t['duration_minutes'],target,'route_duration');quantity(t['cost'],target,'route_fare')
        for eid in a['evidence_ids']:
            cited.add(eid)
            if eid not in ledger:unsupported.append('unknown_activity_evidence:'+eid)
    gapkeys=set();resolved=set();resolved_levels={};false_resolved=[]
    for gap in plan['gaps']:
        key=target_key(gap['target_id'],gap['field']);gapkeys.add(key)
        if key not in required:continue
        if gap['state'] in ('reference','estimate','verified'):
            matches=[]
            for eid in gap['evidence_ids']:
                cited.add(eid);e=ledger.get(eid)
                if e and assess_evidence(e,required[key],now)['usable'] and (gap['state']==e['level'] or gap['state']=='reference' and e['level'] in ('estimate','verified')):
                    matches.append(eid)
            if matches:resolved.add(key);resolved_levels[key]=gap['state'];used_valid.update(matches)
            else:false_resolved.append(key)
        if key not in resolved:unknown.append(key)
    missing=set(required)-gapkeys
    if missing:issues.extend('unreported_required_gap:'+k for k in sorted(missing))
    if false_resolved:unsupported.extend('false_resolution:'+k for k in false_resolved)
    requested=set();useful=0;requested_field_count=0;useful_field_count=0
    requestids=set()
    for req in plan['retrieval_requests']:
        if req['request_id'] in requestids:issues.append('duplicate_request_id')
        requestids.add(req['request_id']);hits=0
        for field in req['fields']:
            requested_field_count+=1
            key=target_key(req['target_id'],field)
            if key in required:
                r=required[key]
                if city_matches(req['city'],r) and all(req['context'].get(k)==v for k,v in r['context'].items()):requested.add(key);hits+=1;useful_field_count+=1
        useful+=bool(hits)
    if len(plan['retrieval_requests'])>query['retrieval_budget']:issues.append('request_budget_exceeded')
    returned={e['evidence_id'] for event in events for e in event.get('evidence',[])}
    feedbackids={f['evidence_id'] for f in plan['feedback']}
    for f in plan['feedback']:
        eid=f['evidence_id']
        if eid not in returned:issues.append('feedback_without_returned_evidence:'+eid)
        if f['action']=='use' and eid in ledger:
            e=ledger[eid];r=required.get(target_key(e['target_id'],e['field']))
            if r is None or not assess_evidence(e,r,now)['usable']:unsupported.append('used_irrelevant_or_rejected_evidence:'+eid)
        if not set(f['affected_ids'])<=ids:set_missing=set(f['affected_ids'])-ids;issues.extend('feedback_unknown_activity:'+v for v in set_missing)
    # A resolved hours reference must alter/check the chosen times, not merely cite it.
    for key in resolved:
        r=required[key]
        if r['field']=='opening_hours':
            admissible=[ledger[eid]['value'] for gap in plan['gaps'] if target_key(gap['target_id'],gap['field'])==key for eid in gap['evidence_ids'] if eid in ledger and assess_evidence(ledger[eid],r,now)['usable']]
            for a in acts:
                if a['entity_id']==r['target_id']:
                    for v in admissible:
                        if isinstance(v,dict) and (a['start_time']<v.get('open','00:00') or a['end_time']>v.get('close','23:59')):issues.append('hours_not_applied:'+a['activity_id'])
    invalid_returned=set();valid_returned=set()
    for eid in returned:
        e=ledger.get(eid)
        r=required.get(target_key(e['target_id'],e['field'])) if e else None
        if e and r and assess_evidence(e,r,now)['usable']:valid_returned.add(eid)
        else:invalid_returned.add(eid)
    rejected_or_deferred={f['evidence_id'] for f in plan['feedback'] if f['action'] in ('reject','defer')}
    feedback_used={f['evidence_id'] for f in plan['feedback'] if f['action']=='use'}
    changed=bool(previous and previous['itinerary']!=plan['itinerary'])
    hard_ready=not (set(required)-{k for k,v in resolved_levels.items() if v in ('verified','estimate')})
    complete=not issues and not unsupported and hard_ready
    if plan['status']=='complete' and not complete:issues.append('overclaimed_complete')
    return {'schema_ok':True,'schema_errors':[],'protocol_ok':not issues,'safe':not unsupported,
        'complete':complete,'issues':sorted(set(issues)),'unsupported':sorted(set(unsupported)),
        'unknown_requirements':sorted(set(required)-resolved),'resolved_levels':resolved_levels,
        'metrics':{'required_fields':len(required),'gap_recall':len(gapkeys&set(required))/len(required) if required else 1,
            'request_field_coverage':len(requested)/len(required) if required else 1,
            'useful_request_precision':useful/len(plan['retrieval_requests']) if plan['retrieval_requests'] else None,
            'requested_field_count':requested_field_count,'useful_requested_fields':useful_field_count,
            'resolved_fields':len(resolved),'verified_fields':sum(v=='verified' for v in resolved_levels.values()),
            'estimate_fields':sum(v=='estimate' for v in resolved_levels.values()),
            'reference_fields':sum(v=='reference' for v in resolved_levels.values()),
            'returned_evidence':len(returned),'reviewed_evidence':len(feedbackids&returned),
            'valid_used_evidence':len(used_valid&returned),'usable_returned_evidence':len(valid_returned),
            'unusable_returned_evidence':len(invalid_returned),'correctly_rejected_or_deferred':len(rejected_or_deferred&invalid_returned),
            'wrongly_used_evidence':len(feedback_used&invalid_returned),'itinerary_changed':changed}}

def serve(query,requests,evidence,*,budget=None):
    """Actually execute participant retrieval requests against captured evidence.

    This gateway is replay, not a new HTTP call. No evidence is auto-fed if the
    model did not ask for the matching field/context. Invalid candidates are
    returned with their warnings so feedback can be tested independently.
    """
    result=[];limit=query['retrieval_budget'] if budget is None else budget
    for i,req in enumerate(requests):
        response={'request_id':req['request_id'],'status':'unavailable','evidence':[],'reason':'No matching source captured; remain unknown, do not invent.'}
        if i>=limit:response.update(status='budget_exhausted',reason='Episode request budget exhausted')
        else:
            def matches_request(e):
                if e['target_id']!=req['target_id'] or e['field'] not in req['fields']:return False
                if not city_matches(req['city'],e):return False
                # Descriptive metadata (name/city/party/reason/planned_start) is
                # not an extra applicability requirement. Exact binding keys
                # remain strict: date, oriented endpoints, departure and mode.
                binding={'travel_date','departure_at','mode','origin','destination','coord_system','adcode'}
                for k in binding:
                    if k in req['context'] and k in e.get('context',{}) and req['context'][k]!=e['context'][k]:return False
                mandatory={'weather_forecast':{'travel_date'},'price':{'travel_date'},'opening_hours':{'travel_date'},
                    'route_duration':{'travel_date','departure_at','mode','origin','destination','coord_system'},
                    'route_fare':{'travel_date','departure_at','mode','origin','destination','coord_system'},
                    'intercity_schedule':{'travel_date','origin','destination'},'intercity_fare':{'travel_date','origin','destination'}}.get(e['field'],set())
                return all(k in req['context'] and k in e.get('context',{}) and req['context'][k]==e['context'][k] for k in mandatory)
            matches=[e for e in evidence if matches_request(e)]
            if matches:response.update(status='returned',evidence=matches,reason='Captured evidence replay; inspect source scope, level and rejection reasons.')
        result.append(response)
    return result
