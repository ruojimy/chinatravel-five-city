"""Combine strict record and candidate diagnostics without upgrading evidence.

This is an engineering adapter, not an exhaustive travel planner. The caller
must supply all candidate facts and independent evidence verifiers.
"""
import copy
import unicodedata
from datetime import date, timedelta

from .collection_workflow import classify
from .strict_fields import room_beds_for_scope
from .strict_v4_adapter import diagnose_candidate, diagnose_record
from .strict_constraints import evaluate_constraint
from .strict_constraint_compiler import compile_constraint
from .strict_tag_constraints import evaluate_tag_constraint
from .strict_itinerary_checks import check_itinerary_chronology_and_continuity
from .strict_lodging import check_lodging
from .strict_intercity import check_intercity
from .strict_route_proof import diagnose_finite_route_domain
from .strict_business_chain import check_business_chain
from .strict_overnight_continuity import check_overnight_continuity
from .strict_meal_coverage import check_meal_coverage
from .strict_snapshot import strict_snapshot_equal
from .strict_cost_constraint_bridge import evaluate_cost_constraint

_UNSET_COST_CONTEXT_VALUE = object()


def _semantic_token(value):
    if not isinstance(value, str):
        return ''
    return unicodedata.normalize('NFKC', value).strip().casefold().replace('-', '_').replace(' ', '_')


