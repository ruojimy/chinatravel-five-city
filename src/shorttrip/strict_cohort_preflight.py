"""Non-destructive preflight for proposed formal ChinaTravel task cohorts.

This intentionally cannot approve a freeze: full evaluator and independent
evidence verification are not yet integrated. It explains concrete gaps first.
"""
from collections import Counter

from .collection_task_schema import validate_cohort, KINDS
from .strict_constraint_compiler import compile_constraint

CITIES = ('西安', '厦门', '宁波', '长沙', '青岛')
LEVELS = ('easy', 'medium', 'human')
TAG_OPS = frozenset(('prefer_tag', 'conditional_prefer_tag', 'exclude_tag'))
IMPLEMENTED_OPS = frozenset(('total_cost_at_most', 'count_at_least', 'arrive_by')) | TAG_OPS


def validate_freeze_readiness(tasks):
    """Reject schema examples and uncompiled/unsupported formal expressions.

    Passing is necessary, not sufficient, for an actual experiment: caller
    must separately verify evaluator integration, policy and all split coverage.
    """
    validate_cohort(tasks)
    for task in tasks:
        if task['purpose'] == 'schema_example' or task['split'] == 'example':
            raise ValueError('schema examples cannot be formally frozen')
        if task.get('generation', {}).get('draft_only') is True:
            raise ValueError('unreviewed draft cannot be formally frozen: ' + task['uid'])
        for constraint in task['additional_constraints']:
            op = constraint['expression']['op']
            if constraint['compiler_status'] != 'supported' or op not in IMPLEMENTED_OPS:
                raise ValueError('constraint is uncompiled or unsupported: ' + task['uid'] + ':' + constraint['id'])
            if compile_constraint(constraint)['status'] != 'supported':
                raise ValueError('constraint syntax is not independently compiled: ' + task['uid'] + ':' + constraint['id'])
            if op in TAG_OPS:
                scope = constraint['scope']
                if (set(scope) not in ({'domain', 'quantifier'}, {'domain', 'quantifier', 'item_kind'})
                    or scope.get('domain') != 'trip'
                    or scope.get('quantifier') not in ('all', 'any')):
                    raise ValueError('tag scope is underspecified: ' + task['uid'] + ':' + constraint['id'])
                if 'item_kind' in scope and (scope['item_kind'] not in task.get('required_kinds', [])):
                    raise ValueError('tag item_kind is outside task kinds: ' + task['uid'] + ':' + constraint['id'])
    # The current P31 bridge is deliberately incomplete and the reviewed
    # evidence pipeline is not yet established for all required fields.
    # Replace this gate only together with end-to-end verifier evidence.
    raise ValueError('full strict planner and evidence evaluation are not yet verified')


def preflight(development, holdout):
    problems = []
    if not isinstance(development, list) or not isinstance(holdout, list):
        raise ValueError('development and holdout must be lists')
    for split, tasks, per_cell in (('development', development, 4), ('holdout', holdout, 2)):
        try:
            validate_cohort(tasks)
        except (ValueError, TypeError, KeyError) as exc:
            problems.append({'reason': 'schema_invalid', 'split': split, 'detail': str(exc)})
        if len(tasks) != len(CITIES) * len(LEVELS) * per_cell:
            problems.append({'reason': 'split_size_mismatch', 'split': split, 'actual': len(tasks)})
        counts = Counter((t.get('target_city'), t.get('level')) for t in tasks if isinstance(t, dict))
        for city in CITIES:
            for level in LEVELS:
                if counts[(city, level)] != per_cell:
                    problems.append({'reason': 'stratum_size_mismatch', 'split': split,
                                     'city': city, 'level': level, 'actual': counts[(city, level)]})
        coverage = {k for t in tasks if isinstance(t, dict) for k in t.get('required_kinds', [])
                    if isinstance(k, str)}
        missing = sorted(set(KINDS) - coverage)
        if missing:
            problems.append({'reason': 'kind_coverage_missing', 'split': split, 'kinds': missing})
        for city in CITIES:
            city_kinds = {k for t in tasks if isinstance(t, dict) and t.get('target_city') == city
                          for k in t.get('required_kinds', []) if isinstance(k, str)}
            absent = sorted(set(KINDS) - city_kinds)
            if absent:
                problems.append({'reason': 'city_kind_coverage_missing', 'split': split,
                                 'city': city, 'kinds': absent})
        if not any(isinstance(t, dict) and len(set(t.get('required_kinds', []))) >= 3 for t in tasks):
            problems.append({'reason': 'business_chain_coverage_missing', 'split': split})
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if isinstance(task.get('generation'), dict) and task['generation'].get('draft_only') is True:
                problems.append({'reason': 'draft_semantics_not_independently_reviewed', 'uid': task.get('uid')})
            if task.get('split') != split or task.get('purpose') != split:
                problems.append({'reason': 'split_label_mismatch', 'uid': task.get('uid')})
            for constraint in task.get('additional_constraints', []):
                if not isinstance(constraint, dict):
                    continue
                expression = constraint.get('expression') or {}
                op = expression.get('op') if isinstance(expression, dict) else None
                if op not in IMPLEMENTED_OPS:
                    problems.append({'reason': 'operator_unsupported', 'uid': task.get('uid'),
                                     'constraint': constraint.get('id'), 'operator': op})
                if op in TAG_OPS:
                    scope = constraint.get('scope')
                    if (not isinstance(scope, dict) or set(scope) not in (
                            {'domain', 'quantifier'}, {'domain', 'quantifier', 'item_kind'})
                        or scope.get('domain') != 'trip' or scope.get('quantifier') not in ('all','any')):
                        problems.append({'reason': 'tag_scope_underspecified', 'uid': task.get('uid'),
                                         'constraint': constraint.get('id')})
                    elif 'item_kind' in scope and scope['item_kind'] not in task.get('required_kinds', []):
                        problems.append({'reason': 'tag_item_kind_not_required', 'uid': task.get('uid'),
                                         'constraint': constraint.get('id'), 'item_kind': scope['item_kind']})
                if constraint.get('compiler_status') != 'supported':
                    problems.append({'reason': 'constraint_not_compiled', 'uid': task.get('uid'),
                                     'constraint': constraint.get('id')})
                elif compile_constraint(constraint)['status'] != 'supported':
                    problems.append({'reason': 'compiler_recheck_failed', 'uid': task.get('uid'),
                                     'constraint': constraint.get('id')})
    def ids(tasks):
        return {value for t in tasks if isinstance(t, dict)
                for value in (t.get('candidate_selection') or {}).get('required_entity_ids', [])
                if isinstance(value, str)}
    overlap = sorted(ids(development) & ids(holdout))
    if overlap:
        problems.append({'reason': 'development_holdout_candidate_overlap', 'entity_ids': overlap})
    keys = [(t.get('level'), t.get('uid')) for t in development + holdout if isinstance(t, dict)]
    if len(keys) != len(set(keys)):
        problems.append({'reason': 'cross_split_duplicate_task_key'})
    problems.append({'reason': 'complete_planner_and_independent_evidence_verifier_not_integrated'})
    return {'freeze_approved': False, 'development_count': len(development),
            'holdout_count': len(holdout), 'blockers': problems,
            'formal_evaluation_performed': False}
