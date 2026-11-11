import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_v4_evidence import qualify_v4_field_claim

NOW = "2026-10-30T08:00:00Z"


def fixture():
    raw = "普通成人票 80 元，适用日期 2026-11-02"
    ev = {"evidence_id":"ev", "source_id":"operator", "source_url":"https://venue.invalid/ticket",
          "retrieved_at":NOW, "raw_text":raw, "raw_sha256":hashlib.sha256(raw.encode()).hexdigest(),
          "authority":"primary_operator", "licence_status":"allowed", "source_published_at":NOW,
          "source_updated_at":NOW, "observed_at":NOW, "entity_id":"venue", "entity_verified":True}
    claim = {"claim_id":"c", "entity_id":"venue", "entity_verified":True, "evidence_id":"ev",
             "native_field":"price", "field":"price", "value":80, "unit":"CNY", "quote":raw,
             "source_id":"operator", "source_url":ev["source_url"], "observed_at":NOW,
             "retrieved_at":NOW, "valid_until":None,
             "context":{"native_field":"price", "static_reference":True,
                        "scope":{"travel_date":"2026-11-02", "ticket_type":"ordinary_adult"}},
             "licence_status":"allowed", "extraction_verified":True, "conflict":False}
    profiles = {"operator":{"allowed_hosts":["venue.invalid"], "supports":["price"],
                            "authority":"primary_operator", "independence_group":"venue"}}
    return claim, ev, profiles


def qualify(claim, ev, profiles, scope=None, verifier=None):
    return qualify_v4_field_claim(claim, ev, entity_id="venue", native_field="price",
        policy_field="price", requested_scope=scope or {"travel_date":"2026-11-02", "ticket_type":"ordinary_adult"},
        source_profiles=profiles, now=NOW, evidence_verifier=verifier)


