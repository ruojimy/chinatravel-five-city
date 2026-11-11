import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.strict_tag_constraints import evaluate_tag_constraint


ITEMS = ["a1", "a2"]
TRIP = {"domain": "trip"}


def preference(quantifier="all", *, strength="soft", tag="walkable"):
    return {"strength": strength, "scope": {"domain": "trip", "quantifier": quantifier},
            "expression": {"op": "prefer_tag", "args": {"tag": tag}}}


def tagfacts(tag="walkable", values=(True, True)):
    return [{"item_id": item, "tag": tag, "present": value, "scope": dict(TRIP),
             "catalog_category": "ignored", "verified": True}
            for item, value in zip(ITEMS, values)]


def trusted_verifier(*facts):
    return lambda _constraint, fact: any(fact == trusted for trusted in facts)


def checked(constraint, facts, verifier=None, **kwargs):
    kwargs.setdefault("scope_verifier", lambda _constraint, items: set(items) == set(ITEMS))
    return evaluate_tag_constraint(constraint, scope_items=ITEMS, tag_facts=facts,
        fact_verifier=verifier, **kwargs)


class StrictTagConstraintTests(unittest.TestCase):
    def test_unknown_tag_name_cannot_pass_hard_exclusion(self):
        constraint = {'strength':'hard', 'scope':{'domain':'trip','quantifier':'all'},
                      'expression':{'op':'exclude_tag','args':{'tag':'unknown'}}}
        facts = [{'item_id':'a','tag':'unknown','present':False,'scope':{'domain':'trip'}}]
        result = evaluate_tag_constraint(constraint, scope_items=['a'], tag_facts=facts,
            scope_verifier=lambda *_: True, fact_verifier=lambda *_: True)
        self.assertEqual(result['state'], 'unknown')

    def test_unknown_scope_entity_cannot_pass_hard_exclusion(self):
        constraint = {'strength':'hard', 'scope':{'domain':'trip','quantifier':'all'},
                      'expression':{'op':'exclude_tag','args':{'tag':'stairs'}}}
        for entity in ('unknown', 'unresolved_id', '待核验'):
            facts = [{'item_id':entity,'tag':'stairs','present':False,'scope':{'domain':'trip'}}]
            result = evaluate_tag_constraint(constraint, scope_items=[entity], tag_facts=facts,
                scope_verifier=lambda *_: True, fact_verifier=lambda *_: True)
            with self.subTest(entity=entity):
                self.assertEqual(result['state'], 'unknown')

    def test_scope_or_fact_callback_cannot_change_original_inputs(self):
        for callback_type in ('scope', 'fact'):
            constraint, facts = preference(), tagfacts()
            def mutate(*_args):
                facts[0]['present'] = False
                return True
            callbacks = {'scope_verifier': lambda *_: True, 'fact_verifier': lambda *_: True}
            callbacks[callback_type + '_verifier'] = mutate
            result = evaluate_tag_constraint(constraint, scope_items=list(ITEMS),
                                              tag_facts=facts, **callbacks)
            with self.subTest(callback_type=callback_type):
                self.assertEqual(result['state'], 'unknown')
                self.assertIn('tag_original_inputs_mutated_or_unavailable', result['reasons'])

    def test_preference_is_soft_and_requires_verified_explicit_tag_facts(self):
        c = preference()
        facts = tagfacts(values=(True, True))
        absent = checked(c, facts)
        self.assertEqual(absent["state"], "unknown")
        self.assertEqual(absent["soft_state"], "unknown")
        self.assertEqual(absent["hard_state"], "not_applicable")
        self.assertIn("independent_fact_verifier_required", absent["reasons"])
        out = checked(c, facts, trusted_verifier(*facts))
        self.assertEqual(out["soft_state"], "satisfied")
        self.assertEqual(out["hard_state"], "not_applicable")
        self.assertFalse(out["truth_certified"])

    def test_all_and_any_are_explicit_and_have_different_preference_meanings(self):
        facts = tagfacts(values=(True, False))
        all_result = checked(preference("all"), facts, trusted_verifier(*facts))
        any_result = checked(preference("any"), facts, trusted_verifier(*facts))
        self.assertEqual(all_result["soft_state"], "unsatisfied")
        self.assertEqual(any_result["soft_state"], "satisfied")

    def test_missing_or_invalid_trip_quantifier_stays_unknown(self):
        facts = tagfacts()
        for scope in ({"domain": "trip"}, {"domain": "trip", "quantifier": "most"},
                      {"quantifier": "all"}):
            c = preference()
            c["scope"] = scope
            out = checked(c, facts, trusted_verifier(*facts))
            self.assertEqual(out["state"], "unknown")
            self.assertTrue(any("scope" in reason for reason in out["reasons"]))

    def test_all_scope_facts_required_even_for_any_quantifier(self):
        c = preference("any")
        facts = tagfacts(values=(True,))
        out = checked(c, facts, trusted_verifier(*facts))
        self.assertEqual(out["soft_state"], "unknown")
        self.assertIn("tag_fact_scope_incomplete", out["reasons"])

    def test_scope_inventory_requires_its_own_independent_verifier(self):
        facts = tagfacts()
        out = evaluate_tag_constraint(preference(), scope_items=ITEMS, tag_facts=facts,
            fact_verifier=trusted_verifier(*facts))
        self.assertEqual(out["state"], "unknown")
        self.assertIn("independent_scope_verifier_required", out["reasons"])
        failed = checked(preference(), facts, trusted_verifier(*facts),
                         scope_verifier=lambda *_: False)
        self.assertIn("independent_scope_verification_failed", failed["reasons"])

    def test_explicit_item_kind_requires_exact_scoped_facts_and_inventory_review(self):
        c = preference("any")
        c["scope"]["item_kind"] = "restaurant"
        facts = [{"item_id": item, "item_kind": "restaurant", "tag": "walkable",
                  "present": value, "scope": {"domain": "trip", "item_kind": "restaurant"}}
                 for item, value in zip(ITEMS, (False, True))]
        facts_trusted = trusted_verifier(*facts)
        reviewed_inventory = {"restaurant": list(ITEMS), "attraction": ["other-item"]}
        scope_cb = lambda constraint, items: (
            constraint["scope"].get("item_kind") == "restaurant"
            and list(items) == reviewed_inventory["restaurant"])
        out = evaluate_tag_constraint(c, scope_items=ITEMS, tag_facts=facts,
            fact_verifier=facts_trusted, scope_verifier=scope_cb)
        self.assertEqual(out["soft_state"], "satisfied")

        wrong_scope_facts = [dict(f, item_kind="attraction",
            scope={"domain": "trip", "item_kind": "attraction"}) for f in facts]
        out = evaluate_tag_constraint(c, scope_items=ITEMS, tag_facts=wrong_scope_facts,
            fact_verifier=trusted_verifier(*wrong_scope_facts),
            scope_verifier=lambda *_: True)
        self.assertEqual(out["state"], "unknown")
        self.assertIn("tag_fact_value_or_scope_invalid", out["reasons"])
        out = evaluate_tag_constraint(c, scope_items=ITEMS[:-1], tag_facts=facts,
            fact_verifier=facts_trusted, scope_verifier=scope_cb)
        self.assertIn("independent_scope_verification_failed", out["reasons"])

    def test_invalid_item_kind_scope_is_unknown(self):
        c = preference()
        c["scope"]["item_kind"] = "menu_category"
        out = checked(c, tagfacts(), trusted_verifier(*tagfacts()))
        self.assertIn("trip_scope_item_kind_invalid", out["reasons"])
        c["scope"]["item_kind"] = None
        out = checked(c, tagfacts(), trusted_verifier(*tagfacts()))
        self.assertIn("trip_scope_item_kind_invalid", out["reasons"])

    def test_exclusion_is_hard_and_negation_uses_explicit_quantifier(self):
        c = {"strength": "hard", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "exclude_tag", "args": {"tag": "night_activity"}}}
        facts = tagfacts(tag="night_activity", values=(False, True))
        out = checked(c, facts, trusted_verifier(*facts))
        self.assertEqual(out["hard_state"], "fail")
        self.assertEqual(out["soft_state"], "not_applicable")
        c["scope"]["quantifier"] = "any"
        out = checked(c, facts, trusted_verifier(*facts))
        self.assertEqual(out["hard_state"], "pass")
        self.assertEqual(out["quantifier"], "any")

    def test_conditional_preference_requires_independently_verified_condition_and_tag(self):
        c = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "any"},
             "expression": {"op": "conditional_prefer_tag", "args": {
                 "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}}
        condition = {"key": "weather", "value": "rain", "scope": dict(TRIP), "verified": True}
        facts = tagfacts(tag="setting:indoor", values=(False, True))
        no_condition_verifier = checked(c, facts, trusted_verifier(*facts), condition_facts=[condition])
        self.assertEqual(no_condition_verifier["state"], "unknown")
        verifier = trusted_verifier(condition, *facts)
        out = checked(c, facts, verifier, condition_facts=[condition])
        self.assertEqual(out["condition_state"], "true")
        self.assertEqual(out["soft_state"], "satisfied")

    def test_verified_false_condition_does_not_require_or_consume_tag_facts(self):
        c = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "conditional_prefer_tag", "args": {
                 "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}}
        condition = {"key": "weather", "value": "clear", "scope": dict(TRIP)}
        out = checked(c, [], trusted_verifier(condition), condition_facts=[condition])
        self.assertEqual(out["condition_state"], "false")
        self.assertEqual(out["soft_state"], "not_applicable")

    def test_unknown_or_unverified_condition_context_stays_unknown(self):
        c = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "conditional_prefer_tag", "args": {
                 "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}}
        unknown = checked(c, [], trusted_verifier(), condition_facts=[])
        self.assertEqual(unknown["state"], "unknown")
        bad = {"key": "weather", "value": "rain", "scope": {"domain": "city"}}
        out = checked(c, [], trusted_verifier(bad), condition_facts=[bad])
        self.assertEqual(out["state"], "unknown")
        self.assertIn("condition_fact_scope_or_value_invalid", out["reasons"])
        unknown_value = {"key": "weather", "value": "unknown", "scope": dict(TRIP)}
        out = checked(c, [], trusted_verifier(unknown_value), condition_facts=[unknown_value])
        self.assertEqual(out["condition_state"], "unknown")
        self.assertIn("condition_fact_scope_or_value_invalid", out["reasons"])

    def test_condition_type_mismatch_nan_and_malformed_fact_stay_unknown(self):
        c = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "conditional_prefer_tag", "args": {
                 "if": {"weather": True}, "prefer": {"setting": "indoor"}}}}
        numeric = {"key": "weather", "value": 1, "scope": dict(TRIP)}
        out = checked(c, [], trusted_verifier(numeric), condition_facts=[numeric])
        self.assertEqual(out["state"], "unknown")
        self.assertIn("condition_fact_expected_type_mismatch", out["reasons"])

        c["expression"]["args"]["if"]["weather"] = float("nan")
        valid = {"key": "weather", "value": True, "scope": dict(TRIP)}
        out = checked(c, [], trusted_verifier(valid), condition_facts=[valid])
        self.assertIn("conditional_expression_malformed", out["reasons"])
        c["expression"]["args"]["if"]["weather"] = True
        out = checked(c, [], trusted_verifier(valid), condition_facts=[None, valid])
        self.assertIn("condition_fact_not_object", out["reasons"])

        invalid = {"key": "weather", "value": float("nan"), "scope": dict(TRIP)}
        out = checked(c, [], trusted_verifier(invalid), condition_facts=[invalid])
        self.assertIn("condition_fact_scope_or_value_invalid", out["reasons"])

    def test_verifier_mutation_of_fact_or_scope_input_cannot_change_checked_result(self):
        c = preference()
        facts = tagfacts(values=(False, False))
        def mutate_fact(_constraint, fact):
            fact["present"] = True
            return True
        out = checked(c, facts, mutate_fact)
        self.assertEqual(out["state"], "unknown")
        self.assertIn("tag_fact_mutated_during_verification", out["reasons"])
        self.assertEqual([f["present"] for f in facts], [False, False])

        facts = tagfacts(values=(True, True))
        def mutate_inventory(_constraint, items):
            items.clear()
            return True
        items = list(ITEMS)
        out = evaluate_tag_constraint(c, scope_items=items, tag_facts=facts,
            fact_verifier=trusted_verifier(*facts), scope_verifier=mutate_inventory)
        self.assertEqual(out["soft_state"], "unknown")
        self.assertIn("independent_scope_verification_failed", out["reasons"])
        self.assertEqual(items, ITEMS)

        def mutate_condition(_constraint, fact):
            fact["value"] = "clear"
            return True
        conditional = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "conditional_prefer_tag", "args": {
                 "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}}
        condition = {"key": "weather", "value": "rain", "scope": dict(TRIP)}
        out = checked(conditional, [], mutate_condition, condition_facts=[condition])
        self.assertEqual(out["state"], "unknown")
        self.assertIn("condition_fact_mutated_during_verification", out["reasons"])
        self.assertEqual(condition["value"], "rain")

    def test_fact_verifiers_cannot_mutate_the_constraint_to_change_its_meaning(self):
        exclusion = {"strength": "hard", "scope": {"domain": "trip", "quantifier": "all"},
                     "expression": {"op": "exclude_tag", "args": {"tag": "night_activity"}}}
        facts = tagfacts(tag="night_activity", values=(True, True))

        def rewrite_to_preference(constraint, _fact):
            constraint["expression"]["op"] = "prefer_tag"
            return True

        out = checked(exclusion, facts, rewrite_to_preference)
        self.assertEqual(out["hard_state"], "unknown")
        self.assertIn("constraint_mutated_during_verification", out["reasons"])
        self.assertEqual(exclusion["expression"]["op"], "exclude_tag")

        conditional = {"strength": "soft", "scope": {"domain": "trip", "quantifier": "all"},
            "expression": {"op": "conditional_prefer_tag", "args": {
                "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}}
        condition = {"key": "weather", "value": "rain", "scope": dict(TRIP)}

        def rewrite_condition(constraint, _fact):
            constraint["expression"]["args"]["if"]["weather"] = "clear"
            return True

        out = checked(conditional, [], rewrite_condition, condition_facts=[condition])
        self.assertEqual(out["state"], "unknown")
        self.assertIn("constraint_mutated_during_verification", out["reasons"])
        self.assertEqual(conditional["expression"]["args"]["if"]["weather"], "rain")

    def test_scope_verifier_receives_copies_and_cannot_mutate_inputs(self):
        constraint = preference("all")
        facts = tagfacts(values=(True, True))
        items = list(ITEMS)

        def mutate_scope_inputs(candidate, inventory):
            candidate["scope"]["quantifier"] = "any"
            inventory.clear()
            return True

        out = evaluate_tag_constraint(constraint, scope_items=items, tag_facts=facts,
            fact_verifier=trusted_verifier(*facts), scope_verifier=mutate_scope_inputs)
        self.assertEqual(out["state"], "unknown")
        self.assertIn("independent_scope_verification_failed", out["reasons"])
        self.assertEqual(constraint["scope"]["quantifier"], "all")
        self.assertEqual(items, ITEMS)
    def test_verifier_must_return_literal_true_and_duplicate_facts_are_rejected(self):
        c = preference()
        facts = tagfacts()
        self.assertEqual(checked(c, facts, lambda *_: 1)["state"], "unknown")
        dup = facts + [dict(facts[0])]
        out = checked(c, dup, lambda *_: True)
        self.assertIn("duplicate_tag_fact_for_scope_item", out["reasons"])

    def test_tag_verifier_bool_int_mutation_is_detected_without_changing_input(self):
        c = {"strength": "hard", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "exclude_tag", "args": {"tag": "night_activity"}}}
        facts = tagfacts(tag="night_activity", values=(True, True))

        def change_presence_type(_constraint, fact):
            fact["present"] = 1
            return True

        out = checked(c, facts, change_presence_type)
        self.assertEqual(out["hard_state"], "unknown")
        self.assertIn("tag_fact_mutated_during_verification", out["reasons"])
        self.assertTrue(all(type(f["present"]) is bool and f["present"] for f in facts))

    def test_cyclic_and_deep_tag_facts_fail_closed_without_input_mutation(self):
        c = preference()
        facts = tagfacts(values=(True, True))
        cycle = {}
        cycle["self"] = cycle
        facts[0]["opaque"] = cycle
        out = checked(c, facts, lambda *_: True)
        self.assertEqual(out["state"], "unknown")
        self.assertIs(facts[0]["opaque"]["self"], facts[0]["opaque"])

        nested = []
        cursor = nested
        for _ in range(300):
            child = []
            cursor.append(child)
            cursor = child
        facts = tagfacts(values=(True, True))
        facts[0]["opaque"] = nested
        out = checked(c, facts, lambda *_: True)
        self.assertEqual(out["state"], "unknown")
        self.assertEqual(len(nested[0][0]), 1)

    def test_strength_mismatch_and_category_only_evidence_never_pass(self):
        facts = tagfacts(values=(True, True))
        c = preference(strength="hard")
        self.assertIn("preference_strength_must_be_soft",
                      checked(c, facts, trusted_verifier(*facts))["reasons"])
        c = {"strength": "hard", "scope": {"domain": "trip", "quantifier": "all"},
             "expression": {"op": "exclude_tag", "args": {"tag": "attraction"}}}
        # No tag facts are inferred from the entities' attraction category.
        out = checked(c, [], trusted_verifier())
        self.assertEqual(out["hard_state"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
