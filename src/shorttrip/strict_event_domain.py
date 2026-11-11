"""Bounded finite domains of explicit event slots for assembled development search.

The caller supplies every slot option as a complete ordered event fragment.
This module selects among those fragments, asks the strict assembler to reject
missing transitions, and requires a caller-owned record-binding factory. It
does not create routes, times, events, evidence, lodging, or a complete task
domain.
"""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .strict_assembled_search import search_assembled_development_assignments
from .strict_plan_assembler import assemble_strict_plan
from .strict_snapshot import strict_snapshot_equal


MAX_TOTAL_CANDIDATES = 512
MAX_ASSIGNMENT_COMBINATIONS = 10_000
MAX_SELECTED_EVENTS = 512
_SLOT_KEYS = frozenset({"slot_id", "date", "candidates"})
_OPTION_KEYS = frozenset({"candidate_id", "events"})
_ANCHOR_KEYS = frozenset({"date", "city", "start_location"})
_LOCATION_KEYS = frozenset({"entity_id", "kind", "entrance_id"})


def search_explicit_event_domain(
    task: Any,
    context: Any,
    day_anchors: Any,
    slots: Any,
    *,
    entity_kinds: Any,
    repeat_policy: Any,
    record_bindings_resolver,
    now: str,
    registry: Any = None,
    diagnostic_inputs: Any = None,
    diagnostic_callbacks: Any = None,
    max_assignments: int = MAX_ASSIGNMENT_COMBINATIONS,
) -> dict[str, Any]:
    """Select explicit candidates per ordered slot and delegate strict search.

    Slot options contain complete caller-supplied event lists, including every
    travel leg and interval. Concatenation never fills a gap. The binding
    callback receives isolated task, assignment and assembled-plan copies and
    must return occurrence-level bindings; mutation or malformed output yields
    unknown. The returned search is bounded to these declared options only.
    """
    error, normalized = _validate_domain(task, context, day_anchors, slots,
        entity_kinds, repeat_policy, record_bindings_resolver, now,
        registry, diagnostic_inputs, diagnostic_callbacks, max_assignments)
    if error:
        return _unknown_domain_result(error)

    context_snapshot = copy.deepcopy(context)
    anchors_snapshot = copy.deepcopy(day_anchors)
    slots_snapshot = copy.deepcopy(normalized)
    kinds_snapshot = copy.deepcopy(entity_kinds)
    repeat_snapshot = copy.deepcopy(repeat_policy)
    registry_snapshot = copy.deepcopy(registry or {})
    inputs_snapshot = copy.deepcopy(diagnostic_inputs or {})
    callbacks_snapshot = dict(diagnostic_callbacks or {})
    option_map = {slot["slot_id"]: {item["candidate_id"]: item["events"]
                                    for item in slot["candidates"]}
                  for slot in slots_snapshot}
    dimensions = {slot["slot_id"]: [item["candidate_id"]
                                    for item in slot["candidates"]]
                  for slot in slots_snapshot}

    def resolver(task_copy, assignment_copy):
        task_before = _canonical_or_none(task_copy)
        assignment_before = _canonical_or_none(assignment_copy)
        daily = []
        for anchor in anchors_snapshot:
            daily.append({"date": anchor["date"], "city": anchor["city"],
                          "start_location": copy.deepcopy(anchor["start_location"]),
                          "timeline": []})
        for slot in slots_snapshot:
            candidate_id = assignment_copy.get(slot["slot_id"])
            option_events = option_map[slot["slot_id"]].get(candidate_id)
            if option_events is None:
                return {"malformed": True}
            day_index = _date_index(slot["date"], anchors_snapshot)
            daily[day_index]["timeline"].extend(copy.deepcopy(option_events))

        assemble_probe = assemble_strict_plan(
            copy.deepcopy(context_snapshot), copy.deepcopy(daily),
            entity_kinds=copy.deepcopy(kinds_snapshot),
            repeat_policy=copy.deepcopy(repeat_snapshot))
        plan = (assemble_probe.get("plan")
                if assemble_probe.get("status") == "synthetic_plan_assembled_unverified"
                else None)
        if plan is None:
            record_bindings = []
        else:
            callback_task = copy.deepcopy(task_copy)
            callback_assignment = copy.deepcopy(assignment_copy)
            callback_plan = copy.deepcopy(plan)
            callback_before = (_canonical_or_none(callback_task),
                               _canonical_or_none(callback_assignment),
                               _canonical_or_none(callback_plan))
            try:
                record_bindings = record_bindings_resolver(
                    callback_task, callback_assignment, callback_plan)
            except Exception:
                record_bindings = None
            if (callback_before != (_canonical_or_none(callback_task),
                                    _canonical_or_none(callback_assignment),
                                    _canonical_or_none(callback_plan))):
                record_bindings = None
            if not isinstance(record_bindings, list):
                record_bindings = None
            else:
                try:
                    record_bindings = copy.deepcopy(record_bindings)
                except Exception:
                    record_bindings = None
        if (_canonical_or_none(task_copy) != task_before or
                _canonical_or_none(assignment_copy) != assignment_before):
            return {"malformed": True}
        return {"plan_context": copy.deepcopy(context_snapshot),
            "daily_items": copy.deepcopy(daily),
            "entity_kinds": copy.deepcopy(kinds_snapshot),
            "repeat_policy": copy.deepcopy(repeat_snapshot),
            "record_bindings": record_bindings,
            "now": now,
            "registry": copy.deepcopy(registry_snapshot),
            "diagnostic_inputs": copy.deepcopy(inputs_snapshot),
            "diagnostic_callbacks": dict(callbacks_snapshot)}

    result = search_assembled_development_assignments(
        task, dimensions, resolver=resolver, max_assignments=max_assignments)
    result.update({
        "event_domain_schema": "strict-explicit-event-slot-domain-v1",
        "declared_slot_count": len(slots_snapshot),
        "declared_candidate_option_count": sum(len(slot["candidates"])
                                                for slot in slots_snapshot),
        "declared_assignment_combinations": math.prod(len(values)
                                                       for values in dimensions.values()),
        "selected_event_facts_were_inferred": False,
        "missing_transitions_were_filled": False,
        "record_bindings_generated_internally": False,
        "event_domain_complete": False,
        "task_domain_complete": False,
        "planner_complete": False,
        "truth_certified": False,
        "execution_confirmed": False,
    })
    return result


