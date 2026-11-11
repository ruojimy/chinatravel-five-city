"""Offline verifier for externally pinned, independently reviewed entity binding.

This checks consistency of a review decision against captured source bytes.
It does not authenticate the reviewer, the publisher, or real-world identity.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from .strict_scope import identifier_is_known
from .strict_source_access import _https_url


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone_required")
    return dt.astimezone(timezone.utc)


class IndependentIdentityReview:
    """Verify record identity against a caller-pinned review manifest.

    Manifest shape:
      ``{"policy":{"identity_review":{"authorized_reviewer_ids": [...]},
      "sources":{source_id:{"allowed_hosts":[],
      "identity_capabilities":["entity_identity"], "rights":{
      "status":"approved", "rights_id":"...", "terms_sha256":"..."}}}},
      "decisions":[...]}``

    Each decision binds exact record ``id/city/kind/name`` to a capture ID,
    source ID/capability, response digest, quote, observation/validity times,
    and an explicit reviewer decision. Captures are passed separately and must
    contain original ``bytes`` in ``response_bytes`` and an ``extractor_id``
    different from a policy-authorized reviewer. These IDs remain caller-pinned
    assertions, not authenticated identities.
    """
    def __init__(self, manifest: Mapping[str, Any], captures: Mapping[str, Any], *,
                 pinned_manifest_sha256: str, now: str,
                 rights_terms_bytes_by_id: Mapping[str, bytes] | None = None):
        self.manifest = manifest
        self.captures = captures
        self.pinned_manifest_sha256 = pinned_manifest_sha256
        self.now = now
        self.rights_terms_bytes_by_id = rights_terms_bytes_by_id

    def adapter_identity_verifier(self, record: Any) -> bool:
        """Callback compatible with ``diagnose_record(..., identity_verifier=)``."""
        return self.verify_record(record)["verified"] is True

    def gap_queue_identity_verifier(self, gap: Any) -> bool:
        """Callback compatible with ``build_static_gap_queue(..., identity_verifier=)``."""
        if not isinstance(gap, Mapping) or gap.get("entity_identity_verified") is not True:
            return False
        entity_id = gap.get("entity_id")
        return self.verify_entity_id(entity_id)["verified"] is True

    def verify_record(self, record: Any) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            return self._result(["record_not_object"])
        identity = {key: record.get(key) for key in ("id", "city", "kind", "name")}
        if not self._valid_identity(identity):
            return self._result(["record_identity_fields_missing_or_invalid"])
        decision, reasons = self._find_decision(identity["id"])
        if decision is None:
            return self._result(reasons)
        reasons.extend(self._check_decision(decision, expected_identity=identity))
        return self._result(reasons)

    def verify_entity_id(self, entity_id: Any) -> dict[str, Any]:
        """Recheck the pinned binding for queue gaps, which carry only entity_id."""
        if not identifier_is_known(entity_id):
            return self._result(["entity_id_missing_or_invalid"])
        decision, reasons = self._find_decision(entity_id)
        if decision is None:
            return self._result(reasons)
        bound = decision.get("record")
        if not isinstance(bound, Mapping) or not self._valid_identity(bound):
            reasons.append("reviewed_record_binding_missing_or_invalid")
        else:
            reasons.extend(self._check_decision(decision, expected_identity=dict(bound)))
        return self._result(reasons)

    def _find_decision(self, entity_id: str) -> tuple[Mapping[str, Any] | None, list[str]]:
        reasons: list[str] = []
        if not isinstance(self.manifest, Mapping):
            return None, ["review_manifest_missing"]
        try:
            actual_pin = canonical_digest(self.manifest)
        except (TypeError, ValueError, RecursionError, UnicodeError):
            return None, ["review_manifest_not_canonicalizable"]
        if not isinstance(self.pinned_manifest_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.pinned_manifest_sha256) or actual_pin != self.pinned_manifest_sha256.lower():
            return None, ["review_manifest_pin_missing_or_mismatch"]
        decisions = self.manifest.get("decisions")
        if not isinstance(decisions, list):
            return None, ["review_decisions_missing"]
        matches = [d for d in decisions if isinstance(d, Mapping) and d.get("entity_id") == entity_id]
        if len(matches) != 1:
            return None, ["review_decision_missing_or_ambiguous"]
        return matches[0], reasons

    def _check_decision(self, decision: Mapping[str, Any], *,
                        expected_identity: Mapping[str, Any]) -> list[str]:
        reasons: list[str] = []
        bound = decision.get("record")
        if not isinstance(bound, Mapping) or not self._valid_identity(bound):
            return ["reviewed_record_binding_missing_or_invalid"]
        if dict(bound) != dict(expected_identity) or decision.get("entity_id") != expected_identity.get("id"):
            reasons.append("reviewed_record_identity_mismatch")

        source_id = decision.get("source_id")
        capability = decision.get("identity_capability")
        policy = self.manifest.get("policy") if isinstance(self.manifest, Mapping) else None
        sources = policy.get("sources") if isinstance(policy, Mapping) else None
        source_id_valid = identifier_is_known(source_id)
        profile = sources.get(source_id) if isinstance(sources, Mapping) and source_id_valid else None
        capabilities = profile.get("identity_capabilities") if isinstance(profile, Mapping) else None
        if (not source_id_valid or not isinstance(profile, Mapping)
                or not identifier_is_known(capability)
                or not isinstance(capabilities, list) or capability not in capabilities):
            reasons.append("source_identity_capability_not_authorized")

        rights = profile.get("rights") if isinstance(profile, Mapping) else None
        if not isinstance(rights, Mapping):
            reasons.append("source_rights_policy_missing")
        else:
            terms_sha = rights.get("terms_sha256")
            rights_id = rights.get("rights_id")
            decision_terms_sha = decision.get("rights_terms_sha256")
            if (rights.get("status") != "approved"
                    or not identifier_is_known(rights_id)
                    or not isinstance(terms_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", terms_sha)
                    or decision.get("rights_id") != rights_id
                    or decision_terms_sha != terms_sha):
                reasons.append("source_rights_terms_not_approved_or_mismatched")
            else:
                terms_bytes = (self.rights_terms_bytes_by_id.get(rights_id)
                               if isinstance(self.rights_terms_bytes_by_id, Mapping) else None)
                if (not isinstance(terms_bytes, bytes)
                        or hashlib.sha256(terms_bytes).hexdigest() != terms_sha.lower()):
                    reasons.append("source_rights_terms_artifact_missing_or_digest_mismatch")

        capture_id = decision.get("capture_id")
        capture = (self.captures.get(capture_id) if isinstance(self.captures, Mapping)
                   and identifier_is_known(capture_id) else None)
        if not isinstance(capture, Mapping):
            return reasons + ["raw_capture_missing"]
        raw = capture.get("response_bytes")
        if not isinstance(raw, bytes):
            reasons.append("raw_capture_bytes_missing_or_not_bytes")
            return reasons
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected_sha = decision.get("response_sha256")
        if (not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha)
                or actual_sha != expected_sha.lower() or capture.get("response_sha256") != expected_sha):
            reasons.append("raw_capture_digest_mismatch")
        if capture.get("source_id") != source_id:
            reasons.append("capture_source_id_mismatch")
        if type(capture.get("status")) is not int or capture.get("status") != 200:
            reasons.append("capture_http_status_not_success")
        try:
            url = _https_url(capture.get("final_url"))
            host = url.hostname if url is not None else ""
            if url is None or not host:
                raise ValueError
            allowed_hosts = profile.get("allowed_hosts") if isinstance(profile, Mapping) else None
            if not isinstance(allowed_hosts, list) or not all(isinstance(h, str) for h in allowed_hosts):
                reasons.append("identity_host_allowlist_invalid")
            elif host not in allowed_hosts:
                reasons.append("capture_host_not_authorized_for_identity")
        except (ValueError, AttributeError, TypeError):
            reasons.append("capture_final_url_invalid")

        quote = decision.get("quote")
        try:
            decoded = raw.decode("utf-8", errors="strict")
            if not isinstance(quote, str) or not quote or quote not in decoded:
                reasons.append("review_quote_not_in_raw_capture")
            elif _has_obvious_challenge_marker(decoded):
                reasons.append("obvious_challenge_or_login_marker_present")
        except UnicodeDecodeError:
            decoded = None
            reasons.append("raw_capture_utf8_decode_failed")

        review = decision.get("reviewed_binding")
        if not isinstance(review, Mapping):
            reasons.append("independent_reviewed_binding_missing")
        else:
            if review.get("decision") != "same_entity":
                reasons.append("review_decision_not_same_entity")
            if review.get("record") != dict(bound):
                reasons.append("reviewed_binding_record_mismatch")
            if review.get("source_id") != source_id or review.get("quote") != quote:
                reasons.append("reviewed_binding_source_or_quote_mismatch")
            capture_url = capture.get("final_url")
            if (not isinstance(capture_url, str) or decision.get("final_url") != capture_url
                    or review.get("final_url") != capture_url):
                reasons.append("reviewed_final_url_capture_mismatch")
            if (any(type(x) is not int or x != 200 for x in
                    (capture.get("status"), decision.get("http_status"), review.get("http_status")))):
                reasons.append("reviewed_http_status_capture_mismatch")
            if isinstance(rights, Mapping):
                if (review.get("rights_id") != rights.get("rights_id")
                        or review.get("rights_terms_sha256") != rights.get("terms_sha256")):
                    reasons.append("reviewed_binding_rights_terms_mismatch")
            reviewer = review.get("reviewer_id")
            if not identifier_is_known(reviewer):
                reasons.append("reviewer_identity_missing")
            review_policy = policy.get('identity_review') if isinstance(policy, Mapping) else None
            authorized = review_policy.get('authorized_reviewer_ids') if isinstance(review_policy, Mapping) else None
            if (not isinstance(authorized, list) or not authorized or
                    not all(identifier_is_known(item) for item in authorized) or
                    reviewer not in authorized):
                reasons.append('identity_reviewer_not_policy_authorized')
            extractor = capture.get('extractor_id')
            if not identifier_is_known(extractor):
                reasons.append('identity_capture_extractor_missing')
            elif (identifier_is_known(reviewer) and
                  unicodedata.normalize('NFKC', extractor).strip().casefold() ==
                  unicodedata.normalize('NFKC', reviewer).strip().casefold()):
                reasons.append('identity_reviewer_not_independent_of_extractor')

        try:
            now = _time(self.now)
            observed = _time(decision.get("observed_at"))
            capture_observed = _time(capture.get("observed_at"))
            captured_at = _time(capture.get("captured_at"))
            valid_from = _time(decision.get("valid_from"))
            valid_until = _time(decision.get("valid_until"))
            reviewed_at = _time(review.get("reviewed_at")) if isinstance(review, Mapping) else None
            time_ok = (observed == capture_observed and valid_from <= observed < valid_until
                       and observed <= captured_at <= now < valid_until
                       and reviewed_at is not None and captured_at < reviewed_at <= now)
        except (TypeError, ValueError):
            time_ok = False
        if not time_ok:
            reasons.append("observation_review_or_validity_time_invalid")
        return reasons

    @staticmethod
    def _valid_identity(identity: Mapping[str, Any]) -> bool:
        return all(identifier_is_known(identity.get(k)) for k in ("id", "city", "kind", "name"))

    @staticmethod
    def _result(reasons: list[str]) -> dict[str, Any]:
        reasons = list(dict.fromkeys(reasons))
        return {"verified": not reasons, "reasons": reasons,
                "real_world_identity_certified": False,
                "source_truth_certified": False,
                "challenge_screening": "deterministic markers only; no marker is not proof of no challenge"}


def _has_obvious_challenge_marker(text: str) -> bool:
    """Reject only explicit challenge/login markers; absence proves nothing."""
    lowered = text.lower()
    markers = (
        "<title>just a moment</title>", "id=\"challenge-form\"", "cf-chl-",
        "name=\"captcha\"", "verify you are human", "sign in to continue",
        "log in to continue", "captcha challenge", "请先登录", "请登录后查看",
        "登录后继续", "人机验证", "完成安全验证", "验证码验证",
    )
    return any(marker in lowered for marker in markers)
