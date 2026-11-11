"""Development-only orchestration for an explicitly built P31-shaped plan.

This prototype does not build plans, certify evidence, or establish complete
itinerary feasibility. The caller must provide the plan, its declared context,
and exact entity-ID-to-record/field-requirement bindings.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Mapping

from .collection_workflow import classify
from .strict_p31_bridge import diagnose_p31_plan
from .strict_scope import scope_is_complete, identifier_is_known
from .strict_snapshot import strict_snapshot_equal


_ACTIVITY_TYPES = frozenset(("visit", "attraction", "breakfast", "lunch", "dinner", "meal"))


def diagnose_development_plan(
    task: Any,
    plan: Any,
    *,
    plan_context: Any,
    record_bindings: Any,
    now: str,
    registry: Mapping[str, Any] | None = None,
    business_chain_events: Any = None,
    business_chain_inventory_verifier=None,
    **diagnostic_callbacks: Any,
) -> dict[str, Any]:
    """Validate explicit development bindings and call the strict P31 bridge.

    ``record_bindings`` is a list of ``{entity_id, kind, record, occurrences}``.
    Each occurrence has ``day_index``, ``item_index``, ``role`` and a non-empty
    ``requirements`` list. Every requirement must carry the exact plan-day
    ``travel_date``. One record may appear several times, but each occurrence
    needs its own scope binding. ``plan_context`` is a separately supplied
    consistency assertion, not evidence of the asserted facts.
    """
    uid = task.get("uid", "unknown") if isinstance(task, dict) else "unknown"
    level = task.get("level", "easy") if isinstance(task, dict) else "easy"
    if level not in ("easy", "medium", "human"):
        level = "easy"

    try:
        protected_inputs = (task, plan, plan_context, record_bindings, registry,
                            business_chain_events,
                            {k: v for k, v in diagnostic_callbacks.items() if not callable(v)})
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return _error(uid, level, "development_inputs_cannot_be_snapshotted", "pipeline", None)

    error = _validate(task, plan, plan_context, record_bindings)
    if error:
        return _error(uid, level, *error)

    declared = set(task["candidate_selection"]["required_entity_ids"])
    selected = task["generation"]["selected_entities_by_kind"]
    declared_kind_by_id = {item["id"]: kind for kind, item in selected.items()}
    try:
        references = _plan_occurrences(plan)
    except ValueError as exc:
        return _error(uid, level, "plan_timeline_entity_binding_invalid", "pipeline",
                      {"detail": str(exc)})
    undeclared_plan_ids = sorted({ref["entity_id"] for ref in references.values()} - declared)
    if undeclared_plan_ids:
        return _error(uid, level, "plan_uses_undeclared_entity_id", "pipeline",
                      {"entity_ids": undeclared_plan_ids})
    kind_error = _activity_kind_error(plan, declared_kind_by_id)
    if kind_error is not None:
        return _error(uid, level, "plan_activity_kind_mismatch", "pipeline", kind_error)
    bindings_by_id = {item["entity_id"]: item for item in record_bindings}
    referenced_candidate_ids = {ref["entity_id"] for ref in references.values()}
    if referenced_candidate_ids != set(bindings_by_id):
        missing = sorted(referenced_candidate_ids - set(bindings_by_id))
        unused = sorted(set(bindings_by_id) - referenced_candidate_ids)
        return _error(uid, level, "plan_binding_coverage_mismatch", "pipeline",
                      {"missing_bindings": missing, "unreferenced_bindings": unused})

    occurrence_bindings = {}
    for binding in record_bindings:
        for occurrence in binding["occurrences"]:
            key = (occurrence["day_index"], occurrence["item_index"], occurrence["role"])
            if key in occurrence_bindings:
                return _error(uid, level, "duplicate_plan_occurrence_binding", "pipeline",
                              {"occurrence": list(key)})
            reference = references.get(key)
            if reference is None or reference["entity_id"] != binding["entity_id"]:
                return _error(uid, level, "plan_occurrence_binding_mismatch", "pipeline",
                              {"occurrence": list(key), "entity_id": binding["entity_id"]})
            occurrence_bindings[key] = occurrence
            label = reference.get("label")
            expected_name = task["generation"]["selected_entities_by_kind"][binding["kind"]].get(
                "stored_name_unverified")
            if binding["record"].get("name") != expected_name:
                return _error(uid, level, "record_task_name_metadata_mismatch", "pipeline",
                              {"entity_id": binding["entity_id"]})
            if label is not None and label != expected_name:
                return _error(uid, level, "plan_label_entity_mismatch", "pipeline",
                              {"entity_id": binding["entity_id"], "plan_label": label})

    if set(occurrence_bindings) != set(references):
        return _error(uid, level, "plan_occurrence_binding_coverage_mismatch", "pipeline",
                      {"missing": [list(k) for k in sorted(set(references) - set(occurrence_bindings))],
                       "extra": [list(k) for k in sorted(set(occurrence_bindings) - set(references))]})

    record_requirements = [
        (bindings_by_id[entity_id]["record"], [
            requirement
            for occurrence in bindings_by_id[entity_id]["occurrences"]
            for requirement in occurrence["requirements"]
        ])
        for entity_id in sorted(bindings_by_id)
    ]
    chain = task.get("generation", {}).get("business_chain")
    # Explicit events must correspond in order to the actual plan. This
    # mechanical binding does not establish complete business coverage: an
    # independent verifier must review the task, plan, chain and event list.
    bound_events = _bound_chain_events(business_chain_events, references, declared_kind_by_id)
    chain_input = {"chain": chain, "events": bound_events} if isinstance(chain, list) else None
    if bound_events is not None:
        def verify_chain_inventory(checked_chain, checked_events):
            if not callable(business_chain_inventory_verifier):
                return False
            try:
                args = copy.deepcopy((task, plan, checked_chain, checked_events))
                before = copy.deepcopy(args)
                accepted = business_chain_inventory_verifier(*args)
                return accepted is True and strict_snapshot_equal(args, before)
            except Exception:
                return False
        diagnostic_callbacks = dict(diagnostic_callbacks)
        diagnostic_callbacks['chain_inventory_verifier'] = verify_chain_inventory
    try:
        result = diagnose_p31_plan(
            plan,
            task=task,
            now=now,
            registry=dict(registry or {}),
            record_requirements=record_requirements,
            business_chain=chain_input,
            **diagnostic_callbacks,
        )
    except Exception as exc:
        return _error(uid, level, "strict_bridge_failed", "pipeline",
                      {"error_type": type(exc).__name__})

    if not strict_snapshot_equal(protected_inputs, protected_snapshot):
        return _error(uid, level, "development_original_inputs_mutated", "pipeline", None)

    # Pin the prototype's status even if a downstream helper changes labels.
    result.update({
        "label": "engineering_only",
        "engineering_only": True,
        "formal_score": None,
        "frozen": False,
        "truth_certified": False,
        "execution_confirmed": False,
        "planner_integration": "caller_supplied_plan_only",
        "complete_planner_integrated": False,
        "bound_entity_ids": sorted(bindings_by_id),
        "bound_occurrence_count": len(occurrence_bindings),
        "plan_context_is_evidence": False,
    })
    return result


def _validate(task: Any, plan: Any, context: Any, bindings: Any):
    if not isinstance(task, dict):
        return "task_not_object", "pipeline", None
    if task.get("split") == "holdout" or task.get("purpose") == "holdout":
        return "holdout_rejected_from_development_orchestrator", "adapter", None
    if task.get("split") != "development" or task.get("purpose") != "development":
        return "development_task_required", "adapter", None
    uid, level = task.get("uid"), task.get("level")
    if not isinstance(uid, str) or not uid.strip() or level not in ("easy", "medium", "human"):
        return "task_identity_or_level_invalid", "pipeline", None
    if not isinstance(plan, dict):
        return "plan_missing_or_not_object", "pipeline", None
    if plan.get("uid") != uid:
        return "task_plan_uid_mismatch", "adapter", None
    if plan.get("level") != level:
        return "task_plan_level_mismatch", "adapter", None

    if not isinstance(context, dict):
        return "plan_context_missing", "context", None
    required_context = ("start_city", "target_city", "start_date", "days",
                        "people_number", "start_location_id")
    if any(context.get(key) in (None, "") for key in required_context):
        return "plan_context_incomplete", "context", {
            "missing": [key for key in required_context if context.get(key) in (None, "")]
        }
    for key in ("start_city", "target_city", "start_date", "days", "people_number"):
        if not strict_snapshot_equal(context.get(key), task.get(key)):
            return "plan_context_task_mismatch", "context", {"field": key}
    if type(context.get("days")) is not int or context["days"] < 1:
        return "plan_context_days_invalid", "context", None
    if type(context.get("people_number")) is not int or context["people_number"] < 1:
        return "plan_context_people_invalid", "context", None
    if not scope_is_complete({'start_city': context.get('start_city'),
                              'target_city': context.get('target_city')}):
        return "plan_context_city_unknown", "context", None
    try:
        first_date = date.fromisoformat(context["start_date"])
    except (TypeError, ValueError):
        return "plan_context_start_date_invalid", "context", None
    if first_date.isoformat() != context["start_date"]:
        return "plan_context_start_date_invalid", "context", None

    days = plan.get("days")
    if not isinstance(days, list) or len(days) != context["days"]:
        return "plan_days_missing_or_count_mismatch", "pipeline", None
    try:
        first_date + timedelta(days=len(days) - 1)
    except OverflowError:
        return "plan_date_horizon_out_of_range", "context", None
    for index, day in enumerate(days):
        if not isinstance(day, dict) or day.get("city") != context["target_city"]:
            return "plan_day_city_missing_or_mismatched", "context", {"day_index": index}
        if day.get("date") != (first_date + timedelta(days=index)).isoformat():
            return "plan_day_date_missing_or_mismatched", "context", {"day_index": index}
        if not isinstance(day.get("timeline"), list) or not day["timeline"]:
            return "plan_timeline_missing", "pipeline", {"day_index": index}
    first_timeline = next((item for item in days[0]["timeline"]
                           if isinstance(item, dict) and item.get("type") != "wait"), None)
    if not isinstance(first_timeline, dict) or first_timeline.get("type") != "travel":
        return "plan_initial_position_not_established", "context", None
    if first_timeline.get("origin_id") != context["start_location_id"]:
        return "plan_start_location_mismatch", "context", {
            "expected_start_location_id": context["start_location_id"],
            "actual_origin_id": first_timeline.get("origin_id")}

    selection = task.get("candidate_selection")
    declared = selection.get("required_entity_ids") if isinstance(selection, dict) else None
    if (not isinstance(declared, list) or not declared or
            any(not isinstance(value, str) or not value.strip() for value in declared) or
            len(set(declared)) != len(declared)):
        return "declared_candidate_ids_invalid", "pipeline", None
    generation = task.get("generation")
    selected = generation.get("selected_entities_by_kind") if isinstance(generation, dict) else None
    if not isinstance(selected, dict):
        return "declared_candidate_kind_mapping_missing", "pipeline", None
    expected_kinds = {item.get("id"): kind for kind, item in selected.items()
                      if isinstance(kind, str) and isinstance(item, dict)
                      and isinstance(item.get("id"), str)}
    if len(expected_kinds) != len(selected) or set(declared) != set(expected_kinds):
        return "declared_candidate_kind_mapping_mismatch", "pipeline", None
    if any(not isinstance(item.get("stored_name_unverified"), str)
           or not item["stored_name_unverified"].strip() for item in selected.values()):
        return "candidate_name_metadata_missing", "pipeline", None
    if context["start_location_id"] not in expected_kinds:
        return "start_location_id_undeclared", "context", None

    if not isinstance(bindings, list):
        return "record_bindings_missing_or_invalid", "pipeline", None
    binding_ids = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            return "record_binding_not_object", "pipeline", {"binding_index": index}
        entity_id, kind = binding.get("entity_id"), binding.get("kind")
        record, occurrences = binding.get("record"), binding.get("occurrences")
        if not isinstance(entity_id, str) or not entity_id:
            return "record_binding_entity_id_missing", "pipeline", {"binding_index": index}
        binding_ids.append(entity_id)
        if entity_id not in expected_kinds:
            return "record_binding_uses_undeclared_entity_id", "pipeline", {"entity_id": entity_id}
        if kind != expected_kinds[entity_id]:
            return "record_binding_kind_mismatch", "pipeline", {"entity_id": entity_id}
        if (not isinstance(record, dict) or record.get("id") != entity_id or
                record.get("city") != context["target_city"] or
                not isinstance(record.get("name"), str) or
                not isinstance(record.get("payload"), dict) or
                not isinstance(record.get("claims"), list)):
            return "record_binding_record_mismatch_or_malformed", "pipeline", {"entity_id": entity_id}
        if record.get("kind") != kind:
            return "record_binding_kind_mismatch", "pipeline", {"entity_id": entity_id}
        if not isinstance(occurrences, list) or not occurrences:
            return "record_binding_occurrences_missing", "pipeline", {"entity_id": entity_id}
        seen_occurrences = set()
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                return "record_binding_occurrence_malformed", "pipeline", {"entity_id": entity_id}
            day_index, item_index, role = (occurrence.get("day_index"),
                                           occurrence.get("item_index"), occurrence.get("role"))
            if (type(day_index) is not int or type(item_index) is not int or
                    day_index < 0 or item_index < 0 or
                    role not in ("activity", "travel_origin", "travel_destination", "travel_entity")):
                return "record_binding_occurrence_location_invalid", "pipeline", {"entity_id": entity_id}
            key = (day_index, item_index, role)
            if key in seen_occurrences:
                return "duplicate_record_occurrence_binding", "pipeline", {"entity_id": entity_id}
            seen_occurrences.add(key)
            if day_index >= len(days) or item_index >= len(days[day_index]["timeline"]):
                return "record_binding_occurrence_out_of_range", "pipeline", {"entity_id": entity_id}
            requirements = occurrence.get("requirements")
            if not isinstance(requirements, list) or not requirements:
                return "record_binding_requirements_missing", "pipeline", {
                    "entity_id": entity_id, "occurrence": list(key)}
            expected_date = days[day_index]["date"]
            seen_requirements = set()
            for req in requirements:
                if (not isinstance(req, dict) or
                        not isinstance(req.get("native_field"), str) or not req["native_field"] or
                        not isinstance(req.get("policy_field"), str) or not req["policy_field"] or
                        not isinstance(req.get("scope"), dict) or
                        not scope_is_complete(req["scope"])):
                    return "record_binding_requirement_incomplete", "pipeline", {
                        "entity_id": entity_id, "occurrence": list(key)}
                if req["scope"].get("travel_date") != expected_date:
                    return "record_binding_requirement_date_mismatch", "pipeline", {
                        "entity_id": entity_id, "occurrence": list(key),
                        "expected_travel_date": expected_date,
                        "actual_travel_date": req["scope"].get("travel_date")}
                key_req = (req["native_field"], req["policy_field"],
                           repr(sorted(req["scope"].items())))
                if key_req in seen_requirements:
                    return "record_binding_requirement_duplicate", "pipeline", {
                        "entity_id": entity_id, "occurrence": list(key)}
                seen_requirements.add(key_req)
    if len(binding_ids) != len(set(binding_ids)):
        return "duplicate_record_binding", "pipeline", None
    return None


def _plan_occurrences(plan: dict):
    references = {}
    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind in _ACTIVITY_TYPES:
                entity_id = item.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id:
                    raise ValueError("plan_activity_entity_id_missing")
                _add_reference(references, day_index, item_index, "activity", entity_id,
                               day["date"], item.get("entity", item.get("name")))
            elif kind == "travel":
                for key, role, label_key in (("origin_id", "travel_origin", "from"),
                                             ("destination_id", "travel_destination", "to")):
                    entity_id = item.get(key)
                    if not isinstance(entity_id, str) or not entity_id:
                        raise ValueError("plan_travel_endpoint_id_missing:" + key)
                    _add_reference(references, day_index, item_index, role, entity_id,
                                   day["date"], item.get(label_key))
                if isinstance(item.get("entity_id"), str) and item["entity_id"]:
                    _add_reference(references, day_index, item_index, "travel_entity",
                                   item["entity_id"], day["date"], item.get("entity", item.get("name")))
    return references


def _bound_chain_events(events, references, kinds):
    """Accept only ordered explicit references to occurrences in this plan."""
    if not isinstance(events, list):
        return None
    keys = {'day_index', 'item_index', 'role', 'date', 'entity_id', 'kind'}
    ranks = {'travel_origin': 0, 'travel_entity': 1, 'travel_destination': 2, 'activity': 3}
    previous = None
    for event in events:
        if not isinstance(event, dict) or set(event) != keys:
            return None
        day, item, role = event['day_index'], event['item_index'], event['role']
        if type(day) is not int or type(item) is not int or not isinstance(role, str) or role not in ranks:
            return None
        order = (day, item, ranks[role])
        if previous is not None and order <= previous:
            return None
        ref = references.get((day, item, role))
        entity_id = event['entity_id']
        if (ref is None or not identifier_is_known(entity_id) or
                not identifier_is_known(event['kind']) or
                ref['entity_id'] != entity_id or ref['travel_date'] != event['date'] or
                kinds.get(entity_id) != event['kind']):
            return None
        previous = order
    return copy.deepcopy(events)


def _add_reference(references: dict, day_index: int, item_index: int, role: str,
                   entity_id: str, travel_date: str, label: Any):
    references[(day_index, item_index, role)] = {
        "entity_id": entity_id, "travel_date": travel_date, "label": label}


def _activity_kind_error(plan: dict, declared_kind_by_id: Mapping[str, str]):
    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            expected_kind = ("restaurant" if item_type in ("breakfast", "lunch", "dinner", "meal")
                             else "attraction" if item_type in ("visit", "attraction") else None)
            if expected_kind is None:
                continue
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue  # The reference-shape check reports the missing ID.
            actual_kind = declared_kind_by_id.get(entity_id)
            if actual_kind != expected_kind:
                return {"day_index": day_index, "item_index": item_index,
                        "item_type": item_type, "entity_id": entity_id,
                        "expected_kind": expected_kind, "declared_kind": actual_kind}
    return None


def _error(uid: Any, level: str, reason: str, axis: str,
           detail: dict[str, Any] | None) -> dict[str, Any]:
    key = uid if isinstance(uid, str) and uid else "unknown"
    gap = {"gap_id": f"development-orchestrator:{key}:{reason}",
           "blocker_class": axis, "reason": reason,
           "required": True, "blocking": True, "repairable": False}
    if detail is not None:
        gap["detail"] = detail
    result = classify({"uid": "development-orchestrator:" + key,
                       "level": level, "city": "unknown", "gaps": [gap],
                       "hard_checks": [], "planner": {"supported": False},
                       "plan_present": False, "required_checks_complete": False})
    result.update({"label": "engineering_only", "engineering_only": True,
                   "formal_score": None, "frozen": False,
                   "truth_certified": False, "execution_confirmed": False,
                   "complete_planner_integrated": False})
    return result
