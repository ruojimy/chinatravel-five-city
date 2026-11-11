import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_identity_review import IndependentIdentityReview, canonical_digest

NOW = "2026-10-30T09:00:00Z"
RECORD = {"id": "r-1", "city": "Xiamen", "kind": "attraction", "name": "Harbor Garden"}
RAW = b"Source page: Harbor Garden in Xiamen. Entity code HG-42."
SHA = hashlib.sha256(RAW).hexdigest()
TERMS_BYTES = b"identity source terms v1"
TERMS_SHA = hashlib.sha256(TERMS_BYTES).hexdigest()
FINAL_URL = "https://identity.example/entities/HG-42"


def fixture():
    binding = {"decision": "same_entity", "record": dict(RECORD), "source_id": "registry-a",
               "quote": "Entity code HG-42", "reviewer_id": "reviewer-7",
               "reviewed_at": "2026-10-30T08:00:00Z", "final_url": FINAL_URL,
               "http_status": 200, "rights_id": "identity-terms-v1",
               "rights_terms_sha256": TERMS_SHA}
    decision = {"entity_id": RECORD["id"], "record": dict(RECORD),
                "source_id": "registry-a", "identity_capability": "entity_identity",
                "rights_id": "identity-terms-v1", "rights_terms_sha256": TERMS_SHA,
                "capture_id": "capture-1", "response_sha256": SHA,
                "final_url": FINAL_URL, "http_status": 200,
                "quote": "Entity code HG-42", "observed_at": "2026-10-29T10:00:00Z",
                "valid_from": "2026-10-29T00:00:00Z", "valid_until": "2026-11-01T00:00:00Z",
                "reviewed_binding": binding}
    manifest = {"policy": {"identity_review": {"authorized_reviewer_ids": ["reviewer-7"]}, "sources": {"registry-a": {
                    "allowed_hosts": ["identity.example"],
                    "identity_capabilities": ["entity_identity"],
                    "rights": {"status": "approved", "rights_id": "identity-terms-v1",
                               "terms_sha256": TERMS_SHA}}}},
                "decisions": [decision]}
    capture = {"response_bytes": RAW, "response_sha256": SHA, "source_id": "registry-a",
               "final_url": FINAL_URL, "status": 200,
               "extractor_id": "extractor-1",
               "observed_at": decision["observed_at"], "captured_at": "2026-10-30T07:00:00Z"}
    return manifest, {"capture-1": capture}


def verifier(manifest=None, captures=None, pin=None, now=NOW):
    manifest, captures = fixture() if manifest is None else (manifest, captures)
    return IndependentIdentityReview(manifest, captures,
        pinned_manifest_sha256=canonical_digest(manifest) if pin is None else pin, now=now,
        rights_terms_bytes_by_id={"identity-terms-v1": TERMS_BYTES})


