"""Strict, offline evidence qualification for one field claim.

Structural validity is only a prerequisite. This module never certifies truth;
it requires explicit identity, scope, source capability, rights and freshness.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .expansion_contract import validate_claim
from .freshness import check_claim
from .strict_scope import scope_is_complete, identifier_is_known, scope_identifiers_are_known
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money

_ALLOWED_LICENSES = {"allowed", "api_terms"}


def _source_supports_field(source: Any, field: Any) -> bool:
    supports = source.get("supports") if isinstance(source, Mapping) else None
    return (type(supports) is list and bool(supports)
            and all(isinstance(item, str) and item.strip() for item in supports)
            and isinstance(field, str) and field in supports)


def _valid_price_or_cost(value: Any) -> bool:
    return exact_money(value) is not None


def qualify_field_evidence(
    claim: Any,
    evidence_by_id: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    field: str,
    entity_id: str,
    scope: Mapping[str, Any],
    now: str,
    evidence_verifier=None,
) -> dict[str, Any]:
    """Return conservative eligibility for a single requested field.

    ``scope`` is the complete required use context (for example travel_date,
    party_size, room_type, origin/destination/departure_at). Every supplied
    scope key must exactly match the claim's context; empty scope is not proof
    that the claim applies universally. The caller must supply a non-empty
    scope whenever the field's applicability is contextual.

    A positive result means evidence passed these mechanical gates, not that
    the value is true or independently corroborated.
    """
    reasons: list[str] = []
    if not isinstance(claim, dict):
        return _result(False, False, ["claim_not_object"])
    for key in ('claim_id', 'evidence_id', 'source_id'):
        if not identifier_is_known(claim.get(key)):
            return _result(False, False, ['claim_identifier_invalid:' + key])
    if not isinstance(scope, Mapping):
        return _result(False, False, ["requested_scope_not_object"])
    if scope and (not scope_is_complete(scope) or not scope_identifiers_are_known(scope)):
        return _result(False, False, ["requested_scope_incomplete_or_invalid"])
    if not isinstance(registry, Mapping):
        return _result(False, False, ["registry_not_object"])
    try:
        protected_inputs = (claim, evidence_by_id, registry, scope)
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return _result(False, False, ['evidence_inputs_cannot_be_snapshotted'])

    try:
        structural = validate_claim(claim, evidence_by_id, now=now)
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return _result(False, False, ['structural:claim_not_safely_validatable'])
    reasons.extend("structural:" + reason for reason in structural.get("errors", []))
    if claim.get("field") != field:
        reasons.append("wrong_field")
    if field in ("price", "Cost", "dynamic_price", "route_fare") and not _valid_price_or_cost(claim.get("value")):
        reasons.append("invalid_numeric_price_or_cost")
    if not identifier_is_known(entity_id):
        reasons.append("requested_entity_missing")
    elif claim.get("entity_id") != entity_id:
        reasons.append("wrong_entity")

    context = claim.get("context")
    if not isinstance(context, dict):
        reasons.append("claim_context_missing")
    else:
        if not scope:
            reasons.append("requested_scope_empty")
        for key, expected in scope.items():
            if expected is None or expected == "":
                reasons.append("requested_scope_value_missing:" + str(key))
            elif key not in context or not strict_snapshot_equal(context.get(key), expected):
                reasons.append("scope_mismatch:" + str(key))
        # Context declared by the claim cannot add a hidden applicability
        # dimension absent from the request; it remains unproven.
        for key, actual in context.items():
            if actual not in (None, "") and key not in scope:
                reasons.append("unrequested_scope_dimension:" + str(key))

    evidence = evidence_by_id.get(claim.get("evidence_id")) if isinstance(evidence_by_id, Mapping) else None
    if not isinstance(evidence, dict):
        reasons.append("evidence_missing")
    else:
        # Identity is deliberately an explicit, exact assertion on the claim.
        if claim.get("entity_verified") is not True:
            reasons.append("identity_not_verified")
        if evidence.get("entity_id") != entity_id:
            reasons.append("evidence_entity_mismatch")
        if evidence.get("entity_verified") is not True:
            reasons.append("evidence_identity_not_verified")
        licence = evidence.get("licence_status")
        if licence not in _ALLOWED_LICENSES or claim.get("licence_status") != licence:
            reasons.append("licence_not_explicitly_allowed")
        if claim.get("extraction_verified") is not True:
            reasons.append("extraction_not_verified")

    source_id = claim.get("source_id")
    source = registry.get(source_id, {}) if isinstance(source_id, str) else {}
    if not isinstance(source, dict) or not source:
        reasons.append("unregistered_source")
    elif not _source_supports_field(source, field):
        supports = source.get("supports")
        if not (type(supports) is list and bool(supports)
                and all(isinstance(item, str) and item.strip() for item in supports)):
            reasons.append("source_supports_invalid")
        reasons.append("source_not_authorized_for_field")

    if claim.get("conflict") is True:
        reasons.append("known_conflict")
    # A record's own booleans are not independent proof of identity, rights,
    # or semantic value binding. The caller must supply a separate verifier.
    verified = False
    if callable(evidence_verifier):
        try:
            callback_inputs = copy.deepcopy((claim, evidence, registry, dict(scope)))
            callback_before = copy.deepcopy(callback_inputs)
            callback_result = evidence_verifier(*callback_inputs)
            if not strict_snapshot_equal(protected_inputs, protected_snapshot):
                return _result(False, False, ['evidence_original_inputs_mutated'])
            verified = (callback_result is True and
                        strict_snapshot_equal(callback_inputs, callback_before))
        except Exception:
            verified = False
    if not verified:
        reasons.append("independent_evidence_verifier_required")
    # Reuse the project's field-specific freshness/context and quality checks,
    # but only after checking identity and requested scope above.
    if not reasons:
        gate = check_claim({**evidence, **claim}, field, registry, now=now, context=dict(scope))
        reasons.extend(gate.get("reasons", []))
    return _result(structural.get("ok", False), not reasons, reasons)


def _result(structural_ok: bool, eligible: bool, reasons: list[str]) -> dict[str, Any]:
    return {
        "structural_ok": structural_ok,
        "eligible": eligible,
        "reasons": list(dict.fromkeys(reasons)),
        "truth_certified": False,
        "independent_corroboration_certified": False,
    }

