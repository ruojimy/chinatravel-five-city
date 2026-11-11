"""Synthetic end-to-end integration for the strict three-day proposal path."""
from __future__ import annotations

import copy
import unittest

from shorttrip.strict_plan_assembler import assemble_strict_plan
from shorttrip.strict_search_orchestrator import search_development_assignments


DATES = ["2026-11-15", "2026-11-16", "2026-11-17"]
NAMES = {"home": "Synthetic start", "hotel": "Synthetic lodging",
         "attraction": "Synthetic attraction", "restaurant": "Synthetic restaurant"}
KINDS = {"home": "poi", "hotel": "accommodation",
         "attraction": "attraction", "restaurant": "restaurant"}
REQUIRED_MEALS = [{"date": day, "slot": "lunch"} for day in DATES]


def task_fixture():
    return {
        "uid": "synthetic-3day-search", "level": "human",
        "task_origin": "synthetic_human_style", "purpose": "development",
        "split": "development", "nature_language": "Synthetic integration fixture",
        "start_city": "A", "target_city": "A", "days": 3,
        "people_number": 2, "start_date": DATES[0],
        "required_kinds": ["poi", "accommodation", "attraction", "restaurant"],
        "mode": "collection_static_reference", "evidence_policy_id": "synthetic-no-evidence",
        "additional_constraints": [{
            "id": "explicit-lunch-slots", "strength": "hard",
            "scope": {"domain": "trip"},
            "expression": {"op": "meal_slot_inventory",
                           "args": {"required_slots": copy.deepcopy(REQUIRED_MEALS)}},
            "compiler_status": "unmapped",
        }],
        "generation": {"seed": 7, "budget_sampling": "not_sampled",
                       "feasibility_claim": "not_checked",
                       "selected_entities_by_kind": {
                           "poi": {"id": "home", "stored_name_unverified": NAMES["home"]},
                           "accommodation": {"id": "hotel", "stored_name_unverified": NAMES["hotel"]},
                           "attraction": {"id": "attraction", "stored_name_unverified": NAMES["attraction"]},
                           "restaurant": {"id": "restaurant", "stored_name_unverified": NAMES["restaurant"]},
                       }},
        "candidate_selection": {"policy": "one explicit synthetic ID per kind",
                                "required_entity_ids": list(KINDS)},
    }


def route(occurrence_id, origin, origin_kind, origin_entrance,
          destination, destination_kind, destination_entrance, start, end):
    return {"occurrence_id": occurrence_id, "type": "travel",
            "origin_id": origin, "origin_kind": origin_kind,
            "origin_entrance_id": origin_entrance,
            "destination_id": destination, "destination_kind": destination_kind,
            "destination_entrance_id": destination_entrance,
            "start": start, "end": end, "mode": "synthetic_walk"}


def daily_fixture():
    days = []
    for index, day in enumerate(DATES):
        start_id, start_kind, start_entrance = (
            ("home", "poi", "start-gate") if index == 0 else
            ("hotel", "accommodation", "lobby"))
        base = f"d{index + 1}"
        days.append({"date": day, "city": "A",
            "start_location": {"entity_id": start_id, "kind": start_kind,
                                "entrance_id": start_entrance},
            "timeline": [
                route(base + "-to-visit", start_id, start_kind, start_entrance,
                      "attraction", "attraction", "main-gate",
                      "09:00:00+08:00", "09:20:00+08:00"),
                {"occurrence_id": base + "-visit", "type": "visit",
                 "entity_id": "attraction", "entity_kind": "attraction",
                 "entrance_id": "main-gate", "start": "09:20:00+08:00",
                 "end": "11:00:00+08:00", "entity": NAMES["attraction"]},
                route(base + "-to-lunch", "attraction", "attraction", "main-gate",
                      "restaurant", "restaurant", "front-door",
                      "11:00:00+08:00", "11:20:00+08:00"),
                {"occurrence_id": base + "-lunch", "type": "lunch",
                 "entity_id": "restaurant", "entity_kind": "restaurant",
                 "entrance_id": "front-door", "start": "11:20:00+08:00",
                 "end": "12:00:00+08:00", "entity": NAMES["restaurant"]},
                route(base + "-to-hotel", "restaurant", "restaurant", "front-door",
                      "hotel", "accommodation", "lobby",
                      "12:00:00+08:00", "12:20:00+08:00"),
            ]})
    return days


