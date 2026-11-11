import copy
import unittest
from shorttrip.strict_business_chain import check_business_chain
from shorttrip.strict_development_orchestrator import _bound_chain_events

CHAIN=[{'kind':'attraction','entity_id':'a'}, {'kind':'restaurant','entity_id':'r'},
       {'kind':'accommodation','entity_id':'h'}]


class BusinessChainTests(unittest.TestCase):
    def test_callbacks_cannot_change_original_chain_or_events(self):
        for callback_kind in ('inventory', 'event'):
            chain, events = copy.deepcopy(CHAIN), copy.deepcopy(CHAIN)
            def mutate(*_args):
                events[0]['entity_id'] = 'other'
                return True
            callbacks = {'inventory_verifier': lambda *_: True, 'event_verifier': lambda *_: True}
            callbacks[callback_kind + '_verifier'] = mutate
            with self.subTest(callback=callback_kind):
                self.assertEqual(check_business_chain(chain, events, **callbacks)['state'], 'unknown')

    def test_unknown_sentinel_identity_is_not_pass_even_with_true_verifiers(self):
        for entity_id in ("unknown", "unresolved", "missing", "none", "null"):
            chain = [{"kind": "attraction", "entity_id": entity_id}]
            events = [{"kind": "attraction", "entity_id": entity_id}]
            with self.subTest(entity_id=entity_id):
                out = check_business_chain(
                    chain, events, inventory_verifier=lambda *_: True,
                    event_verifier=lambda _: True)
                self.assertEqual(out["state"], "unknown")

        for kind in ("unknown", "unresolved", "missing", "none", "null"):
            chain = [{"kind": kind, "entity_id": "entity-1"}]
            events = [{"kind": kind, "entity_id": "entity-1"}]
            with self.subTest(kind=kind):
                out = check_business_chain(
                    chain, events, inventory_verifier=lambda *_: True,
                    event_verifier=lambda _: True)
                self.assertEqual(out["state"], "unknown")

    def test_bound_plan_events_reject_unknown_identity_sentinels(self):
        for entity_id, kind in (("unknown", "attraction"),
                                ("entity-1", "unknown"),
                                ("unresolved", "restaurant"),
                                ("entity-2", "unresolved")):
            event = {"day_index": 0, "item_index": 1, "role": "activity",
                     "date": "2026-11-15", "entity_id": entity_id, "kind": kind}
            references = {(0, 1, "activity"): {
                "entity_id": entity_id, "travel_date": "2026-11-15", "label": None}}
            kinds = {entity_id: kind}
            with self.subTest(entity_id=entity_id, kind=kind):
                self.assertIsNone(_bound_chain_events([event], references, kinds))

    def test_verifier_cannot_mutate_plan_to_fake_order(self):
        events=list(reversed(CHAIN))
        def mutate(_chain, items):
            items.reverse()
            return True
        out=check_business_chain(CHAIN,events,inventory_verifier=mutate,event_verifier=lambda _:True)
        self.assertEqual(out['state'],'unknown')
        self.assertEqual(events,list(reversed(CHAIN)))
    def test_order_is_checked_only_under_complete_verified_inventory(self):
        out=check_business_chain(CHAIN,CHAIN,inventory_verifier=lambda *_:True,event_verifier=lambda _:True)
        self.assertEqual(out['state'],'pass')
        self.assertFalse(out['execution_confirmed'])
        self.assertEqual(check_business_chain(CHAIN,CHAIN)['state'],'unknown')

    def test_missing_or_reordered_required_items_are_verified_candidate_failures(self):
        for events in (CHAIN[:2],[CHAIN[1],CHAIN[0],CHAIN[2]]):
            out=check_business_chain(CHAIN,events,inventory_verifier=lambda *_:True,event_verifier=lambda _:True)
            self.assertEqual(out['state'],'fail')

    def test_wrong_kind_or_unverified_event_is_not_accepted(self):
        events=[dict(x) for x in CHAIN];events[1]['kind']='attraction'
        self.assertEqual(check_business_chain(CHAIN,events,inventory_verifier=lambda *_:True,
                                               event_verifier=lambda _:True)['state'],'fail')
        self.assertEqual(check_business_chain(CHAIN,events,inventory_verifier=lambda *_:True,
                                               event_verifier=lambda _:False)['state'],'unknown')

    def test_verifier_bool_to_int_mutations_are_detected_without_input_changes(self):
        chain = [dict(CHAIN[0])]
        events = [dict(CHAIN[0], sequence=True)]
        original_chain, original_events = copy.deepcopy(chain), copy.deepcopy(events)

        def mutate_inventory(items_chain, items_events):
            items_events[0]["sequence"] = 1
            return True

        out = check_business_chain(chain, events, inventory_verifier=mutate_inventory,
                                   event_verifier=lambda _: True)
        self.assertEqual(out["state"], "unknown")
        self.assertEqual(chain, original_chain)
        self.assertEqual(events, original_events)

        def mutate_event(event):
            event["sequence"] = 1
            return True

        out = check_business_chain(chain, events, inventory_verifier=lambda *_: True,
                                   event_verifier=mutate_event)
        self.assertEqual(out["state"], "unknown")
        self.assertEqual(chain, original_chain)
        self.assertEqual(events, original_events)

    def test_whitespace_kind_and_entity_id_are_rejected(self):
        for field in ("kind", "entity_id"):
            with self.subTest(field=field):
                blank = [{"kind": "attraction", "entity_id": "a"}]
                blank[0][field] = "   "
                out = check_business_chain(blank, blank,
                    inventory_verifier=lambda *_: True, event_verifier=lambda _: True)
                self.assertEqual(out["state"], "unknown")
                self.assertIn("chain_identity_invalid", out["reason"])

    def test_snapshot_copy_failures_return_unknown_without_changing_inputs(self):
        nested = []
        cursor = nested
        for _ in range(1500):
            child = []
            cursor.append(child)
            cursor = child
        chain = [dict(CHAIN[0])]
        events = [dict(CHAIN[0], metadata=nested)]
        out = check_business_chain(chain, events, inventory_verifier=lambda *_: True,
                                   event_verifier=lambda _: True)
        self.assertEqual(out["state"], "unknown")
        self.assertIs(events[0]["metadata"], nested)

        class Uncopyable:
            def __deepcopy__(self, memo):
                raise RuntimeError("cannot copy")

        marker = Uncopyable()
        events = [dict(CHAIN[0], metadata=marker)]
        out = check_business_chain(chain, events, inventory_verifier=lambda *_: True,
                                   event_verifier=lambda _: True)
        self.assertEqual(out["state"], "unknown")
        self.assertIs(events[0]["metadata"], marker)


if __name__ == '__main__':
    unittest.main()
