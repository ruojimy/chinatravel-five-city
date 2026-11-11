"""Offline P31-to-v4 strict diagnostic smoke; not a planner evaluation."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from p31_static import build_plan
from shorttrip.strict_p31_bridge import diagnose_p31_plan
from shorttrip.strict_v4_reader import V4Reader
from shorttrip.strict_gap_queue import build_static_gap_queue

CITIES = ['西安', '厦门', '宁波', '长沙', '青岛']
CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--level', choices=('easy','human'), default='easy')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    tasks_path = ROOT / 'results/p31_five_city_96/tasks' / (args.level + '.json')
    if output.exists():
        raise FileExistsError('Preserve immutable smoke artifact')
    tasks = json.loads(tasks_path.read_text(encoding='utf-8'))
    now = datetime.now(timezone.utc).isoformat()
    reader = V4Reader(CATALOG)
    try:
        cases = []
        for city in CITIES:
            task = next(t for t in tasks if t.get('city_sequence', [None])[0] == city)
            plan = build_plan(task)  # Build in memory; archived outputs remain untouched.
            planned = []
            for day in plan.get('days', []):
                for item in day.get('timeline', []) if isinstance(day, dict) and isinstance(day.get('timeline'), list) else []:
                    if isinstance(item, dict) and item.get('type') in (
                            'visit', 'attraction', 'breakfast', 'lunch', 'dinner', 'meal'):
                        planned.append((day, item))
            record_requirements = []
            missing_records = []
            selected_ids = []
            for day, item in planned:
                name = item.get('entity')
                typ = item.get('type')
                expected_kind = 'restaurant' if typ in ('breakfast', 'lunch', 'dinner', 'meal') else 'attraction'
                item_city = day.get('city', city)
                # P31 retains labels only. Resolve through the frozen task's
                # explicit candidate entity ID and reject ambiguity/mismatch.
                matches = [c for c in task['candidates'] if c.get('kind') == expected_kind
                           and c.get('city') == item_city and c.get('name') == name]
                if len(matches) != 1:
                    missing_records.append(name)
                    continue
                try:
                    record = reader.get(matches[0]['entity_id'])
                except KeyError:
                    missing_records.append(name)
                    continue
                if record['city'] != item_city or record['kind'] != expected_kind or record['name'] != name:
                    missing_records.append(name)
                    continue
                selected_ids.append(record['id'])
                price_scope = ({'ticket': 'ordinary_adult', 'currency': 'CNY'}
                               if expected_kind == 'attraction' else
                               {'meal': 'per_person', 'currency': 'CNY'})
                record_requirements.append((record, [{'native_field': 'price',
                    'policy_field': 'price', 'scope': price_scope}]))
            result = diagnose_p31_plan(
                plan, now=now, registry={}, record_requirements=record_requirements, task=task)
            if missing_records:
                result['axes']['pipeline'].append({'reason': 'selected_entity_resolution_failed',
                                                   'labels': missing_records})
                result['outcome'] = 'pipeline_error'
            cases.append({
                'city': city, 'task_uid': task['uid'], 'plan_uid': plan['uid'],
                'selected_candidates': [{'type': x.get('type'), 'name': x.get('entity')}
                                        for _, x in planned],
                'selected_entity_ids': selected_ids,
                'v4_record_ids': [r['id'] for r, _ in record_requirements],
                'unmatched_v4_records': missing_records,
                'diagnostic': result,
            })
        artifact = {
            'label': 'engineering_smoke', 'evaluation_at': now,
            'task_source': str(tasks_path.relative_to(ROOT)).replace('\\','/'),
            'task_source_sha256': hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
            'catalog': 'data/five_city_reference_v4_20261026/catalog.sqlite3',
            'catalog_sha256': hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
            'evaluator_sha256': {str(p.relative_to(ROOT)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__).resolve(), ROOT/'src/shorttrip/strict_p31_bridge.py',
                          ROOT/'src/shorttrip/strict_plan_diagnostics.py', ROOT/'src/shorttrip/strict_v4_adapter.py',
                          ROOT/'src/shorttrip/strict_gap_queue.py', ROOT/'src/shorttrip/strict_evidence.py',
                          ROOT/'src/shorttrip/strict_constraints.py', ROOT/'src/shorttrip/strict_snapshot.py', ROOT/'src/shorttrip/strict_scope.py', ROOT/'src/shorttrip/strict_itinerary_checks.py',
                          ROOT/'src/shorttrip/strict_p31_constraints.py', ROOT/'src/shorttrip/strict_v4_evidence.py',
                          ROOT/'src/shorttrip/strict_route_solver.py', ROOT/'src/shorttrip/strict_route_proof.py',
                          ROOT/'src/shorttrip/route_context_ttl.py', ROOT/'src/shorttrip/strict_fields.py',
                          ROOT/'src/shorttrip/strict_hours.py', ROOT/'src/shorttrip/strict_hours_parser.py',
                          ROOT/'src/shorttrip/strict_tag_constraints.py', ROOT/'src/shorttrip/strict_lodging.py',
                          ROOT/'src/shorttrip/strict_intercity.py', ROOT/'src/shorttrip/strict_constraint_compiler.py',
                          ROOT/'src/shorttrip/collection_workflow.py', ROOT/'src/shorttrip/freshness.py',
                          ROOT/'src/shorttrip/expansion_contract.py', ROOT/'src/shorttrip/strict_v4_reader.py',
                          ROOT/'scripts/p31_static.py', ROOT/'scripts/p31_common.py']},
            'cities': CITIES, 'source_profiles': 'empty; no field-specific approval supplied',
            'requirements': {'price': {'ticket': 'ordinary_adult', 'currency': 'CNY'}},
            'formal_metric': False, 'planner_completeness_claimed': False,
            'execution_confirmed': False, 'cases': cases,
        }
        reports = [case['diagnostic'] for case in cases]
        queue = build_static_gap_queue(reports)
        artifact['gap_queues'] = {
            'static': queue,
            'runtime': [{'uid': r['uid'], 'gap': gap} for r in reports
                        for gap in r['axes']['data'] if gap.get('lifecycle') == 'runtime'],
            'other_axes': {axis: [{'uid': r['uid'], 'gap': gap} for r in reports
                                  for gap in r['axes'].get(axis, [])]
                           for axis in ('adapter', 'pipeline', 'context', 'access', 'solver')},
            'hard_failures': [{'uid': r['uid'], 'check': check} for r in reports
                              for check in r['hard_failures']],
            'source_selection_performed': False,
            'network_requests': 0,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'artifact': str(output), 'cities': len(cases),
                          'unmatched_records': sum(len(c['unmatched_v4_records']) for c in cases),
                          'outcomes': [c['diagnostic']['outcome'] for c in cases],
                          'formal_metric': False}, ensure_ascii=False))
    finally:
        reader.close()


if __name__ == '__main__':
    main()