def assemble_fixture():
    task = task_fixture()
    context = {"uid": task["uid"], "level": task["level"],
        "start_city": task["start_city"], "target_city": task["target_city"],
        "start_date": task["start_date"], "days": task["days"],
        "people_number": task["people_number"], "start_location_id": "home"}
    assembled = assemble_strict_plan(context, daily_fixture(), entity_kinds=KINDS,
        repeat_policy={"allow_repeated_occurrence_entities": True})
    if assembled["status"] != "synthetic_plan_assembled_unverified":
        raise AssertionError(assembled)
    return task, assembled["plan"]


def bindings_for(task, plan):
    selected = task["generation"]["selected_entities_by_kind"]
    by_id = {}

    def add(entity_id, day_index, item_index, role):
        kind = KINDS[entity_id]
        target = by_id.setdefault(entity_id, {"entity_id": entity_id, "kind": kind,
            "record": {"id": entity_id, "kind": kind, "city": task["target_city"],
                       "name": selected[kind]["stored_name_unverified"],
                       "payload": {"data": {}}, "claims": []},
            "occurrences": []})
        day_date = plan["days"][day_index]["date"]
        native = ("opentime" if kind == "attraction" else
                  "business_hours" if kind == "restaurant" else "lat")
        field = ("opening_hours" if kind == "attraction" else
                 "business_hours" if kind == "restaurant" else "coordinates")
        target["occurrences"].append({"day_index": day_index, "item_index": item_index,
            "role": role, "requirements": [{"native_field": native,
                "policy_field": field,
                "scope": {"travel_date": day_date, "occurrence_role": role}}]})

    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] in {"visit", "attraction", "breakfast", "lunch", "dinner", "meal"}:
                add(item["entity_id"], day_index, item_index, "activity")
            elif item["type"] == "travel":
                add(item["origin_id"], day_index, item_index, "travel_origin")
                add(item["destination_id"], day_index, item_index, "travel_destination")
    return [by_id[key] for key in sorted(by_id)]


def diagnostic_inputs(plan):
    lodging_requirement = {"entity_id": "hotel", "room_type": "synthetic-twin",
        "check_in": DATES[0], "check_out": "2026-11-17", "rooms": 1,
        "guests_per_room": 2, "minimum_beds": 2, "eligibility": "synthetic",
        "meal_plan": "none", "taxes_included": True,
        "mandatory_fees_included": True}
    lodging_claim = {"entity_id": "hotel", "room_type": "synthetic-twin",
        "check_in": DATES[0], "check_out": "2026-11-17", "guests_per_room": 2,
        "currency": "CNY", "unit": "CNY/room/night", "rate": 0,
        "beds": 2, "max_guests_per_room": 2, "eligibility": "synthetic",
        "meal_plan": "none", "taxes_included": True,
        "mandatory_fees_included": True}
    overnight_boundaries = []
    for index in range(2):
        previous_day, next_day = DATES[index], DATES[index + 1]
        overnight_boundaries.append({"previous_day": previous_day, "next_day": next_day,
            "last_endpoint": {"entity_id": "hotel", "entrance_id": "lobby",
                "datetime": previous_day + "T12:20:00+08:00"},
            "first_endpoint": {"entity_id": "hotel", "entrance_id": "lobby",
                "datetime": next_day + "T09:00:00+08:00"},
            "lodging_entrance_id": "lobby",
            "lodging_requirement": copy.deepcopy(lodging_requirement),
            "lodging_claim": copy.deepcopy(lodging_claim)})
    meal_events = []
    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] in {"breakfast", "lunch", "dinner", "meal"}:
                meal_events.append({"date": day["date"], "item_index": item_index,
                    "type": item["type"], "entity_id": item["entity_id"],
                    "event_id": f"meal-event-{day_index + 1}",
                    "slot": item.get("meal_slot", item["type"])})
    return {"overnight_boundaries": overnight_boundaries,
            "meal_coverage": {"required_slots": copy.deepcopy(REQUIRED_MEALS),
                              "events": meal_events}}


def meal_policy_verifier(task, required_slots):
    constraints = task.get("additional_constraints", [])
    if len(constraints) != 1:
        return False
    args = constraints[0].get("expression", {}).get("args", {})
    return args.get("required_slots") == required_slots


