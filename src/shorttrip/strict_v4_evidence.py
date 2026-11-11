"""Conservative bridge from nested v4 field claims to strict field checks.

This module only maps caller-declared policy. It does not infer source
authority, identity, freshness, rights, or truth from catalog metadata.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .strict_evidence import _source_supports_field, qualify_field_evidence
from .strict_scope import scope_is_complete
from .strict_snapshot import strict_snapshot_equal


def qualify_v4_field_claim(
    claim: Any,
    evidence: Any,
    *,
    entity_id: str,
    native_field: str,
    policy_field: str,
    requested_scope: Mapping[str, Any],
    source_profiles: Mapping[str, Any],
    now: str,
    evidence_verifier=None,
) -> dict[str, Any]:
    """Qualify one joined v4 claim without flattening away scope meaning.

    ``requested_scope`` keys must be present with exact values under the
    claim's nested ``context.scope``. Other non-descriptive scope dimensions
    make applicability unproven. Source profiles are explicit caller input,
    keyed by source id and carrying a ``supports`` field allowlist.
    """
    reasons: list[str] = []
    if not isinstance(claim, Mapping):
        return _result(["claim_not_object"])
    if not isinstance(evidence, Mapping):
        return _result(["evidence_not_object"])
    if not isinstance(requested_scope, Mapping) or not requested_scope:
        return _result(["requested_scope_missing"])
    if not scope_is_complete(requested_scope):
        return _result(["requested_scope_incomplete_or_invalid"])
    if not isinstance(source_profiles, Mapping):
        return _result(["source_profiles_not_object"])
    try:
        protected_inputs = (claim, evidence, requested_scope, source_profiles)
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return _result(["v4_evidence_inputs_cannot_be_snapshotted"])
    if claim.get("native_field") != native_field:
        reasons.append("native_field_mismatch")
    original_field = claim.get("field")
    if ("field" in claim and
            (not isinstance(original_field, str) or
             original_field not in (native_field, policy_field))):
        reasons.append("claim_field_mapping_mismatch")
    if claim.get("entity_id") != entity_id:
        reasons.append("claim_entity_mismatch")
    context = claim.get("context")
    if (isinstance(context, Mapping) and "native_field" in context and
            not strict_snapshot_equal(context.get("native_field"), native_field)):
        reasons.append("context_native_field_mismatch")
    nested = context.get("scope") if isinstance(context, Mapping) else None
    if not isinstance(nested, Mapping):
        reasons.append("nested_scope_missing")
    else:
        for key, wanted in requested_scope.items():
            if wanted is None or wanted == "":
                reasons.append("requested_scope_value_missing:" + str(key))
            elif key not in nested or not strict_snapshot_equal(nested.get(key), wanted):
                reasons.append("scope_mismatch:" + str(key))
        # These are v4 envelope/metadata keys, not use-context dimensions.
        metadata = {"native_field", "static_reference"}
        for key, value in context.items():
            if key not in ("scope", *metadata) and value not in (None, ""):
                reasons.append("unsupported_context_dimension:" + str(key))
        for key, value in nested.items():
            if key not in requested_scope and value not in (None, ""):
                reasons.append("unrequested_scope_dimension:" + str(key))

    source_id = claim.get("source_id")
    profile = source_profiles.get(source_id) if isinstance(source_id, str) else None
    if not isinstance(profile, Mapping):
        reasons.append("source_profile_missing")
    elif not _source_supports_field(profile, policy_field):
        reasons.append("source_policy_field_not_authorized")

    # Do not synthesize claim/evidence flags. Pass the original joined data
    # through the existing strict gate after a lossless, scoped context map.
    if reasons:
        return _result(reasons)
    flat_claim = dict(claim)
    flat_claim["field"] = policy_field
    flat_claim["context"] = dict(requested_scope)
    registry = {source_id: dict(profile)}
    result = qualify_field_evidence(
        flat_claim,
        {str(evidence.get("evidence_id", claim.get("evidence_id"))): dict(evidence)},
        registry,
        field=policy_field,
        entity_id=entity_id,
        scope=dict(requested_scope),
        now=now,
        evidence_verifier=evidence_verifier,
    )
    if not strict_snapshot_equal(protected_inputs, protected_snapshot):
        return _result(["v4_evidence_original_inputs_mutated"])
    return result


def _result(reasons: list[str]) -> dict[str, Any]:
    return {"structural_ok": False, "eligible": False,
            "reasons": list(dict.fromkeys(reasons)), "truth_certified": False,
            "independent_corroboration_certified": False}
