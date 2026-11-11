"""Synthetic control tests for candidate -> finite search -> dev diagnostics.

All records and plans here are reconstructed controls. They are not travel
facts and this test cannot certify a real itinerary.
"""
import copy
import unittest

from shorttrip.strict_multiday_candidates import generate_multiday_candidate_proposals
from shorttrip.strict_search_orchestrator import search_development_assignments


DATES = ["2026-11-15", "2026-11-16", "2026-11-17"]
START_ID = "synthetic-start"


def occ(entity_id, kind, day):
    return {"entity_id": entity_id, "kind": kind, "date": day,
            "start": f"{day}T10:00:00+08:00", "end": f"{day}T11:00:00+08:00"}


def input_slots():
    return [{"date": day, "slots": [{"slot_id": f"visit-{index}", "candidates": [
        occ(f"synthetic-att-{index}", "attraction", day)]}]}
        for index, day in enumerate(DATES)]


def task_fixture():
    selected = {"poi": {"id": START_ID, "stored_name_unverified": "synthetic start"}}
    required = [START_ID]
    for index in range(3):
        entity_id = f"synthetic-att-{index}"
        selected[f"attraction_{index}"] = {
            "id": entity_id, "stored_name_unverified": f"synthetic attraction {index}"}
        required.append(entity_id)
    return {"uid": "synthetic-multiday-control", "level": "easy",
            "split": "development", "purpose": "development",
            "start_city": "Synthetic City", "target_city": "Synthetic City",
            "start_date": DATES[0], "days": 3, "people_number": 1,
            "candidate_selection": {"required_entity_ids": required},
            "generation": {"selected_entities_by_kind": selected},
            "additional_constraints": []}


def bindings_for(plan, task):
    selected = task["generation"]["selected_entities_by_kind"]
    by_id = {item["id"]: (kind, item["stored_name_unverified"])
             for kind, item in selected.items()}
    occurrences = {entity_id: [] for entity_id in by_id}
    for day_index, day in enumerate(plan["days"]):
        date = day["date"]
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] != "travel":
                continue
            for entity_id, role in ((item["origin_id"], "travel_origin"),
                                    (item["destination_id"], "travel_destination")):
                requirements = [{"native_field": "lat", "policy_field": "coordinates",
                                 "scope": {"travel_date": date}}]
                occurrences[entity_id].append({"day_index": day_index,
                    "item_index": item_index, "role": role,
                    "requirements": requirements})
        visit_index = next(i for i, item in enumerate(day["timeline"])
                           if item["type"] == "visit")
        entity_id = day["timeline"][visit_index]["entity_id"]
        occurrences[entity_id].append({"day_index": day_index, "item_index": visit_index,
            "role": "activity", "requirements": [{
                "native_field": "opentime", "policy_field": "opening_hours",
                "scope": {"travel_date": date}}]})

    result = []
    for entity_id, scoped_occurrences in occurrences.items():
        kind, name = by_id[entity_id]
        result.append({"entity_id": entity_id, "kind": kind,
            "record": {"id": entity_id, "kind": kind, "city": "Synthetic City",
                       "name": name, "payload": {"data": {}}, "claims": []},
            "occurrences": scoped_occurrences})
    return result


def plan_for(proposal, task):
    selected = task["generation"]["selected_entities_by_kind"]
    names = {item["id"]: item["stored_name_unverified"] for item in selected.values()}
    days = []
    for occurrence in proposal["occurrences"]:
        entity_id, day = occurrence["entity_id"], occurrence["date"]
        days.append({"date": day, "city": task["target_city"], "timeline": [
            {"type": "travel", "origin_id": START_ID, "destination_id": entity_id,
             "from": names[START_ID], "to": names[entity_id],
             "start": "09:00", "end": "09:30"},
            {"type": "visit", "entity_id": entity_id, "entity": names[entity_id],
             "start": "10:00", "end": "11:00"}]})
    return {"uid": task["uid"], "level": task["level"], "days": days}


class StrictMultidayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.task = task_fixture()
        self.generated = generate_multiday_candidate_proposals(
            input_slots(), expected_dates=DATES)
        self.assertEqual(self.generated["status"], "candidate_proposal_unverified")
        self.proposal = self.generated["proposals"][0]

    def run_search(self, *, include_bindings, evidence_present=False):
        plan = plan_for(self.proposal, self.task)
        context = {"start_city": self.task["start_city"],
                   "target_city": self.task["target_city"],
                   "start_date": self.task["start_date"], "days": 3,
                   "people_number": self.task["people_number"],
                   "start_location_id": START_ID}
        bindings = bindings_for(plan, self.task) if include_bindings else []
        if evidence_present:
            # Even this control data is synthetic; it is not independent evidence.
            for binding in bindings:
                binding["record"]["payload"]["data"] = {
                    "lat": 0.0, "lng": 0.0, "opentime": "00:00-23:59"}
                binding["record"]["claims"] = ["synthetic-only"]

        def resolver(_task, assignment):
            selected_proposal = assignment["proposal"]
            return {"plan": plan_for(selected_proposal, self.task),
                    "plan_context": context,
                    "record_bindings": copy.deepcopy(bindings),
                    "now": "2026-10-31T00:00:00Z", "registry": {}}

        return search_development_assignments(
            self.task, {"proposal": [self.proposal]}, resolver=resolver,
            decision_verifier=lambda *_: True)

    def test_generator_emits_only_explicit_occurrences(self):
        explicit = {item["entity_id"] for day in input_slots()
                    for slot in day["slots"] for item in slot["candidates"]}
        generated = {item["entity_id"] for proposal in self.generated["proposals"]
                     for item in proposal["occurrences"]}
        self.assertEqual(generated, explicit)
        self.assertEqual(len(self.proposal["occurrences"]), 3)
        self.assertFalse(self.generated["task_coverage_verified"])
        self.assertFalse(self.generated["facts_verified"])
        self.assertIsNone(self.generated["feasibility"])

    def test_missing_occurrence_bindings_remain_unknown(self):
        result = self.run_search(include_bindings=False)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        reasons = {gap.get("reason") for gap in
                   result["diagnostics"][0]["diagnostic"].get("blocking_gaps", [])}
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["real_world_feasibility_certified"])

    def test_fixed_planner_gap_and_synthetic_empty_evidence_never_pass(self):
        result = self.run_search(include_bindings=True, evidence_present=False)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        diagnostic = result["diagnostics"][0]["diagnostic"]
        all_gaps = [gap for axis in diagnostic.get("axes", {}).values()
                    for gap in axis if isinstance(gap, dict)]
        self.assertTrue(any(gap.get("reason") == "planner_feature_unsupported"
                            for gap in all_gaps), all_gaps)
        self.assertFalse(result["complete_planner_integrated"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_synthetic_filled_fields_and_planner_estimates_cannot_create_pass(self):
        result = self.run_search(include_bindings=True, evidence_present=True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        diagnostic = result["diagnostics"][0]["diagnostic"]
        self.assertTrue(any(gap.get("reason") == "planner_feature_unsupported"
                            for axis in diagnostic.get("axes", {}).values()
                            for gap in axis if isinstance(gap, dict)))
        self.assertIsNone(result["formal_score"])
        self.assertFalse(result["frozen"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
