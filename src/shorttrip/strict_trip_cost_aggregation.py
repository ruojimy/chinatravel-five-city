"""Strict evidence-scoped trip cost aggregation.

This module checks declared cost coverage and arithmetic only. A qualified
result is not a quote, booking, feasibility claim, or real-trip conclusion.
"""
from __future__ import annotations

import copy
import math
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from collections.abc import Mapping

from .strict_scope import identifier_is_known, scope_is_complete, scope_identifiers_are_known
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money


def _finite_nonnegative(value):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and value >= 0)
    except (OverflowError, TypeError, ValueError):
        return False


def _normalise_expense_id(value):
    if not isinstance(value, str):
        return None
    normalised = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalised if identifier_is_known(normalised) else None


_OCCURRENCE_COST_CATEGORIES = {"tickets", "meals", "transport", "local_transport"}
_LODGING_COST_CATEGORIES = {"rooms", "accommodation"}
_INTERCITY_COST_CATEGORIES = {"intercity"}


def _scope_identities_are_known(value):
    return scope_identifiers_are_known(value)


def _timeline_time_matches(value, day_date, expected_time, clock_zone, *, day_offset=0):
    """Bind an assembled ISO timeline time to a local time and explicit zone."""
    if not all(isinstance(item, str) and item for item in
               (value, day_date, expected_time, clock_zone)):
        return False
    try:
        expected_date = (date.fromisoformat(day_date) + timedelta(days=day_offset)).isoformat()
        actual = datetime.fromisoformat(expected_date + "T" + value)
        expected = datetime.fromisoformat(expected_date + "T" + expected_time + clock_zone)
    except (OverflowError, TypeError, ValueError):
        return False
    return (actual.utcoffset() is not None and expected.utcoffset() is not None and
            actual.date() == expected.date() and actual.timetz().replace(tzinfo=None) ==
            expected.timetz().replace(tzinfo=None) and
            actual.utcoffset() == expected.utcoffset())


