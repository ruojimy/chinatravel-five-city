import unittest
import json

from shorttrip.strict_route_solver import route_evidence_gate, solve_finite_route_domain

NOW = "2026-10-30T10:00:00+08:00"
CTX = {
    "origin": "poi:A", "destination": "poi:B", "origin_entry": "east gate",
    "destination_entry": "main gate", "coord_system": "GCJ02", "mode": "walking",
    "travel_date": "2026-10-30", "departure_at": "2026-10-30T10:30:00+08:00",
}


def evidence(ctx=CTX, duration=20, **extra):
    return {"context": dict(ctx), "duration_minutes": duration, "unit": "minutes",
            "observed_at": "2026-10-30T09:55:00+08:00",
            "valid_until": "2026-10-30T10:10:00+08:00", **extra}


def candidate(choice, limit):
    return {"choices": {"route": choice}, "legs": [{"context": dict(CTX),
            "max_duration_minutes": limit}]}


class StrictRouteSolverTests(unittest.TestCase):
    def test_non_utf8_choice_cannot_be_feasible(self):
        result = solve_finite_route_domain(dimensions={'route':['\ud800']},
            candidates=[candidate('\ud800', 30)], evidence=[self.trusted_evidence()],
            now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(result['status'], 'context_incomplete')

    def test_float_duration_loses_source_precision_and_cannot_pass(self):
        rounded = json.loads('20.0000000000000005')
        result = solve_finite_route_domain(dimensions={'route':['r1']},
            candidates=[candidate('r1', 20)], evidence=[self.trusted_evidence(duration=rounded)],
            now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(result['status'], 'solver_incomplete')
        exact = solve_finite_route_domain(dimensions={'route':['r1']},
            candidates=[candidate('r1', 20)],
            evidence=[self.trusted_evidence(duration='20.0000000000000005')],
            now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(exact['outcomes'][0]['status'], 'candidate_constraint_fail')

    def test_float_limit_cannot_establish_feasibility(self):
        result = solve_finite_route_domain(dimensions={'route':['r1']},
            candidates=[candidate('r1', 20.0)], evidence=[self.trusted_evidence(duration=20)],
            now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(result['status'], 'solver_incomplete')

    def test_evidence_verifier_closure_cannot_widen_original_candidate_limit(self):
        route_candidate = candidate("r1", 10)

        def widen_limit_through_closure(_requirement, _evidence):
            route_candidate["legs"][0]["max_duration_minutes"] = 30
            return True

        result = solve_finite_route_domain(
            dimensions={"route": ["r1"]}, candidates=[route_candidate],
            evidence=[self.trusted_evidence(duration=20)], now=NOW,
            evidence_verifier=widen_limit_through_closure)

        self.assertEqual(result["status"], "solver_incomplete")
        self.assertEqual(result["reason"], "route_original_inputs_mutated")
        self.assertFalse(any(
            outcome.get("status") == "candidate_feasible"
            for outcome in result.get("outcomes", [])))

    def test_tuple_values_and_whitespace_dimension_names_are_rejected(self):
        tuple_value = solve_finite_route_domain(
            dimensions={"route": [("r1",)]},
            candidates=[candidate(("r1",), 30)],
            evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(tuple_value["status"], "context_incomplete")

        whitespace_name = solve_finite_route_domain(
            dimensions={" ": ["r1"]},
            candidates=[{"choices": {" ": "r1"},
                         "legs": [{"context": dict(CTX),
                                   "max_duration_minutes": 30}]}],
            evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(whitespace_name["status"], "context_incomplete")

    def test_verifier_cannot_mutate_both_copy_and_original(self):
        route = self.trusted_evidence()
        def mutate(_req_copy, ev_copy):
            route['duration_minutes'] = 1
            ev_copy['duration_minutes'] = 1
            return True
        result = route_evidence_gate({'context': dict(CTX)}, route,
                                     now=NOW, evidence_verifier=mutate)
        self.assertFalse(result['usable'])
        self.assertIsNone(result['duration_minutes'])

    def test_conflicting_durations_remain_unknown_in_any_order(self):
        short = self.trusted_evidence(duration=5)
        long = self.trusted_evidence(duration=20)
        for observations in ([short, long], [long, short]):
            result = solve_finite_route_domain(dimensions={'route': ['r1']},
                candidates=[candidate('r1', 10)], evidence=observations, now=NOW,
                evidence_verifier=self.verifier)
            self.assertEqual(result['status'], 'solver_incomplete')
            self.assertEqual(result['outcomes'][0]['status'], 'solver_incomplete')

    def test_elapsed_departure_is_not_eligible(self):
        context = dict(CTX, departure_at='2026-10-30T09:30:00+08:00')
        out = route_evidence_gate({'context': context}, self.trusted_evidence(context),
                                  now=NOW, evidence_verifier=self.verifier)
        self.assertFalse(out['usable'])
        self.assertIn('route_departure_already_elapsed', out['reasons'])

    def test_large_declared_domain_is_rejected_before_enumeration(self):
        result = solve_finite_route_domain(dimensions={'a': list(range(101)), 'b': list(range(100))},
            candidates=[], evidence=[], now=NOW)
        self.assertEqual(result['status'], 'solver_incomplete')
        self.assertEqual(result['reason'], 'route_domain_assignment_limit_exceeded')
        too_many = solve_finite_route_domain(dimensions={'route': ['r1']},
            candidates=[candidate('r1', 30)], evidence=[self.trusted_evidence()] * 65,
            now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(too_many['reason'], 'route_evidence_per_context_limit_exceeded')

    def test_utc_conversion_overflow_and_excessive_leg_count_fail_closed(self):
        # This local timestamp is parseable, but converting it to UTC would
        # cross year 9999. It must not bypass the elapsed-time comparison.
        overflow_context = dict(CTX, travel_date='9999-12-31',
            departure_at='9999-12-31T23:30:00-14:00')
        overflow_evidence = self.trusted_evidence(overflow_context)
        gate = route_evidence_gate({'context': overflow_context}, overflow_evidence,
            now=NOW, evidence_verifier=self.verifier)
        self.assertFalse(gate['usable'])
        self.assertIn('route_departure_context_invalid', gate['reasons'])

        oversized_candidate = candidate('r1', 30)
        oversized_candidate['legs'] = [dict(oversized_candidate['legs'][0])
                                       for _ in range(50001)]
        result = solve_finite_route_domain(dimensions={'route': ['r1']},
            candidates=[oversized_candidate], evidence=[], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(result['status'], 'solver_incomplete')
        self.assertEqual(result['reason'], 'route_input_limit_or_shape_invalid')

    def test_deep_malformed_candidate_choice_fails_closed(self):
        nested = []
        cursor = nested
        for _ in range(5000):
            child = []
            cursor.append(child)
            cursor = child
        malformed = {'choices': {'route': nested}, 'legs': []}
        result = solve_finite_route_domain(dimensions={'route': ['r1']},
            candidates=[malformed], evidence=[], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(result['status'], 'solver_incomplete')

    @staticmethod
    def verifier(requirement, item):
        # Test verifier models an independently checked provider payload.
        return item.get("provider_id") == "provider-route-1" and bool(item.get("raw_response")) and item.get("permission") == "allowed"

    @classmethod
    def trusted_evidence(cls, ctx=CTX, duration=20, **extra):
        return evidence(ctx, duration, provider_id="provider-route-1", raw_response={"duration": duration},
                        permission="allowed", **extra)

    def test_missing_context_and_wrong_direction_rejected_even_with_self_flags(self):
        missing = dict(CTX); missing.pop("departure_at")
        out = route_evidence_gate({"context": missing}, self.trusted_evidence(missing, verified=True),
                                  now=NOW, evidence_verifier=self.verifier)
        self.assertFalse(out["usable"])
        reverse = dict(CTX, origin="poi:B", destination="poi:A")
        out = route_evidence_gate({"context": CTX}, self.trusted_evidence(reverse, validated=True),
                                  now=NOW, evidence_verifier=self.verifier)
        self.assertIn("route_context_mismatch:origin", out["reasons"])
        self.assertIn("route_context_mismatch:destination", out["reasons"])

    def test_request_and_evidence_context_reject_extra_dimensions(self):
        request = dict(CTX, avoid_tolls=True)
        evidence_with_extra = self.trusted_evidence(request)
        out = route_evidence_gate({"context": request}, evidence_with_extra,
                                  now=NOW, evidence_verifier=self.verifier)
        self.assertFalse(out["usable"])
        self.assertIn("route_request_context_keys_missing_or_unsupported", out["reasons"])
        self.assertIn("route_evidence_context_keys_missing_or_unsupported", out["reasons"])

        out = route_evidence_gate({"context": CTX}, self.trusted_evidence(dict(CTX, avoid_tolls=True)),
                                  now=NOW, evidence_verifier=self.verifier)
        self.assertFalse(out["usable"])
        self.assertIn("route_evidence_context_keys_missing_or_unsupported", out["reasons"])

    def test_expired_route_rejected(self):
        e = self.trusted_evidence(valid_until="2026-10-30T09:59:59+08:00")
        self.assertIn("route_evidence_expired", route_evidence_gate({"context": CTX}, e, now=NOW,
            evidence_verifier=self.verifier)["reasons"])

    def test_long_lived_route_is_rejected_even_with_verified_source(self):
        e = self.trusted_evidence(valid_until="2026-10-30T10:16:00+08:00")
        out = route_evidence_gate({"context": CTX}, e, now=NOW, evidence_verifier=self.verifier)
        self.assertIn("route_ttl_exceeds_policy", out["reasons"])
        self.assertFalse(out["usable"])

    def test_date_and_coordinate_system_cannot_be_internally_inconsistent(self):
        bad = dict(CTX, travel_date='2026-10-31', coord_system='unknown')
        out = route_evidence_gate({'context':bad}, self.trusted_evidence(bad), now=NOW,
                                  evidence_verifier=self.verifier)
        self.assertIn('route_departure_date_mismatch', out['reasons'])
        self.assertIn('route_coordinate_system_unknown', out['reasons'])

    def test_verifier_is_mandatory_and_self_asserted_flags_are_ignored(self):
        e = evidence(CTX, verified=True, source_verified=True, licence_ok=True)
        out = route_evidence_gate({"context": CTX}, e, now=NOW)
        self.assertFalse(out["usable"])
        self.assertIn("independent_evidence_verifier_required", out["reasons"])
        out = route_evidence_gate({"context": CTX}, e, now=NOW,
                                  evidence_verifier=lambda *_: True)
        self.assertTrue(out["usable"])
        self.assertFalse(route_evidence_gate({"context": CTX}, e, now=NOW,
            evidence_verifier=lambda *_: "true")["usable"])

    def test_verifier_bool_int_mutation_is_detected_and_input_is_unchanged(self):
        e = self.trusted_evidence(duration=1)

        def change_duration_type(_requirement, evidence_copy):
            evidence_copy["duration_minutes"] = True
            return True

        out = route_evidence_gate({"context": CTX}, e, now=NOW,
                                  evidence_verifier=change_duration_type)
        self.assertFalse(out["usable"])
        self.assertIn("independent_evidence_verification_failed", out["reasons"])
        self.assertEqual(e["duration_minutes"], 1)
        self.assertIs(type(e["duration_minutes"]), int)

    def test_cyclic_and_deep_route_payloads_fail_closed_without_input_mutation(self):
        cycle = {}
        cycle["self"] = cycle
        e = evidence(CTX, 20, provider_id="provider-route-1", raw_response=cycle,
                     permission="allowed")
        out = route_evidence_gate({"context": CTX}, e, now=NOW,
                                  evidence_verifier=lambda *_: True)
        self.assertFalse(out["usable"])
        self.assertIn("independent_evidence_verification_failed", out["reasons"])
        self.assertIs(e["raw_response"]["self"], e["raw_response"])

        nested = []
        cursor = nested
        for _ in range(300):
            child = []
            cursor.append(child)
            cursor = child
        e = evidence(CTX, 20, provider_id="provider-route-1", raw_response=nested,
                     permission="allowed")
        out = route_evidence_gate({"context": CTX}, e, now=NOW,
                                  evidence_verifier=lambda *_: True)
        self.assertFalse(out["usable"])
        self.assertIn("independent_evidence_verification_failed", out["reasons"])
        self.assertEqual(len(nested[0][0]), 1)

    def test_one_candidate_failure_does_not_prove_finite_domain_unsat(self):
        out = solve_finite_route_domain(dimensions={"route": ["r1", "r2"]},
            candidates=[candidate("r1", 10), candidate("r2", 30)], evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "candidate_feasible")
        self.assertEqual(out["outcomes"][0]["status"], "candidate_constraint_fail")

    def test_unsat_requires_complete_domain_and_independently_checked_inputs(self):
        out = solve_finite_route_domain(dimensions={"route": ["r1", "r2"]},
            candidates=[candidate("r1", 10), candidate("r2", 15)], evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")
        self.assertEqual(out["reason"], "independent_infeasibility_verifier_required")
        # A participant's claim cannot compensate for a missing domain member.
        out = solve_finite_route_domain(dimensions={"route": ["r1", "r2"]},
            candidates=[candidate("r1", 10)], evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")
        # Expired/missing evidence means unknown, even if all listed candidates fail.
        out = solve_finite_route_domain(dimensions={"route": ["r1", "r2"]},
            candidates=[candidate("r1", 10), candidate("r2", 15)],
            evidence=[self.trusted_evidence(valid_until="2026-10-30T09:59:59+08:00")], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")

    def test_duplicate_and_unhashable_domain_values_are_not_proofs(self):
        for values in (["r1", "r1"], [["r1"]]):
            out = solve_finite_route_domain(dimensions={"route": values}, candidates=[], evidence=[], now=NOW,
                                             evidence_verifier=self.verifier)
            self.assertEqual(out["status"], "context_incomplete")

    def test_malformed_dimensions_and_candidate_choices_fail_closed(self):
        for dimensions in ({1: ["r1"]}, {"route": [float("nan")]}, {"route": []}):
            out = solve_finite_route_domain(dimensions=dimensions, candidates=[], evidence=[], now=NOW,
                                             evidence_verifier=self.verifier)
            self.assertNotEqual(out["status"], "candidate_feasible")
        out = solve_finite_route_domain(dimensions={"route": ["r1"]},
            candidates=[{"choices": [["route", "r1"]], "legs": []}], evidence=[], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")

    def test_malformed_leg_and_evidence_contexts_are_unknown_not_proof(self):
        bad_candidate = {"choices": {"route": "r1"}, "legs": ["not-a-leg"]}
        out = solve_finite_route_domain(dimensions={"route": ["r1"]}, candidates=[bad_candidate],
            evidence=[{"context": {"origin": []}}], now=NOW, evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")
        self.assertEqual(out["outcomes"][0]["status"], "solver_incomplete")

    def test_infeasibility_is_never_promoted_without_independent_proof(self):
        out = solve_finite_route_domain(dimensions={"route": ["r1"]},
            candidates=[candidate("r1", 10)], evidence=[self.trusted_evidence()], now=NOW,
            evidence_verifier=self.verifier)
        self.assertEqual(out["status"], "solver_incomplete")
        self.assertIsNone(out["proof_scope"])
        self.assertFalse(out["execution_confirmed"])


if __name__ == "__main__":
    unittest.main()
