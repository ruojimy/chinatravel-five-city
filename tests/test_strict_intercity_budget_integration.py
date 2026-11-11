import copy
import unittest

from shorttrip.strict_constraint_compiler import compile_constraint
from shorttrip.strict_cost_constraint_bridge import evaluate_cost_constraint
from shorttrip.strict_trip_cost_aggregation import aggregate_trip_costs
from tests.test_strict_intercity_cost_manifest import fixture as intercity_fixture


def callbacks():
    return {"intercity_policy_verifier": lambda *_: True,
            "intercity_inventory_verifier": lambda *_: True,
            "intercity_segment_verifier": lambda *_: True,
            "intercity_timetable_verifier": lambda *_: True,
            "intercity_fare_verifier": lambda *_: True}


def make_input():
    task, plan, manifest = intercity_fixture()
    for index, day in enumerate(plan["days"]):
        day["timeline"] = [{"type": "visit", "entity_id": "synthetic-place-" + str(index)}]
    for segment in plan["intercity_segments"]:
        day = next(day for day in plan["days"] if day["date"] == segment["travel_date"])
        day["timeline"].append({"type": "travel",
            "entity_id": "intercity-occurrence-" + segment["segment_id"],
            "segment_id": segment["segment_id"], "date": segment["travel_date"],
            "direction": segment["direction"], "origin_city": segment["origin_city"],
            "destination_city": segment["destination_city"],
            "origin_station": segment["origin_station"],
            "destination_station": segment["destination_station"],
            "start": segment["departure_time"] + segment["clock_zone"],
            "end": segment["arrival_time"] + segment["clock_zone"],
            "departure_time": segment["departure_time"], "clock_zone": segment["clock_zone"],
            "arrival_time": segment["arrival_time"],
            "arrival_day_offset": segment["arrival_day_offset"]})
    dates = [day["date"] for day in plan["days"]]
    scope = {"task_uid": task["uid"], "plan_uid": plan["uid"],
             "target_city": task["target_city"], "itinerary_dates": dates}
    component = {"category": "intercity", "amount_decimal": "401.00",
        "currency": "CNY", "party_size": task["people_number"],
        "scope": copy.deepcopy(scope),
        "expense_ids": [fare["expense_id"] for fare in manifest["fares"]],
        "intercity_segment_bindings": [
            {"segment_id": fare["segment_id"],
             "direction": fare["fare_claim"]["direction"],
             "expense_id": fare["expense_id"]} for fare in manifest["fares"]],
        "evidence": {"fixture": "synthetic"}, "conflict": False}
    policy = {"required_categories": ["intercity"], "currency": "CNY",
        "party_size": task["people_number"], "total_limit": 500,
        "trip_scope": copy.deepcopy(scope)}
    return task, plan, manifest, scope, component, policy