class StrictAssemblerSearchIntegrationTests(unittest.TestCase):
    def test_valid_synthetic_three_day_plan_reaches_search_but_stays_incomplete(self):
        task, plan = assemble_fixture()
        bindings = bindings_for(task, plan)
        self.assertEqual(len(plan["days"]), 3)
        self.assertEqual(sum(len(day["timeline"]) for day in plan["days"]), 15)
        self.assertEqual(sum(len(binding["occurrences"]) for binding in bindings), 24)
        self.assertEqual(len(task["candidate_selection"]["required_entity_ids"]), 4)
        self.assertEqual(len(task["generation"]["selected_entities_by_kind"]), 4)
        self.assertEqual(len(diagnostic_inputs(plan)["meal_coverage"]["events"]), 3)

        def resolver(task_copy, assignment):
            assigned_plan = copy.deepcopy(plan)
            return {"plan": assigned_plan,
                "plan_context": {"start_city": task_copy["start_city"],
                    "target_city": task_copy["target_city"], "start_date": task_copy["start_date"],
                    "days": task_copy["days"], "people_number": task_copy["people_number"],
                    "start_location_id": "home"},
                "record_bindings": copy.deepcopy(bindings),
                "now": "2026-10-31T00:00:00Z", "registry": {},
                "diagnostic_inputs": diagnostic_inputs(assigned_plan),
                "diagnostic_callbacks": {"meal_policy_verifier": meal_policy_verifier}}

        result = search_development_assignments(task,
            {"synthetic_case": ["a", "b"]}, resolver=resolver)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["enumerated_assignment_count"], 2)
        self.assertEqual(result["decision_counts"], {"pass": 0, "fail": 0, "unknown": 2})
        self.assertEqual(result["unknown_assignment_count"], 2)
        self.assertFalse(result["global_unsat_claimed"])
        for diagnostic in result["diagnostics"]:
            diag = diagnostic["diagnostic"]
            self.assertEqual(diag["bound_occurrence_count"], 24)
            self.assertEqual(diag["meal_coverage_check"]["state"], "unknown")
            self.assertEqual(diag["overnight_checks"]["state"], "unknown")
            self.assertFalse(diag["truth_certified"])
            self.assertFalse(diag["execution_confirmed"])

    def test_missing_route_and_wrong_entity_domain_are_not_repaired(self):
        task = task_fixture()
        context = {"uid": task["uid"], "level": task["level"],
            "start_city": task["start_city"], "target_city": task["target_city"],
            "start_date": task["start_date"], "days": task["days"],
            "people_number": task["people_number"], "start_location_id": "home"}
        daily = daily_fixture()
        del daily[0]["timeline"][2]
        blocked = assemble_strict_plan(context, daily, entity_kinds=KINDS,
            repeat_policy={"allow_repeated_occurrence_entities": True})
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "transition_missing_or_endpoint_mismatch")
        self.assertIsNone(blocked["plan"])

        task, plan = assemble_fixture()
        bindings = bindings_for(task, plan)
        bad_plan = copy.deepcopy(plan)
        bad_plan["days"][0]["timeline"][1]["entity_id"] = "undeclared-attraction"

        def wrong_domain_resolver(task_copy, _assignment):
            return {"plan": bad_plan,
                "plan_context": {"start_city": task_copy["start_city"],
                    "target_city": task_copy["target_city"], "start_date": task_copy["start_date"],
                    "days": task_copy["days"], "people_number": task_copy["people_number"],
                    "start_location_id": "home"},
                "record_bindings": bindings, "now": "2026-10-31T00:00:00Z",
                "registry": {}}

        result = search_development_assignments(task, {"case": ["wrong-domain"]},
                                                resolver=wrong_domain_resolver)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        diag = result["diagnostics"][0]["diagnostic"]
        self.assertIn("plan_uses_undeclared_entity_id",
                      [gap["reason"] for gap in diag["axes"]["pipeline"]])
        self.assertFalse(result["global_unsat_claimed"])

    def test_assembler_rejects_wrong_date_before_search(self):
        task = task_fixture()
        context = {"uid": task["uid"], "level": task["level"],
            "start_city": task["start_city"], "target_city": task["target_city"],
            "start_date": task["start_date"], "days": task["days"],
            "people_number": task["people_number"], "start_location_id": "home"}
        daily = daily_fixture()
        daily[1]["date"] = "2026-11-19"
        result = assemble_strict_plan(context, daily, entity_kinds=KINDS,
            repeat_policy={"allow_repeated_occurrence_entities": True})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "day_date_mismatch")


if __name__ == "__main__":
    unittest.main()
