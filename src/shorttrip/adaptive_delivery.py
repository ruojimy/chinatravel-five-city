"""Budgeted gap retrieval and delivery checks, separate from frozen benchmark truth.

Published references, provider estimates, decisions and certified facts retain
different types. This module never changes the legacy freshness policy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from datetime import date

from .freshness import reconcile


def normalized_stage(stage):
    value = {'static': 'static_first', 'dynamic': 'dynamic_first'}.get(stage, stage)
    if value not in ('static_first', 'dynamic_first', 'revised'):
        raise ValueError('unknown stage')
    return value


def stage_instruction(stage):
    return {
        'static_first': '仅检索静态候选，未知字段生成缺口。',
        'dynamic_first': '读取本次动态证据；逐字段关联实体、日期、来源，更新行程并保留待确认项。',
        'revised': '从实际前稿生成锁定集，排除指定对象，修订后重查约束。',
    }[normalized_stage(stage)]


def canonical_id(rid, aliases):
    seen = set()
    while rid in aliases:
        if rid in seen:
            raise ValueError('alias cycle')
        seen.add(rid)
        rid = aliases[rid]
    return rid


def prioritize_tasks(tasks, *, budget, paused=(), recovered=()):
    """Greedy marginal coverage per request, not one query for every null cell.

    Route keys must contain oriented endpoints, departure time and mode.
    Weather can share one city forecast request across its coverage dates.
    """
    grouped = {}
    for item in tasks:
        t = copy.deepcopy(item)
        context = t.get('context', {})
        if t['kind'] == 'weather':
            scope = {'city': context.get('city'), 'adcode': context.get('adcode')}
        elif t['kind'] == 'route':
            scope = {k: context.get(k) for k in ('origin', 'destination', 'departure_at', 'mode', 'coord_system')}
            if not all(scope.values()):
                raise ValueError('route task needs exact context')
        else:
            scope = {'resource_id': t.get('resource_id') or t.get('entity_id'), 'travel_date': context.get('travel_date')}
        key = json.dumps([t['provider'], t['kind'], scope], sort_keys=True, ensure_ascii=False)
        if key not in grouped:
            grouped[key] = {**t, 'covers': [], 'request_cost': t.get('request_cost', 1), 'scope': scope}
        grouped[key]['covers'] += t.get('covers', [])
        grouped[key]['covers'] = list(dict.fromkeys(grouped[key]['covers']))
    blocked, pending = [], []
    for t in grouped.values():
        if t['provider'] in set(paused) - set(recovered):
            blocked.append({**t, 'status': 'provider_paused'})
        else:
            pending.append(t)
    chosen, covered, spent = [], set(), 0
    while pending:
        eligible = [t for t in pending if spent + t['request_cost'] <= budget]
        if not eligible:
            break
        def score(t):
            gain = sum(t.get('field_weights', {}).get(f, 1) for f in set(t['covers']) - covered)
            return gain * t.get('relevance', 1) / t['request_cost']
        best = max(eligible, key=score)
        if score(best) <= 0:
            break
        chosen.append({**best, 'marginal_score': score(best)})
        spent += best['request_cost']
        covered.update(best['covers'])
        pending.remove(best)
    return {'selected': chosen, 'blocked': blocked, 'deferred': pending,
            'request_units': spent, 'input_tasks': len(tasks), 'grouped_tasks': len(grouped),
            'covered_fields': sorted(covered)}


def evidence_view(claim, registry, *, now, context):
    """Expose evidence use without promoting a read-only reference to hard truth."""
    verdict = reconcile([claim], claim['field'], registry, now=now, context=context,
                        entity_id=claim['entity_id'])
    raw, quote = claim.get('raw_text', ''), claim.get('quote', '')
    literal = bool(quote) and quote in raw and hashlib.sha256(raw.encode()).hexdigest() == claim.get('raw_sha256')
    # A source with valid syntax but an incorrect branch/date stays quarantined.
    reasons = [r for x in verdict['checks'] for r in x['reasons']]
    fatal = ('wrong_field', 'wrong_entity', 'source_host_mismatch', 'unsupported_quote',
             'raw_digest_mismatch', 'known_conflict', 'entity_unverified',
             'unregistered_source', 'source_not_authoritative_for_field', 'extraction_unverified',
             'invalid_numeric_value', 'invalid_unit',
             'context_mismatch:', 'before_applicability_window', 'after_applicability_window')
    checked_reference = literal and claim.get('entity_verified') is True and claim.get('extraction_verified') is True \
        and claim.get('semantic_reviewed') is True and not any(any(r.startswith(f) for f in fatal) for r in reasons)
    if verdict['usable_as_hard_fact']:
        use = 'certified_fact'
    elif verdict['usable_as_labelled_estimate']:
        use = 'provider_estimate'
    elif checked_reference:
        use = 'published_reference'
    else:
        use = 'quarantined'
    return {'claim_id': claim['claim_id'], 'entity_id': claim['entity_id'], 'field': claim['field'], 'value': claim['value'],
            'unit': claim.get('unit'), 'source_url': claim.get('source_url'),
            'context': claim.get('context'), 'evidence_use': use, 'legacy_verdict': verdict,
            'usable_as_hard_fact': verdict['usable_as_hard_fact'],
            'source_clock_known': bool(claim.get('observed_at') or claim.get('source_updated_at')),
            'planning_projection_only': use in ('published_reference', 'provider_estimate')}


def rank_candidates(candidates, *, requested_theme, evidence, aliases=None):
    aliases = aliases or {}
    views = defaultdict(list)
    for v in evidence:
        if v.get('entity_id'):
            views[canonical_id(v['entity_id'], aliases)].append(v)
    ranked = []
    seen = set()
    for item in candidates:
        rid = canonical_id(item['entity_id'], aliases)
        if rid in seen:
            continue
        seen.add(rid)
        facts = views[rid]
        usable = [v for v in facts if v['evidence_use'] != 'quarantined']
        fields = {v['field'] for v in usable}
        # Evidence coverage affects rank, never the truth status of a TAG.
        score = 4 * (requested_theme in item.get('themes', [])) + 3 * len(fields)
        score += 4 * bool(item.get('branch_verified'))
        score -= 5 * bool(item.get('generic_name') or item.get('city_suspect'))
        ranked.append({**item, 'entity_id': rid, 'score': score,
                       'evidence_fields': sorted(fields), 'visit_group_id': item.get('visit_group_id', rid)})
    return sorted(ranked, key=lambda v: (-v['score'], v['entity_id']))


def repair_anchors(answer, query):
    """Repair decision anchors only; never shift evidence clocks or source facts."""
    result, edits = copy.deepcopy(answer), []
    days = result['proposed_plan']['itinerary']
    first, last = days[0]['activities'][0], days[-1]['activities'][-1]
    for obj, key, value in ((first, 'start_time', query['start_time']),
                            (first, 'position', query['anchor']), (last, 'position', query['anchor'])):
        if obj.get(key) != value:
            edits.append({'field': key, 'before': obj.get(key), 'after': value})
            obj[key] = value
    if first.get('end_time', '00:00') < first['start_time']:
        first['end_time'] = first['start_time']
    return result, edits


def select_diverse(ranked, count):
    selected, seen = [], set()
    for item in ranked:
        group = item.get('visit_group_id', item['entity_id'])
        if group not in seen:
            selected.append(item)
            seen.add(group)
        if len(selected) == count:
            break
    return selected


def revision_locks(answer):
    return sorted({a['entity_id'] for d in answer['proposed_plan']['itinerary'] for a in d['activities']
                   if a.get('entity_id') and a['type'] in ('accommodation', 'lunch')})


def normalize_delivery_anchors(plan, request):
    """Represent meeting/return decisions separately from museum activities.

    Adding a zero-duration meeting marker never moves an activity or invents a
    return route. Earlier activities still fail the chronological check.
    """
    result = copy.deepcopy(plan)
    edits = []
    schedule = result['schedule']
    if schedule[0].get('type') != 'start':
        schedule.insert(0, {'type':'start','start_time':request['start_time'],
            'end_time':request['start_time'],'position':request['anchor'],'evidence_refs':[]})
        edits.append('explicit_start_decision_marker')
    if schedule[-1].get('type') != 'end' and schedule[-1]['position'] == request['anchor']:
        at = schedule[-1]['end_time']
        schedule.append({'type':'end','start_time':at,'end_time':at,
                         'position':request['anchor'],'evidence_refs':[]})
        edits.append('explicit_end_decision_marker')
    return result, edits


def minutes(value):
    h, m = map(int, value.split(':'))
    if not 0 <= h < 24 or not 0 <= m < 60:
        raise ValueError('invalid time')
    return h * 60 + m


def evaluate_delivery(plan, request, *, entities, references):
    """Separate proposal correctness, source support and execution prerequisites."""
    checks = []
    def add(name, ok, detail=None):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
    schedule = plan['schedule']
    add('people_and_date', plan['people_number'] == request['people_number'] and plan['date'] == request['date'])
    add('exact_start', schedule[0]['start_time'] == request['start_time'] and schedule[0]['position'] == request['anchor'])
    add('return_anchor_and_deadline', schedule[-1]['position'] == request['anchor'] and minutes(schedule[-1]['end_time']) <= minutes(request['end_time']))
    previous = minutes(request['start_time'])
    valid = True
    for item in schedule:
        start, end = minutes(item['start_time']), minutes(item['end_time'])
        valid &= start >= previous and end >= start
        previous = end
    add('chronology', valid)
    groups = {entities[x['entity_id']].get('visit_group_id', x['entity_id']) for x in schedule if x['type'] == 'attraction' and x.get('entity_id') in entities}
    add('distinct_visit_groups', len(groups) >= request['min_attractions'], sorted(groups))
    add('one_lunch', sum(x['type'] == 'lunch' for x in schedule) == 1)
    for item in schedule:
        rid = item.get('entity_id')
        if rid:
            add('entity_grounded:' + rid, rid in entities)
        if item['type'] == 'attraction' and rid in entities:
            add('theme_supported:' + rid, request['theme'] in entities[rid].get('themes', []))
        for ref in item.get('evidence_refs', []):
            add('reference_resolves:' + ref, ref in references)
        if item['type'] == 'travel':
            route = references.get(item['route_ref'], {})
            wanted = request['date'] + 'T' + item['start_time'] + ':00+08:00'
            add('route_departure_context:' + item['route_ref'], route.get('departure_at') == wanted)
            add('route_mode:' + item['route_ref'], route.get('mode_requirement_met') is True)
            duration = route.get('duration_minutes')
            add('route_fits_buffer:' + item['route_ref'], isinstance(duration, (int, float)) and math.ceil(duration) + request.get('route_buffer_minutes', 10) <= minutes(item['end_time']) - minutes(item['start_time']))
    costs = plan['budget']['items']
    add('all_budget_items_have_basis', all(x.get('basis') in ('published_reference', 'provider_estimate', 'spending_cap_decision') and x.get('evidence_refs') for x in costs))
    add('budget_references_resolve', all(r in references for x in costs for r in x.get('evidence_refs', [])))
    add('budget_arithmetic', abs(sum(x['amount_cny'] for x in costs) - plan['budget']['projection_cny']) < 1e-6)
    add('projection_within_limit', plan['budget']['projection_cny'] <= request['budget_cny'])
    add('no_budget_as_quote', plan['budget'].get('confirmed_total_cny') is None and plan['budget'].get('conditional') is True)
    add('prerequisites_explicit', bool(plan.get('before_departure')))
    return {'proposal_checks': checks, 'proposal_ok': all(x['ok'] for x in checks),
            'execution_certified': False,
            'remaining_prerequisites': plan.get('before_departure', []),
            'scope': 'Proposal decisions and source-linked projections, not inventory, physical arrival or official benchmark acceptance.'}
