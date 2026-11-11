"""Independent evaluator for P20 DeepSeek / expanded-sandbox query-to-plan run.

Three-valued project checks + official ChinaTravel schema and DSL subset.
Unknown is never counted as pass and never treated as proof of infeasibility.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p20_deepseek_dynamic_sandbox'
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'ChinaTravel')]
from jsonschema import Draft7Validator  # noqa: E402
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py  # noqa: E402
from shorttrip.freshness import utcnow  # noqa: E402

FILES_TO_FREEZE = [
    'results/p20_deepseek_dynamic_sandbox/public/protocol.json',
    'results/p20_deepseek_dynamic_sandbox/public/queries.json',
    'results/p20_deepseek_dynamic_sandbox/public/participant_prompt.txt',
    'results/p20_deepseek_dynamic_sandbox/private/constraints.json',
    'scripts/p20_agent.py',
    'scripts/p20_evaluate.py',
]


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def ref_base(ref):
    return str(ref).split('#')[0].replace('\\', '/')


def plan_activities(plan):
    return [dict(a, _day=d.get('day')) for d in plan.get('itinerary', []) for a in d.get('activities', [])]


def check_anchor(activity, rule, db):
    if not isinstance(activity, dict):
        return False
    terms = rule.get('anchor_terms', [])
    position = activity.get('position') or ''
    if any(t and t in position for t in terms):
        return True
    entity_id = activity.get('entity_id')
    if entity_id:
        row = db.execute('SELECT payload FROM records WHERE id=?', (entity_id,)).fetchone()
        if row:
            name = json.loads(row[0]).get('name') or ''
            return any(t and t in name for t in terms)
    return False


def evaluate_one(case_id, stage, answer, query, rule, db, schema, overlay, event_paths):
    checks = []

    def add(name, status, detail):
        checks.append({'name': name,
                       'status': 'pass' if status is True else 'fail' if status is False else 'unknown',
                       'detail': detail})

    plan = answer.get('proposed_plan') or {}
    activities = plan_activities(plan)
    selected = {}
    for a in activities:
        rid = a.get('entity_id')
        if rid:
            row = db.execute('SELECT payload FROM records WHERE id=?', (rid,)).fetchone()
            if row:
                selected[rid] = json.loads(row[0])
    codes = [f"result=(day_count(plan)=={query['days']})",
             f"result=(people_count(plan)=={query['people_number']})",
             "count=0\nfor activity in allactivities(plan):\n    if activity_type(activity)=='attraction':\n        count+=1\n"
             f"result=(count>={rule['min_attractions']})",
             "count=0\nfor activity in allactivities(plan):\n    if activity_type(activity)=='lunch':\n        count+=1\n"
             f"result=(count=={rule['lunches']})"]
    try:
        dsl = evaluate_constraints_py(codes, plan)
    except Exception as exc:  # noqa: BLE001
        dsl = [None, None, None, None]
        add('official_dsl_execution', False, {'error': f'{type(exc).__name__}: {exc}'})
    for name, result in zip(('days', 'people', 'at_least_required_attractions', 'lunch_count'), dsl):
        add(name, result, 'Official ChinaTravel DSL over proposed plan only; not environmental validity.')

    anchor_ids = {a.get('entity_id') for a in activities
                  if a.get('type') in ('start', 'end') and a.get('entity_id')}
    attractions = [a for a in activities if a.get('type') == 'attraction']
    grounded = []
    for a in attractions:
        rid = a.get('entity_id')
        r = selected.get(rid)
        ok = bool(r and r.get('kind') == 'attraction' and r.get('city') == query['city']
                  and a.get('position') == r.get('name') and rid not in anchor_ids)
        if ok:
            grounded.append(a)
    unique_attractions = {a.get('entity_id') for a in grounded}
    add('distinct_catalogue_attractions', len(unique_attractions) >= rule['min_attractions'],
        {'grounded_unique': sorted(unique_attractions), 'anchor_ids_excluded': sorted(x for x in anchor_ids if x)})
    theme_ok = bool(unique_attractions) and all(
        any(t.get('tag') == rule['required_theme'] and t.get('value') is True
            for t in selected[rid].get('tags', [])) for rid in unique_attractions)
    add('requested_theme_tag_recalled', theme_ok,
        {'theme': rule['required_theme'], 'scope': 'derived TAG recall, not independent content truth'})

    lunch_days = collections.Counter(a['_day'] for a in activities if a.get('type') == 'lunch')
    add('one_lunch_each_day', all(lunch_days.get(d.get('day')) == 1 for d in plan.get('itinerary', [])),
        dict(lunch_days))

    chronological = True
    for d in plan.get('itinerary', []):
        previous = '00:00'
        for a in d.get('activities', []):
            start, end = a.get('start_time'), a.get('end_time')
            if not isinstance(start, str) or not isinstance(end, str) or not (previous <= start <= end <= '23:59'):
                chronological = False
            if isinstance(end, str):
                previous = end
    add('proposed_activity_chronology', chronological,
        'Planned slots only; transfer feasibility is scored separately.')

    days = plan.get('itinerary') or [{}]
    first = (days[0].get('activities') or [{}])[0]
    last = (days[-1].get('activities') or [{}])[-1]
    add('start_anchor', first.get('type') == 'start' and first.get('start_time') == rule.get('start_time')
        and check_anchor(first, rule, db), {'type': first.get('type'), 'start_time': first.get('start_time'),
                                            'position': first.get('position')})
    add('end_anchor', last.get('type') == 'end' and isinstance(last.get('end_time'), str)
        and last['end_time'] <= rule['end_by'] and check_anchor(last, rule, db),
        {'type': last.get('type'), 'end_time': last.get('end_time'), 'position': last.get('position'),
         'deadline': rule['end_by']})

    hotels = [a for a in activities if a.get('type') == 'accommodation']
    if rule.get('hotel_nights'):
        hotel_ok = len(hotels) == 1 and hotels[0].get('rooms') == rule.get('rooms')
        add('hotel_room_count', hotel_ok,
            {'hotels': len(hotels), 'rooms': hotels[0].get('rooms') if hotels else None})
        if case_id == 'D02':
            room = hotels[0] if hotels else {}
            twin = (isinstance(room.get('room_type'), str) and any(x in room['room_type'] for x in ('twin', '双床', '两张单人床'))) \
                   or room.get('single_beds') == 2
            add('twin_room_configuration_proposed', twin if twin else None,
                {'room_type': room.get('room_type'), 'single_beds': room.get('single_beds'),
                 'scope': 'proposal only; not dated inventory'})
    else:
        add('hotel_room_count', len(hotels) == 0, {'hotels': len(hotels)})

    if rule.get('require_metro'):
        modes = [t.get('mode') for a in activities for t in a.get('transports', [])]
        metro_ok = bool(modes) and 'metro' in modes and all(m in ('metro', 'walk') for m in modes)
        add('metro_priority', metro_ok, {'modes': modes})
    else:
        add('metro_priority', None, 'not required by query')

    costs = [a.get('cost') for a in activities] + [t.get('cost') for a in activities for t in a.get('transports', [])]
    computable = [x for x in costs if number(x)]
    if costs and len(computable) == len(costs):
        total = sum(computable)
        add('budget_arithmetic', total <= rule['budget'],
            {'budget': rule['budget'], 'sum_of_declared_costs': total,
             'scope': 'declared activity/transport costs only; not verified prices'})
    else:
        add('budget_arithmetic', None, {'budget': rule['budget'], 'declared_costs': costs,
                                        'reason': 'At least one cost is null/unknown; arithmetic cannot certify budget.'})

    numeric = []
    for a in activities:
        for key in ('cost', 'price'):
            if number(a.get(key)):
                numeric.append({'where': 'activity', 'type': a.get('type'), 'key': key,
                                'value': a[key], 'refs': a.get('evidence_refs') or []})
        for t in a.get('transports', []):
            for key in ('cost', 'price'):
                if number(t.get(key)):
                    numeric.append({'where': 'transport', 'mode': t.get('mode'), 'key': key,
                                    'value': t[key], 'refs': t.get('route_evidence_refs') or a.get('evidence_refs') or []})
    add('numeric_costs_cited', all(x['refs'] for x in numeric) if numeric else True,
        {'numeric_costs': numeric[:20], 'count': len(numeric)})

    # A zero may only be used where a source value or a hard fact says free/zero.
    zero_unsupported = []
    for a in activities:
        for key in ('cost', 'price'):
            if a.get(key) == 0:
                rid = a.get('entity_id')
                record_price = (selected.get(rid) or {}).get('data', {}).get('price')
                hard_free = any(c.get('entity_id') == rid and c.get('field') == 'price'
                                and (c.get('ingest_verdict') or {}).get('usable_as_hard_fact')
                                and (c.get('value') in (0, '0') or
                                     (isinstance(c.get('value'), dict) and
                                      any(v == 0 for v in c['value'].values() if isinstance(v, (int, float)))))
                                for c in overlay)
                if record_price != 0 and not hard_free:
                    zero_unsupported.append({'type': a.get('type'), 'key': key, 'entity_id': rid})
    add('zero_cost_has_source_or_hard_evidence', not zero_unsupported,
        {'unsupported_zero_values': zero_unsupported})

    claims = answer.get('fact_claims') or []
    add('fact_claims_have_refs', bool(claims) and all(c.get('evidence_refs') for c in claims),
        {'fact_claims': len(claims)})
    claim_ids = {c.get('claim_id') for c in overlay}
    evidence_ids = {c.get('evidence_id') for c in overlay}
    known_refs = set(event_paths) | claim_ids | evidence_ids
    unresolved = []
    for c in claims:
        for ref in c.get('evidence_refs') or []:
            if ref_base(ref) not in known_refs:
                unresolved.append({'claim': c.get('field'), 'ref': ref})
    add('all_fact_claim_refs_resolve', not unresolved, {'unresolved': unresolved[:20]})

    hard_statuses = {'verified', 'corroborated', 'hard_fact'}
    unsupported = []
    for c in claims:
        if c.get('status') in hard_statuses:
            refs = set(c.get('evidence_refs') or [])
            supported = any(x in refs and x in claim_ids for x in refs) and any(
                x.get('claim_id') in refs and x.get('ingest_verdict', {}).get('usable_as_hard_fact')
                for x in overlay)
            if not supported:
                unsupported.append({'entity_id': c.get('entity_id'), 'field': c.get('field'),
                                    'status': c.get('status')})
    add('no_unsupported_claimed_hard_facts', not unsupported, {'unsupported': unsupported[:20]})

    if stage in ('dynamic_first', 'revised'):
        dynamic_refs = []
        for c in claims:
            dynamic_refs.extend(c.get('evidence_refs') or [])
        for change in answer.get('plan_changes') or []:
            dynamic_refs.extend(change.get('evidence_refs') or [])
        consumed = any(ref_base(x) in claim_ids or
                       (ref_base(x).startswith('events/') and ('evidence' in ref_base(x) or 'submit' in ref_base(x)))
                       for x in dynamic_refs)
        add('dynamic_evidence_consumed', consumed, {'refs': sorted({x for x in dynamic_refs})[:20]})
    else:
        add('dynamic_evidence_consumed', None, 'not applicable to static_first')

    # Evidence-aware checks: strictly unknown unless qualified claims exist.
    def qualified(field, entity_ids=None):
        out = []
        for c in overlay:
            if c.get('field') != field:
                continue
            if entity_ids is not None and c.get('entity_id') not in entity_ids:
                continue
            v = c.get('ingest_verdict') or {}
            if v.get('usable_as_hard_fact') or v.get('usable_as_labelled_estimate'):
                out.append(c)
        return out

    attraction_ids = {a.get('entity_id') for a in attractions if a.get('entity_id')}
    open_claims = qualified('opening_hours', attraction_ids)
    price_claims = qualified('price', attraction_ids)
    venue_ok = bool(attraction_ids) and all(
        any(c.get('entity_id') == rid for c in open_claims) and any(c.get('entity_id') == rid for c in price_claims)
        for rid in attraction_ids)
    add('venue_opening_and_admission_verified', venue_ok if venue_ok else None,
        {'attractions': len(attraction_ids), 'qualified_opening': len(open_claims),
         'qualified_price': len(price_claims)})

    route_claims = qualified('route_duration') + qualified('route_fare')
    planned_segments = sum(len(a.get('transports') or []) for a in activities)
    add('exact_context_amap_transfers_verified', True if planned_segments and len(route_claims) >= 2 * planned_segments else None,
        {'planned_segments': planned_segments, 'qualified_route_claims': len(route_claims),
         'reason': 'Amap remains paused; no static-speed substitution.'})

    weather = [c for c in overlay if c.get('field') == 'weather_forecast' and c.get('case_id') == case_id]
    usable_weather = [c for c in weather if (c.get('ingest_verdict') or {}).get('usable_as_labelled_estimate')
                      and query['date'] in (c.get('coverage_dates') or [])]
    add('applicable_weather_checked', True if usable_weather else None,
        {'applicable_usable_claims': len(usable_weather), 'not_a_weather_guarantee': True})

    if rule.get('no_spicy_hard'):
        spicy_claims = [c for c in overlay if c.get('field') in ('dish_preparation', 'spicy', 'menu')
                        and (c.get('ingest_verdict') or {}).get('usable_as_hard_fact')]
        add('non_spicy_lunch_verified', True if spicy_claims else None,
            {'qualified_claims': len(spicy_claims)})

    if rule.get('hotel_nights'):
        hotel_ids = {h.get('entity_id') for h in hotels if h.get('entity_id')}
        dated = [c for c in overlay if c.get('field') in ('inventory', 'dynamic_price', 'room_configuration')
                 and c.get('entity_id') in hotel_ids
                 and (c.get('ingest_verdict') or {}).get('usable_as_hard_fact')]
        add('dated_room_and_total_verified', True if dated else None, {'qualified_claims': len(dated)})

    revision_file = OUT / 'public/revision.json'
    if stage == 'revised' and revision_file.exists():
        rev = load(revision_file)
        add('revision_banned_entity_removed', rev['banned_entity_id'] not in selected,
            rev['banned_entity_id'])
        add('revision_locked_entities_preserved',
            all(x in selected for x in rev.get('locked_entity_ids', [])), rev.get('locked_entity_ids'))

    schema_errors = list(Draft7Validator(schema).iter_errors(plan))
    add('official_output_schema_ok', not schema_errors,
        {'errors': [{'path': list(e.absolute_path), 'message': e.message} for e in schema_errors][:20]})

    counts = collections.Counter(c['status'] for c in checks)
    strict_pass = counts['fail'] == 0 and counts['unknown'] == 0 and not schema_errors
    return {'case_id': case_id, 'stage': stage,
            'answer_sha256': hashlib.sha256(json.dumps(answer, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'model_status': answer.get('status'), 'proposal_delivered': bool(activities),
            'official_output_schema_ok': not schema_errors,
            'official_output_schema_errors': [{'path': list(e.absolute_path), 'message': e.message}
                                              for e in schema_errors][:20],
            'official_dsl_subset': {'codes': codes, 'results': dsl,
                                    'scope': 'computable structural subset only, not full score'},
            'adapted_evidence_aware_checks': checks, 'check_counts': dict(counts),
            'strict_accepted_plan': strict_pass, 'unsupported_claimed_hard_facts': unsupported,
            'unresolved_evidence_refs': unresolved,
            'grounded_attractions': sorted(unique_attractions),
            'selected_entities': sorted(selected)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true', help='write preregistered hashes; refuses if exists')
    args = parser.parse_args()
    freeze_path = OUT / 'private/freeze.json'
    if args.freeze:
        if freeze_path.exists():
            raise SystemExit('freeze already exists')
        payload = {'at': utcnow(), 'files': {f: digest(ROOT / f) for f in FILES_TO_FREEZE},
                   'baseline_sha256': load(OUT / 'public/protocol.json')['baseline']['sha256'],
                   'note': 'Frozen before the first participant API call; revision.json is a post-freeze input.'}
        freeze_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(payload, ensure_ascii=False))
        return
    freeze = load(freeze_path)
    assert all(digest(ROOT / f) == h for f, h in freeze['files'].items()), 'freeze hash mismatch'
    protocol = load(OUT / 'public/protocol.json')
    catalog = ROOT / protocol['baseline']['catalog']
    assert digest(catalog) == protocol['baseline']['sha256'], 'catalog hash mismatch'
    rules = load(OUT / 'private/constraints.json')
    queries = {q['case_id']: q for q in load(OUT / 'public/queries.json')}
    schema = load(ROOT / 'ChinaTravel/chinatravel/evaluation/output_schema.json')
    db = sqlite3.connect(catalog.resolve().as_uri() + '?mode=ro', uri=True)
    overlay = []
    for f in sorted((OUT / 'overlay').glob('v*/claims.json')):
        overlay.extend(load(f).get('claims', []))
    event_paths = set()
    for p in (OUT / 'events').glob('*/*.json'):
        event_paths.add(str(p.relative_to(ROOT)).replace('\\', '/'))
        event_paths.add('/'.join(p.parts[p.parts.index('events'):]).replace('\\', '/'))
    outputs = []
    for p in sorted((OUT / 'plans').glob('*/*.json')):
        cid, stage = p.parent.name, p.stem
        if cid not in queries:
            continue
        try:
            out = evaluate_one(cid, stage, load(p), queries[cid], rules[cid], db, schema, overlay, event_paths)
        except Exception as exc:  # noqa: BLE001
            out = {'case_id': cid, 'stage': stage, 'evaluation_error': f'{type(exc).__name__}: {exc}',
                   'check_counts': {'fail': 1}, 'strict_accepted_plan': False, 'proposal_delivered': False}
        outputs.append(out)
    db.close()
    delivered = sum(x.get('proposal_delivered', False) for x in outputs)
    no_violation = sum(x.get('check_counts', {}).get('fail', 1) == 0 for x in outputs)
    strict = sum(x.get('strict_accepted_plan', False) for x in outputs)
    all_checks = [c for x in outputs for c in x.get('adapted_evidence_aware_checks', [])]
    check_status = collections.Counter(c['status'] for c in all_checks)
    result = {'at': utcnow(), 'baseline_unchanged': True,
              'freeze_verified': True, 'freeze_at': freeze['at'],
              'evaluations': outputs,
              'metrics': {'plans': len(outputs), 'delivered': delivered,
                          'delivery_rate': round(delivered / len(outputs), 4) if outputs else None,
                          'no_explicit_violation': no_violation,
                          'no_explicit_violation_rate': round(no_violation / len(outputs), 4) if outputs else None,
                          'strict_accepted': strict,
                          'strict_acceptance_rate': round(strict / len(outputs), 4) if outputs else None,
                          'check_status_counts': dict(check_status),
                          'total_checks': len(all_checks)},
              'official_benchmark_scores': None, 'real_world_accuracy': None,
              'method': 'Official schema plus official DSL subset; independent three-valued project checks over dynamic evidence.',
              'limitations': ['Four custom queries; one external model; one deterministic run at temperature 0.',
                              'No known feasible witness. Missing evidence is unknown, never proof of infeasibility.',
                              'The evaluator does not independently verify quoted source semantics beyond the overlay gate.',
                              'Native schema requires numeric cost/price/transport fields; null unknowns correctly fail it.',
                              'No official DR/EPR/LPR/FPR claim and no model ranking.']}
    (OUT / 'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['metrics'], ensure_ascii=False))
    for x in outputs:
        print(x['case_id'], x['stage'], x.get('check_counts'), 'strict', x.get('strict_accepted_plan'))


if __name__ == '__main__':
    main()
