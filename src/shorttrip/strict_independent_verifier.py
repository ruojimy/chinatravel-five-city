"""Fail-closed mechanical verifier for explicitly reviewed evidence inputs.

This module verifies consistency against caller-pinned policy and reviewed
bindings. It does not authenticate the reviewer, the upstream publisher, or
the semantic truth of a statement.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping
from .strict_identity_review import _has_obvious_challenge_marker
from .strict_source_access import _https_url
from .strict_scope import scope_is_complete, identifier_is_known, scope_identifiers_are_known
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money


def canonical_digest(value: Any) -> str:
    """SHA-256 of deterministic UTF-8 JSON (sorted keys, no NaN)."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def verify_evidence(*, claim: Mapping[str, Any], capture: Mapping[str, Any],
                    policy: Mapping[str, Any], pinned_policy_sha256: str,
                    reviewed_bindings: Mapping[str, Any],
                    pinned_reviewed_bindings_sha256: str, now: str,
                    license_terms_bytes_by_id: Mapping[str, bytes] | None = None,
                    semantic_review_manifest: Mapping[str, Any] | None = None,
                    pinned_semantic_review_sha256: str | None = None) -> dict[str, Any]:
    """Check one claim against raw captured bytes and explicit reviewed inputs.

    `reviewed_bindings` carries `reviewer_id`, `entity_map` (claim entity to
    capture entity), and `scope_map` (claim id to reviewed exact scope). These
    are inputs, not authenticated signatures; the caller must protect/pin them.
    An optional separately pinned semantic-review manifest can allow
    ``eligible=True`` only when all mechanical checks pass and its approved
    decision canonically binds the claim, response digest, quote, entity,
    scope, value, and unit.
    """
    reasons: list[str] = []
    checks = {k: False for k in ("policy_pin", "reviewed_bindings_pin", "byte_integrity", "source_authorization",
        "rights", "identity_binding", "scope_binding", "quote_binding",
        "value_binding", "freshness")}
    if not isinstance(claim, Mapping) or not isinstance(capture, Mapping) or not isinstance(policy, Mapping) or not isinstance(reviewed_bindings, Mapping):
        return _result(checks, ["input_not_object"])
    for name in ("claim_id", "source_id", "entity_id", "license_id"):
        if not identifier_is_known(claim.get(name)):
            return _result(checks, ["claim_identifier_invalid:" + name])

    try:
        checks["policy_pin"] = canonical_digest(policy) == pinned_policy_sha256
    except (TypeError, ValueError, RecursionError, UnicodeError):
        checks["policy_pin"] = False
    if not checks["policy_pin"]:
        reasons.append("policy_pin_missing_or_mismatch")
    try:
        checks["reviewed_bindings_pin"] = canonical_digest(reviewed_bindings) == pinned_reviewed_bindings_sha256
    except (TypeError, ValueError, RecursionError, UnicodeError):
        checks["reviewed_bindings_pin"] = False
    if not checks["reviewed_bindings_pin"]:
        reasons.append("reviewed_bindings_pin_missing_or_mismatch")

    raw = capture.get("response_bytes")
    if not isinstance(raw, bytes):
        reasons.append("response_bytes_missing_or_not_bytes")
    else:
        digest = hashlib.sha256(raw).hexdigest()
        checks["byte_integrity"] = digest == capture.get("response_sha256") == claim.get("response_sha256")
        if not checks["byte_integrity"]:
            reasons.append("response_digest_mismatch")
    text = None
    if isinstance(raw, bytes):
        if capture.get("decoder") != "utf-8":
            reasons.append("unsupported_or_missing_decoder")
        else:
            try:
                text = raw.decode("utf-8", errors="strict")
                if _has_obvious_challenge_marker(text):
                    reasons.append("obvious_challenge_or_login_marker_present")
            except UnicodeDecodeError:
                reasons.append("response_decode_failed")

    # Require the same narrow canonical HTTPS URL form used by source-access
    # preflight, then bind its canonical ASCII host to the policy allowlist.
    try:
        parsed = _https_url(capture.get("final_url"))
        host = parsed.hostname if parsed is not None else ""
        if parsed is None or not host:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        host = ""
        reasons.append("final_url_invalid")
    if (not isinstance(claim.get('source_url'), str) or not claim['source_url'] or
            claim['source_url'] != capture.get('final_url')):
        reasons.append('claim_source_url_capture_final_url_mismatch')
    source_id = claim.get("source_id")
    sources = policy.get("sources", {})
    profile = sources.get(source_id) if isinstance(sources, Mapping) else None
    field = claim.get("field")
    allowed_hosts = profile.get("allowed_hosts") if isinstance(profile, Mapping) else None
    supports = profile.get("supports") if isinstance(profile, Mapping) else None
    hosts_valid = _valid_string_list(allowed_hosts)
    supports_valid = _valid_string_list(supports)
    if not hosts_valid:
        reasons.append("source_allowed_hosts_invalid")
    if not supports_valid:
        reasons.append("source_supports_invalid")
    if (type(capture.get("status")) is int and capture.get("status") == 200 and isinstance(profile, Mapping)
            and hosts_valid and host in allowed_hosts
            and supports_valid and field in supports):
        checks["source_authorization"] = True
    elif hosts_valid and supports_valid:
        reasons.append("source_not_authorized_for_host_field_or_status")
    license_id = claim.get("license_id")
    licenses = policy.get("licenses", {})
    lic = licenses.get(license_id) if isinstance(licenses, Mapping) else None
    terms_digest = claim.get("license_terms_sha256")
    if (isinstance(lic, Mapping) and lic.get("status") == "approved"
            and isinstance(terms_digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", terms_digest)
            and lic.get("terms_sha256") == terms_digest):
        terms_bytes = (license_terms_bytes_by_id.get(license_id)
                       if isinstance(license_terms_bytes_by_id, Mapping) else None)
        if (isinstance(terms_bytes, bytes)
                and hashlib.sha256(terms_bytes).hexdigest() == terms_digest.lower()):
            checks["rights"] = True
        else:
            reasons.append("license_terms_artifact_missing_or_digest_mismatch")
    else:
        reasons.append("license_not_explicitly_approved_or_terms_mismatch")

    reviewer = reviewed_bindings.get("reviewer_id")
    entities = reviewed_bindings.get("entity_map", {})
    if (isinstance(reviewer, str) and reviewer.strip()
            and isinstance(entities, Mapping)
            and entities.get(claim.get("entity_id")) == capture.get("entity_id")
            and identifier_is_known(capture.get("entity_id"))):
        checks["identity_binding"] = True
    else:
        reasons.append("reviewed_identity_binding_missing_or_mismatch")

    scopes = reviewed_bindings.get("scope_map", {})
    requested, stated = claim.get("scope"), scopes.get(claim.get("claim_id")) if isinstance(scopes, Mapping) else None
    if (isinstance(requested, Mapping) and requested and scope_is_complete(requested)
            and scope_identifiers_are_known(requested)
            and isinstance(stated, Mapping) and scope_is_complete(stated)
            and scope_identifiers_are_known(stated)
            and strict_snapshot_equal(dict(requested), dict(stated))):
        checks["scope_binding"] = True
    else:
        incomplete = ((isinstance(requested, Mapping) and requested
                       and not scope_identifiers_are_known(requested))
                      or (isinstance(stated, Mapping) and stated
                          and not scope_identifiers_are_known(stated)))
        reasons.append("reviewed_scope_binding_incomplete_or_invalid" if incomplete else
                       "reviewed_scope_binding_missing_or_mismatch")

    quote = claim.get("quote")
    if isinstance(text, str) and isinstance(quote, str) and quote and quote in text:
        checks["quote_binding"] = True
    else:
        reasons.append("quote_not_found_in_decoded_response")
    if checks["quote_binding"] and _value_occurs(quote, claim.get("value"), claim.get("unit")):
        checks["value_binding"] = True
    else:
        reasons.append("field_value_or_unit_not_bound_by_quote")

    try:
        asof = _time(now)
        retrieved = _time(capture.get("retrieved_at"))
        observed = _time(capture.get("observed_at"))
        claimed_observed = _time(claim.get("observed_at"))
        expires = _time(capture.get("expires_at"))
        checks["freshness"] = observed == claimed_observed and observed <= retrieved <= asof < expires
    except (TypeError, ValueError):
        checks["freshness"] = False
    if not checks["freshness"]:
        reasons.append("freshness_missing_invalid_or_expired")
    mechanical_checks_pass = all(checks.values()) and not reasons
    semantic_review_pass = False
    if semantic_review_manifest is None and pinned_semantic_review_sha256 is None:
        reasons.append("audited_semantic_verifier_not_provided")
    elif not mechanical_checks_pass:
        reasons.append("semantic_review_blocked_by_mechanical_check_failure")
    else:
        semantic_review_pass, semantic_reasons = _check_semantic_review(
            claim=claim, capture=capture, policy=policy,
            review_manifest=semantic_review_manifest,
            pinned_review_sha256=pinned_semantic_review_sha256, now=now)
        reasons.extend(semantic_reasons)
    return _result(checks, reasons, mechanical_checks_pass=mechanical_checks_pass,
                   semantic_review_pass=semantic_review_pass)


def _check_semantic_review(*, claim: Mapping[str, Any], capture: Mapping[str, Any],
                           policy: Mapping[str, Any], review_manifest: Any,
                           pinned_review_sha256: Any, now: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(review_manifest, Mapping):
        return False, ["semantic_review_manifest_missing_or_invalid"]
    try:
        actual_pin = canonical_digest(review_manifest)
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return False, ["semantic_review_manifest_not_canonicalizable"]
    if (not isinstance(pinned_review_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", pinned_review_sha256)
            or actual_pin != pinned_review_sha256.lower()):
        return False, ["semantic_review_manifest_pin_missing_or_mismatch"]

    decisions = review_manifest.get("decisions")
    if not isinstance(decisions, list):
        return False, ["semantic_review_decisions_missing"]
    claim_id = claim.get("claim_id")
    matches = [d for d in decisions if isinstance(d, Mapping) and d.get("claim_id") == claim_id]
    if not claim_id or len(matches) != 1:
        return False, ["semantic_review_decision_missing_or_ambiguous"]
    decision = matches[0]
    if decision.get("decision") != "approved":
        reasons.append("semantic_review_not_approved")

    semantic_policy = policy.get("semantic_review")
    authorized = semantic_policy.get("authorized_reviewer_ids") if isinstance(semantic_policy, Mapping) else None
    reviewer_id = decision.get("reviewer_id")
    extractor_id = capture.get("extractor_id")
    if (not isinstance(authorized, list) or not authorized or
            not all(identifier_is_known(item) for item in authorized) or
            not identifier_is_known(reviewer_id) or reviewer_id not in authorized):
        reasons.append("semantic_reviewer_not_policy_authorized")
    if not identifier_is_known(extractor_id):
        reasons.append("capture_extractor_identity_missing")
    elif (identifier_is_known(reviewer_id) and
          unicodedata.normalize('NFKC', reviewer_id).strip().casefold() ==
          unicodedata.normalize('NFKC', extractor_id).strip().casefold()):
        reasons.append("semantic_reviewer_not_independent_of_extractor")

    try:
        reviewed_at = _time(decision.get("reviewed_at"))
        captured_at = _time(capture.get("retrieved_at"))
        asof = _time(now)
        if not captured_at < reviewed_at <= asof:
            reasons.append("semantic_review_time_not_after_capture_or_after_now")
    except (TypeError, ValueError):
        reasons.append("semantic_review_timestamp_missing_or_invalid")

    try:
        actual_response_sha = (hashlib.sha256(capture["response_bytes"]).hexdigest()
                               if isinstance(capture.get("response_bytes"), bytes) else None)
        expected_binding = {
            "claim_sha256": canonical_digest(claim),
            "response_sha256": actual_response_sha,
            "quote": claim.get("quote"),
            "entity_id": claim.get("entity_id"),
            "scope": claim.get("scope"),
            "value": claim.get("value"),
            "unit": claim.get("unit"),
        }
        expected_binding_sha = canonical_digest(expected_binding)
        binding = decision.get("binding")
        if not isinstance(binding, Mapping) or canonical_digest(binding) != expected_binding_sha:
            reasons.append("semantic_review_canonical_binding_mismatch")
        if decision.get("binding_sha256") != expected_binding_sha:
            reasons.append("semantic_review_binding_digest_mismatch")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        reasons.append("semantic_review_binding_not_canonicalizable")
    return not reasons, reasons


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def _value_occurs(quote: str, value: Any, unit: Any) -> bool:
    if exact_money(value) is None:
        return False
    if unit != "CNY":
        return False
    if re.search(r"免票|免费|不含|不适用|非普通|仅限|学生|儿童|优待|套餐|套票|多次|年卡|次卡|原价|优惠|起价|低至", quote):
        return False
    if re.search(r"(?:[-+−－＋]\s*\d+(?:\.\d+)?|\d+\s*[,，]\s*\d+)\s*(?:元|人民币|CNY)", quote, re.I):
        return False
    # Do not bind a positive value to the suffix of a signed or grouped
    # number, e.g. treating "-1 元" as 1 or "1,000 元" as 0.
    boundary = r"(?<![\d.,，+\-−－＋])"
    amounts = list(re.finditer(boundary + r"\d+(?:\.\d+)?\s*(?:元|人民币|CNY)(?![\w])", quote, re.I))
    if len(amounts) != 1:
        return False
    prefix = quote[:amounts[0].start()].rstrip()
    # A separated sign, range endpoint, or digit group must not be mistaken
    # for a standalone positive amount. Unsupported formats remain unknown.
    if (prefix and (prefix[-1].isdigit() or prefix[-1] in
                    "'’_٬,，、.＋+−－-–—‐‑‒―﹣~～〜/／至到万千百亿")):
        return False
    if re.search(r'(?:负|负数|亏损|退款|退还|返还|返现|补贴)\s*[:：]?\s*$', prefix):
        return False
    if (prefix and unicodedata.category(prefix[-1])[0] in {'P', 'S'} and
            prefix[:-1].rstrip() and prefix[:-1].rstrip()[-1].isdigit()):
        return False
    numeric = re.escape(str(value))
    return bool(re.search(boundary + numeric + r"\s*(?:元|人民币|CNY)(?![\w])", quote, re.I))


def _valid_string_list(value: Any) -> bool:
    return (type(value) is list and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value))


def _result(checks: dict[str, bool], reasons: list[str], *,
            mechanical_checks_pass: bool = False,
            semantic_review_pass: bool = False) -> dict[str, Any]:
    reasons = list(dict.fromkeys(reasons))
    return {"eligible": mechanical_checks_pass and semantic_review_pass,
            "mechanical_checks_pass": mechanical_checks_pass,
            "semantic_verifier_pass": semantic_review_pass, "checks": checks, "reasons": reasons,
            "truth_certified": False, "semantic_proof": False,
            "independent_corroboration_certified": False}