def validate_expense_occurrence_bindings(components, plan, scope=None, *,
                                         lodging_category=None,
                                         lodging_expense_ids=None,
                                         intercity_expense_ids=None,
                                         intercity_segments=None):
    """Bind every expense ID one-to-one to an actual dated plan occurrence.

    This is a structural check only. It does not infer that an event implies a
    charge, or that a category is covered by that event; trusted context and
    inventory verifiers must establish those semantics independently.
    ``tickets``, ``meals``, ``transport``, and ``local_transport`` use ordinary
    occurrence bindings. A lodging category bypasses that representation only
    when its raw night manifest was independently revalidated and its expense
    IDs match ``lodging_expense_ids`` exactly. Intercity-range and unknown
    categories remain unsupported. Every intercity helper segment must also
    bind to one dated, fully scoped travel item in the plan timeline.
    """
    def unknown(reason):
        return {"valid": False, "reason": reason}

    if not isinstance(plan, Mapping) or not isinstance(plan.get("days"), list) or not plan["days"]:
        return unknown("cost_plan_missing")
    if not identifier_is_known(plan.get("uid")):
        return unknown("cost_plan_uid_missing_or_unknown")
    if isinstance(scope, Mapping):
        if (not scope_is_complete(dict(scope)) or
                not _scope_identities_are_known(scope)):
            return unknown("cost_scope_incomplete_or_unknown")
        if ("plan_uid" in scope and plan.get("uid") != scope.get("plan_uid")):
            return unknown("cost_plan_uid_mismatch")
    expected_dates = []
    occurrences = {}
    timeline_intercity = []
    for day_index, day in enumerate(plan["days"]):
        if not isinstance(day, Mapping):
            return unknown("cost_plan_day_malformed")
        if not identifier_is_known(day.get("city")):
            return unknown("cost_plan_city_missing_or_unknown")
        day_date = day.get("date")
        if not isinstance(day_date, str):
            return unknown("cost_plan_date_missing")
        try:
            if __import__("datetime").date.fromisoformat(day_date).isoformat() != day_date:
                return unknown("cost_plan_date_invalid")
        except ValueError:
            return unknown("cost_plan_date_invalid")
        expected_dates.append(day_date)
        timeline = day.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            return unknown("cost_plan_timeline_empty_or_missing")
        for item_index, item in enumerate(timeline):
            if not isinstance(item, Mapping):
                return unknown("cost_plan_timeline_item_malformed")
            if intercity_segments is not None and "segment_id" in item:
                segment_id = item.get("segment_id")
                if not identifier_is_known(segment_id):
                    return unknown("intercity_timeline_segment_id_invalid")
                timeline_intercity.append((day_index, item_index, item, day_date))
            typ = item.get("type")
            entity_id = item.get("entity_id")
            if not identifier_is_known(typ) or not identifier_is_known(entity_id):
                return unknown("cost_plan_occurrence_identity_missing")
            occurrences[(day_index, item_index)] = {
                "date": day_date, "type": typ, "entity_id": entity_id}

    if isinstance(scope, Mapping):
        scoped_dates = scope.get("itinerary_dates", scope.get("travel_dates"))
        if scoped_dates is not None and scoped_dates != expected_dates:
            return unknown("cost_plan_dates_mismatch")
        if (scope.get("target_city") is not None and
                plan["days"][-1].get("city") != scope.get("target_city")):
            return unknown("cost_plan_target_city_mismatch")

    if intercity_segments is not None:
        if not isinstance(intercity_segments, list) or not intercity_segments:
            return unknown("intercity_timeline_segment_inventory_missing")
        expected_by_id = {}
        required_timeline_fields = {
            "segment_id", "date", "direction", "origin_city", "destination_city",
            "origin_station", "destination_station", "departure_time", "clock_zone",
            "arrival_time", "arrival_day_offset", "start", "end"}
        for segment in intercity_segments:
            if not isinstance(segment, Mapping):
                return unknown("intercity_verified_segment_malformed")
            segment_id = segment.get("segment_id")
            if (not identifier_is_known(segment_id) or
                    segment_id in expected_by_id):
                return unknown("intercity_verified_segment_id_invalid_or_duplicate")
            expected_by_id[segment_id] = segment
        timeline_ids = [item.get("segment_id") for _day_index, _item_index, item, _day_date
                       in timeline_intercity]
        if len(timeline_ids) != len(set(timeline_ids)):
            return unknown("intercity_timeline_occurrence_missing_duplicate_or_incomplete")
        matched_ids = []
        for _day_index, _item_index, item, day_date in timeline_intercity:
            segment_id = item.get("segment_id")
            expected = expected_by_id.get(segment_id)
            if expected is None:
                return unknown("intercity_timeline_has_unbound_segment")
            if item.get("type") != "travel":
                return unknown("intercity_timeline_occurrence_not_travel")
            if not required_timeline_fields.issubset(item):
                return unknown("intercity_timeline_occurrence_scope_incomplete")
            if (item.get("date") != day_date or
                    any(item.get(key) != expected.get(key) for key in (
                        "segment_id", "direction", "origin_city", "destination_city",
                        "origin_station", "destination_station",
                        "departure_time", "clock_zone", "arrival_time",
                    "arrival_day_offset")) or not _timeline_time_matches(
                        item.get("start"), day_date, expected.get("departure_time"),
                        expected.get("clock_zone")) or not _timeline_time_matches(
                        item.get("end"), day_date, expected.get("arrival_time"),
                        expected.get("clock_zone"),
                        day_offset=expected.get("arrival_day_offset", 0))
                    or day_date != expected.get("travel_date")):
                return unknown("intercity_timeline_occurrence_scope_mismatch")
            matched_ids.append(segment_id)
        if (len(matched_ids) != len(expected_by_id) or
                set(matched_ids) != set(expected_by_id) or
                len(matched_ids) != len(set(matched_ids))):
            return unknown("intercity_timeline_occurrence_missing_duplicate_or_incomplete")

    if not isinstance(components, list) or not components:
        return unknown("components_missing")
    seen_expenses, seen_occurrences = set(), set()
    binding_keys = {"expense_id", "day_index", "item_index", "date", "type", "entity_id"}
    for component in components:
        if not isinstance(component, Mapping):
            return unknown("component_malformed")
        ids = component.get("expense_ids")
        category = component.get("category")
        if category in _INTERCITY_COST_CATEGORIES:
            if category != "intercity" or not isinstance(intercity_expense_ids, list):
                return unknown("intercity_manifest_required_for_expense_binding")
            normal_ids = [_normalise_expense_id(value) for value in ids] if isinstance(ids, list) else []
            expected_ids = [_normalise_expense_id(value) for value in intercity_expense_ids]
            bindings = component.get("intercity_segment_bindings")
            if (not normal_ids or None in normal_ids or len(set(normal_ids)) != len(normal_ids)
                    or normal_ids != expected_ids or not isinstance(bindings, list)
                    or len(bindings) != len(expected_ids)):
                return unknown("intercity_expense_ids_not_bound_to_verified_segments")
            if component.get("occurrence_bindings") not in (None, []):
                return unknown("intercity_generic_occurrence_binding_not_supported")
            if any(value in seen_expenses for value in normal_ids):
                return unknown("expense_occurrence_id_missing_or_duplicate")
            seen_expenses.update(normal_ids)
            continue
        if category in _LODGING_COST_CATEGORIES:
            if category != lodging_category or not isinstance(lodging_expense_ids, list):
                return unknown("lodging_manifest_required_for_expense_binding")
            normal_ids = [_normalise_expense_id(value) for value in ids] if isinstance(ids, list) else []
            expected_ids = [_normalise_expense_id(value) for value in lodging_expense_ids]
            if (not normal_ids or None in normal_ids or len(set(normal_ids)) != len(normal_ids)
                    or normal_ids != expected_ids):
                return unknown("lodging_expense_ids_not_bound_to_verified_nights")
            if component.get("occurrence_bindings") not in (None, []):
                return unknown("lodging_generic_occurrence_binding_not_supported")
            if any(value in seen_expenses for value in normal_ids):
                return unknown("expense_occurrence_id_missing_or_duplicate")
            seen_expenses.update(normal_ids)
            continue
        if category not in _OCCURRENCE_COST_CATEGORIES:
            return unknown("cost_category_requires_unsupported_scope_manifest")
        bindings = component.get("occurrence_bindings")
        if not isinstance(ids, list) or not ids or not isinstance(bindings, list):
            return unknown("expense_occurrence_manifest_missing")
        if len(ids) != len(bindings):
            return unknown("expense_occurrence_manifest_incomplete")
        local_bindings = set()
        for binding in bindings:
            if not isinstance(binding, Mapping) or set(binding) != binding_keys:
                return unknown("expense_occurrence_binding_malformed")
            raw_id = binding.get("expense_id")
            normal_id = _normalise_expense_id(raw_id)
            if normal_id is None or normal_id in seen_expenses:
                return unknown("expense_occurrence_id_missing_or_duplicate")
            seen_expenses.add(normal_id)
            if normal_id not in {_normalise_expense_id(value) for value in ids}:
                return unknown("expense_occurrence_id_not_in_component")
            day_index, item_index = binding.get("day_index"), binding.get("item_index")
            if type(day_index) is not int or type(item_index) is not int:
                return unknown("expense_occurrence_index_invalid")
            occurrence_key = (day_index, item_index)
            actual = occurrences.get(occurrence_key)
            if actual is None or occurrence_key in seen_occurrences:
                return unknown("expense_occurrence_missing_or_duplicate")
            expected = {"date": actual["date"], "type": actual["type"],
                        "entity_id": actual["entity_id"]}
            if any(binding.get(key) != value for key, value in expected.items()):
                return unknown("expense_occurrence_not_bound_to_plan")
            if normal_id in local_bindings:
                return unknown("expense_occurrence_binding_duplicate")
            local_bindings.add(normal_id)
            seen_occurrences.add(occurrence_key)
        if local_bindings != {_normalise_expense_id(value) for value in ids}:
            return unknown("expense_occurrence_manifest_incomplete")
    return {"valid": True, "reason": None,
            "expense_binding_count": len(seen_expenses),
            "occurrence_binding_count": len(seen_occurrences),
            "itinerary_dates": expected_dates}


