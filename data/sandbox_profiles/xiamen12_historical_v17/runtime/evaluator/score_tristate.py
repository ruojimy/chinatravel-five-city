"""Score a frozen plan with three-valued gates; do not expose gold DSL to planners."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import sys


def verdict(states):
    if 'fail' in states:
        return 'fail'
    if not states or 'unknown' in states:
        return 'unknown'
    return 'pass'


def monetary_uncertainty(plan, key):
    if key not in {'daily_budget', 'total_budget', 'restaurant_budget', 'accommodation_budget'}:
        return None
    activities = [a for day in plan.get('itinerary', []) for a in day.get('activities', [])]
    if key == 'restaurant_budget':
        activities = [a for a in activities if a.get('type') in ('breakfast', 'lunch', 'dinner')]
    if key == 'accommodation_budget':
        activities = [a for a in activities if a.get('type') == 'accommodation']
    if not activities:
        return 'No relevant activity costs exist to evaluate this budget.'
    def known(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    for activity in activities:
        if not known(activity.get('cost')):
            return 'An activity cost is missing, invalid, or negative.'
        if key in {'daily_budget', 'total_budget'}:
            if not isinstance(activity.get('transports'), list):
                return 'An activity transport list is missing.'
            if any(not known(t.get('cost')) for t in activity['transports']):
                return 'A local transport cost is missing, invalid, or negative.'
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-root', type=Path, required=True)
    parser.add_argument('--query', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True, help='Private query repair audit; do not share with planner')
    args = parser.parse_args()
    root = args.target_root.resolve()
    sys.path.insert(0, str(root))
    from chinatravel.evaluation import schema_constraint
    from chinatravel.symbol_verification import commonsense_constraint as common
    from chinatravel.symbol_verification import hard_constraint as hard
    from chinatravel.symbol_verification import concept_func
    for module in (schema_constraint, common, hard, concept_func):
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise RuntimeError(f'module leaked outside target root: {module.__file__}')
    query_bytes, plan_bytes = args.query.read_bytes(), args.plan.read_bytes()
    query, plan = json.loads(query_bytes), json.loads(plan_bytes)
    audit = json.loads(args.audit.read_text(encoding='utf-8'))
    uid = query['uid']
    if audit.get('uid') != uid or audit.get('scorer_query_sha256') != sha256(query_bytes).hexdigest():
        raise ValueError('query does not match supplied repair audit')
    if not isinstance(plan, dict) or not plan.get('itinerary'):
        raise ValueError('no nonempty itinerary; record no-plan separately')
    result = {'uid': uid, 'target_root': str(root),
              'query_sha256': sha256(query_bytes).hexdigest(),
              'plan_sha256': sha256(plan_bytes).hexdigest(),
              'scored_utc': datetime.now(timezone.utc).isoformat(), 'groups': []}
    try:
        schema_path = root / 'chinatravel/evaluation/output_schema.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        _, _, ids = schema_constraint.evaluate_schema_constraints([uid], {uid: plan}, schema)
        result['schema'] = {'state': 'pass' if uid in ids else 'fail', 'error': None}
    except Exception as exc:
        result['schema'] = {'state': 'unknown', 'error': f'{type(exc).__name__}: {exc}'}
    public = {k: v for k, v in query.items() if k not in {'hard_logic', 'hard_logic_py', 'hard_logic_nl', 'oracle', 'gold', 'label'}}
    common._set_tool_lang('zh')
    for name in ('Is_activity_grounded', 'Is_intercity_transport_correct', 'Is_attractions_correct',
                 'Is_hotels_correct', 'Is_restaurants_correct', 'Is_transport_correct',
                 'Is_time_correct', 'Is_space_correct'):
        try:
            table, messages = getattr(common, name)(public, plan, verbose=False)
            cells = {str(k): int(v) for k, v in table.iloc[0].items() if k != 'data_id'}
            if not cells:
                raise ValueError('checker returned no result cells')
            state_attr = {'Is_space_correct': 'space_state', 'Is_time_correct': 'time_state'}.get(name)
            state = table.attrs.get(state_attr)
            if name == 'Is_hotels_correct' and not any(cells.values()) and table.attrs.get('room_state') == 'unknown':
                state = 'unknown'
            if state not in ('pass','fail','unknown'):
                state = 'fail' if any(cells.values()) else 'pass'
            result['groups'].append({'name': name, 'state': state,
                                     'cells': cells, 'messages': messages,
                                     'conditional_assumptions': [m for m in messages if isinstance(m,str) and m.startswith('Conditional zero assumption')]})
        except Exception as exc:
            result['groups'].append({'name': name, 'state': 'unknown', 'error': f'{type(exc).__name__}: {exc}'})
    result['commonsense'] = {'state': verdict([x['state'] for x in result['groups']])}
    # The native evaluator swallows DSL errors as False. Evaluate identically
    # but preserve exceptions as unknown, without emitting hidden source code.
    hard._set_tool_lang('zh')
    clauses = query.get('hard_logic_py') or []
    hard_results = []
    repaired_records = {r['repaired_index']: r for r in audit['clauses'] if r.get('repaired_index') is not None}
    for index, clause in enumerate(clauses):
        try:
            record = repaired_records[index]
            reason = monetary_uncertainty(plan, record['key'])
            if reason:
                hard_results.append({'index': index, 'state': 'unknown', 'reason': reason})
                continue
            env = deepcopy(hard.func_dict)
            env['plan'] = plan
            hard.execute_dsl_code(hard._normalize_legacy_hard_logic_py(clause), env, allowed_builtins={'set': set})
            if 'result' not in env:
                raise ValueError('clause did not set result')
            state = 'pass' if bool(env['result']) else 'fail'
            hard_results.append({'index': index, 'state': state})
        except Exception as exc:
            hard_results.append({'index': index, 'state': 'unknown', 'error': f'{type(exc).__name__}: {exc}'})
    unresolved = audit.get('unresolved_requirements') or []
    result['hard'] = {'state': verdict([x['state'] for x in hard_results] + ['unknown'] * len(unresolved)),
                      'clauses': hard_results, 'unresolved_requirements': unresolved}
    from chinatravel.environment.requested_places import evaluate as evaluate_requested_places
    result['requested_places'] = evaluate_requested_places(public, plan)
    result['overall'] = verdict([result['schema']['state'], result['commonsense']['state'], result['hard']['state'], result['requested_places']['state']])
    result['policy'] = 'A failed gate determines fail; checker errors are unknown if no other definite gate fails.'
    result['query_audit_sha256'] = sha256(args.audit.read_bytes()).hexdigest()
    result['evaluator_hashes'] = {str(Path(m.__file__).relative_to(root)): sha256(Path(m.__file__).read_bytes()).hexdigest()
                                  for m in (schema_constraint, common, hard, concept_func)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