class StrictIntercityBudgetIntegrationTests(unittest.TestCase):
    def test_raw_manifest_is_revalidated_and_decimal_total_is_used_once(self):
        task, plan, manifest, scope, component, policy = make_input()
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "arithmetic_evaluated")
        self.assertEqual(out["total_decimal"], "401.00")
        self.assertEqual(out["intercity_manifest_check"]["state"], "pass")

    def test_component_amount_bindings_and_all_intercity_verifiers_are_required(self):
        task, plan, manifest, scope, component, policy = make_input()
        component["amount_decimal"] = "401.01"
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "unknown")
        self.assertIn("intercity_component_amount_not_bound_to_recomputed_total", out["reasons"])

        task, plan, manifest, scope, component, policy = make_input()
        component["intercity_segment_bindings"].pop()
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "unknown")
        self.assertIn("intercity_component_bindings_not_bound_to_verified_segments", out["reasons"])

        task, plan, manifest, scope, component, policy = make_input()
        missing_callback = callbacks()
        missing_callback["intercity_fare_verifier"] = None
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **missing_callback)
        self.assertEqual(out["status"], "unknown")

    def test_cross_category_expense_reuse_and_unmodeled_policy_are_unknown(self):
        task, plan, manifest, scope, component, policy = make_input()
        ticket_id = component["expense_ids"][0]
        plan["days"][0]["timeline"].append({"type": "visit", "entity_id": "place-a"})
        ticket = {"category": "tickets", "amount": 1, "currency": "CNY",
            "party_size": 2, "scope": copy.deepcopy(scope), "expense_ids": [ticket_id],
            "evidence": {"fixture": "synthetic"},
            "occurrence_bindings": [{"expense_id": ticket_id, "day_index": 0,
                "item_index": 0, "date": plan["days"][0]["date"],
                "type": "visit", "entity_id": "place-a"}]}
        policy["required_categories"] = ["intercity", "tickets"]
        out = aggregate_trip_costs(policy, [component, ticket], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "unknown")
        self.assertIn("expense_id_duplicate_across_categories", out["reasons"])

        task, plan, manifest, scope, component, policy = make_input()
        task.pop("intercity_policy")
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "unknown")

    def test_intercity_segments_require_unique_mechanical_timeline_occurrences(self):
        mutations = [
            ("sidecar_only", lambda p: [d.update(timeline=[x for x in d["timeline"]
                 if "segment_id" not in x]) for d in p["days"]],
             "intercity_timeline_occurrence_missing_duplicate_or_incomplete"),
            ("wrong_station", lambda p: next(x for d in p["days"] for x in d["timeline"]
                 if x.get("segment_id") == "leg-out").update(destination_station="wrong"),
             "intercity_timeline_occurrence_scope_mismatch"),
            ("wrong_date", lambda p: next(x for d in p["days"] for x in d["timeline"]
                 if x.get("segment_id") == "leg-out").update(date="2026-11-16"),
             "intercity_timeline_occurrence_scope_mismatch"),
            ("wrong_display_start", lambda p: next(x for d in p["days"] for x in d["timeline"]
                 if x.get("segment_id") == "leg-out").update(start="08:00"),
             "intercity_timeline_occurrence_scope_mismatch"),
            ("wrong_display_end", lambda p: next(x for d in p["days"] for x in d["timeline"]
                 if x.get("segment_id") == "leg-out").update(end="12:00"),
             "intercity_timeline_occurrence_scope_mismatch"),
            ("wrong_display_offset", lambda p: next(x for d in p["days"] for x in d["timeline"]
                 if x.get("segment_id") == "leg-out").update(start="09:00:00+07:00"),
             "intercity_timeline_occurrence_scope_mismatch"),
            ("duplicate", lambda p: next(d for d in p["days"] if d["date"] == "2026-11-15")
                 ["timeline"].append(copy.deepcopy(next(x for d in p["days"] for x in d["timeline"]
                     if x.get("segment_id") == "leg-out"))),
             "intercity_timeline_occurrence_missing_duplicate_or_incomplete"),
            ("missing", lambda p: next(d for d in p["days"] if d["date"] == "2026-11-17")
                 .update(timeline=[x for x in next(d for d in p["days"]
                     if d["date"] == "2026-11-17")["timeline"]
                     if x.get("segment_id") != "leg-back"]),
             "intercity_timeline_occurrence_missing_duplicate_or_incomplete"),
        ]
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                task, plan, manifest, scope, component, policy = make_input()
                mutate(plan)
                out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
                    plan=plan, evidence_verifier=lambda *_: True,
                    inventory_verifier=lambda *_: True, intercity_manifest=manifest,
                    **callbacks())
                self.assertEqual(out["status"], "unknown")
                self.assertIn(expected, out["reasons"])

        task, plan, manifest, scope, component, policy = make_input()
        component.pop("conflict")
        out = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=plan, evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(out["status"], "unknown")
        self.assertIn("intercity_component_conflict_or_shape_invalid", out["reasons"])

    def test_compiled_budget_bridge_accepts_raw_policy_only_with_all_gates(self):
        task, plan, manifest, scope, component, policy = make_input()
        raw_constraint = {"id": "intercity-budget", "strength": "hard",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 500, "people": 2, "includes": ["intercity"]}}}
        constraint = compile_constraint(raw_constraint)["constraint"]
        task["additional_constraints"] = [constraint]
        out = evaluate_cost_constraint(constraint, policy, [component], scope=scope,
            evidence_verifier=lambda *_: True, inventory_verifier=lambda *_: True,
            fact_verifier=lambda *_: True, task_context=scope,
            context_verifier=lambda *_: True, task_input=task, plan_input=plan,
            intercity_manifest=manifest, **callbacks())
        self.assertEqual(out["state"], "pass")
        self.assertEqual(out["aggregate"]["total_decimal"], "401.00")

        task, plan, manifest, scope, component, policy = make_input()
        task.pop("intercity_policy")
        task["additional_constraints"] = [constraint]
        out = evaluate_cost_constraint(constraint, policy, [component], scope=scope,
            evidence_verifier=lambda *_: True, inventory_verifier=lambda *_: True,
            fact_verifier=lambda *_: True, task_context=scope,
            context_verifier=lambda *_: True, task_input=task, plan_input=plan,
            intercity_manifest=manifest, **callbacks())
        self.assertEqual(out["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