def diagnose_plan(*, uid, city, record_requirements, registry, now, candidate,
                  room=None, room_verifier=None, field_evidence_verifier=None,
                  plan_uncertainty=None, constraints=(), constraint_facts=None,
                  constraint_fact_verifier=None, evidence_auditor=None,
                  level='easy', tag_evidence=None, tag_scope_verifier=None,
                  identity_verifier=None, itinerary_days=None,
                  itinerary_interval_verifier=None,
                  itinerary_endpoint_verifier=None, lodging=None, lodging_verifier=None,
                  overnight_boundaries=None, overnight_fact_verifier=None,
                  overnight_lodging_verifier=None,
                  meal_coverage=None, meal_policy_context=None,
                  meal_policy_verifier=None, meal_inventory_verifier=None,
                  meal_event_verifier=None,
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
                  cost_intercity_fare_verifier=None,
                  cost_task_uid=_UNSET_COST_CONTEXT_VALUE,
                  cost_plan_uid=_UNSET_COST_CONTEXT_VALUE,
                  cost_target_city=_UNSET_COST_CONTEXT_VALUE,
                  cost_task_input=None, cost_plan_input=None,
                  cost_context_valid=True):
    protected_inputs = {key: value for key, value in locals().items()
                        if not callable(value) and value is not _UNSET_COST_CONTEXT_VALUE}
    try:
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        protected_snapshot = None
    gaps, checks, evidence_audits = [], [], []
    itinerary_report = None
    overnight_report = None
    meal_report = None
    for record, requirements in record_requirements:
        result = diagnose_record(record, requirements, registry=registry, now=now,
                                 uid=uid + ':' + record['id'],
                                 evidence_verifier=field_evidence_verifier,
                                 evidence_auditor=evidence_auditor,
                                 identity_verifier=identity_verifier)
        evidence_audits.extend(result.get('evidence_audits', []))
        for axis, entries in result['axes'].items():
            for entry in entries:
                # Generic unsupported-planner markers are emitted once below.
                if entry.get('reason') == 'planner_feature_unsupported':
                    continue
                gaps.append(dict(entry, blocker_class=axis, required=True, blocking=True))
        checks.extend(result['hard_failures'] + result['unknown_checks'] + result.get('passed_checks', []))
    proposals = candidate if isinstance(candidate, list) else [candidate]
    for index, item in enumerate(proposals):
        # The typed envelope is used by the P31 bridge. Its closed set of
        # scopes prevents arbitrary callers from suppressing required checks.
        if isinstance(item, dict) and 'diagnostic_kind' in item:
            kind = item.get('diagnostic_kind')
            if kind not in ('activity', 'route', 'budget'):
                raise ValueError('unsupported candidate diagnostic kind')
            payload = item.get('candidate')
            if not isinstance(payload, dict):
                raise ValueError('candidate diagnostic payload malformed')
            proposal = diagnose_candidate(uid=f'{uid}:candidate:{index + 1}', city=city,
                                          now=now, **payload)
            visible_fields = {'activity': {'opening_hours'},
                              'route': {'route'}, 'budget': {'budget'}}[kind]
        else:
            proposal = diagnose_candidate(uid=f'{uid}:candidate:{index + 1}', city=city,
                                          now=now, **item)
            visible_fields = None
        for axis, entries in proposal['axes'].items():
            for entry in entries:
                if entry.get('reason') == 'planner_feature_unsupported':
                    continue
                mapped_field = _field_for_reason(entry.get('reason'))
                if visible_fields is not None and mapped_field is not None and mapped_field not in visible_fields:
                    continue
                gaps.append(dict(entry, blocker_class=axis, required=True, blocking=True))
        checks.extend(c for c in proposal['hard_failures'] + proposal['unknown_checks'] + proposal.get('passed_checks', [])
                      if visible_fields is None or c.get('field') in visible_fields)
    if room is not None:
        beds = room_beds_for_scope(room.get('claim'), room.get('room_type'))
        try:
            # A verifier may inspect this claim, but it must not be able to
            # rewrite either the caller's requirement or the value later used
            # for the comparison. Mutation invalidates the verification.
            verifier_room = copy.deepcopy(room)
            verifier_snapshot = copy.deepcopy(verifier_room)
            verifier_result = (callable(room_verifier) and
                               room_verifier(verifier_room) is True)
            verified = (verifier_result and
                        strict_snapshot_equal(verifier_room, verifier_snapshot) and
                        strict_snapshot_equal(room, verifier_snapshot))
        except Exception:
            verified = False
        if beds is None or not verified:
            gaps.append({'gap_id': uid + ':room', 'blocker_class': 'data',
                         'reason': 'room_scope_or_evidence_unqualified',
                         'required': True, 'blocking': True, 'repairable': False})
            checks.append({'field': 'room_beds', 'state': 'unknown'})
        elif type(room.get('required_beds')) is not int or room['required_beds'] <= 0:
            gaps.append({'gap_id': uid + ':room_context', 'blocker_class': 'context',
                         'reason': 'required_beds_missing', 'required': True, 'blocking': True})
        else:
            checks.append({'field': 'room_beds', 'state': 'pass' if beds >= room['required_beds'] else 'fail'})
    lodging_report = None
    if lodging is not None:
        if not isinstance(lodging, dict):
            raise ValueError('lodging must be a structured requirement and claim')
        lodging_report = check_lodging(lodging.get('requirement'), lodging.get('claim'),
                                       claim_verifier=lodging_verifier)
        checks.append({'field':'lodging_scope_and_beds','state':lodging_report['state'],
                       'reason':lodging_report['reason']})
        if lodging_report['state'] == 'unknown':
            gaps.append({'gap_id':uid+':lodging', 'blocker_class':'data',
                         'reason':lodging_report['reason'], 'required':True,
                         'blocking':True,'repairable':False})
    intercity_report = None
    if intercity is not None:
        if not isinstance(intercity, dict):
            raise ValueError('intercity must be a structured requirement and claim')
        intercity_report = check_intercity(intercity.get('requirement'), intercity.get('claim'),
                                           claim_verifier=intercity_verifier)
        checks.append({'field':'intercity_timetable','state':intercity_report['state'],
                       'reason':intercity_report['reason']})
        if intercity_report['state'] == 'unknown':
            reason=intercity_report['reason']
            axis=('adapter' if reason in ('native_duration_unit_conflict','duration_timetable_conflict')
                  else 'context' if reason in ('intercity_context_missing','intercity_direction_invalid')
                  else 'data')
            gaps.append({'gap_id':uid+':intercity', 'blocker_class':axis,
                         'reason':reason, 'required':True,'blocking':True,'repairable':False})
    route_domain_report = None
    if finite_route_domain is not None:
        if not isinstance(finite_route_domain, dict):
            raise ValueError('finite route domain must be structured')
        route_domain_report = diagnose_finite_route_domain(
            dimensions=finite_route_domain.get('dimensions'),
            candidates=finite_route_domain.get('candidates'),
            evidence=finite_route_domain.get('evidence'), now=now,
            evidence_verifier=finite_route_evidence_verifier)
        # A domain-only result is not a complete itinerary proof. It remains
        # a solver limitation pending a controller-reviewed whole-task proof.
        gaps.append({'gap_id':uid+':finite_route_domain', 'blocker_class':'solver',
                     'reason':'whole_task_proof_not_established', 'required':True,
                     'blocking':True,'repairable':False})
    chain_report = None
    if business_chain is not None:
        if not isinstance(business_chain, dict):
            raise ValueError('business chain must be structured')
        chain_report=check_business_chain(business_chain.get('chain'), business_chain.get('events'),
            inventory_verifier=chain_inventory_verifier, event_verifier=chain_event_verifier)
        checks.append({'field':'business_chain','state':chain_report['state'],'reason':chain_report['reason']})
        if chain_report['state'] == 'unknown':
            gaps.append({'gap_id':uid+':business_chain','blocker_class':'solver',
                         'reason':chain_report['reason'],'required':True,'blocking':True,'repairable':False})
    if plan_uncertainty:
        gaps.append({'gap_id': uid + ':' + str(plan_uncertainty),
                     'blocker_class': 'adapter', 'reason': str(plan_uncertainty),
                     'required': True, 'blocking': True, 'repairable': False})
        checks.append({'field': 'itinerary_chronology_and_coverage', 'state': 'unknown'})
    if itinerary_days is not None:
        def itinerary_verifier(kind, fact):
            verifier = (itinerary_interval_verifier if kind == 'interval'
                        else itinerary_endpoint_verifier)
            if not callable(verifier):
                return False
            try:
                return verifier(fact) is True
            except Exception:
                return False
        itinerary = check_itinerary_chronology_and_continuity(
            itinerary_days, fact_verifier=itinerary_verifier)
        itinerary_report = itinerary
        for axis in ('chronology', 'continuity'):
            item = itinerary[axis]
            field = 'itinerary_' + axis
            state = ('unknown' if axis == 'chronology' and item.get('structural_errors')
                     else item['state'])
            checks.append({'field': field, 'state': state, 'reason': item['reason']})
            if state == 'unknown':
                gaps.append({'gap_id': uid + ':' + field + ':unknown',
                             'blocker_class': 'solver', 'reason': item['reason'],
                             'required': True, 'blocking': True, 'repairable': False})
        if itinerary['chronology']['structural_errors']:
            gaps.append({'gap_id': uid + ':itinerary_structure',
                         'blocker_class': 'adapter',
                         'reason': 'itinerary_structure_malformed',
                         'required': True, 'blocking': True, 'repairable': False,
                         'detail': itinerary['chronology']['structural_errors']})
        overnight_state = 'unknown'
        overnight_reason = 'overnight_itinerary_binding_unavailable'
        if isinstance(itinerary_days, list) and len(itinerary_days) > 1:
            binding = _bind_overnight_boundaries(itinerary_days, overnight_boundaries)
            if binding['complete']:
                def overnight_verifier(kind, fact):
                    if not callable(overnight_fact_verifier):
                        return False
                    try:
                        return overnight_fact_verifier(kind, fact) is True
                    except Exception:
                        return False
                overnight_report = check_overnight_continuity(
                    overnight_boundaries, fact_verifier=overnight_verifier,
                    lodging_claim_verifier=overnight_lodging_verifier)
                overnight_state = overnight_report['state']
                overnight_reason = overnight_report['reason']
            else:
                overnight_report = {'state': 'unknown', 'reason': binding['reason'],
                                     'binding': binding,
                                     'truth_certified': False,
                                     'execution_confirmed': False,
                                     'complete_itinerary_certified': False}
                overnight_reason = binding['reason']
            checks.append({'field': 'itinerary_overnight_continuity',
                           'state': overnight_state, 'reason': overnight_reason})
            if overnight_state == 'unknown':
                gaps.append({'gap_id': uid + ':itinerary_overnight_continuity:unknown',
                             'blocker_class': 'solver', 'reason': overnight_reason,
                             'required': True, 'blocking': True, 'repairable': False})
    if overnight_boundaries is not None and (not isinstance(itinerary_days, list) or len(itinerary_days) < 2):
        overnight_report = {'state': 'unknown', 'reason': 'overnight_itinerary_binding_unavailable',
                            'truth_certified': False, 'execution_confirmed': False,
                            'complete_itinerary_certified': False}
        checks.append({'field': 'itinerary_overnight_continuity', 'state': 'unknown',
                       'reason': overnight_report['reason']})
        gaps.append({'gap_id': uid + ':itinerary_overnight_continuity:unknown',
                     'blocker_class': 'solver', 'reason': overnight_report['reason'],
                     'required': True, 'blocking': True, 'repairable': False})
    if meal_coverage is not None:
        if (not isinstance(meal_coverage, dict) or
                set(meal_coverage) != {'required_slots', 'events'}):
            meal_report = {'state': 'unknown', 'reason': 'meal_coverage_input_malformed',
                           'truth_certified': False, 'execution_confirmed': False,
                           'complete_itinerary_certified': False}
        else:
            binding = (_bind_meal_events(itinerary_days, meal_coverage.get('events'))
                       if isinstance(itinerary_days, list) else
                       {'complete': False, 'reason': 'meal_itinerary_missing'})
            policy_ok = _verify_meal_policy(
                meal_policy_context, meal_coverage.get('required_slots'), meal_policy_verifier)
            if not binding['complete']:
                meal_report = {'state': 'unknown', 'reason': binding['reason'],
                               'binding': binding, 'truth_certified': False,
                               'execution_confirmed': False,
                               'complete_itinerary_certified': False}
            elif not policy_ok:
                meal_report = {'state': 'unknown',
                               'reason': 'meal_required_slots_not_bound_to_task_policy',
                               'binding': binding, 'truth_certified': False,
                               'execution_confirmed': False,
                               'complete_itinerary_certified': False}
            else:
                meal_report = check_meal_coverage(
                    meal_coverage['required_slots'], binding['component_events'],
                    inventory_verifier=meal_inventory_verifier,
                    event_verifier=meal_event_verifier)
                meal_report['binding'] = {'complete': True,
                                          'explicit_meal_item_count': binding['explicit_meal_item_count']}
        checks.append({'field': 'itinerary_meal_coverage',
                       'state': meal_report['state'], 'reason': meal_report['reason']})
        if meal_report['state'] == 'unknown':
            gaps.append({'gap_id': uid + ':itinerary_meal_coverage:unknown',
                         'blocker_class': 'solver', 'reason': meal_report['reason'],
                         'required': True, 'blocking': True, 'repairable': False})
    if not isinstance(constraints, (list, tuple)) or (constraint_facts is not None and not isinstance(constraint_facts, dict)):
        raise ValueError('constraints and constraint facts must be structured')
    facts = constraint_facts or {}
    soft_checks = []
    seen = set()
    for constraint in constraints:
        if not isinstance(constraint, dict) or not isinstance(constraint.get('id'), str) or not constraint['id']:
            raise ValueError('each constraint requires an id')
        cid = constraint['id']
        if cid in seen:
            raise ValueError('duplicate constraint id')
        seen.add(cid)
        expression = constraint.get('expression')
        op = expression.get('op') if isinstance(expression, dict) else None
        if constraint.get('compiler_status') != 'supported':
            evaluated = {'state': 'unknown', 'reason': 'constraint_not_compiled'}
        elif compile_constraint(constraint)['status'] != 'supported':
            evaluated = {'state': 'unknown', 'reason': 'constraint_compile_validation_failed'}
        elif (op == 'conditional_prefer_tag' and
              isinstance(expression.get('args', {}).get('if'), dict) and
              any(_semantic_token(key) in {'weather', '天气'}
                  for key in expression['args']['if'])):
            # The present task schema and fact interface carry no explicit
            # temporal window or quantifier for a multi-day weather condition.
            evaluated = {'state': 'unknown', 'reason': 'weather_temporal_scope_unresolved'}
        elif (op in ('exclude_tag', 'prefer_tag') and
              isinstance(expression.get('args', {}).get('tag'), str) and
              _semantic_token(expression['args']['tag']) in {'night_activity', '夜间活动'}):
            # TAG evidence does not bind a scheduled activity's time window.
            evaluated = {'state': 'unknown', 'reason': 'night_activity_semantics_or_time_unresolved'}
        elif (op == 'conditional_prefer_tag' and
              isinstance(expression.get('args', {}).get('prefer'), dict) and
              any(_semantic_token(value) in {'night_activity', '夜间活动'}
                  for value in expression['args']['prefer'].values())):
            evaluated = {'state': 'unknown', 'reason': 'night_activity_semantics_or_time_unresolved'}
        elif op in ('prefer_tag', 'conditional_prefer_tag', 'exclude_tag'):
            context = tag_evidence.get(cid, {}) if isinstance(tag_evidence, dict) else {}
            if not isinstance(context, dict):
                context = {}
            tag_result = evaluate_tag_constraint(constraint,
                scope_items=context.get('scope_items', ()), tag_facts=context.get('tag_facts', ()),
                condition_facts=context.get('condition_facts', ()),
                fact_verifier=constraint_fact_verifier, scope_verifier=tag_scope_verifier)
            evaluated = {'state': tag_result['state'],
                         'reason': ','.join(tag_result['reasons']) or 'tag_check_unexplained'}
        else:
            evaluated = evaluate_constraint(constraint, facts.get(cid), fact_verifier=constraint_fact_verifier)
        check = {'field': 'constraint:' + cid, 'state': evaluated['state'], 'reason': evaluated['reason'],
                 'natural_language_equivalence_verified': False}
        if constraint.get('strength') == 'soft':
            # Soft preferences are not hard failures and cannot drive collection.
            soft_checks.append(check)
            continue
        checks.append(check)
        if evaluated['state'] == 'unknown':
            gaps.append({'gap_id': uid + ':constraint:' + cid, 'blocker_class': 'adapter'
                         if evaluated['reason'] in ('operator_unsupported', 'constraint_not_compiled',
                                                    'constraint_compile_validation_failed') else 'solver',
                         'reason': evaluated['reason'], 'required': True, 'blocking': True,
                         'repairable': False})

    # Optional aggregate-cost diagnostic; it is additive and never rewrites
    # existing budget or constraint checks.
    total_cost_constraints = []
    for constraint in constraints:
        expression = constraint.get('expression') if isinstance(constraint, dict) else None
        if isinstance(expression, dict) and expression.get('op') == 'total_cost_at_most':
            total_cost_constraints.append(constraint)
    cost_result = None
    if cost_aggregation is not None or total_cost_constraints:
        reason = None
        expected_keys = {'constraint_id', 'policy', 'components', 'scope'}
        allowed_keys = tuple(expected_keys | extras for extras in
                             (set(), {'lodging_manifest'}, {'intercity_manifest'},
                              {'lodging_manifest', 'intercity_manifest'}))
        if (not isinstance(cost_aggregation, dict) or
                set(cost_aggregation) not in allowed_keys):
            reason = 'cost_aggregation_input_missing_or_malformed'
        elif len(total_cost_constraints) != 1:
            reason = ('budget_constraint_missing' if not total_cost_constraints else
                      'budget_constraint_ambiguous')
        elif cost_aggregation.get('constraint_id') != total_cost_constraints[0].get('id'):
            reason = 'cost_constraint_id_mismatch'
        else:
            try:
                task_uid = uid if cost_task_uid is _UNSET_COST_CONTEXT_VALUE else cost_task_uid
                plan_uid = uid if cost_plan_uid is _UNSET_COST_CONTEXT_VALUE else cost_plan_uid
                target_city = city if cost_target_city is _UNSET_COST_CONTEXT_VALUE else cost_target_city
                itinerary_dates = []
                dates_valid = isinstance(itinerary_days, list) and bool(itinerary_days)
                if dates_valid:
                    for day in itinerary_days:
                        day_date = day.get('date') if isinstance(day, dict) else None
                        try:
                            parsed_day = date.fromisoformat(day_date)
                            if parsed_day.isoformat() != day_date:
                                dates_valid = False
                                break
                        except (TypeError, ValueError):
                            dates_valid = False
                            break
                        itinerary_dates.append(day_date)
                    if len(set(itinerary_dates)) != len(itinerary_dates):
                        dates_valid = False
                    if any(date.fromisoformat(following) != date.fromisoformat(previous) + timedelta(days=1)
                           for previous, following in zip(itinerary_dates, itinerary_dates[1:])):
                        dates_valid = False
                plan_target_city = (itinerary_days[-1].get('city')
                                    if dates_valid and isinstance(itinerary_days[-1], dict) else None)
                task_context = None
                if (cost_context_valid is True and dates_valid and
                        isinstance(task_uid, str) and task_uid.strip() and
                        isinstance(plan_uid, str) and plan_uid.strip() and
                        task_uid == plan_uid and
                        isinstance(target_city, str) and target_city.strip() and
                        target_city == plan_target_city and
                        isinstance(cost_plan_input, dict) and
                        strict_snapshot_equal(cost_plan_input.get('days'), itinerary_days)):
                    task_context = {'task_uid': task_uid, 'plan_uid': plan_uid,
                                    'target_city': target_city,
                                    'itinerary_dates': itinerary_dates}
                cost_result = evaluate_cost_constraint(
                    total_cost_constraints[0], cost_aggregation.get('policy'),
                    cost_aggregation.get('components'), scope=cost_aggregation.get('scope'),
                    evidence_verifier=cost_evidence_verifier,
                    inventory_verifier=cost_inventory_verifier,
                    fact_verifier=constraint_fact_verifier,
                    task_context=task_context,
                    context_verifier=cost_context_verifier,
                    task_input=cost_task_input, plan_input=cost_plan_input,
                    lodging_manifest=cost_aggregation.get('lodging_manifest'),
                    lodging_claim_verifier=cost_lodging_claim_verifier,
                    lodging_inventory_verifier=cost_lodging_inventory_verifier,
                    intercity_manifest=cost_aggregation.get('intercity_manifest'),
                    intercity_policy_verifier=cost_intercity_policy_verifier,
                    intercity_inventory_verifier=cost_intercity_inventory_verifier,
                    intercity_segment_verifier=cost_intercity_segment_verifier,
                    intercity_timetable_verifier=cost_intercity_timetable_verifier,
                    intercity_fare_verifier=cost_intercity_fare_verifier)
            except Exception:
                reason = 'cost_constraint_bridge_failed'
        if cost_result is None:
            cost_result = {'state': 'unknown', 'reason': reason or 'cost_constraint_unresolved',
                           'truth_certified': False, 'real_trip_conclusion': False}
        cost_check = {'field': 'trip_cost_aggregation',
                      'state': cost_result.get('state', 'unknown'),
                      'reason': cost_result.get('reason', 'cost_constraint_unresolved'),
                      'natural_language_equivalence_verified': False}
        checks.append(cost_check)
        if cost_check['state'] == 'unknown':
            gaps.append({'gap_id': uid + ':trip_cost_aggregation:unknown',
                         'blocker_class': 'data', 'reason': cost_check['reason'],
                         'required': True, 'blocking': True, 'repairable': False})
        elif cost_check['state'] == 'fail':
            gaps.append({'gap_id': uid + ':trip_cost_aggregation:over_limit',
                         'blocker_class': 'solver', 'reason': cost_check['reason'],
                         'required': True, 'blocking': True, 'repairable': False})
    result = classify({'uid': uid, 'city': city, 'level': level, 'gaps': gaps,
                       'hard_checks': checks, 'planner': {'supported': False},
                       'plan_present': True, 'required_checks_complete': False})
    result.update({'label': 'engineering_smoke', 'truth_certified': False, 'soft_checks': soft_checks,
                   'evidence_audits': evidence_audits,
                   'execution_confirmed': False})
    if itinerary_report is not None:
        result['itinerary_checks'] = itinerary_report
    if overnight_report is not None:
        result['overnight_checks'] = overnight_report
    if meal_report is not None:
        result['meal_coverage_check'] = meal_report
    if lodging_report is not None:
        # The room-night total is not automatically folded into trip budget.
        result['lodging_check'] = lodging_report
    if intercity_report is not None:
        result['intercity_check'] = intercity_report
    if route_domain_report is not None:
        result['route_domain_check'] = route_domain_report
    if chain_report is not None:
        result['business_chain_check'] = chain_report
    if cost_result is not None:
        result['trip_cost_aggregation_check'] = cost_result
    if protected_snapshot is None or not strict_snapshot_equal(protected_inputs, protected_snapshot):
        rejected = classify({'uid':uid, 'level':level, 'city':city,
            'gaps':[{'gap_id':str(uid)+':plan:original_inputs_mutated',
                     'blocker_class':'pipeline','reason':'plan_original_inputs_mutated',
                     'required':True,'blocking':True,'repairable':False}],
            'hard_checks':[], 'planner':{'supported':False},
            'required_checks_complete':False, 'plan_present':True})
        rejected.update({'label':'engineering_smoke', 'truth_certified':False,
                         'soft_checks':[], 'evidence_audits':[], 'execution_confirmed':False})
        return rejected
    return result


