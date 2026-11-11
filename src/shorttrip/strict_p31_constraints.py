"""Conservative adapter for native P31 task constraints.

P31's legacy ``constraints`` map has no per-field hard/soft declaration and
does not provide the evidence scope required by the strict operators. Native
entries are therefore surfaced as unknown mappings. Explicit structured
constraints can be passed to ``strict_plan_diagnostics`` without rewriting
their strength or expression.
"""
from .strict_plan_diagnostics import diagnose_plan
from .strict_scope import identifier_is_known
from .strict_constraint_compiler import compile_constraint


_STRICT_OPERATORS = {'total_cost_at_most', 'count_at_least', 'arrive_by',
                     'prefer_tag', 'conditional_prefer_tag', 'exclude_tag'}


def map_p31_task_constraints(task):
    """Return structured strict constraints and explicit unresolved mappings.

    No budget components, arrival destinations, or strength labels are
    inferred from P31's scalar ``constraints`` fields.
    """
    if not isinstance(task, dict):
        raise ValueError('task_not_object')
    uid = task.get('uid')
    if not identifier_is_known(uid):
        raise ValueError('task_uid_missing')

    strict_constraints = []
    unresolved = []
    entries = task.get('additional_constraints', [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        unresolved.append(_unresolved('additional_constraints', entries,
                                      'structured_constraints_not_list'))
        entries = []
    seen = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            unresolved.append(_unresolved(f'additional_constraints[{index}]', item,
                                          'structured_constraint_not_object'))
            continue
        cid = item.get('id')
        if not identifier_is_known(cid) or cid in seen:
            unresolved.append(_unresolved(f'additional_constraints[{index}]', item,
                                          'constraint_id_missing_or_duplicate'))
            continue
        seen.add(cid)
        if set(item) - {'id', 'strength', 'scope', 'expression', 'compiler_status'}:
            unresolved.append(_unresolved(cid, item, 'constraint_has_unsupported_fields',
                                          strength=_strength(item.get('strength'))))
            continue
        expression = item.get('expression')
        strength = _strength(item.get('strength'))
        if strength == 'unclassified':
            unresolved.append(_unresolved(cid, item, 'constraint_strength_unclassified', strength=strength))
            continue
        if not isinstance(expression, dict) or not isinstance(expression.get('op'), str):
            unresolved.append(_unresolved(cid, item, 'constraint_expression_malformed',
                                          strength=strength))
            continue
        if item.get('compiler_status') != 'supported' or expression['op'] not in _STRICT_OPERATORS:
            unresolved.append(_unresolved(cid, item,
                'constraint_compiler_or_operator_unsupported', strength=strength))
            continue
        if compile_constraint(item).get('status') != 'supported':
            unresolved.append(_unresolved(cid, item, 'constraint_compile_validation_failed',
                                          strength=strength))
            continue
        # The downstream evaluator owns operator support and independently
        # verifies facts. Preserve ID, strength and expression verbatim.
        strict_constraints.append({key: item[key] for key in ('id', 'strength', 'expression', 'scope', 'compiler_status')
                                   if key in item})

    native = task.get('constraints', {})
    if isinstance(native, dict):
        if any(not isinstance(key, str) for key in native):
            unresolved.append(_unresolved('p31:constraints', native,
                                          'native_constraints_key_invalid'))
        else:
            for key, value in sorted(native.items()):
                strength = _strength(value.get('strength')) if isinstance(value, dict) else 'unclassified'
                unresolved.append(_unresolved('p31:' + str(key), value,
                                              'native_p31_constraint_not_compiled', strength=strength))
    elif native not in (None, []):
        unresolved.append(_unresolved('p31:constraints', native,
                                      'native_constraints_shape_unsupported'))

    return {'task_uid': uid, 'constraints': strict_constraints,
            'constraint_facts': {}, 'unresolved': unresolved,
            'structured_constraints_only': True, 'natural_language_equivalence_verified': False,
            'supported_operators': sorted(_STRICT_OPERATORS)}


def diagnose_p31_task_constraints(task, *, city, record_requirements, registry,
                                  now, candidate, constraint_facts=None,
                                  constraint_fact_verifier=None,
                                  field_evidence_verifier=None,
                                  tag_evidence=None, tag_scope_verifier=None,
                                  identity_verifier=None):
    """Route explicit P31 constraints through strict checks and report gaps.

    The legacy native fields remain unknown checks with their original values.
    They are not added as hard failures when P31 supplied no strength label.
    """
    bundle = map_p31_task_constraints(task)
    facts = bundle['constraint_facts'] if constraint_facts is None else constraint_facts
    result = diagnose_plan(
        uid='strict-p31:' + bundle['task_uid'], city=city,
        record_requirements=record_requirements, registry=registry, now=now,
        candidate=candidate, constraints=bundle['constraints'],
        constraint_facts=facts,
        constraint_fact_verifier=constraint_fact_verifier,
        field_evidence_verifier=field_evidence_verifier,
        tag_evidence=tag_evidence, tag_scope_verifier=tag_scope_verifier,
        identity_verifier=identity_verifier)
    # Use the same reclassification as the P31 plan bridge: unresolved hard
    # mappings must remain an adapter blocker, not merely a displayed check.
    from .strict_p31_bridge import _merge_constraint_mapping
    result = _merge_constraint_mapping(result, bundle)
    result['p31_constraint_mapping']['structured_constraints_only'] = True
    result['p31_constraint_mapping']['natural_language_equivalence_verified'] = False
    return result


def _strength(value):
    return value if value in ('hard', 'soft') else 'unclassified'


def _unresolved(cid, value, reason, strength='unclassified'):
    return {'id': cid, 'value': value, 'strength': strength,
            'state': 'unknown', 'reason': reason}
