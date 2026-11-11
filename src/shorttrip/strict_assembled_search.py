"""Compose explicit three-day assembly with bounded development search.

This adapter does not select entities or invent events. For each finite-domain
assignment, a caller resolver must supply all three days, kinds, repeat policy,
and the existing occurrence-to-record bindings. Assembly or integration gaps
remain unknown; this is not a complete planner or a feasibility proof.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from .strict_plan_assembler import assemble_strict_plan
from .strict_search_orchestrator import search_development_assignments
from .strict_snapshot import strict_snapshot_equal


_RESOLVED_KEYS = frozenset({
    "plan_context", "daily_items", "entity_kinds", "repeat_policy",
    "record_bindings", "now", "registry", "diagnostic_inputs",
    "diagnostic_callbacks",
})
_REQUIRED_KEYS = frozenset({
    "plan_context", "daily_items", "entity_kinds", "repeat_policy",
    "record_bindings", "now",
})


def search_assembled_development_assignments(
    task: Any,
    dimensions: Any,
    *,
    resolver=None,
    decision_verifier=None,
    max_assignments: int = 10_000,
) -> dict[str, Any]:
    """Assemble caller-supplied three-day events before development search.

    ``resolver(task_copy, assignment_copy)`` must return exactly the required
    keys in ``_REQUIRED_KEYS`` and may return only the optional keys in
    ``_RESOLVED_KEYS``. It supplies explicit ``plan_context``, ``daily_items``,
    ``entity_kinds``, ``repeat_policy``, and already-created ``record_bindings``.
    No default routes, starts, meals, prices, facts, or evidence are generated.

    Resolver inputs and returned data are isolated and checked for mutation.
    ``diagnostic_inputs`` is forwarded to the underlying allowlisted search
    bridge. The bridge retains every diagnostic gap and cannot emit a verified
    pass under its current contract. A bounded sample is not a complete domain.
    """
    if not callable(resolver):
        result = search_development_assignments(
            task, dimensions, resolver=None, decision_verifier=decision_verifier,
            max_assignments=max_assignments)
        return _label_result(result)

    assembly_rejections = {}

    def assembled_resolver(task_copy, assignment_copy):
        task_before = _canonical_or_none(task_copy)
        assignment_before = _canonical_or_none(assignment_copy)
        try:
            raw = resolver(task_copy, assignment_copy)
        except Exception:
            raise
        if (_canonical_or_none(task_copy) != task_before or
                _canonical_or_none(assignment_copy) != assignment_before):
            # The parent search observes its own isolated inputs changed and
            # converts the assignment to unknown.
            return {"malformed": True}
        if not isinstance(raw, Mapping) or set(raw) - _RESOLVED_KEYS or not _REQUIRED_KEYS <= set(raw):
            return {"malformed": True}
        try:
            source = copy.deepcopy(dict(raw))
            callbacks = source.get("diagnostic_callbacks", {})
            if (not isinstance(callbacks, Mapping) or any(
                    not isinstance(name, str) or not callable(callback)
                    for name, callback in callbacks.items())):
                return {"malformed": True}
            source_data = {key: value for key, value in source.items()
                           if key != "diagnostic_callbacks"}
            before = _canonical_or_none(source_data)
            callback_snapshot = dict(callbacks)
            if before is None:
                return {"malformed": True}
            context = source["plan_context"]
            if not _context_matches_task(task_copy, context):
                plan = None
            else:
                assembled = assemble_strict_plan(
                    copy.deepcopy(context), copy.deepcopy(source["daily_items"]),
                    entity_kinds=copy.deepcopy(source["entity_kinds"]),
                    repeat_policy=copy.deepcopy(source["repeat_policy"]))
                plan = (copy.deepcopy(assembled.get("plan"))
                        if assembled.get("status") == "synthetic_plan_assembled_unverified"
                        else None)
                if plan is None:
                    assignment_key = _canonical_or_none(assignment_copy)
                    if assignment_key is not None:
                        assembly_rejections[assignment_key] = {
                            "reason": assembled.get("reason", "assembly_rejected"),
                            "detail": copy.deepcopy(assembled.get("detail")),
                        }
            if (_canonical_or_none(source_data) != before or
                    set(callbacks) != set(callback_snapshot) or
                    any(callbacks.get(name) is not callback
                        for name, callback in callback_snapshot.items())):
                return {"malformed": True}
            # A failed assembly is deliberately sent as a missing plan; the
            # development diagnostic reports unknown for this assignment.
            result = {
                "plan": plan,
                "plan_context": copy.deepcopy(context),
                "record_bindings": copy.deepcopy(source["record_bindings"]),
                "now": copy.deepcopy(source["now"]),
                "registry": copy.deepcopy(source.get("registry", {})),
                "diagnostic_inputs": copy.deepcopy(source.get("diagnostic_inputs", {})),
                "diagnostic_callbacks": dict(callback_snapshot),
            }
            if (_canonical_or_none(source_data) != before or
                    set(callbacks) != set(callback_snapshot) or
                    any(callbacks.get(name) is not callback
                        for name, callback in callback_snapshot.items())):
                return {"malformed": True}
            return result
        except Exception:
            return {"malformed": True}

    result = search_development_assignments(
        task, dimensions, resolver=assembled_resolver,
        decision_verifier=decision_verifier, max_assignments=max_assignments)
    _apply_assembly_rejections(result, assembly_rejections)
    return _label_result(result)


def _context_matches_task(task, context):
    if not isinstance(task, dict) or not isinstance(context, dict):
        return False
    expected = {"uid": task.get("uid"), "level": task.get("level"),
                "start_city": task.get("start_city"),
                "target_city": task.get("target_city"),
                "start_date": task.get("start_date"), "days": task.get("days"),
                "people_number": task.get("people_number")}
    return (all(strict_snapshot_equal(context.get(key), value) for key, value in expected.items())
            and type(task.get("days")) is int and task.get("days") == 3)


def _label_result(result):
    result = copy.deepcopy(result)
    result.update({
        "label": "engineering_only",
        "adapter": "strict_assembled_search",
        "planner_complete": False,
        "domain_complete": False,
        "explicit_three_day_events_only": True,
        "declared_finite_domain_only": True,
        "full_task_domain_claimed": False,
        "truth_certified": False,
        "execution_confirmed": False,
        "real_world_feasibility_certified": False,
        "global_unsat_claimed": False,
    })
    if not result.get("domain_valid", True):
        result["outcome_state"] = "unknown"
        result["unknown_assignment_count"] = result.get("unknown_assignment_count", 0)
    else:
        result["outcome_state"] = (
            "unknown" if result.get("decision_counts", {}).get("unknown", 0) else "incomplete")
    return result


def _canonical_or_none(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None


def _apply_assembly_rejections(result, assembly_rejections):
    """Keep routine candidate assembly failures out of pipeline diagnostics."""
    if not isinstance(result, dict) or not assembly_rejections:
        return
    for record in result.get("diagnostics", []):
        if not isinstance(record, dict):
            continue
        key = _canonical_or_none(record.get("assignment"))
        rejection = assembly_rejections.get(key)
        if rejection is None:
            continue
        diagnostic = record.get("diagnostic")
        if isinstance(diagnostic, dict):
            axes = diagnostic.get("axes")
            if isinstance(axes, dict):
                axes["pipeline"] = [gap for gap in axes.get("pipeline", [])
                                    if not isinstance(gap, Mapping) or
                                    gap.get("reason") != "plan_missing_or_not_object"]
                axes.setdefault("solver", []).append({
                    "gap_id": "candidate-assembly-rejected",
                    "blocker_class": "solver",
                    "reason": "candidate_assembly_rejected",
                    "required": True,
                    "blocking": True,
                    "repairable": False,
                    "detail": copy.deepcopy(rejection),
                })
            diagnostic["outcome"] = ("adapter_block" if axes.get("adapter")
                                     else "solver_incomplete") if isinstance(axes, dict) else "solver_incomplete"
            diagnostic["candidate_assembly_rejection"] = copy.deepcopy(rejection)
        record["reason"] = "candidate_assembly_rejected"
    for record in result.get("assignments", []):
        if not isinstance(record, dict):
            continue
        key = _canonical_or_none(record.get("assignment"))
        if key in assembly_rejections:
            record["reason"] = "candidate_assembly_rejected"
