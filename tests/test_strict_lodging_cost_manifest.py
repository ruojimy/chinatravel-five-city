import copy
import unittest

from shorttrip.strict_lodging_cost_manifest import evaluate_lodging_cost_manifest


def fixture():
    task = {"uid": "task-1", "target_city": "西安", "start_date": "2026-11-15",
            "days": 3, "people_number": 2,
            "generation": {"selected_entities_by_kind": {
                "accommodation": {"id": "hotel-7"}}}}
    dates = ["2026-11-15", "2026-11-16", "2026-11-17"]
    scope = {"task_uid": "task-1", "plan_uid": "task-1",
             "target_city": "西安", "itinerary_dates": dates}
    ids = ["roomnight-15", "roomnight-16"]
    timeline = lambda start, end: [{"type": "visit", "entity_id": "hotel-7",
        "entrance_id": "lobby-a", "start": start, "end": end}]
    plan = {"uid": "task-1", "days": [
        {"date": dates[0], "city": "西安",
         "timeline": timeline("09:00:00+08:00", "22:00:00+08:00")},
        {"date": dates[1], "city": "西安",
         "timeline": timeline("08:00:00+08:00", "22:00:00+08:00")},
        {"date": dates[2], "city": "西安",
         "timeline": timeline("08:00:00+08:00", "09:00:00+08:00")}],
        "lodging_nights": [
            {"night_date": day, "hotel_id": "hotel-7", "entrance_id": "lobby-a",
             "expense_id": expense_id}
            for day, expense_id in zip(dates[:2], ids)]}
    requirement = {**scope, "check_in": dates[0], "check_out": dates[-1],
        "hotel_id": "hotel-7", "room_type": "twin", "rooms": 1,
        "guests_per_room": 2, "minimum_beds": 2, "eligibility": "standard",
        "meal_plan": "none", "taxes_included": True,
        "mandatory_fees_included": True, "required_nights": dates[:2]}
    nights = []
    for index, (day, expense_id) in enumerate(zip(dates[:2], ids)):
        next_day = dates[index + 1]
        nights.append({"night_date": day, "hotel_id": "hotel-7",
            "entrance_id": "lobby-a", "expense_id": expense_id,
            "claim": {"entity_id": "hotel-7", "room_type": "twin",
                "check_in": day, "check_out": next_day, "guests_per_room": 2,
                "currency": "CNY", "unit": "CNY/room/night", "rate": 300,
                "beds": 2, "max_guests_per_room": 2, "eligibility": "standard",
                "meal_plan": "none", "taxes_included": True,
                "mandatory_fees_included": True}})
    component = {"category": "accommodation", "amount": 600, "currency": "CNY",
        "party_size": 2, "scope": copy.deepcopy(scope), "expense_ids": list(ids),
        "lodging_night_bindings": [
            {"expense_id": item["expense_id"], "night_date": item["night_date"],
             "hotel_id": item["hotel_id"], "entrance_id": item["entrance_id"]}
            for item in nights],
        "evidence": {"source_refs": ["quote-15", "quote-16"]}, "conflict": False}
    return task, plan, requirement, nights, component


def evaluate(args, *, claim_verifier=lambda *_: True,
             inventory_verifier=lambda *_: True, required_categories=None):
    return evaluate_lodging_cost_manifest(*args, claim_verifier=claim_verifier,
        inventory_verifier=inventory_verifier,
        required_categories=(required_categories or [args[4]["category"]]))


