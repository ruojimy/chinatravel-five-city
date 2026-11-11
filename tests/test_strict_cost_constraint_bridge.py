import copy
import json
import unittest

from src.shorttrip.strict_constraint_compiler import compile_constraint
from src.shorttrip.strict_cost_constraint_bridge import evaluate_cost_constraint

_DEFAULT = object()


def contains_pass_state(value):
    if isinstance(value, dict):
        return (value.get("state") == "pass" or
                any(contains_pass_state(item) for item in value.values()))
    if isinstance(value, list):
        return any(contains_pass_state(item) for item in value)
    return False


class StrictCostConstraintBridgeTests(unittest.TestCase):
    def setUp(self):
        self.scope = {"task_uid": "T1", "plan_uid": "T1", "target_city": "X",
                      "itinerary_dates": ["2026-11-01", "2026-11-02", "2026-11-03"]}
        self.policy = {"required_categories": ["tickets", "transport", "meals"],
                       "currency": "CNY", "party_size": 2,
                       "total_limit": 1000, "trip_scope": self.scope}
        self.plan = {"uid": "T1", "days": [
            {"date": day, "city": "X", "timeline": [
                {"type": "visit", "entity_id": "entity-" + str(index)}]}
            for index, day in enumerate(self.scope["itinerary_dates"])]}
        self.components = [self.item("tickets", 500, 0),
                           self.item("transport", 200, 1), self.item("meals", 250, 2)]
        raw = {"id": "budget", "strength": "hard",
               "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
               "expression": {"op": "total_cost_at_most",
                              "args": {"CNY": 1000, "people": 2,
                                       "includes": list(self.policy["required_categories"])}}}
        self.constraint = compile_constraint(raw)["constraint"]

    def item(self, category, amount, day_index=None):
        if day_index is None:
            day_index = {"tickets": 0, "transport": 1, "meals": 2}[category]
        day = self.plan["days"][day_index]
        expense_id = "expense-" + category
        return {"category": category, "amount": amount, "currency": "CNY",
                "party_size": 2, "scope": copy.deepcopy(self.scope),
                "evidence": {"evidence_id": "E-" + category},
                "expense_ids": [expense_id],
                "occurrence_bindings": [{"expense_id": expense_id,
                    "day_index": day_index, "item_index": 0, "date": day["date"],
                    "type": "visit", "entity_id": day["timeline"][0]["entity_id"]}]}

    @staticmethod
    def item_verifier(*_):
        return True

    @staticmethod
    def inventory_verifier(*_):
        return True

    @staticmethod
    def fact_verifier(*_):
        return True

    @staticmethod
    def context_verifier(*_):
        return True

    def evaluate(self, *, evidence_verifier=_DEFAULT, inventory_verifier=_DEFAULT,
                 fact_verifier=_DEFAULT, context_verifier=_DEFAULT, **overrides):
        constraint = overrides.get("constraint", self.constraint)
        context = overrides.get("task_context", self.scope)
        task_input = {"uid": context.get("task_uid"), "target_city": context.get("target_city"),
                      "start_date": context.get("itinerary_dates", [None])[0],
                      "days": len(context.get("itinerary_dates", [])),
                      "additional_constraints": [constraint]}
        plan_input = copy.deepcopy(self.plan)
        plan_input["uid"] = context.get("plan_uid")
        plan_input["days"] = [copy.deepcopy(day) for day in plan_input["days"]]
        for day, day_date in zip(plan_input["days"], context.get("itinerary_dates", [])):
            day["date"] = day_date
            day["city"] = context.get("target_city")
        args = {"constraint": constraint, "policy": self.policy,
                "components": self.components, "scope": self.scope,
                "task_context": self.scope,
                "task_input": task_input, "plan_input": plan_input,
                "evidence_verifier": self.item_verifier if evidence_verifier is _DEFAULT else evidence_verifier,
                "inventory_verifier": self.inventory_verifier if inventory_verifier is _DEFAULT else inventory_verifier,
                "fact_verifier": self.fact_verifier if fact_verifier is _DEFAULT else fact_verifier,
                "context_verifier": self.context_verifier if context_verifier is _DEFAULT else context_verifier}
        args.update(overrides)
        return evaluate_cost_constraint(**args)

    def test_exactly_bound_compiled_budget_evaluates_after_all_three_gates(self):
        calls = {"item": 0, "inventory": 0, "fact": 0}
        def item(*_):
            calls["item"] += 1
            return True
        def inventory(*_):
            calls["inventory"] += 1
            return True
        def fact(constraint, result):
            calls["fact"] += 1
            self.assertEqual(constraint["expression"]["args"]["CNY"], 1000)
            self.assertEqual(result["value"], "950")
            return True
        result = self.evaluate(evidence_verifier=item, inventory_verifier=inventory,
                               fact_verifier=fact)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(calls, {"item": 3, "inventory": 1, "fact": 1})
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["real_trip_conclusion"])

    def test_over_limit_is_only_constraint_comparison(self):
        components = copy.deepcopy(self.components)
        components[0]["amount"] = 900
        result = self.evaluate(components=components)
        self.assertEqual(result["state"], "fail")
        self.assertFalse(result["real_trip_conclusion"])

    def test_json_float_with_lost_money_lexeme_cannot_pass_budget(self):
        source_token = "1.0000000000000001"
        components = [self.item("tickets", json.loads(source_token), 0),
                      self.item("transport", 0, 1), self.item("meals", 0, 2)]
        policy = {**self.policy, "total_limit": 1}
        constraint = compile_constraint({
            "id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 1, "people": 2,
                "includes": list(policy["required_categories"])}}})["constraint"]

        result = self.evaluate(policy=policy, constraint=constraint,
                               components=components)

        self.assertEqual(components[0]["amount"], 1.0)
        self.assertEqual(result["state"], "unknown")

    def test_raw_decimal_text_over_limit_fails_and_float_policy_limit_is_rejected(self):
        decimal_policy = {**self.policy, "total_limit": "0.1"}
        decimal_constraint = compile_constraint({
            "id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": "0.1", "people": 2,
                "includes": list(decimal_policy["required_categories"])}}})["constraint"]
        components = [self.item("tickets", "0.100000000000000005", 0),
                      self.item("transport", "0", 1), self.item("meals", "0", 2)]

        result = self.evaluate(policy=decimal_policy, constraint=decimal_constraint,
                               components=components)

        self.assertEqual(result["state"], "fail")
        self.assertEqual(result["aggregate"]["total_decimal"],
                         "0.100000000000000005")
        self.assertEqual(result["aggregate"]["comparison"], "over_limit")

        float_policy = {**self.policy, "total_limit": 0.1}
        string_limit_constraint = compile_constraint({
            "id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": "0.1", "people": 2,
                "includes": list(float_policy["required_categories"])}}})["constraint"]
        rejected = self.evaluate(policy=float_policy,
                                 constraint=string_limit_constraint)
        self.assertEqual(rejected["state"], "unknown")
        self.assertEqual(rejected["reason"], "cost_policy_constraint_mismatch")

    def test_tiny_exact_amount_above_limit_is_a_verified_failure(self):
        policy = {**self.policy, "total_limit": 1}
        constraint = compile_constraint({
            "id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most",
                           "args": {"CNY": 1, "people": 2,
                                    "includes": list(policy["required_categories"])}}
        })["constraint"]
        components = [self.item("tickets", 1),
                      self.item("transport", "0.00000000000000001"), self.item("meals", 0)]
        result = self.evaluate(policy=policy, constraint=constraint, components=components)
        self.assertEqual(result["state"], "fail")
        self.assertEqual(result["aggregate"]["total_decimal"], "1.00000000000000001")

    def test_decimal_tenth_plus_two_tenths_boundary_is_not_tolerance_adjusted(self):
        policy = {**self.policy, "total_limit": "0.3"}
        constraint = compile_constraint({
            "id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most",
                           "args": {"CNY": "0.3", "people": 2,
                                    "includes": list(policy["required_categories"])}}
        })["constraint"]
        components = [self.item("tickets", "0.1"),
                      self.item("transport", "0.2"), self.item("meals", 0)]
        result = self.evaluate(policy=policy, constraint=constraint, components=components)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["aggregate"]["total_decimal"], "0.3")

        # A preserved decimal that exceeds the limit must not be rounded away.
        components[0]["amount"] = "0.30000000000000004"
        components[1]["amount"] = 0
        result = self.evaluate(policy=policy, constraint=constraint, components=components)
        self.assertEqual(result["state"], "fail")
        self.assertEqual(result["aggregate"]["comparison"], "over_limit")

    def test_policy_categories_currency_people_and_cap_must_match_compiled_task(self):
        mutations = [
            ("categories", {"required_categories": ["tickets", "transport"]}),
            ("currency", {"currency": "USD"}),
            ("party_size", {"party_size": 3}),
            ("limit", {"total_limit": 999}),
            ("limit_type", {"total_limit": 1000.0}),
        ]
        for name, mutation in mutations:
            with self.subTest(name=name):
                result = self.evaluate(policy={**self.policy, **mutation})
                self.assertEqual(result["state"], "unknown")
                self.assertEqual(result["reason"], "cost_policy_constraint_mismatch")

    def test_uncompiled_or_wrong_operator_constraints_cannot_drive_cost_policy(self):
        raw = copy.deepcopy(self.constraint)
        raw.pop("compiler_status")
        self.assertEqual(self.evaluate(constraint=raw)["reason"], "constraint_not_compiled")
        raw = copy.deepcopy(self.constraint)
        raw["expression"]["op"] = "count_at_least"
        self.assertEqual(self.evaluate(constraint=raw)["reason"], "constraint_compilation_failed")

    def test_missing_aggregate_verifiers_keep_constraint_unknown(self):
        for name, overrides in (
                ("component", {"evidence_verifier": None}),
                ("inventory", {"inventory_verifier": None}),
                ("fact", {"fact_verifier": None}),
                ("context", {"context_verifier": None})):
            with self.subTest(name=name):
                result = self.evaluate(**overrides)
                self.assertEqual(result["state"], "unknown")

    def test_cost_scope_must_match_actual_task_plan_context(self):
        other_scope = {**self.scope, "plan_uid": "OTHER", "itinerary_dates": ["2099-01-01"]}
        result = self.evaluate(scope=other_scope)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "cost_scope_not_bound_to_task_plan")

        result = self.evaluate(context_verifier=lambda *_: False)
        self.assertEqual(result["state"], "unknown")

    def test_empty_plan_occurrences_or_forged_bindings_cannot_pass(self):
        empty_plan = copy.deepcopy(self.plan)
        for day in empty_plan["days"]:
            day["timeline"] = []
        result = self.evaluate(plan_input=empty_plan)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("cost_aggregate_unknown", result["reason"])

        forged_plan = copy.deepcopy(self.plan)
        forged_plan["days"][0]["timeline"][0]["entity_id"] = "other-entity"
        result = self.evaluate(plan_input=forged_plan)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("expense_occurrence_not_bound_to_plan", result["aggregate"]["reasons"])

        repeated = copy.deepcopy(self.components)
        repeated[1]["occurrence_bindings"][0] = copy.deepcopy(
            repeated[0]["occurrence_bindings"][0])
        repeated[1]["occurrence_bindings"][0]["expense_id"] = repeated[1]["expense_ids"][0]
        result = self.evaluate(components=repeated)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("expense_occurrence_missing_or_duplicate", result["aggregate"]["reasons"])

        unbound = copy.deepcopy(self.components)
        unbound[0]["occurrence_bindings"] = []
        result = self.evaluate(components=unbound)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("expense_occurrence_manifest_incomplete", result["aggregate"]["reasons"])

    def test_lodging_and_intercity_categories_are_unknown_even_with_visit_bindings(self):
        for category in ('rooms', 'accommodation', 'intercity', 'hotel', '住宿'):
            with self.subTest(category=category):
                constraint = compile_constraint({
                    "id": "budget", "strength": "hard",
                    "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
                    "expression": {"op": "total_cost_at_most", "args": {
                        "CNY": 1000, "people": 2,
                        "includes": [category, "transport", "meals"]}}})["constraint"]
                components = copy.deepcopy(self.components)
                components[0]["category"] = category
                policy = {**self.policy,
                          "required_categories": [category, "transport", "meals"]}
                result = self.evaluate(constraint=constraint, components=components, policy=policy)
                self.assertEqual(result["state"], "unknown")
                self.assertEqual(result["reason"], "cost_aggregate_unknown")
                expected_reason = ("lodging_manifest_missing_or_malformed"
                                   if category in {"rooms", "accommodation"} else
                                   "intercity_manifest_missing_or_malformed"
                                   if category == "intercity" else
                                   "cost_category_requires_unsupported_scope_manifest")
                self.assertIn(expected_reason, result["aggregate"]["reasons"])

    def test_context_verifier_mutation_is_unknown(self):
        def mutate(context, *_):
            context["plan_uid"] = "OTHER"
            return True
        result = self.evaluate(context_verifier=mutate)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "cost_context_verifier_mutated_input")

    def test_context_verifier_closure_mutation_of_original_inputs_is_unknown(self):
        policy = copy.deepcopy(self.policy)
        task_input = {"uid":"T1", "target_city":"X", "start_date":"2026-11-01",
                      "days":3, "additional_constraints":[self.constraint]}
        plan_input = copy.deepcopy(self.plan)
        mutation_attempted = []

        def mutate_originals(*_args):
            mutation_attempted.append(True)
            task_input["target_city"] = "Y"
            plan_input["days"][0]["city"] = "Y"
            policy["total_limit"] = 999
            return True

        result = self.evaluate(policy=policy, task_input=task_input,
            plan_input=plan_input, context_verifier=mutate_originals)

        self.assertTrue(mutation_attempted)
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(contains_pass_state(result))

    def test_fact_verifier_closure_mutation_of_original_inputs_is_unknown(self):
        policy = copy.deepcopy(self.policy)
        task_input = {"uid":"T1", "target_city":"X", "start_date":"2026-11-01",
                      "days":3, "additional_constraints":[self.constraint]}
        plan_input = copy.deepcopy(self.plan)
        mutation_attempted = []

        def mutate_originals(*_args):
            mutation_attempted.append(True)
            task_input["target_city"] = "Y"
            plan_input["days"][0]["city"] = "Y"
            policy["total_limit"] = 999
            return True

        result = self.evaluate(policy=policy, task_input=task_input,
            plan_input=plan_input, fact_verifier=mutate_originals)

        self.assertTrue(mutation_attempted)
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(contains_pass_state(result))

    def test_max_date_overflow_returns_unknown_without_raising(self):
        dates = ["9999-12-31", "9999-12-31"]
        context = {"task_uid":"T1", "plan_uid":"T1", "target_city":"X",
                   "itinerary_dates":dates}
        policy = {**self.policy, "trip_scope":copy.deepcopy(context)}

        result = self.evaluate(task_context=context, scope=context, policy=policy)

        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"],
                         "cost_itinerary_dates_incomplete_or_unordered")
        self.assertFalse(contains_pass_state(result))

    def test_raw_task_and_plan_objects_must_match_selected_constraint_and_context(self):
        task = {"uid":"T1","target_city":"X","start_date":"2026-11-01","days":3,
                "additional_constraints":[]}
        result = self.evaluate(task_input=task)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "cost_task_budget_constraint_missing_or_ambiguous")

        plan = {"uid":"T1","days":[{"date":"2026-11-01","city":"X"},
                                       {"date":"2026-11-02","city":"X"},
                                       {"date":"2026-11-04","city":"X"}]}
        result = self.evaluate(plan_input=plan)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "cost_plan_dates_or_target_mismatch")

    def test_aggregate_unknown_does_not_call_fact_verifier_or_become_failure(self):
        components = copy.deepcopy(self.components[:-1])
        calls = []
        result = self.evaluate(components=components,
                               fact_verifier=lambda *_: calls.append("called") or True)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(calls, [])

    def test_fact_verifier_mutation_cannot_upgrade_constraint(self):
        def mutate(constraint, fact):
            fact["value"] = 0
            return True
        result = self.evaluate(fact_verifier=mutate)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("constraint_fact_unverified", result["reason"])

    def test_existing_unknown_is_preserved_without_replacement(self):
        result = self.evaluate(existing_check={"state": "unknown", "reason": "prior_gap"})
        self.assertEqual(result["state"], "unknown")
        self.assertTrue(result["existing_unknown_preserved"])
        self.assertEqual(result["reason"], "existing_unknown_preserved")

    def test_existing_failure_is_preserved(self):
        result = self.evaluate(existing_check={"state": "fail", "reason": "prior_failure"})
        self.assertEqual(result["state"], "fail")
        self.assertEqual(result["new_constraint_state"], "pass")


if __name__ == "__main__":
    unittest.main()
