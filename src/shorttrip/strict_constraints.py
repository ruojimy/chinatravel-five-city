"""Three-valued checks of selected structured travel constraints.

These checks consume explicitly scoped facts, not P31 estimates. A separate
caller-provided verifier must attest each fact; without it every value is
unknown. The result is never an overall itinerary feasibility certificate.
"""
import copy
from .strict_snapshot import strict_snapshot_equal as _strict_snapshot_equal
from .strict_money import exact_money
from .strict_scope import identifier_is_known, scope_is_complete, scope_identifiers_are_known


def _minutes(clock):
    if (not isinstance(clock, str) or len(clock) != 5 or clock[2] != ':' or
            not clock.isascii() or not clock[:2].isdigit() or not clock[3:].isdigit()):
        return None
    try:
        hours, minutes = int(clock[:2]), int(clock[3:])
    except ValueError:
        return None
    return hours * 60 + minutes if 0 <= hours < 24 and 0 <= minutes < 60 else None


def evaluate_constraint(constraint, fact, *, fact_verifier=None):
    """Evaluate one supported operator as pass/fail/unknown, with reasons.

    fact is a dict with value, unit, and exact context. The verifier receives
    (constraint, fact) and must independently attest provenance, semantics and
    applicability; a fact's own flags cannot satisfy this gate.
    """
    def result(state, reason):
        return {'state': state, 'reason': reason, 'execution_confirmed': False}

    if not isinstance(constraint, dict) or not isinstance(constraint.get('expression'), dict):
        return result('unknown', 'malformed_constraint')
    expression = constraint['expression']
    op, args = expression.get('op'), expression.get('args')
    if op not in ('total_cost_at_most', 'count_at_least', 'arrive_by'):
        return result('unknown', 'operator_unsupported')
    if not isinstance(args, dict) or not isinstance(fact, dict):
        return result('unknown', 'input_or_fact_missing')
    if constraint.get('strength') != 'hard':
        return result('unknown', 'soft_preference_not_hard_check')
    try:
        constraint_before, fact_before = copy.deepcopy(constraint), copy.deepcopy(fact)
        constraint_copy, fact_copy = copy.deepcopy(constraint_before), copy.deepcopy(fact_before)
        verified = (callable(fact_verifier) and fact_verifier(constraint_copy, fact_copy) is True
                    and _strict_snapshot_equal(constraint_copy, constraint_before)
                    and _strict_snapshot_equal(fact_copy, fact_before)
                    and _strict_snapshot_equal(constraint, constraint_before)
                    and _strict_snapshot_equal(fact, fact_before))
    except Exception:
        verified = False
    if not verified:
        return result('unknown', 'independent_fact_verifier_required')
    context = fact.get('context')
    if not isinstance(context, dict):
        return result('unknown', 'fact_context_missing')

    if op == 'total_cost_at_most':
        includes = args.get('includes')
        components = context.get('includes')
        if (set(args) != {'CNY', 'people', 'includes'} or
            not isinstance(includes, list) or not includes or
            not all(identifier_is_known(x) for x in includes) or
            len(set(includes)) != len(includes) or not isinstance(components, list) or
            not all(isinstance(x, str) and x for x in components) or
            len(components) != len(includes) or set(components) != set(includes) or
            set(context) != {'people', 'includes'} or type(context.get('people')) is not int or
            context.get('people') != args.get('people') or type(args.get('people')) is not int or
            args['people'] < 1 or fact.get('unit') != 'CNY'):
            return result('unknown', 'cost_scope_or_unit_mismatch')
        value, limit = fact.get('value'), args.get('CNY')
        value, limit = exact_money(value), exact_money(limit)
        if value is None or limit is None:
            return result('unknown', 'cost_value_invalid')
        return result('pass' if value <= limit else 'fail', 'verified_cost_comparison')

    if op == 'count_at_least':
        count = args.get('count')
        expected = {k: v for k, v in args.items() if k != 'count'}
        if (not expected or not scope_is_complete(expected) or not scope_identifiers_are_known(expected) or
                ('kind' in expected and not identifier_is_known(expected['kind'])) or
                not _strict_snapshot_equal(context, expected) or type(count) is not int or count < 0 or
                type(fact.get('value')) is not int or fact['value'] < 0 or fact.get('unit') != 'count'):
            return result('unknown', 'count_scope_or_value_invalid')
        return result('pass' if fact['value'] >= count else 'fail', 'verified_count_comparison')

    if set(args) != {'day', 'destination', 'time'}:
        return result('unknown', 'arrival_scope_or_time_invalid')
    expected = {'day': args.get('day'), 'destination': args.get('destination')}
    deadline, arrival = _minutes(args.get('time')), _minutes(fact.get('value'))
    if (type(expected['day']) is not int or expected['day'] < 1 or
        not identifier_is_known(expected['destination']) or
        not _strict_snapshot_equal(context, expected) or fact.get('unit') != 'local_time' or deadline is None or arrival is None):
        return result('unknown', 'arrival_scope_or_time_invalid')
    return result('pass' if arrival <= deadline else 'fail', 'verified_arrival_comparison')
