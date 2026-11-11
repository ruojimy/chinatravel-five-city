import copy
import math
import unittest

from shorttrip.strict_finite_plan_search import search_finite_plan_domain


def proof(state, *, reason="synthetic-control", evidence_id="fixture-evidence"):
    return {"state": state, "reason": reason, "proof_id": "fixture-proof",
            "proof_scope": "synthetic-declared-assignment",
            "evidence_ids": [evidence_id]}


class StrictFinitePlanSearchTests(unittest.TestCase):
    def test_non_utf8_domain_value_is_not_a_verified_candidate(self):
        result = search_finite_plan_domain({'x':['\ud800']},
            evaluator=lambda _: proof('pass'), decision_verifier=lambda *_: True)
        self.assertEqual(result['status'], 'solver_incomplete')
        self.assertEqual(result['candidate_count'], 0)

    def test_callbacks_cannot_mutate_original_domain_or_decision(self):
        domain = {'x': ['a']}
        def mutate_domain(_assignment):
            domain['x'].append('b')
            return proof('pass')
        result = search_finite_plan_domain(domain, evaluator=mutate_domain,
                                           decision_verifier=lambda *_: True)
        self.assertEqual(result['status'], 'solver_incomplete')
        self.assertEqual(result['reason'], 'domain_original_input_mutated')
        self.assertEqual(result['candidate_count'], 0)

        decision = proof('pass')
        def mutate_decision(*_args):
            decision['evidence_ids'].append('other')
            return True
        result = search_finite_plan_domain({'x':['a']}, evaluator=lambda _: decision,
                                           decision_verifier=mutate_decision)
        self.assertEqual(result['candidate_count'], 0)
        self.assertEqual(result['assignments'][0]['reason'], 'decision_verifier_mutated_input')

    def test_unknown_proof_credentials_cannot_be_verified_into_a_decision(self):
        for field in ('proof_id', 'proof_scope', 'evidence_ids'):
            decision = proof('pass')
            decision[field] = ['unknown_entity'] if field == 'evidence_ids' else 'unresolved_id'
            result = search_finite_plan_domain({'x': ['a']}, evaluator=lambda _: decision,
                                               decision_verifier=lambda *_: True)
            self.assertEqual(result['decision_counts']['unknown'], 1)
            self.assertEqual(result['candidate_count'], 0)

    def test_found_candidate_is_bounded_and_never_certified(self):
        result = search_finite_plan_domain(
            {"day": [1, 2], "choice": ["a", "b"]},
            evaluator=lambda a: proof("pass" if a == {"choice": "b", "day": 2} else "fail"),
            decision_verifier=lambda *_: True,
        )
        self.assertEqual(result["status"], "bounded_candidate_found")
        self.assertEqual(result["declared_assignment_count"], 4)
        self.assertEqual(result["enumerated_assignment_count"], 4)
        self.assertEqual(result["decision_counts"], {"pass": 1, "fail": 3, "unknown": 0})
        self.assertFalse(result["global_unsat_claimed"])
        self.assertFalse(result["real_world_feasibility_certified"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_unknown_and_missing_evaluator_are_not_failure_or_pass(self):
        missing = search_finite_plan_domain({"x": ["a", "b"]})
        self.assertEqual(missing["status"], "solver_incomplete")
        self.assertEqual(missing["decision_counts"]["unknown"], 2)
        self.assertEqual(missing["assignments"][0]["reason"], "independent_evaluator_missing")

        mixed = search_finite_plan_domain(
            {"x": ["a", "b"]},
            evaluator=lambda a: proof("unknown", reason="evidence-missing")
            if a["x"] == "a" else proof("fail"),
            decision_verifier=lambda *_: True,
        )
        self.assertEqual(mixed["status"], "solver_incomplete")
        self.assertEqual(mixed["decision_counts"], {"pass": 0, "fail": 1, "unknown": 1})
        self.assertFalse(mixed["global_unsat_claimed"])

    def test_all_proved_failures_still_do_not_claim_global_unsat(self):
        result = search_finite_plan_domain(
            {"x": ["a", "b"]}, evaluator=lambda _: proof("fail"),
            decision_verifier=lambda *_: True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["reason"],
                         "all_enumerated_assignments_rejected_but_global_unsat_unproved")
        self.assertTrue(result["domain_enumeration_complete"])
        self.assertFalse(result["global_unsat_claimed"])

    def test_missing_credentials_or_invalid_decision_become_unknown(self):
        cases = [
            lambda _: {"state": "pass", "reason": "claimed"},
            lambda _: {"state": "fail", "reason": "claimed", "verified": True},
            lambda _: {"state": "pass", "reason": "claimed", "proof_id": "p",
                       "proof_scope": "scope", "evidence_ids": []},
            lambda _: {"state": "solved", "reason": "claimed"},
            lambda _: {"state": "fail"},
        ]
        for evaluator in cases:
            with self.subTest(evaluator=evaluator):
                result = search_finite_plan_domain({"x": ["a"]}, evaluator=evaluator,
                                                   decision_verifier=lambda *_: True)
                self.assertEqual(result["decision_counts"]["unknown"], 1)
                self.assertEqual(result["status"], "solver_incomplete")

    def test_evaluator_exception_and_input_mutation_become_unknown(self):
        original = {"x": [{"id": "a", "nested": [1]}]}

        def raising(_):
            raise RuntimeError("synthetic verifier failure")

        raised = search_finite_plan_domain(original, evaluator=raising)
        self.assertEqual(raised["assignments"][0]["reason"], "evaluator_exception")

        def mutating(assignment):
            assignment["x"]["nested"].append(2)
            return proof("pass")

        mutated = search_finite_plan_domain(original, evaluator=mutating)
        self.assertEqual(mutated["assignments"][0]["reason"],
                         "evaluator_mutated_assignment")
        self.assertEqual(original, {"x": [{"id": "a", "nested": [1]}]})

    def test_invalid_domains_and_caps_are_rejected_before_evaluator(self):
        calls = []
        evaluator = lambda a: calls.append(a) or proof("pass")
        cases = [
            ({}, 10, "domain_missing_malformed_or_too_many_dimensions"),
            ({"x": []}, 10, "dimension_domain_empty_or_malformed"),
            ({"x": ["a", "a"]}, 10, "duplicate_domain_value"),
            ({"x": [None]}, 10, "domain_value_null_not_allowed"),
            ({"x": [float("nan")]}, 10, "domain_value_nonfinite_number"),
            ({"x": [""]}, 10, "domain_value_empty_string"),
            ({"x": [1, 2], "y": ["a", "b"]}, 3, "domain_limit_exceeded"),
            ({"x": ["a"]}, 0, "assignment_limit_invalid"),
        ]
        for dimensions, cap, reason in cases:
            with self.subTest(reason=reason):
                result = search_finite_plan_domain(dimensions, evaluator=evaluator,
                                                   max_assignments=cap)
                self.assertEqual(result["status"], "solver_incomplete")
                self.assertEqual(result["reason"], reason)
        self.assertEqual(calls, [])

    def test_cyclic_and_unsupported_domain_values_are_rejected(self):
        cyclic = []
        cyclic.append(cyclic)
        unsupported = {"x": [object()]}
        result = search_finite_plan_domain({"x": [cyclic]})
        self.assertEqual(result["reason"], "domain_value_cycle")
        result = search_finite_plan_domain(unsupported)
        self.assertEqual(result["reason"], "domain_value_type_unsupported")

    def test_domain_order_is_canonical_and_json_scalar_types_stay_distinct(self):
        result = search_finite_plan_domain(
            {"z": [True, 1], "a": ["x"]}, evaluator=lambda _: proof("unknown"),
            decision_verifier=lambda *_: True)
        self.assertEqual(result["dimensions"], ["a", "z"])
        self.assertEqual(result["declared_assignment_count"], 2)
        self.assertEqual([x["assignment"]["z"] for x in result["assignments"]], [True, 1])

    def test_decision_verifier_is_required_and_must_return_literal_true(self):
        assignment = {"x": True}
        evaluator = lambda _: proof("pass")
        missing = search_finite_plan_domain({"x": [True]}, evaluator=evaluator)
        self.assertEqual(missing["assignments"][0]["reason"],
                         "independent_decision_verifier_missing")

        rejected = search_finite_plan_domain(
            {"x": [True]}, evaluator=evaluator,
            decision_verifier=lambda *_: 1)
        self.assertEqual(rejected["assignments"][0]["reason"],
                         "independent_decision_verification_failed")

        def raising_verifier(_candidate, _decision):
            raise RuntimeError("synthetic decision verifier failure")

        raised = search_finite_plan_domain(
            {"x": [True]}, evaluator=evaluator,
            decision_verifier=raising_verifier)
        self.assertEqual(raised["assignments"][0]["reason"],
                         "decision_verifier_exception")

        def mutate_assignment(candidate, _decision):
            candidate["x"] = 1  # Python considers this equal to True; canonical JSON does not.
            return True

        assignment_mutation = search_finite_plan_domain(
            {"x": [True]}, evaluator=evaluator,
            decision_verifier=mutate_assignment)
        self.assertEqual(assignment_mutation["assignments"][0]["reason"],
                         "decision_verifier_mutated_input")

        def mutate_decision(_candidate, decision):
            decision["proof_id"] = "changed"
            return True

        decision_mutation = search_finite_plan_domain(
            {"x": [True]}, evaluator=evaluator,
            decision_verifier=mutate_decision)
        self.assertEqual(decision_mutation["assignments"][0]["reason"],
                         "decision_verifier_mutated_input")

        self.assertEqual(assignment, {"x": True})


if __name__ == "__main__":
    unittest.main()
