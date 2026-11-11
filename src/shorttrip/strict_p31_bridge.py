"""Conservative bridge from P31 plans to strict candidate diagnostics.

P31 labels, estimated travel times, costs, and feasibility flags are never
treated as verified evidence. This bridge diagnoses every activity and
travel leg independently; it is not a complete itinerary feasibility solver.
"""
import copy
from datetime import date, datetime, timedelta

from .collection_workflow import classify
from .strict_plan_diagnostics import diagnose_plan
from .strict_p31_constraints import map_p31_task_constraints
from .strict_snapshot import strict_snapshot_equal


_ACTIVITY_TYPES = {'visit', 'attraction', 'breakfast', 'lunch', 'dinner', 'meal'}
_MEAL_TYPES = {'breakfast', 'lunch', 'dinner', 'meal'}
_SUPPORTED_TYPES = _ACTIVITY_TYPES | {'travel', 'wait'}


def diagnose_p31_plan(plan, *, now, registry, record_requirements=(),
                      field_evidence_verifier=None, task=None,
                      constraint_facts=None, constraint_fact_verifier=None,
                      evidence_auditor=None, tag_evidence=None, tag_scope_verifier=None,
                      identity_verifier=None,
                      itinerary_interval_verifier=None,
                      itinerary_endpoint_verifier=None, lodging=None, lodging_verifier=None,
                      overnight_boundaries=None, overnight_fact_verifier=None,
                      overnight_lodging_verifier=None,
                      meal_coverage=None, meal_policy_verifier=None,
                      meal_inventory_verifier=None, meal_event_verifier=None,
                      intercity=None, intercity_verifier=None,
                      finite_route_domain=None, finite_route_evidence_verifier=None,
                      business_chain=None, chain_inventory_verifier=None, chain_event_verifier=None,
                      cost_aggregation=None, cost_evidence_verifier=None,
                      cost_inventory_verifier=None, cost_context_verifier=None,
                      cost_lodging_claim_verifier=None,
                      cost_lodging_inventory_verifier=None,
                      cost_intercity_policy_verifier=None,
                      cost_intercity_inventory_verifier=None,
                      cost_intercity_segment_verifier=None,
                      cost_intercity_timetable_verifier=None,
                      cost_intercity_fare_verifier=None):
    """Diagnose each activity/meal and route leg in a P31 plan.

    The output reports evidence gaps only. It does not establish whether the
    overall itinerary is feasible, and proposal metadata is intentionally
    discarded as evidence.
    """
    if not isinstance(plan, dict):
        return _pipeline_error('plan_not_object')
    uid, level, days = plan.get('uid'), plan.get('level'), plan.get('days')
    if not isinstance(uid, str) or not uid or level not in ('easy', 'medium', 'human'):
        return _pipeline_error('plan_identity_or_level_invalid', uid=uid)
    if not isinstance(days, list) or not days:
        return _pipeline_error('plan_days_missing', uid=uid)

    try:
        protected_inputs = (plan, registry, record_requirements, task, constraint_facts,
            tag_evidence, lodging, overnight_boundaries, meal_coverage, intercity,
            finite_route_domain, business_chain, cost_aggregation)
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return _pipeline_error('p31_inputs_cannot_be_snapshotted', uid=uid)

    constraint_bundle = None
    if task is not None:
        try:
            constraint_bundle = map_p31_task_constraints(task)
        except ValueError as exc:
            return _adapter_error(str(exc), uid=uid)
        if constraint_bundle['task_uid'] != uid:
            return _adapter_error('task_plan_uid_mismatch', uid=uid)

    candidates = []
    day_adapter_gaps = []
    city = None
    activity_count = 0
    for day_index, day in enumerate(days):
        if not isinstance(day, dict):
            return _pipeline_error('day_timeline_malformed', uid=uid)
        day_city = day.get('city')
        if not isinstance(day_city, str) or not day_city:
            return _pipeline_error('plan_city_missing', uid=uid)
        if city is None:
            city = day_city
        date = day.get('date')
        if not isinstance(date, str):
            return _pipeline_error('day_date_missing', uid=uid)
        try:
            datetime.fromisoformat(date)
        except ValueError:
            return _pipeline_error('day_date_malformed', uid=uid)
        if 'timeline' not in day:
            if day_index == 0:
                return _adapter_error('day_timeline_unsupported', uid=uid)
            native_fields = ('departure', 'arrival', 'intercity', 'old_attraction',
                             'visit_start', 'visit_end', 'feasible', 'reasons')
            present_fields = [field for field in native_fields if field in day]
            if not present_fields:
                day_adapter_gaps.append(_day_adapter_gap(uid, day_index,
                                                        'nonstandard_day_shape', [], day))
                continue
            if not any(field in day for field in ('departure', 'arrival', 'intercity', 'old_attraction')):
                day_adapter_gaps.append(_day_adapter_gap(uid, day_index,
                                                        'day_timeline_unsupported', present_fields, day))
            # Preserve the native P31 fields as adapter gaps. Times, segment
            # feasibility labels, and intercity estimates remain unverified.
            for field in present_fields:
                if field in ('visit_start', 'visit_end'):
                    continue
                day_adapter_gaps.append(_day_adapter_gap(uid, day_index,
                                                        'p31_multiday_field_unverified', [field], day))
            if 'old_attraction' in day and 'visit_start' in day and 'visit_end' in day:
                start, end = _interval(date, {'start': day['visit_start'],
                                               'end': day['visit_end']})
                if start is not None and end > start:
                    candidates.append({'diagnostic_kind': 'activity',
                        'candidate': _candidate(start, end, {
                            'candidate_type': 'old_attraction', 'day_index': day_index,
                            'entity_label': day.get('old_attraction')})})
                    activity_count += 1
                else:
                    day_adapter_gaps.append(_day_adapter_gap(uid, day_index,
                                                            'old_attraction_interval_unusable',
                                                            ['visit_start', 'visit_end'], day))
            continue
        if not isinstance(day.get('timeline'), list):
            return _pipeline_error('day_timeline_malformed', uid=uid)
        for item_index, item in enumerate(day['timeline']):
            if not isinstance(item, dict):
                return _pipeline_error('timeline_item_malformed', uid=uid)
            typ = item.get('type')
            if typ not in _SUPPORTED_TYPES:
                return _adapter_error('timeline_type_unsupported', uid=uid)
            if typ in _ACTIVITY_TYPES:
                start, end = _interval(date, item)
                if start is None or end <= start:
                    return _pipeline_error('activity_interval_malformed', uid=uid)
                context = {'candidate_type': 'meal' if typ in _MEAL_TYPES else 'activity',
                           'day_index': day_index, 'activity_index': item_index}
                candidates.append({'diagnostic_kind': 'activity',
                                   'candidate': _candidate(start, end, context)})
                activity_count += 1
            elif typ == 'travel':
                # Endpoint labels alone are insufficient route evidence. Keep
                # only labels; discard minutes, status and fare estimates.
                route_context = {}
                if isinstance(item.get('from'), str): route_context['origin'] = item['from']
                if isinstance(item.get('to'), str): route_context['destination'] = item['to']
                start, end = _interval(date, item)
                if start is None or end <= start:
                    return _pipeline_error('travel_interval_malformed', uid=uid)
                candidates.append({'diagnostic_kind': 'route',
                                   'candidate': _candidate(start, end, route_context)})
            elif typ == 'wait':
                start, end = _interval(date, item)
                if start is None or end <= start:
                    return _pipeline_error('wait_interval_malformed', uid=uid)
        # A day with no travel still has activity diagnostics; route evidence
        # remains unknown for each activity candidate.
    if activity_count == 0:
        return _pipeline_error('activity_not_found', uid=uid)
    cost_context_valid = _p31_cost_context_matches_task(task, uid, days)
    # Aggregate budget is deliberately one unknown candidate. P31 static
    # totals and individual nominal costs are estimate metadata only.
    candidates.append({'diagnostic_kind': 'budget',
                       'candidate': _candidate(datetime(2000, 1, 1),
                                               datetime(2000, 1, 1, 0, 1), {})})
    diagnostic = diagnose_plan(
        uid='strict-p31:' + uid, city=city,
        record_requirements=record_requirements, registry=registry, now=now,
        candidate=candidates, field_evidence_verifier=field_evidence_verifier,
        plan_uncertainty='chronology_and_coverage_unverified',
        constraints=constraint_bundle['constraints'] if constraint_bundle else (),
        constraint_facts=(constraint_facts if constraint_facts is not None else
                          (constraint_bundle['constraint_facts'] if constraint_bundle else None)),
        constraint_fact_verifier=constraint_fact_verifier,
        evidence_auditor=evidence_auditor, level=level,
        tag_evidence=tag_evidence, tag_scope_verifier=tag_scope_verifier,
        identity_verifier=identity_verifier, itinerary_days=days,
        itinerary_interval_verifier=itinerary_interval_verifier,
        itinerary_endpoint_verifier=itinerary_endpoint_verifier,
        overnight_boundaries=overnight_boundaries,
        overnight_fact_verifier=overnight_fact_verifier,
        overnight_lodging_verifier=overnight_lodging_verifier,
        meal_coverage=meal_coverage, meal_policy_context=task,
        meal_policy_verifier=meal_policy_verifier,
        meal_inventory_verifier=meal_inventory_verifier,
        meal_event_verifier=meal_event_verifier,
        lodging=lodging, lodging_verifier=lodging_verifier,
        intercity=intercity, intercity_verifier=intercity_verifier,
        finite_route_domain=finite_route_domain,
        finite_route_evidence_verifier=finite_route_evidence_verifier,
        business_chain=business_chain, chain_inventory_verifier=chain_inventory_verifier,
        chain_event_verifier=chain_event_verifier,
        cost_aggregation=cost_aggregation,
        cost_evidence_verifier=cost_evidence_verifier,
        cost_inventory_verifier=cost_inventory_verifier,
        cost_context_verifier=cost_context_verifier,
        cost_lodging_claim_verifier=cost_lodging_claim_verifier,
        cost_lodging_inventory_verifier=cost_lodging_inventory_verifier,
        cost_intercity_policy_verifier=cost_intercity_policy_verifier,
        cost_intercity_inventory_verifier=cost_intercity_inventory_verifier,
        cost_intercity_segment_verifier=cost_intercity_segment_verifier,
        cost_intercity_timetable_verifier=cost_intercity_timetable_verifier,
        cost_intercity_fare_verifier=cost_intercity_fare_verifier,
        cost_task_uid=constraint_bundle['task_uid'] if constraint_bundle else None,
        cost_plan_uid=uid,
        cost_target_city=(task.get('target_city') if isinstance(task, dict) else None),
        cost_task_input=task,
        cost_plan_input=plan,
        cost_context_valid=cost_context_valid)
    if not strict_snapshot_equal(protected_inputs, protected_snapshot):
        return _pipeline_error('p31_original_inputs_mutated', uid=uid)
    if constraint_bundle is not None:
        diagnostic = _merge_constraint_mapping(diagnostic, constraint_bundle)
    if day_adapter_gaps:
        diagnostic = _merge_adapter_gaps(diagnostic, day_adapter_gaps)
    diagnostic['structured_constraints_only'] = True
    diagnostic['natural_language_equivalence_verified'] = False
    return diagnostic


