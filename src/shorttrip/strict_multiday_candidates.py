"""Unverified Cartesian candidate proposals for an explicit three-day horizon.

This module consumes caller-supplied, dated slot occurrences only. It does not
select sources, fill fields, test feasibility, or certify plan completeness.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from itertools import product
from math import prod
from typing import Any


_KINDS = frozenset({"attraction", "restaurant", "accommodation", "poi",
                    "metro_station", "train", "flight"})
_DAY_KEYS = frozenset({"date", "slots"})
_SLOT_KEYS = frozenset({"slot_id", "candidates"})
_OCCURRENCE_KEYS = frozenset({"entity_id", "kind", "date", "start", "end"})
DEFAULT_MAX_COMBINATIONS = 256
HARD_MAX_COMBINATIONS = 256
MAX_TOTAL_SLOTS = 36
MAX_CANDIDATES_PER_SLOT = 32
MAX_TOTAL_OCCURRENCES = 512


def generate_multiday_candidate_proposals(daily_slots: Any, *, expected_dates: Any,
                                           max_combinations: int = DEFAULT_MAX_COMBINATIONS) -> dict:
    """Enumerate one caller-supplied occurrence choice per ordered slot.

    Exactly three days are supported. Dates are compared to an explicit
    ``expected_dates`` list. Each occurrence must carry a full ISO datetime
    with an explicit UTC offset; intervals must be positive and stay on their
    declared day. These are input-shape checks only. Overlap, routes, budget,
    evidence, and task coverage are intentionally not evaluated.
    """
    if type(max_combinations) is not int or max_combinations < 1:
        return _blocked("combination_limit_invalid", {"max_combinations": max_combinations})
    if max_combinations > HARD_MAX_COMBINATIONS:
        return _blocked("combination_limit_exceeds_hard_cap", {
            "requested_limit": max_combinations,
            "hard_max_combinations": HARD_MAX_COMBINATIONS})
    if not isinstance(expected_dates, list) or len(expected_dates) != 3:
        return _blocked("three_explicit_expected_dates_required")
    parsed_dates = []
    for value in expected_dates:
        parsed = _parse_date(value)
        if parsed is None:
            return _blocked("expected_date_invalid", {"date": value})
        parsed_dates.append(parsed)
    if len(set(expected_dates)) != 3:
        return _blocked("expected_dates_duplicate")
    if any(parsed_dates[index] != parsed_dates[0] + timedelta(days=index)
           for index in range(3)):
        return _blocked("expected_dates_not_three_consecutive_days")
    if not isinstance(daily_slots, list) or len(daily_slots) != 3:
        return _blocked("unsupported_candidate_horizon", {
            "day_count": len(daily_slots) if isinstance(daily_slots, list) else None,
            "supported_day_count": 3})

    total_slots = 0
    total_occurrences = 0
    option_lists = []
    for day_index, (day, expected_date) in enumerate(zip(daily_slots, expected_dates)):
        if not isinstance(day, dict) or set(day) != _DAY_KEYS:
            return _blocked("day_shape_invalid", {"day_index": day_index})
        if day["date"] != expected_date:
            return _blocked("day_date_mismatch", {"day_index": day_index,
                                                   "expected_date": expected_date,
                                                   "actual_date": day["date"]})
        slots = day["slots"]
        if not isinstance(slots, list) or not slots:
            return _blocked("day_slots_missing", {"day_index": day_index})
        total_slots += len(slots)
        if total_slots > MAX_TOTAL_SLOTS:
            return _blocked("slot_count_exceeds_limit", {
                "slot_count": total_slots, "max_total_slots": MAX_TOTAL_SLOTS})
        seen_slot_ids = set()
        for slot_index, slot in enumerate(slots):
            if (not isinstance(slot, dict) or set(slot) != _SLOT_KEYS or
                    not isinstance(slot.get("slot_id"), str) or not slot["slot_id"].strip()):
                return _blocked("slot_shape_invalid", {"day_index": day_index,
                                                        "slot_index": slot_index})
            if slot["slot_id"] in seen_slot_ids:
                return _blocked("slot_id_duplicate_within_day", {"day_index": day_index,
                                                                  "slot_id": slot["slot_id"]})
            seen_slot_ids.add(slot["slot_id"])
            candidates = slot["candidates"]
            if not isinstance(candidates, list) or not candidates:
                return _blocked("slot_candidates_missing", {"day_index": day_index,
                                                             "slot_id": slot["slot_id"]})
            if len(candidates) > MAX_CANDIDATES_PER_SLOT:
                return _blocked("slot_candidate_count_exceeds_limit", {
                    "day_index": day_index, "slot_id": slot["slot_id"],
                    "candidate_count": len(candidates),
                    "max_candidates_per_slot": MAX_CANDIDATES_PER_SLOT})
            total_occurrences += len(candidates)
            if total_occurrences > MAX_TOTAL_OCCURRENCES:
                return _blocked("occurrence_count_exceeds_limit", {
                    "occurrence_count": total_occurrences,
                    "max_total_occurrences": MAX_TOTAL_OCCURRENCES})
            parsed_options = []
            seen_occurrences = set()
            for candidate_index, occurrence in enumerate(candidates):
                checked, reason = _validate_occurrence(occurrence, expected_date)
                if reason:
                    return _blocked(reason, {"day_index": day_index,
                                             "slot_id": slot["slot_id"],
                                             "candidate_index": candidate_index})
                signature = tuple(checked[key] for key in
                                  ("entity_id", "kind", "date", "start", "end"))
                if signature in seen_occurrences:
                    return _blocked("duplicate_slot_occurrence", {"day_index": day_index,
                                                                   "slot_id": slot["slot_id"]})
                seen_occurrences.add(signature)
                parsed_options.append({"day_index": day_index,
                                       "slot_index": slot_index,
                                       "slot_id": slot["slot_id"],
                                       **checked})
            option_lists.append(parsed_options)

    combination_count = prod(len(options) for options in option_lists)
    if combination_count > max_combinations:
        return _blocked("candidate_combination_limit_exceeded", {
            "combination_count": combination_count,
            "max_combinations": max_combinations})

    proposals = []
    for index, selection in enumerate(product(*option_lists), start=1):
        proposals.append({"proposal_id": f"proposal-{index:04d}",
                          "occurrences": [dict(item) for item in selection]})
    return {
        "status": "candidate_proposal_unverified",
        "candidate_proposal_unverified": True,
        "proposals": proposals,
        "combination_count": combination_count,
        "enumeration_exhaustive_over_supplied_slots": True,
        "task_coverage_verified": False,
        "plan_complete": False,
        "feasibility": None,
        "facts_verified": False,
        "infeasibility_proven": False,
        "planner_invoked": False,
        "execution_confirmed": False,
    }


def _validate_occurrence(value: Any, expected_date: str):
    if not isinstance(value, dict) or set(value) != _OCCURRENCE_KEYS:
        return None, "occurrence_shape_invalid"
    entity_id, kind = value.get("entity_id"), value.get("kind")
    if not isinstance(entity_id, str) or not entity_id.strip():
        return None, "occurrence_entity_id_invalid"
    if not isinstance(kind, str) or kind not in _KINDS:
        return None, "occurrence_kind_invalid"
    if value.get("date") != expected_date:
        return None, "occurrence_date_mismatch"
    start, end = _parse_datetime(value.get("start")), _parse_datetime(value.get("end"))
    if start is None or end is None:
        return None, "occurrence_time_invalid_or_timezone_missing"
    if start.date().isoformat() != expected_date or end.date().isoformat() != expected_date:
        return None, "occurrence_time_outside_declared_day"
    if start.utcoffset() != end.utcoffset():
        return None, "occurrence_timezone_offset_mismatch"
    try:
        if end <= start:
            return None, "occurrence_interval_nonpositive"
    except TypeError:
        return None, "occurrence_timezone_incomparable"
    return {key: value[key] for key in _OCCURRENCE_KEYS}, None


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _parse_datetime(value):
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _blocked(reason, detail=None):
    try:
        safe_detail = copy.deepcopy(detail)
    except Exception:
        safe_detail = None
    return {"status": "blocked", "reason": reason, "detail": safe_detail,
            "candidate_proposal_unverified": False, "proposals": [],
            "combination_count": None, "enumeration_exhaustive_over_supplied_slots": False,
            "task_coverage_verified": False, "plan_complete": False,
            "feasibility": None, "facts_verified": False,
            "infeasibility_proven": False, "planner_invoked": False,
            "execution_confirmed": False}
