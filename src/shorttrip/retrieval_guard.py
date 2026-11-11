"""P25 field-specific eligibility, monetary/transport checks and safe projection.

Immutable evidence is authoritative for allowed usage, not a participant's state
label. Conditional acceptance and confirmed execution are separate outcomes.
"""
from __future__ import annotations
import copy,hashlib,json,math
from datetime import datetime,timedelta,timezone
from jsonschema import Draft202012Validator
from . import retrieval_benchmark as old
from .freshness import parse_time

VERSION='shorttrip-dynamic-v2'
STRICT={'identity','inventory','room_configuration','intercity_schedule'}
FORECAST={'weather_forecast','route_duration','route_fare'}

def schema():
    s=copy.deepcopy(old.schemas()['plan']);s['$id']=VERSION+'/plan';s['properties']['schema_version']={'const':VERSION}
    t=s['properties']['itinerary']['items']['properties']['activities']['items']['properties']['transports']['items']
    t['properties'].update(price=old.quantity_schema(),tickets={'type':'integer','minimum':1},cars={'type':'integer','minimum':1})
    return s

def gate(e,r,now):
    result=old.assess_evidence(e,r,now);reasons=list(result['reasons']);field=r['field'];level=e.get('level')
    if field in STRICT and level!='verified':reasons.append('field_requires_verified_binding')
    if field=='identity' and level=='verified':
        proof=e.get('identity_binding',{})
        if e.get('synthetic'):
            if not e.get('fixture_validated'):reasons.append('unvalidated_fixture')
        else:
            try:
                raw=json.loads(e['raw_text']);pois=raw['pois'];poi=next(v for v in pois if v.get('id')==proof.get('provider_id'))
                if e.get('source_id')!='amap' or not proof.get('expected_name') or poi.get('name')!=proof['expected_name'] or poi.get('cityname')!=r['city']+'市':reasons.append('identity_binding_mismatch')
                if not proof.get('provider_id') or e.get('value',{}).get('provider_id')!=poi['id']:reasons.append('identity_id_mismatch')
            except (ValueError,KeyError,TypeError,StopIteration):reasons.append('identity_binding_not_in_raw')
    if field in FORECAST:
        if level not in ('estimate','verified'):reasons.append('field_requires_provider_estimate')
        if e.get('source_id')!='amap' and not e.get('synthetic'):reasons.append('provider_required')
        if not e.get('synthetic'):
            observed=parse_time(e.get('source_observed_at'));deadline=parse_time(e.get('valid_until'));at=parse_time(now)
            if not observed or not deadline or not at:reasons.append('estimate_clock_required')
            elif observed>at+timedelta(minutes=5):reasons.append('future_observation')
    if field in ('route_duration','route_fare'):
        c=e.get('context',{})
        if not e.get('synthetic'):
            if e.get('entity_verified') is not True:reasons.append('route_endpoints_not_bound')
            if e.get('mode_requirement_met') is not True:reasons.append('route_mode_not_met')
        if not all(c.get(k) for k in ('origin','destination','departure_at','coord_system','mode')):reasons.append('exact_route_context_required')
        if c.get('coord_system')!='GCJ02':reasons.append('verified_gcj02_required')
        if not isinstance(e.get('value'),(int,float)) or isinstance(e.get('value'),bool) or not math.isfinite(e['value']) or e['value']<0:reasons.append('invalid_route_number')
        if e.get('unit')!=('minutes' if field=='route_duration' else 'CNY/person'):reasons.append('route_unit_mismatch')
    if field=='price' and level=='reference' and not e.get('synthetic'):
        if e.get('price_scope')!='adult_general_per_person_CNY':reasons.append('price_scope_unverified')
        # A root-reviewed price extraction must retain the numeric source line.
        if str(int(e['value']) if isinstance(e.get('value'),(int,float)) and float(e['value']).is_integer() else e.get('value')) not in e.get('raw_text',''):reasons.append('price_not_in_source_excerpt')
    if field=='inventory' and not e.get('synthetic'):
        if not e.get('booking_confirmation_id') or not e.get('value',{}).get('confirmed_available'):reasons.append('inventory_not_confirmed')
    if e.get('conflict'):reasons.append('unresolved_source_conflict')
    return {'usable':not reasons,'reasons':sorted(set(reasons)),'max_status':level if not reasons else 'unknown',
        'can_resolve':not reasons,'execution_guaranteed':False,
        'requires_condition':not reasons and (level in ('reference','estimate') or field in FORECAST),
        'synthetic':bool(e.get('synthetic'))}

def annotate_events(events,now):
    """Explicit eligibility accompanies clues; unavailable clues never get fill permission."""
    out=copy.deepcopy(events)
    for event in out:
        event['eligibility']={}
        for e in event['evidence']:
            r={k:e[k] for k in ('target_id','city','field','context')}
            event['eligibility'][e['evidence_id']]=gate(e,r,now)
    return out

