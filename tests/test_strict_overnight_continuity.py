import copy
import unittest

from shorttrip.strict_overnight_continuity import check_overnight_continuity


def fixture():
    requirement = {
        "entity_id": "hotel-1", "room_type": "twin", "check_in": "2026-11-15",
        "check_out": "2026-11-17", "rooms": 1, "guests_per_room": 2,
        "minimum_beds": 2, "eligibility": "standard", "meal_plan": "none",
        "taxes_included": True, "mandatory_fees_included": True,
    }
    claim = {
        "entity_id": "hotel-1", "room_type": "twin", "check_in": "2026-11-15",
        "check_out": "2026-11-17", "guests_per_room": 2, "currency": "CNY",
        "unit": "CNY/room/night", "rate": 300, "beds": 2,
        "max_guests_per_room": 2, "eligibility": "standard", "meal_plan": "none",
        "taxes_included": True, "mandatory_fees_included": True,
    }
    boundary = {
        "previous_day": "2026-11-15", "next_day": "2026-11-16",
        "last_endpoint": {"entity_id": "hotel-1", "entrance_id": "gate-a",
                          "datetime": "2026-11-15T22:00:00+08:00"},
        "first_endpoint": {"entity_id": "hotel-1", "entrance_id": "gate-a",
                           "datetime": "2026-11-16T08:00:00+08:00"},
        "lodging_entrance_id": "gate-a",
        "lodging_requirement": requirement, "lodging_claim": claim,
    }
    return boundary


def endpoint_verifier(_kind, _fact):
    return True


def lodging_verifier(requirement, claim):
    return requirement["entity_id"] == claim["entity_id"]


class StrictOvernightContinuityTests(unittest.TestCase):
    def test_duplicate_boundary_cannot_count_as_two_checked_nights(self):
        item = fixture()
        result = check_overnight_continuity([item, copy.deepcopy(item)],
            fact_verifier=endpoint_verifier, lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['reason'], 'overnight_boundary_duplicate')

    def test_callback_mutating_original_boundary_does_not_preserve_pass(self):
        boundaries = [fixture()]
        def mutate(_kind, _fact):
            boundaries[0]['first_endpoint']['entity_id'] = 'other'
            return True
        out = check_overnight_continuity(boundaries, fact_verifier=mutate,
                                        lodging_claim_verifier=lodging_verifier)
        self.assertEqual(out['state'], 'unknown')
        self.assertEqual(out['reason'], 'overnight_original_inputs_mutated')
        self.assertFalse(out['boundaries'])

    def test_scoped_endpoints_and_stay_pass(self):
        result = check_overnight_continuity(
            [fixture()], fact_verifier=endpoint_verifier,
            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["boundaries"][0]["lodging"]["total_cny"], 600)
        self.assertFalse(result["complete_itinerary_certified"])
        self.assertEqual(result['coverage_scope'], 'provided_boundaries_only')
        self.assertFalse(result['itinerary_horizon_known'])
        self.assertFalse(result["truth_certified"])

    def test_missing_fact_or_lodging_verifier_is_unknown(self):
        missing_facts = check_overnight_continuity(
            [fixture()], lodging_claim_verifier=lodging_verifier)
        self.assertEqual(missing_facts["state"], "unknown")
        missing_lodging = check_overnight_continuity(
            [fixture()], fact_verifier=endpoint_verifier)
        self.assertEqual(missing_lodging["state"], "unknown")

    def test_scope_mismatch_and_bad_dates_stay_unknown(self):
        boundary = fixture()
        boundary["lodging_entrance_id"] = "gate-b"
        mismatch = check_overnight_continuity(
            [boundary], fact_verifier=endpoint_verifier,
            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(mismatch["state"], "unknown")
        self.assertEqual(mismatch["boundaries"][0]["reason"],
                         "transfer_between_endpoint_and_lodging_unverified")

        boundary = fixture()
        boundary["lodging_requirement"]["check_out"] = "2026-11-15"
        bad_stay = check_overnight_continuity(
            [boundary], fact_verifier=endpoint_verifier,
            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(bad_stay["state"], "unknown")

    def test_verifier_mutation_or_claimed_status_does_not_pass(self):
        def mutate(_kind, fact):
            fact["entity_id"] = "hotel-forged"
            return True

        mutated = check_overnight_continuity(
            [fixture()], fact_verifier=mutate,
            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(mutated["state"], "unknown")

        boundary = fixture()
        boundary["verified"] = True
        boundary["lodging_requirement"]["verified"] = True
        claimed = check_overnight_continuity([boundary])
        self.assertEqual(claimed["state"], "unknown")

    def test_lodging_scope_or_claim_conflict_is_unknown(self):
        boundary = fixture()
        boundary["lodging_claim"]["check_out"] = "2026-11-16"
        result = check_overnight_continuity(
            [boundary], fact_verifier=endpoint_verifier,
            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result["state"], "unknown")

    def test_invalid_boundary_shape_is_unknown(self):
        result = check_overnight_continuity([{"previous_day": "2026-11-15"}],
                                            fact_verifier=endpoint_verifier)
        self.assertEqual(result["state"], "unknown")

    def test_dates_in_different_offsets_cannot_reverse_absolute_time(self):
        boundary = fixture()
        boundary['last_endpoint']['datetime'] = '2026-11-15T23:00:00-12:00'
        boundary['first_endpoint']['datetime'] = '2026-11-16T00:00:00+14:00'
        result = check_overnight_continuity([boundary], fact_verifier=endpoint_verifier,
                                            lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['boundaries'][0]['reason'], 'endpoint_time_order_invalid')

    def test_unknown_identity_sentinels_cannot_pass_with_approving_callbacks(self):
        boundary = fixture()
        boundary['last_endpoint']['entity_id'] = 'unknown'
        boundary['first_endpoint']['entity_id'] = 'unknown'
        boundary['lodging_requirement']['entity_id'] = 'unknown'
        boundary['lodging_claim']['entity_id'] = 'unknown'
        boundary['last_endpoint']['entrance_id'] = 'unknown'
        boundary['first_endpoint']['entrance_id'] = 'unknown'
        boundary['lodging_entrance_id'] = 'unknown'
        result = check_overnight_continuity([boundary],
            fact_verifier=endpoint_verifier, lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['boundaries'][0]['reason'],
                         'endpoint_scope_missing_or_invalid')

        boundary = fixture()
        boundary['lodging_requirement']['entity_id'] = 'unknown'
        boundary['lodging_claim']['entity_id'] = 'unknown'
        result = check_overnight_continuity([boundary],
            fact_verifier=endpoint_verifier, lodging_claim_verifier=lodging_verifier)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['boundaries'][0]['reason'],
                         'lodging_stay_scope_missing_or_invalid')


if __name__ == "__main__":
    unittest.main()