def _bind_overnight_boundaries(days, boundaries):
    """Require full, ordered boundary coverage exactly matching plan endpoints."""
    from datetime import date, datetime, timedelta
    if not isinstance(boundaries, list):
        return {'complete': False, 'reason': 'overnight_boundaries_missing'}
    expected = []
    for index, (previous, following) in enumerate(zip(days, days[1:])):
        if not isinstance(previous, dict) or not isinstance(following, dict):
            return {'complete': False, 'reason': 'overnight_day_malformed', 'boundary_index': index}
        previous_date, next_date = previous.get('date'), following.get('date')
        try:
            parsed_previous = date.fromisoformat(previous_date)
            parsed_next = date.fromisoformat(next_date)
        except (TypeError, ValueError):
            return {'complete': False, 'reason': 'overnight_day_date_invalid', 'boundary_index': index}
        if (parsed_previous.isoformat() != previous_date or
                parsed_next != parsed_previous + timedelta(days=1)):
            return {'complete': False, 'reason': 'overnight_days_not_consecutive',
                    'boundary_index': index}
        prev_items, next_items = previous.get('timeline'), following.get('timeline')
        if not isinstance(prev_items, list) or not prev_items or not isinstance(next_items, list) or not next_items:
            return {'complete': False, 'reason': 'overnight_timeline_endpoint_missing',
                    'boundary_index': index}
        last = _timeline_boundary_endpoint(previous_date, prev_items[-1], 'last')
        first = _timeline_boundary_endpoint(next_date, next_items[0], 'first')
        if last is None or first is None:
            return {'complete': False, 'reason': 'overnight_timeline_endpoint_unrepresented',
                    'boundary_index': index}
        expected.append({'previous_day': previous_date, 'next_day': next_date,
                         'last_endpoint': last, 'first_endpoint': first})
    if len(boundaries) != len(expected):
        return {'complete': False, 'reason': 'overnight_boundary_coverage_mismatch',
                'expected_count': len(expected), 'actual_count': len(boundaries)}
    for index, (boundary, actual) in enumerate(zip(boundaries, expected)):
        if not isinstance(boundary, dict) or any(boundary.get(key) != actual[key]
                                                 for key in actual):
            return {'complete': False, 'reason': 'overnight_boundary_not_bound_to_itinerary',
                    'boundary_index': index, 'expected': actual}
    return {'complete': True, 'boundary_count': len(expected)}


