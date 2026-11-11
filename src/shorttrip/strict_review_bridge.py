"""Bridge strict field-evidence callbacks to the independently pinned verifier.

Legacy v4 extracted text is checked as extracted text only. It is never treated
as captured HTTP response bytes; a separately supplied raw response capture
and pinned review decisions are mandatory for approval.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .strict_independent_verifier import verify_evidence


class StrictReviewBridge:
    """Callable evidence verifier compatible with ``qualify_field_evidence``.

    ``captures_by_evidence_id`` is an explicit mapping to separate capture
    objects containing response bytes. A semantic review must be generated for
    ``review_claim(claim, requested_scope)``; that helper adds the exact scope
    binding used by the strict field callback.
    """
    def __init__(self, *, policy: Mapping[str, Any] | None = None,
                 pinned_policy_sha256: str | None = None,
                 reviewed_bindings: Mapping[str, Any] | None = None,
                 pinned_reviewed_bindings_sha256: str | None = None,
                 semantic_review_manifest: Mapping[str, Any] | None = None,
                 pinned_semantic_review_sha256: str | None = None,
                 captures_by_evidence_id: Mapping[str, Any] | None = None,
                 license_terms_bytes_by_id: Mapping[str, bytes] | None = None,
                 now: str | None = None):
        self.policy = policy
        self.pinned_policy_sha256 = pinned_policy_sha256
        self.reviewed_bindings = reviewed_bindings
        self.pinned_reviewed_bindings_sha256 = pinned_reviewed_bindings_sha256
        self.semantic_review_manifest = semantic_review_manifest
        self.pinned_semantic_review_sha256 = pinned_semantic_review_sha256
        self.captures = captures_by_evidence_id
        self.license_terms_bytes_by_id = license_terms_bytes_by_id
        self.now = now

    @staticmethod
    def review_claim(claim: Mapping[str, Any], requested_scope: Mapping[str, Any]) -> dict[str, Any]:
        """Canonical claim representation to bind in semantic review decisions."""
        mapped = dict(claim)
        mapped["scope"] = dict(requested_scope)
        return mapped

    def __call__(self, claim: Any, evidence: Any, registry: Any,
                 requested_scope: Any) -> bool:
        return self.audit(claim, evidence, registry, requested_scope)["eligible"] is True

    def audit(self, claim: Any, evidence: Any, registry: Any,
              requested_scope: Any) -> dict[str, Any]:
        reasons: list[str] = []
        details: dict[str, Any] = {"eligible": False, "bridge_link_checks_pass": False,
            "independent_verification": None, "truth_certified": False,
            "independent_corroboration_certified": False}
        if not all(isinstance(x, Mapping) for x in (claim, evidence, registry, requested_scope)):
            return self._result(details, ["callback_input_not_object"])
        claim_id, evidence_id = claim.get("claim_id"), claim.get("evidence_id")
        source_id, entity_id = claim.get("source_id"), claim.get("entity_id")
        field, unit, quote = claim.get("field"), claim.get("unit"), claim.get("quote")
        if not isinstance(claim_id, str) or not claim_id.strip():
            reasons.append("claim_id_missing")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            reasons.append("claim_evidence_id_missing")
        if not isinstance(source_id, str) or not source_id.strip() or evidence.get("source_id") != source_id:
            reasons.append("claim_evidence_source_id_mismatch")
        if not isinstance(entity_id, str) or not entity_id.strip() or evidence.get("entity_id") != entity_id:
            reasons.append("claim_evidence_entity_id_mismatch")
        if not isinstance(field, str) or not field.strip() or evidence.get("field") != field:
            reasons.append("claim_evidence_field_mismatch")
        if evidence.get("claim_id") != claim_id:
            reasons.append("claim_evidence_claim_id_mismatch")
        if evidence.get("evidence_id") != evidence_id:
            reasons.append("claim_evidence_id_mismatch")
        if claim.get("value") is None or not _same(claim.get("value"), evidence.get("value")):
            reasons.append("claim_evidence_value_mismatch")
        if not isinstance(unit, str) or not unit.strip() or not _same(unit, evidence.get("unit")):
            reasons.append("claim_evidence_unit_mismatch")
        if not isinstance(quote, str) or not quote or evidence.get("quote") != quote:
            reasons.append("claim_evidence_quote_mismatch")
        if not requested_scope or not _same(claim.get("context"), requested_scope):
            reasons.append("claim_context_requested_scope_mismatch")
        if not _same(evidence.get("scope"), requested_scope):
            reasons.append("evidence_requested_scope_mismatch")

        source = registry.get(source_id) if isinstance(source_id, str) else None
        supports = source.get("supports") if isinstance(source, Mapping) else None
        if not isinstance(source, Mapping) or not isinstance(supports, list) or field not in supports:
            reasons.append("callback_registry_source_field_not_authorized")

        raw_text = evidence.get("raw_text")
        raw_sha = evidence.get("raw_sha256")
        if not isinstance(raw_text, str):
            reasons.append("old_evidence_extracted_text_missing")
        else:
            try:
                extracted_sha = hashlib.sha256(raw_text.encode("utf-8", errors="strict")).hexdigest()
                if (not isinstance(raw_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", raw_sha)
                        or extracted_sha != raw_sha.lower()):
                    reasons.append("old_evidence_extracted_text_digest_mismatch")
            except UnicodeEncodeError:
                reasons.append("old_evidence_extracted_text_encoding_invalid")
        if isinstance(raw_text, str) and (not isinstance(quote, str) or not quote or quote not in raw_text):
            reasons.append("claim_quote_not_in_old_extracted_text")

        capture = (self.captures.get(evidence_id)
                   if isinstance(self.captures, Mapping) and isinstance(evidence_id, str) else None)
        if not isinstance(capture, Mapping):
            reasons.append("separate_raw_response_capture_missing")
        else:
            if capture.get("evidence_id") != evidence_id:
                reasons.append("capture_evidence_id_mismatch")
            reviewed_entities = self.reviewed_bindings.get("entity_map") if isinstance(self.reviewed_bindings, Mapping) else None
            expected_capture_entity = (reviewed_entities.get(entity_id)
                if isinstance(reviewed_entities, Mapping) and isinstance(entity_id, str) else None)
            if (capture.get("source_id") != source_id
                    or not isinstance(expected_capture_entity, str)
                    or capture.get("entity_id") != expected_capture_entity):
                reasons.append("capture_source_or_reviewed_entity_mismatch")
            final_url = capture.get("final_url")
            if (not isinstance(final_url, str) or not final_url
                    or evidence.get("final_url") != final_url
                    or evidence.get("source_url") != final_url
                    or claim.get("source_url") != final_url):
                reasons.append("old_evidence_claim_capture_final_url_mismatch")
            raw_response = capture.get("response_bytes")
            if not isinstance(raw_response, bytes):
                reasons.append("capture_response_bytes_missing_or_not_bytes")
            else:
                response_sha = hashlib.sha256(raw_response).hexdigest()
                if (capture.get("response_sha256") != response_sha
                        or claim.get("response_sha256") != response_sha
                        or evidence.get("response_sha256") != response_sha):
                    reasons.append("claim_old_evidence_capture_response_digest_mismatch")

        pinned_inputs = (isinstance(self.policy, Mapping)
            and isinstance(self.reviewed_bindings, Mapping)
            and isinstance(self.semantic_review_manifest, Mapping)
            and isinstance(self.captures, Mapping)
            and isinstance(self.license_terms_bytes_by_id, Mapping)
            and isinstance(self.now, str)
            and isinstance(self.pinned_policy_sha256, str)
            and isinstance(self.pinned_reviewed_bindings_sha256, str)
            and isinstance(self.pinned_semantic_review_sha256, str))
        if not pinned_inputs:
            reasons.append("externally_pinned_review_inputs_missing")

        details["bridge_link_checks_pass"] = not reasons
        if reasons:
            return self._result(details, reasons)

        review_claim = self.review_claim(claim, requested_scope)
        try:
            independent = verify_evidence(
                claim=review_claim,
                capture=capture,
                policy=self.policy,
                pinned_policy_sha256=self.pinned_policy_sha256,
                reviewed_bindings=self.reviewed_bindings,
                pinned_reviewed_bindings_sha256=self.pinned_reviewed_bindings_sha256,
                license_terms_bytes_by_id=self.license_terms_bytes_by_id,
                semantic_review_manifest=self.semantic_review_manifest,
                pinned_semantic_review_sha256=self.pinned_semantic_review_sha256,
                now=self.now)
        except Exception as exc:
            return self._result(details, ["independent_verifier_error:" + type(exc).__name__])
        details["independent_verification"] = independent
        details["eligible"] = independent.get("eligible") is True
        if not details["eligible"]:
            reasons.extend(independent.get("reasons", []))
            return self._result(details, reasons)
        return self._result(details, [])

    @staticmethod
    def _result(details: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
        return {**details, "eligible": details.get("eligible") is True and not reasons,
                "reasons": list(dict.fromkeys(reasons)),
                "truth_certified": False,
                "independent_corroboration_certified": False}


def _same(left: Any, right: Any) -> bool:
    try:
        return json_digest(left) == json_digest(right)
    except (TypeError, ValueError):
        return False


def json_digest(value: Any) -> str:
    import json
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
