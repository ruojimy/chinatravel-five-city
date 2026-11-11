"""Strict, offline route evidence and finite-domain diagnostics.

This module intentionally does not fetch routes. A route observation is usable
only for its exact ordered endpoints, entrances, coordinate system, mode, date,
and departure time, and only until its explicit expiry. Durations and limits
must be nonnegative integers or canonical decimal strings; floats may have
already lost the source's original precision and remain unknown.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import product
import math
import json
import copy
from .route_context_ttl import verify_route_context_ttl
from .strict_snapshot import strict_snapshot_equal as _strict_snapshot_equal
from .strict_money import exact_money as _exact_duration

CONTEXT_FIELDS = (
    "origin", "destination", "origin_entry", "destination_entry",
    "coord_system", "mode", "travel_date", "departure_at",
)
MAX_ROUTE_ASSIGNMENTS = 10_000
MAX_ROUTE_EVIDENCE = 20_000
MAX_ROUTE_EVIDENCE_PER_CONTEXT = 64
MAX_ROUTE_LEGS = 50_000


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def route_evidence_gate(requirement, evidence, *, now, evidence_verifier=None):
    """Return eligibility; ``now`` is the planning clock, not an observation time.

    For a frozen historical simulation the caller must supply the simulated
    clock. A departure before that clock cannot be used as an upcoming route.
    Caller-supplied verification flags are ignored.
    """
    reasons = []
    if not isinstance(requirement, dict) or not isinstance(evidence, dict):
        return {"usable": False, "reasons": ["malformed_route_requirement_or_evidence"], "duration_minutes": None}
    # Applicability and the maximum freshness window are separate from source
    # verification; both must pass before a route can be used.
    reasons.extend(verify_route_context_ttl(requirement, evidence, now=now)["reasons"])
    reqctx = requirement.get("context") or {}
    evctx = evidence.get("context") or {}
    if not isinstance(reqctx, dict) or not isinstance(evctx, dict):
        return {"usable": False, "reasons": ["malformed_route_context"], "duration_minutes": None}
    expected_context_keys = set(CONTEXT_FIELDS)
    if set(reqctx) != expected_context_keys:
        reasons.append("route_request_context_keys_missing_or_unsupported")
    if set(evctx) != expected_context_keys:
        reasons.append("route_evidence_context_keys_missing_or_unsupported")
    missing = [k for k in CONTEXT_FIELDS if not reqctx.get(k)]
    if missing:
        reasons.append("route_context_missing:" + ",".join(missing))
    for key in CONTEXT_FIELDS:
        if reqctx.get(key) and evctx.get(key) != reqctx[key]:
            reasons.append("route_context_mismatch:" + key)
    departure = reqctx.get('departure_at')
    try:
        departure_local = datetime.fromisoformat(departure.replace('Z', '+00:00'))
        travel_date = date.fromisoformat(reqctx.get('travel_date', ''))
        if departure_local.tzinfo is None or departure_local.date() != travel_date:
            reasons.append('route_departure_date_mismatch')
    except (ValueError, TypeError, AttributeError):
        reasons.append('route_departure_date_invalid')
    if reqctx.get('coord_system') not in ('GCJ02', 'WGS84'):
        reasons.append('route_coordinate_system_unknown')
    observed = _time(evidence.get("observed_at"))
    expires = _time(evidence.get("valid_until"))
    at = _time(now)
    departure_at = _time(reqctx.get("departure_at"))
    if departure_at is not None and at is not None and departure_at < at:
        reasons.append("route_departure_already_elapsed")
    if not observed or not expires or not at:
        reasons.append("route_clock_missing_or_invalid")
    else:
        if observed > at:
            reasons.append("route_observation_from_future")
        if at >= expires:
            reasons.append("route_evidence_expired")
        if expires <= observed:
            reasons.append("route_ttl_nonpositive")
    value = evidence.get("duration_minutes")
    if _exact_duration(value) is None:
        reasons.append("route_duration_invalid")
    if evidence.get("unit") != "minutes":
        reasons.append("route_duration_unit_invalid")
    # This callback must independently validate provider/source identity,
    # preserved raw response, permission/licence, and response-to-value binding.
    # A self-asserted flag in evidence is never a substitute.
    if not callable(evidence_verifier):
        reasons.append("independent_evidence_verifier_required")
    else:
        try:
            req_before, ev_before = copy.deepcopy(requirement), copy.deepcopy(evidence)
            req_copy, ev_copy = copy.deepcopy(req_before), copy.deepcopy(ev_before)
            if (evidence_verifier(req_copy, ev_copy) is not True or
                    not _strict_snapshot_equal(req_copy, req_before) or
                    not _strict_snapshot_equal(ev_copy, ev_before) or
                    not _strict_snapshot_equal(requirement, req_before) or
                    not _strict_snapshot_equal(evidence, ev_before)):
                reasons.append("independent_evidence_verification_failed")
        except Exception:
            reasons.append("independent_evidence_verification_error")
    return {"usable": not reasons, "reasons": sorted(set(reasons)),
            "duration_minutes": value if not reasons else None}


def solve_finite_route_domain(*, dimensions, candidates, evidence, now, evidence_verifier=None):
    """Exhaustively assess a finite Cartesian domain of route alternatives.

    `dimensions` maps choice names to finite, nonempty lists. Each candidate is
    keyed by `choices` (a full assignment) and contains legs. Each leg has an
    exact `context` and a positive/zero `max_duration_minutes`. Evidence is
    matched by exact context; no asserted search-complete/validated flag is
    consumed. Even exhaustive candidate failures remain solver_incomplete until
    a separate verifier has independently checked a proof.
    """
    if (not isinstance(dimensions, dict) or not dimensions
            or any(not isinstance(n, str) or not n.strip() for n in dimensions)
            or any(not isinstance(v, list) or not v for v in dimensions.values())):
        return {"status": "context_incomplete", "reason": "finite_nonempty_dimensions_required"}
    # Restrict choices to JSON scalars to keep domain equality deterministic;
    # duplicates and malformed/unhashable values cannot inflate coverage.
    try:
        for values in dimensions.values():
            if any(type(v) not in (str, bool, int, float) or
                   (type(v) is str and not v.strip()) or
                   (type(v) is float and not math.isfinite(v)) for v in values):
                raise ValueError("non-scalar domain value")
            encoded = [json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False) for v in values]
            for item in encoded:
                item.encode('utf-8', errors='strict')
            if len(set(encoded)) != len(encoded) or len(set(values)) != len(values):
                return {"status": "context_incomplete", "reason": "duplicate_domain_values"}
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return {"status": "context_incomplete", "reason": "invalid_domain_values"}
    names = sorted(dimensions)
    if math.prod(len(dimensions[name]) for name in names) > MAX_ROUTE_ASSIGNMENTS:
        return {"status": "solver_incomplete", "reason": "route_domain_assignment_limit_exceeded",
                "execution_confirmed": False}
    if (not isinstance(candidates, list) or not isinstance(evidence, list) or
            len(candidates) > MAX_ROUTE_ASSIGNMENTS or len(evidence) > MAX_ROUTE_EVIDENCE or
            sum(len(c.get('legs', [])) for c in candidates
                if isinstance(c, dict) and isinstance(c.get('legs'), list)) > MAX_ROUTE_LEGS):
        return {"status": "solver_incomplete", "reason": "route_input_limit_or_shape_invalid",
                "execution_confirmed": False}
    try:
        protected_inputs = (dimensions, candidates, evidence)
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return {"status": "solver_incomplete", "reason": "route_inputs_cannot_be_snapshotted",
                "execution_confirmed": False}
    def assignment_key(choices):
        # JSON encoding preserves distinctions such as true versus 1 and
        # avoids hashing malformed/unhashable participant values.
        return tuple((n, json.dumps(choices[n], sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':'))) for n in names)
    expected = [dict(zip(names, vals)) for vals in product(*(dimensions[n] for n in names))]
    expected_keys = [assignment_key(c) for c in expected]
    expected_key_set = set(expected_keys)
    by_key = {}
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        choices = c.get("choices") or {}
        if not isinstance(choices, dict) or set(choices) != set(names):
            continue
        try:
            k = assignment_key(choices)
        except (TypeError, ValueError, KeyError, RecursionError):
            continue
        if k not in expected_key_set:
            continue
        by_key.setdefault(k, []).append(c)
    if len(by_key) != len(expected) or any(len(by_key.get(k, [])) != 1 for k in expected_keys):
        return {"status": "solver_incomplete", "reason": "candidate_domain_not_exhaustively_covered",
                "expected_assignments": len(expected), "covered_assignments": len(by_key)}

    evidence_index = {}
    for e in evidence if isinstance(evidence, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("context"), dict):
            continue
        ctx = e.get("context") or {}
        try:
            ctx_key = json.dumps([ctx.get(k) for k in CONTEXT_FIELDS], sort_keys=True,
                                 ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        except (TypeError, ValueError, RecursionError):
            continue
        evidence_index.setdefault(ctx_key, []).append(e)
        if len(evidence_index[ctx_key]) > MAX_ROUTE_EVIDENCE_PER_CONTEXT:
            return {"status": "solver_incomplete", "reason": "route_evidence_per_context_limit_exceeded",
                    "execution_confirmed": False}
    outcomes = []
    unknown = False
    for assignment in expected:
        candidate = by_key[assignment_key(assignment)][0]
        leg_durations = []
        leg_blocked = False
        violated = False
        legs = candidate.get("legs")
        if not isinstance(legs, list) or not legs:
            unknown = True
            outcomes.append({"choices": assignment, "status": "solver_incomplete", "reason": "candidate_legs_missing"})
            continue
        for leg in legs:
            if not isinstance(leg, dict):
                leg_blocked = True
                continue
            ctx = leg.get("context") or {}
            if not isinstance(ctx, dict):
                leg_blocked = True
                continue
            req = {"context": ctx}
            usable_durations = []
            try:
                ctx_key = json.dumps([ctx.get(k) for k in CONTEXT_FIELDS], sort_keys=True,
                                     ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            except (TypeError, ValueError, RecursionError):
                leg_blocked = True
                continue
            for e in evidence_index.get(ctx_key, []):
                checked = route_evidence_gate(req, e, now=now, evidence_verifier=evidence_verifier)
                if not _strict_snapshot_equal(protected_inputs, protected_snapshot):
                    return {"status": "solver_incomplete", "reason": "route_original_inputs_mutated",
                            "execution_confirmed": False}
                if checked["usable"]:
                    usable_durations.append(checked["duration_minutes"])
            limit = leg.get("max_duration_minutes")
            exact_durations = [_exact_duration(value) for value in usable_durations]
            exact_limit = _exact_duration(limit)
            if (not usable_durations or None in exact_durations or
                    len(set(exact_durations)) != 1 or exact_limit is None):
                leg_blocked = True
                continue
            passed = usable_durations[0]
            leg_durations.append(passed)
            if exact_durations[0] > exact_limit:
                violated = True
        if leg_blocked:
            unknown = True
            outcomes.append({"choices": assignment, "status": "solver_incomplete", "reason": "eligible_route_evidence_missing"})
        elif violated:
            outcomes.append({"choices": assignment, "status": "candidate_constraint_fail",
                             "durations_minutes": leg_durations})
        else:
            outcomes.append({"choices": assignment, "status": "candidate_feasible",
                             "durations_minutes": leg_durations})

    if any(o["status"] == "candidate_feasible" for o in outcomes):
        status = "candidate_feasible"
    elif unknown:
        status = "solver_incomplete"
    else:
        # Enumeration is performed by this same implementation, not an
        # independent proof verifier. Do not promote it to proven infeasible.
        status = "solver_incomplete"
    return {"status": status, "domain_size": len(expected), "checked_assignments": len(outcomes),
            "outcomes": outcomes, "proof_scope": None,
            "reason": "independent_infeasibility_verifier_required" if not unknown and all(o["status"] == "candidate_constraint_fail" for o in outcomes) else None,
            "execution_confirmed": False}