def triage(request):
    fields=set(request['fields']);context=request.get('context',{})
    if fields&{'route_duration','route_fare'} and not all(context.get(k) for k in ('origin','destination','coord_system','departure_at')):
        return {'status':'needs_clarification','missing':[k for k in ('origin','destination','coord_system','departure_at') if not context.get(k)],'network_allowed':False}
    if fields&{'intercity_schedule','intercity_fare'}:
        return {'status':'adapter_required','missing':[],'network_allowed':False}
    return {'status':'ready','missing':[],'network_allowed':True}

def _ledger(evidence):return {e['evidence_id']:e for e in evidence}
def _req(query,target,field):
    return next((r for r in query['requirements'] if r['target_id']==target and r['field']==field),None)
def _eligible(ids,requirement,ledger,now):
    if requirement is None:return []
    return [ledger[i] for i in ids if i in ledger and gate(ledger[i],requirement,now)['usable']]

def _quantity_supported(q,r,ledger,now,*,factor=1):
    if q['status']=='unknown':return q['value'] is None
    if q['value'] is None or q['status']=='decision':return False
    for e in _eligible(q['evidence_ids'],r,ledger,now):
        level=e['level'];status=q['status']
        if not (status==level or status=='reference' and level in ('verified','estimate')):continue
        if isinstance(e['value'],(int,float)) and old.same(q['value'],e['value']*factor):return True
    return False

def monetary_check(plan,limit=None):
    known=0.0;missing=[];decisions=[]
    for day in plan['itinerary']:
        for a in day['activities']:
            for label,q in ([] if a['type']=='anchor' else [(a['activity_id'],a['cost'])])+[(a['activity_id']+':transport:'+str(i),t['cost']) for i,t in enumerate(a['transports'])]:
                if q['value'] is None:missing.append(label)
                elif q['status']=='decision':decisions.append(label)
                else:known+=q['value']
    if limit is None:status='not_requested'
    elif known>limit+1e-6:status='over_budget'
    elif missing or decisions:status='unknown'
    else:status='within_projected_budget'
    return {'status':status,'known_projected_cost':round(known,6),'limit':limit,'unknown_components':missing,'decision_components':decisions,
        'confirmed_paid_total':None,'note':'References/estimates support a projection; never a confirmed bill.'}

