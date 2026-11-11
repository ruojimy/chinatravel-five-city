import copy
import unittest

from src.shorttrip.strict_event_domain import search_explicit_event_domain


DATES = ["2026-11-01", "2026-11-02", "2026-11-03"]
KINDS = {"home": "poi", "hotel": "accommodation", "attraction": "attraction"}


def task_fixture(split="development", purpose="development"):
    return {"uid": "explicit-event-domain", "level": "human", "split": split,
        "purpose": purpose, "start_city": "A", "target_city": "A",
        "start_date": DATES[0], "days": 3, "people_number": 2,
        "candidate_selection": {"required_entity_ids": list(KINDS)},
        "generation": {"selected_entities_by_kind": {
            "poi": {"id": "home", "stored_name_unverified": "Home"},
            "accommodation": {"id": "hotel", "stored_name_unverified": "Hotel"},
            "attraction": {"id": "attraction", "stored_name_unverified": "Attraction"}}},
        "additional_constraints": []}


def context(task):
    return {"uid": task["uid"], "level": task["level"],
        "start_city": task["start_city"], "target_city": task["target_city"],
        "start_date": task["start_date"], "days": task["days"],
        "people_number": task["people_number"], "start_location_id": "home"}


def anchors():
    return [{"date": day, "city": "A", "start_location": {
        "entity_id": "home" if index == 0 else "hotel",
        "kind": KINDS["home" if index == 0 else "hotel"],
        "entrance_id": "gate-home" if index == 0 else "gate-hotel"}}
        for index, day in enumerate(DATES)]


def route(occurrence_id, origin, destination, start, end):
    return {"occurrence_id": occurrence_id, "type": "travel",
        "origin_id": origin, "origin_kind": KINDS[origin],
        "origin_entrance_id": "gate-" + origin,
        "destination_id": destination, "destination_kind": KINDS[destination],
        "destination_entrance_id": "gate-" + destination,
        "start": start, "end": end, "mode": "synthetic_walk"}


def events_for(day_index, omit_return=False):
    start = "home" if day_index == 0 else "hotel"
    prefix = f"d{day_index + 1}"
    events = [route(prefix + "-out", start, "attraction", "09:00:00+08:00",
                    "09:30:00+08:00"),
        {"occurrence_id": prefix + "-visit", "type": "visit",
         "entity_id": "attraction", "entity_kind": "attraction",
         "entrance_id": "gate-attraction", "start": "09:30:00+08:00",
         "end": "11:00:00+08:00"}]
    if not omit_return:
        events.append(route(prefix + "-back", "attraction", "hotel",
                            "11:00:00+08:00", "11:30:00+08:00"))
    return events


def slots_fixture():
    result = []
    for index, day in enumerate(DATES):
        options = [{"candidate_id": f"day-{index + 1}-complete",
                    "events": events_for(index)}]
        if index == 0:
            options.insert(0, {"candidate_id": "day-1-missing-return",
                               "events": events_for(index, omit_return=True)})
        result.append({"slot_id": f"day-slot-{index + 1}", "date": day,
                       "candidates": options})
    return result


def bindings_for(task, assignment, plan):
    selected = task["generation"]["selected_entities_by_kind"]
    kind_by_id = {entity["id"]: kind for kind, entity in selected.items()}
    by_id = {}

    def add(entity_id, day_index, item_index, role):
        kind = kind_by_id[entity_id]
        item = by_id.setdefault(entity_id, {"entity_id": entity_id, "kind": kind,
            "record": {"id": entity_id, "kind": kind, "city": "A",
                "name": selected[kind]["stored_name_unverified"],
                "payload": {"data": {}}, "claims": []}, "occurrences": []})
        item["occurrences"].append({"day_index": day_index, "item_index": item_index,
            "role": role, "requirements": [{"native_field": "lat",
                "policy_field": "coordinates", "scope": {
                    "travel_date": plan["days"][day_index]["date"],
                    "occurrence_role": role}}]})

    for day_index, day in enumerate(plan["days"]):
        for item_index, event in enumerate(day["timeline"]):
            if event["type"] == "travel":
                add(event["origin_id"], day_index, item_index, "travel_origin")
                if "entity_id" in event:
                    add(event["entity_id"], day_index, item_index, "travel_entity")
                add(event["destination_id"], day_index, item_index, "travel_destination")
            else:
                add(event["entity_id"], day_index, item_index, "activity")
    return list(by_id.values())


def binding_resolver(task, assignment, plan):
    return bindings_for(task, assignment, plan)


