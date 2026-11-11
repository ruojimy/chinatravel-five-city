import unittest

from shorttrip.strict_domain_search import search_declared_domain


def fail(reason="synthetic_verified_conflict"):
    return {"state": "fail", "reason": reason, "proof_id": "proof-1",
            "proof_scope": "one-assignment", "evidence_ids": ["evidence-1"]}


class StrictDomainSearchTests(unittest.TestCase):
    def test_unknown_is_never_converted_to_failure(self):
        result = search_declared_domain(
            {"attraction": ["a", "b"]}, evaluator=lambda a: (
                fail() if a["attraction"] == "a" else
                {"state": "unknown", "reason": "evidence_missing"}),
            decision_verifier=lambda *_: True,
            domain_completeness_verifier=lambda *_: True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["decision_counts"], {"pass": 0, "fail": 1, "unknown": 1})
        self.assertFalse(result["global_unsat_claimed"])

    def test_complete_domain_generic_fails_cannot_certify_no_candidate(self):
        result = search_declared_domain(
            {"attraction": ["a", "b"]}, evaluator=lambda _: fail(),
            decision_verifier=lambda *_: True,
            domain_completeness_verifier=lambda *_: True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertFalse(result["global_unsat_claimed"])
        self.assertFalse(result["domain_limited_no_candidate_certified"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["three_day_plan_claimed"])

    def test_unreviewed_domain_never_gets_no_candidate_result(self):
        result = search_declared_domain(
            {"attraction": ["a"]}, evaluator=lambda _: fail(),
            decision_verifier=lambda *_: True)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertFalse(result["global_unsat_claimed"])

    def test_pass_requires_verifier_and_is_bounded_candidate_only(self):
        passed = {"state": "pass", "reason": "synthetic_fixture_pass",
                  "proof_id": "p", "proof_scope": "assignment",
                  "evidence_ids": ["e"]}
        result = search_declared_domain(
            {"meal": ["restaurant-1"]}, evaluator=lambda _: passed,
            decision_verifier=lambda *_: True)
        self.assertEqual(result["status"], "candidate_found_under_declared_domain")
        self.assertFalse(result["planner_integrated"])
        self.assertFalse(result["real_world_evidence_claimed"])
        self.assertFalse(result["execution_confirmed"])

    def test_domain_verifier_mutation_and_exception_fail_closed(self):
        def mutate(domain, _digest):
            domain["x"].append("forged")
            return True

        result = search_declared_domain(
            {"x": ["a"]}, evaluator=lambda _: fail(),
            decision_verifier=lambda *_: True,
            domain_completeness_verifier=mutate)
        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["domain_audit"]["completeness_reason"],
                         "domain_completeness_verifier_mutated_input")

        raised = search_declared_domain(
            {"x": ["a"]}, evaluator=lambda _: fail(),
            decision_verifier=lambda *_: True,
            domain_completeness_verifier=lambda *_: (_ for _ in ()).throw(RuntimeError()))
        self.assertFalse(raised["domain_audit"]["completeness_verified"])
        self.assertEqual(raised["status"], "solver_incomplete")

    def test_invalid_or_over_cap_domain_stays_incomplete(self):
        invalid = search_declared_domain({"x": []})
        self.assertEqual(invalid["status"], "solver_incomplete")
        self.assertFalse(invalid["domain_enumeration_complete"])
        capped = search_declared_domain({"x": ["a", "b"]}, max_assignments=1)
        self.assertEqual(capped["status"], "solver_incomplete")
        self.assertFalse(capped["global_unsat_claimed"])


if __name__ == "__main__":
    unittest.main()
