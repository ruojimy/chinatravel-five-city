"""Bounded finite-domain search control plane; it does not build plans.

The evaluator and decision verifier are trusted integration boundaries. The
evaluator proposes a three-valued decision and credentials; a separate
decision verifier must independently validate any pass/fail claim. Credentials
alone never establish validity. This module checks the callback contract,
bounds and enumerates the declared domain, but does not validate real-world
evidence or prove domain completeness itself.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
from collections.abc import Mapping
from typing import Any
from .strict_scope import identifier_is_known


_MAX_ASSIGNMENTS = 10_000
_MAX_DIMENSIONS = 32
_MAX_VALUES_PER_DIMENSION = 10_000
_MAX_VALUE_DEPTH = 32
_MAX_VALUE_CHARS = 16_384
_MAX_TOTAL_INPUT_CHARS = 2_000_000


def search_finite_plan_domain(
    dimensions: Any,
    *,
    evaluator=None,
    decision_verifier=None,
    max_assignments: int = _MAX_ASSIGNMENTS,
) -> dict[str, Any]:
    """Enumerate an explicit Cartesian domain and preserve three-valued results.

    ``dimensions`` maps non-empty variable names to non-empty lists of JSON
    values. The evaluator receives a deep-copied assignment and returns either
    ``{"state": "unknown", "reason": ...}`` or a pass/fail decision carrying
    ``proof_id``, ``proof_scope`` and a non-empty ``evidence_ids`` list. A
    separate ``decision_verifier(assignment_copy, decision_copy)`` must return
    literal ``True`` without mutating either copy before pass/fail is counted.
    Its independence and evidence review remain a caller-owned trust boundary.

    A returned candidate is only bounded to this exact declared domain. All
    fail results deliberately remain ``solver_incomplete`` because this
    control plane has no independent global-unsatisfiability proof mechanism.
    """
    normalized, error = _validate_domain(dimensions, max_assignments)
    if error:
        return _incomplete(error, domain_valid=False)
    original_domain = _canonical_or_none(dimensions)
    if original_domain is None:
        return _incomplete("domain_not_canonical", domain_valid=False)

    names = sorted(normalized)
    values = [normalized[name] for name in names]
    assignments = []
    counts = {"pass": 0, "fail": 0, "unknown": 0}
    for product in itertools.product(*values):
        assignment = dict(zip(names, product))
        outcome = _evaluate_one(assignment, evaluator, decision_verifier)
        if _canonical_or_none(dimensions) != original_domain:
            return _incomplete("domain_original_input_mutated", domain_valid=False)
        counts[outcome["state"]] += 1
        assignments.append({"assignment": copy.deepcopy(assignment), **outcome})

    candidate_count = counts["pass"]
    result = {
        "status": "bounded_candidate_found" if candidate_count else "solver_incomplete",
        "reason": ("one_or_more_bounded_candidates_found" if candidate_count else
                   "all_enumerated_assignments_rejected_but_global_unsat_unproved"
                   if counts["unknown"] == 0 else "no_verified_candidate_and_unknown_assignments_remain"),
        "dimensions": names,
        "declared_assignment_count": math.prod(len(normalized[name]) for name in names),
        "enumerated_assignment_count": len(assignments),
        "domain_enumeration_complete": True,
        "decision_counts": counts,
        "candidate_count": candidate_count,
        "unknown_assignment_count": counts["unknown"],
        "global_unsat_claimed": False,
        "real_world_feasibility_certified": False,
        "truth_certified": False,
        "execution_confirmed": False,
        "assignments": assignments,
    }
    return result


def _evaluate_one(assignment: dict[str, Any], evaluator: Any,
                  decision_verifier: Any) -> dict[str, Any]:
    if not callable(evaluator):
        return {"state": "unknown", "reason": "independent_evaluator_missing"}
    snapshot = copy.deepcopy(assignment)
    supplied = copy.deepcopy(assignment)
    try:
        decision = evaluator(supplied)
    except Exception as exc:  # A verifier failure is unknown, never a pass/fail.
        return {"state": "unknown", "reason": "evaluator_exception",
                "detail": {"error_type": type(exc).__name__}}
    if _canonical_or_none(supplied) != _canonical_or_none(snapshot):
        return {"state": "unknown", "reason": "evaluator_mutated_assignment"}
    if not isinstance(decision, Mapping):
        return {"state": "unknown", "reason": "evaluator_decision_malformed"}
    state, reason = decision.get("state"), decision.get("reason")
    if state not in ("pass", "fail", "unknown"):
        return {"state": "unknown", "reason": "evaluator_state_invalid"}
    if not isinstance(reason, str) or not reason.strip():
        return {"state": "unknown", "reason": "evaluator_reason_missing"}
    if state == "unknown":
        return {"state": "unknown", "reason": reason}

    proof_id, proof_scope, evidence_ids = (decision.get("proof_id"),
                                           decision.get("proof_scope"),
                                           decision.get("evidence_ids"))
    if (not identifier_is_known(proof_id) or
            not identifier_is_known(proof_scope) or
            not isinstance(evidence_ids, list) or not evidence_ids or
            any(not identifier_is_known(item) for item in evidence_ids) or
            len(set(evidence_ids)) != len(evidence_ids)):
        return {"state": "unknown", "reason": "evaluator_proof_credentials_missing_or_invalid"}
    if not callable(decision_verifier):
        return {"state": "unknown", "reason": "independent_decision_verifier_missing"}
    try:
        assignment_copy = copy.deepcopy(snapshot)
        decision_copy = copy.deepcopy(dict(decision))
        original_decision = _canonical_or_none(dict(decision))
        assignment_before = _canonical_or_none(assignment_copy)
        decision_before = _canonical_or_none(decision_copy)
        if assignment_before is None or decision_before is None or original_decision is None:
            return {"state": "unknown", "reason": "decision_verifier_input_not_canonical"}
        verified = decision_verifier(assignment_copy, decision_copy)
    except Exception as exc:
        return {"state": "unknown", "reason": "decision_verifier_exception",
                "detail": {"error_type": type(exc).__name__}}
    if (_canonical_or_none(assignment_copy) != assignment_before or
            _canonical_or_none(decision_copy) != decision_before or
            _canonical_or_none(dict(decision)) != original_decision):
        return {"state": "unknown", "reason": "decision_verifier_mutated_input"}
    if verified is not True:
        return {"state": "unknown", "reason": "independent_decision_verification_failed"}
    return {"state": state, "reason": reason,
            "proof_id": proof_id, "proof_scope": proof_scope,
            "evidence_ids": list(evidence_ids)}


def _canonical_or_none(value: Any) -> str | None:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
        result.encode('utf-8', errors='strict')
        return result
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None


def _validate_domain(dimensions: Any, max_assignments: Any):
    if (not isinstance(dimensions, dict) or not dimensions or
            len(dimensions) > _MAX_DIMENSIONS):
        return None, "domain_missing_malformed_or_too_many_dimensions"
    if type(max_assignments) is not int or not 1 <= max_assignments <= _MAX_ASSIGNMENTS:
        return None, "assignment_limit_invalid"
    normalized = {}
    product_size = 1
    total_chars = 0
    for name, domain in dimensions.items():
        if not isinstance(name, str) or not name.strip():
            return None, "dimension_name_invalid"
        if (not isinstance(domain, list) or not domain or
                len(domain) > _MAX_VALUES_PER_DIMENSION):
            return None, "dimension_domain_empty_or_malformed"
        encoded_values = []
        for value in domain:
            error = _validate_value(value, set(), depth=0)
            if error:
                return None, error
            try:
                encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError, RecursionError):
                return None, "domain_value_not_canonical_json"
            if len(encoded) > _MAX_VALUE_CHARS:
                return None, "domain_value_too_large"
            total_chars += len(encoded)
            if total_chars > _MAX_TOTAL_INPUT_CHARS:
                return None, "domain_input_too_large"
            encoded_values.append(encoded)
        if len(set(encoded_values)) != len(encoded_values):
            return None, "duplicate_domain_value"
        product_size *= len(domain)
        if product_size > max_assignments:
            return None, "domain_limit_exceeded"
        normalized[name] = copy.deepcopy(domain)
    return normalized, None


def _validate_value(value: Any, ancestors: set[int], *, depth: int) -> str | None:
    if depth > _MAX_VALUE_DEPTH:
        return "domain_value_too_deep"
    if value is None:
        return "domain_value_null_not_allowed"
    if isinstance(value, str):
        try:
            value.encode('utf-8', errors='strict')
        except UnicodeError:
            return "domain_value_not_utf8"
        return None if value.strip() else "domain_value_empty_string"
    if type(value) in (bool, int):
        return None
    if type(value) is float:
        return None if math.isfinite(value) else "domain_value_nonfinite_number"
    if isinstance(value, list):
        if not value:
            return "domain_value_empty_list"
        ident = id(value)
        if ident in ancestors:
            return "domain_value_cycle"
        ancestors.add(ident)
        try:
            for item in value:
                error = _validate_value(item, ancestors, depth=depth + 1)
                if error:
                    return error
        finally:
            ancestors.remove(ident)
        return None
    if isinstance(value, dict):
        if not value:
            return "domain_value_empty_object"
        ident = id(value)
        if ident in ancestors:
            return "domain_value_cycle"
        ancestors.add(ident)
        try:
            for key, item in value.items():
                if not isinstance(key, str) or not key.strip():
                    return "domain_object_key_invalid"
                error = _validate_value(item, ancestors, depth=depth + 1)
                if error:
                    return error
        finally:
            ancestors.remove(ident)
        return None
    return "domain_value_type_unsupported"


def _incomplete(reason: str, *, domain_valid: bool) -> dict[str, Any]:
    return {
        "status": "solver_incomplete",
        "reason": reason,
        "domain_valid": domain_valid,
        "declared_assignment_count": None,
        "enumerated_assignment_count": 0,
        "domain_enumeration_complete": False,
        "decision_counts": {"pass": 0, "fail": 0, "unknown": 0},
        "candidate_count": 0,
        "unknown_assignment_count": 0,
        "global_unsat_claimed": False,
        "real_world_feasibility_certified": False,
        "truth_certified": False,
        "execution_confirmed": False,
        "assignments": [],
    }