def _timeline_boundary_endpoint(day_date, item, side):
    from datetime import datetime
    if not isinstance(item, dict):
        return None
    kind = item.get('type')
    if kind == 'travel':
        identity_key, entrance_key, time_key = (
            ('destination_id', 'destination_entrance_id', 'end') if side == 'last' else
            ('origin_id', 'origin_entrance_id', 'start'))
    elif kind in {'visit', 'attraction', 'breakfast', 'lunch', 'dinner', 'meal'}:
        identity_key, entrance_key = 'entity_id', 'entrance_id'
        time_key = 'end' if side == 'last' else 'start'
    else:
        return None
    identity, entrance, clock = item.get(identity_key), item.get(entrance_key), item.get(time_key)
    if any(not isinstance(value, str) or not value.strip()
           for value in (identity, entrance, clock)):
        return None
    try:
        moment = datetime.fromisoformat(day_date + 'T' + clock)
    except (TypeError, ValueError):
        return None
    if moment.utcoffset() is None:
        return None
    return {'entity_id': identity, 'entrance_id': entrance,
            'datetime': moment.isoformat()}


def _verify_meal_policy(task_context, required_slots, verifier):
    if not callable(verifier) or task_context is None:
        return False
    try:
        task_copy = copy.deepcopy(task_context)
        slots_copy = copy.deepcopy(required_slots)
        task_before, slots_before = copy.deepcopy(task_copy), copy.deepcopy(slots_copy)
        accepted = verifier(task_copy, slots_copy)
        return (accepted is True and strict_snapshot_equal(task_copy, task_before) and
                strict_snapshot_equal(slots_copy, slots_before))
    except Exception:
        return False


