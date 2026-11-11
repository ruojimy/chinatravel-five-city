import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_independent_verifier import canonical_digest
from shorttrip.strict_review_bridge import StrictReviewBridge

NOW = "2026-10-30T08:00:00Z"
SCOPE = {"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}
QUOTE = "Adult entry 80 元"
FINAL_URL = "https://venue.invalid/ticket"
RAW_TEXT = "Extracted text: " + QUOTE
RESPONSE = ("<html><body>" + QUOTE + "</body></html>").encode("utf-8")
RESPONSE_SHA = hashlib.sha256(RESPONSE).hexdigest()
TEXT_SHA = hashlib.sha256(RAW_TEXT.encode("utf-8")).hexdigest()
LICENSE_TERMS = b"synthetic bridge license terms"
LICENSE_TERMS_SHA = hashlib.sha256(LICENSE_TERMS).hexdigest()


def fixture():
    claim = {"claim_id": "c-1", "evidence_id": "ev-1", "source_id": "operator",
        "entity_id": "venue-claim", "field": "price", "value": 80, "unit": "CNY",
        "quote": QUOTE, "context": dict(SCOPE), "observed_at": "2026-10-30T06:30:00Z",
        "source_url": FINAL_URL, "response_sha256": RESPONSE_SHA,
        "license_id": "terms-1", "license_terms_sha256": LICENSE_TERMS_SHA}
    evidence = {"claim_id": "c-1", "evidence_id": "ev-1", "source_id": "operator",
        "entity_id": "venue-claim", "field": "price", "value": 80, "unit": "CNY",
        "quote": QUOTE, "scope": dict(SCOPE), "source_url": FINAL_URL,
        "final_url": FINAL_URL, "response_sha256": RESPONSE_SHA,
        "raw_text": RAW_TEXT, "raw_sha256": TEXT_SHA}
    capture = {"evidence_id": "ev-1", "source_id": "operator", "entity_id": "venue-source",
        "response_bytes": RESPONSE, "response_sha256": RESPONSE_SHA, "decoder": "utf-8",
        "final_url": FINAL_URL, "status": 200, "extractor_id": "extractor-1",
        "retrieved_at": "2026-10-30T07:00:00Z", "observed_at": claim["observed_at"],
        "expires_at": "2026-11-01T00:00:00Z"}
    policy = {"sources": {"operator": {"allowed_hosts": ["venue.invalid"], "supports": ["price"]}},
        "licenses": {"terms-1": {"status": "approved", "terms_sha256": LICENSE_TERMS_SHA}},
        "semantic_review": {"authorized_reviewer_ids": ["reviewer-2"]}}
    bindings = {"reviewer_id": "identity-reviewer", "entity_map": {"venue-claim": "venue-source"},
        "scope_map": {"c-1": dict(SCOPE)}}
    review_claim = StrictReviewBridge.review_claim(claim, SCOPE)
    binding = {"claim_sha256": canonical_digest(review_claim), "response_sha256": RESPONSE_SHA,
        "quote": QUOTE, "entity_id": "venue-claim", "scope": dict(SCOPE),
        "value": 80, "unit": "CNY"}
    semantic = {"decisions": [{"claim_id": "c-1", "decision": "approved",
        "reviewer_id": "reviewer-2", "reviewed_at": "2026-10-30T07:30:00Z",
        "binding": binding, "binding_sha256": canonical_digest(binding)}]}
    bridge = make_bridge(policy, bindings, semantic, capture)
    registry = {"operator": {"supports": ["price"]}}
    return claim, evidence, capture, policy, bindings, semantic, bridge, registry


def make_bridge(policy, bindings, semantic, capture, *, now=NOW, pin_policy=None,
                pin_bindings=None, pin_semantic=None, captures=None,
                terms_bytes=LICENSE_TERMS):
    return StrictReviewBridge(policy=policy,
        pinned_policy_sha256=canonical_digest(policy) if pin_policy is None else pin_policy,
        reviewed_bindings=bindings,
        pinned_reviewed_bindings_sha256=canonical_digest(bindings) if pin_bindings is None else pin_bindings,
        semantic_review_manifest=semantic,
        pinned_semantic_review_sha256=canonical_digest(semantic) if pin_semantic is None else pin_semantic,
        captures_by_evidence_id={"ev-1": capture} if captures is None else captures,
        license_terms_bytes_by_id=({"terms-1": terms_bytes} if isinstance(terms_bytes, bytes) else {}), now=now)


class StrictReviewBridgeTests(unittest.TestCase):
    def test_positive_independent_callback_keeps_extracted_text_separate_from_response_bytes(self):
        claim, evidence, capture, _, _, _, bridge, registry = fixture()
        self.assertNotEqual(evidence["raw_text"].encode("utf-8"), capture["response_bytes"])
        audit = bridge.audit(claim, evidence, registry, SCOPE)
        self.assertTrue(audit["eligible"], audit)
        self.assertTrue(bridge(claim, evidence, registry, SCOPE))
        self.assertTrue(audit["independent_verification"]["mechanical_checks_pass"])
        self.assertTrue(audit["independent_verification"]["semantic_verifier_pass"])
        self.assertFalse(audit["truth_certified"])
        self.assertFalse(audit["independent_corroboration_certified"])

    def test_missing_pins_or_review_are_never_approved(self):
        claim, evidence, capture, policy, bindings, semantic, _, registry = fixture()
        unconfigured = StrictReviewBridge()
        self.assertFalse(unconfigured(claim, evidence, registry, SCOPE))
        no_semantic = StrictReviewBridge(policy=policy, pinned_policy_sha256=canonical_digest(policy),
            reviewed_bindings=bindings, pinned_reviewed_bindings_sha256=canonical_digest(bindings),
            captures_by_evidence_id={"ev-1": capture},
            license_terms_bytes_by_id={"terms-1": LICENSE_TERMS}, now=NOW)
        self.assertFalse(no_semantic(claim, evidence, registry, SCOPE))
        bad_pin = make_bridge(policy, bindings, semantic, capture, pin_semantic="0" * 64)
        self.assertFalse(bad_pin(claim, evidence, registry, SCOPE))

    def test_license_terms_artifact_bytes_are_required_by_bridge(self):
        claim, evidence, capture, policy, bindings, semantic, _, registry = fixture()
        for terms in (None, b"different terms"):
            bridge = make_bridge(policy, bindings, semantic, capture, terms_bytes=terms)
            audit = bridge.audit(claim, evidence, registry, SCOPE)
            self.assertFalse(audit["eligible"])
            self.assertIn("license_terms_artifact_missing_or_digest_mismatch",
                          audit["independent_verification"]["reasons"])

    def test_claim_evidence_id_source_entity_field_value_unit_quote_and_scope_substitution_fail(self):
        for field, changed in (
            ("claim_id", "other-claim"), ("evidence_id", "other-evidence"),
            ("source_id", "other-source"), ("entity_id", "other-entity"),
            ("field", "opening_hours"), ("value", 81), ("unit", "USD"),
            ("quote", "Different quote"),
        ):
            with self.subTest(field=field):
                claim, evidence, _, _, _, _, bridge, registry = fixture()
                claim[field] = changed
                audit = bridge.audit(claim, evidence, registry, SCOPE)
                self.assertFalse(audit["eligible"])
                self.assertTrue(audit["reasons"])
        claim, evidence, _, _, _, _, bridge, registry = fixture()
        changed_scope = {"travel_date": "2026-11-03", "ticket_type": "ordinary_adult"}
        self.assertFalse(bridge(claim, evidence, registry, changed_scope))

    def test_old_evidence_raw_text_digest_quote_and_response_linkage_are_all_required(self):
        claim, evidence, capture, _, _, _, bridge, registry = fixture()
        for field, value in (("raw_sha256", "0" * 64), ("response_sha256", "0" * 64),
                             ("final_url", "https://venue.invalid/other"),
                             ("source_url", "https://venue.invalid/other"),
                             ("quote", "not in extracted text")):
            with self.subTest(field=field):
                bad = copy.deepcopy(evidence)
                bad[field] = value
                self.assertFalse(bridge(claim, bad, registry, SCOPE))
        no_final_url = dict(evidence)
        no_final_url.pop("final_url")
        self.assertFalse(bridge(claim, no_final_url, registry, SCOPE))
        no_response_link = dict(evidence)
        no_response_link.pop("response_sha256")
        self.assertFalse(bridge(claim, no_response_link, registry, SCOPE))

    def test_legacy_v4_text_alone_cannot_be_promoted_to_response_capture(self):
        claim, evidence, capture, policy, bindings, semantic, _, registry = fixture()
        bridge = make_bridge(policy, bindings, semantic, capture, captures={})
        self.assertFalse(bridge(claim, evidence, registry, SCOPE))
        self.assertIn("separate_raw_response_capture_missing",
                      bridge.audit(claim, evidence, registry, SCOPE)["reasons"])

    def test_callback_registry_scope_and_pinned_source_policy_are_required(self):
        claim, evidence, _, _, _, _, bridge, _ = fixture()
        self.assertFalse(bridge(claim, evidence, {}, SCOPE))
        claim, evidence, _, _, _, _, bridge, registry = fixture()
        self.assertFalse(bridge(claim, evidence, registry, {}))
        registry["operator"]["supports"] = ["coordinates"]
        self.assertFalse(bridge(claim, evidence, registry, SCOPE))

    def test_semantic_review_substitution_fails_even_if_old_extracted_text_is_consistent(self):
        claim, evidence, capture, policy, bindings, semantic, _, registry = fixture()
        claim["value"] = evidence["value"] = 79
        bridge = make_bridge(policy, bindings, semantic, capture)
        audit = bridge.audit(claim, evidence, registry, SCOPE)
        self.assertFalse(audit["eligible"])
        self.assertIn("field_value_or_unit_not_bound_by_quote",
                      audit["independent_verification"]["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
