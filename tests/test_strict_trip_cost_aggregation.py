import copy
import json
import unittest
from decimal import Decimal

from src.shorttrip.strict_trip_cost_aggregation import aggregate_trip_costs
from tests.test_strict_lodging_cost_manifest import fixture as lodging_fixture


class StrictTripCostAggregationTests(unittest.TestCase):
    def test_inventory_verifier_receives_full_plan_and_can_reject_omission(self):
        plan = copy.deepcopy(self.plan)
        plan['days'][0]['timeline'].append({'type':'visit', 'entity_id':'unaccounted-event'})
        def verify_inventory(_policy, components, _scope, _task, plan_snapshot):
            declared = {(binding['day_index'], binding['item_index'])
                        for component in components for binding in component['occurrence_bindings']}
            represented = {(day_index, item_index)
                           for day_index, day in enumerate(plan_snapshot['days'])
                           for item_index, _ in enumerate(day['timeline'])}
            return declared == represented
        result = self.aggregate(plan=plan, inventory_verifier=verify_inventory)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('cost_inventory_unverified', result['reasons'])

    def test_old_three_argument_inventory_verifier_fails_closed(self):
        result = self.aggregate(inventory_verifier=lambda _policy, _components, _scope: True)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('inventory_verifier_failed', result['reasons'])

    def test_json_float_with_lost_money_lexeme_is_unknown(self):
        self.setUp()
        components = copy.deepcopy(self.components)
        source_token = "1.0000000000000001"
        components[0]["amount"] = json.loads(source_token)
        components[1]["amount"] = 0
        components[2]["amount"] = 0
        self.assertEqual(components[0]["amount"], 1.0)
        self.assertGreater(Decimal(source_token), Decimal("1"))

        result = self.aggregate(components)

        self.assertEqual(result["status"], "unknown")
        self.assertIn("component_amount_invalid", result["reasons"])

    def test_raw_decimal_text_compares_exactly_over_decimal_limit(self):
        self.setUp()
        components = copy.deepcopy(self.components)
        components[0]["amount"] = "0.100000000000000005"
        components[1]["amount"] = 0
        components[2]["amount"] = 0
        policy = {**self.policy, "total_limit": "0.1"}

        result = self.aggregate(components, policy=policy)

        self.assertEqual(result["status"], "arithmetic_evaluated")
        self.assertEqual(result["total_decimal"], "0.100000000000000005")
        self.assertEqual(result["comparison"], "over_limit")

    def test_float_budget_limit_is_unknown(self):
        self.setUp()
        result = self.aggregate(policy={**self.policy, "total_limit": 0.1})

        self.assertEqual(result["status"], "unknown")
        self.assertIn("policy_scope_incomplete", result["reasons"])

    def test_verifiers_cannot_change_original_inputs_through_closure(self):
        for verifier_type in ('evidence', 'inventory'):
            with self.subTest(verifier_type=verifier_type):
                self.setUp()
                def mutate(*_args):
                    self.components[0]['amount'] = 0
                    return True
                result = self.aggregate(**{verifier_type + '_verifier': mutate})
                self.assertEqual(result['status'], 'unknown')
                self.assertIn('cost_original_inputs_mutated', result['reasons'])

    def test_fractional_lodging_uses_decimal_manifest_total_for_budget_comparison(self):
        task, plan, requirement, nights, component = lodging_fixture()
        for night in nights:
            night["claim"]["rate"] = "0.1"
        component["amount"] = "0.2"
        scope = copy.deepcopy(component["scope"])
        policy = {"required_categories": ["accommodation"], "currency": "CNY",
            "party_size": task["people_number"], "trip_scope": scope,
            "total_limit": "0.19"}
        result = aggregate_trip_costs(policy, [component], scope=scope,
            task=task, plan=plan,
            lodging_manifest={"requirement": requirement, "nights": nights},
            evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True,
            lodging_claim_verifier=lambda *_: True,
            lodging_inventory_verifier=lambda *_: True)
        self.assertEqual(result["status"], "arithmetic_evaluated")
        self.assertEqual(result["total_decimal"], "0.2")
        self.assertEqual(result["comparison"], "over_limit")
        self.assertIsNone(result["lodging_manifest_check"]["total_cny"])

    def test_decimal_boundary_does_not_create_float_rounding_failure(self):
        scope = {'trip_id': 't'}
        policy = {'required_categories': ['tickets', 'meals'], 'currency': 'CNY',
                  'party_size': 1, 'trip_scope': scope, 'total_limit': '0.3'}
        plan = {'uid': 't', 'days': []}
        items = []
        for index, (key, value) in enumerate([('tickets', '0.1'), ('meals', '0.2')]):
            day = {'date': f'2026-11-0{index + 1}', 'city': 'X',
                   'timeline': [{'type': 'visit', 'entity_id': 'e-' + key}]}
            plan['days'].append(day)
            items.append({'category': key, 'amount': value, 'currency': 'CNY',
                          'party_size': 1, 'scope': scope, 'evidence': {'id': key},
                          'expense_ids': ['expense-' + key],
                          'occurrence_bindings': [{'expense_id': 'expense-' + key,
                              'day_index': index, 'item_index': 0, 'date': day['date'],
                              'type': 'visit', 'entity_id': 'e-' + key}]})
        out = aggregate_trip_costs(policy, items, scope=scope,
                                   evidence_verifier=lambda *_: True,
                                   inventory_verifier=lambda *_: True, plan=plan)
        self.assertEqual(out['comparison'], 'within_limit')
        self.assertEqual(out['total_decimal'], '0.3')
        self.assertTrue(out['total_is_approximate'])

    def test_large_integral_total_is_not_rounded_in_numeric_field(self):
        components = copy.deepcopy(self.components)
        components[0]['amount'] = 9007199254740993
        result = self.aggregate(components)
        self.assertEqual(result['total'], 9007199254741443)
        self.assertEqual(result['total_decimal'], '9007199254741443')
        self.assertFalse(result['total_is_approximate'])

    def setUp(self):
        self.scope = {"trip_id": "T1", "travel_dates": ["2026-11-01", "2026-11-02", "2026-11-03"]}
        self.policy = {
            "required_categories": ["tickets", "transport", "meals"],
            "currency": "CNY", "party_size": 2, "trip_scope": self.scope,
            "total_limit": 1000,
        }
        self.components = [
            self.item("tickets", 500),
            self.item("transport", 200),
            self.item("meals", 250),
        ]
        self.plan = {'uid': 'T1', 'days': [
            {'date': day, 'city': 'X', 'timeline': [
                {'type': 'visit', 'entity_id': 'entity-' + str(index)}]}
            for index, day in enumerate(self.scope['travel_dates'])]}
        for index, component in enumerate(self.components):
            day = self.plan['days'][index]
            component['occurrence_bindings'] = [{
                'expense_id': component['expense_ids'][0], 'day_index': index,
                'item_index': 0, 'date': day['date'], 'type': 'visit',
                'entity_id': day['timeline'][0]['entity_id']}]

    def item(self, category, amount):
        return {"category": category, "amount": amount, "currency": "CNY",
                "party_size": 2, "scope": copy.deepcopy(self.scope),
                "evidence": {"evidence_id": "E-" + category,
                             "expense_ids": ["X-" + category]},
                "expense_ids": ["X-" + category]}

    @staticmethod
    def verified(*_):
        return True

    @staticmethod
    def inventory_verified(*_):
        return True

    def aggregate(self, components=None, *, evidence_verifier=None,
                  inventory_verifier=None, policy=None, scope=None, plan=None):
        return aggregate_trip_costs(
            self.policy if policy is None else policy,
            self.components if components is None else components,
            scope=self.scope if scope is None else scope,
            evidence_verifier=self.verified if evidence_verifier is None else evidence_verifier,
            inventory_verifier=self.inventory_verified if inventory_verifier is None else inventory_verifier,
            plan=self.plan if plan is None else plan)

    def test_complete_policy_and_both_verification_layers_yield_arithmetic_only(self):
        calls = {"items": 0, "inventory": 0}
        def item_verifier(*_):
            calls["items"] += 1
            return True
        def inventory_verifier(policy, components, scope, task, plan):
            calls["inventory"] += 1
            self.assertIsNone(task)
            self.assertEqual(plan, self.plan)
            self.assertEqual(set(c["category"] for c in components),
                             set(policy["required_categories"]))
            return True
        result = self.aggregate(evidence_verifier=item_verifier,
                                inventory_verifier=inventory_verifier)
        self.assertEqual(result["status"], "arithmetic_evaluated")
        self.assertEqual(result["total"], 950)
        self.assertEqual(result["comparison"], "within_limit")
        self.assertEqual(calls, {"items": 3, "inventory": 1})
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["real_trip_conclusion"])

    def test_explicit_over_limit_is_arithmetic_only(self):
        policy = {**self.policy, "total_limit": 900}
        result = self.aggregate(policy=policy)
        self.assertEqual(result["comparison"], "over_limit")
        self.assertFalse(result["real_trip_conclusion"])

    def test_policy_must_declare_every_category_and_no_duplicates(self):
        for categories, expected in ((["tickets", "meals"], "undeclared_category_present"),
                                     (["tickets", "tickets"], "policy_categories_invalid")):
            with self.subTest(categories=categories):
                policy = {**self.policy, "required_categories": categories}
                result = self.aggregate(policy=policy)
                self.assertEqual(result["status"], "unknown")
                self.assertIn(expected, result["reasons"])

    def test_missing_duplicate_and_conflicting_category_are_unknown(self):
        cases = [
            (self.components[:-1], "required_category_missing"),
            (self.components + [self.item("meals", 1)], "duplicate_category"),
        ]
        conflict = copy.deepcopy(self.components)
        conflict[0]["conflict"] = True
        cases.append((conflict, "component_evidence_conflict"))
        for components, expected in cases:
            with self.subTest(expected=expected):
                result = self.aggregate(components)
                self.assertEqual(result["status"], "unknown")
                self.assertIn(expected, result["reasons"])
                self.assertIsNone(result["total"])

    def test_same_expense_across_categories_requires_inventory_rejection(self):
        components = copy.deepcopy(self.components)
        components[1]["expense_ids"] = ["X-tickets"]
        def inventory(policy, items, scope, task, plan):
            ids = [expense for item in items for expense in item["evidence"]["expense_ids"]]
            return len(ids) == len(set(ids))
        result = self.aggregate(components, inventory_verifier=inventory)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("expense_id_duplicate_across_categories", result["reasons"])
        self.assertIsNone(result["total"])

    def test_expense_ids_are_required_normalized_and_unique(self):
        components = copy.deepcopy(self.components)
        components[0].pop('expense_ids')
        result = self.aggregate(components)
        self.assertIn('expense_inventory_missing_or_incomplete', result['reasons'])

        components = copy.deepcopy(self.components)
        components[0]['expense_ids'] = ['  DUP ']
        components[1]['expense_ids'] = ['dup']
        result = self.aggregate(components)
        self.assertIn('expense_id_duplicate_across_categories', result['reasons'])

        components = copy.deepcopy(self.components)
        components[0]['expense_ids'] = ['X', ' x ']
        result = self.aggregate(components)
        self.assertIn('expense_id_duplicate_within_category', result['reasons'])

    def test_missing_inventory_verifier_is_unknown(self):
        result = aggregate_trip_costs(self.policy, self.components, scope=self.scope,
                                      evidence_verifier=self.verified, inventory_verifier=None,
                                      plan=self.plan)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("independent_inventory_verifier_required", result["reasons"])

    def test_inventory_rejection_and_exception_are_unknown(self):
        def explode(*_):
            raise RuntimeError("failed")
        for verifier, reason in ((lambda *_: False, "cost_inventory_unverified"),
                                 (explode, "inventory_verifier_failed")):
            result = self.aggregate(inventory_verifier=verifier)
            self.assertEqual(result["status"], "unknown")
            self.assertIn(reason, result["reasons"])

    def test_inventory_verifier_mutation_fails_closed_and_is_isolated(self):
        components = copy.deepcopy(self.components)
        policy = copy.deepcopy(self.policy)
        before = (copy.deepcopy(policy), copy.deepcopy(components))
        def mutate(_policy, items, _scope, _task, _plan):
            items.pop()
            return True
        result = self.aggregate(components, policy=policy, inventory_verifier=mutate)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("inventory_verifier_mutated_input", result["reasons"])
        self.assertEqual((policy, components), before)

    def test_currency_party_and_trip_scope_must_match_exactly(self):
        mutations = [
            ("currency", lambda item: item.update(currency="USD"), "currency_mismatch"),
            ("party", lambda item: item.update(party_size=1), "party_size_mismatch"),
            ("scope", lambda item: item["scope"].update(trip_id="T2"), "component_trip_scope_mismatch"),
        ]
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                components = copy.deepcopy(self.components)
                mutate(components[0])
                result = self.aggregate(components)
                self.assertEqual(result["status"], "unknown")
                self.assertIn(expected, result["reasons"])

    def test_scope_must_match_policy(self):
        result = self.aggregate(scope={"trip_id": "T2"})
        self.assertEqual(result["status"], "unknown")
        self.assertIn("requested_trip_scope_mismatch", result["reasons"])

    def test_lodging_requires_manifest_and_intercity_requires_raw_manifest(self):
        for category in ('rooms', 'accommodation'):
            components = copy.deepcopy(self.components)
            components[0]['category'] = category
            policy = {**self.policy, 'required_categories': [category, 'transport', 'meals']}
            result = self.aggregate(components, policy=policy)
            self.assertEqual(result['status'], 'unknown', category)
            self.assertIn('lodging_manifest_missing_or_malformed', result['reasons'])
        for category in ('intercity', 'hotel', '住宿'):
            components = copy.deepcopy(self.components)
            components[0]['category'] = category
            policy = {**self.policy, 'required_categories': [category, 'transport', 'meals']}
            result = self.aggregate(components, policy=policy)
            self.assertEqual(result['status'], 'unknown', category)
            self.assertIn('intercity_manifest_missing_or_malformed' if category == 'intercity'
                          else 'cost_category_requires_unsupported_scope_manifest', result['reasons'])

    def test_rooms_and_accommodation_aliases_cannot_be_mixed(self):
        components = copy.deepcopy(self.components)
        components[0]['category'] = 'rooms'
        components.append({**copy.deepcopy(components[0]), 'category': 'accommodation'})
        policy = {**self.policy,
                  'required_categories': ['rooms', 'accommodation', 'transport', 'meals']}
        result = self.aggregate(components, policy=policy)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('duplicate_category', result['reasons'])

    def test_occurrence_manifest_must_bind_each_expense_once_to_actual_plan(self):
        result = self.aggregate(plan={'uid': 'T1', 'days': [
            {'date': day, 'city': 'X', 'timeline': []}
            for day in self.scope['travel_dates']]})
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('cost_plan_timeline_empty_or_missing', result['reasons'])

        components = copy.deepcopy(self.components)
        components[1]['occurrence_bindings'][0] = copy.deepcopy(
            components[0]['occurrence_bindings'][0])
        components[1]['occurrence_bindings'][0]['expense_id'] = components[1]['expense_ids'][0]
        result = self.aggregate(components)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('expense_occurrence_missing_or_duplicate', result['reasons'])

        components = copy.deepcopy(self.components)
        components[0]['occurrence_bindings'][0]['entity_id'] = 'forged-entity'
        result = self.aggregate(components)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('expense_occurrence_not_bound_to_plan', result['reasons'])

    def test_missing_or_unverified_component_evidence_is_unknown(self):
        components = copy.deepcopy(self.components)
        components[0]["evidence"] = None
        result = self.aggregate(components)
        self.assertIn("component_evidence_missing", result["reasons"])
        result = self.aggregate(evidence_verifier=lambda *_: 1)
        self.assertIn("component_evidence_unverified", result["reasons"])

    def test_component_verifier_mutation_is_unknown_and_isolated(self):
        components = copy.deepcopy(self.components)
        before = copy.deepcopy(components)
        def mutate(component, _policy, _scope):
            component["amount"] = 0
            return True
        result = self.aggregate(components, evidence_verifier=mutate)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("evidence_verifier_mutated_input", result["reasons"])
        self.assertEqual(components, before)

    def test_invalid_amount_or_nonfinite_sum_is_unknown(self):
        for value in (True, -1, float("nan"), float("inf")):
            components = copy.deepcopy(self.components)
            components[0]["amount"] = value
            result = self.aggregate(components)
            self.assertIn("component_amount_invalid", result["reasons"])
        components = [self.item("tickets", '1' + '0' * 308),
                      self.item("transport", '1' + '0' * 308), self.item("meals", 1)]
        for index, component in enumerate(components):
            day = self.plan['days'][index]
            component['occurrence_bindings'] = [{
                'expense_id': component['expense_ids'][0], 'day_index': index,
                'item_index': 0, 'date': day['date'], 'type': 'visit',
                'entity_id': day['timeline'][0]['entity_id']}]
        result = self.aggregate(components)
        self.assertIn("aggregate_total_invalid", result["reasons"])

    def test_unknown_scope_entity_and_expense_sentinels_cannot_produce_total(self):
        components = copy.deepcopy(self.components)
        plan = copy.deepcopy(self.plan)
        plan['days'][0]['timeline'][0]['entity_id'] = 'unknown'
        components[0]['occurrence_bindings'][0]['entity_id'] = 'unknown'
        result = self.aggregate(components, plan=plan)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('cost_plan_occurrence_identity_missing', result['reasons'])

        plan = copy.deepcopy(self.plan)
        plan['days'][0]['city'] = 'unknown'
        result = self.aggregate(plan=plan)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('cost_plan_city_missing_or_unknown', result['reasons'])

        components = copy.deepcopy(self.components)
        components[0]['expense_ids'] = ['unknown']
        components[0]['occurrence_bindings'][0]['expense_id'] = 'unknown'
        result = self.aggregate(components)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('expense_id_invalid', result['reasons'])

        policy = copy.deepcopy(self.policy)
        scope = copy.deepcopy(self.scope)
        scope['trip_id'] = 'missing'
        policy['trip_scope'] = copy.deepcopy(scope)
        components = copy.deepcopy(self.components)
        for component in components:
            component['scope'] = copy.deepcopy(scope)
        result = self.aggregate(components, policy=policy, scope=scope)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('policy_scope_incomplete', result['reasons'])


if __name__ == "__main__":
    unittest.main()