def evaluate(query,plan,evidence,events=(),*,now):
    errors=list(Draft202012Validator(schema()).iter_errors(plan))
    if errors:return {'schema_ok':False,'policy_accepted':False,'execution_confirmed':False,'safe':False,'issues':[e.message for e in errors]}
    ledger=_ledger(evidence);view=copy.deepcopy(plan);view['schema_version']=old.VERSION
    for day in view['itinerary']:
        for a in day['activities']:
            for t in a['transports']:
                # V1 transport cost was unit fare; V2 stores group total plus unit price.
                if 'price' in t:t['cost']=t['price']
                for k in ('price','tickets','cars'):t.pop(k,None)
    base=old.evaluate(query,view,evidence,events,now=now)
    issues=[s for s in base.get('issues',[]) if s!='overclaimed_complete'];unsupported=[];resolved={};conditions=[]
    acts=[a for d in plan['itinerary'] for a in d['activities']]
    for gap in plan['gaps']:
        r=_req(query,gap['target_id'],gap['field'])
        if r is None:continue
        key=old.target_key(r['target_id'],r['field'])
        eligible=_eligible(gap['evidence_ids'],r,ledger,now)
        matches=[e for e in eligible if e['level']==gap['state'] or gap['state']=='reference' and e['level'] in ('estimate','verified')]
        if gap['state'] in ('verified','estimate','reference'):
            if not matches:unsupported.append('unqualified_resolution:'+key)
            else:
                allowed=r.get('accepted_levels', ['verified','estimate'] if r['field'] in FORECAST else ['verified'])
                supported=[e for e in matches if e['level'] in allowed]
                if supported:
                    resolved[key]=supported[0]
                    if gate(supported[0],r,now)['requires_condition']:conditions.append(key+':'+supported[0]['level'])
        # Pending/unavailable does not falsely claim a field has been resolved.
    for a in acts:
        if a['type']!='anchor':
            if a['type'] in ('train','airplane','transfer'):
                target='leg:'+a.get('start_city','')+'>'+a.get('end_city','');field='intercity_fare'
            else:target=a['entity_id'];field='price'
            r=_req(query,target,field)
            multiplier=a.get('rooms') if a['type']=='accommodation' else query['people_number']
            is_legacy=next((c for c in query['candidates'] if c['entity_id']==target and c.get('dataset')=='legacy_frozen_sandbox'),None)
            if is_legacy and a['price']['status']=='sandbox':
                if not old.same(a['price']['value'],is_legacy['data'].get('price')) or not old.same(a['cost']['value'],a['price']['value']*multiplier):unsupported.append('legacy_price_or_total_mismatch')
            else:
                if not _quantity_supported(a['price'],r,ledger,now):unsupported.append('unsupported_price:'+a['activity_id'])
                if not _quantity_supported(a['cost'],r,ledger,now,factor=multiplier or 1):unsupported.append('unsupported_total:'+a['activity_id'])
        for t in a['transports']:
            target='route:'+t['start']+'>'+t['end'];fare=_req(query,target,'route_fare');dur=_req(query,target,'route_duration')
            unit=t.get('price',t['cost']);tickets=t.get('tickets',query['people_number'])
            if t['mode'] in ('metro','public_transit') and tickets!=query['people_number']:issues.append('route_ticket_count_mismatch')
            if not _quantity_supported(unit,fare,ledger,now):unsupported.append('unsupported_route_unit_fare:'+a['activity_id'])
            if not _quantity_supported(t['cost'],fare,ledger,now,factor=tickets):unsupported.append('unsupported_route_group_cost:'+a['activity_id'])
            if not _quantity_supported(t['duration_minutes'],dur,ledger,now):unsupported.append('unsupported_route_duration:'+a['activity_id'])
            if t['end_time']<t['start_time']:issues.append('transport_reversed_time')
            if dur:
                departure=parse_time(dur.get('context',{}).get('departure_at'))
                if departure:
                    local=departure.astimezone(timezone(timedelta(hours=8)))
                    if local.strftime('%H:%M')!=t['start_time']:issues.append('route_departure_mismatch')
                if dur['context'].get('mode') and dur['context']['mode']!=t['mode']:issues.append('route_mode_mismatch')
            if t['duration_minutes']['value'] is not None:
                def minutes(clock):
                    h,m=clock.split(':');return int(h)*60+int(m)
                window=minutes(t['end_time'])-minutes(t['start_time'])
                if window+1e-6<t['duration_minutes']['value']+query.get('route_buffer_minutes',0):issues.append('insufficient_transport_window')
            if t['end_time']>a['start_time'] and a['type']!='anchor':issues.append('transport_arrives_after_activity_start')
    for f in plan['feedback']:
        if f['action']!='use':continue
        e=ledger.get(f['evidence_id']);r=_req(query,e['target_id'],e['field']) if e else None
        if not e or not r or not gate(e,r,now)['usable']:unsupported.append('unqualified_feedback_use:'+f['evidence_id'])
    for key,e in resolved.items():
        if e['field']!='opening_hours':continue
        value=e['value']
        for day in plan['itinerary']:
            for a in day['activities']:
                if a['entity_id']!=e['target_id']:continue
                if a['start_time']<value.get('open','00:00') or a['end_time']>value.get('close','23:59') or a['start_time']>value.get('last_admission','23:59'):issues.append('outside_admission_window')
                if value.get('closed_weekday')==datetime.fromisoformat(day['date']).strftime('%A'):issues.append('closed_weekday')
    required={old.target_key(r['target_id'],r['field']) for r in query['requirements'] if not r.get('prerequisite_only')}
    unmet=sorted(required-set(resolved));budget=monetary_check(plan,query.get('budget_cny'))
    if budget['status']=='over_budget':issues.append('budget_exceeded')
    if query.get('budget_cny') is not None and budget['status']=='unknown':unmet.append('budget:unpriced_components')
    prerequisites=[old.target_key(r['target_id'],r['field']) for r in query['requirements'] if r.get('prerequisite_only') and old.target_key(r['target_id'],r['field']) not in resolved]
    accepted=not issues and not unsupported and not unmet
    confirmed=accepted and not conditions and not prerequisites and not any(e.get('synthetic') for e in evidence)
    if plan['status']=='complete' and not confirmed:issues.append('false_execution_completion');accepted=False
    return {'schema_ok':True,'protocol_ok':not issues,'safe':not unsupported,'policy_accepted':accepted,'execution_confirmed':confirmed,
        'issues':sorted(set(issues)),'unsupported':sorted(set(unsupported)),'unmet_requirements':unmet,'prerequisites':prerequisites,
        'conditions':sorted(set(conditions)),'resolved_fields':len(resolved),'budget':budget,
        'synthetic_only':any(e.get('synthetic') for e in evidence),'legacy_base_complete_ignored':True}

