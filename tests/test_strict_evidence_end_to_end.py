"""End-to-end tests across nested v4 claims, the strict bridge and identity review.

Synthetic positive witnesses test interface wiring only. They do not establish
the truth of any travel fact or authenticate a reviewer/publisher.
"""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.strict_identity_review import IndependentIdentityReview, canonical_digest
from shorttrip.strict_review_bridge import StrictReviewBridge
from shorttrip.strict_v4_evidence import qualify_v4_field_claim
from shorttrip.strict_v4_adapter import diagnose_record

NOW = "2026-10-30T09:00:00Z"
OBSERVED = "2026-10-30T06:30:00Z"
RETRIEVED = "2026-10-30T07:00:00Z"
SCOPE = {"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}
QUOTE = "Adult entry 80 CNY"
URL = "https://venue.invalid/ticket"
RESPONSE = ("<html><body>" + QUOTE + "</body></html>").encode()
RESPONSE_SHA = hashlib.sha256(RESPONSE).hexdigest()
RAW_TEXT = "Extracted: " + QUOTE
RAW_SHA = hashlib.sha256(RAW_TEXT.encode()).hexdigest()
LICENSE_TERMS_BYTES = b"reviewed source terms v1"
TERMS_SHA = hashlib.sha256(LICENSE_TERMS_BYTES).hexdigest()


def witnesses():
    claim = {
        "claim_id": "claim-1", "evidence_id": "evidence-1", "source_id": "operator",
        "entity_id": "venue-1", "native_field": "price", "field": "price",
        "value": 80, "unit": "CNY", "quote": QUOTE, "source_url": URL,
        "response_sha256": RESPONSE_SHA, "observed_at": OBSERVED,
        "retrieved_at": RETRIEVED, "valid_until": "2026-11-01T00:00:00Z",
        "license_id": "license-1", "license_terms_sha256": TERMS_SHA,
        "entity_verified": True, "licence_status": "allowed",
        "extraction_verified": True, "conflict": False,
        "context": {"native_field": "price", "static_reference": True,
                    "scope": dict(SCOPE)},
    }
    evidence = {
        "claim_id": "claim-1", "evidence_id": "evidence-1", "source_id": "operator",
        "entity_id": "venue-1", "entity_verified": True, "field": "price",
        "value": 80, "unit": "CNY", "quote": QUOTE, "scope": dict(SCOPE),
        "source_url": URL, "final_url": URL, "response_sha256": RESPONSE_SHA,
        "observed_at": OBSERVED, "retrieved_at": RETRIEVED,
        "raw_text": RAW_TEXT, "raw_sha256": RAW_SHA,
        "authority": "primary_operator", "licence_status": "allowed",
        "source_published_at": OBSERVED, "source_updated_at": OBSERVED,
    }
    capture = {"evidence_id": "evidence-1", "source_id": "operator",
        "entity_id": "venue-source-1", "response_bytes": RESPONSE,
        "response_sha256": RESPONSE_SHA, "final_url": URL, "status": 200,
        "decoder": "utf-8",
        "extractor_id": "extractor-1", "observed_at": OBSERVED,
        "retrieved_at": RETRIEVED, "expires_at": "2026-11-01T00:00:00Z"}
    policy = {"sources": {"operator": {"allowed_hosts": ["venue.invalid"],
                "supports": ["price"]}},
        "licenses": {"license-1": {"status": "approved", "terms_sha256": TERMS_SHA}},
        "semantic_review": {"authorized_reviewer_ids": ["semantic-reviewer"]}}
    bindings = {"reviewer_id": "binding-reviewer",
        "entity_map": {"venue-1": "venue-source-1"},
        "scope_map": {"claim-1": dict(SCOPE)}}
    bridge_claim = dict(claim, field="price", context=dict(SCOPE))
    review_claim = StrictReviewBridge.review_claim(bridge_claim, SCOPE)
    binding = {"claim_sha256": canonical_digest(review_claim),
        "response_sha256": RESPONSE_SHA, "quote": QUOTE, "entity_id": "venue-1",
        "scope": dict(SCOPE), "value": 80, "unit": "CNY"}
    semantic = {"decisions": [{"claim_id": "claim-1", "decision": "approved",
        "reviewer_id": "semantic-reviewer", "reviewed_at": "2026-10-30T08:00:00Z",
        "binding": binding, "binding_sha256": canonical_digest(binding)}]}
    bridge = StrictReviewBridge(policy=policy, pinned_policy_sha256=canonical_digest(policy),
        reviewed_bindings=bindings, pinned_reviewed_bindings_sha256=canonical_digest(bindings),
        semantic_review_manifest=semantic,
        pinned_semantic_review_sha256=canonical_digest(semantic),
        captures_by_evidence_id={"evidence-1": capture},
        license_terms_bytes_by_id={"license-1": LICENSE_TERMS_BYTES}, now=NOW)
    registry = {"operator": {"supports": ["price"], "allowed_hosts": ["venue.invalid"],
        "authority": "primary_operator", "independence_group": "venue"}}
    record = {"id": "venue-1", "city": "Xiamen", "kind": "attraction",
        "name": "Harbor Garden", "payload": {"data": {"price": 80}},
        "claims": [{"payload": claim, "evidence": evidence}]}
    identity_manifest, identity_captures, identity_terms = _identity_witness(record)
    identity = IndependentIdentityReview(identity_manifest, identity_captures,
        pinned_manifest_sha256=canonical_digest(identity_manifest), now=NOW,
        rights_terms_bytes_by_id={"identity-rights": identity_terms})
    return claim, evidence, capture, bridge, registry, record, identity


def _identity_witness(record):
    raw = b"Official entity registry: HG-42"
    sha = hashlib.sha256(raw).hexdigest()
    url = "https://identity.invalid/entity/HG-42"
    terms_bytes = b"identity rights terms"
    terms = hashlib.sha256(terms_bytes).hexdigest()
    bound = {key: record[key] for key in ("id", "city", "kind", "name")}
    reviewed = {"decision": "same_entity", "record": bound, "source_id": "registry",
        "quote": "HG-42", "reviewer_id": "identity-reviewer",
        "reviewed_at": "2026-10-30T08:00:00Z", "final_url": url,
        "http_status": 200, "rights_id": "identity-rights", "rights_terms_sha256": terms}
    decision = {"entity_id": record["id"], "record": bound, "source_id": "registry",
        "identity_capability": "entity_identity", "rights_id": "identity-rights",
        "rights_terms_sha256": terms, "capture_id": "identity-capture",
        "response_sha256": sha, "final_url": url, "http_status": 200,
        "quote": "HG-42", "observed_at": OBSERVED,
        "valid_from": "2026-10-29T00:00:00Z", "valid_until": "2026-11-01T00:00:00Z",
        "reviewed_binding": reviewed}
    manifest = {"policy": {"identity_review": {"authorized_reviewer_ids": ["identity-reviewer"]}, "sources": {"registry": {
        "allowed_hosts": ["identity.invalid"], "identity_capabilities": ["entity_identity"],
        "rights": {"status": "approved", "rights_id": "identity-rights",
                   "terms_sha256": terms}}}}, "decisions": [decision]}
    captures = {"identity-capture": {"response_bytes": raw, "response_sha256": sha,
        "source_id": "registry", "final_url": url, "status": 200,
        "extractor_id": "identity-extractor",
        "observed_at": OBSERVED, "captured_at": "2026-10-30T07:00:00Z"}}
    return manifest, captures, terms_bytes


class StrictEvidenceEndToEndTests(unittest.TestCase):
    def test_scoped_v4_claim_passes_bridge_and_independent_identity_gates(self):
        claim, evidence, _, bridge, registry, record, identity = witnesses()
        result = qualify_v4_field_claim(claim, evidence, entity_id=record["id"],
            native_field="price", policy_field="price", requested_scope=SCOPE,
            source_profiles=registry, now=NOW, evidence_verifier=bridge)
        self.assertTrue(result["eligible"], result)
        self.assertFalse(result["truth_certified"])
        diagnosed = diagnose_record(record, [{"native_field": "price", "policy_field": "price",
            "scope": SCOPE}], registry=registry, now=NOW, uid="synthetic", evidence_verifier=bridge,
            identity_verifier=identity.adapter_identity_verifier)
        self.assertTrue(diagnosed["identity_independently_verified"], diagnosed)
        # classify() intentionally summarizes the diagnose report and does not
        # expose the original hard_checks list; an adapter planner gap remains.
        self.assertEqual(diagnosed["axes"]["data"], [])
        self.assertEqual(diagnosed["identity_resolution_workflow"], None)
        self.assertEqual(diagnosed["outcome"], "adapter_block")
        self.assertFalse(diagnosed["truth_certified"])
        self.assertFalse(diagnosed["execution_confirmed"])

    def test_scope_value_capture_and_pin_forgery_are_rejected(self):
        claim, evidence, capture, bridge, registry, record, _ = witnesses()
        bad_scope = {"travel_date": "2026-11-03", "ticket_type": "ordinary_adult"}
        rejected = qualify_v4_field_claim(claim, evidence, entity_id=record["id"],
            native_field="price", policy_field="price", requested_scope=bad_scope,
            source_profiles=registry, now=NOW, evidence_verifier=bridge)
        self.assertFalse(rejected["eligible"])

        bad_claim = copy.deepcopy(claim)
        bad_claim["value"] = 81
        rejected = qualify_v4_field_claim(bad_claim, evidence, entity_id=record["id"],
            native_field="price", policy_field="price", requested_scope=SCOPE,
            source_profiles=registry, now=NOW, evidence_verifier=bridge)
        self.assertFalse(rejected["eligible"])

        claim, evidence, capture, bridge, registry, record, _ = witnesses()
        capture["response_bytes"] += b" altered"
        self.assertFalse(bridge(claim, evidence, registry, SCOPE))
        claim, evidence, capture, bridge, registry, record, _ = witnesses()
        badpin = StrictReviewBridge(policy=bridge.policy,
            pinned_policy_sha256=bridge.pinned_policy_sha256,
            reviewed_bindings=bridge.reviewed_bindings,
            pinned_reviewed_bindings_sha256=bridge.pinned_reviewed_bindings_sha256,
            semantic_review_manifest=bridge.semantic_review_manifest,
            pinned_semantic_review_sha256="0" * 64,
            captures_by_evidence_id={"evidence-1": capture},
            license_terms_bytes_by_id={"license-1": LICENSE_TERMS_BYTES}, now=NOW)
        self.assertFalse(badpin(claim, evidence, registry, SCOPE))

    def test_legacy_real_v4_item_is_still_unresolved_without_separate_capture(self):
        from shorttrip.strict_v4_reader import V4Reader
        catalog = ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3"
        reader = V4Reader(catalog)
        try:
            entity_id = reader.db.execute("SELECT id FROM records ORDER BY id LIMIT 1").fetchone()[0]
            record = reader.get(entity_id)
        finally:
            reader.close()
        if not record["claims"]:
            self.skipTest("selected frozen catalog record has no claims")
        # The legacy row is genuine local v4 data, but lacks the independently
        # supplied capture/review package in this test; do not synthesize one.
        item = record["claims"][0]
        claim, evidence = item["payload"], item["evidence"]
        scope = claim.get("context", {}).get("scope", {})
        if not scope:
            scope = {"travel_date": "2026-11-02"}
        field = claim.get("native_field")
        result = qualify_v4_field_claim(claim, evidence, entity_id=record["id"],
            native_field=field, policy_field=field, requested_scope=scope,
            source_profiles={claim.get("source_id"): {"supports": [field],
                "allowed_hosts": ["invalid.local"]}}, now=NOW,
            evidence_verifier=StrictReviewBridge())
        self.assertFalse(result["eligible"], result)
        self.assertFalse(result["truth_certified"])
        # Legacy records may already contain contradictory field labels. That
        # mapping conflict must block before the missing-verifier check.
        from shorttrip.strict_scope import scope_is_complete
        if not scope_is_complete(scope):
            self.assertIn('requested_scope_incomplete_or_invalid', result['reasons'])
        elif claim.get("field") not in (None, field):
            self.assertIn("claim_field_mapping_mismatch", result["reasons"])
        else:
            self.assertIn("independent_evidence_verifier_required", result["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
