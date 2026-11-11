"""Offline route-context and TTL checks; does not authenticate route providers.

A passing result means only that the requested context matches and the
observation is within the declared short freshness window. It is not proof of
provider identity, licensing, response integrity, or duration correctness.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from .strict_scope import identifier_is_known

ROUTE_CONTEXT_FIELDS = (
    "origin", "destination", "origin_entry", "destination_entry",
    "coord_system", "mode", "travel_date", "departure_at",
)
DEFAULT_MAX_TTL_SECONDS = 900  # conservative local policy, not a provider guarantee


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def verify_route_context_ttl(
    requirement: Any,
    evidence: Any,
    *,
    now: Any,
    max_ttl_seconds: int = DEFAULT_MAX_TTL_SECONDS,
) -> dict[str, Any]:
    """Check exact route applicability and bounded observation freshness.

    The returned ``context_ttl_ok`` must not be treated as source verification.
    ``eligible_for_planning`` is deliberately always false until a separate
    provider/rights/raw-response verifier and numeric-value binding exist.
    """
    reasons: list[str] = []
    if not isinstance(requirement, dict) or not isinstance(evidence, dict):
        reasons.append("route_requirement_or_evidence_not_object")
        return _result(reasons)
    requested = requirement.get("context")
    observed_context = evidence.get("context")
    if not isinstance(requested, dict) or not isinstance(observed_context, dict):
        reasons.append("route_context_not_object")
        return _result(reasons)

    expected_keys = set(ROUTE_CONTEXT_FIELDS)
    if set(requested) != expected_keys:
        reasons.append("route_request_context_keys_missing_or_unsupported")
    if set(observed_context) != expected_keys:
        reasons.append("route_evidence_context_keys_missing_or_unsupported")

    for key in ROUTE_CONTEXT_FIELDS:
        expected = requested.get(key)
        if not identifier_is_known(expected):
            reasons.append("route_context_missing:" + key)
        elif observed_context.get(key) != expected:
            reasons.append("route_context_mismatch:" + key)

    departure_text = requested.get("departure_at")
    departure = _parse_aware(departure_text)
    travel_date = requested.get("travel_date")
    try:
        parsed_date = date.fromisoformat(travel_date) if isinstance(travel_date, str) else None
    except ValueError:
        parsed_date = None
    if departure is None or parsed_date is None or parsed_date.isoformat() != travel_date:
        reasons.append("route_departure_context_invalid")
    else:
        # Compare the departure's own stated local calendar date, not UTC date.
        try:
            local_departure = datetime.fromisoformat(departure_text.replace("Z", "+00:00"))
            if local_departure.date() != parsed_date:
                reasons.append("route_departure_date_mismatch")
        except (ValueError, TypeError, AttributeError):
            reasons.append("route_departure_context_invalid")
    if requested.get("coord_system") not in ("GCJ02", "WGS84"):
        reasons.append("route_coordinate_system_unknown")

    try:
        valid_max_ttl = type(max_ttl_seconds) is int and max_ttl_seconds > 0
    except Exception:
        valid_max_ttl = False
    if not valid_max_ttl:
        reasons.append("route_max_ttl_invalid")

    observed = _parse_aware(evidence.get("observed_at"))
    expires = _parse_aware(evidence.get("valid_until"))
    instant = _parse_aware(now)
    if observed is None or expires is None or instant is None:
        reasons.append("route_clock_missing_or_invalid")
    else:
        if observed > instant:
            reasons.append("route_observation_from_future")
        if instant >= expires:
            reasons.append("route_evidence_expired")
        if expires <= observed:
            reasons.append("route_ttl_nonpositive")
        elif valid_max_ttl and (expires - observed).total_seconds() > max_ttl_seconds:
            reasons.append("route_ttl_exceeds_policy")
    return _result(reasons)


def _result(reasons: list[str]) -> dict[str, Any]:
    unique = sorted(set(reasons))
    return {
        "context_ttl_ok": not unique,
        "eligible_for_planning": False,
        "reasons": unique,
        "provider_identity_verified": False,
        "response_value_binding_verified": False,
        "truth_certified": False,
    }
