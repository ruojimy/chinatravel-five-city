"""Small bounded finite-domain search with fail-closed three-valued decisions.

This is an engineering control plane, not a trip planner. It enumerates only
the caller's JSON domain; it cannot establish real-world evidence or that the
declared inventory is complete.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .strict_finite_plan_search import search_finite_plan_domain


def search_declared_domain(dimensions: Any, *, evaluator=None,
                           decision_verifier=None, domain_completeness_verifier=None,
                           max_assignments: int = 10_000) -> dict[str, Any]:
    """Exhaustively evaluate an explicit Cartesian domain under a hard cap.

    Evaluator returns ``{state: pass|fail|unknown, reason, proof_id,
    proof_scope, evidence_ids}``. Pass/fail count only if an independent
    decision verifier returns literal True without mutating its inputs.
    ``domain_completeness_verifier`` independently attests that the supplied
    domain is complete; its callback contract is still a caller-owned trust
    boundary. Unknowns are never treated as failures.
    """
    try:
        frozen = copy.deepcopy(dimensions)
        digest = hashlib.sha256(_canonical(frozen).encode("utf-8")).hexdigest()
    except Exception:
        return _result("solver_incomplete", "domain_not_canonical_json")

    audit = {"domain_sha256": digest, "completeness_verified": False,
             "completeness_reason": "domain_completeness_verifier_missing"}
    if callable(domain_completeness_verifier):
        arg = copy.deepcopy(frozen)
        before = _canonical_or_none(arg)
        try:
            accepted = domain_completeness_verifier(arg, digest)
        except Exception:
            accepted = False
        if before is None or _canonical_or_none(arg) != before:
            audit["completeness_reason"] = "domain_completeness_verifier_mutated_input"
        elif accepted is True:
            audit["completeness_verified"] = True
            audit["completeness_reason"] = None
        else:
            audit["completeness_reason"] = "domain_completeness_unverified"

    result = search_finite_plan_domain(
        frozen, evaluator=evaluator, decision_verifier=decision_verifier,
        max_assignments=max_assignments)
    result["domain_audit"] = audit
    result.update({"label": "engineering_only", "planner_integrated": False,
                   "three_day_plan_claimed": False,
                   "real_world_evidence_claimed": False,
                   "truth_certified": False, "execution_confirmed": False})
    if result.get("candidate_count", 0):
        result["status"] = "candidate_found_under_declared_domain"
        result["reason"] = "verified_candidate_within_supplied_domain"
    else:
        result["status"] = "solver_incomplete"
        # The underlying verifier authenticates a decision but its generic
        # fail state does not establish that a hard constraint was violated.
        # A separate hard-failure and coverage certificate is still needed.
        if result.get("decision_counts", {}).get("fail", 0):
            result["reason"] = "hard_failure_coverage_not_independently_certified"
    # Keep the legacy global flag false: even a complete declared domain is
    # not a claim about the user's full travel problem.
    result["global_unsat_claimed"] = False
    result["domain_limited_no_candidate_certified"] = False
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _canonical_or_none(value: Any):
    try:
        return _canonical(value)
    except (TypeError, ValueError, RecursionError):
        return None


def _result(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "domain_valid": False,
            "declared_assignment_count": None, "enumerated_assignment_count": 0,
            "domain_enumeration_complete": False,
            "decision_counts": {"pass": 0, "fail": 0, "unknown": 0},
            "candidate_count": 0, "unknown_assignment_count": 0,
            "global_unsat_claimed": False, "real_world_feasibility_certified": False,
            "truth_certified": False, "execution_confirmed": False,
            "label": "engineering_only", "planner_integrated": False,
            "three_day_plan_claimed": False, "real_world_evidence_claimed": False}