def _merge_constraint_mapping(diagnostic, bundle):
    """Attach unresolved task mappings and reclassify with hard gaps included."""
    soft_checks = list(diagnostic.get('soft_checks', []))
    extra_checks, extra_gaps = [], []
    for item in bundle['unresolved']:
        check = {'field': 'constraint:' + item['id'], 'state': 'unknown',
                 'reason': item['reason'], 'strength': item['strength']}
        if item['strength'] == 'soft':
            soft_checks.append(check)
        else:
            extra_checks.append(check)
            if item['strength'] in ('hard', 'unclassified'):
                extra_gaps.append({'gap_id': diagnostic['uid'] + ':' + item['id'],
                    'blocker_class': 'adapter', 'reason': item['reason'],
                    'required': True, 'blocking': True, 'repairable': False,
                    'constraint_strength': item['strength']})
    result = _reclassify(diagnostic, extra_gaps=extra_gaps, extra_checks=extra_checks,
                         soft_checks=soft_checks)
    result.update({'p31_constraint_mapping': {
        'task_uid': bundle['task_uid'],
        'mapped_constraint_ids': [item['id'] for item in bundle['constraints']],
        'unresolved': bundle['unresolved'],
        'structured_constraints_only': True,
        'natural_language_equivalence_verified': False,
        'execution_confirmed': False,
    }})
    return result


