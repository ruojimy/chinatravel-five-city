"""Assemble a synthetic P31-shaped proposal from explicit caller input.

This module validates structure and copies supplied timeline events. It does
not infer missing routes, times, identities, prices, evidence, or domain
completeness, and it is not a feasibility planner.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from typing import Any
from .strict_scope import identifier_is_known


_KINDS = frozenset({"attraction", "restaurant", "accommodation", "poi",
                    "metro_station", "train", "flight"})
_EVENT_TYPES = frozenset({"visit", "attraction", "breakfast", "lunch",
                          "dinner", "meal"})
_MEAL_SLOTS = frozenset({"breakfast", "lunch", "dinner"})
_CONTEXT_KEYS = frozenset({"uid", "level", "start_city", "target_city",
                           "start_date", "days", "people_number",
                           "start_location_id"})
_DAY_KEYS = frozenset({"date", "city", "start_location", "timeline"})
_LOCATION_KEYS = frozenset({"entity_id", "kind", "entrance_id"})
_EVENT_KEYS = frozenset({"occurrence_id", "type", "entity_id", "entity_kind",
                         "entrance_id", "start", "end", "entity", "meal_slot"})
_TRAVEL_KEYS = frozenset({"occurrence_id", "type", "origin_id", "origin_kind",
                          "origin_entrance_id", "destination_id", "destination_kind",
                          "destination_entrance_id", "start", "end", "mode", "from", "to",
                          "entity_id", "intercity_segment"})
_INTERCITY_SEGMENT_KEYS = frozenset({
    "segment_id", "direction", "origin_city", "destination_city",
    "origin_station", "destination_station", "travel_date", "departure_time",
    "clock_zone", "seat_class", "passenger_count", "arrival_time",
    "arrival_day_offset", "Duration", "Duration_unit", "expense_id"})
_MAX_TOTAL_OCCURRENCES = 512


def assemble_strict_plan(context: Any, daily_items: Any, *, entity_kinds: Any,
                         repeat_policy: Any) -> dict[str, Any]:
    """Build a 3-day P31-shaped proposal without filling omitted facts.

    ``context`` supplies identity, horizon and day-one start ID. ``daily_items``
    is three ordered day objects. Each day declares its date, city, start
    location and non-empty timeline. Every day starts with a caller-provided
    travel leg from that exact start anchor. Any two consecutive timeline
    occurrences must share an explicit endpoint; movement between different
    endpoints therefore needs a caller-supplied travel item.

    ``entity_kinds`` is a caller-supplied ID-to-kind map used only for internal
    consistency. ``repeat_policy.allow_repeated_occurrence_entities`` must be
    explicit; this assembler does not silently decide whether repeating an
    attraction/restaurant is permitted.

    An optional travel ``entity_id`` and full ``intercity_segment`` are
    caller-supplied data. For same-day segments they are copied into both the
    occurrence and segment inventory so later independent cost checks can
    bind them; this is structural assembly, not timetable or fare verification.
    Overnight intercity travel remains unsupported.
    """
    error = _validate_context(context)
    if error:
        return _blocked(error)
    if not isinstance(entity_kinds, dict) or not entity_kinds:
        return _blocked("entity_kind_mapping_missing")
    if any(not identifier_is_known(entity_id) or
           not isinstance(kind, str) or kind not in _KINDS
           for entity_id, kind in entity_kinds.items()):
        return _blocked("entity_kind_mapping_invalid")
    if context["start_location_id"] not in entity_kinds:
        return _blocked("start_location_kind_binding_missing")
    if (not isinstance(repeat_policy, dict) or
            set(repeat_policy) != {"allow_repeated_occurrence_entities"} or
            type(repeat_policy.get("allow_repeated_occurrence_entities")) is not bool):
        return _blocked("repeat_policy_missing_or_invalid")
    if not isinstance(daily_items, list) or len(daily_items) != 3:
        return _blocked("three_explicit_days_required")

    first_date = date.fromisoformat(context["start_date"])
    output_days = []
    seen_occurrences = set()
    seen_selected_entities = set()
    seen_intercity_segments = set()
    occurrence_count = 0
    previous_day_end = None
    previous_day_time_end = None
    intercity_segments = []
    for day_index, raw_day in enumerate(daily_items):
        if not isinstance(raw_day, dict) or set(raw_day) != _DAY_KEYS:
            return _blocked("day_shape_invalid", {"day_index": day_index})
        expected_date = (first_date + timedelta(days=day_index)).isoformat()
        if raw_day.get("date") != expected_date:
            return _blocked("day_date_mismatch", {"day_index": day_index,
                "expected_date": expected_date, "actual_date": raw_day.get("date")})
        if raw_day.get("city") != context["target_city"]:
            return _blocked("day_city_mismatch", {"day_index": day_index})
        anchor = raw_day.get("start_location")
        if not _valid_location(anchor, entity_kinds):
            return _blocked("day_start_location_invalid", {"day_index": day_index})
        if day_index == 0 and anchor["entity_id"] != context["start_location_id"]:
            return _blocked("first_day_anchor_does_not_match_context_start", {
                "expected_entity_id": context["start_location_id"],
                "actual_entity_id": anchor["entity_id"]})
        if day_index > 0 and previous_day_end != {
                "entity_id": anchor["entity_id"], "entrance_id": anchor["entrance_id"]}:
            return _blocked("overnight_transition_not_explicit_or_endpoint_mismatch", {
                "day_index": day_index})
        timeline = raw_day.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            return _blocked("day_timeline_missing", {"day_index": day_index})

        built_timeline = []
        last_end = None
        previous_endpoint = None
        for item_index, item in enumerate(timeline):
            if not isinstance(item, dict):
                return _blocked("timeline_item_malformed", {
                    "day_index": day_index, "item_index": item_index})
            typ = item.get("type")
            expected_keys = _TRAVEL_KEYS if typ == "travel" else _EVENT_KEYS
            if set(item) - expected_keys or not set(item) <= expected_keys:
                return _blocked("timeline_item_fields_unsupported_or_invalid", {
                    "day_index": day_index, "item_index": item_index})
            if not isinstance(typ, str) or typ not in _EVENT_TYPES | {"travel"}:
                return _blocked("timeline_type_unsupported", {
                    "day_index": day_index, "item_index": item_index})
            occurrence_id = item.get("occurrence_id")
            if not _nonempty(occurrence_id):
                return _blocked("occurrence_id_missing", {
                    "day_index": day_index, "item_index": item_index})
            if occurrence_id in seen_occurrences:
                return _blocked("occurrence_id_duplicate", {"occurrence_id": occurrence_id})
            seen_occurrences.add(occurrence_id)
            occurrence_count += 1
            if occurrence_count > _MAX_TOTAL_OCCURRENCES:
                return _blocked("timeline_occurrence_limit_exceeded", {
                    "occurrence_count": occurrence_count,
                    "max_occurrences": _MAX_TOTAL_OCCURRENCES})

            interval, reason = _interval(expected_date, item.get("start"), item.get("end"))
            if reason:
                return _blocked(reason, {"day_index": day_index, "item_index": item_index})
            start, end, time_values = interval
            if item_index == 0 and previous_day_time_end is not None and start < previous_day_time_end:
                return _blocked("cross_day_absolute_time_order_conflict", {
                    "day_index": day_index, "item_index": item_index})
            if last_end is not None:
                try:
                    if start < last_end:
                        return _blocked("timeline_order_or_overlap_conflict", {
                            "day_index": day_index, "item_index": item_index})
                except TypeError:
                    return _blocked("timeline_timezone_incomparable", {
                        "day_index": day_index, "item_index": item_index})

            if typ == "travel":
                if not _valid_travel(item, entity_kinds):
                    return _blocked("travel_scope_missing_or_kind_mismatch", {
                        "day_index": day_index, "item_index": item_index})
                origin = {"entity_id": item["origin_id"],
                          "entrance_id": item["origin_entrance_id"]}
                destination = {"entity_id": item["destination_id"],
                              "entrance_id": item["destination_entrance_id"]}
                if item_index == 0:
                    if origin != {"entity_id": anchor["entity_id"],
                                  "entrance_id": anchor["entrance_id"]}:
                        return _blocked("first_travel_origin_does_not_match_day_anchor", {
                            "day_index": day_index})
                elif previous_endpoint != origin:
                    return _blocked("transition_missing_or_endpoint_mismatch", {
                        "day_index": day_index, "item_index": item_index})
                built = {"type": "travel", "start": time_values[0],
                         "end": time_values[1], "origin_id": item["origin_id"],
                         "origin_entrance_id": item["origin_entrance_id"],
                         "destination_id": item["destination_id"],
                         "destination_entrance_id": item["destination_entrance_id"],
                         "mode": item["mode"]}
                if "from" in item:
                    built["from"] = item["from"]
                if "to" in item:
                    built["to"] = item["to"]
                if "entity_id" in item:
                    built["entity_id"] = item["entity_id"]
                if "intercity_segment" in item:
                    segment = item["intercity_segment"]
                    if (not isinstance(segment, dict) or set(segment) != _INTERCITY_SEGMENT_KEYS or
                            not _nonempty(item.get("entity_id")) or
                            not _nonempty(segment.get("segment_id")) or
                            segment.get("travel_date") != expected_date or
                            type(segment.get("arrival_day_offset")) is not int or
                            segment.get("arrival_day_offset") != 0):
                        return _blocked("intercity_event_scope_missing_or_unsupported", {
                            "day_index": day_index, "item_index": item_index})
                    if segment['segment_id'] in seen_intercity_segments:
                        return _blocked("intercity_segment_id_duplicate", {
                            "day_index": day_index, "item_index": item_index})
                    if (not _segment_time_matches(expected_date, item['start'],
                            segment.get('departure_time'), segment.get('clock_zone')) or
                            not _segment_time_matches(expected_date, item['end'],
                            segment.get('arrival_time'), segment.get('clock_zone'))):
                        return _blocked("intercity_event_time_scope_mismatch", {
                            "day_index": day_index, "item_index": item_index})
                    seen_intercity_segments.add(segment['segment_id'])
                    intercity_segments.append(copy.deepcopy(segment))
                    for key in ("segment_id", "direction", "origin_city", "destination_city",
                                "origin_station", "destination_station", "departure_time",
                                "clock_zone", "arrival_time", "arrival_day_offset"):
                        built[key] = copy.deepcopy(segment[key])
                    built["date"] = segment["travel_date"]
                next_endpoint = destination
            else:
                if not _valid_event(item, entity_kinds):
                    return _blocked("event_scope_missing_or_kind_mismatch", {
                        "day_index": day_index, "item_index": item_index})
                entity_id = item["entity_id"]
                if not repeat_policy["allow_repeated_occurrence_entities"]:
                    if entity_id in seen_selected_entities:
                        return _blocked("repeated_occurrence_entity_forbidden", {
                            "day_index": day_index, "item_index": item_index,
                            "entity_id": entity_id})
                    seen_selected_entities.add(entity_id)
                location = {"entity_id": entity_id, "entrance_id": item["entrance_id"]}
                if item_index == 0:
                    return _blocked("first_timeline_item_must_be_explicit_travel", {
                        "day_index": day_index})
                if previous_endpoint != location:
                    return _blocked("transition_missing_or_endpoint_mismatch", {
                        "day_index": day_index, "item_index": item_index})
                built = {"type": typ, "entity_id": entity_id,
                         "entrance_id": item["entrance_id"],
                         "start": time_values[0], "end": time_values[1]}
                if "entity" in item:
                    built["entity"] = item["entity"]
                if "meal_slot" in item:
                    built["meal_slot"] = item["meal_slot"]
                next_endpoint = location
            built["occurrence_id"] = occurrence_id
            built_timeline.append(built)
            last_end, previous_endpoint = end, next_endpoint

        if day_index == 0 and timeline[0].get("type") != "travel":
            return _blocked("first_day_initial_travel_required")
        previous_day_end = previous_endpoint
        previous_day_time_end = last_end
        output_days.append({"date": expected_date, "city": raw_day["city"],
                            "timeline": built_timeline})

    plan = {"uid": context["uid"], "level": context["level"], "days": output_days}
    if intercity_segments:
        plan["intercity_segments"] = intercity_segments
    return {"status": "synthetic_plan_assembled_unverified", "plan": plan,
            "label": "synthetic_engineering_proposal", "synthetic_proposal": True,
            "engineering_only": True, "explicit_three_day_structure": True,
            "explicit_intra_day_transition_structure": True,
            "entity_kind_mapping_consistency_checked": True,
            "occurrence_count": occurrence_count,
            "feasibility": None, "facts_verified": False,
            "domain_complete": False, "task_coverage_verified": False,
            "truth_certified": False, "execution_confirmed": False,
            "planner_invoked": False}


def _validate_context(context):
    if not isinstance(context, dict) or set(context) != _CONTEXT_KEYS:
        return "plan_context_missing_or_malformed"
    if (not _nonempty(context.get("uid")) or
            not isinstance(context.get("level"), str) or
            context.get("level") not in {"easy", "medium", "human"} or
            not _nonempty(context.get("start_city")) or
            not _nonempty(context.get("target_city")) or
            type(context.get("days")) is not int or context["days"] != 3 or
            type(context.get("people_number")) is not int or context["people_number"] < 1 or
            not _nonempty(context.get("start_location_id"))):
        return "plan_context_invalid_or_three_days_required"
    first_date = _parse_date(context.get("start_date"))
    if first_date is None:
        return "plan_context_start_date_invalid"
    try:
        first_date + timedelta(days=2)
    except OverflowError:
        return "plan_context_trip_dates_out_of_range"
    return None


def _valid_location(location, entity_kinds):
    return (isinstance(location, dict) and set(location) == _LOCATION_KEYS and
            _nonempty(location.get("entity_id")) and
            _nonempty(location.get("entrance_id")) and
            isinstance(location.get("kind"), str) and
            location.get("kind") in _KINDS and
            entity_kinds.get(location.get("entity_id")) == location.get("kind"))


def _valid_event(item, entity_kinds):
    typ, entity_id, kind = item.get("type"), item.get("entity_id"), item.get("entity_kind")
    if (set(item) - _EVENT_KEYS or not _nonempty(entity_id) or
            not _nonempty(item.get("entrance_id")) or
            not isinstance(kind, str) or
            kind not in _KINDS or entity_kinds.get(entity_id) != kind):
        return False
    if "entity" in item and not _nonempty(item["entity"]):
        return False
    if typ in {"visit", "attraction"} and kind != "attraction":
        return False
    if typ in _MEAL_SLOTS | {"meal"} and kind != "restaurant":
        return False
    if typ == "meal":
        return (isinstance(item.get("meal_slot"), str) and
                item.get("meal_slot") in _MEAL_SLOTS)
    if "meal_slot" in item and item["meal_slot"] != typ:
        return False
    return "meal_slot" not in item or typ in _MEAL_SLOTS


def _valid_travel(item, entity_kinds):
    return (set(item) - _TRAVEL_KEYS == set() and
            all(_nonempty(item.get(key)) for key in
                ("occurrence_id", "origin_id", "origin_entrance_id",
                 "destination_id", "destination_entrance_id", "mode")) and
            isinstance(item.get("origin_kind"), str) and
            item.get("origin_kind") in _KINDS and
            isinstance(item.get("destination_kind"), str) and
            item.get("destination_kind") in _KINDS and
            entity_kinds.get(item.get("origin_id")) == item.get("origin_kind") and
            entity_kinds.get(item.get("destination_id")) == item.get("destination_kind") and
            ("entity_id" not in item or _nonempty(item["entity_id"])) and
            ("from" not in item or _nonempty(item["from"])) and
            ("to" not in item or _nonempty(item["to"])))


def _interval(day, start, end):
    if not isinstance(start, str) or not isinstance(end, str):
        return None, "timeline_time_missing"
    try:
        first, last = datetime.fromisoformat(day + "T" + start), datetime.fromisoformat(day + "T" + end)
    except ValueError:
        return None, "timeline_time_invalid"
    if (first.utcoffset() is None or last.utcoffset() is None or
            first.utcoffset() != last.utcoffset()):
        return None, "timeline_timezone_missing_or_mismatched"
    if first.date().isoformat() != day or last.date().isoformat() != day:
        return None, "timeline_time_outside_declared_day"
    try:
        if last <= first:
            return None, "timeline_interval_nonpositive"
    except TypeError:
        return None, "timeline_timezone_incomparable"
    return (first, last, (start, end)), None


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _segment_time_matches(day, value, expected, zone):
    if not all(isinstance(item, str) and item for item in (value, expected, zone)):
        return False
    try:
        actual = datetime.fromisoformat(day + 'T' + value)
        claimed = datetime.fromisoformat(day + 'T' + expected + zone)
    except (TypeError, ValueError):
        return False
    return (actual.utcoffset() is not None and claimed.utcoffset() is not None and
            actual.date() == claimed.date() and
            actual.time() == claimed.time() and actual.utcoffset() == claimed.utcoffset())


def _nonempty(value):
    return identifier_is_known(value)


def _blocked(reason, detail=None):
    try:
        safe_detail = copy.deepcopy(detail)
    except Exception:
        safe_detail = None
    return {"status": "blocked", "reason": reason, "detail": safe_detail,
            "plan": None, "label": "synthetic_engineering_proposal",
            "synthetic_proposal": False, "feasibility": None,
            "facts_verified": False, "domain_complete": False,
            "task_coverage_verified": False, "truth_certified": False,
            "execution_confirmed": False, "planner_invoked": False}
