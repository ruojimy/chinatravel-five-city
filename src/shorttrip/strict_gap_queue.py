"""Merge strict diagnostic data gaps without turning other failures into work.

This is an offline queue builder: it never chooses a source or makes a request.
An incomplete identity, scope, or evidence policy remains an unresolved gap.
"""
import copy
import hashlib
import json
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import scope_is_complete, identifier_is_known, scope_identifiers_are_known


def _key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _complete(value):
    return scope_is_complete(value)


def build_static_gap_queue(diagnostics, *, identity_verifier=None):
    """Group actionable static gaps by entity, field, scope, and policy.

    Returns invalid entries separately, rather than losing or dispatching them.
    Entity identity must pass an independent verifier at both diagnostic and
    queue stages before a static job can be emitted. Identity-resolution gaps
    are preserved in a separate workflow list; they are never static source
    jobs. Every source still needs its own preflight.
    """
    if not isinstance(diagnostics, list):
        raise ValueError('diagnostics must be a list')
    groups, unresolved, identity_groups = {}, [], {}
    # Identity resolution is entity-wide across the supplied diagnostic batch.
    # A separate report cannot make a static gap dispatchable while any report
    # in this batch still says that same entity's identity is unresolved.
    unresolved_identity_entities = {
        gap.get('entity_id')
        for report in diagnostics if isinstance(report, dict)
        for axes in [report.get('axes')]
        if isinstance(axes, dict) and isinstance(axes.get('data'), list)
        for gap in axes['data']
        if isinstance(gap, dict) and gap.get('reason') == 'identity_unresolved'
        and identifier_is_known(gap.get('entity_id'))
    }
    for report in diagnostics:
        if not isinstance(report, dict) or not isinstance(report.get('uid'), str) or not report['uid']:
            raise ValueError('each diagnostic requires a uid')
        axes = report.get('axes')
        if not isinstance(axes, dict) or not isinstance(axes.get('data'), list):
            raise ValueError('each diagnostic requires a data axis')
        for gap in axes['data']:
            if not isinstance(gap, dict):
                unresolved.append({'uid': report['uid'], 'reason': 'malformed_data_gap'})
                continue
            if gap.get('required') is not True or gap.get('blocking') is not True:
                continue
            if gap.get('reason') == 'identity_unresolved':
                entity = gap.get('entity_id')
                if identifier_is_known(entity):
                    item = identity_groups.setdefault(entity, {'entity_id': entity,
                        'affected_tasks': [], 'gap_ids': [], 'dispatch_to_static_sources': False})
                    if report['uid'] not in item['affected_tasks']:
                        item['affected_tasks'].append(report['uid'])
                    if isinstance(gap.get('gap_id'), str) and gap['gap_id'] not in item['gap_ids']:
                        item['gap_ids'].append(gap['gap_id'])
                unresolved.append({'uid': report['uid'], 'gap': gap,
                                   'reason': 'identity_resolution_required'})
                continue
            if isinstance(gap.get('entity_id'), str) and gap['entity_id'] in unresolved_identity_entities:
                unresolved.append({'uid': report['uid'], 'gap': gap,
                                   'reason': 'entity_identity_unresolved_in_report'})
                continue
            if (not isinstance(gap.get('gap_id'), str) or not gap['gap_id'].strip() or
                not isinstance(gap.get('reason'), str) or not gap['reason'].strip()):
                unresolved.append({'uid': report['uid'], 'gap': gap, 'reason': 'gap_provenance_incomplete'})
                continue
            if gap.get('entity_identity_verified') is not True:
                unresolved.append({'uid': report['uid'], 'gap': gap,
                                   'reason': 'entity_identity_unverified'})
                continue
            if not callable(identity_verifier):
                unresolved.append({'uid': report['uid'], 'gap': gap,
                                   'reason': 'independent_identity_verifier_required'})
                continue
            try:
                supplied = copy.deepcopy(gap)
                before = copy.deepcopy(supplied)
                identity_ok = (identity_verifier(supplied) is True and
                               strict_snapshot_equal(supplied, before))
            except Exception:
                identity_ok = False
            if not identity_ok:
                unresolved.append({'uid': report['uid'], 'gap': gap,
                                   'reason': 'independent_identity_verification_failed'})
                continue
            if gap.get('repairable') is not True or gap.get('lifecycle', 'static') != 'static':
                unresolved.append({'uid': report['uid'], 'gap': gap, 'reason': 'not_static_actionable'})
                continue
            entity, field, scope, policy = (gap.get('entity_id'), gap.get('field'),
                                            gap.get('context'), gap.get('evidence_policy'))
            if (not identifier_is_known(entity) or
                not identifier_is_known(field) or
                not identifier_is_known(policy) or
                not isinstance(scope, dict) or not _complete(scope) or
                not scope_identifiers_are_known(scope)):
                unresolved.append({'uid': report['uid'], 'gap': gap, 'reason': 'gap_key_incomplete'})
                continue
            try:
                canonical = _key([entity, field, scope, policy])
            except (TypeError, ValueError):
                unresolved.append({'uid': report['uid'], 'gap': gap, 'reason': 'gap_scope_invalid'})
                continue
            item = groups.setdefault(canonical, {'key_sha256': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
                'entity_id': entity, 'field': field, 'scope': scope, 'evidence_policy': policy,
                'identity_verified_by_queue': True,
                'affected_tasks': [], 'gap_ids': [], 'reasons': []})
            for key, value in (('affected_tasks', report['uid']), ('gap_ids', gap.get('gap_id')),
                               ('reasons', gap.get('reason'))):
                if value is not None and value not in item[key]:
                    item[key].append(value)
    return {'static_jobs': sorted(groups.values(), key=lambda x: x['key_sha256']),
            'identity_resolution_workflow': [identity_groups[k] for k in sorted(identity_groups)],
            'unresolved': unresolved, 'source_selection_performed': False}
