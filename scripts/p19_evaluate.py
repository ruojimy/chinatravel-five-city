"""Independent evidence-aware evaluator for expanded-sandbox query-to-plan pilot.

Official output schema and DSL execute computable checks. Real-world evidence
checks are project-specific, three-valued, and never claimed as official EPR.
"""
import collections
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'ChinaTravel')]
from jsonschema import Draft7Validator
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
from shorttrip.freshness import utcnow

OUT = ROOT / 'results/p19_query_to_plan'

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0

def main():
    sealed = read(OUT / 'private/preregistered_hashes.json')
    assert all(hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == h for f, h in sealed.items())
    protocol = read(OUT / 'public/protocol.json')
    assert hashlib.sha256((ROOT / protocol['baseline']['catalog']).read_bytes()).hexdigest() == protocol['baseline']['sha256']
    rules = read(OUT / 'private/constraints.json')
    queries = {q['case_id']: q for q in read(OUT / 'public/queries.json')}
    db = sqlite3.connect((ROOT / protocol['baseline']['catalog']).resolve().as_uri() + '?mode=ro', uri=True)
    overlay = []
    for f in sorted((OUT / 'overlay').glob('v*/claims.json')):
        overlay.extend(read(f)['claims'])
    schema = read(ROOT / 'ChinaTravel/chinatravel/evaluation/output_schema.json')
    outputs = []
    for p in sorted((OUT / 'plans').glob('*/*.json')):
        cid, stage = p.parent.name, p.stem
        query, rule, answer = queries[cid], rules[cid], read(p)
        plan = answer['proposed_plan']
        days = plan.get('itinerary', [])
        activities = [dict(a, _day=d.get('day')) for d in days for a in d.get('activities', [])]
        selected = {}
        for a in activities:
            rid = a.get('entity_id')
            if rid:
                row = db.execute('SELECT payload FROM records WHERE id=?', (rid,)).fetchone()
                if row:
                    selected[rid] = json.loads(row[0])
        checks = []
        def add(name, status, detail):
            checks.append({'name': name, 'status': ('pass' if status is True else 'fail' if status is False else 'unknown'), 'detail': detail})
        codes = [f"result=(day_count(plan)=={query['days']})", f"result=(people_count(plan)=={query['people_number']})",
                 "count=0\nfor activity in allactivities(plan):\n    if activity_type(activity)=='attraction':\n        count+=1\nresult=(count>=2)",
                 f"count=0\nfor activity in allactivities(plan):\n    if activity_type(activity)=='lunch':\n        count+=1\nresult=(count=={rule['lunches']})"]
        dsl = evaluate_constraints_py(codes, plan)
        for name, result in zip(('days', 'people', 'at_least_two_attraction_activities', 'lunch_count'), dsl):
            add(name, result, 'Official ChinaTravel DSL over proposed plan only; not environmental validity.')
        attractions = [a for a in activities if a.get('type') == 'attraction']
        unique = {a.get('entity_id') for a in attractions}
        grounded = all(a.get('entity_id') in selected and selected[a['entity_id']]['kind'] == 'attraction' and selected[a['entity_id']]['city'] == query['city'] and a.get('position') == selected[a['entity_id']]['name'] for a in attractions)
        add('distinct_catalogue_attractions', grounded and len(unique) >= 2, 'Catalogue identity only; does not prove current operator identity or access.')
        tag_support = all(any(t['tag'] == rule['required_theme'] and t['value'] is True for t in selected.get(a.get('entity_id'), {}).get('tags', [])) for a in attractions)
        add('requested_theme_tag_recalled', tag_support, 'Derived TAG matching; not an independent attraction-content truth label.')
        lunch_days = collections.Counter(a['_day'] for a in activities if a.get('type') == 'lunch')
        add('one_lunch_each_day', all(lunch_days.get(d.get('day')) == 1 for d in days), dict(lunch_days))
        chronological = True
        for d in days:
            previous = '00:00'
            for a in d.get('activities', []):
                start, end = a.get('start_time'), a.get('end_time')
                if not isinstance(start, str) or not isinstance(end, str) or not (previous <= start <= end <= '23:59'):
                    chronological = False
                if isinstance(end, str):
                    previous = end
        add('proposed_activity_chronology', chronological, 'Planned activity slots only; unresolved transfer feasibility is scored separately.')
        # A proposed return is a decision, not evidence that the return is possible.
        returns = answer.get('return_to_start') or plan.get('return_to_start')
        add('return_by_deadline_verified', None, {'deadline': rule['end_by'], 'proposal_metadata': returns,
                                                'reason': 'No qualified exact-context final transfer evidence.'})
        all_costs = [a.get('cost') for a in activities]
        all_costs += [t.get('cost') for a in activities for t in a.get('transports', [])]
        computable_cost = sum(all_costs) if all(number(x) for x in all_costs) and all_costs else None
        add('budget_verified', None, {'budget': rule['budget'], 'model_declared_arithmetic_total': computable_cost,
                                     'reason': 'Budget requires eligible dated activity and every transfer cost; arithmetic alone cannot certify it.'})
        claims = [c for c in overlay if c['entity_id'] in selected]
        def qualified(field):
            return [c for c in claims if c['field'] == field and (c['ingest_verdict']['usable_as_hard_fact'] or c['ingest_verdict']['usable_as_labelled_estimate'])]
        add('venue_opening_and_admission_verified', None, 'References/unknown source clocks cannot guarantee the planned date or slot.')
        add('exact_context_amap_transfers_verified', None, {'qualified_duration_claims': len(qualified('route_duration')),
                                                         'qualified_fare_claims': len(qualified('route_fare')),
                                                         'reason': 'Amap remains paused; no static-speed substitution.'})
        weather = [c for c in overlay if c['field'] == 'weather_forecast' and c.get('case_id') == cid]
        usable_weather = [c for c in weather if c['ingest_verdict']['usable_as_labelled_estimate'] and query['date'] in c.get('coverage_dates', [])]
        add('applicable_weather_checked', True if usable_weather else None, {'source_estimates': len(usable_weather), 'not_a_weather_guarantee': True})
        if cid == 'D01':
            add('non_spicy_lunch_verified', None, 'Cuisine/category/name is not proof of selected dish preparation.')
        if cid == 'D02':
            hotels = [a for a in activities if a.get('type') == 'accommodation']
            add('one_room_one_night_proposed', len(hotels) == 1 and hotels[0].get('rooms') == 1 if hotels else False, 'Choice only, not inventory confirmation.')
            add('two_single_beds_available_for_dates', None, 'Literal room configuration and dated inventory must both pass; OR options cannot be summed.')
            add('dated_total_and_cancellation_verified', None, 'Checkin/out, adults, rooms, taxes and cancellation/discount eligibility remain required.')
        revision = OUT / 'public/revision.json'
        if stage == 'revised' and revision.exists():
            rev = read(revision)
            add('revision_banned_entity_removed', rev['banned_entity_id'] not in selected, rev['banned_entity_id'])
            add('revision_locked_entities_preserved', all(x in selected for x in rev['locked_entity_ids']), rev['locked_entity_ids'])
        schema_errors = list(Draft7Validator(schema).iter_errors(plan))
        unsupported = [f for f in answer.get('fact_claims', []) if f.get('status') in ('verified', 'corroborated', 'hard_fact') and not any(c['claim_id'] in f.get('evidence_refs', []) and c['ingest_verdict']['usable_as_hard_fact'] for c in overlay)]
        counts = collections.Counter(c['status'] for c in checks)
        strict_pass = counts['fail'] == 0 and counts['unknown'] == 0 and not schema_errors
        outputs.append({'case_id': cid, 'stage': stage, 'answer_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                        'model_status': answer['status'], 'proposal_delivered': bool(activities),
                        'official_output_schema_ok': not schema_errors,
                        'official_output_schema_errors': [{'path': list(e.absolute_path), 'message': e.message} for e in schema_errors],
                        'official_dsl_subset': {'codes': codes, 'results': dsl, 'scope': 'Computable structural subset only, not full logical/official score'},
                        'adapted_evidence_aware_checks': checks, 'check_counts': dict(counts),
                        'strict_accepted_plan': strict_pass, 'unsupported_claimed_hard_facts': unsupported,
                        'tag_recall_used': any(read(x)['request']['operation'] == 'lookup' for x in (OUT / 'events' / cid).glob('*.json'))})
    db.close()
    result = {'at': utcnow(), 'baseline_unchanged': True, 'evaluations': outputs,
              'official_benchmark_scores': None, 'real_world_accuracy': None,
              'method': 'Official schema plus official DSL subset; independent three-valued project checks over dynamic evidence.',
              'limitations': ['Two custom queries, one inherited-model participant, one sample per stage.',
                             'No known feasible witness. Missing evidence is unknown, never a proof of infeasibility.',
                             'No hidden oracle supplied to participant; no checker feedback before dynamic_first.',
                             'Original ChinaTravel commonsense scorer not applied to unregistered new-city discovery records or raw real routes.',
                             'Project acceptance is stricter than proposal delivery; no official DR/EPR/LPR/FPR claim.']}
    (OUT / 'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{'case': x['case_id'], 'stage': x['stage'], 'counts': x['check_counts'], 'accepted': x['strict_accepted_plan']} for x in outputs], ensure_ascii=False))

if __name__ == '__main__':
    main()