class StrictV4EvidenceTests(unittest.TestCase):
    def test_float_price_is_rejected_and_decimal_text_needs_exact_quote_binding(self):
        claim, ev, profiles = fixture()
        claim["value"] = 80.0
        rejected_float = qualify(claim, ev, profiles, verifier=lambda *_: True)
        self.assertFalse(rejected_float["eligible"])
        self.assertIn("invalid_numeric_price_or_cost", rejected_float["reasons"])

        amount = "0.100000000000000005"
        raw = f"普通成人票 {amount} 元，适用日期 2026-11-02"
        claim, ev, profiles = fixture()
        claim["value"] = amount
        claim["quote"] = raw
        ev["raw_text"] = raw
        ev["raw_sha256"] = hashlib.sha256(raw.encode()).hexdigest()

        def exact_quote_verifier(claim_copy, evidence_copy, *_):
            return (claim_copy["value"] in claim_copy["quote"] and
                    claim_copy["quote"] == evidence_copy["raw_text"])

        accepted = qualify(claim, ev, profiles, verifier=exact_quote_verifier)
        self.assertTrue(accepted["eligible"], accepted)

        claim["quote"] = "普通成人票 0.1 元，适用日期 2026-11-02"
        ev["raw_text"] = claim["quote"]
        ev["raw_sha256"] = hashlib.sha256(claim["quote"].encode()).hexdigest()
        rounded_quote = qualify(claim, ev, profiles, verifier=exact_quote_verifier)
        self.assertFalse(rounded_quote["eligible"], rounded_quote)

    def test_callback_cannot_mutate_original_flattened_claim(self):
        claim, ev, profiles = fixture()
        def mutate(*_args):
            claim['value'] = 1
            return True
        out = qualify(claim, ev, profiles, verifier=mutate)
        self.assertFalse(out['eligible'])
        self.assertIn('v4_evidence_original_inputs_mutated', out['reasons'])

    def test_explicit_scope_and_source_mapping_can_pass_mechanical_gate(self):
        claim, ev, profiles = fixture()
        out = qualify(claim, ev, profiles, verifier=lambda *args: True)
        self.assertTrue(out["eligible"], out)
        self.assertFalse(out["truth_certified"])

    def test_scope_mismatch_and_unrequested_dimensions_fail_closed(self):
        claim, ev, profiles = fixture()
        claim["context"]["scope"]["ticket_type"] = "student"
        out = qualify(claim, ev, profiles)
        self.assertFalse(out["eligible"])
        self.assertIn("scope_mismatch:ticket_type", out["reasons"])
        claim, ev, profiles = fixture()
        claim["context"]["scope"]["season"] = "winter"
        out = qualify(claim, ev, profiles)
        self.assertIn("unrequested_scope_dimension:season", out["reasons"])

    def test_unknown_policy_field_or_source_profile_is_not_inferred(self):
        claim, ev, profiles = fixture()
        profiles["operator"]["supports"] = ["coordinates"]
        out = qualify(claim, ev, profiles)
        self.assertIn("source_policy_field_not_authorized", out["reasons"])
        claim, ev, profiles = fixture()
        out = qualify(claim, ev, {})
        self.assertIn("source_profile_missing", out["reasons"])

    def test_supports_string_substring_does_not_authorize_field(self):
        claim, ev, profiles = fixture()
        profiles["operator"]["supports"] = "surprice"
        out = qualify(claim, ev, profiles, verifier=lambda *_: True)
        self.assertFalse(out["eligible"])
        self.assertIn("source_policy_field_not_authorized", out["reasons"])

    def test_cost_to_dynamic_price_mapping_accepts_numeric_and_rejects_invalid_values(self):
        for value in (80, 0):
            with self.subTest(value=value):
                claim, ev, profiles = fixture()
                claim.update(native_field="Cost", field="dynamic_price", value=value)
                claim["context"]["native_field"] = "Cost"
                claim["context"]["scope"] = {
                    "travel_date": "2026-11-02", "party_size": 1}
                ev["value"] = value
                profiles["operator"]["supports"] = ["dynamic_price"]
                out = qualify_v4_field_claim(claim, ev, entity_id="venue",
                    native_field="Cost", policy_field="dynamic_price",
                    requested_scope={"travel_date": "2026-11-02", "party_size": 1},
                    source_profiles=profiles, now=NOW, evidence_verifier=lambda *_: True)
                self.assertTrue(out["eligible"], out)

        for invalid in (True, float("nan"), -1, "01"):
            with self.subTest(invalid=invalid):
                claim, ev, profiles = fixture()
                claim.update(native_field="Cost", field="dynamic_price", value=invalid)
                claim["context"]["native_field"] = "Cost"
                claim["context"]["scope"] = {
                    "travel_date": "2026-11-02", "party_size": 1}
                ev["value"] = invalid
                profiles["operator"]["supports"] = ["dynamic_price"]
                out = qualify_v4_field_claim(claim, ev, entity_id="venue",
                    native_field="Cost", policy_field="dynamic_price",
                    requested_scope={"travel_date": "2026-11-02", "party_size": 1},
                    source_profiles=profiles, now=NOW, evidence_verifier=lambda *_: True)
                self.assertFalse(out["eligible"])
                self.assertIn("invalid_numeric_price_or_cost", out["reasons"])

    def test_catalog_self_assertions_do_not_supply_independent_verification(self):
        claim, ev, profiles = fixture()
        out = qualify(claim, ev, profiles)
        self.assertFalse(out["eligible"])
        self.assertIn("independent_evidence_verifier_required", out["reasons"])

    def test_entity_and_native_field_mismatch_are_distinct(self):
        claim, ev, profiles = fixture()
        claim["entity_id"] = "other"
        claim["native_field"] = "opening"
        out = qualify(claim, ev, profiles)
        self.assertIn("claim_entity_mismatch", out["reasons"])
        self.assertIn("native_field_mismatch", out["reasons"])

    def test_conflicting_original_field_labels_are_rejected_before_mapping(self):
        for location in ("field", "context_native_field"):
            with self.subTest(location=location):
                claim, ev, profiles = fixture()
                if location == "field":
                    claim["field"] = "opening_hours"
                else:
                    claim["context"]["native_field"] = "opening_hours"
                out = qualify(claim, ev, profiles, verifier=lambda *_: True)
                self.assertFalse(out["eligible"])
                wanted = ("claim_field_mapping_mismatch" if location == "field"
                          else "context_native_field_mismatch")
                self.assertIn(wanted, out["reasons"])

    def test_explicit_native_to_policy_mapping_remains_supported(self):
        claim, ev, profiles = fixture()
        raw = "纬度 24.5"
        ev["raw_text"] = raw
        ev["raw_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        claim.update(native_field="lat", field="coordinates", value=24.5,
                     unit="degrees", quote=raw)
        claim["source_url"] = ev["source_url"]
        claim["context"]["native_field"] = "lat"
        profiles["operator"]["supports"] = ["coordinates"]
        out = qualify_v4_field_claim(
            claim, ev, entity_id="venue", native_field="lat", policy_field="coordinates",
            requested_scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult"},
            source_profiles=profiles, now=NOW, evidence_verifier=lambda *_: True)
        self.assertTrue(out["eligible"], out)

    def test_v4_price_and_cost_reject_boolean_nonfinite_and_negative_values(self):
        invalid = (True, False, float("nan"), float("inf"), -1)
        for field in ("price", "Cost"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    claim, ev, profiles = fixture()
                    claim.update(native_field=field, field=field, value=value)
                    claim["context"]["native_field"] = field
                    profiles["operator"]["supports"] = [field]
                    out = qualify_v4_field_claim(
                        claim, ev, entity_id="venue", native_field=field, policy_field=field,
                        requested_scope={"travel_date": "2026-11-02",
                                         "ticket_type": "ordinary_adult"},
                        source_profiles=profiles, now=NOW,
                        evidence_verifier=lambda *_: True)
                    self.assertFalse(out["eligible"])
                    self.assertIn("invalid_numeric_price_or_cost", out["reasons"])

    def test_nested_scope_comparison_is_type_strict(self):
        claim, ev, profiles = fixture()
        claim["context"]["scope"]["party"] = {"size": True}
        out = qualify(claim, ev, profiles,
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult",
                   "party": {"size": 1}}, verifier=lambda *_: True)
        self.assertFalse(out["eligible"])
        self.assertIn("scope_mismatch:party", out["reasons"])

    def test_scope_rejects_nested_missing_values_and_accepts_zero_and_false(self):
        for missing in (None, [], {"size": None}, {"size": []}, {"size": "  "},
                        {"size": float("nan")}):
            with self.subTest(missing=missing):
                claim, ev, profiles = fixture()
                claim["context"]["scope"]["party"] = missing
                scope = {"travel_date": "2026-11-02", "ticket_type": "ordinary_adult",
                         "party": missing}
                out = qualify(claim, ev, profiles, scope=scope, verifier=lambda *_: True)
                self.assertFalse(out["eligible"])
                self.assertIn("requested_scope_incomplete_or_invalid", out["reasons"])

        cyclic = []
        cyclic.append(cyclic)
        claim, ev, profiles = fixture()
        claim["context"]["scope"]["party"] = cyclic
        out = qualify(claim, ev, profiles,
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult",
                   "party": cyclic}, verifier=lambda *_: True)
        self.assertFalse(out["eligible"])
        self.assertIn("requested_scope_incomplete_or_invalid", out["reasons"])

        claim, ev, profiles = fixture()
        valid = {"size": 0, "accessible": False}
        claim["context"]["scope"]["party"] = valid
        out = qualify(claim, ev, profiles,
            scope={"travel_date": "2026-11-02", "ticket_type": "ordinary_adult",
                   "party": valid}, verifier=lambda *_: True)
        self.assertTrue(out["eligible"], out)

    def test_verifier_cannot_mutate_qualified_claim(self):
        import copy
        claim, ev, profiles = fixture()
        original_claim = copy.deepcopy(claim)

        def mutating_verifier(claim_copy, _evidence_copy, _registry_copy, _scope_copy):
            claim_copy["value"] = 800
            return True

        out = qualify(claim, ev, profiles, verifier=mutating_verifier)
        self.assertFalse(out["eligible"])
        self.assertIn("independent_evidence_verifier_required", out["reasons"])
        self.assertEqual(claim, original_claim)


if __name__ == "__main__":
    unittest.main(verbosity=2)