def _merge_adapter_gaps(diagnostic, extra_gaps):
    return _reclassify(diagnostic, extra_gaps=extra_gaps,
                       soft_checks=list(diagnostic.get('soft_checks', [])))


def _reclassify(diagnostic, *, extra_gaps=(), extra_checks=(), soft_checks=()):
    gaps = [gap for entries in diagnostic['axes'].values() for gap in entries
            if isinstance(gap, dict) and gap.get('gap_id')]
    gaps.extend(extra_gaps)
    checks = (list(diagnostic.get('hard_failures', [])) + list(diagnostic.get('unknown_checks', [])) +
              list(diagnostic.get('passed_checks', [])))
    checks.extend(extra_checks)
    result = classify({'uid': diagnostic['uid'], 'city': diagnostic['city'], 'level': diagnostic['level'],
                       'gaps': gaps, 'hard_checks': checks,
                       'planner': {'supported': False}, 'plan_present': True,
                       'required_checks_complete': False})
    result.update({'label': 'engineering_smoke', 'truth_certified': False,
                   'soft_checks': list(soft_checks),
                   'evidence_audits': list(diagnostic.get('evidence_audits', [])),
                   'execution_confirmed': False})
    if 'itinerary_checks' in diagnostic:
        result['itinerary_checks'] = diagnostic['itinerary_checks']
    if 'overnight_checks' in diagnostic:
        result['overnight_checks'] = diagnostic['overnight_checks']
    if 'meal_coverage_check' in diagnostic:
        result['meal_coverage_check'] = diagnostic['meal_coverage_check']
    if 'lodging_check' in diagnostic:
        result['lodging_check'] = diagnostic['lodging_check']
    if 'intercity_check' in diagnostic:
        result['intercity_check'] = diagnostic['intercity_check']
    if 'route_domain_check' in diagnostic:
        result['route_domain_check'] = diagnostic['route_domain_check']
    if 'business_chain_check' in diagnostic:
        result['business_chain_check'] = diagnostic['business_chain_check']
    if 'trip_cost_aggregation_check' in diagnostic:
        result['trip_cost_aggregation_check'] = diagnostic['trip_cost_aggregation_check']
    return result