def enforce(query,plan,evidence,events=(),*,now):
    """Safe output projection, not an LLM improvement. Original remains untouched."""
    out=copy.deepcopy(plan);out['schema_version']=VERSION;ledger=_ledger(evidence);edits=[]
    known={c['entity_id']:c for c in query['candidates']}
    def endpoint(value):
        if value in known:return value
        matches=[rid for rid,c in known.items() if value in (c['name'],c['name']+'正门',c['name']+'同一正门',c['name']+'入口')]
        return matches[0] if len(matches)==1 else value
    acts=[a for d in out['itinerary'] for a in d['activities']]
    for a in acts:
        c=known.get(a['entity_id'])
        if c:
            text=a['position'];name=c['name'];prefix=text.split('（',1)[0].split('(',1)[0]
            permitted={name} | ({name+'正门',name+'同一正门',name+'入口'} if a['type']=='anchor' else set())
            if prefix in permitted and text!=name:
                edits.append({'field':a['activity_id']+':canonical_position','before':text,'reason':'Explicit entity_id and exact canonical name/entrance prefix; preserve explanatory text in audit'})
                a['position']=name
        for t in a['transports']:
            for k in ('start','end'):
                canonical=endpoint(t[k])
                if canonical!=t[k]:edits.append({'field':a['activity_id']+':transport_'+k,'before':t[k],'after':canonical,'reason':'Exact unique endpoint alias to ID, no fuzzy matching'});t[k]=canonical
    activity_ids={a['activity_id'] for a in acts}
    for f in out['feedback']:
        mapped=[]
        for ref in f['affected_ids']:
            if ref in activity_ids:mapped.append(ref);continue
            matches=[a['activity_id'] for a in acts if a['entity_id']==ref]
            if ref.startswith('weather:'):
                matches=[a['activity_id'] for a in acts if a['city']==ref.split(':',1)[1] and a['type']!='anchor']
            elif ref.startswith('route:'):
                matches=[a['activity_id'] for a in acts if any('route:'+t['start']+'>'+t['end']==ref for t in a['transports'])]
            mapped.extend(matches or [ref])
        mapped=list(dict.fromkeys(mapped))
        if mapped!=f['affected_ids']:
            edits.append({'field':'feedback_affected_ids:'+f['evidence_id'],'before':f['affected_ids'],'after':mapped,'reason':'Known entity/route/weather target mapped to existing activity IDs'})
            f['affected_ids']=mapped
    def reset(q,label):
        if q!={'value':None,'status':'unknown','evidence_ids':[]}:
            edits.append({'field':label,'before':copy.deepcopy(q),'reason':'Evidence eligibility/numeric binding failed'})
            q.clear();q.update(value=None,status='unknown',evidence_ids=[])
    for gap in out['gaps']:
        r=_req(query,gap['target_id'],gap['field'])
        if gap['state'] in ('verified','estimate','reference') and r:
            eligible=_eligible(gap['evidence_ids'],r,ledger,now)
            if not any(e['level']==gap['state'] or gap['state']=='reference' and e['level'] in ('estimate','verified') for e in eligible):
                edits.append({'field':'gap:'+old.target_key(gap['target_id'],gap['field']),'before':gap['state'],'reason':'Not eligible; remain unresolved'})
                gap.update(state='pending',evidence_ids=[])
    for day in out['itinerary']:
        for a in day['activities']:
            if a['type'] in ('anchor','train','airplane','transfer'):continue
            r=_req(query,a['entity_id'],'price')
            is_legacy=any(c['entity_id']==a['entity_id'] and c.get('dataset')=='legacy_frozen_sandbox' for c in query['candidates'])
            if not is_legacy:
                if not _quantity_supported(a['price'],r,ledger,now):reset(a['price'],a['activity_id']+':price')
                factor=a.get('rooms') if a['type']=='accommodation' else query['people_number']
                if not _quantity_supported(a['cost'],r,ledger,now,factor=factor or 1):reset(a['cost'],a['activity_id']+':cost')
    request_ids={r['request_id'] for r in out['retrieval_requests']}
    kept=[]
    for f in out['feedback']:
        if f['evidence_id'] not in ledger and f['evidence_id'] in request_ids and f['action'] in ('defer','reject'):
            edits.append({'field':'request_status_in_evidence_feedback','before':copy.deepcopy(f),'reason':'Request-status note is not evidence; preserve in audit, unresolved gaps remain'})
            continue
        e=ledger.get(f['evidence_id']);r=_req(query,e['target_id'],e['field']) if e else None
        if f['action']=='use' and (not e or not r or not gate(e,r,now)['usable']):
            edits.append({'field':'feedback:'+f['evidence_id'],'before':'use','reason':'Evidence rejected by guard'})
            f.update(action='defer',reason='机器证据门：该证据不具备本字段填值/解决权限，保持未知。'+f['reason'])
        kept.append(f)
    out['feedback']=kept
    if out['status']=='complete':out['status']='conditional';edits.append({'field':'status','before':'complete','reason':'No execution confirmation inferred from a plan'})
    return out,edits
