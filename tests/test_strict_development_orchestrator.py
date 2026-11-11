import copy
import unittest
from unittest.mock import patch

from shorttrip.strict_development_orchestrator import diagnose_development_plan


def self_cycle():
    value = []
    value.append(value)
    return value


def deep_scope():
    value = "leaf"
    for _ in range(130):
        value = {"nested": value}
    return value


def contains_pass_state(value):
    if isinstance(value, dict):
        return (value.get('state') == 'pass' or
                any(contains_pass_state(item) for item in value.values()))
    if isinstance(value, list):
        return any(contains_pass_state(item) for item in value)
    return False


class StrictDevelopmentOrchestratorTests(unittest.TestCase):
    def test_chain_events_bind_actual_plan_and_require_independent_inventory(self):
        task = copy.deepcopy(self.task)
        task['generation']['business_chain'] = [{'entity_id': 'entity-1', 'kind': 'attraction'}]
        event = {'day_index': 0, 'item_index': 1, 'role': 'activity',
                 'date': '2026-11-15', 'entity_id': 'entity-1', 'kind': 'attraction'}
        kwargs = {'task': task, 'business_chain_events': [event],
                  'chain_event_verifier': lambda _: True}
        unverified = self.call(**kwargs)
        self.assertEqual(unverified['business_chain_check']['state'], 'unknown')
        verified = self.call(**kwargs, business_chain_inventory_verifier=lambda *_: True)
        self.assertEqual(verified['business_chain_check']['state'], 'pass')
        self.assertFalse(verified['complete_planner_integrated'])

        forged = dict(event, entity_id='start-1', kind='poi')
        rejected = self.call(task=task, business_chain_events=[forged],
            business_chain_inventory_verifier=lambda *_: True, chain_event_verifier=lambda _: True)
        self.assertEqual(rejected['business_chain_check']['state'], 'unknown')

        def mutate(_task, plan, _chain, _events):
            plan['days'].clear()
            return True
        rejected = self.call(**kwargs, business_chain_inventory_verifier=mutate)
        self.assertEqual(rejected['business_chain_check']['state'], 'unknown')

    def test_chain_inventory_closure_mutation_returns_pipeline_error_without_pass(self):
        task = copy.deepcopy(self.task)
        task['generation']['business_chain'] = [
            {'entity_id': 'entity-1', 'kind': 'attraction'}]
        plan = copy.deepcopy(self.plan)
        context = copy.deepcopy(self.context)
        bindings = copy.deepcopy(self.bindings)
        event = {'day_index': 0, 'item_index': 1, 'role': 'activity',
                 'date': '2026-11-15', 'entity_id': 'entity-1', 'kind': 'attraction'}
        mutation_attempted = []

        def mutate_through_closure(*_args):
            mutation_attempted.append(True)
            task['generation']['business_chain'][0]['entity_id'] = 'start-1'
            plan['days'][0]['timeline'][1]['entity_id'] = 'start-1'
            return True

        result = diagnose_development_plan(
            task, plan, plan_context=context, record_bindings=bindings,
            now='2026-10-31T00:00:00Z', registry={},
            business_chain_events=[event],
            business_chain_inventory_verifier=mutate_through_closure,
            chain_event_verifier=lambda _: True)

        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertFalse(contains_pass_state(result))
        self.assertTrue(mutation_attempted)

    def test_identity_verifier_closure_record_mutation_returns_pipeline_error_without_pass(self):
        task = copy.deepcopy(self.task)
        plan = copy.deepcopy(self.plan)
        context = copy.deepcopy(self.context)
        bindings = copy.deepcopy(self.bindings)
        record = bindings[0]['record']
        mutation_attempted = []

        def mutate_record_through_closure(_record_copy):
            mutation_attempted.append(True)
            record['id'] = 'attacker-entity'
            record['name'] = 'replacement record'
            return True

        result = diagnose_development_plan(
            task, plan, plan_context=context, record_bindings=bindings,
            now='2026-10-31T00:00:00Z', registry={},
            identity_verifier=mutate_record_through_closure)

        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertFalse(contains_pass_state(result))
        self.assertFalse(any(
            item.get('entity_identity_verified') is True
            for axis in result.get('axes', {}).values()
            for item in axis if isinstance(item, dict)))
        self.assertTrue(mutation_attempted)

    def test_chain_event_order_and_role_must_bind_plan(self):
        task = copy.deepcopy(self.task)
        task['generation']['business_chain'] = [{'entity_id': 'entity-1', 'kind': 'attraction'}]
        first = {'day_index': 0, 'item_index': 0, 'role': 'travel_destination',
                 'date': '2026-11-15', 'entity_id': 'entity-1', 'kind': 'attraction'}
        second = dict(first, item_index=1, role='activity')
        for events in ([second, first], [first, first], [dict(first, role=[])],
                       [dict(first, date='2026-11-16')]):
            result = self.call(task=task, business_chain_events=events,
                business_chain_inventory_verifier=lambda *_: True, chain_event_verifier=lambda _: True)
            self.assertEqual(result['business_chain_check']['state'], 'unknown')

    def test_out_of_range_trip_horizon_is_context_block(self):
        task, context, plan = copy.deepcopy(self.task), copy.deepcopy(self.context), copy.deepcopy(self.plan)
        task['start_date'] = context['start_date'] = '9999-12-31'
        task['days'] = context['days'] = 2
        plan['days'] = [copy.deepcopy(plan['days'][0]), copy.deepcopy(plan['days'][0])]
        result = self.call(task=task, plan_context=context, plan=plan)
        self.assertEqual(result['axes']['context'][0]['reason'], 'plan_date_horizon_out_of_range')

    def test_unknown_city_cannot_become_valid_by_matching_task_and_plan(self):
        task = copy.deepcopy(self.task)
        context = copy.deepcopy(self.context)
        task['target_city'] = context['target_city'] = 'unknown'
        result = self.call(task=task, plan_context=context)
        self.assertEqual(result['axes']['context'][0]['reason'], 'plan_context_city_unknown')

    def test_boolean_party_or_boolean_task_day_cannot_alias_integer_context(self):
        task = copy.deepcopy(self.task)
        context = copy.deepcopy(self.context)
        task['days'] = True
        out = self.call(task=task, plan_context=context)
        self.assertEqual(out['axes']['context'][0]['reason'], 'plan_context_task_mismatch')
        task = copy.deepcopy(self.task)
        context = copy.deepcopy(self.context)
        task['people_number'] = context['people_number'] = True
        out = self.call(task=task, plan_context=context)
        self.assertEqual(out['axes']['context'][0]['reason'], 'plan_context_people_invalid')

    def setUp(self):
        self.task = {
            "uid": "dev-1", "level": "easy", "split": "development",
            "purpose": "development", "start_city": "A", "target_city": "A",
            "start_date": "2026-11-15", "days": 1, "people_number": 2,
            "candidate_selection": {"required_entity_ids": ["entity-1", "start-1"]},
            "generation": {"selected_entities_by_kind": {
                "attraction": {"id": "entity-1", "stored_name_unverified": "attraction label"},
                "poi": {"id": "start-1", "stored_name_unverified": "start label"}}},
            "additional_constraints": [],
        }
        self.plan = {
            "uid": "dev-1", "level": "easy", "days": [{
                "date": "2026-11-15", "city": "A", "timeline": [
                    {"type": "travel", "origin_id": "start-1",
                     "destination_id": "entity-1", "from": "start label",
                     "to": "attraction label", "start": "09:00", "end": "09:30"},
                    {"type": "visit", "entity_id": "entity-1",
                     "entity": "attraction label",
                     "start": "09:30", "end": "10:30"},
                ]}],
        }
        self.context = {
            "start_city": "A", "target_city": "A", "start_date": "2026-11-15",
            "days": 1, "people_number": 2, "start_location_id": "start-1",
        }
        self.bindings = [{
            "entity_id": "entity-1", "kind": "attraction",
            "record": {"id": "entity-1", "kind": "attraction", "city": "A", "name": "attraction label",
                       "payload": {"data": {}}, "claims": []},
            "occurrences": [{"day_index": 0, "item_index": 0, "role": "travel_destination",
                             "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                                               "scope": {"travel_date": "2026-11-15"}}]},
                            {"day_index": 0, "item_index": 1, "role": "activity",
                             "requirements": [{"native_field": "opentime", "policy_field": "opening_hours",
                                               "scope": {"travel_date": "2026-11-15"}}]}],
        }, {
            "entity_id": "start-1", "kind": "poi",
            "record": {"id": "start-1", "kind": "poi", "city": "A", "name": "start label",
                       "payload": {"data": {}}, "claims": []},
            "occurrences": [{"day_index": 0, "item_index": 0, "role": "travel_origin",
                             "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                                               "scope": {"travel_date": "2026-11-15"}}]}],
        }]

    def call(self, **changes):
        args = {"task": copy.deepcopy(self.task), "plan": copy.deepcopy(self.plan),
                "plan_context": copy.deepcopy(self.context),
                "record_bindings": copy.deepcopy(self.bindings),
                "now": "2026-10-31T00:00:00Z", "registry": {}}
        args.update(changes)
        return diagnose_development_plan(**args)

    def test_calls_strict_bridge_with_explicit_records_and_stays_engineering_only(self):
        bridge_result = {"uid": "strict-p31:dev-1", "level": "easy", "city": "A",
                         "outcome": "data_block", "axes": {"data": []}}
        with patch("shorttrip.strict_development_orchestrator.diagnose_p31_plan",
                   return_value=bridge_result) as bridge:
            result = self.call(identity_verifier=lambda _: True)
        self.assertEqual(bridge.call_count, 1)
        kwargs = bridge.call_args.kwargs
        self.assertEqual(kwargs["task"]["uid"], "dev-1")
        passed = {record["id"]: requirements for record, requirements in kwargs["record_requirements"]}
        self.assertEqual(set(passed), {"entity-1", "start-1"})
        self.assertEqual({item["policy_field"] for item in passed["entity-1"]},
                         {"opening_hours", "coordinates"})
        self.assertEqual(kwargs["business_chain"], None)
        self.assertTrue(result["engineering_only"])
        self.assertFalse(result["frozen"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])
        self.assertFalse(result["complete_planner_integrated"])

    def test_real_bridge_path_keeps_missing_identity_and_facts_unresolved(self):
        result = self.call()
        self.assertTrue(result["engineering_only"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])
        self.assertIn(result["outcome"], {"data_block", "solver_incomplete", "adapter_block"})
        self.assertTrue(result["axes"]["data"] or result["axes"]["solver"] or
                        result["axes"]["adapter"])

    def test_holdout_is_rejected_before_bridge(self):
        task = copy.deepcopy(self.task)
        task.update(split="holdout", purpose="holdout")
        with patch("shorttrip.strict_development_orchestrator.diagnose_p31_plan") as bridge:
            result = self.call(task=task)
        bridge.assert_not_called()
        self.assertEqual(result["axes"]["adapter"][0]["reason"],
                         "holdout_rejected_from_development_orchestrator")

    def test_missing_plan_or_context_is_rejected(self):
        missing_plan = self.call(plan=None)
        self.assertTrue(missing_plan["axes"]["pipeline"])
        self.assertEqual(missing_plan["axes"]["pipeline"][0]["reason"],
                         "plan_missing_or_not_object")
        missing_context = self.call(plan_context=None)
        self.assertTrue(missing_context["axes"]["context"])
        self.assertEqual(missing_context["axes"]["context"][0]["reason"],
                         "plan_context_missing")

    def test_cross_task_uid_and_mismatched_context_are_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["uid"] = "another-task"
        mismatch = self.call(plan=plan)
        self.assertEqual(mismatch["axes"]["adapter"][0]["reason"],
                         "task_plan_uid_mismatch")
        context = copy.deepcopy(self.context)
        context["people_number"] = 3
        mismatch = self.call(plan_context=context)
        self.assertEqual(mismatch["axes"]["context"][0]["reason"],
                         "plan_context_task_mismatch")

    def test_plan_start_must_match_context_and_be_explicitly_established(self):
        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"][0]["origin_id"] = "entity-1"
        result = self.call(plan=plan)
        self.assertEqual(result["axes"]["context"][0]["reason"],
                         "plan_start_location_mismatch")

        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"].pop(0)
        result = self.call(plan=plan)
        self.assertEqual(result["axes"]["context"][0]["reason"],
                         "plan_initial_position_not_established")

    def test_undeclared_duplicate_and_missing_bindings_fail_closed(self):
        undeclared = copy.deepcopy(self.bindings)
        undeclared[0]["entity_id"] = "other-id"
        undeclared[0]["record"]["id"] = "other-id"
        result = self.call(record_bindings=undeclared)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_uses_undeclared_entity_id")

        duplicate = copy.deepcopy(self.bindings) * 2
        result = self.call(record_bindings=duplicate)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "duplicate_record_binding")

        missing = self.call(record_bindings=[])
        self.assertEqual(missing["axes"]["pipeline"][0]["reason"],
                         "plan_binding_coverage_mismatch")

    def test_unbound_activity_id_and_missing_travel_endpoint_are_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"][1]["entity_id"] = "entity-2"
        with patch("shorttrip.strict_development_orchestrator.diagnose_p31_plan") as bridge:
            result = self.call(plan=plan)
        bridge.assert_not_called()
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "plan_uses_undeclared_entity_id")

        plan = copy.deepcopy(self.plan)
        del plan["days"][0]["timeline"][0]["destination_id"]
        result = self.call(plan=plan)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "plan_timeline_entity_binding_invalid")

    def test_activity_types_must_match_declared_entity_kinds(self):
        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"][1]["type"] = "lunch"
        result = self.call(plan=plan)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "plan_activity_kind_mismatch")
        self.assertEqual(result["axes"]["pipeline"][0]["detail"]["expected_kind"],
                         "restaurant")

        task = copy.deepcopy(self.task)
        task["generation"]["selected_entities_by_kind"]["attraction"] = {
            "id": "entity-1", "stored_name_unverified": "attraction label"}
        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"][1]["type"] = "visit"
        plan["days"][0]["timeline"][1]["entity_id"] = "start-1"
        result = self.call(task=task, plan=plan)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "plan_activity_kind_mismatch")

    def test_record_kind_city_and_requirement_scope_are_mandatory(self):
        bindings = copy.deepcopy(self.bindings)
        bindings[0]["record"]["kind"] = "restaurant"
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_kind_mismatch")

        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"][0]["requirements"][0]["scope"] = {}
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_requirement_incomplete")

    def test_requirement_scope_rejects_mixed_keys_cycles_and_excessive_depth(self):
        for mutate in (
            lambda scope: scope.update({1: "extra"}),
            lambda scope: scope.update({"cycle": self_cycle()}),
            lambda scope: scope.update({"deep": deep_scope()}),
        ):
            bindings = copy.deepcopy(self.bindings)
            scope = bindings[0]["occurrences"][0]["requirements"][0]["scope"]
            mutate(scope)
            result = self.call(record_bindings=bindings)
            self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                             "record_binding_requirement_incomplete")

        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"][0]["requirements"][0]["scope"].update(
            {"nested": {"zero": 0, "flag": False}})
        with patch("shorttrip.strict_development_orchestrator.diagnose_p31_plan",
                   return_value={"uid": "dev-1", "level": "easy", "outcome": "data_block",
                                 "axes": {"data": []}}) as bridge:
            self.call(record_bindings=bindings)
        bridge.assert_called_once()

    def test_future_scope_date_is_rejected_against_plan_date(self):
        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"][1]["requirements"][0]["scope"]["travel_date"] = "2099-01-01"
        result = self.call(record_bindings=bindings)
        gap = result["axes"]["pipeline"][0]
        self.assertEqual(gap["reason"], "record_binding_requirement_date_mismatch")
        self.assertEqual(gap["detail"]["expected_travel_date"], "2026-11-15")

    def test_reused_entity_requires_date_scoped_binding_for_each_occurrence(self):
        task = copy.deepcopy(self.task)
        task["days"] = 2
        context = copy.deepcopy(self.context)
        context["days"] = 2
        plan = copy.deepcopy(self.plan)
        plan["days"].append({"date": "2026-11-16", "city": "A", "timeline": [
            {"type": "visit", "entity_id": "entity-1", "entity": "attraction label",
             "start": "09:00", "end": "10:00"},
        ]})
        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"].append({
            "day_index": 1, "item_index": 0, "role": "activity",
            # Reusing the first day's scope for the second day's occurrence is invalid.
            "requirements": [{"native_field": "opentime", "policy_field": "opening_hours",
                              "scope": {"travel_date": "2026-11-15"}}],
        })
        result = self.call(task=task, plan=plan, plan_context=context, record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_requirement_date_mismatch")

    def test_record_name_and_plan_label_must_match_task_id_metadata(self):
        bindings = copy.deepcopy(self.bindings)
        bindings[0]["record"]["name"] = "different label"
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_task_name_metadata_mismatch")

        plan = copy.deepcopy(self.plan)
        plan["days"][0]["timeline"][1]["entity"] = "different label"
        result = self.call(plan=plan)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "plan_label_entity_mismatch")

        bindings = copy.deepcopy(self.bindings)
        bindings[1]["occurrences"][0]["requirements"] = []
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_requirements_missing")

        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"][0]["requirements"][0]["scope"] = {"travel": {}}
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_requirement_incomplete")

        bindings = copy.deepcopy(self.bindings)
        bindings[0]["occurrences"][0]["requirements"][0]["scope"] = {"travel": {"date": "   "}}
        result = self.call(record_bindings=bindings)
        self.assertEqual(result["axes"]["pipeline"][0]["reason"],
                         "record_binding_requirement_incomplete")

    def test_bridge_exception_becomes_pipeline_block_not_success(self):
        with patch("shorttrip.strict_development_orchestrator.diagnose_p31_plan",
                   side_effect=RuntimeError("synthetic failure")):
            result = self.call()
        self.assertEqual(result["axes"]["pipeline"][0]["reason"], "strict_bridge_failed")
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["frozen"])


if __name__ == "__main__":
    unittest.main()