def _day_adapter_gap(uid, day_index, reason, fields, day=None):
    return {'gap_id': f'strict-p31:{uid}:day:{day_index + 1}:{reason}',
            'blocker_class': 'adapter', 'reason': reason, 'required': True,
            'blocking': True, 'repairable': False,
            'detail': {'fields': fields,
                       'unverified_values': {key: day.get(key) for key in fields}
                                            if isinstance(day, dict) else {}}}


def _interval(date, item):
    try:
        start, end = item['start'], item['end']
        if not isinstance(start, str) or not isinstance(end, str):
            return None, None
        first, last = datetime.fromisoformat(date + 'T' + start), datetime.fromisoformat(date + 'T' + end)
        if (first.utcoffset() is None) != (last.utcoffset() is None):
            return None, None
        return first, last
    except (KeyError, TypeError, ValueError):
        return None, None


def _p31_cost_context_matches_task(task, plan_uid, days):
    """Require the complete ordered plan dates and target to match task scope."""
    if not isinstance(task, dict) or not isinstance(days, list) or not days:
        return False
    task_uid, target_city = task.get('uid'), task.get('target_city')
    start_date, day_count = task.get('start_date'), task.get('days')
    if (not isinstance(task_uid, str) or not task_uid.strip() or task_uid != plan_uid or
            not isinstance(target_city, str) or not target_city.strip() or
            not isinstance(start_date, str) or type(day_count) is not int or day_count < 1 or
            len(days) != day_count):
        return False
    try:
        start = date.fromisoformat(start_date)
        if start.isoformat() != start_date:
            return False
        expected = [(start + timedelta(days=index)).isoformat() for index in range(day_count)]
    except (ValueError, OverflowError):
        return False
    actual = [day.get('date') if isinstance(day, dict) else None for day in days]
    if actual != expected:
        return False
    return isinstance(days[-1], dict) and days[-1].get('city') == target_city


def _candidate(start, end, context, activity_kind='activity'):
    return {
        'activity': {'start': start, 'end': end, 'windows': None},
        'route_requirement': {'context': context}, 'route_evidence': {},
        # Costs and budget are unknown; P31 static totals are estimates only.
        'required_costs': [None], 'budget': None,
    }


def _pipeline_error(reason, uid=None):
    return _error(reason, uid, 'pipeline')


def _adapter_error(reason, uid=None):
    return _error(reason, uid, 'adapter')


def _error(reason, uid, axis):
    key = uid if isinstance(uid, str) and uid else 'unknown'
    result = classify({'uid': 'strict-p31:' + key, 'level': 'easy', 'city': 'unknown',
                       'gaps': [{'gap_id': 'strict-p31:' + key + ':' + reason,
                                 'required': True, 'blocking': True,
                                 'blocker_class': axis, 'reason': reason}],
                       'hard_checks': [], 'planner': {'supported': False},
                       'plan_present': False, 'required_checks_complete': False})
    result.update({'label': 'engineering_smoke', 'truth_certified': False,
                   'execution_confirmed': False})
    return result
