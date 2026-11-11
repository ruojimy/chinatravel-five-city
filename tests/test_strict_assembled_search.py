import copy
import unittest

from src.shorttrip.strict_assembled_search import search_assembled_development_assignments, _context_matches_task


DATES = ["2026-11-01", "2026-11-02", "2026-11-03"]
KINDS = {"home": "poi", "hotel": "accommodation", "attraction": "attraction"}
ALL_DIAGNOSTIC_INPUTS = {
    "overnight_boundaries", "meal_coverage", "lodging", "intercity",
    "finite_route_domain", "constraint_facts", "tag_evidence", "cost_aggregation",
}


def task_fixture(split="development", purpose="development"):
    return {
        "uid": "adapter-three-day", "level": "human", "split": split,
        "purpose": purpose, "task_origin": "synthetic_human_style",
        "start_city": "A", "target_city": "A", "start_date": DATES[0],
        "days": 3, "people_number": 2,
        "required_kinds": ["poi", "attraction", "accommodation"],
        "candidate_selection": {"required_entity_ids": list(KINDS)},
        "generation": {"selected_entities_by_kind": {
            "poi": {"id": "home", "stored_name_unverified": "Home"},
            "accommodation": {"id": "hotel", "stored_name_unverified": "Hotel"},
            "attraction": {"id": "attraction", "stored_name_unverified": "Attraction"},
        }},
        "additional_constraints": [],
    }


def route(oid, origin, dest, start, end):
    return {"occurrence_id": oid, "type": "travel",
            "origin_id": origin, "origin_kind": KINDS[origin],
            "origin_entrance_id": "gate-" + origin,
            "destination_id": dest, "destination_kind": KINDS[dest],
            "destination_entrance_id": "gate-" + dest,
            "start": start, "end": end, "mode": "synthetic_walk"}


def daily_items(broken=False):
    result = []
    for index, day_date in enumerate(DATES):
        start, start_time = ("home", "09:00:00+08:00") if index == 0 else (
            "hotel", "09:00:00+08:00")
        prefix = f"day-{index + 1}"
        timeline = [route(prefix + "-to-visit", start, "attraction",
                          start_time, "09:30:00+08:00"),
                    {"occurrence_id": prefix + "-visit", "type": "visit",
                     "entity_id": "attraction", "entity_kind": "attraction",
                     "entrance_id": "gate-attraction", "start": "09:30:00+08:00",
                     "end": "11:00:00+08:00"},
                    route(prefix + "-to-hotel", "attraction", "hotel",
                          "11:00:00+08:00", "11:30:00+08:00")]
        if broken and index == 0:
            timeline.pop()
        result.append({"date": day_date, "city": "A",
            "start_location": {"entity_id": start, "kind": KINDS[start],
                               "entrance_id": "gate-" + start},
            "timeline": timeline})
    return result


def bindings_for(task, plan):
    selected = task["generation"]["selected_entities_by_kind"]
    by_id = {}

    def add(entity_id, kind, day_index, item_index, role):
        row = by_id.setdefault(entity_id, {"entity_id": entity_id, "kind": kind,
            "record": {"id": entity_id, "kind": kind, "city": "A",
                       "name": selected[kind]["stored_name_unverified"],
                       "payload": {"data": {}}, "claims": []}, "occurrences": []})
        row["occurrences"].append({"day_index": day_index, "item_index": item_index,
            "role": role, "requirements": [{"native_field": "lat",
                "policy_field": "coordinates", "scope": {
                    "travel_date": plan["days"][day_index]["date"],
                    "occurrence_role": role}}]})

    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] == "travel":
                add(item["origin_id"], KINDS[item["origin_id"]], day_index, item_index, "travel_origin")
                add(item["destination_id"], KINDS[item["destination_id"]], day_index, item_index,
                    "travel_destination")
            else:
                add(item["entity_id"], KINDS[item["entity_id"]], day_index, item_index, "activity")
    return list(by_id.values())


def context_for(task):
    return {"uid": task["uid"], "level": task["level"],
        "start_city": task["start_city"], "target_city": task["target_city"],
        "start_date": task["start_date"], "days": task["days"],
        "people_number": task["people_number"], "start_location_id": "home"}


