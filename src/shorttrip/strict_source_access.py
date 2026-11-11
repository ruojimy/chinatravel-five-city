"""Offline, fail-closed verification of narrowly scoped source access evidence.

This module is intentionally not connected to source registration, request
dispatch, a ledger, or a network client. A positive result is only a mechanical
scoped preflight result; it does not authenticate a publisher or establish the
truth of any content claim.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .strict_scope import identifier_is_known
from .strict_snapshot import strict_snapshot_equal


_POLICY_KEYS = frozenset({
    "policy_id", "policy_reviewer_id", "authorized_terms_reviewers",
    "user_agent", "max_robots_age_seconds", "max_terms_age_seconds",
    "max_review_age_seconds", "max_artifact_bytes", "allowed_fields",
    "allowed_actions", "allowed_uses", "terms_content_types",
    "valid_from", "valid_until",
})
_TARGET_KEYS = frozenset({"url", "field", "action", "use", "collector_id"})
_ARTIFACT_KEYS = frozenset({
    "url", "final_url", "status", "content_type", "captured_at", "body",
    "sha256",
})
_REVIEW_KEYS = frozenset({
    "review_id", "reviewer_id", "decision", "policy_sha256",
    "terms_sha256", "terms_url", "target_url", "field", "action", "use",
    "collector_id", "reviewed_at", "valid_until",
})


def _canonical_sha256(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _aware(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _sha256_bytes(value):
    if type(value) is not bytes:
        return None
    return hashlib.sha256(value).hexdigest()


def _https_url(value, *, allow_query=True):
    """Accept a deliberately small, unambiguous HTTPS URL form."""
    if (not isinstance(value, str) or not value or len(value) > 4096 or not value.isascii() or
            any(ord(char) <= 32 or ord(char) == 127 for char in value)):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if (parsed.scheme != "https" or not host or host != host.lower() or
            not host.isascii() or len(host) > 253 or
            len(host.split('.')) < 2 or host.endswith(('.local', '.localhost', '.internal')) or
            not re.fullmatch(r'[a-z]{2,63}', host.split('.')[-1]) or
            any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                for label in host.split('.')) or
            parsed.username is not None or parsed.password is not None or
            port not in (None, 443) or parsed.fragment or
            (not allow_query and parsed.query) or
            not parsed.path.startswith("/") or "\\" in parsed.path or
            '%' in parsed.path or '%' in parsed.query or ';' in parsed.path or
            '//' in parsed.path or any(part in ('.', '..') for part in parsed.path.split('/'))):
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None
    # Reject unusual netloc spellings that urlsplit may normalize silently.
    expected_netloc = host if port is None else host + ":443"
    if parsed.netloc != expected_netloc:
        return None
    if parsed.geturl() != value:
        return None
    return parsed


def _callback_accepted_unchanged(callback, args):
    if not callable(callback):
        return False
    try:
        supplied = copy.deepcopy(args)
        before = copy.deepcopy(supplied)
        accepted = callback(*supplied)
        return (accepted is True and
                strict_snapshot_equal(supplied, before))
    except Exception:
        return False


def _validate_policy(policy, pinned_policy_sha256, now):
    reasons = []
    if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS:
        return ["source_policy_missing_or_malformed"], None
    calculated = _canonical_sha256(policy)
    if (not isinstance(pinned_policy_sha256, str) or
            calculated is None or calculated != pinned_policy_sha256):
        reasons.append("source_policy_pin_mismatch")
    if not identifier_is_known(policy.get("policy_id")):
        reasons.append("source_policy_id_invalid")
    if not identifier_is_known(policy.get("policy_reviewer_id")):
        reasons.append("source_policy_reviewer_invalid")
    reviewers = policy.get("authorized_terms_reviewers")
    if (not isinstance(reviewers, list) or not reviewers or
            any(not identifier_is_known(value) for value in reviewers) or
            len(set(reviewers)) != len(reviewers)):
        reasons.append("source_policy_authorized_reviewers_invalid")
    if not identifier_is_known(policy.get("user_agent")):
        reasons.append("source_policy_user_agent_invalid")
    for key in ("max_robots_age_seconds", "max_terms_age_seconds",
                "max_review_age_seconds", "max_artifact_bytes"):
        if type(policy.get(key)) is not int or policy[key] <= 0:
            reasons.append("source_policy_limit_invalid:" + key)
    for key in ("allowed_fields", "allowed_actions", "allowed_uses",
                "terms_content_types"):
        values = policy.get(key)
        if (not isinstance(values, list) or not values or
                any(not identifier_is_known(value) for value in values) or
                len(set(values)) != len(values)):
            reasons.append("source_policy_allowlist_invalid:" + key)
    valid_from, valid_until = _aware(policy.get("valid_from")), _aware(policy.get("valid_until"))
    instant = _aware(now)
    if valid_from is None or valid_until is None or instant is None:
        reasons.append("source_policy_clock_invalid")
    elif valid_until <= valid_from or instant < valid_from or instant >= valid_until:
        reasons.append("source_policy_not_current")
    return reasons, calculated


def _verify_robots_subset(body):
    """Accept only one universal group with empty Disallow directives.

    Nonempty disallow rules, Allow, user-agent-specific groups, extensions,
    and unrecognized syntax are unknown. This narrow subset cannot accidentally
    claim that a complex robots policy permits a path.
    """
    if type(body) is not bytes:
        return False
    try:
        text = body.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return False
    seen_agent = False
    seen_empty_disallow = False
    directive_count = 0
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            return False
        name, value = line.split(":", 1)
        name, value = name.strip().casefold(), value.strip()
        directive_count += 1
        if name == "user-agent":
            if seen_agent or value != "*":
                return False
            seen_agent = True
        elif name == "disallow":
            if not seen_agent or value:
                return False
            seen_empty_disallow = True
        else:
            return False
    return seen_agent and seen_empty_disallow and directive_count > 0


def _validate_artifact(artifact, *, kind, target_host, policy, now):
    reasons = []
    if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_KEYS:
        return [kind + "_artifact_missing_or_malformed"], None
    parsed_url = _https_url(artifact.get("url"), allow_query=False)
    parsed_final = _https_url(artifact.get("final_url"), allow_query=False)
    if parsed_url is None or parsed_final is None:
        reasons.append(kind + "_artifact_url_invalid")
    else:
        if parsed_url.hostname != target_host or parsed_final.hostname != target_host:
            reasons.append(kind + "_artifact_host_mismatch")
        if artifact.get("final_url") != artifact.get("url"):
            reasons.append(kind + "_artifact_redirect_not_supported")
    if type(artifact.get("status")) is not int or artifact.get("status") != 200:
        reasons.append(kind + "_artifact_status_not_accepted")
    content_type = artifact.get("content_type")
    if not isinstance(content_type, str):
        reasons.append(kind + "_artifact_content_type_invalid")
    elif kind == "robots" and content_type.split(";", 1)[0].strip().casefold() != "text/plain":
        reasons.append("robots_artifact_content_type_not_plain_text")
    elif kind == "terms":
        allowed_types = policy.get("terms_content_types", [])
        normalized_type = content_type.split(";", 1)[0].strip().casefold()
        normalized_allowed = ([item.casefold() for item in allowed_types
                               if isinstance(item, str)]
                              if isinstance(allowed_types, list) else [])
        if normalized_type not in normalized_allowed:
            reasons.append("terms_artifact_content_type_not_allowed")
    captured = _aware(artifact.get("captured_at"))
    instant = _aware(now)
    if captured is None or instant is None:
        reasons.append(kind + "_artifact_clock_invalid")
    else:
        max_age_key = "max_robots_age_seconds" if kind == "robots" else "max_terms_age_seconds"
        max_age = policy.get(max_age_key)
        if captured > instant:
            reasons.append(kind + "_artifact_from_future")
        elif type(max_age) is int and (instant - captured).total_seconds() > max_age:
            reasons.append(kind + "_artifact_stale")
    body = artifact.get("body")
    actual_sha = _sha256_bytes(body)
    if (actual_sha is None or not isinstance(artifact.get("sha256"), str) or
            actual_sha != artifact.get("sha256")):
        reasons.append(kind + "_artifact_hash_mismatch_or_non_bytes")
    elif len(body) > policy.get("max_artifact_bytes", 0):
        reasons.append(kind + "_artifact_too_large")
    if kind == "robots" and actual_sha is not None and not _verify_robots_subset(body):
        reasons.append("robots_syntax_outside_supported_permissive_subset")
    return reasons, actual_sha


def verify_source_access(*, policy, pinned_policy_sha256, target,
                         robots_artifact, terms_artifact, terms_review,
                         pinned_terms_review_sha256, now,
                         policy_pin_verifier=None,
                         terms_review_verifier=None):
    """Mechanically verify one narrowly scoped source-access bundle.

    The two callbacks are external trust boundaries. The first must establish
    that the policy hash is genuinely pinned. The second must independently
    authenticate the pinned reviewer decision and its semantic review of the
    preserved terms bytes. Both callbacks receive isolated snapshots and must
    return literal ``True`` without mutation.

    A positive output is deliberately `mechanical_scoped_pass`; it does not
    register a source, authorize a live fetch, authenticate publisher identity,
    or certify any factual claim.
    """
    originals = (policy, target, robots_artifact, terms_artifact, terms_review)
    try:
        original_snapshot = copy.deepcopy(originals)
        policy, target, robots_artifact, terms_artifact, terms_review = copy.deepcopy(original_snapshot)
    except Exception:
        return _result(['source_inputs_snapshot_unavailable'])
    reasons, policy_sha = _validate_policy(policy, pinned_policy_sha256, now)
    if reasons:
        return _result(reasons)
    if isinstance(policy, dict):
        if not _callback_accepted_unchanged(policy_pin_verifier,
                (policy, pinned_policy_sha256)):
            reasons.append("source_policy_external_pin_unverified")
    if not isinstance(target, dict) or set(target) != _TARGET_KEYS:
        return _result(reasons + ["source_target_missing_or_malformed"])
    parsed_target = _https_url(target.get("url"))
    if parsed_target is None:
        reasons.append("source_target_https_url_invalid")
        target_host = None
    else:
        target_host = parsed_target.hostname
    for key in ("field", "action", "use", "collector_id"):
        if not identifier_is_known(target.get(key)):
            reasons.append("source_target_value_invalid:" + key)
    if isinstance(policy, dict):
        for key, policy_key in (("field", "allowed_fields"),
                                ("action", "allowed_actions"),
                                ("use", "allowed_uses")):
            allowed = policy.get(policy_key)
            if isinstance(allowed, list) and target.get(key) not in allowed:
                reasons.append("source_target_not_in_policy:" + key)
    robots_reasons, robots_sha = _validate_artifact(
        robots_artifact, kind="robots", target_host=target_host,
        policy=policy if isinstance(policy, dict) else {}, now=now)
    terms_reasons, terms_sha = _validate_artifact(
        terms_artifact, kind="terms", target_host=target_host,
        policy=policy if isinstance(policy, dict) else {}, now=now)
    reasons.extend(robots_reasons)
    reasons.extend(terms_reasons)
    if (isinstance(robots_artifact, dict) and
            robots_artifact.get("url") != ("https://" + target_host + "/robots.txt"
                                           if target_host else None)):
        reasons.append("robots_artifact_not_exact_host_root")

    if not isinstance(terms_review, dict) or set(terms_review) != _REVIEW_KEYS:
        reasons.append("terms_review_missing_or_malformed")
    else:
        review = terms_review
        for key in ("review_id", "reviewer_id", "collector_id"):
            if not identifier_is_known(review.get(key)):
                reasons.append("terms_review_value_invalid:" + key)
        if review.get("decision") != "approved":
            reasons.append("terms_review_not_approved")
        reviewer, collector = review.get("reviewer_id"), target.get("collector_id")
        same_principal = (identifier_is_known(reviewer) and identifier_is_known(collector) and
            unicodedata.normalize('NFKC', reviewer).strip().casefold() ==
            unicodedata.normalize('NFKC', collector).strip().casefold())
        if (same_principal or
                (isinstance(policy, dict) and
                 review.get("reviewer_id") not in policy.get("authorized_terms_reviewers", []))):
            reasons.append("terms_reviewer_not_independent_and_authorized")
        if review.get("policy_sha256") != pinned_policy_sha256:
            reasons.append("terms_review_policy_pin_mismatch")
        if review.get("terms_sha256") != terms_sha:
            reasons.append("terms_review_artifact_hash_mismatch")
        if (review.get("terms_url") != terms_artifact.get("url")
                if isinstance(terms_artifact, dict) else True):
            reasons.append("terms_review_artifact_url_mismatch")
        for key in ("url", "field", "action", "use", "collector_id"):
            if review.get("target_url" if key == "url" else key) != target.get(key):
                reasons.append("terms_review_target_scope_mismatch:" + key)
        reviewed = _aware(review.get("reviewed_at"))
        expires = _aware(review.get("valid_until"))
        instant = _aware(now)
        robot_capture = (_aware(robots_artifact.get("captured_at"))
                         if isinstance(robots_artifact, dict) else None)
        terms_capture = (_aware(terms_artifact.get("captured_at"))
                         if isinstance(terms_artifact, dict) else None)
        if reviewed is None or expires is None or instant is None:
            reasons.append("terms_review_clock_invalid")
        else:
            if reviewed > instant:
                reasons.append("terms_review_from_future")
            if (robot_capture is None or terms_capture is None or
                    reviewed <= max(robot_capture, terms_capture)):
                reasons.append("terms_review_not_after_artifact_capture")
            if expires <= reviewed or instant >= expires:
                reasons.append("terms_review_expired_or_nonpositive")
            max_age = (policy.get("max_review_age_seconds")
                       if isinstance(policy, dict) else None)
            if (reviewed <= instant and type(max_age) is int and
                    (instant - reviewed).total_seconds() > max_age):
                reasons.append("terms_review_stale")
        calculated_review_sha = _canonical_sha256(review)
        if (calculated_review_sha is None or
                calculated_review_sha != pinned_terms_review_sha256):
            reasons.append("terms_review_pin_mismatch")
        if not _callback_accepted_unchanged(terms_review_verifier,
                (policy, review, terms_artifact, target,
                 pinned_terms_review_sha256)):
            reasons.append("independent_terms_review_unverified")

    if not strict_snapshot_equal(originals, original_snapshot):
        reasons.append('source_verifier_mutated_original_inputs')
    return _result(reasons, scope={
        "target_url": target.get("url") if isinstance(target, dict) else None,
        "field": target.get("field") if isinstance(target, dict) else None,
        "action": target.get("action") if isinstance(target, dict) else None,
        "use": target.get("use") if isinstance(target, dict) else None,
        "policy_sha256": policy_sha,
        "robots_sha256": robots_sha,
        "terms_sha256": terms_sha,
        "terms_review_sha256": _canonical_sha256(terms_review),
    })


def _result(reasons, *, scope=None):
    unique = sorted(set(reasons))
    return {
        "status": "mechanical_scoped_pass" if not unique else "unknown",
        "reasons": unique,
        "scope": scope,
        "source_registered": False,
        "live_fetch_authorized": False,
        "provider_identity_authenticated": False,
        "claim_truth_certified": False,
        "execution_confirmed": False,
    }