def _validate_domain(task, context, day_anchors, slots, entity_kinds,
                     repeat_policy, bindings_resolver, now, registry,
                     diagnostic_inputs, diagnostic_callbacks, max_assignments):
    if not isinstance(task, dict):
        return "task_not_object", None
    if (task.get("split") == "holdout" or task.get("purpose") == "holdout"):
        return "holdout_rejected_from_event_domain", None
    if task.get("split") != "development" or task.get("purpose") != "development":
        return "development_task_required", None
    if (not isinstance(context, dict) or set(context) != {
            "uid", "level", "start_city", "target_city", "start_date", "days",
            "people_number", "start_location_id"}):
        return "event_domain_context_invalid", None
    for key in ("uid", "level", "start_city", "target_city", "start_date", "days", "people_number"):
        task_key = "uid" if key == "uid" else key
        if not strict_snapshot_equal(context.get(key), task.get(task_key)):
            return "event_domain_context_task_mismatch", None
    if (type(context.get("days")) is not int or context["days"] != 3 or
            type(context.get("people_number")) is not int or context["people_number"] < 1):
        return "three_day_event_domain_required", None
    try:
        first_date = date.fromisoformat(context["start_date"])
        if first_date.isoformat() != context["start_date"]:
            return "event_domain_start_date_invalid", None
    except (TypeError, ValueError):
        return "event_domain_start_date_invalid", None
    try:
        expected_dates = [(first_date + timedelta(days=index)).isoformat() for index in range(3)]
    except OverflowError:
        return "event_domain_trip_dates_out_of_range", None
    if (not isinstance(day_anchors, list) or len(day_anchors) != 3 or
            any(not isinstance(anchor, dict) or set(anchor) != _ANCHOR_KEYS
                for anchor in day_anchors)):
        return "three_explicit_day_anchors_required", None
    for index, (anchor, expected) in enumerate(zip(day_anchors, expected_dates)):
        if (anchor.get("date") != expected or anchor.get("city") != context.get("target_city") or
                not isinstance(anchor.get("start_location"), dict) or
                set(anchor["start_location"]) != _LOCATION_KEYS or
                not all(isinstance(anchor["start_location"].get(key), str) and
                        anchor["start_location"][key].strip() for key in _LOCATION_KEYS)):
            return "day_anchor_date_city_or_location_invalid", None
    if not isinstance(entity_kinds, dict) or not entity_kinds:
        return "entity_kind_mapping_missing", None
    if context.get("start_location_id") not in entity_kinds:
        return "context_start_location_kind_missing", None
    if not callable(bindings_resolver):
        return "record_bindings_resolver_required", None
    if not isinstance(now, str) or not now.strip():
        return "diagnostic_time_missing", None
    if registry is not None and not isinstance(registry, Mapping):
        return "registry_malformed", None
    if diagnostic_inputs is not None and not isinstance(diagnostic_inputs, Mapping):
        return "diagnostic_inputs_malformed", None
    if diagnostic_callbacks is not None and (not isinstance(diagnostic_callbacks, Mapping) or
            any(not isinstance(key, str) or not callable(value)
                for key, value in diagnostic_callbacks.items())):
        return "diagnostic_callbacks_malformed", None
    if (type(max_assignments) is not int or max_assignments < 1 or
            max_assignments > MAX_ASSIGNMENT_COMBINATIONS):
        return "assignment_limit_invalid", None
    if not isinstance(slots, list) or not slots:
        return "event_slots_missing", None
    if len(slots) > MAX_TOTAL_CANDIDATES:
        return "event_slot_limit_exceeded", None

    normalized, seen_slot_ids, total_options = [], set(), 0
    options_product = 1
    last_day_index = -1
    slots_per_day = [0, 0, 0]
    max_selected_event_count = 0
    for slot_index, raw_slot in enumerate(slots):
        if not isinstance(raw_slot, dict) or set(raw_slot) != _SLOT_KEYS:
            return "event_slot_shape_invalid", None
        slot_id, slot_date, candidates = (raw_slot.get("slot_id"), raw_slot.get("date"),
                                          raw_slot.get("candidates"))
        if not isinstance(slot_id, str) or not slot_id.strip() or slot_id in seen_slot_ids:
            return "event_slot_id_missing_or_duplicate", None
        seen_slot_ids.add(slot_id)
        day_index = _date_index(slot_date, day_anchors)
        if day_index is None:
            return "event_slot_date_not_in_trip", None
        if day_index < last_day_index:
            return "event_slots_not_ordered_by_date", None
        last_day_index = day_index
        slots_per_day[day_index] += 1
        if not isinstance(candidates, list) or not candidates:
            return "event_slot_candidates_missing", None
        ids, items = set(), []
        maximum_events = 0
        for option in candidates:
            if not isinstance(option, dict) or set(option) != _OPTION_KEYS:
                return "event_candidate_shape_invalid", None
            candidate_id, events = option.get("candidate_id"), option.get("events")
            if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in ids:
                return "event_candidate_id_missing_or_duplicate", None
            ids.add(candidate_id)
            if not isinstance(events, list) or not events or any(not isinstance(e, dict) for e in events):
                return "event_candidate_events_missing_or_malformed", None
            maximum_events = max(maximum_events, len(events))
            items.append({"candidate_id": candidate_id, "events": copy.deepcopy(events)})
        total_options += len(items)
        options_product *= len(items)
        max_selected_event_count += maximum_events
        if total_options > MAX_TOTAL_CANDIDATES:
            return "event_candidate_limit_exceeded", None
        if options_product > MAX_ASSIGNMENT_COMBINATIONS:
            return "event_domain_product_limit_exceeded", None
        normalized.append({"slot_id": slot_id, "date": slot_date, "candidates": items})
    if any(count == 0 for count in slots_per_day):
        return "event_slot_coverage_missing_for_day", None
    if max_selected_event_count > MAX_SELECTED_EVENTS:
        return "selected_event_count_limit_exceeded", None
    if options_product > max_assignments:
        return "event_domain_exceeds_assignment_limit", None
    return None, normalized


def _date_index(value, anchors):
    if not isinstance(value, str):
        return None
    for index, anchor in enumerate(anchors):
        if anchor.get("date") == value:
            return index
    return None


def _unknown_domain_result(reason):
    return {"status": "solver_incomplete", "reason": reason,
        "outcome_state": "unknown", "domain_valid": False,
        "domain_enumeration_complete": False, "declared_assignment_count": None,
        "enumerated_assignment_count": 0,
        "decision_counts": {"pass": 0, "fail": 0, "unknown": 0},
        "candidate_count": 0, "unknown_assignment_count": 0,
        "global_unsat_claimed": False, "assignments": [], "diagnostics": [],
        "event_domain_complete": False, "task_domain_complete": False,
        "planner_complete": False, "truth_certified": False,
        "execution_confirmed": False}


def _canonical_or_none(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None