def aggregate_trip_costs(policy, components, *, scope, evidence_verifier,
                         inventory_verifier, plan=None, task=None,
                         lodging_manifest=None, lodging_claim_verifier=None,
                         lodging_inventory_verifier=None,
                         intercity_manifest=None,
                         intercity_policy_verifier=None,
                         intercity_inventory_verifier=None,
                         intercity_segment_verifier=None,
                         intercity_timetable_verifier=None,
                         intercity_fare_verifier=None):
    """Aggregate one independently verified total for every policy category.

    The inventory callback receives the complete policy, component list,
    requested scope, task, and plan. It must independently verify full cost coverage and that
    no expense is counted across multiple categories. Each component also needs
    a separate evidence callback bound to that component and scope. Both
    callbacks receive isolated copies and must return exactly ``True`` without
    changing their inputs. These callback contracts are trust boundaries: this
    module cannot itself establish that their implementations are independent,
    competent, or truthful.

    Occurrence categories need unique bindings to dated plan timeline items.
    The ``rooms``/``accommodation`` policy category instead requires a raw
    lodging manifest. This function reruns the lodging verifier against the
    actual task and plan; caller-supplied pass results are never accepted.
    Intercity costs require a raw fare manifest revalidated against this exact
    task and plan, with five independent intercity verifiers. Caller-supplied
    result objects are never accepted.

    Any missing, duplicate, conflicting, unverified, or scope-mismatched input
    returns ``status='unknown'`` and no total. A complete result exposes
    arithmetic comparison only; it never certifies truth or trip feasibility.
    Nonnegative integer or canonical decimal-string monetary inputs preserve
    the submitted amount; binary floats are rejected as already imprecise.
    """
    def unknown(*reasons):
        return {
            "status": "unknown",
            "reasons": list(dict.fromkeys(reasons)),
            "total": None,
            "currency": None,
            "comparison": None,
            "truth_certified": False,
            "real_trip_conclusion": False,
        }

    if not isinstance(policy, Mapping) or not isinstance(scope, Mapping):
        return unknown("policy_or_scope_missing")
    if not isinstance(components, list) or not components:
        return unknown("components_missing")
    try:
        original_inputs = (policy, components, scope, plan, task, lodging_manifest, intercity_manifest)
        original_snapshot = copy.deepcopy(original_inputs)
    except Exception:
        return unknown("cost_inputs_cannot_be_snapshotted")

    def originals_unchanged():
        return strict_snapshot_equal(original_inputs, original_snapshot)
    categories = policy.get("required_categories")
    if (not isinstance(categories, list) or not categories
            or any(not isinstance(c, str) or not c.strip() for c in categories)
            or len(set(categories)) != len(categories)):
        return unknown("policy_categories_invalid")
    currency = policy.get("currency")
    party_size = policy.get("party_size")
    limit = policy.get("total_limit")
    trip_scope = policy.get("trip_scope")
    if (not scope_is_complete({"currency": currency})
            or type(party_size) is not int or party_size < 1
            or exact_money(limit) is None
            or not isinstance(trip_scope, Mapping) or not scope_is_complete(dict(trip_scope))
            or not _scope_identities_are_known(trip_scope)):
        return unknown("policy_scope_incomplete")
    if (not scope or not scope_is_complete(dict(scope)) or
            not _scope_identities_are_known(scope) or
            not strict_snapshot_equal(dict(scope), dict(trip_scope))):
        return unknown("requested_trip_scope_mismatch")

    by_category = {}
    semantic_categories = set()
    for item in components:
        if not isinstance(item, Mapping):
            return unknown("component_malformed")
        category = item.get("category")
        if not isinstance(category, str) or not category.strip():
            return unknown("component_category_invalid")
        category_key = unicodedata.normalize("NFKC", category).strip().casefold()
        if (category not in _LODGING_COST_CATEGORIES and
                category not in _INTERCITY_COST_CATEGORIES and
                category_key not in _OCCURRENCE_COST_CATEGORIES):
            return unknown("cost_category_requires_unsupported_scope_manifest")
        semantic_category = "__lodging__" if category in _LODGING_COST_CATEGORIES else category
        if semantic_category in semantic_categories:
            return unknown("duplicate_category", "conflicting_category_claims")
        semantic_categories.add(semantic_category)
        if category in by_category:
            return unknown("duplicate_category", "conflicting_category_claims")
        by_category[category] = item
    missing = [category for category in categories if category not in by_category]
    extra = [category for category in by_category if category not in categories]
    if missing:
        return unknown("required_category_missing")
    if extra:
        return unknown("undeclared_category_present")

    lodging_required_categories = [category for category in categories
                                   if category in _LODGING_COST_CATEGORIES]
    if len(lodging_required_categories) > 1:
        return unknown("lodging_policy_category_aliases_mixed")
    lodging_category = lodging_required_categories[0] if lodging_required_categories else None
    lodging_result = None
    lodging_expense_ids = None
    if lodging_category is not None:
        if (not isinstance(lodging_manifest, Mapping) or
                set(lodging_manifest) != {"requirement", "nights"}):
            return unknown("lodging_manifest_missing_or_malformed")
        from .strict_lodging_cost_manifest import evaluate_lodging_cost_manifest
        component = by_category.get(lodging_category)
        if not isinstance(component, Mapping):
            return unknown("lodging_component_missing")
        component_keys = {"category", "amount", "currency", "party_size", "scope",
                          "expense_ids", "lodging_night_bindings", "evidence", "conflict"}
        if (set(component) - (component_keys | {"occurrence_bindings"}) or
                component.get("occurrence_bindings") not in (None, [])):
            return unknown("lodging_component_has_unsupported_fields")
        lodging_component = {key: component.get(key) for key in component_keys}
        lodging_result = evaluate_lodging_cost_manifest(
            task, plan, lodging_manifest.get("requirement"), lodging_manifest.get("nights"),
            lodging_component, claim_verifier=lodging_claim_verifier,
            inventory_verifier=lodging_inventory_verifier,
            required_categories=categories)
        if not originals_unchanged():
            return unknown("cost_original_inputs_mutated")
        if lodging_result.get("state") != "pass":
            return unknown("lodging_manifest_unknown:" + str(lodging_result.get("reason")))
        lodging_expense_ids = [item.get("expense_id")
                               for item in lodging_manifest.get("nights", [])]
    elif lodging_manifest is not None:
        return unknown("lodging_manifest_for_undeclared_category")

    intercity_result = None
    intercity_expense_ids = None
    if "intercity" in categories:
        if not isinstance(intercity_manifest, Mapping) or set(intercity_manifest) != {"fares"}:
            return unknown("intercity_manifest_missing_or_malformed")
        from .strict_intercity_cost_manifest import evaluate_intercity_cost_manifest
        intercity_result = evaluate_intercity_cost_manifest(
            task, plan, intercity_manifest,
            policy_verifier=intercity_policy_verifier,
            inventory_verifier=intercity_inventory_verifier,
            segment_verifier=intercity_segment_verifier,
            timetable_verifier=intercity_timetable_verifier,
            fare_verifier=intercity_fare_verifier)
        if not originals_unchanged():
            return unknown("cost_original_inputs_mutated")
        if intercity_result.get("state") != "pass":
            return unknown("intercity_manifest_unknown:" + str(intercity_result.get("reason")))
        intercity_expense_ids = [item.get("expense_id") for item in intercity_result["segments"]]
        component = by_category.get("intercity")
        component_keys = {"category", "amount_decimal", "currency", "party_size", "scope",
                          "expense_ids", "intercity_segment_bindings", "evidence", "conflict"}
        if (not isinstance(component, Mapping) or
                set(component) - (component_keys | {"occurrence_bindings"}) or
                not component_keys.issubset(component) or component.get("conflict") is not False
                or component.get("occurrence_bindings") not in (None, [])):
            return unknown("intercity_component_conflict_or_shape_invalid")
        bindings = component.get("intercity_segment_bindings")
        expected_bindings = [{"segment_id": item["segment_id"],
                              "direction": item["direction"],
                              "expense_id": item["expense_id"]}
                             for item in intercity_result["segments"]]
        if not strict_snapshot_equal(bindings, expected_bindings):
            return unknown("intercity_component_bindings_not_bound_to_verified_segments")
        if not isinstance(component.get("amount_decimal"), str):
            return unknown("intercity_component_decimal_amount_invalid")
        try:
            amount_decimal = Decimal(component["amount_decimal"])
            if (not amount_decimal.is_finite() or amount_decimal < 0 or
                    str(amount_decimal) != component["amount_decimal"] or
                    component["amount_decimal"] != intercity_result["total_decimal"]):
                return unknown("intercity_component_amount_not_bound_to_recomputed_total")
        except (InvalidOperation, ValueError):
            return unknown("intercity_component_decimal_amount_invalid")
    elif intercity_manifest is not None:
        return unknown("intercity_manifest_for_undeclared_category")

    # Require an auditable, nonempty identifier inventory and reject aliases
    # that normalize to the same expense across or within categories.
    expense_owner = {}
    for category in categories:
        expense_ids = by_category[category].get("expense_ids")
        if not isinstance(expense_ids, list) or not expense_ids:
            return unknown("expense_inventory_missing_or_incomplete")
        local_ids = set()
        for raw_id in expense_ids:
            expense_id = _normalise_expense_id(raw_id)
            if expense_id is None:
                return unknown("expense_id_invalid")
            if expense_id in local_ids:
                return unknown("expense_id_duplicate_within_category")
            local_ids.add(expense_id)
            previous_category = expense_owner.get(expense_id)
            if previous_category is not None:
                return unknown("expense_id_duplicate_across_categories")
            expense_owner[expense_id] = category

    occurrence_validation = validate_expense_occurrence_bindings(
        components, plan, scope, lodging_category=lodging_category,
        lodging_expense_ids=lodging_expense_ids,
        intercity_expense_ids=intercity_expense_ids,
        intercity_segments=(intercity_result.get("segments")
                            if intercity_result is not None else None))
    if not occurrence_validation["valid"]:
        return unknown(occurrence_validation["reason"])

    if not callable(inventory_verifier):
        return unknown("independent_inventory_verifier_required")
    try:
        inventory_inputs = copy.deepcopy((policy, components, dict(scope), task, plan))
        inventory_before = copy.deepcopy(inventory_inputs)
        inventory_accepted = inventory_verifier(*inventory_inputs)
        if not originals_unchanged():
            return unknown("cost_original_inputs_mutated")
        if not strict_snapshot_equal(inventory_inputs, inventory_before):
            return unknown("inventory_verifier_mutated_input")
        if inventory_accepted is not True:
            return unknown("cost_inventory_unverified")
    except Exception:
        return unknown("inventory_verifier_failed")

    verified_components = []
    for category in categories:
        component = by_category[category]
        if component.get("currency") != currency:
            return unknown("currency_mismatch")
        if type(component.get("party_size")) is not int or component.get("party_size") != party_size:
            return unknown("party_size_mismatch")
        if (not isinstance(component.get("scope"), Mapping) or
                not scope_is_complete(dict(component["scope"])) or
                not _scope_identities_are_known(component["scope"]) or not strict_snapshot_equal(
                dict(component["scope"]), dict(trip_scope))):
            return unknown("component_trip_scope_mismatch")
        if category == "intercity":
            if "amount" in component or not isinstance(component.get("amount_decimal"), str):
                return unknown("intercity_component_amount_invalid")
        elif category == lodging_category:
            # The lodging manifest has already bound the supplied component
            # to exact per-night Decimal arithmetic.
            pass
        elif exact_money(component.get("amount")) is None:
            return unknown("component_amount_invalid")
        evidence = component.get("evidence")
        if evidence is None or evidence == {} or evidence == [] or evidence == "":
            return unknown("component_evidence_missing")
        if component.get("conflict") is True:
            return unknown("component_evidence_conflict")
        if not callable(evidence_verifier):
            return unknown("independent_evidence_verifier_required")
        try:
            callback_inputs = copy.deepcopy((component, policy, dict(scope)))
            before = copy.deepcopy(callback_inputs)
            accepted = evidence_verifier(*callback_inputs)
            if not originals_unchanged():
                return unknown("cost_original_inputs_mutated")
            if not strict_snapshot_equal(callback_inputs, before):
                return unknown("evidence_verifier_mutated_input")
            if accepted is not True:
                return unknown("component_evidence_unverified")
        except Exception:
            return unknown("evidence_verifier_failed")
        verified_components.append(component)

    try:
        # Decimal strings preserve the supplied decimal values at a budget
        # boundary (e.g. 0.1 + 0.2) without binary float comparison noise.
        with localcontext() as context:
            context.prec = max(1000, sum(len(str(item.get('amount_decimal', item.get('amount'))))
                                         for item in verified_components) + 20)
            exact_total = sum((Decimal(intercity_result['total_decimal'])
                               if item.get('category') == 'intercity'
                               else Decimal(lodging_result['total_decimal'])
                               if item.get('category') == lodging_category
                               else Decimal(str(item['amount']))
                               for item in verified_components), Decimal(0))
            exact_limit = Decimal(str(limit))
        float_total = float(exact_total)
        if not _finite_nonnegative(float_total):
            return unknown("aggregate_total_invalid")
        total = (int(exact_total) if exact_total == exact_total.to_integral_value()
                 else float_total)
        total_is_approximate = (isinstance(total, float) and
                                Decimal.from_float(total) != exact_total)
    except (OverflowError, TypeError, ValueError, InvalidOperation):
        return unknown("aggregate_total_invalid")
    return {
        "status": "arithmetic_evaluated",
        "reasons": [],
        "total": total,
        "total_decimal": format(exact_total, 'f'),
        "total_is_approximate": total_is_approximate,
        "currency": currency,
        "comparison": "within_limit" if exact_total <= exact_limit else "over_limit",
        "truth_certified": False,
        "real_trip_conclusion": False,
        "execution_confirmed": False,
        "scope": copy.deepcopy(dict(trip_scope)),
        "party_size": party_size,
        "categories": list(categories),
        "lodging_manifest_check": lodging_result,
        "intercity_manifest_check": intercity_result,
    }
