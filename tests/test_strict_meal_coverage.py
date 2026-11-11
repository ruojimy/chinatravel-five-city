import copy
import unittest

from shorttrip.strict_meal_coverage import check_meal_coverage


class MealCoverageTests(unittest.TestCase):
    def test_callback_mutating_original_event_does_not_preserve_pass(self):
        slots = [{'date':'2026-11-15','slot':'lunch'}]
        events = [{'date':'2026-11-15','slot':'lunch','entity_id':'r1','event_id':'e1'}]
        for name in ('inventory', 'event'):
            current = copy.deepcopy(events)
            def mutate(*_args):
                current[0]['entity_id'] = 'other'
                return True
            callbacks = {'inventory_verifier': lambda *_: True, 'event_verifier': lambda *_: True}
            callbacks[name + '_verifier'] = mutate
            with self.subTest(name=name):
                self.assertEqual(check_meal_coverage(slots, current, **callbacks)['state'], 'unknown')

    def setUp(self):
        self.slots = [{'date': '2026-11-15', 'slot': 'lunch'},
                      {'date': '2026-11-16', 'slot': 'dinner'}]
        self.events = [{'date': '2026-11-15', 'slot': 'lunch',
                        'entity_id': 'r1', 'event_id': 'e1'}]

    def test_missing_slot_is_failure_only_after_independent_complete_inventory(self):
        self.assertEqual(check_meal_coverage(self.slots, self.events)['state'], 'unknown')
        out = check_meal_coverage(self.slots, self.events,
                                  inventory_verifier=lambda *_: True,
                                  event_verifier=lambda *_: True)
        self.assertEqual(out['state'], 'fail')
        self.assertEqual(out['missing_slots'], [self.slots[1]])
        self.assertFalse(out['complete_itinerary_certified'])

    def test_complete_slots_pass_only_as_component(self):
        events = self.events + [{'date': '2026-11-16', 'slot': 'dinner',
                                 'entity_id': 'r2', 'event_id': 'e2'}]
        out = check_meal_coverage(self.slots, events, inventory_verifier=lambda *_: True,
                                  event_verifier=lambda *_: True)
        self.assertEqual(out['state'], 'pass')
        self.assertFalse(out['truth_certified'])

    def test_duplicate_missing_and_mutation_never_become_failure(self):
        before = copy.deepcopy(self.events)
        duplicate = check_meal_coverage(self.slots, self.events * 2,
                                        inventory_verifier=lambda *_: True,
                                        event_verifier=lambda *_: True)
        self.assertEqual(duplicate['state'], 'unknown')
        def mutate(policy, events):
            events.clear()
            return True
        out = check_meal_coverage(self.slots, self.events, inventory_verifier=mutate,
                                  event_verifier=lambda *_: True)
        self.assertEqual(out['state'], 'unknown')
        self.assertEqual(self.events, before)
        self.assertEqual(check_meal_coverage([], [], inventory_verifier=lambda *_: True,
                                             event_verifier=lambda *_: True)['state'], 'unknown')

    def test_unknown_slot_and_event_id_sentinels_cannot_pass(self):
        inventory = lambda *_: True
        verify = lambda *_: True
        cases = [
            ([{'date': '2026-11-15', 'slot': 'unknown'}],
             [{'date': '2026-11-15', 'slot': 'unknown',
               'entity_id': 'restaurant-1', 'event_id': 'event-1'}]),
            ([{'date': '2026-11-15', 'slot': 'lunch'}],
             [{'date': '2026-11-15', 'slot': 'lunch',
               'entity_id': 'unknown', 'event_id': 'event-1'}]),
            ([{'date': '2026-11-15', 'slot': 'lunch'}],
             [{'date': '2026-11-15', 'slot': 'lunch',
               'entity_id': 'restaurant-1', 'event_id': 'unknown'}]),
        ]
        for required, events in cases:
            with self.subTest(required=required, events=events):
                out = check_meal_coverage(required, events,
                    inventory_verifier=inventory, event_verifier=verify)
                self.assertEqual(out['state'], 'unknown')
