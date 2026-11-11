import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_evidence import qualify_field_evidence
from shorttrip.strict_scope import scope_is_complete

NOW = "2026-10-30T08:00:00Z"
RAW = "普通成人票 80 元，适用日期 2026-11-02"


def fixture():
    evidence = {
        "evidence_id": "ev-1", "source_id": "operator", "source_url": "https://venue.invalid/ticket",
        "retrieved_at": NOW, "raw_text": RAW, "raw_sha256": hashlib.sha256(RAW.encode()).hexdigest(),
        "authority": "primary_operator", "licence_status": "allowed", "source_published_at": NOW,
        "source_updated_at": NOW, "observed_at": NOW, "entity_id": "venue-1",
        "entity_verified": True,
    }
    claim = {
        "claim_id": "claim-1", "entity_id": "venue-1", "entity_verified": True,
        "evidence_id": "ev-1", "field": "price", "value": 80, "unit": "CNY",
        "quote": RAW, "source_id": "operator", "source_url": evidence["source_url"],
        "observed_at": NOW, "retrieved_at": NOW, "valid_until": None,
        "context": {"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"},
        "licence_status": "allowed", "extraction_verified": True, "conflict": False,
    }
    registry = {"operator": {"allowed_hosts": ["venue.invalid"], "supports": ["price"],
                             "authority": "primary_operator", "independence_group": "venue"}}
    return claim, {"ev-1": evidence}, registry


def qualify(claim, evidence, registry, **kwargs):
    return qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
                                  scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"},
                                  now=NOW, **kwargs)


