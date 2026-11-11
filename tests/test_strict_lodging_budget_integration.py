import copy
import unittest

from shorttrip.strict_constraint_compiler import compile_constraint
from shorttrip.strict_p31_bridge import diagnose_p31_plan


def fixture():
    dates = ["2026-11-15", "2026-11-16", "2026-11-17"]
    scope = {"task_uid": "task-lodge", "plan_uid": "task-lodge",
             "target_city": "西安", "itinerary_dates": dates}
    raw_constraint = {"id": "budget", "strength": "hard",
        "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
        "expression": {"op": "total_cost_at_most", "args": {
            "CNY": 1000, "people": 2, "includes": ["rooms", "tickets"]}}}
    constraint = compile_constraint(raw_constraint)["constraint"]
    task = {"uid": "task-lodge", "target_city": "西安", "start_date": dates[0],
        "days": 3, "people_number": 2,
        "generation": {"selected_entities_by_kind": {
            "accommodation": {"id": "hotel-7"}}},
        "additional_constraints": [constraint]}
    def stay_item(start, end):
        return {"type": "visit", "entity_id": "hotel-7", "entrance_id": "lobby",
                "start": start, "end": end}
    plan = {"uid": "task-lodge", "level": "easy", "days": [
        {"date": dates[0], "city": "西安", "timeline": [stay_item("09:00:00+08:00", "22:00:00+08:00")]},
        {"date": dates[1], "city": "西安", "timeline": [
            stay_item("08:00:00+08:00", "09:00:00+08:00"),
            {"type": "visit", "entity_id": "museum", "entrance_id": "main",
             "start": "10:00:00+08:00", "end": "11:00:00+08:00"},
            stay_item("20:00:00+08:00", "22:00:00+08:00")]},
        {"date": dates[2], "city": "西安", "timeline": [stay_item("08:00:00+08:00", "09:00:00+08:00")]}],
        "lodging_nights": [
            {"night_date": dates[index], "hotel_id": "hotel-7", "entrance_id": "lobby",
             "expense_id": f"room-night-{index + 1}"} for index in range(2)]}
    requirement = {**scope, "check_in": dates[0], "check_out": dates[-1],
        "hotel_id": "hotel-7", "room_type": "twin", "rooms": 1,
        "guests_per_room": 2, "minimum_beds": 2, "eligibility": "standard",
        "meal_plan": "none", "taxes_included": True,
        "mandatory_fees_included": True, "required_nights": dates[:2]}
    nights = []
    for index in range(2):
        nights.append({"night_date": dates[index], "hotel_id": "hotel-7",
            "entrance_id": "lobby", "expense_id": f"room-night-{index + 1}",
            "claim": {"entity_id": "hotel-7", "room_type": "twin",
                "check_in": dates[index], "check_out": dates[index + 1],
                "guests_per_room": 2, "currency": "CNY", "unit": "CNY/room/night",
                "rate": 300, "beds": 2, "max_guests_per_room": 2,
                "eligibility": "standard", "meal_plan": "none",
                "taxes_included": True, "mandatory_fees_included": True}})
    manifest = {"requirement": requirement, "nights": nights}
    lodging_component = {"category": "rooms", "amount": 600, "currency": "CNY",
        "party_size": 2, "scope": copy.deepcopy(scope),
        "expense_ids": ["room-night-1", "room-night-2"],
        "lodging_night_bindings": [
            {"expense_id": item["expense_id"], "night_date": item["night_date"],
             "hotel_id": item["hotel_id"], "entrance_id": item["entrance_id"]}
            for item in nights],
        "evidence": {"quote_refs": ["q1", "q2"]}, "conflict": False}
    ticket = {"category": "tickets", "amount": 100, "currency": "CNY",
        "party_size": 2, "scope": copy.deepcopy(scope),
        "evidence": {"ticket_ref": "t1"}, "expense_ids": ["ticket-1"],
        "occurrence_bindings": [{"expense_id": "ticket-1", "day_index": 1,
            "item_index": 1, "date": dates[1], "type": "visit", "entity_id": "museum"}]}
    policy = {"required_categories": ["rooms", "tickets"], "currency": "CNY",
        "party_size": 2, "total_limit": 1000, "trip_scope": copy.deepcopy(scope)}
    payload = {"constraint_id": "budget", "policy": policy,
        "components": [lodging_component, ticket], "scope": copy.deepcopy(scope),
        "lodging_manifest": manifest}
    return task, plan, constraint, payload


