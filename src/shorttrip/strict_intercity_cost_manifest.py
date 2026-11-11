"""Explicit intercity timetable and fare manifest checks.

This standalone module does not integrate a fare into trip-budget totals and
does not infer a route or return policy. Passing checks are scoped engineering
results, never evidence that travel is available or booked.
"""
from __future__ import annotations

import copy
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .strict_intercity import check_intercity
from .strict_scope import scope_is_complete, scope_identifiers_are_known, identifier_is_known
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money


_POLICY_KEYS = frozenset({"origin_city", "destination_city", "currency", "return_policy",
                          "required_segments"})
_POLICY_SEGMENT_KEYS = frozenset({
    "segment_id", "direction", "origin_city", "destination_city",
    "origin_station", "destination_station",
    "travel_date", "departure_time", "clock_zone", "seat_class",
    "passenger_count", "date_scope_exception",
})
_PLAN_SEGMENT_KEYS = frozenset({
    "segment_id", "direction", "origin_city", "destination_city",
    "origin_station", "destination_station", "travel_date", "departure_time",
    "clock_zone", "seat_class", "passenger_count", "arrival_time",
    "arrival_day_offset", "Duration", "Duration_unit", "expense_id",
})
_MANIFEST_KEYS = frozenset({"fares"})
_FARE_ENTRY_KEYS = frozenset({"segment_id", "expense_id", "timetable_claim", "fare_claim"})
_TIMETABLE_KEYS = frozenset({
    "origin_city", "destination_city", "origin_station", "destination_station",
    "travel_date", "departure_time", "clock_zone", "arrival_time",
    "arrival_day_offset", "Duration", "Duration_unit",
})
_FARE_CLAIM_KEYS = frozenset({
    "segment_id", "direction", "origin_city", "destination_city",
    "origin_station", "destination_station", "travel_date", "departure_time",
    "clock_zone", "seat_class",
    "passenger_count", "currency", "unit", "unit_price", "taxes_included",
    "mandatory_fees_included", "conflict", "evidence",
})
_EVIDENCE_KEYS = frozenset({"source_ref", "retrieved_at", "licence"})


def _unknown(reason, *, segments=None):
    return {"state": "unknown", "reason": reason, "segments": segments or [],
            "total_decimal": None, "currency": None, "truth_certified": False,
            "real_trip_conclusion": False, "execution_confirmed": False}


def _expense_id(value):
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized if identifier_is_known(normalized) else None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _verified_unchanged(verifier, args):
    if not callable(verifier):
        return False
    try:
        copied = copy.deepcopy(args)
        before = copy.deepcopy(copied)
        accepted = verifier(*copied)
        return accepted is True and strict_snapshot_equal(copied, before)
    except Exception:
        return False


def _price_decimal(value):
    return exact_money(value)


