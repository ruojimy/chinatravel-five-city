import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_independent_verifier import canonical_digest, verify_evidence, _value_occurs

LICENSE_TERMS = b"synthetic reviewed operator terms v1"
LICENSE_TERMS_SHA = hashlib.sha256(LICENSE_TERMS).hexdigest()


def fixture():
    raw = "普通成人票 80 元，适用日期 2026-11-02".encode("utf-8")
    claim = {"claim_id": "c1", "source_id": "operator", "entity_id": "venue-claim",
             "field": "price", "scope": {"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"},
             "quote": "普通成人票 80 元，适用日期 2026-11-02", "value": 80, "unit": "CNY",
             "license_id": "terms-v1", "license_terms_sha256": LICENSE_TERMS_SHA,
             "observed_at": "2026-10-30T06:30:00Z",
             "source_url": "https://venue.invalid/ticket",
             "response_sha256": hashlib.sha256(raw).hexdigest()}
    capture = {"response_bytes": raw, "response_sha256": hashlib.sha256(raw).hexdigest(),
               "decoder": "utf-8", "final_url": "https://venue.invalid/ticket", "status": 200,
               "retrieved_at": "2026-10-30T07:00:00Z", "observed_at": "2026-10-30T06:30:00Z",
               "expires_at": "2026-10-31T07:00:00Z",
               "entity_id": "venue-source", "extractor_id": "extractor-1"}
    policy = {"sources": {"operator": {"allowed_hosts": ["venue.invalid"], "supports": ["price"]}},
              "licenses": {"terms-v1": {"status": "approved", "terms_sha256": LICENSE_TERMS_SHA}},
              "semantic_review": {"authorized_reviewer_ids": ["reviewer-semantic-2"]}}
    reviewed = {"reviewer_id": "reviewer-1", "entity_map": {"venue-claim": "venue-source"},
                "scope_map": {"c1": dict(claim["scope"])}}
    return claim, capture, policy, reviewed


def run_verify(claim, capture, policy, reviewed):
    return verify_evidence(claim=claim, capture=capture, policy=policy,
        pinned_policy_sha256=canonical_digest(policy), reviewed_bindings=reviewed,
        pinned_reviewed_bindings_sha256=canonical_digest(reviewed),
        license_terms_bytes_by_id={"terms-v1": LICENSE_TERMS},
        now="2026-10-30T08:00:00Z")


def semantic_manifest(claim, capture, *, reviewer="reviewer-semantic-2",
                      decision="approved", reviewed_at="2026-10-30T07:30:00Z"):
    binding = {"claim_sha256": canonical_digest(claim),
        "response_sha256": hashlib.sha256(capture["response_bytes"]).hexdigest(),
        "quote": claim["quote"], "entity_id": claim["entity_id"],
        "scope": dict(claim["scope"]), "value": claim["value"], "unit": claim["unit"]}
    return {"decisions": [{"claim_id": claim["claim_id"], "decision": decision,
        "reviewer_id": reviewer, "reviewed_at": reviewed_at,
        "binding": binding, "binding_sha256": canonical_digest(binding)}]}


def run_reviewed(claim, capture, policy, reviewed, sem_manifest, pin=None, now="2026-10-30T08:00:00Z"):
    return verify_evidence(claim=claim, capture=capture, policy=policy,
        pinned_policy_sha256=canonical_digest(policy), reviewed_bindings=reviewed,
        pinned_reviewed_bindings_sha256=canonical_digest(reviewed), now=now,
        license_terms_bytes_by_id={"terms-v1": LICENSE_TERMS},
        semantic_review_manifest=sem_manifest,
        pinned_semantic_review_sha256=canonical_digest(sem_manifest) if pin is None else pin)


