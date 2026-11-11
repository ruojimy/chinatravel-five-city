"""Unknown-first bridge from finite assignments to development diagnostics.

This is not a planner. A caller resolver must map each assignment to an
explicit development plan and occurrence bindings. The existing diagnostic's
blocking axes are preserved; only externally reverified, evidence-backed hard
failures can reject an assignment. The current fixed planner/coverage gap makes
assignment pass intentionally unavailable.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .strict_development_orchestrator import diagnose_development_plan
from .strict_finite_plan_search import search_finite_plan_domain


_RESOLVER_KEYS = frozenset(("plan", "plan_context", "record_bindings", "now",
                            "registry", "diagnostic_callbacks",
                            "diagnostic_inputs", "hard_failure_credentials"))
_DIAGNOSTIC_INPUT_KEYS = frozenset(("overnight_boundaries", "meal_coverage", "lodging",
                                    "intercity", "finite_route_domain", "constraint_facts",
                                    "tag_evidence", "cost_aggregation", "business_chain_events"))


def search_development_assignments(
    task: Any,
    dimensions: Any,
    *,
    resolver=None,
    decision_verifier=None,
    max_assignments: int = 10_000,
) -> dict[str, Any]:
    """Search a caller-declared domain through explicit development plans.

    The resolver receives ``(task_copy, assignment_copy)`` and must return a
    mapping with ``plan``, ``plan_context``, ``record_bindings`` and ``now``.
    It may also return ``registry``, ``diagnostic_callbacks``, allowlisted
    ``diagnostic_inputs`` and explicit
    ``hard_failure_credentials``. It must not infer missing plan facts.

    The evaluator never emits pass. A hard failure is only proposed when an
    exact ``field``/``reason`` match exists in the strict diagnostic and the
    resolver supplies proof/evidence references. The independent verifier
    must then recheck the assignment, plan, diagnostic and evidence. All other
    cases remain unknown. The current orchestrator's fixed planner/coverage
    gap is retained and is never interpreted as resolved.
    """
    if not isinstance(task, dict):
        return _blocked("task_not_object")
    if task.get("split") == "holdout" or task.get("purpose") == "holdout":
        return _blocked("holdout_rejected_from_search_orchestrator")
    if task.get("split") != "development" or task.get("purpose") != "development":
        return _blocked("development_task_required")
    try:
        task_snapshot = copy.deepcopy(task)
        task_digest = _sha256(task_snapshot)
    except Exception:
        return _blocked("task_not_canonical_json")

    observed: dict[str, dict[str, Any]] = {}
    audit_records: list[dict[str, Any]] = []

    def evaluate(assignment: dict[str, Any]) -> dict[str, Any]:
        if not callable(resolver):
            audit_records.append({"assignment": copy.deepcopy(assignment),
                                  "state": "unknown", "reason": "plan_resolver_missing"})
            return {"state": "unknown", "reason": "plan_resolver_missing"}
        task_arg, assignment_arg = copy.deepcopy(task_snapshot), copy.deepcopy(assignment)
        task_before, assignment_before = _canonical_or_none(task_arg), _canonical_or_none(assignment_arg)
        try:
            resolved = resolver(task_arg, assignment_arg)
        except Exception as exc:
            audit_records.append({"assignment": copy.deepcopy(assignment), "state": "unknown",
                                  "reason": "plan_resolver_exception",
                                  "error_type": type(exc).__name__})
            return {"state": "unknown", "reason": "plan_resolver_exception"}
        if (_canonical_or_none(task_arg) != task_before or
                _canonical_or_none(assignment_arg) != assignment_before):
            audit_records.append({"assignment": copy.deepcopy(assignment), "state": "unknown",
                                  "reason": "plan_resolver_mutated_input"})
            return {"state": "unknown", "reason": "plan_resolver_mutated_input"}
        if not isinstance(resolved, Mapping) or set(resolved) - _RESOLVER_KEYS:
            audit_records.append({"assignment": copy.deepcopy(assignment), "state": "unknown",
                                  "reason": "plan_resolver_output_malformed"})
            return {"state": "unknown", "reason": "plan_resolver_output_malformed"}
        required = ("plan", "plan_context", "record_bindings", "now")
        if any(key not in resolved for key in required):
            audit_records.append({"assignment": copy.deepcopy(assignment), "state": "unknown",
                                  "reason": "plan_resolver_output_incomplete"})
            return {"state": "unknown", "reason": "plan_resolver_output_incomplete"}
        try:
            resolved_copy = copy.deepcopy(dict(resolved))
            callbacks = resolved_copy.get("diagnostic_callbacks", {})
            if not isinstance(callbacks, Mapping) or any(
                    not isinstance(name, str) or not callable(callback)
                    for name, callback in callbacks.items()):
                raise ValueError("diagnostic_callbacks_malformed")
            inputs = resolved_copy.get("diagnostic_inputs", {})
            if (not isinstance(inputs, Mapping) or set(inputs) - _DIAGNOSTIC_INPUT_KEYS
                    or set(inputs) & set(callbacks)):
                raise ValueError("diagnostic_inputs_malformed")
            resolver_data = {key: value for key, value in resolved_copy.items()
                             if key != "diagnostic_callbacks"}
            resolver_data_before = _canonical_or_none(resolver_data)
            if resolver_data_before is None:
                raise ValueError("resolver_data_not_canonical")
            callback_snapshot = dict(callbacks)
            callback_manifest = [
                {"name": name,
                 "module": getattr(callback, "__module__", None),
                 "qualname": getattr(callback, "__qualname__", None)}
                for name, callback in sorted(callbacks.items())]
            # Each diagnostic argument is an isolated copy; snapshots never enter
            # the diagnostic bridge and therefore remain suitable for hashing.
            diagnostic_task = copy.deepcopy(task_snapshot)
            diagnostic_plan = copy.deepcopy(resolver_data["plan"])
            diagnostic_context = copy.deepcopy(resolver_data["plan_context"])
            diagnostic_bindings = copy.deepcopy(resolver_data["record_bindings"])
            diagnostic_now = copy.deepcopy(resolver_data["now"])
            diagnostic_registry = copy.deepcopy(resolver_data.get("registry", {}))
            diagnostic_args = {"task": diagnostic_task, "plan": diagnostic_plan,
                               "plan_context": diagnostic_context,
                               "record_bindings": diagnostic_bindings,
                               "now": diagnostic_now, "registry": diagnostic_registry}
            diagnostic_inputs = copy.deepcopy(dict(inputs))
            diagnostic_args['diagnostic_inputs'] = diagnostic_inputs
            diagnostic_args_before = _canonical_or_none(diagnostic_args)
            if diagnostic_args_before is None:
                raise ValueError("resolver_data_not_canonical")
            diagnostic = diagnose_development_plan(
                diagnostic_task, diagnostic_plan, plan_context=diagnostic_context,
                record_bindings=diagnostic_bindings, now=diagnostic_now,
                registry=diagnostic_registry, **diagnostic_inputs, **dict(callback_snapshot))
            if _canonical_or_none(diagnostic_args) != diagnostic_args_before:
                raise ValueError("diagnostic_input_mutated")
            after_data = _canonical_or_none(resolver_data)
            if after_data != resolver_data_before:
                raise ValueError("diagnostic_input_mutated")
            if set(callbacks) != set(callback_snapshot) or any(
                    callbacks.get(name) is not callback
                    for name, callback in callback_snapshot.items()):
                raise ValueError("diagnostic_callbacks_mutated")
            if _canonical_or_none(diagnostic) is None:
                raise ValueError("diagnostic_not_canonical")
        except Exception as exc:
            reason = (str(exc) if str(exc) in {
                "diagnostic_input_mutated", "diagnostic_callbacks_mutated",
                "diagnostic_callbacks_malformed", "diagnostic_inputs_malformed", "resolver_data_not_canonical",
                "diagnostic_not_canonical"} else "development_diagnostic_exception")
            audit_records.append({"assignment": copy.deepcopy(assignment), "state": "unknown",
                                  "reason": reason, "error_type": type(exc).__name__})
            return {"state": "unknown", "reason": reason}

        failure = _matching_hard_failure(diagnostic, resolved_copy.get("hard_failure_credentials"))
        assignment_key = _canonical_or_none(assignment)
        diagnostic_snapshot = copy.deepcopy(diagnostic)
        record = {"assignment": copy.deepcopy(assignment), "state": "unknown",
                  "diagnostic": diagnostic_snapshot,
                  "reason": "strict_diagnostic_unresolved_or_fixed_planner_gap"}
        if assignment_key is None:
            audit_records.append(record)
            return {"state": "unknown", "reason": "assignment_not_canonical"}
        audit = {
            "schema": "strict-search-audit-v1",
            "task": copy.deepcopy(task_snapshot), "task_sha256": task_digest,
            "assignment": copy.deepcopy(assignment),
            "assignment_sha256": _sha256(assignment),
            "plan": copy.deepcopy(resolver_data["plan"]),
            "plan_context": copy.deepcopy(resolver_data["plan_context"]),
            "record_bindings": copy.deepcopy(resolver_data["record_bindings"]),
            "now": copy.deepcopy(resolver_data["now"]),
            "registry": copy.deepcopy(resolver_data.get("registry", {})),
            "diagnostic_inputs": copy.deepcopy(resolver_data.get("diagnostic_inputs", {})),
            "hard_failure_credentials": copy.deepcopy(
                resolver_data.get("hard_failure_credentials")),
            "resolver_data_sha256": _sha256(resolver_data),
            "diagnostic_callback_manifest": callback_manifest,
            "diagnostic": diagnostic_snapshot,
            "diagnostic_sha256": _sha256(diagnostic_snapshot),
        }
        audit_digest = _sha256(audit)
        observed[assignment_key] = {"audit": copy.deepcopy(audit),
                                    "audit_sha256": audit_digest,
                                    "diagnostic": diagnostic_snapshot,
                                    "failure": copy.deepcopy(failure),
                                    "task_sha256": task_digest}
        if failure is None:
            audit_records.append(record)
            return {"state": "unknown", "reason": record["reason"]}

        proof_id = failure["proof_id"]
        evidence_ids = failure["evidence_ids"]
        proposed = {
            "state": "fail",
            "reason": "externally_reverifiable_hard_failure_proposed",
            "proof_id": proof_id,
            "proof_scope": failure["proof_scope"],
            "evidence_ids": evidence_ids,
            "task_sha256": task_digest,
            "assignment_sha256": _sha256(assignment),
            "failure": copy.deepcopy(failure["failure"]),
            "diagnostic": diagnostic_snapshot,
            "audit": copy.deepcopy(audit),
            "audit_sha256": audit_digest,
        }
        record.update({"state": "fail_proposed", "reason": proposed["reason"],
                       "failure": copy.deepcopy(failure["failure"]),
                       "proof_id": proof_id, "evidence_ids": evidence_ids})
        audit_records.append(record)
        return proposed

    def verify(assignment: dict[str, Any], decision: dict[str, Any]) -> bool:
        if not callable(decision_verifier):
            return False
        key = _canonical_or_none(assignment)
        entry = observed.get(key) if key is not None else None
        if not isinstance(entry, dict) or decision.get("state") != "fail":
            return False
        expected_failure = entry.get("failure")
        if not isinstance(expected_failure, dict):
            return False
        expected_audit = entry.get("audit")
        if (not isinstance(expected_audit, dict) or
                _canonical_or_none(decision.get("audit")) != _canonical_or_none(expected_audit) or
                decision.get("audit_sha256") != entry.get("audit_sha256") or
                _sha256(expected_audit) != entry.get("audit_sha256") or
                _canonical_or_none(expected_audit.get("task")) != _canonical_or_none(task_snapshot) or
                _canonical_or_none(expected_audit.get("assignment")) != _canonical_or_none(assignment) or
                expected_audit.get("task_sha256") != task_digest or
                expected_audit.get("assignment_sha256") != _sha256(assignment) or
                decision.get("task_sha256") != task_digest or
                decision.get("assignment_sha256") != _sha256(assignment) or
                _canonical_or_none(decision.get("diagnostic")) !=
                _canonical_or_none(entry.get("diagnostic")) or
                _canonical_or_none(decision.get("failure")) !=
                _canonical_or_none(expected_failure.get("failure")) or
                decision.get("proof_id") != expected_failure.get("proof_id") or
                decision.get("proof_scope") != expected_failure.get("proof_scope") or
                _canonical_or_none(decision.get("evidence_ids")) !=
                _canonical_or_none(expected_failure.get("evidence_ids"))):
            return False
        task_arg = copy.deepcopy(task_snapshot)
        assignment_arg, decision_arg = copy.deepcopy(assignment), copy.deepcopy(decision)
        task_before = _canonical_or_none(task_arg)
        assignment_before = _canonical_or_none(assignment_arg)
        decision_before = _canonical_or_none(decision_arg)
        try:
            accepted = decision_verifier(task_arg, assignment_arg, decision_arg)
        except Exception:
            return False
        return (accepted is True and
                _canonical_or_none(task_arg) == task_before and
                _canonical_or_none(assignment_arg) == assignment_before and
                _canonical_or_none(decision_arg) == decision_before)

    result = search_finite_plan_domain(
        dimensions, evaluator=evaluate,
        decision_verifier=verify if callable(decision_verifier) else None,
        max_assignments=max_assignments,
    )
    for record, outcome in zip(audit_records, result.get("assignments", [])):
        if record.get("state") == "fail_proposed":
            record["state"] = "fail_verified" if outcome.get("state") == "fail" else "unknown"
            if outcome.get("state") != "fail":
                record["reason"] = outcome.get("reason", "independent_decision_verification_failed")
    result["diagnostics"] = audit_records
    result.update({"label": "engineering_only", "planner_integrated": False,
                   "complete_planner_integrated": False,
                   "formal_score": None, "frozen": False,
                   "real_world_feasibility_certified": False,
                   "truth_certified": False, "execution_confirmed": False})
    if result.get("status") == "bounded_candidate_found":
        # This prototype's evaluator has no pass branch; guard future changes.
        result["status"] = "solver_incomplete"
        result["reason"] = "pass_not_supported_by_current_development_diagnostic_contract"
        result["decision_counts"]["unknown"] += result["decision_counts"]["pass"]
        result["decision_counts"]["pass"] = 0
        result["candidate_count"] = 0
        result["unknown_assignment_count"] = result["decision_counts"]["unknown"]
        for item in result.get("assignments", []):
            if item.get("state") == "pass":
                item["state"] = "unknown"
                item["reason"] = "pass_not_supported_by_current_development_diagnostic_contract"
    result["global_unsat_claimed"] = False
    return result


def _matching_hard_failure(diagnostic: Any, credentials: Any):
    if not isinstance(diagnostic, dict) or not isinstance(credentials, list):
        return None
    failures = diagnostic.get("hard_failures")
    if not isinstance(failures, list):
        return None
    for failure in failures:
        if (not isinstance(failure, dict) or failure.get("state") != "fail" or
                not isinstance(failure.get("field"), str) or
                not isinstance(failure.get("reason"), str)):
            continue
        matches = [credential for credential in credentials
                   if isinstance(credential, dict) and
                   credential.get("field") == failure["field"] and
                   credential.get("reason") == failure["reason"]]
        if len(matches) != 1:
            continue
        credential = matches[0]
        proof_id, proof_scope, evidence_ids = (credential.get("proof_id"),
                                                credential.get("proof_scope"),
                                                credential.get("evidence_ids"))
        if (not isinstance(proof_id, str) or not proof_id.strip() or
                not isinstance(proof_scope, str) or not proof_scope.strip() or
                not isinstance(evidence_ids, list) or not evidence_ids or
                any(not isinstance(value, str) or not value.strip() for value in evidence_ids) or
                len(set(evidence_ids)) != len(evidence_ids)):
            continue
        return {"failure": copy.deepcopy(failure), "proof_id": proof_id,
                "proof_scope": proof_scope, "evidence_ids": list(evidence_ids)}
    return None


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _canonical_or_none(value: Any) -> str | None:
    try:
        return _canonical(value)
    except (TypeError, ValueError, RecursionError):
        return None


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "solver_incomplete", "reason": reason,
            "domain_valid": False, "declared_assignment_count": None,
            "enumerated_assignment_count": 0, "domain_enumeration_complete": False,
            "decision_counts": {"pass": 0, "fail": 0, "unknown": 0},
            "candidate_count": 0, "unknown_assignment_count": 0,
            "global_unsat_claimed": False, "assignments": [], "diagnostics": [],
            "label": "engineering_only", "planner_integrated": False,
            "complete_planner_integrated": False, "formal_score": None,
            "frozen": False, "real_world_feasibility_certified": False,
            "truth_certified": False, "execution_confirmed": False}