def evaluate_intercity_cost_manifest(task, plan, manifest, *,
                                     policy_verifier, inventory_verifier,
                                     segment_verifier, timetable_verifier,
                                     fare_verifier):
    """Validate explicit outbound/return policy, plan segments, and per-person fares.

    The only accepted task policy is ``task['intercity_policy']`` with an
    explicit origin, destination, and ``return_policy``. Each declared segment
    must match one plan segment and one fare entry. The complete inventory,
    task-policy authenticity, plan-segment identity, timetable claim, and fare
    claim each cross separate callback trust boundaries. ``check_intercity``
    supplies the existing same-zone time/duration/unit check.

    Prices use canonical decimal strings or nonnegative integers and the exact
    unit ``CNY/person/segment``. This module returns arithmetic for its explicit
    fare domain only; unsupported/absent route policies remain unknown.
    """
    if not isinstance(task, Mapping) or not isinstance(plan, Mapping):
        return _unknown("intercity_task_or_plan_missing")
    try:
        original_inputs = (task, plan, manifest)
        original_snapshot = copy.deepcopy(original_inputs)
    except Exception:
        return _unknown("intercity_inputs_cannot_be_snapshotted")

    def originals_unchanged():
        return strict_snapshot_equal(original_inputs, original_snapshot)
    uid, plan_uid = task.get("uid"), plan.get("uid")
    if (not identifier_is_known(uid) or uid != plan_uid or
            not scope_is_complete({"task_uid": uid, "plan_uid": plan_uid})):
        return _unknown("intercity_task_plan_uid_mismatch")
    policy = task.get("intercity_policy")
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_KEYS:
        return _unknown("intercity_task_policy_missing_or_malformed")
    origin, destination = policy.get("origin_city"), policy.get("destination_city")
    if (not identifier_is_known(origin) or not identifier_is_known(destination) or
            not scope_is_complete({"origin_city": origin, "destination_city": destination})):
        return _unknown("intercity_task_origin_or_destination_missing")
    if origin == destination:
        return _unknown("intercity_task_direction_invalid")
    currency = policy.get("currency")
    if not isinstance(currency, str) or not scope_is_complete({"currency": currency}):
        return _unknown("intercity_task_currency_missing")
    if (not isinstance(task.get("target_city"), str) or
            not scope_is_complete({"target_city": task.get("target_city")}) or
            destination != task.get("target_city")):
        return _unknown("intercity_task_destination_not_bound_to_target")
    task_start = _date(task.get("start_date"))
    task_days = task.get("days")
    people_number = task.get("people_number")
    plan_days = plan.get("days")
    if (task_start is None or type(task_days) is not int or task_days < 1 or
            type(people_number) is not int or people_number < 1 or
            not isinstance(plan_days, list) or not plan_days or
            len(plan_days) != task_days or
            task_days != len(plan_days) or
            any(not isinstance(day, Mapping) or day.get("city") != destination
                for day in plan_days)):
        return _unknown("intercity_plan_city_scope_mismatch")
    itinerary_dates = [day.get("date") for day in plan_days]
    parsed_plan_dates = [_date(value) for value in itinerary_dates]
    if any(value is None for value in parsed_plan_dates):
        return _unknown("intercity_plan_date_scope_invalid")
    try:
        dates_are_consecutive = not any(
            parsed_plan_dates[index + 1] != parsed_plan_dates[index] + timedelta(days=1)
            for index in range(len(parsed_plan_dates) - 1))
    except OverflowError:
        return _unknown("intercity_plan_date_scope_invalid")
    if parsed_plan_dates[0] != task_start or not dates_are_consecutive:
        return _unknown("intercity_plan_date_scope_invalid")
    try:
        expected_plan_dates = [(task_start + timedelta(days=index)).isoformat()
                               for index in range(task_days)]
    except OverflowError:
        return _unknown("intercity_plan_date_scope_invalid")
    if itinerary_dates != expected_plan_dates:
        return _unknown("intercity_plan_dates_do_not_match_task")
    return_policy = policy.get("return_policy")
    if not isinstance(return_policy, str) or return_policy not in {"required", "not_required"}:
        return _unknown("intercity_return_policy_missing_or_invalid")
    required = policy.get("required_segments")
    if not isinstance(required, list) or not required:
        return _unknown("intercity_required_segment_inventory_missing")
    if any(not isinstance(item, Mapping) for item in required):
        return _unknown("intercity_policy_segment_malformed")
    directions = [item.get("direction") for item in required]
    if any(not isinstance(value, str) for value in directions):
        return _unknown("intercity_policy_direction_invalid")
    if not _verified_unchanged(policy_verifier, (copy.deepcopy(dict(task)),
                                                  copy.deepcopy(dict(policy)))):
        return _unknown("intercity_task_policy_unverified_or_mutated")
    if not originals_unchanged():
        return _unknown("intercity_original_inputs_mutated")

    if return_policy == "required":
        if len(required) != 2 or set(directions) != {"outbound", "return"}:
            return _unknown("intercity_required_return_segment_missing_or_ambiguous")
    elif len(required) != 1 or required[0].get("direction") != "outbound":
        return _unknown("intercity_unexpected_segment_without_return_policy")

    normalized_policy = []
    for item in required:
        if not isinstance(item, Mapping) or set(item) != _POLICY_SEGMENT_KEYS:
            return _unknown("intercity_policy_segment_malformed")
        direction = item.get("direction")
        if direction == "outbound":
            expected_origin, expected_destination = origin, destination
        elif direction == "return" and return_policy == "required":
            expected_origin, expected_destination = destination, origin
        else:
            return _unknown("intercity_policy_direction_invalid")
        if (item.get("origin_city") != expected_origin or
                item.get("destination_city") != expected_destination):
            return _unknown("intercity_policy_segment_city_mismatch")
        policy_scope = {key: item.get(key) for key in (
            "segment_id", "origin_city", "destination_city", "origin_station",
            "destination_station", "travel_date", "departure_time", "clock_zone",
            "seat_class")}
        if (any(not isinstance(item.get(key), str) for key in (
                    "segment_id", "origin_city", "destination_city", "origin_station",
                    "destination_station", "travel_date", "departure_time", "clock_zone",
                    "seat_class")) or
                not scope_is_complete(policy_scope) or not scope_identifiers_are_known(policy_scope)
                or type(item.get("passenger_count")) is not int or item["passenger_count"] < 1
                or item.get("passenger_count") != people_number):
            return _unknown("intercity_policy_segment_scope_incomplete")
        # Top-level task policy declares cities; each segment's direction
        # mechanically determines which explicit endpoint pair applies.
        travel_day = _date(item.get("travel_date"))
        if travel_day is None:
            return _unknown("intercity_policy_segment_date_invalid")
        exception = item.get("date_scope_exception")
        if travel_day.isoformat() not in itinerary_dates:
            # Out-of-itinerary services need an explicitly designed exception
            # contract; this implementation remains conservative and unknown.
            if exception is None:
                return _unknown("intercity_segment_date_outside_plan_without_exception")
            return _unknown("intercity_date_scope_exception_not_supported")
        if exception is not None:
            return _unknown("intercity_unnecessary_date_scope_exception")
        normalized_policy.append((item, expected_origin, expected_destination))

    if len({item.get("segment_id") for item, _, _ in normalized_policy}) != len(required):
        return _unknown("intercity_policy_segment_id_missing_or_duplicate")

    plan_segments = plan.get("intercity_segments")
    if not isinstance(plan_segments, list) or len(plan_segments) != len(required):
        return _unknown("intercity_plan_segment_inventory_missing_or_incomplete")
    if not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST_KEYS:
        return _unknown("intercity_fare_manifest_missing_or_malformed")
    fares = manifest.get("fares")
    if not isinstance(fares, list) or len(fares) != len(required):
        return _unknown("intercity_fare_inventory_missing_or_incomplete")

    policy_by_id = {item["segment_id"]: (item, leg_origin, leg_destination)
                    for item, leg_origin, leg_destination in normalized_policy}
    plan_by_id = {}
    for segment in plan_segments:
        if not isinstance(segment, Mapping) or set(segment) != _PLAN_SEGMENT_KEYS:
            return _unknown("intercity_plan_segment_malformed")
        segment_id = segment.get("segment_id")
        if (not identifier_is_known(segment_id) or
                segment_id in plan_by_id):
            return _unknown("intercity_plan_segment_id_missing_or_duplicate")
        plan_by_id[segment_id] = segment
    fare_by_id = {}
    seen_expense_ids = set()
    for entry in fares:
        if not isinstance(entry, Mapping) or set(entry) != _FARE_ENTRY_KEYS:
            return _unknown("intercity_fare_entry_malformed")
        segment_id = entry.get("segment_id")
        expense_id = _expense_id(entry.get("expense_id"))
        if (not identifier_is_known(segment_id) or segment_id not in policy_by_id
                or segment_id in fare_by_id or expense_id is None
                or not scope_is_complete({"expense_id": entry.get("expense_id")})
                or expense_id in seen_expense_ids):
            return _unknown("intercity_fare_segment_or_expense_id_duplicate_or_invalid")
        seen_expense_ids.add(expense_id)
        fare_by_id[segment_id] = entry
    if set(plan_by_id) != set(policy_by_id) or set(fare_by_id) != set(policy_by_id):
        return _unknown("intercity_manifest_segment_coverage_mismatch")

    segment_results = []
    totals = []
    segment_moments = {}
    for policy_leg, leg_origin, leg_destination in normalized_policy:
        segment_id = policy_leg["segment_id"]
        plan_segment = plan_by_id[segment_id]
        fare_entry = fare_by_id[segment_id]
        expected = {"segment_id": segment_id, "direction": policy_leg["direction"],
            "origin_city": leg_origin, "destination_city": leg_destination,
            "origin_station": policy_leg["origin_station"],
            "destination_station": policy_leg["destination_station"],
            "travel_date": policy_leg["travel_date"],
            "departure_time": policy_leg["departure_time"],
            "clock_zone": policy_leg["clock_zone"], "seat_class": policy_leg["seat_class"],
            "passenger_count": policy_leg["passenger_count"]}
        if any(plan_segment.get(key) != value for key, value in expected.items()):
            return _unknown("intercity_plan_segment_not_bound_to_task_policy",
                            segments=segment_results)
        expense_id = fare_entry["expense_id"]
        if (not scope_is_complete({"expense_id": plan_segment.get("expense_id")}) or
                plan_segment.get("expense_id") != expense_id):
            return _unknown("intercity_expense_id_not_bound_to_plan_segment",
                            segments=segment_results)
        if not _verified_unchanged(segment_verifier,
                (copy.deepcopy(dict(task)), copy.deepcopy(dict(plan)),
                 copy.deepcopy(dict(policy_leg)), copy.deepcopy(dict(plan_segment)))):
            return _unknown("intercity_plan_segment_unverified_or_mutated",
                            segments=segment_results)
        if not originals_unchanged():
            return _unknown("intercity_original_inputs_mutated", segments=segment_results)

        requirement = {key: expected[key] for key in (
            "origin_city", "destination_city", "origin_station", "destination_station",
            "travel_date", "departure_time", "clock_zone")}
        timetable_claim = fare_entry.get("timetable_claim")
        if not isinstance(timetable_claim, Mapping) or set(timetable_claim) != _TIMETABLE_KEYS:
            return _unknown("intercity_timetable_claim_missing_or_malformed",
                            segments=segment_results)
        if any(plan_segment.get(key) != timetable_claim.get(key) for key in _TIMETABLE_KEYS):
            return _unknown("intercity_timetable_claim_not_bound_to_plan",
                            segments=segment_results)
        try:
            timetable = check_intercity(requirement, dict(timetable_claim),
                                        claim_verifier=timetable_verifier)
        except Exception:
            return _unknown("intercity_timetable_check_failed", segments=segment_results)
        if not originals_unchanged():
            return _unknown("intercity_original_inputs_mutated", segments=segment_results)
        if timetable.get("state") != "pass":
            return _unknown("intercity_timetable_unverified:" + str(timetable.get("reason")),
                            segments=segment_results)
        try:
            arrival_day = (_date(policy_leg["travel_date"]) +
                           timedelta(days=timetable_claim["arrival_day_offset"]))
        except OverflowError:
            return _unknown("intercity_timetable_moment_invalid", segments=segment_results)
        first_day, last_day = parsed_plan_dates[0], parsed_plan_dates[-1]
        if arrival_day < first_day or arrival_day > last_day:
            if policy_leg.get("date_scope_exception") is None:
                return _unknown("intercity_arrival_date_outside_plan_without_exception",
                                segments=segment_results)
            return _unknown("intercity_date_scope_exception_not_supported",
                            segments=segment_results)

        fare_claim = fare_entry.get("fare_claim")
        if not isinstance(fare_claim, Mapping) or set(fare_claim) != _FARE_CLAIM_KEYS:
            return _unknown("intercity_fare_claim_missing_or_malformed",
                            segments=segment_results)
        evidence = fare_claim.get("evidence")
        if (not isinstance(evidence, Mapping) or set(evidence) != _EVIDENCE_KEYS or
                not scope_is_complete(evidence)):
            return _unknown("intercity_fare_source_missing_or_malformed",
                            segments=segment_results)
        for key, value in expected.items():
            if fare_claim.get(key) != value:
                return _unknown("intercity_fare_scope_mismatch", segments=segment_results)
        if (fare_claim.get("currency") != currency or
                fare_claim.get("unit") != currency + "/person/segment" or
                fare_claim.get("taxes_included") is not True or
                fare_claim.get("mandatory_fees_included") is not True or
                fare_claim.get("conflict") is not False):
            return _unknown("intercity_fare_price_unit_or_charge_scope_invalid",
                            segments=segment_results)
        price = _price_decimal(fare_claim.get("unit_price"))
        if price is None:
            return _unknown("intercity_fare_price_invalid_or_imprecise",
                            segments=segment_results)
        if not _verified_unchanged(fare_verifier,
                (copy.deepcopy(dict(task)), copy.deepcopy(dict(plan)),
                 copy.deepcopy(dict(policy_leg)), copy.deepcopy(dict(plan_segment)),
                 copy.deepcopy(dict(fare_claim)))):
            return _unknown("intercity_fare_unverified_or_mutated",
                            segments=segment_results)
        if not originals_unchanged():
            return _unknown("intercity_original_inputs_mutated", segments=segment_results)
        try:
            precision = len(price.as_tuple().digits) + len(str(policy_leg["passenger_count"])) + 10
            with localcontext() as context:
                context.prec = max(100, precision)
                segment_total = price * Decimal(policy_leg["passenger_count"])
        except (OverflowError, ValueError, InvalidOperation):
            return _unknown("intercity_fare_total_invalid", segments=segment_results)
        totals.append(segment_total)
        try:
            zone = timetable_claim["clock_zone"]
            departure_moment = datetime.fromisoformat(
                timetable_claim["travel_date"] + "T" +
                timetable_claim["departure_time"] + zone)
            arrival_date = (_date(timetable_claim["travel_date"]) +
                            timedelta(days=timetable_claim["arrival_day_offset"]))
            arrival_moment = datetime.fromisoformat(
                arrival_date.isoformat() + "T" + timetable_claim["arrival_time"] + zone)
        except (OverflowError, TypeError, ValueError):
            return _unknown("intercity_timetable_moment_invalid", segments=segment_results)
        segment_moments[policy_leg["direction"]] = (departure_moment, arrival_moment)
        segment_results.append({"segment_id": segment_id,
            "direction": policy_leg["direction"], "expense_id": expense_id,
            "origin_city": leg_origin, "destination_city": leg_destination,
            "origin_station": policy_leg["origin_station"],
            "destination_station": policy_leg["destination_station"],
            "travel_date": policy_leg["travel_date"],
            "departure_time": policy_leg["departure_time"],
            "clock_zone": policy_leg["clock_zone"],
            "arrival_time": timetable_claim["arrival_time"],
            "arrival_day_offset": timetable_claim["arrival_day_offset"],
            "passenger_count": policy_leg["passenger_count"],
            "seat_class": policy_leg["seat_class"],
            "state": "pass", "total_decimal": str(segment_total),
            "duration_minutes": timetable["duration_minutes"]})

    if return_policy == "required":
        outbound_moments = segment_moments.get("outbound")
        return_moments = segment_moments.get("return")
        if (outbound_moments is None or return_moments is None or
                return_moments[0] <= outbound_moments[1]):
            return _unknown("intercity_return_time_not_after_outbound_arrival",
                            segments=segment_results)

    if not _verified_unchanged(inventory_verifier,
            (copy.deepcopy(dict(task)), copy.deepcopy(dict(plan)),
             copy.deepcopy(dict(policy)), copy.deepcopy(dict(manifest)))):
        return _unknown("intercity_inventory_unverified_or_mutated", segments=segment_results)
    if not originals_unchanged():
        return _unknown("intercity_original_inputs_mutated", segments=segment_results)
    try:
        with localcontext() as context:
            low_exp = min(value.as_tuple().exponent for value in totals)
            high_adj = max(value.adjusted() for value in totals)
            context.prec = max(100, high_adj - low_exp + len(str(len(totals))) + 10)
            total = sum(totals, Decimal(0))
    except (InvalidOperation, ValueError):
        return _unknown("intercity_fare_total_invalid", segments=segment_results)
    return {"state": "pass", "reason": "explicit_intercity_fare_manifest_verified",
            "segments": segment_results, "total_decimal": str(total),
            "currency": currency, "return_policy": return_policy,
            "truth_certified": False, "real_trip_conclusion": False,
            "execution_confirmed": False}