def _bind_meal_events(days, events):
    """Bind one explicit event to every meal timeline item by exact occurrence."""
    from datetime import date
    if not isinstance(days, list) or not days or not isinstance(events, list):
        return {'complete': False, 'reason': 'meal_itinerary_or_events_missing'}
    meal_types = {'breakfast', 'lunch', 'dinner', 'meal'}
    expected = {}
    seen_dates = set()
    for day_index, day in enumerate(days):
        if not isinstance(day, dict) or not isinstance(day.get('date'), str):
            return {'complete': False, 'reason': 'meal_itinerary_day_malformed'}
        try:
            valid_date = date.fromisoformat(day['date']).isoformat() == day['date']
        except ValueError:
            valid_date = False
        if not valid_date or day['date'] in seen_dates:
            return {'complete': False, 'reason': 'meal_itinerary_date_invalid_or_duplicate'}
        seen_dates.add(day['date'])
        timeline = day.get('timeline')
        if not isinstance(timeline, list):
            return {'complete': False, 'reason': 'meal_itinerary_timeline_missing'}
        for item_index, item in enumerate(timeline):
            if not isinstance(item, dict):
                return {'complete': False, 'reason': 'meal_timeline_item_malformed'}
            typ = item.get('type')
            if not isinstance(typ, str) or typ not in meal_types | {'visit', 'attraction', 'travel', 'wait'}:
                return {'complete': False, 'reason': 'meal_timeline_type_unsupported'}
            if typ not in meal_types:
                continue
            entity_id = item.get('entity_id')
            if not isinstance(entity_id, str) or not entity_id.strip():
                return {'complete': False, 'reason': 'meal_timeline_entity_id_missing'}
            slot = typ if typ != 'meal' else item.get('meal_slot')
            if not isinstance(slot, str) or not slot.strip():
                return {'complete': False, 'reason': 'generic_meal_slot_missing'}
            if typ != 'meal' and slot != typ:
                return {'complete': False, 'reason': 'meal_type_slot_mismatch'}
            expected[(day['date'], item_index)] = {
                'date': day['date'], 'item_index': item_index, 'type': typ,
                'entity_id': entity_id, 'slot': slot}
    if len(events) != len(expected):
        return {'complete': False, 'reason': 'meal_event_timeline_coverage_mismatch',
                'expected_count': len(expected), 'actual_count': len(events)}
    component_events, seen = [], set()
    required_event_keys = {'date', 'item_index', 'type', 'entity_id', 'event_id', 'slot'}
    for event in events:
        if not isinstance(event, dict) or set(event) != required_event_keys:
            return {'complete': False, 'reason': 'meal_event_binding_shape_invalid'}
        index = event.get('item_index')
        key = (event.get('date'), index)
        if type(index) is not int or key not in expected or key in seen:
            return {'complete': False, 'reason': 'meal_event_occurrence_missing_duplicate_or_extra'}
        actual = expected[key]
        if any(event.get(field) != actual[field]
               for field in ('date', 'item_index', 'type', 'entity_id', 'slot')):
            return {'complete': False, 'reason': 'meal_event_not_bound_to_timeline'}
        seen.add(key)
        component_events.append({'date': event['date'], 'slot': event['slot'],
                                 'entity_id': event['entity_id'],
                                 'event_id': event['event_id']})
    if len(seen) != len(expected):
        return {'complete': False, 'reason': 'meal_event_timeline_coverage_mismatch'}
    return {'complete': True, 'explicit_meal_item_count': len(expected),
            'component_events': component_events}


def _field_for_reason(reason):
    return {'opening_evidence_unqualified': 'opening_hours',
            'opening_schedule_unsupported': 'opening_hours',
            'route_evidence_ineligible': 'route',
            'required_cost_unknown': 'budget'}.get(reason)