class IndependentIdentityReviewTests(unittest.TestCase):
    def test_capture_and_review_http_statuses_require_integers(self):
        for target in ('capture', 'decision', 'binding'):
            manifest, captures = fixture()
            if target == 'capture':
                captures['capture-1']['status'] = 200.0
            elif target == 'decision':
                manifest['decisions'][0]['http_status'] = 200.0
            else:
                manifest['decisions'][0]['reviewed_binding']['http_status'] = 200.0
            with self.subTest(target=target):
                self.assertFalse(verifier(manifest, captures).verify_record(RECORD)['verified'])

    def test_unknown_identity_and_malformed_manifest_identifiers_fail_closed(self):
        for field in ('id', 'city', 'kind', 'name'):
            result = verifier().verify_record(dict(RECORD, **{field: 'unknown'}))
            self.assertFalse(result['verified'])
            self.assertIn('record_identity_fields_missing_or_invalid', result['reasons'])
        self.assertFalse(verifier().verify_entity_id('unknown')['verified'])
        for field in ('source_id', 'capture_id'):
            manifest, captures = fixture()
            manifest['decisions'][0][field] = []
            result = verifier(manifest, captures).verify_record(RECORD)
            self.assertFalse(result['verified'])
        manifest, captures = fixture()
        decision = manifest['decisions'][0]
        captures['unknown'] = captures.pop('capture-1')
        decision['capture_id'] = 'unknown'
        self.assertIn('raw_capture_missing', verifier(manifest, captures).verify_record(RECORD)['reasons'])
        manifest, captures = fixture()
        manifest['decisions'][0]['reviewed_binding']['reviewer_id'] = 'unknown'
        self.assertIn('reviewer_identity_missing', verifier(manifest, captures).verify_record(RECORD)['reasons'])

    def test_unknown_entity_sentinel_variant_cannot_be_reviewed_into_identity(self):
        manifest, captures = fixture()
        sentinel_record = dict(RECORD, id='unknown_entity')
        decision = manifest['decisions'][0]
        decision['entity_id'] = 'unknown_entity'
        decision['record'] = dict(sentinel_record)
        decision['reviewed_binding']['record'] = dict(sentinel_record)
        out = verifier(manifest, captures).verify_record(sentinel_record)
        self.assertFalse(out['verified'])

    def test_deeply_nested_manifest_fails_closed_without_crashing(self):
        manifest, captures = fixture()
        pin = canonical_digest(manifest)
        value = 'leaf'
        for _ in range(3000):
            value = {'nested': value}
        manifest['untrusted_extra'] = value
        out = IndependentIdentityReview(manifest, captures,
            pinned_manifest_sha256=pin, now=NOW,
            rights_terms_bytes_by_id={'identity-terms-v1': TERMS_BYTES}).verify_record(RECORD)
        self.assertFalse(out['verified'])

    def test_review_by_capture_extractor_is_not_independent(self):
        manifest, captures = fixture()
        reviewer_id = manifest['decisions'][0]['reviewed_binding']['reviewer_id']
        captures['capture-1']['extractor_id'] = reviewer_id
        out = verifier(manifest, captures).verify_record(RECORD)
        self.assertFalse(out['verified'])

    def test_unlisted_review_identity_is_not_authorized(self):
        manifest, captures = fixture()
        manifest['decisions'][0]['reviewed_binding']['reviewer_id'] = 'unlisted-reviewer'
        out = verifier(manifest, captures).verify_record(RECORD)
        self.assertFalse(out['verified'])

    def test_independent_identity_review_requires_policy_extractor_and_later_time(self):
        manifest, captures = fixture()
        del manifest['policy']['identity_review']
        self.assertIn('identity_reviewer_not_policy_authorized',
                      verifier(manifest, captures).verify_record(RECORD)['reasons'])
        manifest, captures = fixture()
        del captures['capture-1']['extractor_id']
        self.assertIn('identity_capture_extractor_missing',
                      verifier(manifest, captures).verify_record(RECORD)['reasons'])
        manifest, captures = fixture()
        captures['capture-1']['extractor_id'] = 'REVIEWER-7'
        self.assertIn('identity_reviewer_not_independent_of_extractor',
                      verifier(manifest, captures).verify_record(RECORD)['reasons'])
        manifest, captures = fixture()
        manifest['decisions'][0]['reviewed_binding']['reviewed_at'] = captures['capture-1']['captured_at']
        self.assertIn('observation_review_or_validity_time_invalid',
                      verifier(manifest, captures).verify_record(RECORD)['reasons'])

    def test_positive_adapter_and_gap_queue_wrappers(self):
        v = verifier()
        record = dict(RECORD, payload={"entity_verified": False})
        self.assertTrue(v.adapter_identity_verifier(record))
        self.assertTrue(v.verify_record(record)["verified"])
        gap = {"entity_id": RECORD["id"], "entity_identity_verified": True}
        self.assertTrue(v.gap_queue_identity_verifier(gap))
        self.assertFalse(v.verify_record(record)["real_world_identity_certified"])
        self.assertIn("not proof of no challenge", v.verify_record(record)["challenge_screening"])

    def test_exact_record_identity_fields_are_required(self):
        v = verifier()
        for field, value in (("id", "other"), ("city", "Ningbo"),
                             ("kind", "poi"), ("name", "Harbor Park")):
            with self.subTest(field=field):
                altered = dict(RECORD, **{field: value})
                result = v.verify_record(altered)
                self.assertFalse(result["verified"])
                expected = "review_decision_missing_or_ambiguous" if field == "id" else "reviewed_record_identity_mismatch"
                self.assertIn(expected, result["reasons"])

    def test_pinned_manifest_is_mandatory_and_covers_policy_and_decision(self):
        manifest, captures = fixture()
        v = verifier(manifest, captures, pin="0" * 64)
        self.assertFalse(v.adapter_identity_verifier(RECORD))
        self.assertIn("review_manifest_pin_missing_or_mismatch", v.verify_record(RECORD)["reasons"])
        changed = copy.deepcopy(manifest)
        changed["policy"]["sources"]["registry-a"]["identity_capabilities"] = []
        v = verifier(changed, captures, pin=canonical_digest(manifest))
        self.assertIn("review_manifest_pin_missing_or_mismatch", v.verify_record(RECORD)["reasons"])

    def test_missing_or_bad_capture_digest_and_quote_fail_closed(self):
        manifest, captures = fixture()
        self.assertIn("raw_capture_missing", verifier(manifest, {}).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(captures)
        bad["capture-1"]["response_bytes"] = "not raw bytes"
        self.assertIn("raw_capture_bytes_missing_or_not_bytes",
                      verifier(manifest, bad).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(captures)
        bad["capture-1"]["response_sha256"] = "0" * 64
        self.assertIn("raw_capture_digest_mismatch",
                      verifier(manifest, bad).verify_record(RECORD)["reasons"])
        bad_manifest = copy.deepcopy(manifest)
        bad_manifest["decisions"][0]["quote"] = "not in capture"
        bad_manifest["decisions"][0]["reviewed_binding"]["quote"] = "not in capture"
        result = verifier(bad_manifest, captures).verify_record(RECORD)
        self.assertIn("review_quote_not_in_raw_capture", result["reasons"])

    def test_source_identifier_capability_host_and_binding_are_checked(self):
        manifest, captures = fixture()
        bad = copy.deepcopy(manifest)
        bad["decisions"][0]["identity_capability"] = "price"
        self.assertIn("source_identity_capability_not_authorized",
                      verifier(bad, captures).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(captures)
        bad["capture-1"]["final_url"] = "https://elsewhere.example/e"
        self.assertIn("capture_host_not_authorized_for_identity",
                      verifier(manifest, bad).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(captures)
        bad["capture-1"]["source_id"] = "other-source"
        self.assertIn("capture_source_id_mismatch",
                      verifier(manifest, bad).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(manifest)
        bad["decisions"][0]["reviewed_binding"]["record"]["name"] = "Different Name"
        self.assertIn("reviewed_binding_record_mismatch",
                      verifier(bad, captures).verify_record(RECORD)["reasons"])

    def test_final_url_rejects_noncanonical_or_ambiguous_https_forms(self):
        invalid_urls = (
            "https://identity.example/ent\nities/HG-42",
            "\thttps://identity.example/entities/HG-42",
            "https://identit\u00e9.example/entities/HG-42",
            "https://identity.example:8443/entities/HG-42",
            "https://identity.example/entities/HG-42#fragment",
            "http://identity.example/entities/HG-42",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                manifest, captures = fixture()
                decision = manifest["decisions"][0]
                decision["final_url"] = url
                decision["reviewed_binding"]["final_url"] = url
                captures["capture-1"]["final_url"] = url
                out = verifier(manifest, captures).verify_record(RECORD)
                self.assertIn("capture_final_url_invalid", out["reasons"])
                self.assertFalse(out["verified"], out)

    def test_http_success_rights_terms_and_exact_reviewed_url_are_required(self):
        manifest, captures = fixture()
        bad = copy.deepcopy(captures)
        bad["capture-1"]["status"] = 302
        result = verifier(manifest, bad).verify_record(RECORD)
        self.assertIn("capture_http_status_not_success", result["reasons"])
        self.assertIn("reviewed_http_status_capture_mismatch", result["reasons"])
        bad = copy.deepcopy(manifest)
        bad["policy"]["sources"]["registry-a"]["rights"]["terms_sha256"] = None
        self.assertIn("source_rights_terms_not_approved_or_mismatched",
                      verifier(bad, captures).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(manifest)
        bad["decisions"][0]["final_url"] = "https://identity.example/other"
        self.assertIn("reviewed_final_url_capture_mismatch",
                      verifier(bad, captures).verify_record(RECORD)["reasons"])
        bad = copy.deepcopy(captures)
        bad["capture-1"]["final_url"] = "https://identity.example/alternate"
        self.assertIn("reviewed_final_url_capture_mismatch",
                      verifier(manifest, bad).verify_record(RECORD)["reasons"])

    def test_rights_digest_requires_separately_supplied_matching_terms_bytes(self):
        manifest, captures = fixture()
        for terms in (None, {"identity-terms-v1": b"different terms"}, {"wrong-id": TERMS_BYTES}):
            with self.subTest(terms=terms):
                v = IndependentIdentityReview(manifest, captures,
                    pinned_manifest_sha256=canonical_digest(manifest), now=NOW,
                    rights_terms_bytes_by_id=terms)
                result = v.verify_record(RECORD)
                self.assertFalse(result["verified"])
                self.assertIn("source_rights_terms_artifact_missing_or_digest_mismatch",
                              result["reasons"])

    def test_deterministically_detected_challenge_or_login_content_is_rejected(self):
        manifest, captures = fixture()
        raw = b"<title>Just a moment</title> Entity code HG-42"
        sha = hashlib.sha256(raw).hexdigest()
        captures["capture-1"]["response_bytes"] = raw
        captures["capture-1"]["response_sha256"] = sha
        manifest["decisions"][0]["response_sha256"] = sha
        result = verifier(manifest, captures).verify_record(RECORD)
        self.assertIn("obvious_challenge_or_login_marker_present", result["reasons"])
        self.assertFalse(result["verified"])

    def test_review_outcome_reviewer_and_time_validity_are_mandatory(self):
        manifest, captures = fixture()
        for mutate, expected in (
            (lambda d: d["reviewed_binding"].update(decision="uncertain"), "review_decision_not_same_entity"),
            (lambda d: d["reviewed_binding"].update(reviewer_id=""), "reviewer_identity_missing"),
            (lambda d: d.update(valid_until="2026-10-30T08:59:00Z"), "observation_review_or_validity_time_invalid"),
            (lambda d: d.update(observed_at="2026-10-30T10:00:00"), "observation_review_or_validity_time_invalid"),
        ):
            bad = copy.deepcopy(manifest)
            mutate(bad["decisions"][0])
            result = verifier(bad, captures).verify_record(RECORD)
            self.assertIn(expected, result["reasons"])

    def test_gap_wrapper_uses_only_pinned_entity_binding_and_requires_adapter_gate(self):
        v = verifier()
        self.assertFalse(v.gap_queue_identity_verifier({"entity_id": RECORD["id"]}))
        self.assertFalse(v.gap_queue_identity_verifier({"entity_id": "other", "entity_identity_verified": True}))
        self.assertTrue(v.gap_queue_identity_verifier(
            {"entity_id": RECORD["id"], "entity_identity_verified": True}))

    def test_duplicate_decisions_are_ambiguous(self):
        manifest, captures = fixture()
        manifest["decisions"].append(copy.deepcopy(manifest["decisions"][0]))
        result = verifier(manifest, captures).verify_record(RECORD)
        self.assertIn("review_decision_missing_or_ambiguous", result["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