class StrictAssembledSearchTests(unittest.TestCase):
    def test_boolean_party_does_not_equal_integer_plan_context(self):
        task = task_fixture()
        task['people_number'] = True
        ctx = context_for(task)
        ctx['people_number'] = 1
        self.assertFalse(_context_matches_task(task, ctx))

    def resolver(self, *, mutate=None, diagnostics=None, callback=None):
        def resolve(task, assignment):
            if mutate == "assignment":
                assignment["case"] = "changed"
            elif mutate == "task":
                task["uid"] = "tampered-task"
            source = task_fixture()
            explicit = daily_items(broken=assignment.get("case") == "missing-transition")
            assembled = __import__("src.shorttrip.strict_plan_assembler", fromlist=[
                "assemble_strict_plan"]).assemble_strict_plan(
                    context_for(source), copy.deepcopy(explicit), entity_kinds=KINDS,
                    repeat_policy={"allow_repeated_occurrence_entities": True})
            plan = assembled.get("plan")
            bindings = bindings_for(source, plan) if isinstance(plan, dict) else []
            data = {
                "plan_context": context_for(task), "daily_items": explicit,
                "entity_kinds": KINDS,
                "repeat_policy": {"allow_repeated_occurrence_entities": True},
                "record_bindings": bindings, "now": "2026-10-31T00:00:00Z",
                "registry": {}, "diagnostic_inputs": diagnostics or {},
                "diagnostic_callbacks": {},
            }
            if callback is not None:
                data["diagnostic_callbacks"] = {"meal_policy_verifier": callback}
            return data
        return resolve

    def test_missing_transition_and_no_evidence_both_remain_unknown(self):
        task = task_fixture()
        result = search_assembled_development_assignments(task, {"case": [
            "missing-transition", "complete-structure-no-evidence"]},
            resolver=self.resolver())
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"], {"pass": 0, "fail": 0, "unknown": 2})
        self.assertEqual(result["unknown_assignment_count"], 2)
        self.assertFalse(result["global_unsat_claimed"])
        self.assertFalse(result["planner_complete"])
        self.assertFalse(result["domain_complete"])
        self.assertEqual(len(result["assignments"]), 2)
        self.assertTrue(all(item["state"] == "unknown" for item in result["assignments"]))
        failed_assembly = result["diagnostics"][0]["diagnostic"]
        self.assertNotIn("plan_missing_or_not_object",
                         [gap["reason"] for gap in failed_assembly["axes"]["pipeline"]])
        self.assertEqual(failed_assembly["outcome"], "adapter_block")
        self.assertEqual(failed_assembly["candidate_assembly_rejection"]["reason"],
                         "overnight_transition_not_explicit_or_endpoint_mismatch")
        self.assertEqual(result["diagnostics"][0]["reason"],
                         "candidate_assembly_rejected")
        self.assertEqual(result["assignments"][0]["reason"],
                         "candidate_assembly_rejected")
        self.assertTrue(result["diagnostics"][1]["diagnostic"].get("truth_certified") is False)

    def test_holdout_and_assignment_limit_are_rejected_as_unknown(self):
        holdout = search_assembled_development_assignments(
            task_fixture("holdout", "holdout"), {"case": ["a"]}, resolver=self.resolver())
        self.assertEqual(holdout["outcome_state"], "unknown")
        self.assertEqual(holdout["enumerated_assignment_count"], 0)

        over_limit = search_assembled_development_assignments(
            task_fixture(), {"case": ["a", "b"]}, resolver=self.resolver(), max_assignments=1)
        self.assertEqual(over_limit["outcome_state"], "unknown")
        self.assertEqual(over_limit["enumerated_assignment_count"], 0)

    def test_resolver_mutating_task_or_assignment_cannot_become_decision(self):
        for target in ("task", "assignment"):
            with self.subTest(target=target):
                result = search_assembled_development_assignments(task_fixture(), {"case": ["a"]},
                    resolver=self.resolver(mutate=target))
                self.assertEqual(result["decision_counts"],
                                 {"pass": 0, "fail": 0, "unknown": 1})
                self.assertEqual(result["assignments"][0]["reason"],
                                 "plan_resolver_mutated_input")

    def test_all_allowlisted_diagnostic_inputs_are_forwarded(self):
        supplied = {key: None for key in ALL_DIAGNOSTIC_INPUTS}
        result = search_assembled_development_assignments(task_fixture(), {"case": ["a"]},
            resolver=self.resolver(diagnostics=supplied))
        self.assertIn("diagnostic", result["diagnostics"][0])
        self.assertEqual(result["diagnostics"][0]["diagnostic"]["overnight_checks"]["state"],
                         "unknown")
        self.assertNotEqual(result["diagnostics"][0]["reason"],
                            "diagnostic_inputs_malformed")
        self.assertEqual(result["decision_counts"]["unknown"], 1)

    def test_mutating_policy_callback_cannot_upgrade_unknown(self):
        def mutate(task, slots):
            task["tampered"] = True
            return True
        meal_input = {"meal_coverage": {"required_slots": [
            {"date": DATES[0], "slot": "lunch"}], "events": []}}
        result = search_assembled_development_assignments(task_fixture(), {"case": ["a"]},
            resolver=self.resolver(diagnostics=meal_input, callback=mutate))
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        self.assertFalse(result["truth_certified"])


if __name__ == "__main__":
    unittest.main()