def call_domain(*, task=None, slots=None, bindings_factory=binding_resolver,
                diagnostic_inputs=None, max_assignments=10_000,
                entity_kinds=None):
    task = task or task_fixture()
    return search_explicit_event_domain(task, context(task), anchors(),
        slots_fixture() if slots is None else slots,
        entity_kinds=KINDS if entity_kinds is None else entity_kinds,
        repeat_policy={"allow_repeated_occurrence_entities": True},
        record_bindings_resolver=bindings_factory,
        now="2026-10-31T00:00:00Z", registry={},
        diagnostic_inputs=diagnostic_inputs or {}, diagnostic_callbacks={},
        max_assignments=max_assignments)


class StrictEventDomainTests(unittest.TestCase):
    def test_travel_entity_binding_reaches_development_search_without_pipeline_error(self):
        task = task_fixture()
        task["candidate_selection"]["required_entity_ids"].append("rail-service")
        task["generation"]["selected_entities_by_kind"]["train"] = {
            "id": "rail-service", "stored_name_unverified": "Synthetic Rail Service"}
        slots = slots_fixture()
        travel = slots[0]["candidates"][1]["events"][0]
        travel["entity_id"] = "rail-service"
        travel["intercity_segment"] = {
            "segment_id": "train-day-1-outbound", "direction": "outbound",
            "origin_city": "A", "destination_city": "B",
            "origin_station": "A Central", "destination_station": "B Central",
            "travel_date": DATES[0], "departure_time": "09:00",
            "clock_zone": "+08:00", "seat_class": "second",
            "passenger_count": 2, "arrival_time": "09:30",
            "arrival_day_offset": 0, "Duration": "30",
            "Duration_unit": "minutes", "expense_id": "expense-train-day-1"}

        result = call_domain(task=task, slots=slots,
            entity_kinds={**KINDS, "rail-service": "train"})

        self.assertEqual(result["outcome_state"], "unknown")
        self.assertEqual(result["enumerated_assignment_count"], 2)
        self.assertTrue(all(not row.get("diagnostic", {}).get("axes", {}).get("pipeline", [])
                            for row in result["diagnostics"]))
        pipeline_reasons = [gap["reason"]
            for row in result["diagnostics"]
            for gap in row.get("diagnostic", {}).get("axes", {}).get("pipeline", [])]
        self.assertNotIn("plan_missing_or_not_object", pipeline_reasons)
        self.assertNotIn("plan_binding_coverage_mismatch", pipeline_reasons)
        self.assertNotIn("plan_occurrence_binding_coverage_mismatch", pipeline_reasons)
        self.assertNotIn("record_binding_uses_undeclared_entity_id", pipeline_reasons)
        train_lat_gaps = [gap for row in result["diagnostics"]
            for gap in row.get("diagnostic", {}).get("axes", {}).get("data", [])
            if gap.get("entity_id") == "rail-service" and gap.get("field") == "lat"]
        self.assertTrue(any(gap.get("context", {}).get("occurrence_role") == "travel_entity"
                            for gap in train_lat_gaps))
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 2)

    def test_boolean_party_does_not_alias_integer_in_task_context(self):
        task = task_fixture()
        task['people_number'] = True
        plan_context = context(task)
        plan_context['people_number'] = 1
        result = search_explicit_event_domain(task, plan_context, anchors(), slots_fixture(),
            entity_kinds=KINDS, repeat_policy={'allow_repeated_occurrence_entities': True},
            record_bindings_resolver=binding_resolver, now='2026-10-31T00:00:00Z')
        self.assertEqual(result['reason'], 'event_domain_context_task_mismatch')
        self.assertEqual(result['outcome_state'], 'unknown')

    def test_trip_horizon_overflow_stays_unknown(self):
        task = task_fixture()
        task['start_date'] = '9999-12-31'
        result = call_domain(task=task)
        self.assertEqual(result['reason'], 'event_domain_trip_dates_out_of_range')
        self.assertEqual(result['outcome_state'], 'unknown')
        self.assertEqual(result['enumerated_assignment_count'], 0)

    def test_missing_transition_and_no_evidence_candidates_remain_unknown(self):
        result = call_domain()
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["declared_assignment_combinations"], 2)
        self.assertEqual(result["enumerated_assignment_count"], 2)
        self.assertEqual(result["decision_counts"], {"pass": 0, "fail": 0, "unknown": 2})
        self.assertFalse(result["event_domain_complete"])
        self.assertFalse(result["task_domain_complete"])
        self.assertFalse(result["planner_complete"])
        reasons = [row.get("reason") for row in result["diagnostics"]]
        self.assertEqual(len(reasons), 2)
        self.assertEqual(result["global_unsat_claimed"], False)
        broken_diagnostic = result["diagnostics"][0].get("diagnostic", {})
        self.assertNotIn("plan_missing_or_not_object",
                         [gap["reason"] for gap in broken_diagnostic.get("axes", {}).get("pipeline", [])])
        self.assertIn("candidate_assembly_rejected",
                      [gap["reason"] for gap in broken_diagnostic.get("axes", {}).get("solver", [])])
        self.assertEqual(broken_diagnostic['outcome'], 'adapter_block')

    def test_candidate_count_limit_and_assignment_product_limit_fail_closed(self):
        slots = slots_fixture()
        slots[0]["candidates"] = [{"candidate_id": f"option-{index}",
            "events": events_for(0)} for index in range(513)]
        over_total = call_domain(slots=slots)
        self.assertEqual(over_total["outcome_state"], "unknown")
        self.assertEqual(over_total["reason"], "event_candidate_limit_exceeded")
        self.assertEqual(over_total["decision_counts"], {"pass": 0, "fail": 0, "unknown": 0})
        self.assertEqual(over_total["outcome_state"], "unknown")
        self.assertEqual(over_total["enumerated_assignment_count"], 0)

        slots = slots_fixture()
        slots[0]["candidates"] = [{"candidate_id": f"product-{index}",
            "events": events_for(0)} for index in range(101)]
        slots[1]["candidates"] = [{"candidate_id": f"product-b-{index}",
            "events": events_for(1)} for index in range(100)]
        over_product = call_domain(slots=slots)
        self.assertEqual(over_product["outcome_state"], "unknown")
        self.assertEqual(over_product["reason"], "event_domain_product_limit_exceeded")

    def test_slot_id_date_collision_and_duplicate_candidate_ids_rejected(self):
        slots = slots_fixture()
        slots[1]["slot_id"] = slots[0]["slot_id"]
        duplicate_slot = call_domain(slots=slots)
        self.assertEqual(duplicate_slot["outcome_state"], "unknown")
        self.assertEqual(duplicate_slot["reason"], "event_slot_id_missing_or_duplicate")

        slots = slots_fixture()
        slots[0]["candidates"][1]["candidate_id"] = slots[0]["candidates"][0]["candidate_id"]
        duplicate_candidate = call_domain(slots=slots)
        self.assertEqual(duplicate_candidate["outcome_state"], "unknown")
        self.assertEqual(duplicate_candidate["reason"], "event_candidate_id_missing_or_duplicate")

        slots = slots_fixture()
        slots[0]["date"] = "2099-01-01"
        wrong_date = call_domain(slots=slots)
        self.assertEqual(wrong_date["outcome_state"], "unknown")
        self.assertEqual(wrong_date["reason"], "event_slot_date_not_in_trip")

    def test_binding_factory_mutation_of_task_assignment_or_plan_stays_unknown(self):
        for target in ("task", "assignment", "plan"):
            with self.subTest(target=target):
                def malicious(task, assignment, plan):
                    if target == "task":
                        task["uid"] = "tampered"
                    elif target == "assignment":
                        assignment["day-slot-1"] = "tampered"
                    else:
                        plan["days"][0]["timeline"].clear()
                    return bindings_for(task_fixture(), {}, plan)
                result = call_domain(bindings_factory=malicious)
                self.assertEqual(result["decision_counts"]["pass"], 0)
                self.assertEqual(result["decision_counts"]["unknown"], 2)

    def test_binding_factory_receives_copies_and_caller_inputs_stay_unchanged(self):
        original_task, original_slots = task_fixture(), slots_fixture()
        task_snapshot, slots_snapshot = copy.deepcopy(original_task), copy.deepcopy(original_slots)
        result = search_explicit_event_domain(original_task, context(original_task), anchors(),
            original_slots, entity_kinds=KINDS,
            repeat_policy={"allow_repeated_occurrence_entities": True},
            record_bindings_resolver=binding_resolver, now="2026-10-31T00:00:00Z",
            registry={}, diagnostic_inputs={"overnight_boundaries": None,
                "meal_coverage": None, "lodging": None, "intercity": None,
                "finite_route_domain": None, "constraint_facts": None,
                "tag_evidence": None, "cost_aggregation": None},
            diagnostic_callbacks={})
        self.assertEqual(original_task, task_snapshot)
        self.assertEqual(original_slots, slots_snapshot)
        self.assertEqual(result["decision_counts"]["unknown"], 2)

    def test_holdout_rejected_without_enumerating_domain(self):
        result = call_domain(task=task_fixture("holdout", "holdout"))
        self.assertEqual(result["outcome_state"], "unknown")
        self.assertEqual(result["reason"], "holdout_rejected_from_event_domain")
        self.assertEqual(result["enumerated_assignment_count"], 0)

    def test_caller_completeness_claim_does_not_upgrade_declared_sample(self):
        task = task_fixture()
        task["candidate_selection"]["domain_complete"] = True
        task["event_domain_complete"] = True
        result = call_domain(task=task)
        self.assertFalse(result["event_domain_complete"])
        self.assertFalse(result["task_domain_complete"])
        self.assertFalse(result["planner_complete"])
        self.assertEqual(result["decision_counts"]["pass"], 0)


if __name__ == "__main__":
    unittest.main()