class StrictLodgingBudgetIntegrationTests(unittest.TestCase):
    def diagnose(self, task, plan, payload):
        return diagnose_p31_plan(plan, task=task, now="2026-10-31T00:00:00Z",
            registry={}, cost_aggregation=payload,
            cost_evidence_verifier=lambda *_: True,
            cost_inventory_verifier=lambda *_: True,
            cost_context_verifier=lambda *_: True,
            cost_lodging_claim_verifier=lambda *_: True,
            cost_lodging_inventory_verifier=lambda *_: True,
            constraint_fact_verifier=lambda *_: True)

    def test_rooms_alias_is_revalidated_in_current_task_plan_budget_chain(self):
        task, plan, _constraint, payload = fixture()
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "pass")
        self.assertEqual(result["trip_cost_aggregation_check"]["aggregate"]["total_decimal"], "700")
        # The P31 budget and mapped constraint remain unknown as independent checks.
        self.assertIn("budget", [item["field"] for item in result["unknown_checks"]])
        self.assertIn("constraint:budget", [item["field"] for item in result["unknown_checks"]])
        self.assertFalse(result["truth_certified"])

    def test_valid_lodging_cannot_certify_unmodeled_intercity_cost(self):
        task, plan, _constraint, payload = fixture()
        constraint = compile_constraint({'id':'budget', 'strength':'hard',
            'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':1000,'people':2,
                          'includes':['rooms','tickets','intercity']}}})['constraint']
        task['additional_constraints'] = [constraint]
        payload['policy']['required_categories'].append('intercity')
        fake_intercity = copy.deepcopy(payload['components'][1])
        fake_intercity['category'] = 'intercity'
        fake_intercity['expense_ids'] = ['unverified-fare']
        fake_intercity['occurrence_bindings'][0]['expense_id'] = 'unverified-fare'
        payload['components'].append(fake_intercity)
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result['trip_cost_aggregation_check']['state'], 'unknown')
        self.assertIn('intercity_manifest_missing_or_malformed',
                      result['trip_cost_aggregation_check']['aggregate']['reasons'])

    def test_accommodation_alias_requires_compiled_policy_to_use_same_name(self):
        task, plan, _constraint, payload = fixture()
        payload["policy"]["required_categories"] = ["accommodation", "tickets"]
        payload["components"][0]["category"] = "accommodation"
        constraint = compile_constraint({"id": "budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 1000, "people": 2,
                "includes": ["accommodation", "tickets"]}}})["constraint"]
        task["additional_constraints"] = [constraint]
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "pass")

        # An accommodation component cannot silently satisfy a rooms constraint.
        task, plan, _constraint, payload = fixture()
        payload["components"][0]["category"] = "accommodation"
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "unknown")

    def test_caller_supplied_pass_result_is_not_a_raw_manifest(self):
        task, plan, _constraint, payload = fixture()
        payload["lodging_manifest"] = {"state": "pass", "total_cny": 0}
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "unknown")
        self.assertIn("lodging_manifest_missing_or_malformed",
                      result["trip_cost_aggregation_check"]["aggregate"]["reasons"])

    def test_cross_category_expense_id_duplicate_is_unknown(self):
        task, plan, _constraint, payload = fixture()
        payload["components"][1]["expense_ids"] = ["room-night-1"]
        payload["components"][1]["occurrence_bindings"][0]["expense_id"] = "room-night-1"
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "unknown")
        self.assertIn("expense_id_duplicate_across_categories",
                      result["trip_cost_aggregation_check"]["aggregate"]["reasons"])

    def test_mixed_rooms_and_accommodation_policy_aliases_remain_unknown(self):
        task, plan, _constraint, payload = fixture()
        payload["policy"]["required_categories"] = ["rooms", "accommodation", "tickets"]
        result = self.diagnose(task, plan, payload)
        self.assertEqual(result["trip_cost_aggregation_check"]["state"], "unknown")
        self.assertTrue(result["unknown_checks"])


if __name__ == "__main__":
    unittest.main()
