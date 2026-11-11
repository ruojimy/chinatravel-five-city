import copy
import unittest
from unittest.mock import patch

from shorttrip.strict_search_orchestrator import search_development_assignments


def fixture_inputs():
    task = {
        "uid": "dev-search-1", "level": "easy", "split": "development",
        "purpose": "development", "start_city": "A", "target_city": "A",
        "start_date": "2026-11-15", "days": 1, "people_number": 2,
        "candidate_selection": {"required_entity_ids": ["entity-1", "start-1"]},
        "generation": {"selected_entities_by_kind": {
            "attraction": {"id": "entity-1", "stored_name_unverified": "attraction label"},
            "poi": {"id": "start-1", "stored_name_unverified": "start label"}}},
        "additional_constraints": [],
    }
    plan = {"uid": "dev-search-1", "level": "easy", "days": [{
        "date": "2026-11-15", "city": "A", "timeline": [
            {"type": "travel", "origin_id": "start-1", "destination_id": "entity-1",
             "from": "start label", "to": "attraction label", "start": "09:00", "end": "09:30"},
            {"type": "visit", "entity_id": "entity-1", "entity": "attraction label",
             "start": "09:30", "end": "10:30"},
        ]}]}
    context = {"start_city": "A", "target_city": "A", "start_date": "2026-11-15",
               "days": 1, "people_number": 2, "start_location_id": "start-1"}
    bindings = [{
        "entity_id": "entity-1", "kind": "attraction",
        "record": {"id": "entity-1", "kind": "attraction", "city": "A",
                   "name": "attraction label", "payload": {"data": {}}, "claims": []},
        "occurrences": [
            {"day_index": 0, "item_index": 0, "role": "travel_destination",
             "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                               "scope": {"travel_date": "2026-11-15"}}]},
            {"day_index": 0, "item_index": 1, "role": "activity",
             "requirements": [{"native_field": "opentime", "policy_field": "opening_hours",
                               "scope": {"travel_date": "2026-11-15"}}]},
        ],
    }, {
        "entity_id": "start-1", "kind": "poi",
        "record": {"id": "start-1", "kind": "poi", "city": "A",
                   "name": "start label", "payload": {"data": {}}, "claims": []},
        "occurrences": [{"day_index": 0, "item_index": 0, "role": "travel_origin",
                         "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                                           "scope": {"travel_date": "2026-11-15"}}]}],
    }]

    def resolver(_task, assignment):
        return {"plan": copy.deepcopy(plan), "plan_context": copy.deepcopy(context),
                "record_bindings": copy.deepcopy(bindings), "now": "2026-10-31T00:00:00Z",
                "registry": {}}

    return task, resolver


class StrictSearchOrchestratorTests(unittest.TestCase):
    def test_bound_business_chain_flows_through_search_without_plan_completion(self):
        task, base = fixture_inputs()
        task['generation']['business_chain'] = [{'entity_id': 'entity-1', 'kind': 'attraction'}]
        event = {'day_index': 0, 'item_index': 1, 'role': 'activity',
                 'date': '2026-11-15', 'entity_id': 'entity-1', 'kind': 'attraction'}
        def resolver(t, a):
            out = base(t, a)
            out['diagnostic_inputs'] = {'business_chain_events': [event]}
            out['diagnostic_callbacks'] = {'business_chain_inventory_verifier': lambda *_: True,
                                           'chain_event_verifier': lambda *_: True}
            return out
        result = search_development_assignments(task, {'x': ['a']}, resolver=resolver)
        self.assertEqual(result['diagnostics'][0]['diagnostic']['business_chain_check']['state'], 'pass')
        self.assertEqual(result['decision_counts']['unknown'], 1)
        self.assertFalse(result['complete_planner_integrated'])

    def test_explicit_diagnostic_inputs_are_forwarded_and_invalid_keys_rejected(self):
        task, base = fixture_inputs()
        def resolver(t, a):
            out = base(t, a)
            out['diagnostic_inputs'] = {'meal_coverage': {'required_slots': [], 'events': []}}
            return out
        result = search_development_assignments(task, {'x': ['a']}, resolver=resolver)
        diagnostic = result['diagnostics'][0]['diagnostic']
        self.assertIn('meal_coverage_check', diagnostic)
        self.assertEqual(diagnostic['meal_coverage_check']['state'], 'unknown')
        def invalid(t, a):
            out = base(t, a)
            out['diagnostic_inputs'] = {'plan_context': {'spoofed': True}}
            return out
        blocked = search_development_assignments(task, {'x': ['a']}, resolver=invalid)
        self.assertEqual(blocked['diagnostics'][0]['reason'], 'diagnostic_inputs_malformed')
        def corrupt(*args, **kwargs):
            kwargs['meal_coverage']['events'].append('forged')
            return {}
        with patch('shorttrip.strict_search_orchestrator.diagnose_development_plan', side_effect=corrupt):
            altered = search_development_assignments(task, {'x': ['a']}, resolver=resolver)
        self.assertEqual(altered['diagnostics'][0]['reason'], 'diagnostic_input_mutated')

    def test_actual_diagnostic_keeps_fixed_planner_gap_unknown(self):
        task, resolver = fixture_inputs()
        result = search_development_assignments(
            task, {"attraction": ["entity-1"]}, resolver=resolver,
            decision_verifier=lambda *_: True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        diagnostic = result["diagnostics"][0]["diagnostic"]
        self.assertTrue(diagnostic["axes"]["adapter"])
        reasons = {gap.get("reason") for gap in diagnostic["axes"]["adapter"]}
        self.assertIn("planner_feature_unsupported", reasons)
        self.assertFalse(result["complete_planner_integrated"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_holdout_is_rejected_without_calling_resolver(self):
        task, resolver = fixture_inputs()
        task.update(split="holdout", purpose="holdout")

        def forbidden(*_):
            raise AssertionError("resolver must not receive holdout")

        result = search_development_assignments(task, {"x": ["a"]}, resolver=forbidden)
        self.assertEqual(result["reason"], "holdout_rejected_from_search_orchestrator")
        self.assertEqual(result["enumerated_assignment_count"], 0)

    def test_resolver_missing_exception_or_mutation_is_unknown(self):
        task, resolver = fixture_inputs()
        missing = search_development_assignments(task, {"x": ["a"]})
        self.assertEqual(missing["diagnostics"][0]["reason"], "plan_resolver_missing")

        def raising(*_):
            raise RuntimeError("synthetic resolver exception")

        raised = search_development_assignments(task, {"x": ["a"]}, resolver=raising)
        self.assertEqual(raised["diagnostics"][0]["reason"], "plan_resolver_exception")

        def mutating(task_copy, assignment_copy):
            task_copy["uid"] = "mutated"
            return resolver(task_copy, assignment_copy)

        mutated = search_development_assignments(task, {"x": ["a"]}, resolver=mutating)
        self.assertEqual(mutated["diagnostics"][0]["reason"], "plan_resolver_mutated_input")

        def bool_mutating(_task, assignment_copy):
            assignment_copy["x"] = 1
            return resolver({}, {})

        bool_mutated = search_development_assignments(
            task, {"x": [True]}, resolver=bool_mutating)
        self.assertEqual(bool_mutated["diagnostics"][0]["reason"],
                         "plan_resolver_mutated_input")

    def test_only_exact_diagnostic_hard_failure_with_external_approval_can_fail(self):
        task, resolver = fixture_inputs()
        failure = {"field": "constraint:no_night", "state": "fail",
                   "reason": "verified_hard_tag_violation", "strength": "hard"}
        diagnostic = {"uid": "dev-search-1", "outcome": "adapter_block",
                      "hard_failures": [failure], "unknown_checks": [], "passed_checks": [],
                      "axes": {"adapter": [{"reason": "planner_feature_unsupported"}],
                               "pipeline": [], "data": [], "context": [], "access": [], "solver": []},
                      "planner_integration": "caller_supplied_plan_only",
                      "complete_planner_integrated": False}
        credentials = [{"field": failure["field"], "reason": failure["reason"],
                        "proof_id": "synthetic-proof", "proof_scope": "one-assignment",
                        "evidence_ids": ["synthetic-capture-1"]}]

        def resolver_with_credentials(t, a):
            out = resolver(t, a)
            out["hard_failure_credentials"] = copy.deepcopy(credentials)
            return out

        def verifier(t, a, decision):
            audit = decision["audit"]
            return (t["uid"] == task["uid"] and a == {"x": "candidate"}
                    and decision["failure"] == failure
                    and decision["proof_id"] == "synthetic-proof"
                    and audit["plan"]["uid"] == task["uid"]
                    and audit["plan_context"]["start_location_id"] == "start-1"
                    and len(audit["record_bindings"]) == 2
                    and audit["assignment"] == a
                    and audit["diagnostic"] == diagnostic
                    and decision["audit_sha256"] == __import__("hashlib").sha256(
                        __import__("json").dumps(audit, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":"), allow_nan=False)
                        .encode("utf-8")).hexdigest())

        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            result = search_development_assignments(
                task, {"x": ["candidate"]}, resolver=resolver_with_credentials,
                decision_verifier=verifier)
        self.assertEqual(result["decision_counts"]["fail"], 1)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertFalse(result["global_unsat_claimed"])
        self.assertEqual(result["diagnostics"][0]["state"], "fail_verified")

    def test_callable_callbacks_are_not_serialized_and_noncanonical_data_is_unknown(self):
        task, base_resolver = fixture_inputs()
        callback = lambda *_: None

        def with_callback(t, a):
            out = base_resolver(t, a)
            out["diagnostic_callbacks"] = {"opening_hours_validator": callback}
            out["hard_failure_credentials"] = [{
                "field": "synthetic", "reason": "synthetic_failure", "proof_id": "p",
                "proof_scope": "one-assignment", "evidence_ids": ["e"]}]
            return out

        diagnostic = {"uid": task["uid"], "hard_failures": [{
            "field": "synthetic", "reason": "synthetic_failure", "state": "fail"}],
            "axes": {}, "unknown_checks": [], "passed_checks": []}

        called = []

        def verifier(_task, _assignment, decision):
            called.append(decision)
            return False

        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            result = search_development_assignments(
                task, {"x": ["a"]}, resolver=with_callback, decision_verifier=verifier)
        audit = called[0]["audit"]
        self.assertNotIn("diagnostic_callbacks", audit)
        self.assertEqual(audit["diagnostic_callback_manifest"][0]["name"],
                         "opening_hours_validator")

        def noncanonical(t, a):
            out = base_resolver(t, a)
            out["registry"] = {"unsafe": {1, 2}}
            return out

        blocked = search_development_assignments(
            task, {"x": ["a"]}, resolver=noncanonical,
            decision_verifier=lambda *_: self.fail("must not verify uncanonical input"))
        self.assertEqual(blocked["diagnostics"][0]["reason"], "resolver_data_not_canonical")
        self.assertEqual(blocked["decision_counts"]["unknown"], 1)

    def test_audit_hash_binds_plan_and_bindings_for_verifier(self):
        task, resolver = fixture_inputs()
        failure = {"field": "hard-rule", "state": "fail", "reason": "verified_violation"}
        diagnostic = {"uid": task["uid"], "hard_failures": [failure], "axes": {},
                      "unknown_checks": [], "passed_checks": []}

        def with_credentials(t, a):
            out = resolver(t, a)
            out["hard_failure_credentials"] = [{
                "field": "hard-rule", "reason": "verified_violation", "proof_id": "p",
                "proof_scope": "assignment", "evidence_ids": ["e1"]}]
            return out

        def verifier(_t, _a, decision):
            audit = decision["audit"]
            audit["plan"]["uid"] = "forged"
            return True

        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            result = search_development_assignments(
                task, {"x": ["a"]}, resolver=with_credentials,
                decision_verifier=verifier)
        self.assertEqual(result["decision_counts"]["unknown"], 1)

        def verifier_accept(_t, _a, decision):
            audit = decision["audit"]
            return (audit["plan"]["uid"] == task["uid"] and
                    audit["record_bindings"][0]["entity_id"] == "entity-1" and
                    isinstance(decision["audit_sha256"], str))

        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            accepted = search_development_assignments(
                task, {"x": ["a"]}, resolver=with_credentials,
                decision_verifier=verifier_accept)
        self.assertEqual(accepted["decision_counts"]["fail"], 1)

    def test_missing_or_rejected_external_verifier_downgrades_failure_to_unknown(self):
        task, resolver = fixture_inputs()
        failure = {"field": "hard-rule", "state": "fail", "reason": "verified_violation"}
        diagnostic = {"uid": task["uid"], "hard_failures": [failure], "axes": {},
                      "unknown_checks": [], "passed_checks": []}

        def with_credentials(t, a):
            out = resolver(t, a)
            out["hard_failure_credentials"] = [{
                "field": "hard-rule", "reason": "verified_violation",
                "proof_id": "p", "proof_scope": "assignment",
                "evidence_ids": ["e1"],
            }]
            return out

        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            missing = search_development_assignments(task, {"x": ["a"]}, resolver=with_credentials)
            rejected = search_development_assignments(
                task, {"x": ["a"]}, resolver=with_credentials,
                decision_verifier=lambda *_: False)
            mutating = search_development_assignments(
                task, {"x": [True]}, resolver=with_credentials,
                decision_verifier=lambda _t, a, _d: a.update(x=1) or True)

            def verifier_error(*_):
                raise RuntimeError("synthetic external verifier failure")

            raised = search_development_assignments(
                task, {"x": ["a"]}, resolver=with_credentials,
                decision_verifier=verifier_error)
            no_credentials = search_development_assignments(
                task, {"x": ["a"]}, resolver=resolver,
                decision_verifier=lambda *_: True)
        self.assertEqual(missing["decision_counts"]["unknown"], 1)
        self.assertEqual(rejected["decision_counts"]["unknown"], 1)
        self.assertEqual(mutating["decision_counts"]["unknown"], 1)
        self.assertEqual(raised["decision_counts"]["unknown"], 1)
        self.assertEqual(no_credentials["decision_counts"]["unknown"], 1)

    def test_diagnostic_axes_are_not_filtered_even_with_all_component_passes(self):
        task, resolver = fixture_inputs()
        diagnostic = {"uid": task["uid"], "hard_failures": [],
                      "unknown_checks": [], "passed_checks": [{"field": "x", "state": "pass"}],
                      "axes": {"adapter": [{"reason": "planner_feature_unsupported"}],
                               "solver": [{"reason": "chronology_and_coverage_unverified"}]},
                      "planner_supported": False}
        with patch("shorttrip.strict_search_orchestrator.diagnose_development_plan",
                   return_value=diagnostic):
            result = search_development_assignments(
                task, {"x": ["a"]}, resolver=resolver,
                decision_verifier=lambda *_: True)
        self.assertEqual(result["decision_counts"]["pass"], 0)
        self.assertEqual(result["decision_counts"]["unknown"], 1)
        self.assertEqual(result["diagnostics"][0]["diagnostic"]["axes"], diagnostic["axes"])


if __name__ == "__main__":
    unittest.main()
