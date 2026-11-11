import unittest
from shorttrip.strict_itinerary_checks import check_itinerary_chronology_and_continuity


def verified(*args):
    return True


def travel(start, end, origin, origin_entry, destination, destination_entry):
    return {'type': 'travel', 'start': start, 'end': end,
            'origin_id': origin, 'origin_entrance_id': origin_entry,
            'destination_id': destination,
            'destination_entrance_id': destination_entry,
            'minutes': 30, 'status': 'estimate'}


def visit(start, end, entity, entrance):
    return {'type': 'visit', 'start': start, 'end': end,
            'entity_id': entity, 'entrance_id': entrance,
            'entity': 'display name only', 'opening_status': 'known'}


class StrictItineraryCheckTests(unittest.TestCase):
    def test_noncanonical_date_does_not_pass_chronology(self):
        days = [{'date': '20261102', 'timeline': [
            travel('09:00', '09:30', 'hotel', 'lobby', 'poi', 'gate'),
            visit('09:30', '10:30', 'poi', 'gate')]}]
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertNotEqual(result['chronology']['state'], 'pass')

    def test_overnight_boundary_is_unknown_not_direct_endpoint_failure(self):
        days = [
            {'date': '2026-11-02', 'timeline': [
                travel('20:00', '20:30', 'poi', 'gate', 'hotel', 'lobby')]},
            {'date': '2026-11-03', 'timeline': [
                visit('09:00', '10:00', 'museum', 'gate')]},
        ]
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertEqual(result['continuity']['state'], 'unknown')

    def test_verifier_mutation_is_unverified_and_does_not_modify_input(self):
        days = [{'date': '2026-11-02', 'timeline': [
            travel('09:00', '09:30', 'hotel', 'lobby', 'poi', 'gate'),
            visit('09:30', '10:30', 'poi', 'gate')]}]
        def mutate(kind, fact):
            fact['injected'] = True
            return True
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=mutate)
        self.assertEqual(result['chronology']['state'], 'unknown')
        self.assertEqual(result['continuity']['state'], 'unknown')
        self.assertNotIn('injected', days[0]['timeline'][0])

    def test_verifier_closure_cannot_mutate_later_timeline_facts(self):
        days = [{'date': '2026-11-02', 'timeline': [
            travel('09:00', '09:30', 'hotel', 'lobby', 'poi-1', 'gate'),
            visit('09:30', '10:30', 'poi-2', 'gate'),
        ]}]
        def mutate_via_closure(kind, _fact):
            if kind == 'endpoint':
                days[0]['timeline'][1]['entity_id'] = 'poi-1'
            return True

        result = check_itinerary_chronology_and_continuity(days,
            fact_verifier=mutate_via_closure)
        self.assertNotEqual(result['continuity']['state'], 'pass')
        self.assertIn('verifier_mutated_original_itinerary', result['unresolved'])

    def test_mixed_timezone_interval_does_not_raise(self):
        days=[{'date':'2026-11-02','timeline':[{'type':'visit','start':'10:00+08:00','end':'11:00'}]}]
        out=check_itinerary_chronology_and_continuity(days, fact_verifier=lambda *_:True)
        self.assertTrue(out['chronology']['structural_errors'])
    def test_verified_ordered_segments_and_exact_endpoints_pass(self):
        days = [{'date': '2026-11-02', 'timeline': [
            travel('09:00', '09:30', 'hotel-1', 'lobby', 'poi-1', 'east-gate'),
            visit('09:30', '11:00', 'poi-1', 'east-gate'),
            travel('11:00', '11:30', 'poi-1', 'east-gate', 'poi-2', 'main-gate'),
            visit('11:30', '12:30', 'poi-2', 'main-gate'),
        ]}]
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertEqual(result['chronology']['state'], 'pass')
        self.assertEqual(result['continuity']['state'], 'pass')
        self.assertFalse(result['truth_certified'])
        self.assertFalse(result['execution_confirmed'])

    def test_overlaps_and_out_of_order_require_verified_times(self):
        days = [{'date': '2026-11-02', 'timeline': [
            visit('09:00', '10:00', 'poi-1', 'gate'),
            visit('09:50', '11:00', 'poi-2', 'gate'),
        ]}]
        unverified = check_itinerary_chronology_and_continuity(days)
        self.assertEqual(unverified['chronology']['state'], 'unknown')
        verified_result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertEqual(verified_result['chronology']['state'], 'fail')
        self.assertEqual(verified_result['chronology']['reason'], 'verified_order_or_overlap_conflict')

    def test_endpoint_identity_and_entrance_mismatches_fail_only_when_verified(self):
        days = [{'date': '2026-11-02', 'timeline': [
            travel('09:00', '09:30', 'hotel-1', 'lobby', 'poi-1', 'east-gate'),
            visit('09:30', '10:00', 'poi-1', 'west-gate'),
        ]}]
        self.assertEqual(check_itinerary_chronology_and_continuity(days)['continuity']['state'], 'unknown')
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertEqual(result['continuity']['state'], 'fail')
        self.assertEqual(result['continuity']['reason'], 'verified_endpoint_identity_or_entrance_mismatch')

    def test_unknown_endpoint_sentinels_cannot_pass_with_approving_callbacks(self):
        for sentinel in ('unknown', 'unresolved', 'ＭＩＳＳＩＮＧ'):
            days = [{'date': '2026-11-02', 'timeline': [
                travel('09:00', '09:30', 'hotel-1', 'lobby', sentinel, sentinel),
                visit('09:30', '10:30', sentinel, sentinel),
            ]}]
            with self.subTest(sentinel=sentinel):
                result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
                self.assertNotEqual(result['continuity']['state'], 'pass')

    def test_p31_names_and_time_estimates_stay_unknown_without_verifier(self):
        days = [{'date': '2026-11-02', 'timeline': [
            {'type': 'travel', 'start': '09:00', 'end': '09:30', 'from': 'Hotel', 'to': 'POI'},
            {'type': 'visit', 'start': '09:30', 'end': '10:30', 'entity': 'POI',
             'minutes': 60, 'opening_status': 'known'},
        ]}]
        result = check_itinerary_chronology_and_continuity(days)
        self.assertEqual(result['chronology']['state'], 'unknown')
        self.assertEqual(result['continuity']['state'], 'unknown')
        self.assertTrue(any('context_missing' in item for item in result['unresolved']))

    def test_invalid_interval_and_missing_day_context_are_not_passes(self):
        invalid = check_itinerary_chronology_and_continuity([{'date': '2026-11-02', 'timeline': [
            visit('10:00', '09:00', 'poi-1', 'gate')]}], fact_verifier=verified)
        self.assertEqual(invalid['chronology']['state'], 'fail')
        missing = check_itinerary_chronology_and_continuity([{'date': '2026-11-02'}],
                                                            fact_verifier=verified)
        self.assertEqual(missing['chronology']['state'], 'unknown')
        self.assertEqual(missing['continuity']['state'], 'unknown')

    def test_unhashable_timeline_type_fails_closed_without_crashing(self):
        days = [{'date': '2026-11-02', 'timeline': [
            {'type': ['visit'], 'start': '09:00', 'end': '10:00',
             'entity_id': 'poi-1', 'entrance_id': 'gate'}]}]
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertNotEqual(result['chronology']['state'], 'pass')

    def test_chronology_can_pass_while_missing_movement_keeps_continuity_unknown(self):
        days = [{'date': '2026-11-02', 'timeline': [
            visit('09:00', '10:00', 'poi-1', 'gate'),
            visit('10:00', '11:00', 'poi-2', 'gate'),
        ]}]
        result = check_itinerary_chronology_and_continuity(days, fact_verifier=verified)
        self.assertEqual(result['chronology']['state'], 'pass')
        self.assertEqual(result['continuity']['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