class StrictEvidenceTests(unittest.TestCase):
    def test_float_price_is_rejected_and_decimal_text_needs_exact_quote_binding(self):
        claim, evidence, registry = fixture()
        claim["value"] = 80.0
        rejected_float = qualify(claim, evidence, registry,
                                 evidence_verifier=lambda *_: True)
        self.assertFalse(rejected_float["eligible"])
        self.assertIn("invalid_numeric_price_or_cost", rejected_float["reasons"])

        amount = "0.100000000000000005"
        raw = f"普通成人票 {amount} 元，适用日期 2026-11-02"
        claim, evidence, registry = fixture()
        claim["value"] = amount
        claim["quote"] = raw
        evidence["ev-1"]["raw_text"] = raw
        evidence["ev-1"]["raw_sha256"] = hashlib.sha256(raw.encode()).hexdigest()

        def exact_quote_verifier(claim_copy, evidence_copy, *_):
            return (claim_copy["value"] in claim_copy["quote"] and
                    claim_copy["quote"] == evidence_copy["raw_text"])

        accepted = qualify(claim, evidence, registry,
                           evidence_verifier=exact_quote_verifier)
        self.assertTrue(accepted["eligible"], accepted)

        claim["quote"] = "普通成人票 0.1 元，适用日期 2026-11-02"
        evidence["ev-1"]["raw_text"] = claim["quote"]
        evidence["ev-1"]["raw_sha256"] = hashlib.sha256(
            claim["quote"].encode()).hexdigest()
        rounded_quote = qualify(claim, evidence, registry,
                                evidence_verifier=exact_quote_verifier)
        self.assertFalse(rounded_quote["eligible"], rounded_quote)

    def test_verifier_closure_cannot_mutate_original_evidence(self):
        claim, evidence, registry = fixture()
        def mutate(*_args):
            evidence['ev-1']['entity_id'] = 'other'
            return True
        result = qualify(claim, evidence, registry, evidence_verifier=mutate)
        self.assertFalse(result['eligible'])
        self.assertIn('evidence_original_inputs_mutated', result['reasons'])

    def test_unknown_identifier_inside_context_is_not_qualified(self):
        claim, evidence, registry = fixture()
        claim['context']['origin_id'] = 'unresolved_id'
        result = qualify_field_evidence(claim, evidence, registry, field='price', entity_id='venue-1',
            scope=claim['context'], now=NOW, evidence_verifier=lambda *_: True)
        self.assertFalse(result['eligible'])
        self.assertIn('requested_scope_incomplete_or_invalid', result['reasons'])

    def test_invalid_claim_identifiers_do_not_crash_or_qualify(self):
        for field in ('claim_id', 'evidence_id', 'source_id'):
            for invalid in ([], 'unknown'):
                with self.subTest(field=field, invalid=invalid):
                    claim, evidence, registry = fixture()
                    claim[field] = invalid
                    result = qualify(claim, evidence, registry, evidence_verifier=lambda *_: True)
                    self.assertFalse(result['eligible'])
                    self.assertIn('claim_identifier_invalid:' + field, result['reasons'])

    def test_unknown_entity_cannot_be_accepted_by_matching_claim_and_evidence(self):
        claim, evidence, registry = fixture()
        claim['entity_id'] = evidence['ev-1']['entity_id'] = 'unknown'
        result = qualify_field_evidence(claim, evidence, registry, field='price', entity_id='unknown',
            scope=claim['context'], now=NOW, evidence_verifier=lambda *_: True)
        self.assertFalse(result['eligible'])
        self.assertIn('requested_entity_missing', result['reasons'])

    def test_unknown_entity_sentinel_variant_cannot_be_accepted_by_matching_evidence(self):
        claim, evidence, registry = fixture()
        sentinel = 'unknown_entity'
        claim['entity_id'] = evidence['ev-1']['entity_id'] = sentinel
        result = qualify_field_evidence(claim, evidence, registry, field='price', entity_id=sentinel,
            scope=claim['context'], now=NOW, evidence_verifier=lambda *_: True)
        self.assertFalse(result['eligible'])

    def test_deeply_nested_malformed_claim_fails_closed_without_crashing(self):
        claim, evidence, registry = fixture()
        value = 'leaf'
        for _ in range(3000):
            value = {'nested': value}
        claim['untrusted_extra'] = value
        result = qualify_field_evidence(claim, evidence, registry, field='price', entity_id='venue-1',
            scope=claim['context'], now=NOW, evidence_verifier=lambda *_: True)
        self.assertFalse(result['eligible'])

    def test_valid_mechanical_evidence_is_eligible_but_not_truth_certified(self):
        claim, evidence, registry = fixture()
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW,
            evidence_verifier=lambda claim,evidence,registry,scope: True)
        self.assertTrue(result["structural_ok"], result)
        self.assertTrue(result["eligible"], result)
        self.assertFalse(result["truth_certified"])

    def test_self_asserted_flags_alone_do_not_qualify(self):
        claim, evidence, registry = fixture()
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result['eligible'])
        self.assertIn('independent_evidence_verifier_required', result['reasons'])

    def test_structural_claim_without_identity_binding_is_rejected(self):
        claim, evidence, registry = fixture()
        claim["entity_verified"] = False
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("identity_not_verified", result["reasons"])

    def test_wrong_entity_and_branch_evidence_rejected(self):
        claim, evidence, registry = fixture()
        claim["entity_id"] = "venue-2"
        evidence["ev-1"]["entity_id"] = "venue-2"
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("wrong_entity", result["reasons"])

    def test_wrong_ticket_scope_rejected_even_when_quote_contains_a_price(self):
        claim, evidence, registry = fixture()
        claim["context"]["ticket_type"] = "student"
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("scope_mismatch:ticket_type", result["reasons"])

    def test_unsupported_provider_and_unknown_license_rejected(self):
        claim, evidence, registry = fixture()
        registry["operator"]["supports"] = ["coordinates"]
        evidence["ev-1"]["licence_status"] = "unknown"
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("source_not_authorized_for_field", result["reasons"])
        self.assertIn("licence_not_explicitly_allowed", result["reasons"])

    def test_supports_string_substring_does_not_authorize_field(self):
        claim, evidence, registry = fixture()
        registry["operator"]["supports"] = "surprice"
        result = qualify_field_evidence(claim, evidence, registry, field="price",
            entity_id="venue-1", scope={"travel_date": "2026-11-02",
                "ticket_type": "ordinary_adult"}, now=NOW,
            evidence_verifier=lambda *_: True)
        self.assertFalse(result["eligible"])
        self.assertIn("source_supports_invalid", result["reasons"])
        self.assertIn("source_not_authorized_for_field", result["reasons"])

    def test_dynamic_price_requires_finite_nonnegative_numeric_value(self):
        import hashlib
        for invalid in (True, float("nan"), -1, "01"):
            with self.subTest(invalid=invalid):
                claim, evidence, registry = fixture()
                claim["field"] = "dynamic_price"
                claim["value"] = invalid
                claim["context"] = {"travel_date": "2026-11-02", "party_size": 1}
                registry["operator"]["supports"] = ["dynamic_price"]
                result = qualify_field_evidence(claim, evidence, registry,
                    field="dynamic_price", entity_id="venue-1",
                    scope={"travel_date": "2026-11-02", "party_size": 1}, now=NOW,
                    evidence_verifier=lambda *_: True)
                self.assertFalse(result["eligible"])
                self.assertIn("invalid_numeric_price_or_cost", result["reasons"])

        claim, evidence, registry = fixture()
        raw = "成人票免费，0元"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        claim.update(field="dynamic_price", value=0, quote=raw,
                     context={"travel_date": "2026-11-02", "party_size": 1})
        evidence["ev-1"].update(raw_text=raw, raw_sha256=digest)
        registry["operator"]["supports"] = ["dynamic_price"]
        result = qualify_field_evidence(claim, evidence, registry,
            field="dynamic_price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "party_size": 1}, now=NOW,
            evidence_verifier=lambda *_: True)
        self.assertTrue(result["eligible"], result)

    def test_unverified_extraction_and_known_conflict_rejected(self):
        claim, evidence, registry = fixture()
        claim["extraction_verified"] = False
        claim["conflict"] = True
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("extraction_not_verified", result["reasons"])
        self.assertIn("known_conflict", result["reasons"])

    def test_empty_scope_and_unrequested_context_dimension_fail_closed(self):
        claim, evidence, registry = fixture()
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
                                        scope={}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("requested_scope_empty", result["reasons"])
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02"}, now=NOW)
        self.assertFalse(result["eligible"])
        self.assertIn("unrequested_scope_dimension:ticket_type", result["reasons"])

    def test_expired_evidence_is_not_eligible(self):
        claim, evidence, registry = fixture()
        claim["observed_at"] = "2026-10-28T08:00:00Z"
        evidence["ev-1"]["observed_at"] = claim["observed_at"]
        result = qualify_field_evidence(claim, evidence, registry, field="price", entity_id="venue-1",
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"}, now=NOW)
        self.assertFalse(result["eligible"])

    def test_verifier_mutation_is_isolated_and_fails_closed(self):
        import copy
        claim, evidence, registry = fixture()
        original_claim = copy.deepcopy(claim)
        original_evidence = copy.deepcopy(evidence)

        def mutating_verifier(claim_copy, evidence_copy, _registry_copy, _scope_copy):
            claim_copy["value"] = 800
            evidence_copy["raw_text"] = "forged text"
            return True

        result = qualify(claim, evidence, registry, evidence_verifier=mutating_verifier)
        self.assertFalse(result["eligible"])
        self.assertIn("independent_evidence_verifier_required", result["reasons"])
        self.assertEqual(claim, original_claim)
        self.assertEqual(evidence, original_evidence)

    def test_nested_scope_comparison_is_type_strict(self):
        claim, evidence, registry = fixture()
        claim["context"]["party"] = {"size": True}
        result = qualify_field_evidence(claim, evidence, registry, field="price",
            entity_id="venue-1", scope={"travel_date": "2026-11-02",
                "ticket_type": "ordinary_adult", "party": {"size": 1}}, now=NOW,
            evidence_verifier=lambda *_: True)
        self.assertFalse(result["eligible"])
        self.assertIn("scope_mismatch:party", result["reasons"])

    def test_scope_rejects_recursive_missing_values_and_accepts_zero_and_false(self):
        for missing in (None, [], {"size": None}, {"size": []}, {"size": "  "},
                        {"size": float("nan")}):
            with self.subTest(missing=missing):
                claim, evidence, registry = fixture()
                claim["context"]["party"] = missing
                scope = {**claim["context"], "party": missing}
                result = qualify_field_evidence(claim, evidence, registry, field="price",
                    entity_id="venue-1", scope=scope, now=NOW,
                    evidence_verifier=lambda *_: True)
                self.assertFalse(result["eligible"])
                self.assertIn("requested_scope_incomplete_or_invalid", result["reasons"])

        claim, evidence, registry = fixture()
        valid = {"size": 0, "accessible": False}
        claim["context"]["party"] = valid
        scope = {**claim["context"], "party": valid}
        result = qualify_field_evidence(claim, evidence, registry, field="price",
            entity_id="venue-1", scope=scope, now=NOW, evidence_verifier=lambda *_: True)
        self.assertTrue(result["eligible"], result)

        cyclic = []
        cyclic.append(cyclic)
        self.assertFalse(scope_is_complete({"party": cyclic}))

    def test_price_and_cost_require_finite_nonnegative_numeric_values(self):
        invalid = (True, False, float("nan"), float("inf"), -1, "01")
        for field in ("price", "Cost"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    claim, evidence, registry = fixture()
                    claim["field"] = field
                    claim["value"] = value
                    registry["operator"]["supports"] = [field]
                    result = qualify_field_evidence(
                        claim, evidence, registry, field=field, entity_id="venue-1",
                        scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"},
                        now=NOW, evidence_verifier=lambda *_: True)
                    self.assertFalse(result["eligible"])
                    self.assertIn("invalid_numeric_price_or_cost", result["reasons"])

        claim, evidence, registry = fixture()
        claim["value"] = 0
        result = qualify(claim, evidence, registry, evidence_verifier=lambda *_: True)
        self.assertTrue(result["eligible"], result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