class StrictIndependentVerifierTests(unittest.TestCase):
    def test_http_status_requires_an_integer(self):
        claim, capture, policy, reviewed = fixture()
        capture['status'] = 200.0
        out = run_reviewed(claim, capture, policy, reviewed, semantic_manifest(claim, capture))
        self.assertFalse(out['eligible'])
        self.assertFalse(out['checks']['source_authorization'])

    def test_positive_value_cannot_bind_to_signed_or_grouped_number_suffix(self):
        for text, value in (('-1 元', 1), ('− 1 元', 1), ('1,000 元', 0), ('1， 000 元', 0)):
            with self.subTest(text=text):
                self.assertFalse(_value_occurs(text, value, 'CNY'))
        self.assertTrue(_value_occurs('普通票 1 元', 1, 'CNY'))

    def test_unicode_grouped_negative_and_range_amounts_do_not_bind_suffix(self):
        for quote in ("1’100元", "1'100元", "1_100元", "1٬100元", "1 100元",
                      "–100元", "—100元", "‐100元", "﹣100元", "负100元", "亏损100元", "退款100元", "退还100元", "返现：100元", "20万100元"):
            with self.subTest(quote=quote):
                self.assertFalse(_value_occurs(quote, 100, 'CNY'))
        for quote in ("100–200元", "100~200元", "100 至 200元", "100/200元", "100、200元"):
            with self.subTest(quote=quote):
                self.assertFalse(_value_occurs(quote, 200, 'CNY'))
        self.assertTrue(_value_occurs('普通票 100元/晚', 100, 'CNY'))

    def test_float_price_is_rejected_and_decimal_text_must_match_quote_exactly(self):
        claim, capture, policy, reviewed = fixture()
        claim["value"] = 80.0
        float_result = run_reviewed(
            claim, capture, policy, reviewed, semantic_manifest(claim, capture))
        self.assertFalse(float_result["checks"]["value_binding"])
        self.assertFalse(float_result["eligible"])

        amount = "0.100000000000000005"
        exact_quote = f"普通成人票 {amount} 元，适用日期 2026-11-02"
        claim, capture, policy, reviewed = fixture()
        claim["value"] = amount
        claim["quote"] = exact_quote
        capture["response_bytes"] = exact_quote.encode("utf-8")
        digest = hashlib.sha256(capture["response_bytes"]).hexdigest()
        capture["response_sha256"] = claim["response_sha256"] = digest
        accepted = run_reviewed(
            claim, capture, policy, reviewed, semantic_manifest(claim, capture))
        self.assertTrue(accepted["checks"]["value_binding"], accepted)
        self.assertTrue(accepted["eligible"], accepted)

        rounded_quote = "普通成人票 0.1 元，适用日期 2026-11-02"
        claim["quote"] = rounded_quote
        capture["response_bytes"] = rounded_quote.encode("utf-8")
        digest = hashlib.sha256(capture["response_bytes"]).hexdigest()
        capture["response_sha256"] = claim["response_sha256"] = digest
        rejected = run_reviewed(
            claim, capture, policy, reviewed, semantic_manifest(claim, capture))
        self.assertTrue(rejected["checks"]["quote_binding"], rejected)
        self.assertFalse(rejected["checks"]["value_binding"], rejected)
        self.assertFalse(rejected["eligible"], rejected)

    def test_semantic_review_cannot_use_case_variant_of_extractor(self):
        claim, capture, policy, reviewed = fixture()
        capture['extractor_id'] = 'REVIEWER-SEMANTIC-2'
        out = run_reviewed(claim, capture, policy, reviewed, semantic_manifest(claim, capture))
        self.assertFalse(out['eligible'])
        self.assertIn('semantic_reviewer_not_independent_of_extractor', out['reasons'])

    def test_unhashable_or_blank_claim_identifiers_fail_closed(self):
        for field in ('claim_id', 'source_id', 'entity_id', 'license_id'):
            for invalid in ([], {}, '  ', 'unknown', 'ＵＮＫＮＯＷＮ'):
                with self.subTest(field=field, invalid=invalid):
                    claim, capture, policy, reviewed = fixture()
                    claim[field] = invalid
                    out = run_verify(claim, capture, policy, reviewed)
                    self.assertFalse(out['eligible'])
                    self.assertIn('claim_identifier_invalid:' + field, out['reasons'])

    def test_non_string_final_url_fails_closed(self):
        claim, capture, policy, reviewed = fixture()
        capture['final_url'] = []
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out['eligible'])
        self.assertIn('final_url_invalid', out['reasons'])

    def test_final_url_rejects_noncanonical_or_ambiguous_https_forms(self):
        invalid_urls = (
            "https://venue.invalid/ti\ncket",
            "\thttps://venue.invalid/ticket",
            "https://v\u00e9nue.invalid/ticket",
            "https://venue.invalid:8443/ticket",
            "https://venue.invalid/ticket#fragment",
            "http://venue.invalid/ticket",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                claim, capture, policy, reviewed = fixture()
                claim["source_url"] = capture["final_url"] = url
                sem = semantic_manifest(claim, capture)
                out = run_reviewed(claim, capture, policy, reviewed, sem)
                self.assertFalse(out["checks"]["source_authorization"], out)
                self.assertIn("final_url_invalid", out["reasons"])
                self.assertFalse(out["eligible"], out)

    def test_unknown_capture_identity_cannot_be_reviewed_into_identity(self):
        claim, capture, policy, reviewed = fixture()
        capture['entity_id'] = 'unknown'
        reviewed['entity_map'][claim['entity_id']] = 'unknown'
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out['checks']['identity_binding'])
        self.assertFalse(out['eligible'])

    def test_unknown_entity_sentinel_variant_cannot_be_semantically_approved(self):
        claim, capture, policy, reviewed = fixture()
        claim['entity_id'] = 'unknown_entity'
        reviewed['entity_map'] = {'unknown_entity': capture['entity_id']}
        sem = semantic_manifest(claim, capture)
        out = run_reviewed(claim, capture, policy, reviewed, sem)
        self.assertFalse(out['eligible'])

    def test_deeply_nested_policy_fails_closed_without_crashing(self):
        claim, capture, policy, reviewed = fixture()
        pin = canonical_digest(policy)
        value = 'leaf'
        for _ in range(3000):
            value = {'nested': value}
        policy['untrusted_extra'] = value
        out = verify_evidence(claim=claim, capture=capture, policy=policy,
            pinned_policy_sha256=pin, reviewed_bindings=reviewed,
            pinned_reviewed_bindings_sha256=canonical_digest(reviewed), now="2026-10-30T08:00:00Z",
            license_terms_bytes_by_id={'terms-v1': LICENSE_TERMS})
        self.assertFalse(out['eligible'])

    def test_direct_verifier_rejects_claim_url_different_from_capture(self):
        claim, capture, policy, reviewed = fixture()
        claim['source_url'] = 'https://unrelated.invalid/elsewhere'
        sem = semantic_manifest(claim, capture)
        out = run_reviewed(claim, capture, policy, reviewed, sem)
        self.assertFalse(out['eligible'])
        self.assertIn('claim_source_url_capture_final_url_mismatch', out['reasons'])

    def test_challenge_content_cannot_pass_even_with_matching_hashes(self):
        claim, capture, policy, reviewed = fixture()
        raw=('请先登录 '+claim['quote']).encode('utf-8')
        capture['response_bytes']=raw
        capture['response_sha256']=claim['response_sha256']=hashlib.sha256(raw).hexdigest()
        out=run_verify(claim,capture,policy,reviewed)
        self.assertFalse(out['eligible'])
        self.assertIn('obvious_challenge_or_login_marker_present',out['reasons'])
    def test_synthetic_positive_witness_passes_only_mechanical_checks(self):
        out = run_verify(*fixture())
        self.assertFalse(out["eligible"], out)
        self.assertTrue(out["mechanical_checks_pass"], out)
        self.assertTrue(all(out["checks"].values()))
        self.assertFalse(out["truth_certified"])
        self.assertFalse(out["semantic_proof"])
        self.assertIn("audited_semantic_verifier_not_provided", out["reasons"])

    def test_pinned_independent_semantic_review_can_enable_eligible_only(self):
        claim, capture, policy, reviewed = fixture()
        sem = semantic_manifest(claim, capture)
        out = run_reviewed(claim, capture, policy, reviewed, sem)
        self.assertTrue(out["mechanical_checks_pass"], out)
        self.assertTrue(out["semantic_verifier_pass"], out)
        self.assertTrue(out["eligible"], out)
        self.assertFalse(out["truth_certified"])
        self.assertFalse(out["semantic_proof"])
        self.assertFalse(out["independent_corroboration_certified"])

    def test_semantic_review_absence_bad_pin_and_unapproved_decision_stay_ineligible(self):
        claim, capture, policy, reviewed = fixture()
        no_review = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(no_review["eligible"])
        sem = semantic_manifest(claim, capture)
        bad_pin = run_reviewed(claim, capture, policy, reviewed, sem, pin="0" * 64)
        self.assertIn("semantic_review_manifest_pin_missing_or_mismatch", bad_pin["reasons"])
        rejected = semantic_manifest(claim, capture, decision="rejected")
        out = run_reviewed(claim, capture, policy, reviewed, rejected)
        self.assertIn("semantic_review_not_approved", out["reasons"])
        self.assertFalse(out["eligible"])

    def test_semantic_review_binding_must_cover_claim_response_quote_entity_scope_value_and_unit(self):
        for field in ("claim_sha256", "response_sha256", "quote", "entity_id", "scope", "value", "unit"):
            with self.subTest(field=field):
                claim, capture, policy, reviewed = fixture()
                sem = semantic_manifest(claim, capture)
                binding = sem["decisions"][0]["binding"]
                if field == "scope":
                    binding[field]["ticket_type"] = "student"
                elif field == "value":
                    binding[field] = 81
                else:
                    binding[field] = "forged"
                sem["decisions"][0]["binding_sha256"] = canonical_digest(binding)
                out = run_reviewed(claim, capture, policy, reviewed, sem)
                self.assertTrue(out["mechanical_checks_pass"], out)
                self.assertIn("semantic_review_canonical_binding_mismatch", out["reasons"])
                self.assertFalse(out["eligible"])

    def test_reviewer_must_be_authorized_distinct_from_extractor_and_review_after_capture(self):
        claim, capture, policy, reviewed = fixture()
        for sem, expected in (
            (semantic_manifest(claim, capture, reviewer="intruder"), "semantic_reviewer_not_policy_authorized"),
            (semantic_manifest(claim, capture, reviewer="extractor-1"), "semantic_reviewer_not_independent_of_extractor"),
            (semantic_manifest(claim, capture, reviewed_at="2026-10-30T07:00:00Z"), "semantic_review_time_not_after_capture_or_after_now"),
            (semantic_manifest(claim, capture, reviewed_at="2026-10-30T08:01:00Z"), "semantic_review_time_not_after_capture_or_after_now"),
        ):
            out = run_reviewed(claim, capture, policy, reviewed, sem)
            self.assertIn(expected, out["reasons"])
            self.assertFalse(out["eligible"])

    def test_mechanical_failure_blocks_even_approved_semantic_review(self):
        claim, capture, policy, reviewed = fixture()
        sem = semantic_manifest(claim, capture)
        capture["expires_at"] = "2026-10-30T07:59:59Z"
        out = run_reviewed(claim, capture, policy, reviewed, sem)
        self.assertFalse(out["mechanical_checks_pass"])
        self.assertFalse(out["eligible"])
        self.assertIn("semantic_review_blocked_by_mechanical_check_failure", out["reasons"])

    def test_self_asserted_flags_do_not_replace_raw_bytes_or_review(self):
        claim, capture, policy, reviewed = fixture()
        capture.pop("response_bytes")
        claim.update(entity_verified=True, extraction_verified=True, gate_ok=True)
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out["eligible"])
        self.assertIn("response_bytes_missing_or_not_bytes", out["reasons"])

    def test_digest_quote_value_scope_identity_and_policy_fail_closed(self):
        claim, capture, policy, reviewed = fixture()
        claim["value"] = 81
        claim["scope"]["ticket_type"] = "student"
        reviewed["entity_map"]["venue-claim"] = "other"
        capture["response_sha256"] = "0" * 64
        policy["sources"]["operator"]["allowed_hosts"] = ["other.invalid"]
        out = verify_evidence(claim=claim, capture=capture, policy=policy,
            pinned_policy_sha256="wrong-pin", reviewed_bindings=reviewed,
            pinned_reviewed_bindings_sha256=canonical_digest(reviewed),
            license_terms_bytes_by_id={"terms-v1": LICENSE_TERMS},
            now="2026-10-30T08:00:00Z")
        self.assertFalse(out["eligible"])
        for reason in ("policy_pin_missing_or_mismatch", "response_digest_mismatch",
                       "source_not_authorized_for_host_field_or_status",
                       "reviewed_identity_binding_missing_or_mismatch",
                       "reviewed_scope_binding_missing_or_mismatch",
                       "field_value_or_unit_not_bound_by_quote"):
            self.assertIn(reason, out["reasons"])

    def test_scope_binding_uses_recursive_type_strict_comparison(self):
        claim, capture, policy, reviewed = fixture()
        claim["scope"]["party"] = {"size": True}
        reviewed["scope_map"]["c1"] = {
            "travel_date": "2026-11-02", "ticket_type": "ordinary_adult",
            "party": {"size": 1}}
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out["checks"]["scope_binding"])
        self.assertIn("reviewed_scope_binding_missing_or_mismatch", out["reasons"])
        self.assertFalse(out["eligible"])

    def test_scope_binding_rejects_recursive_missing_values_and_accepts_zero_false(self):
        for missing in (None, [], {"size": None}, {"size": []}, {"size": "  "}):
            with self.subTest(missing=missing):
                claim, capture, policy, reviewed = fixture()
                claim["scope"]["party"] = missing
                reviewed["scope_map"]["c1"] = dict(claim["scope"])
                sem = semantic_manifest(claim, capture)
                out = run_reviewed(claim, capture, policy, reviewed, sem)
                self.assertFalse(out["checks"]["scope_binding"])
                self.assertIn("reviewed_scope_binding_incomplete_or_invalid", out["reasons"])
                self.assertFalse(out["eligible"])

        for invalid in (float("nan"),):
            claim, capture, policy, reviewed = fixture()
            claim["scope"]["party"] = {"size": invalid}
            out = run_verify(claim, capture, policy, reviewed)
            self.assertFalse(out["checks"]["scope_binding"])
            self.assertIn("reviewed_scope_binding_incomplete_or_invalid", out["reasons"])
            self.assertFalse(out["eligible"])

        claim, capture, policy, reviewed = fixture()
        cyclic = []
        cyclic.append(cyclic)
        claim["scope"]["party"] = cyclic
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out["checks"]["scope_binding"])
        self.assertIn("reviewed_scope_binding_incomplete_or_invalid", out["reasons"])
        self.assertFalse(out["eligible"])

        claim, capture, policy, reviewed = fixture()
        valid = {"size": 0, "accessible": False}
        claim["scope"]["party"] = valid
        reviewed["scope_map"]["c1"] = dict(claim["scope"])
        sem = semantic_manifest(claim, capture)
        out = run_reviewed(claim, capture, policy, reviewed, sem)
        self.assertTrue(out["checks"]["scope_binding"], out)
        self.assertTrue(out["eligible"], out)

    def test_source_allowlists_require_nonempty_string_lists_and_exact_membership(self):
        for field, invalid in (
            ("allowed_hosts", "notvenue.invalid.evil"),
            ("supports", "surprice"),
            ("allowed_hosts", []),
            ("supports", ["price", ""]),
        ):
            with self.subTest(field=field, invalid=invalid):
                claim, capture, policy, reviewed = fixture()
                policy["sources"]["operator"][field] = invalid
                out = run_verify(claim, capture, policy, reviewed)
                self.assertFalse(out["checks"]["source_authorization"])
                self.assertFalse(out["eligible"])
                reason = ("source_allowed_hosts_invalid" if field == "allowed_hosts"
                          else "source_supports_invalid")
                if field == "allowed_hosts" and invalid == "notvenue.invalid.evil":
                    self.assertIn(reason, out["reasons"])
                elif field == "supports" and invalid == "surprice":
                    self.assertIn(reason, out["reasons"])

    def test_valid_allowlists_use_exact_membership(self):
        for field, values in (("allowed_hosts", ["notvenue.invalid.evil"]),
                              ("supports", ["surprice"])):
            with self.subTest(field=field):
                claim, capture, policy, reviewed = fixture()
                policy["sources"]["operator"][field] = values
                out = run_verify(claim, capture, policy, reviewed)
                self.assertFalse(out["checks"]["source_authorization"])
                self.assertIn("source_not_authorized_for_host_field_or_status", out["reasons"])

    def test_boolean_values_are_not_numeric_price_values(self):
        claim, capture, policy, reviewed = fixture()
        claim["value"] = True
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out["checks"]["value_binding"])

    def test_expired_capture_is_rejected(self):
        claim, capture, policy, reviewed = fixture()
        capture["expires_at"] = "2026-10-30T07:59:59Z"
        out = run_verify(claim, capture, policy, reviewed)
        self.assertIn("freshness_missing_invalid_or_expired", out["reasons"])

    def test_null_terms_digest_and_reviewed_binding_pin_fail(self):
        claim, capture, policy, reviewed = fixture()
        claim["license_terms_sha256"] = None
        out = verify_evidence(claim=claim, capture=capture, policy=policy,
            pinned_policy_sha256=canonical_digest(policy), reviewed_bindings=reviewed,
            pinned_reviewed_bindings_sha256="0" * 64,
            license_terms_bytes_by_id={"terms-v1": LICENSE_TERMS}, now="2026-10-30T08:00:00Z")
        self.assertFalse(out["checks"]["rights"])
        self.assertFalse(out["checks"]["reviewed_bindings_pin"])

    def test_terms_digest_requires_separately_supplied_matching_artifact_bytes(self):
        claim, capture, policy, reviewed = fixture()
        for supplied in (None, {"terms-v1": b"different terms"}, {"other-id": LICENSE_TERMS}):
            with self.subTest(supplied=supplied):
                out = verify_evidence(claim=claim, capture=capture, policy=policy,
                    pinned_policy_sha256=canonical_digest(policy), reviewed_bindings=reviewed,
                    pinned_reviewed_bindings_sha256=canonical_digest(reviewed),
                    license_terms_bytes_by_id=supplied, now="2026-10-30T08:00:00Z")
                self.assertFalse(out["checks"]["rights"])
                self.assertIn("license_terms_artifact_missing_or_digest_mismatch", out["reasons"])

    def test_negated_and_multi_tier_quotes_do_not_bind_value(self):
        for quote in ("普通成人票不适用80元", "成人票80元，学生票40元", "门票免费，成人原价80元"):
            with self.subTest(quote=quote):
                claim, capture, policy, reviewed = fixture()
                capture["response_bytes"] = quote.encode("utf-8")
                digest = hashlib.sha256(capture["response_bytes"]).hexdigest()
                capture["response_sha256"] = claim["response_sha256"] = digest
                claim["quote"] = quote
                out = run_verify(claim, capture, policy, reviewed)
                self.assertFalse(out["checks"]["value_binding"])

    def test_retrieval_time_cannot_stand_in_for_observation_time(self):
        claim, capture, policy, reviewed = fixture()
        claim.pop("observed_at")
        out = run_verify(claim, capture, policy, reviewed)
        self.assertFalse(out["checks"]["freshness"])
        self.assertIn("freshness_missing_invalid_or_expired", out["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
