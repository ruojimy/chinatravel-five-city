"""Evidence-gated continuity across an overnight stay.

This component checks only an explicitly supplied day boundary and scoped
lodging quote. It does not infer missing endpoints, route feasibility, or a
complete itinerary. Caller claims and ``verified`` flags are never trusted.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any

from .strict_lodging import check_lodging
from .strict_scope import identifier_is_known
from .strict_snapshot import strict_snapshot_equal


_BOUNDARY_KEYS = frozenset({"previous_day", "next_day", "last_endpoint",
                            "first_endpoint", "lodging_requirement",
                            "lodging_claim", "lodging_entrance_id"})
_ENDPOINT_KEYS = frozenset({"entity_id", "entrance_id", "datetime"})


def check_overnight_continuity(boundaries: Any, *, fact_verifier=None,
                               lodging_claim_verifier=None) -> dict[str, Any]:
    """Check explicit adjacent-day endpoint continuity through lodging.

    Each boundary carries ISO dates, the last endpoint on the earlier day,
    the first endpoint on the next day, and the full stay requirement/claim
    accepted by :func:`strict_lodging.check_lodging`. Both endpoints must
    identify the lodging entity and entrance. The independent
    ``fact_verifier(kind, fact)`` must accept each endpoint and the stay
    boundary fact with literal ``True`` and without mutating its input.
    Missing, altered, or unverified scope is ``unknown``.
    """
    if not isinstance(boundaries, list) or not boundaries:
        return _result("unknown", "overnight_boundaries_missing", [])
    pairs = [(item.get('previous_day'), item.get('next_day'))
             for item in boundaries if isinstance(item, dict)]
    if (len(pairs) == len(boundaries) and
            all(isinstance(a, str) and isinstance(b, str) for a, b in pairs) and
            len(set(pairs)) != len(pairs)):
        return _result("unknown", "overnight_boundary_duplicate", [])

    try:
        original_snapshot = copy.deepcopy(boundaries)
    except Exception:
        return _result("unknown", "overnight_inputs_cannot_be_snapshotted", [])
    results = []
    for index, boundary in enumerate(boundaries):
        results.append(_check_one(index, boundary, fact_verifier,
                                  lodging_claim_verifier))
        if not strict_snapshot_equal(boundaries, original_snapshot):
            return _result("unknown", "overnight_original_inputs_mutated", [])
    states = {item["state"] for item in results}
    state = "fail" if "fail" in states else "unknown" if "unknown" in states else "pass"
    reason = ("verified_overnight_conflict" if state == "fail" else
              "overnight_evidence_incomplete" if state == "unknown" else
              "verified_overnight_continuity")
    return _result(state, reason, results)


def _check_one(index, boundary, fact_verifier, lodging_claim_verifier):
    prefix = f"boundary_{index}"
    if not isinstance(boundary, dict) or set(boundary) != _BOUNDARY_KEYS:
        return {"index": index, "state": "unknown", "reason": "boundary_scope_missing_or_malformed"}
    prev, nxt = boundary.get("previous_day"), boundary.get("next_day")
    try:
        prev_date, next_date = date.fromisoformat(prev), date.fromisoformat(nxt)
    except (TypeError, ValueError):
        return {"index": index, "state": "unknown", "reason": "boundary_date_invalid"}
    if prev_date.isoformat() != prev or next_date.isoformat() != nxt:
        return {"index": index, "state": "unknown", "reason": "boundary_date_invalid"}
    if (next_date - prev_date).days != 1:
        return {"index": index, "state": "unknown", "reason": "boundary_days_not_adjacent"}

    last, first = boundary.get("last_endpoint"), boundary.get("first_endpoint")
    if not _valid_endpoint(last, prev_date) or not _valid_endpoint(first, next_date):
        return {"index": index, "state": "unknown", "reason": "endpoint_scope_missing_or_invalid"}
    if datetime.fromisoformat(first['datetime']) <= datetime.fromisoformat(last['datetime']):
        return {"index": index, "state": "unknown", "reason": "endpoint_time_order_invalid"}

    requirement, claim = boundary.get("lodging_requirement"), boundary.get("lodging_claim")
    stay_scope = _stay_scope(requirement, prev_date, next_date)
    if stay_scope is None:
        return {"index": index, "state": "unknown", "reason": "lodging_stay_scope_missing_or_invalid"}
    entity_id, check_in, check_out = stay_scope
    entrance_id = boundary.get("lodging_entrance_id")
    if not identifier_is_known(entrance_id):
        return {"index": index, "state": "unknown", "reason": "lodging_entrance_scope_missing"}

    # A supplied identity mismatch is not a verified world fact. Preserve it
    # as unknown until the independent endpoint verifier accepts the claims.
    endpoint_facts = [
        {"boundary_index": index, "side": "last", "date": prev,
         **copy.deepcopy(last)},
        {"boundary_index": index, "side": "first", "date": nxt,
         **copy.deepcopy(first)},
    ]
    stay_fact = {"boundary_index": index, "check_in": check_in,
                 "check_out": check_out, "lodging_entity_id": entity_id,
                 "lodging_entrance_id": entrance_id,
                 "previous_day": prev, "next_day": nxt}
    verified = [_verify_fact(fact_verifier, "overnight_endpoint", fact)
                for fact in endpoint_facts]
    stay_verified = _verify_fact(fact_verifier, "overnight_stay_boundary", stay_fact)
    if not all(verified) or not stay_verified:
        return {"index": index, "state": "unknown",
                "reason": "independent_overnight_fact_verification_required"}

    mismatch = any(item["entity_id"] != entity_id or
                   item["entrance_id"] != entrance_id for item in (last, first))
    if mismatch:
        # Endpoint differences alone do not establish that an intervening
        # transfer is impossible or absent from the full itinerary.
        return {"index": index, "state": "unknown",
                "reason": "transfer_between_endpoint_and_lodging_unverified"}

    lodging = check_lodging(requirement, claim,
                            claim_verifier=lodging_claim_verifier)
    if lodging.get("state") == "fail":
        return {"index": index, "state": "fail",
                "reason": "verified_lodging_requirement_failure",
                "lodging": lodging}
    if lodging.get("state") != "pass":
        return {"index": index, "state": "unknown",
                "reason": lodging.get("reason", "lodging_unverified"),
                "lodging": lodging}
    return {"index": index, "state": "pass",
            "reason": "verified_endpoints_match_scoped_lodging",
            "lodging": lodging}


def _valid_endpoint(value, expected_date):
    if not isinstance(value, dict) or set(value) != _ENDPOINT_KEYS:
        return False
    if (not identifier_is_known(value.get('entity_id')) or
            not identifier_is_known(value.get('entrance_id')) or
            not isinstance(value.get('datetime'), str) or not value['datetime'].strip()):
        return False
    try:
        moment = datetime.fromisoformat(value["datetime"])
    except ValueError:
        return False
    return moment.date() == expected_date and moment.utcoffset() is not None


def _stay_scope(requirement, previous_day, next_day):
    if not isinstance(requirement, dict):
        return None
    entity_id = requirement.get("entity_id")
    check_in, check_out = requirement.get("check_in"), requirement.get("check_out")
    if (not identifier_is_known(entity_id) or
            any(not isinstance(v, str) or not v.strip()
                for v in (check_in, check_out))):
        return None
    try:
        start, end = date.fromisoformat(check_in), date.fromisoformat(check_out)
    except ValueError:
        return None
    if (start.isoformat() != check_in or end.isoformat() != check_out or
            end <= start or start > previous_day or end < next_day):
        return None
    return entity_id, check_in, check_out


def _verify_fact(verifier, kind, fact):
    if not callable(verifier):
        return False
    try:
        supplied = copy.deepcopy(fact)
        before = copy.deepcopy(supplied)
        accepted = verifier(kind, supplied)
        return accepted is True and strict_snapshot_equal(supplied, before)
    except Exception:
        return False


def _result(state, reason, boundaries):
    return {"state": state, "reason": reason, "boundaries": boundaries,
            "coverage_scope": "provided_boundaries_only",
            "itinerary_horizon_known": False,
            "truth_certified": False, "execution_confirmed": False,
            "complete_itinerary_certified": False}