class StrictLodgingCostManifestTests(unittest.TestCase):
    def test_verifier_cannot_mutate_original_manifest_through_closure(self):
        for callback_type in ('claim', 'inventory'):
            with self.subTest(callback_type=callback_type):
                args = fixture()
                def mutate(*_args):
                    args[2]['rooms'] = 5
                    return True
                callbacks = {callback_type + '_verifier': mutate}
                self.assertEqual(evaluate(args, **callbacks)['reason'],
                                 'lodging_original_inputs_mutated')

    def test_two_explicit_nights_bind_to_task_plan_and_expense_inventory(self):
        result = evaluate(fixture())
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["night_count"], 2)
        self.assertEqual(result["total_decimal"], "600")
        self.assertEqual(result["currency"], "CNY")
        self.assertTrue(result["taxes_included"])
        self.assertFalse(result["real_trip_conclusion"])

    def test_missing_across_night_is_unknown(self):
        args = fixture()
        args[3].pop()
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_night_inventory_incomplete")

    def test_duplicate_expense_or_night_is_unknown(self):
        args = fixture()
        args[3][1]["expense_id"] = args[3][0]["expense_id"]
        args[4]["expense_ids"][1] = args[4]["expense_ids"][0]
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_expense_id_missing_or_duplicate")

        args = fixture()
        args[3][1]["night_date"] = args[3][0]["night_date"]
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_nights_missing_duplicate_or_out_of_scope")

    def test_quote_range_currency_and_component_amount_conflicts_are_unknown(self):
        for mutate in (
            lambda args: args[3][1]["claim"].update(check_in="2026-11-17"),
            lambda args: args[3][0]["claim"].update(currency="USD"),
            lambda args: args[4].update(amount=599),
            lambda args: args[4].update(scope={"task_uid": "other"}),
        ):
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args)
                self.assertEqual(evaluate(args)["state"], "unknown")

    def test_task_plan_hotel_identity_is_mechanically_bound(self):
        args = fixture()
        args[2]["hotel_id"] = "invented-hotel"
        self.assertEqual(evaluate(args)["reason"],
                         "lodging_hotel_not_bound_to_task_candidate")
        args = fixture()
        args[1]["lodging_nights"][1]["hotel_id"] = "other-hotel"
        self.assertEqual(evaluate(args)["reason"],
                         "lodging_plan_night_identity_or_coverage_mismatch")

    def test_forged_plan_night_list_must_match_adjacent_timeline_endpoints(self):
        args = fixture()
        args[1]["days"][1]["timeline"][0]["entity_id"] = "other-hotel"
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"],
                         "lodging_timeline_boundary_not_bound_to_hotel")

        args = fixture()
        args[1]["days"][1]["timeline"][0].pop("entrance_id")
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_timeline_boundary_unrepresented")

    def test_per_night_decimal_room_multiplication_keeps_full_precision(self):
        args = fixture()
        rooms = 10 ** 40
        people = rooms * 2
        args[0]["people_number"] = people
        args[2]["rooms"] = rooms
        for item in args[3]:
            item["claim"]["rate"] = "0.12345678901234566"
        from decimal import Decimal, localcontext
        with localcontext() as context:
            context.prec = 200
            exact_total = Decimal("0.12345678901234566") * Decimal(rooms) * 2
        args[4]["party_size"] = people
        args[4]["amount"] = str(exact_total)
        result = evaluate(args)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["total_decimal"], str(exact_total))

    def test_claim_and_inventory_verifier_mutation_fails_closed(self):
        args = fixture()
        before = copy.deepcopy(args)
        def mutate_claim(requirement, claim):
            claim["rate"] = 1
            return True
        result = evaluate(args, claim_verifier=mutate_claim)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(args, before)

        args = fixture()
        before = copy.deepcopy(args)
        def mutate_inventory(_task, plan, *_):
            plan["uid"] = "tampered"
            return True
        result = evaluate(args, inventory_verifier=mutate_inventory)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_inventory_unverified_or_mutated")
        self.assertEqual(args, before)

    def test_missing_verifier_or_unverified_price_stays_unknown(self):
        args = fixture()
        result = evaluate_lodging_cost_manifest(*args, claim_verifier=None,
            inventory_verifier=lambda *_: True,
            required_categories=["accommodation"])
        self.assertEqual(result["state"], "unknown")
        args = fixture()
        result = evaluate(args, inventory_verifier=lambda *_: False)
        self.assertEqual(result["state"], "unknown")

    def test_rooms_alias_requires_exact_single_policy_category(self):
        args = fixture()
        args[4]["category"] = "rooms"
        self.assertEqual(evaluate(args, required_categories=["rooms"])["state"], "pass")
        self.assertEqual(evaluate(args, required_categories=["accommodation"])["reason"],
                         "lodging_policy_category_mismatch")
        self.assertEqual(evaluate(args, required_categories=["rooms", "accommodation"])["reason"],
                         "lodging_policy_category_mismatch")
        args[4]["category"] = "accommodation"
        self.assertEqual(evaluate(args, required_categories=["accommodation"])["state"], "pass")

    def test_non_string_required_category_items_return_unknown(self):
        for invalid_item in ([], {}, set()):
            with self.subTest(invalid_item=type(invalid_item).__name__):
                args = fixture()
                result = evaluate(args, required_categories=[invalid_item])
                self.assertEqual(result["state"], "unknown")
                self.assertEqual(result["reason"], "lodging_policy_category_mismatch")

    def test_expense_ids_are_normalized_for_duplicate_detection(self):
        args = fixture()
        args[3][1]["expense_id"] = " ROOMNIGHT-15 "
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_expense_id_missing_or_duplicate")

    def test_unknown_entrance_and_expense_placeholders_are_rejected(self):
        args = fixture()
        for day in args[1]["days"]:
            day["timeline"][0]["entrance_id"] = "unknown"
        for item in args[1]["lodging_nights"]:
            item["entrance_id"] = "unknown"
        for item in args[3]:
            item["entrance_id"] = "unknown"
        for item in args[4]["lodging_night_bindings"]:
            item["entrance_id"] = "unknown"
        self.assertEqual(evaluate(args)["state"], "unknown")

        args = fixture()
        ids = ["unknown", "expense-16"]
        for inventory, expense_id in zip(args[1]["lodging_nights"], ids):
            inventory["expense_id"] = expense_id
        for night, expense_id in zip(args[3], ids):
            night["expense_id"] = expense_id
        args[4]["expense_ids"] = list(ids)
        for binding, expense_id in zip(args[4]["lodging_night_bindings"], ids):
            binding["expense_id"] = expense_id
        self.assertEqual(evaluate(args)["state"], "unknown")

    def test_unknown_hotel_identity_is_rejected_by_underlying_lodging_check(self):
        args = fixture()
        args[0]["generation"]["selected_entities_by_kind"]["accommodation"]["id"] = "unknown"
        args[2]["hotel_id"] = "unknown"
        for day in args[1]["days"]:
            day["timeline"][0]["entity_id"] = "unknown"
        for item in args[1]["lodging_nights"]:
            item["hotel_id"] = "unknown"
        for night in args[3]:
            night["hotel_id"] = "unknown"
            night["claim"]["entity_id"] = "unknown"
        for binding in args[4]["lodging_night_bindings"]:
            binding["hotel_id"] = "unknown"
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "lodging_task_hotel_identity_missing")

    def test_unknown_task_and_plan_ids_are_rejected(self):
        args = fixture()
        args[0]["uid"] = "unknown"
        args[1]["uid"] = "unknown"
        args[2]["task_uid"] = "unknown"
        args[2]["plan_uid"] = "unknown"
        args[4]["scope"]["task_uid"] = "unknown"
        args[4]["scope"]["plan_uid"] = "unknown"
        self.assertEqual(evaluate(args)["state"], "unknown")

    def test_large_integral_total_preserves_exact_value(self):
        args = fixture()
        for night in args[3]:
            night["claim"]["rate"] = 9007199254740993
        args[4]["amount"] = "18014398509481986"
        result = evaluate(args)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["total_decimal"], "18014398509481986")
        from decimal import Decimal
        self.assertEqual(Decimal(str(result["total_cny"])),
                         Decimal(result["total_decimal"]))

    def test_invalid_three_day_date_sequence_returns_unknown(self):
        args = fixture()
        args[0]["start_date"] = "9999-12-30"
        args[2]["itinerary_dates"] = ["9999-12-30", "9999-12-31", "9999-12-31"]
        args[1]["days"] = [{"date": day, "city": "西安", "timeline": []}
                            for day in args[2]["itinerary_dates"]]
        self.assertEqual(evaluate(args)['state'], 'unknown')

    def test_fractional_total_has_decimal_authority_and_no_float_shortcut(self):
        args = fixture()
        for night in args[3]:
            night["claim"]["rate"] = "0.1"
        args[4]["amount"] = "0.2"
        result = evaluate(args)
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["total_decimal"], "0.2")
        self.assertIsNone(result["total_cny"])

    def test_float_rate_cannot_retain_original_json_decimal_lexeme(self):
        for lexical, total in (("0.1", "0.2"),
                               ("0.10000000000000001", "0.20000000000000002")):
            args = fixture()
            for night in args[3]:
                night["claim"]["rate"] = float(lexical)
            args[4]["amount"] = total
            self.assertEqual(evaluate(args)["state"], "unknown")
            for night in args[3]:
                night["claim"]["rate"] = lexical
            result = evaluate(args)
            self.assertEqual(result["state"], "pass")
            self.assertEqual(result["total_decimal"], total)

    def test_float_component_amount_is_not_exact_evidence(self):
        args = fixture()
        args[4]["amount"] = 600.0
        self.assertEqual(evaluate(args)["state"], "unknown")

    def test_malformed_category_timeline_kind_and_selected_entities_fail_closed(self):
        args = fixture()
        args[4]["category"] = []
        result = evaluate(args, required_categories=["accommodation"])
        self.assertEqual(result["state"], "unknown")

        args = fixture()
        args[1]["days"][0]["timeline"][0]["type"] = []
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")

        args = fixture()
        args[0]["generation"]["selected_entities_by_kind"] = []
        result = evaluate(args)
        self.assertEqual(result["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
