"""Explicit, evidence-gated lodging-night cost manifest.

This module only checks a supplied three-day stay manifest and its arithmetic.
It does not infer lodging, establish evidence truth, or certify a real trip.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .strict_lodging import check_lodging
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import identifier_is_known


_REQUIREMENT_KEYS = frozenset({
    "task_uid", "plan_uid", "target_city", "itinerary_dates", "check_in",
    "check_out", "hotel_id", "room_type", "rooms", "guests_per_room",
    "minimum_beds", "eligibility", "meal_plan", "taxes_included",
    "mandatory_fees_included", "required_nights",
})
_NIGHT_KEYS = frozenset({"night_date", "hotel_id", "entrance_id", "expense_id", "claim"})
_COMPONENT_KEYS = frozenset({
    "category", "amount", "currency", "party_size", "scope", "expense_ids",
    "lodging_night_bindings", "evidence", "conflict",
})


def _unknown(reason: str, *, night_checks=None):
    return {"state": "unknown", "reason": reason, "total_cny": None,
            "total_decimal": None, "night_checks": night_checks or [],
            "truth_certified": False, "real_trip_conclusion": False,
            "execution_confirmed": False}


def _expense_id(value):
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized if identifier_is_known(normalized) else None


def _canonical_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _same_snapshot_after(callback, args):
    if not callable(callback):
        return False
    try:
        supplied = copy.deepcopy(args)
        before = copy.deepcopy(supplied)
        accepted = callback(*supplied)
        return accepted is True and strict_snapshot_equal(supplied, before)
    except Exception:
        return False


def evaluate_lodging_cost_manifest(task, plan, requirement, nights,
                                   cost_component, *, claim_verifier,
                                   inventory_verifier, required_categories):
    """Validate all explicit room nights against a three-day task and plan.

    ``requirement`` explicitly declares the stay interval, room configuration,
    required night dates and context. ``plan['lodging_nights']`` must independently
    enumerate the same date/hotel/entrance/expense tuples, and each hotel/entrance
    must match the actual last and first dated timeline endpoints around that
    night. Missing or unsupported endpoints stay unknown; no transfer is inferred.
    Each night has a separately verified ``strict_lodging`` quote. The accommodation cost component must
    inventory exactly those expense IDs and its amount must equal the verified
    per-night CNY arithmetic. The inventory callback is a separate trust
    boundary for semantic coverage; callback inputs are isolated and mutation
    is rejected.

    The function returns unknown for absent, duplicate, conflicting, unverified,
    malformed, or scope-mismatched inputs. It never creates a lodging claim.
    """
    if not isinstance(task, Mapping) or not isinstance(plan, Mapping):
        return _unknown("lodging_task_or_plan_missing")
    if not isinstance(requirement, Mapping) or set(requirement) != _REQUIREMENT_KEYS:
        return _unknown("lodging_requirement_missing_or_malformed")
    if not isinstance(nights, list) or not isinstance(cost_component, Mapping):
        return _unknown("lodging_night_manifest_or_cost_component_missing")
    if set(cost_component) != _COMPONENT_KEYS:
        return _unknown("lodging_cost_component_malformed")
    if (not isinstance(required_categories, list) or
            any(not isinstance(category, str) or not category.strip()
                for category in required_categories) or
            sum(category in {"rooms", "accommodation"}
                for category in required_categories) != 1 or
            not isinstance(cost_component.get("category"), str) or
            cost_component.get("category") not in {"rooms", "accommodation"} or
            cost_component.get("category") not in required_categories):
        return _unknown("lodging_policy_category_mismatch")

    uid, plan_uid, city = task.get("uid"), plan.get("uid"), task.get("target_city")
    if (not identifier_is_known(uid) or not identifier_is_known(plan_uid) or uid != plan_uid
            or requirement.get("task_uid") != uid
            or requirement.get("plan_uid") != plan_uid
            or requirement.get("target_city") != city
            or not identifier_is_known(city)):
        return _unknown("lodging_task_plan_context_mismatch")
    if type(task.get("days")) is not int or task.get("days") != 3:
        return _unknown("lodging_requires_explicit_three_day_scope")
    dates = requirement.get("itinerary_dates")
    plan_days = plan.get("days")
    if (not isinstance(dates, list) or len(dates) != 3 or
            not isinstance(plan_days, list) or len(plan_days) != 3):
        return _unknown("lodging_itinerary_dates_missing_or_invalid")
    parsed = [_canonical_date(value) for value in dates]
    if (any(value is None for value in parsed) or
            any((parsed[i + 1] - parsed[i]).days != 1 for i in range(2)) or
            [day.get("date") if isinstance(day, Mapping) else None
             for day in plan_days] != dates or
            any(not isinstance(day, Mapping) or day.get("city") != city
                for day in plan_days) or
            task.get("start_date") != dates[0]):
        return _unknown("lodging_itinerary_context_mismatch")

    generation = task.get("generation")
    selected = generation.get("selected_entities_by_kind") if isinstance(generation, Mapping) else None
    accommodation = selected.get("accommodation") if isinstance(selected, Mapping) else None
    expected_hotel = accommodation.get("id") if isinstance(accommodation, Mapping) else None
    if not identifier_is_known(expected_hotel):
        return _unknown("lodging_task_hotel_identity_missing")
    if requirement.get("hotel_id") != expected_hotel:
        return _unknown("lodging_hotel_not_bound_to_task_candidate")

    check_in, check_out = dates[0], dates[-1]
    required_nights = [dates[0], dates[1]]
    if (requirement.get("check_in") != check_in or
            requirement.get("check_out") != check_out or
            requirement.get("required_nights") != required_nights):
        return _unknown("lodging_stay_interval_or_required_nights_mismatch")
    for key in ("room_type", "eligibility", "meal_plan"):
        if not isinstance(requirement.get(key), str) or not requirement[key].strip():
            return _unknown("lodging_room_configuration_incomplete")
    for key in ("rooms", "guests_per_room", "minimum_beds"):
        if type(requirement.get(key)) is not int or requirement[key] < 1:
            return _unknown("lodging_room_configuration_incomplete")
    people = task.get("people_number")
    if (type(people) is not int or people < 1 or
            requirement["rooms"] * requirement["guests_per_room"] < people):
        return _unknown("lodging_room_party_capacity_mismatch")
    if (requirement.get("taxes_included") is not True or
            requirement.get("mandatory_fees_included") is not True):
        return _unknown("lodging_mandatory_charges_not_included")

    scope = {"task_uid": uid, "plan_uid": plan_uid, "target_city": city,
             "itinerary_dates": list(dates)}
    plan_nights = plan.get("lodging_nights")
    if not isinstance(plan_nights, list) or len(plan_nights) != len(required_nights):
        return _unknown("lodging_plan_night_inventory_missing_or_incomplete")
    expected_pairs = [(day, expected_hotel) for day in required_nights]
    observed_pairs = []
    for item in plan_nights:
        if not isinstance(item, Mapping) or set(item) != {
                "night_date", "hotel_id", "entrance_id", "expense_id"}:
            return _unknown("lodging_plan_night_entry_malformed")
        observed_pairs.append((item.get("night_date"), item.get("hotel_id")))
    if observed_pairs != expected_pairs:
        return _unknown("lodging_plan_night_identity_or_coverage_mismatch")

    if len(nights) != len(required_nights):
        return _unknown("lodging_night_inventory_incomplete")
    normalized_ids = []
    for item in nights:
        if not isinstance(item, Mapping) or set(item) != _NIGHT_KEYS:
            return _unknown("lodging_night_entry_malformed")
        normalized = _expense_id(item.get("expense_id"))
        if normalized is None or normalized in normalized_ids:
            return _unknown("lodging_expense_id_missing_or_duplicate")
        normalized_ids.append(normalized)
    if ([item.get("night_date") for item in nights] != required_nights or
            [item.get("hotel_id") for item in nights] != [expected_hotel] * 2):
        return _unknown("lodging_nights_missing_duplicate_or_out_of_scope")
    for index, night in enumerate(nights):
        entrance_id = night.get("entrance_id")
        plan_entry = plan_nights[index]
        if (not identifier_is_known(entrance_id) or
                plan_entry.get("entrance_id") != entrance_id):
            return _unknown("lodging_plan_entrance_binding_mismatch")
        previous = _timeline_boundary_endpoint(plan_days[index], "last")
        following = _timeline_boundary_endpoint(plan_days[index + 1], "first")
        if previous is None or following is None:
            return _unknown("lodging_timeline_boundary_unrepresented")
        if (previous["entity_id"] != expected_hotel or
                following["entity_id"] != expected_hotel or
                previous["entrance_id"] != entrance_id or
                following["entrance_id"] != entrance_id):
            return _unknown("lodging_timeline_boundary_not_bound_to_hotel")
        if following["datetime"] <= previous["datetime"]:
            return _unknown("lodging_timeline_boundary_time_order_invalid")
    plan_ids = [_expense_id(item.get("expense_id")) for item in plan_nights]
    if None in plan_ids or plan_ids != normalized_ids:
        return _unknown("lodging_plan_expense_scope_mismatch")

    ids = cost_component.get("expense_ids")
    if (not isinstance(ids, list) or len(ids) != 2 or
            [_expense_id(value) for value in ids] != normalized_ids or
            cost_component.get("currency") != "CNY" or
            type(cost_component.get("party_size")) is not int or
            cost_component.get("party_size") != people or
            not strict_snapshot_equal(cost_component.get("scope"), scope) or
            cost_component.get("conflict") is not False or
            cost_component.get("evidence") in (None, {}, [], "")):
        return _unknown("lodging_cost_component_scope_or_conflict")
    expense_bindings = cost_component.get("lodging_night_bindings")
    expected_bindings = [{"expense_id": item["expense_id"],
                          "night_date": item["night_date"],
                          "hotel_id": item["hotel_id"],
                          "entrance_id": item["entrance_id"]} for item in nights]
    if not strict_snapshot_equal(expense_bindings, expected_bindings):
        return _unknown("lodging_cost_expense_bindings_mismatch")

    nightly_checks = []
    decimal_room_totals = []
    try:
        original_inputs = (task, plan, requirement, nights, cost_component, required_categories)
        original_snapshot = copy.deepcopy(original_inputs)
    except Exception:
        return _unknown("lodging_inputs_cannot_be_snapshotted")
    for index, (night, night_date) in enumerate(zip(nights, required_nights)):
        claim = night.get("claim")
        if not isinstance(claim, Mapping):
            return _unknown("lodging_night_claim_missing", night_checks=nightly_checks)
        next_date = (date.fromisoformat(night_date) + timedelta(days=1)).isoformat()
        night_requirement = {
            "entity_id": expected_hotel, "room_type": requirement["room_type"],
            "check_in": night_date, "check_out": next_date,
            "rooms": requirement["rooms"],
            "guests_per_room": requirement["guests_per_room"],
            "minimum_beds": requirement["minimum_beds"],
            "eligibility": requirement["eligibility"],
            "meal_plan": requirement["meal_plan"],
            "taxes_included": requirement["taxes_included"],
            "mandatory_fees_included": requirement["mandatory_fees_included"],
        }
        if not _same_snapshot_after(claim_verifier,
                (copy.deepcopy(night_requirement), copy.deepcopy(dict(claim)))):
            return _unknown("lodging_night_claim_unverified_or_mutated",
                            night_checks=nightly_checks)
        if not strict_snapshot_equal(original_inputs, original_snapshot):
            return _unknown("lodging_original_inputs_mutated", night_checks=nightly_checks)
        result = check_lodging(night_requirement, dict(claim),
                               claim_verifier=lambda *_: True)
        if result.get("state") != "pass":
            return _unknown("lodging_night_quote_invalid_or_conflicting",
                            night_checks=nightly_checks + [{"night_date": night_date,
                                "state": result.get("state"), "reason": result.get("reason")}])
        try:
            rate = Decimal(str(claim["rate"]))
            room_precision = (len(rate.as_tuple().digits) +
                              len(str(requirement["rooms"])) + 10)
            with localcontext() as context:
                context.prec = max(100, room_precision)
                decimal_room_totals.append(rate * Decimal(requirement["rooms"]))
        except (KeyError, TypeError, InvalidOperation, ValueError):
            return _unknown("lodging_night_price_invalid", night_checks=nightly_checks)
        nightly_checks.append({"night_date": night_date,
            "expense_id": night["expense_id"], "hotel_id": expected_hotel,
            "entrance_id": night["entrance_id"], "state": "pass",
            "total_decimal": str(decimal_room_totals[-1])})

    if not _same_snapshot_after(inventory_verifier,
            (copy.deepcopy(dict(task)), copy.deepcopy(dict(plan)),
             copy.deepcopy(dict(requirement)), copy.deepcopy(nights),
             copy.deepcopy(dict(cost_component)))):
        return _unknown("lodging_inventory_unverified_or_mutated",
                        night_checks=nightly_checks)
    if not strict_snapshot_equal(original_inputs, original_snapshot):
        return _unknown("lodging_original_inputs_mutated", night_checks=nightly_checks)
    try:
        with localcontext() as context:
            lowest_exponent = min(value.as_tuple().exponent
                                  for value in decimal_room_totals)
            highest_adjusted = max(value.adjusted() for value in decimal_room_totals)
            context.prec = max(100, highest_adjusted - lowest_exponent +
                               len(str(len(decimal_room_totals))) + 10)
            total_decimal = sum(decimal_room_totals, Decimal(0))
            amount = cost_component.get("amount")
            if not (type(amount) is int and amount >= 0 or
                    isinstance(amount, str) and len(amount) <= 256 and
                    re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', amount)):
                return _unknown("lodging_cost_amount_invalid", night_checks=nightly_checks)
            component_decimal = Decimal(amount)
        if not component_decimal.is_finite() or component_decimal != total_decimal:
            return _unknown("lodging_cost_amount_conflict", night_checks=nightly_checks)
        if total_decimal == total_decimal.to_integral_value():
            total_cny = int(total_decimal)
        else:
            # A binary float is not an exact monetary representation. Keep
            # the authoritative decimal string and omit this numeric shortcut.
            total_cny = None
    except (OverflowError, TypeError, ValueError, InvalidOperation):
        return _unknown("lodging_cost_total_invalid", night_checks=nightly_checks)

    return {"state": "pass", "reason": "explicit_lodging_nights_verified",
            "total_cny": total_cny, "total_decimal": str(total_decimal),
            "night_count": len(nightly_checks), "night_checks": nightly_checks,
            "currency": "CNY", "taxes_included": True,
            "mandatory_fees_included": True,
            "truth_certified": False, "real_trip_conclusion": False,
            "execution_confirmed": False}


def _timeline_boundary_endpoint(day, side):
    """Extract a mechanically represented endpoint; never infer a transfer."""
    if not isinstance(day, Mapping) or not isinstance(day.get("date"), str):
        return None
    day_date = _canonical_date(day.get("date"))
    timeline = day.get("timeline")
    if day_date is None or not isinstance(timeline, list) or not timeline:
        return None
    item = timeline[-1] if side == "last" else timeline[0]
    if not isinstance(item, Mapping):
        return None
    kind = item.get("type")
    if kind == "travel":
        identity_key, entrance_key, time_key = (
            ("destination_id", "destination_entrance_id", "end") if side == "last" else
            ("origin_id", "origin_entrance_id", "start"))
    elif isinstance(kind, str) and kind in {"visit", "attraction", "breakfast", "lunch", "dinner", "meal"}:
        identity_key, entrance_key = "entity_id", "entrance_id"
        time_key = "end" if side == "last" else "start"
    else:
        return None
    identity, entrance, clock = (item.get(identity_key), item.get(entrance_key),
                                 item.get(time_key))
    if (not identifier_is_known(identity) or not identifier_is_known(entrance) or
            not isinstance(clock, str) or not clock.strip()):
        return None
    try:
        moment = datetime.fromisoformat(day_date.isoformat() + "T" + clock)
    except (TypeError, ValueError):
        return None
    if moment.utcoffset() is None:
        return None
    return {"entity_id": identity, "entrance_id": entrance,
            "datetime": moment}
