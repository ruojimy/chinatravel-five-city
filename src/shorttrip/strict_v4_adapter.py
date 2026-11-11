"""Conservative v4 engineering diagnostic; never certifies real travel.

The caller supplies explicit requirements and approved source profiles. No
source registry entry is manufactured from the historical blanket registry.
"""
import copy
import hashlib
import json
from datetime import datetime
from .collection_workflow import classify
from .strict_v4_evidence import qualify_v4_field_claim
from .strict_hours import check_interval
from .strict_hours_parser import parse_explicit_intervals
from .strict_fields import total_required_cost
from .strict_route_solver import route_evidence_gate
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money
from .strict_scope import identifier_is_known


_SCHEDULE_SCOPE_KEYS = frozenset({"source_id", "evidence_id", "valid_from", "valid_until",
                                  "utc_offset", "weekdays", "activity_start", "activity_end",
                                  "schedule_sha256"})

# This mapping applies only to new strict diagnostics. Historical v4 claim
# labels remain untouched; line membership needs a dedicated policy and proof.
_METRO_NATIVE_POLICY = {"name": "identity", "position": "coordinates"}


def schedule_content_sha256(activity):
    """Hash the explicit schedule representation for schedule_scope binding.

    Returns ``None`` for ambiguous, missing, or non-JSON schedule input. For
    raw text, the digest binds the text, its declared weekday scope, parsed
    windows, and completeness flag. For structured windows, it binds those
    windows, weekdays, and completeness flag.
    """
    material = _schedule_material(activity)
    if material is None:
        return None
    try:
        encoded = json.dumps(material, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schedule_material(activity):
    if not isinstance(activity, dict):
        return None
    weekdays = activity.get("weekdays")
    if (not isinstance(weekdays, list) or not weekdays or
            any(type(day) is not int or day not in range(7) for day in weekdays) or
            len(set(weekdays)) != len(weekdays)):
        return None
    if type(activity.get("schedule_complete")) is not bool:
        return None
    raw_text = activity.get("raw_schedule_text")
    supplied_windows = activity.get("windows")
    if raw_text is not None:
        if not isinstance(raw_text, str) or supplied_windows is not None:
            return None
        parsed = parse_explicit_intervals(raw_text, weekdays=weekdays)
        if parsed.get("parse_status") != "parsed_explicit_intervals":
            return None
        windows = parsed["windows"]
        representation = "raw_text"
    else:
        if not isinstance(supplied_windows, list):
            return None
        windows = supplied_windows
        representation = "structured_windows"
        window_weekdays = []
        for window in windows:
            if (not isinstance(window, dict) or type(window.get("weekday")) is not int or
                    window["weekday"] not in range(7)):
                return None
            window_weekdays.append(window["weekday"])
        if windows and set(window_weekdays) != set(weekdays):
            return None
    return {"representation": representation,
            "raw_schedule_text": raw_text if representation == "raw_text" else None,
            "weekdays": list(weekdays), "windows": windows,
            "schedule_complete": activity["schedule_complete"]}


def _parse_aware_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _offset_text(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    seconds = value.utcoffset().total_seconds()
    if seconds % 60:
        return None
    minutes = int(abs(seconds) // 60)
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _valid_price_value(value):
    return exact_money(value) is not None


def _schedule_scope_valid(activity, windows):
    scope = activity.get("schedule_scope") if isinstance(activity, dict) else None
    if not isinstance(scope, dict) or set(scope) != _SCHEDULE_SCOPE_KEYS:
        return False
    if any(not isinstance(scope.get(key), str) or not scope[key].strip()
           for key in ("source_id", "evidence_id")):
        return False
    start, end = activity.get("start"), activity.get("end")
    if (not isinstance(start, datetime) or not isinstance(end, datetime) or
            start.tzinfo is None or end.tzinfo is None or
            start.utcoffset() is None or end.utcoffset() is None or end <= start):
        return False
    requested_offset = _offset_text(start)
    if (requested_offset is None or requested_offset != _offset_text(end) or
            scope.get("utc_offset") != requested_offset):
        return False
    if (scope.get("activity_start") != start.isoformat() or
            scope.get("activity_end") != end.isoformat()):
        return False
    weekdays = scope.get("weekdays")
    if (not isinstance(weekdays, list) or not weekdays or
            any(type(day) is not int or day not in range(7) for day in weekdays) or
            len(set(weekdays)) != len(weekdays) or
            set(weekdays) != set(activity.get("weekdays", []))):
        return False
    if isinstance(windows, list) and windows:
        try:
            if {window["weekday"] for window in windows} != set(weekdays):
                return False
        except (KeyError, TypeError):
            return False
    valid_from = _parse_aware_datetime(scope.get("valid_from"))
    valid_until = _parse_aware_datetime(scope.get("valid_until"))
    if (valid_from is None or valid_until is None or valid_until <= valid_from or
            valid_from > start or end > valid_until):
        return False
    if scope.get("schedule_sha256") != schedule_content_sha256(activity):
        return False
    return True


def _schedule_verifier_accepts(verifier, activity):
    if not callable(verifier):
        return False
    try:
        material = _schedule_material(activity)
        if material is None:
            return False
        if activity.get("windows") is None:
            windows = parse_explicit_intervals(activity["raw_schedule_text"],
                                                weekdays=activity["weekdays"])["windows"]
        else:
            windows = activity["windows"]
        if not _schedule_scope_valid(activity, windows):
            return False
        callback_activity = copy.deepcopy(activity)
        callback_scope = copy.deepcopy(activity["schedule_scope"])
        before_activity = copy.deepcopy(callback_activity)
        before_scope = copy.deepcopy(callback_scope)
        accepted = verifier(callback_activity, callback_scope)
        return (accepted is True and
                strict_snapshot_equal(callback_activity, before_activity) and
                strict_snapshot_equal(callback_scope, before_scope) and
                strict_snapshot_equal(activity, before_activity))
    except Exception:
        return False


def _invoke_isolated(callback, *values):
    """Call an untrusted callback on copies and detect changes to all inputs."""
    if not callable(callback):
        return None, "missing", None
    try:
        callback_values = copy.deepcopy(list(values))
        before = copy.deepcopy(callback_values)
        result = callback(*callback_values)
    except Exception as exc:
        return None, "exception", type(exc).__name__
    if not strict_snapshot_equal(callback_values, before):
        return None, "mutated", None
    try:
        return copy.deepcopy(result), None, None
    except Exception as exc:
        return None, "result_copy_failed", type(exc).__name__


def diagnose_record(record, requirements, *, registry, now, uid, level='easy',
                    evidence_verifier=None, evidence_auditor=None,
                    identity_verifier=None):
    """Diagnose isolated copies and discard results if caller inputs change."""
    if (not isinstance(record, dict) or any(not identifier_is_known(record.get(key))
                                            for key in ('id', 'city', 'kind', 'name'))):
        result = classify({'uid':uid, 'level':level, 'city':'unknown',
            'gaps':[{'gap_id':str(uid)+':identity_unresolved', 'field':'entity',
                     'blocker_class':'data', 'reason':'identity_unresolved',
                     'required':True, 'blocking':True, 'repairable':False,
                     'entity_identity_verified':False}],
            'hard_checks':[], 'planner':{'supported':False}, 'plan_present':False,
            'required_checks_complete':False})
        result.update({'label':'engineering_smoke', 'identity_independently_verified':False,
                       'truth_certified':False, 'execution_confirmed':False,
                       'evidence_audits':[]})
        return result
    original = (record, requirements, registry)
    before = copy.deepcopy(original)
    isolated = copy.deepcopy(before)
    result = _diagnose_record_impl(isolated[0], isolated[1], registry=isolated[2],
        now=now, uid=uid, level=level, evidence_verifier=evidence_verifier,
        evidence_auditor=evidence_auditor, identity_verifier=identity_verifier)
    if strict_snapshot_equal(original, before):
        return result
    source_record = before[0]
    entity_id = source_record.get('id') if isinstance(source_record, dict) else None
    report = {'uid': uid, 'level': level,
              'city': source_record.get('city') if isinstance(source_record, dict) else None,
              'gaps': [{'gap_id': str(uid) + ':record:original_inputs_mutated',
                        'entity_id': entity_id, 'field': 'entity',
                        'blocker_class': 'pipeline', 'reason': 'record_original_inputs_mutated',
                        'required': True, 'blocking': True, 'repairable': False,
                        'entity_identity_verified': False}],
              'hard_checks': [], 'planner': {'supported': False},
              'required_checks_complete': False, 'plan_present': False}
    result = classify(report)
    result.update({'label': 'engineering_smoke', 'entity_id': entity_id,
                   'identity_independently_verified': False,
                   'truth_certified': False, 'execution_confirmed': False})
    return result


def _diagnose_record_impl(record, requirements, *, registry, now, uid, level='easy',
                          evidence_verifier=None, evidence_auditor=None,
                          identity_verifier=None):
    gaps, checks, evidence_audits = [], [], []
    def gap(field, cls, reason, *, repairable=False, scope=None, detail=None):
        g = {'gap_id': uid + ':' + field + ':' + reason, 'entity_id': record['id'],
             'field': field, 'blocker_class': cls, 'reason': reason, 'required': True,
             'blocking': True, 'repairable': repairable, 'context': scope or {},
             'entity_identity_verified': identity_verified,
             'evidence_policy': 'strict-v4-engineering-v1'}
        if detail is not None: g['detail'] = detail
        gaps.append(g)
    identity_result, identity_status, identity_error = _invoke_isolated(
        identity_verifier, record)
    identity_verified = identity_status is None and identity_result is True
    identity_verification_error = identity_error
    if identity_status == 'mutated':
        identity_verification_error = 'mutated_input'
        gap('entity', 'pipeline', 'independent_identity_verifier_mutated_input',
            detail={'callback_input_discarded': True})
    elif identity_status == 'result_copy_failed':
        identity_verification_error = identity_error
        gap('entity', 'pipeline', 'independent_identity_verifier_result_unserializable',
            detail={'error_type': identity_error})
    payload = record['payload']
    data = payload.get('data') or {}
    if not identity_verified:
        detail = {'identity_verifier_required': True}
        if identity_verification_error:
            detail['verifier_error_type'] = identity_verification_error
        gap('entity', 'data', 'identity_unresolved', repairable=False, detail=detail)
    for req in requirements:
        field = req['native_field']
        scope = req.get('scope')
        policy_field = req.get('policy_field')
        matches = [c for c in record['claims'] if c['payload'].get('native_field') == field]
        if field == 'Duration' and record['kind'] in ('train','flight'):
            for item in matches:
                ctx = item['payload'].get('context') or {}
                nested = ctx.get('scope') if isinstance(ctx, dict) else None
                units = nested.get('Duration_unit') if isinstance(nested, dict) else None
                if units and units != 'hours':
                    gap(field, 'adapter', 'native_duration_unit_conflict', scope=scope,
                        detail={'native_contract':'hours','claim_unit':units})
        if not policy_field:
            gap(field, 'adapter', 'policy_field_mapping_missing')
            continue
        if record['kind'] == 'metro_station':
            expected = _METRO_NATIVE_POLICY.get(field)
            if expected is None:
                gap(field, 'adapter', 'metro_native_policy_unavailable', scope=scope,
                    detail={'mapping_version': 'metro-native-v1'})
                continue
            if policy_field != expected:
                gap(field, 'adapter', 'metro_native_policy_mismatch', scope=scope,
                    detail={'mapping_version': 'metro-native-v1',
                            'expected_policy': expected})
                continue
        if not isinstance(scope, dict) or not scope:
            gap(field, 'context', 'required_scope_missing')
            continue
        if field not in data or data[field] is None or data[field] == '':
            gap(field, 'data', 'missing_value', repairable=identity_verified, scope=scope,
                detail=None if identity_verified else {'blocked_by': 'identity_unresolved'})
            continue
        if not matches:
            gap(field, 'data', 'missing_evidence', repairable=identity_verified, scope=scope,
                detail=None if identity_verified else {'blocked_by': 'identity_unresolved'})
            continue
        # Continue structural and evidence diagnostics even when identity is
        # unresolved, so unit conflicts and audit failures are not hidden.
        # Identity remains a blocking gate and cannot be repaired by a claim.
        results = []
        for item in matches:
            claim, evidence = item['payload'], item['evidence']
            if evidence_auditor is not None:
                audit, audit_status, audit_error = _invoke_isolated(
                    evidence_auditor, record, req, claim, evidence)
                if audit_status is not None or not isinstance(audit, dict):
                    reason = ('independent_evidence_auditor_mutated_input'
                              if audit_status == 'mutated' else
                              'independent_evidence_audit_failed')
                    detail = {'error_type': audit_error} if audit_error else None
                    if audit_status == 'mutated':
                        detail = {'callback_input_discarded': True}
                    elif audit_status == 'result_copy_failed':
                        reason = 'independent_evidence_audit_failed'
                    elif audit_status is None:
                        detail = {'error_type': 'audit_result_not_object'}
                    gap(field, 'pipeline', reason, scope=scope, detail=detail)
                    # A diagnostic callback that attempted to change its
                    # inputs is not allowed to influence evidence evaluation.
                    if audit_status == 'mutated':
                        continue
                else:
                    evidence_audits.append({'claim_id': claim.get('claim_id'), 'field': field,
                                            'result': audit})
            if field == 'Duration' and record['kind'] in ('train','flight'):
                ctx = claim.get('context') or {}
                nested = ctx.get('scope') if isinstance(ctx, dict) else None
                units = nested.get('Duration_unit') if isinstance(nested, dict) else None
                if units and units != 'hours':
                    continue
            if claim.get('source_id') not in registry:
                gap(field, 'adapter', 'source_profile_review_pending', scope=scope)
                continue
            if field in ('price', 'Cost') and (
                    not _valid_price_value(claim.get('value')) or
                    not _valid_price_value(data[field])):
                results.append({'eligible': False, 'reasons': ['numeric_price_value_invalid']})
                continue
            if not strict_snapshot_equal(claim.get('value'), data[field]):
                results.append({'eligible': False, 'reasons': ['claim_value_mismatch']})
                continue
            result = qualify_v4_field_claim(
                claim, evidence, entity_id=record['id'], native_field=field,
                policy_field=policy_field, requested_scope=scope,
                source_profiles={claim['source_id']: registry[claim['source_id']]},
                now=now, evidence_verifier=evidence_verifier)
            results.append(result)
        if not results:
            continue
        if not any(x['eligible'] for x in results):
            gap(field, 'data', 'evidence_ineligible', repairable=False, scope=scope, detail=results)
            continue
        if identity_verified:
            checks.append({'field': field, 'state': 'pass'})
    report = {'uid': uid, 'level': level, 'city': record['city'], 'gaps': gaps,
              'hard_checks': checks, 'planner': {'supported': False},
              'required_checks_complete': False, 'plan_present': False}
    result = classify(report)
    result.update({'label': 'engineering_smoke', 'entity_id': record['id'],
                   'kind': record['kind'], 'name': record['name'],
                   'source_claim_count': len(record['claims']),
                   'evidence_audits': evidence_audits,
                   'identity_independently_verified': identity_verified,
                   'identity_resolution_workflow': None if identity_verified else {
                       'status': 'required', 'entity_id': record['id'],
                       'dispatch_to_static_sources': False,
                       'reason': 'independent_identity_verifier_required'},
                   'truth_certified': False, 'execution_confirmed': False})
    return result


def diagnose_candidate(*, uid, city, activity, route_requirement, route_evidence,
                       required_costs, budget, now, schedule_verifier=None,
                       route_verifier=None, cost_verifier=None):
    """Classify a single proposed candidate without asserting exhaustive search.

    Only independently qualified structured schedules may reach the hours
    checker. Missing fares remain unknown; a failed candidate is not unsat.
    """
    protected = (activity, route_requirement, route_evidence, required_costs, budget)
    try:
        protected_before = copy.deepcopy(protected)
    except Exception:
        protected_before = None
    gaps, checks = [], []
    def block(cls, reason, lifecycle='static'):
        gaps.append({'gap_id':uid+':'+reason, 'required':True, 'blocking':True,
                     'blocker_class':cls, 'reason':reason, 'repairable':False,
                     'lifecycle':lifecycle})
    if not _schedule_verifier_accepts(schedule_verifier, activity):
        block('data', 'opening_evidence_unqualified')
        checks.append({'field':'opening_hours','state':'unknown'})
    else:
        windows = activity.get('windows')
        if windows is None and activity.get('raw_schedule_text') is not None:
            parsed = parse_explicit_intervals(activity['raw_schedule_text'], weekdays=activity.get('weekdays'))
            windows = parsed['windows']
        status = check_interval(windows, activity['start'], activity['end'],
                                schedule_complete=activity.get('schedule_complete') is True)
        checks.append({'field':'opening_hours','state':{'open':'pass','closed':'fail','unknown':'unknown'}[status]})
        if status == 'unknown': block('adapter', 'opening_schedule_unsupported')
    route = route_evidence_gate(route_requirement, route_evidence, now=now, evidence_verifier=route_verifier)
    if not route['usable']:
        block('data', 'route_evidence_ineligible', lifecycle='runtime')
        checks.append({'field':'route','state':'unknown','reasons':route['reasons']})
    else:
        checks.append({'field':'route','state':'pass'})
    total = exact_money(total_required_cost(required_costs))
    exact_budget = exact_money(budget)
    cost_result, cost_status, cost_error = _invoke_isolated(cost_verifier, required_costs)
    cost_verified = cost_status is None and cost_result is True
    if cost_status == 'mutated':
        block('pipeline', 'independent_cost_verifier_mutated_input')
    if cost_status == 'result_copy_failed':
        block('pipeline', 'independent_cost_verifier_result_unreadable')
    if total is None or exact_budget is None or not cost_verified:
        block('data', 'required_cost_unknown')
        checks.append({'field':'budget','state':'unknown'})
    else:
        checks.append({'field':'budget','state':'pass' if total <= exact_budget else 'fail'})
    if protected_before is None or not strict_snapshot_equal(protected, protected_before):
        return classify({'uid':uid,'level':'easy','city':city,'gaps':[{
            'gap_id':str(uid)+':candidate:original_inputs_mutated',
            'blocker_class':'pipeline','reason':'candidate_original_inputs_mutated',
            'required':True,'blocking':True,'repairable':False}], 'hard_checks':[],
            'planner':{'supported':False},'plan_present':True,
            'required_checks_complete':False})
    return classify({'uid':uid,'level':'easy','city':city,'gaps':gaps,'hard_checks':checks,
                     'planner':{'supported':False},'plan_present':True,
                     'required_checks_complete':False})
