"""Fail-closed adapter from a narrow V6 task to the legacy P31 input shape.

This module only prepares input. It never calls the planner and never turns
planner estimates into evidence or verified facts.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from datetime import date


_KINDS = frozenset({"attraction", "restaurant", "accommodation", "poi",
                    "metro_station", "train", "flight"})
_LOCAL_KINDS = frozenset({"attraction", "restaurant", "accommodation", "poi",
                          "metro_station"})
_CONTEXT_KEYS = frozenset({"start", "dates", "city_sequence", "constraints",
                           "static_estimate"})
_START_KEYS = frozenset({"entity_id", "name", "city", "coordinate_system",
                         "position_wgs84"})
_CONSTRAINT_KEYS = frozenset({"window", "start_time", "mode", "return_to_start",
                              "budget"})


def prepare_legacy_p31_input(task, *, legacy_context=None, candidates_by_id=None):
    """Prepare a one-day same-city P31 input from explicit caller data.

    The current V6 cohort asks for three days and is therefore rejected before
    any legacy context is consumed. A prepared result is not a plan, evaluation,
    or evidence artifact; its estimates remain explicitly unverified.
    """
    if not isinstance(task, dict):
        return _blocked("task_not_object", "pipeline")
    if task.get("split") != "development" or task.get("purpose") != "development":
        return _blocked("development_task_required", "adapter")
    uid = task.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        return _blocked("task_uid_missing", "pipeline")
    if type(task.get("days")) is not int or task["days"] != 1:
        return _blocked("unsupported_legacy_horizon", "adapter", {
            "requested_days": task.get("days"), "supported_days": [1]})
    if (not isinstance(task.get("start_city"), str) or not task["start_city"].strip() or
            task.get("start_city") != task.get("target_city")):
        return _blocked("legacy_local_same_city_required", "context")
    if type(task.get("people_number")) is not int or task["people_number"] < 1:
        return _blocked("task_people_number_invalid", "context")
    try:
        task_date = date.fromisoformat(task["start_date"])
    except (TypeError, ValueError, KeyError):
        return _blocked("task_start_date_invalid", "context")
    if task.get("level") not in ("easy", "medium", "human"):
        return _blocked("task_level_invalid", "pipeline")

    declared = (task.get("candidate_selection", {}).get("required_entity_ids")
                if isinstance(task.get("candidate_selection"), dict) else None)
    selected = (task.get("generation", {}).get("selected_entities_by_kind")
                if isinstance(task.get("generation"), dict) else None)
    if (not isinstance(declared, list) or not declared or
            any(not isinstance(x, str) or not x.strip() for x in declared) or
            len(declared) != len(set(declared)) or not isinstance(selected, dict)):
        return _blocked("candidate_declaration_invalid", "pipeline")
    expected = {}
    for kind, item in selected.items():
        if (kind not in _KINDS or not isinstance(item, dict) or
                not isinstance(item.get("id"), str) or
                not isinstance(item.get("stored_name_unverified"), str) or
                not item["stored_name_unverified"].strip()):
            return _blocked("candidate_kind_or_name_metadata_invalid", "pipeline")
        if item["id"] in expected:
            return _blocked("candidate_id_mapping_duplicate", "pipeline")
        expected[item["id"]] = (kind, item["stored_name_unverified"])
    if set(declared) != set(expected):
        return _blocked("candidate_id_mapping_mismatch", "pipeline")
    if any(kind in ("train", "flight") for kind, _ in expected.values()):
        return _blocked("auxiliary_transport_is_not_a_route", "adapter")
    if any(kind not in _LOCAL_KINDS for kind, _ in expected.values()):
        return _blocked("candidate_kind_unsupported_by_local_planner", "adapter")
    for required_kind in ("attraction", "restaurant", "accommodation"):
        if sum(kind == required_kind for kind, _ in expected.values()) != 1:
            return _blocked("legacy_required_candidate_kind_count_invalid", "pipeline",
                            {"kind": required_kind})

    if not isinstance(candidates_by_id, Mapping):
        return _blocked("explicit_candidate_mapping_required", "pipeline")
    if any(not isinstance(key, str) for key in candidates_by_id):
        return _blocked("candidate_mapping_keys_invalid", "pipeline")
    if set(candidates_by_id) != set(declared):
        return _blocked("candidate_mapping_id_set_mismatch", "pipeline", {
            "missing": sorted(set(declared) - set(candidates_by_id)),
            "extra": sorted(set(candidates_by_id) - set(declared))})
    candidates = []
    candidate_names = set()
    for entity_id in declared:
        candidate = candidates_by_id[entity_id]
        kind, name = expected[entity_id]
        if not isinstance(candidate, Mapping):
            return _blocked("candidate_not_object", "pipeline", {"entity_id": entity_id})
        if (candidate.get("entity_id") != entity_id or candidate.get("kind") != kind or
                candidate.get("name") != name or candidate.get("city") != task["target_city"]):
            return _blocked("candidate_binding_mismatch", "pipeline", {"entity_id": entity_id})
        if name in candidate_names:
            # P31 resolves schedule labels with next(c for c in candidates
            # if c["name"] == label); duplicate names can select another ID.
            return _blocked("candidate_name_ambiguous_for_legacy_planner", "pipeline",
                            {"name": name})
        candidate_names.add(name)
        if not isinstance(candidate.get("data"), Mapping):
            return _blocked("candidate_data_missing", "pipeline", {"entity_id": entity_id})
        coord_system = candidate.get("coordinate_system")
        if not isinstance(coord_system, str) or not coord_system.strip():
            return _blocked("candidate_coordinate_system_missing", "context",
                            {"entity_id": entity_id})
        if kind in ("attraction", "restaurant", "accommodation"):
            data = candidate["data"]
            if not _valid_coordinate(data.get("lat"), -90, 90) or not _valid_coordinate(
                    data.get("lon"), -180, 180):
                return _blocked("legacy_core_candidate_coordinates_missing_or_invalid", "context",
                                {"entity_id": entity_id})
            if coord_system != "WGS84":
                return _blocked("legacy_core_candidate_coordinate_system_unsupported", "context",
                                {"entity_id": entity_id, "coordinate_system": coord_system})
            if kind in ("attraction", "restaurant"):
                if (not _finite_nonnegative(data.get("price")) or
                        not _valid_clock(data.get("opentime")) or
                        not _valid_clock(data.get("endtime")) or
                        _clock_minutes(data["opentime"]) >= _clock_minutes(data["endtime"])):
                    return _blocked("legacy_candidate_required_data_missing_or_invalid", "context",
                                    {"entity_id": entity_id,
                                     "fields": ["price", "opentime", "endtime"]})
            elif not _finite_nonnegative(data.get("price")):
                return _blocked("legacy_candidate_required_data_missing_or_invalid", "context",
                                {"entity_id": entity_id, "fields": ["price"]})
            if kind == "attraction":
                visit_min = data.get("recommendmintime")
                visit_max = data.get("recommendmaxtime")
                if (not _finite_nonnegative(visit_min) or visit_min <= 0 or
                        (visit_max not in (None, "") and
                         (not _finite_nonnegative(visit_max) or visit_max <= 0))):
                    return _blocked("legacy_candidate_visit_duration_missing_or_invalid", "context",
                                    {"entity_id": entity_id})
        # Construct only the old planner fields. No candidate self-assertion
        # such as entity_verified is copied into the translated object.
        candidates.append({"entity_id": entity_id, "kind": kind, "name": name,
                           "city": task["target_city"],
                           "data": copy.deepcopy(dict(candidate["data"])),
                           "coordinate_system": coord_system})

    if not isinstance(legacy_context, Mapping):
        return _blocked("explicit_legacy_context_required", "context")
    if any(not isinstance(key, str) for key in legacy_context):
        return _blocked("legacy_context_shape_invalid", "context")
    if set(legacy_context) != _CONTEXT_KEYS:
        return _blocked("legacy_context_shape_invalid", "context", {
            "missing": sorted(_CONTEXT_KEYS - set(legacy_context)),
            "extra": sorted(set(legacy_context) - _CONTEXT_KEYS)})
    start = legacy_context["start"]
    if not isinstance(start, Mapping) or set(start) != _START_KEYS:
        return _blocked("legacy_start_shape_invalid", "context")
    start_id = start.get("entity_id")
    if not isinstance(start_id, str) or start_id not in expected:
        return _blocked("legacy_start_id_undeclared", "context")
    start_kind, start_name = expected[start_id]
    start_candidate = candidates_by_id[start_id]
    if (start_kind not in ("poi", "metro_station") or start.get("name") != start_name or
            start.get("city") != task["target_city"] or start_candidate.get("city") != start.get("city") or
            start.get("coordinate_system") != "WGS84" or
            start_candidate.get("coordinate_system") != "WGS84" or
            not isinstance(start.get("position_wgs84"), (list, tuple)) or
            len(start["position_wgs84"]) != 2 or
            not all(_valid_coordinate(x, -180 if i == 1 else -90, 180 if i == 1 else 90)
                    for i, x in enumerate(start["position_wgs84"]))):
        return _blocked("legacy_start_binding_invalid", "context")
    start_data = start_candidate.get("data", {})
    if (not _valid_coordinate(start_data.get("lat"), -90, 90) or
            not _valid_coordinate(start_data.get("lon"), -180, 180) or
            tuple(start["position_wgs84"]) != (start_data["lat"], start_data["lon"])):
        return _blocked("legacy_start_coordinate_binding_mismatch", "context")

    dates = legacy_context["dates"]
    cities = legacy_context["city_sequence"]
    if dates != [task_date.isoformat()] or cities != [task["target_city"]]:
        return _blocked("legacy_date_or_city_sequence_mismatch", "context")
    constraints = legacy_context["constraints"]
    if not isinstance(constraints, Mapping) or set(constraints) != _CONSTRAINT_KEYS:
        return _blocked("legacy_constraints_shape_invalid", "context")
    if (not _valid_clock(constraints.get("start_time")) or
            not isinstance(constraints.get("window"), list) or
            len(constraints["window"]) != 2 or
            not all(_valid_clock(x) for x in constraints["window"]) or
            _clock_minutes(constraints["window"][0]) >= _clock_minutes(constraints["window"][1]) or
            not isinstance(constraints.get("mode"), str) or not constraints["mode"].strip() or
            constraints.get("return_to_start") is not True or
            not _finite_nonnegative(constraints.get("budget"))):
        return _blocked("legacy_constraints_values_invalid", "context")
    estimate = legacy_context["static_estimate"]
    if (not isinstance(estimate, Mapping) or set(estimate) != {"budget_limit"} or
            not _finite_nonnegative(estimate.get("budget_limit"))):
        return _blocked("legacy_static_estimate_invalid", "context")

    legacy_input = {
        "uid": uid,
        "level": task["level"],
        "people_number": task["people_number"],
        "nature_language": task.get("nature_language", ""),
        "dates": copy.deepcopy(list(dates)),
        "city_sequence": copy.deepcopy(list(cities)),
        "start": copy.deepcopy(dict(start)),
        "constraints": copy.deepcopy(dict(constraints)),
        "static_estimate": copy.deepcopy(dict(estimate)),
        "candidates": candidates,
    }
    return {"status": "legacy_shape_built_for_engineering_only",
            "reason": "explicit_local_input_shape_validated",
            "planning_equivalence": False,
            "v6_task_plannability_established": False,
            "legacy_input": legacy_input, "planner_invoked": False,
            "v6_constraints_translated": False, "intercity_inferred": False,
            "estimates_verified": False, "truth_certified": False,
            "execution_confirmed": False}


def _blocked(reason, axis, detail=None):
    return {"status": "blocked", "reason": reason, "axis": axis,
            "detail": detail, "legacy_input": None, "planner_invoked": False,
            "v6_constraints_translated": False, "intercity_inferred": False,
            "estimates_verified": False, "truth_certified": False,
            "execution_confirmed": False}


def _valid_coordinate(value, minimum, maximum):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and minimum <= value <= maximum
    except (OverflowError, TypeError, ValueError):
        return False


def _finite_nonnegative(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except (OverflowError, TypeError, ValueError):
        return False


def _valid_clock(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except ValueError:
        return False
    return 0 <= hour < 24 and 0 <= minute < 60


def _clock_minutes(value):
    return int(value[:2]) * 60 + int(value[3:])
