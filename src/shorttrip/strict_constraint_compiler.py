"""Syntactic compilation into the supported strict constraint vocabulary.

Compilation is not a statement that the natural language is semantically
equivalent, a fact is verified, or the itinerary is feasible.
"""
import copy
from .strict_money import exact_money
from .strict_scope import identifier_is_known, scope_is_complete
from .strict_snapshot import strict_snapshot_equal


def compile_constraint(item):
    def fail(reason):
        return {'status': 'unsupported', 'reason': reason, 'constraint': None}
    if not isinstance(item, dict) or not identifier_is_known(item.get('id')):
        return fail('constraint_identity_invalid')
    if set(item) - {'id', 'strength', 'scope', 'expression', 'compiler_status'}:
        return fail('constraint_has_unsupported_fields')
    expression, scope, strength = item.get('expression'), item.get('scope'), item.get('strength')
    if not isinstance(expression, dict) or set(expression) != {'op', 'args'} or not isinstance(expression['args'], dict):
        return fail('expression_invalid')
    op, args = expression['op'], expression['args']
    if op == 'total_cost_at_most':
        if (strength != 'hard' or set(args) != {'CNY','people','includes'} or
            exact_money(args.get('CNY')) is None or
            type(args.get('people')) is not int or args['people'] < 1 or
            not isinstance(args.get('includes'), list) or not args['includes'] or
            not all(identifier_is_known(x) for x in args['includes']) or
            len(set(args['includes'])) != len(args['includes']) or
            not strict_snapshot_equal(scope, {'currency':'CNY','people':args['people'],'unit':'total_trip_cost'})):
            return fail('budget_scope_or_expression_invalid')
    elif op in ('prefer_tag', 'exclude_tag', 'conditional_prefer_tag'):
        if (not isinstance(scope, dict) or set(scope) not in (
                {'domain','quantifier'}, {'domain','quantifier','item_kind'}) or
            scope.get('domain') != 'trip' or scope.get('quantifier') not in ('all','any') or
            strength != ('hard' if op == 'exclude_tag' else 'soft')):
            return fail('tag_scope_or_strength_invalid')
        if 'item_kind' in scope:
            from .collection_task_schema import KINDS
            if not isinstance(scope['item_kind'], str) or scope['item_kind'] not in KINDS:
                return fail('tag_scope_item_kind_invalid')
        if op == 'exclude_tag' and scope['quantifier'] != 'all':
            return fail('trip_exclusion_requires_all')
        if op == 'conditional_prefer_tag':
            if (set(args) != {'if','prefer'} or not isinstance(args['if'],dict) or
                not isinstance(args['prefer'],dict) or len(args['if']) != 1 or len(args['prefer']) != 1 or
                any(not identifier_is_known(k) or not isinstance(v, str) or not scope_is_complete({'value': v})
                    for obj in (args['if'],args['prefer']) for k,v in obj.items())):
                return fail('conditional_expression_invalid')
        elif set(args) != {'tag'} or not identifier_is_known(args['tag']):
            return fail('tag_expression_invalid')
    else:
        # Other operators require their own reviewed compiler, even if another
        # helper has a partial evaluator implementation.
        return fail('operator_compiler_not_implemented')
    result = copy.deepcopy(item)
    result['compiler_status'] = 'supported'
    return {'status':'supported', 'reason':'syntax_and_scope_compiled', 'constraint':result,
            'natural_language_equivalence_verified':False, 'fact_verification_performed':False}
