import copy
import hashlib
import json
import unittest

from shorttrip.strict_source_access import verify_source_access


def canonical_sha(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


class StrictSourceAccessTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-10-31T12:00:00Z"
        self.policy = {
            "policy_id": "policy-2026-10",
            "policy_reviewer_id": "policy-reviewer",
            "authorized_terms_reviewers": ["independent-reviewer"],
            "user_agent": "StrictResearchBot/1.0",
            "max_robots_age_seconds": 86400,
            "max_terms_age_seconds": 86400,
            "max_review_age_seconds": 604800,
            "max_artifact_bytes": 10000,
            "allowed_fields": ["opening_hours"],
            "allowed_actions": ["fetch"],
            "allowed_uses": ["reference"],
            "terms_content_types": ["text/plain", "text/html"],
            "valid_from": "2026-10-01T00:00:00Z",
            "valid_until": "2026-12-01T00:00:00Z",
        }
        self.target = {
            "url": "https://example.org/poi/42?date=2026-11-01",
            "field": "opening_hours",
            "action": "fetch",
            "use": "reference",
            "collector_id": "collector-7",
        }
        self.robots = self.artifact(
            "https://example.org/robots.txt",
            b"User-agent: *\nDisallow:\n", "text/plain")
        self.terms = self.artifact(
            "https://example.org/terms", b"Synthetic terms snapshot.",
            "text/plain")
        self.review = {
            "review_id": "terms-review-1",
            "reviewer_id": "independent-reviewer",
            "decision": "approved",
            "policy_sha256": canonical_sha(self.policy),
            "terms_sha256": self.terms["sha256"],
            "terms_url": self.terms["url"],
            "target_url": self.target["url"],
            "field": self.target["field"],
            "action": self.target["action"],
            "use": self.target["use"],
            "collector_id": self.target["collector_id"],
            "reviewed_at": "2026-10-31T11:30:00Z",
            "valid_until": "2026-11-01T12:00:00Z",
        }

    def artifact(self, url, body, content_type):
        return {
            "url": url,
            "final_url": url,
            "status": 200,
            "content_type": content_type,
            "captured_at": "2026-10-31T11:00:00Z",
            "body": body,
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    def run_check(self, **overrides):
        args = {
            "policy": self.policy,
            "pinned_policy_sha256": canonical_sha(self.policy),
            "target": self.target,
            "robots_artifact": self.robots,
            "terms_artifact": self.terms,
            "terms_review": self.review,
            "pinned_terms_review_sha256": canonical_sha(self.review),
            "now": self.now,
            "policy_pin_verifier": lambda *_: True,
            "terms_review_verifier": lambda *_: True,
        }
        args.update(overrides)
        return verify_source_access(**args)

    def test_synthetic_scoped_positive_does_not_claim_registration_or_truth(self):
        result = self.run_check()
        self.assertEqual("mechanical_scoped_pass", result["status"])
        self.assertEqual([], result["reasons"])
        for claim in ("source_registered", "live_fetch_authorized",
                      "provider_identity_authenticated", "claim_truth_certified",
                      "execution_confirmed"):
            self.assertFalse(result[claim], claim)

    def test_changed_original_bytes_fail_hash_binding(self):
        changed = copy.deepcopy(self.terms)
        changed["body"] += b" altered"
        result = self.run_check(terms_artifact=changed)
        self.assertIn("terms_artifact_hash_mismatch_or_non_bytes", result["reasons"])
        self.assertNotEqual("mechanical_scoped_pass", result["status"])

    def test_artifacts_from_another_host_fail_even_if_hashes_are_valid(self):
        other_host = self.artifact("https://other.example/robots.txt",
                                   b"User-agent: *\nDisallow:\n", "text/plain")
        result = self.run_check(robots_artifact=other_host)
        self.assertIn("robots_artifact_host_mismatch", result["reasons"])
        self.assertIn("robots_artifact_not_exact_host_root", result["reasons"])

    def test_wrong_robots_path_is_not_accepted(self):
        wrong_path = self.artifact("https://example.org/robots-copy.txt",
                                   b"User-agent: *\nDisallow:\n", "text/plain")
        result = self.run_check(robots_artifact=wrong_path)
        self.assertIn("robots_artifact_not_exact_host_root", result["reasons"])

    def test_stale_capture_and_expired_review_fail_closed(self):
        stale_robots = copy.deepcopy(self.robots)
        stale_robots["captured_at"] = "2026-10-20T11:00:00Z"
        result = self.run_check(robots_artifact=stale_robots)
        self.assertIn("robots_artifact_stale", result["reasons"])
        expired = copy.deepcopy(self.review)
        expired["valid_until"] = "2026-10-31T11:59:59Z"
        result = self.run_check(terms_review=expired,
                                pinned_terms_review_sha256=canonical_sha(expired))
        self.assertIn("terms_review_expired_or_nonpositive", result["reasons"])

    def test_failed_tool_error_text_is_not_a_successful_snapshot(self):
        error = self.artifact("https://example.org/robots.txt",
                              b"URL inaccessible via this tool", "text/plain")
        error["status"] = None
        result = self.run_check(robots_artifact=error)
        self.assertIn("robots_artifact_status_not_accepted", result["reasons"])
        self.assertIn("robots_syntax_outside_supported_permissive_subset", result["reasons"])

    def test_reviewer_alias_of_collector_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["reviewer_id"] = self.target["collector_id"]
        result = self.run_check(terms_review=review,
                                pinned_terms_review_sha256=canonical_sha(review))
        self.assertIn("terms_reviewer_not_independent_and_authorized", result["reasons"])

    def test_unicode_case_alias_of_collector_is_rejected(self):
        for alias in ("COLLECTOR-7", "ＣＯＬＬＥＣＴＯＲ－７"):
            with self.subTest(alias=alias):
                policy = copy.deepcopy(self.policy)
                policy["authorized_terms_reviewers"] = [alias]
                review = copy.deepcopy(self.review)
                review["reviewer_id"] = alias
                review["policy_sha256"] = canonical_sha(policy)
                result = self.run_check(policy=policy,
                    pinned_policy_sha256=canonical_sha(policy), terms_review=review,
                    pinned_terms_review_sha256=canonical_sha(review))
                self.assertIn("terms_reviewer_not_independent_and_authorized", result["reasons"])

    def test_future_reviewed_at_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["reviewed_at"] = "2026-10-31T12:00:01Z"
        result = self.run_check(terms_review=review,
            pinned_terms_review_sha256=canonical_sha(review))
        self.assertIn("terms_review_from_future", result["reasons"])

    def test_leading_whitespace_or_control_in_target_and_artifact_urls_is_rejected(self):
        cases = [
            ("target", {"url": " \thttps://example.org/poi/42?date=2026-11-01"},
             "source_target_https_url_invalid"),
            ("robots", {"url": "\nhttps://example.org/robots.txt"},
             "robots_artifact_url_invalid"),
            ("robots", {"final_url": "\rhttps://example.org/robots.txt"},
             "robots_artifact_url_invalid"),
            ("terms", {"url": "\thttps://example.org/terms"},
             "terms_artifact_url_invalid"),
            ("terms", {"final_url": "\x01https://example.org/terms"},
             "terms_artifact_url_invalid"),
            ("review", {"terms_url": "\nhttps://example.org/terms"},
             "terms_review_artifact_url_mismatch"),
            ("review", {"target_url": " \thttps://example.org/poi/42?date=2026-11-01"},
             "terms_review_target_scope_mismatch:url"),
        ]
        for section, changes, expected_reason in cases:
            with self.subTest(section=section, changes=changes):
                args = {}
                if section == "target":
                    target = copy.deepcopy(self.target)
                    target.update(changes)
                    args["target"] = target
                elif section == "robots":
                    artifact = copy.deepcopy(self.robots)
                    artifact.update(changes)
                    args["robots_artifact"] = artifact
                elif section == "terms":
                    artifact = copy.deepcopy(self.terms)
                    artifact.update(changes)
                    args["terms_artifact"] = artifact
                else:
                    review = copy.deepcopy(self.review)
                    review.update(changes)
                    args["terms_review"] = review
                    args["pinned_terms_review_sha256"] = canonical_sha(review)
                result = self.run_check(**args)
                self.assertNotEqual(result["status"], "mechanical_scoped_pass")
                self.assertIn(expected_reason, result["reasons"])

    def test_target_path_normalization_ambiguities_are_not_scoped_passes(self):
        urls = [
            "https://example.org/a/../poi",
            "https://example.org/a/./poi",
            "https://example.org/%2e%2e/poi",
            "https://example.org/a%2fb",
            "https://example.org/a%5cb",
            "https://example.org/%ZZ",
            "https://example.org//poi",
            "https://example.org/poi;param=value",
            "https://localhost/poi",
            "https://internal/poi",
            "https://127.0.0.1/poi",
            "https://127.1/poi",
            "https://127.0.1/poi",
            "https://0177.0.0.1/poi",
            "https://0177.1/poi",
            "https://0x7f.1/poi",
            "https://example.org/poi/é",
            "https://example.org/poi?city=厦门",
            "https://example.org/a／..／poi",
            "https://example.org/a/．．/poi",
        ]
        for url in urls:
            with self.subTest(url=url):
                target = copy.deepcopy(self.target)
                target["url"] = url
                review = copy.deepcopy(self.review)
                review["target_url"] = url
                result = self.run_check(target=target, terms_review=review,
                    pinned_terms_review_sha256=canonical_sha(review))
                self.assertNotEqual("mechanical_scoped_pass", result["status"])
                self.assertIn("source_target_https_url_invalid", result["reasons"])

    def test_terms_artifact_path_normalization_ambiguities_are_rejected(self):
        for path in ("/a/../terms", "/a%2fb", "/%ZZ", "//terms", "/terms;v=1"):
            with self.subTest(path=path):
                terms = copy.deepcopy(self.terms)
                terms["url"] = "https://example.org" + path
                terms["final_url"] = terms["url"]
                review = copy.deepcopy(self.review)
                review["terms_url"] = terms["url"]
                result = self.run_check(terms_artifact=terms,
                    terms_review=review,
                    pinned_terms_review_sha256=canonical_sha(review))
                self.assertNotEqual("mechanical_scoped_pass", result["status"])
                self.assertIn("terms_artifact_url_invalid", result["reasons"])

    def test_review_of_different_target_path_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["target_url"] = "https://example.org/poi/43?date=2026-11-01"
        result = self.run_check(terms_review=review,
                                pinned_terms_review_sha256=canonical_sha(review))
        self.assertIn("terms_review_target_scope_mismatch:url", result["reasons"])

    def test_unsupported_or_restrictive_robots_syntax_is_unknown(self):
        restricted = self.artifact("https://example.org/robots.txt",
                                   b"User-agent: *\nDisallow: /private\n", "text/plain")
        result = self.run_check(robots_artifact=restricted)
        self.assertIn("robots_syntax_outside_supported_permissive_subset", result["reasons"])

    def test_robots_parser_rejects_incomplete_or_unsupported_groups(self):
        bodies = [
            b"User-agent: *\n",  # no explicit empty Disallow evidence
            b"Disallow:\nUser-agent: *\n",
            b"User-agent: *\nUser-agent: *\nDisallow:\n",
            b"User-agent: *\nDisallow:\nAllow:\n",
            b"User-agent: *\nDisallow:\nCrawl-delay: 1\n",
            b"User-agent: *\nDisallow:\nUser-agent: OtherBot\nDisallow:\n",
            b"User-agent *\nDisallow:\n",
            b"User-agent: *\nDisallow:\n\xff",
        ]
        for body in bodies:
            with self.subTest(body=body):
                robots = self.artifact("https://example.org/robots.txt", body,
                                       "text/plain")
                result = self.run_check(robots_artifact=robots)
                self.assertNotEqual("mechanical_scoped_pass", result["status"])
                self.assertIn("robots_syntax_outside_supported_permissive_subset",
                              result["reasons"])

    def test_external_pins_are_required_and_must_accept(self):
        result = self.run_check(policy_pin_verifier=None)
        self.assertIn("source_policy_external_pin_unverified", result["reasons"])
        result = self.run_check(terms_review_verifier=lambda *_: False)
        self.assertIn("independent_terms_review_unverified", result["reasons"])

    def test_policy_pin_callback_cannot_mutate_caller_policy_to_expand_scope(self):
        policy = copy.deepcopy(self.policy)
        target = copy.deepcopy(self.target)
        target["field"] = "price"
        review = copy.deepcopy(self.review)
        review["field"] = "price"
        review["policy_sha256"] = canonical_sha(policy)

        def mutate_original_policy(*_):
            # Closure-held caller input is outside the defensive callback copy.
            policy["allowed_fields"].append("price")
            return True

        result = self.run_check(
            policy=policy, target=target, terms_review=review,
            pinned_terms_review_sha256=canonical_sha(review),
            policy_pin_verifier=mutate_original_policy)
        self.assertNotEqual("mechanical_scoped_pass", result["status"])

    def test_either_callback_detects_closure_mutation_of_each_caller_input(self):
        mutations = {
            "policy": lambda value: value.update(user_agent="ChangedBot/1.0"),
            "target": lambda value: value.update(field="other_field"),
            "robots_artifact": lambda value: value.update(status=201),
            "terms_artifact": lambda value: value.update(body=value["body"] + b"x"),
            "terms_review": lambda value: value.update(decision="rejected"),
        }
        for callback_name in ("policy", "terms_review"):
          for name, mutate in mutations.items():
            with self.subTest(callback=callback_name, input=name):
                objects = {
                    "policy": copy.deepcopy(self.policy),
                    "target": copy.deepcopy(self.target),
                    "robots_artifact": copy.deepcopy(self.robots),
                    "terms_artifact": copy.deepcopy(self.terms),
                    "terms_review": copy.deepcopy(self.review),
                }

                def callback(*_):
                    mutate(objects[name])
                    return True

                callback_args = ({"policy_pin_verifier": callback,
                                  "terms_review_verifier": lambda *_: True}
                                 if callback_name == "policy" else
                                 {"policy_pin_verifier": lambda *_: True,
                                  "terms_review_verifier": callback})
                result = self.run_check(**objects,
                    pinned_terms_review_sha256=canonical_sha(objects["terms_review"]),
                    **callback_args)
                self.assertNotEqual("mechanical_scoped_pass", result["status"])
                self.assertIn("source_verifier_mutated_original_inputs", result["reasons"])


if __name__ == "__main__":
    unittest.main()
