import unittest
from unittest.mock import patch
from shorttrip.strict_route_proof import verify_route_domain_failure, diagnose_finite_route_domain

CTX={'origin':'a','destination':'b','origin_entry':'east','destination_entry':'main',
     'coord_system':'WGS84','mode':'walking','travel_date':'2026-11-02',
     'departure_at':'2026-11-02T10:00:00+08:00'}
NOW='2026-11-02T09:55:00+08:00'


def evidence(duration):
    return {'context':dict(CTX),'duration_minutes':duration,'unit':'minutes',
            'observed_at':'2026-11-02T09:50:00+08:00','valid_until':'2026-11-02T10:00:00+08:00'}


def candidate(choice, limit):
    return {'choices':{'route':choice}, 'legs':[{'context':dict(CTX),'max_duration_minutes':limit}]}


class RouteProofTests(unittest.TestCase):
    def test_precise_decimal_route_duration_is_not_rounded_to_limit(self):
        out = verify_route_domain_failure(dimensions={'route':['a']},
            candidates=[candidate('a',20)], evidence=[evidence('20.0000000000000005')],
            now=NOW, evidence_verifier=lambda *_: True)
        self.assertTrue(out['verified'])
        rounded = verify_route_domain_failure(dimensions={'route':['a']},
            candidates=[candidate('a',20)], evidence=[evidence(20.0)],
            now=NOW, evidence_verifier=lambda *_: True)
        self.assertFalse(rounded['verified'])

    def test_blank_dimension_or_choice_cannot_become_a_proof(self):
        for dimensions in ({' ': ['a']}, {'route': [' ']}):
            result = verify_route_domain_failure(dimensions=dimensions, candidates=[],
                evidence=[evidence(20)], now=NOW, evidence_verifier=lambda *_: True)
            self.assertFalse(result['verified'])

    def test_verifier_cannot_tighten_original_limit_to_forge_failure(self):
        for entry in (verify_route_domain_failure, diagnose_finite_route_domain):
            candidates = [candidate('a', 30)]
            def mutate(*_args):
                candidates[0]['legs'][0]['max_duration_minutes'] = 10
                return True
            result = entry(dimensions={'route':['a']}, candidates=candidates,
                           evidence=[evidence(20)], now=NOW, evidence_verifier=mutate)
            with self.subTest(entry=entry.__name__):
                self.assertFalse(result.get('verified', False))
                self.assertNotEqual(result.get('status'), 'finite_route_domain_failure_verified')

    def test_conflict_or_elapsed_departure_does_not_become_feasible(self):
        for observations in ([evidence(5), evidence(20)], [evidence(20), evidence(5)]):
            out = diagnose_finite_route_domain(dimensions={'route': ['a']},
                candidates=[candidate('a', 10)], evidence=observations,
                now=NOW, evidence_verifier=lambda *_: True)
            self.assertEqual(out['status'], 'solver_incomplete')
        past_candidate = candidate('a', 30)
        past_candidate['legs'][0]['context']['departure_at'] = '2026-11-02T09:45:00+08:00'
        past_evidence = evidence(20)
        past_evidence['context'] = dict(past_candidate['legs'][0]['context'])
        out = diagnose_finite_route_domain(dimensions={'route': ['a']},
            candidates=[past_candidate], evidence=[past_evidence], now=NOW,
            evidence_verifier=lambda *_: True)
        self.assertEqual(out['status'], 'solver_incomplete')

    def test_enumerator_and_independent_checker_keep_scoped_status(self):
        out = diagnose_finite_route_domain(dimensions={'route':['a','b']},
            candidates=[candidate('a',10),candidate('b',15)], evidence=[evidence(20)],
            now=NOW,evidence_verifier=lambda *_: True)
        self.assertEqual(out['status'],'finite_route_domain_failure_verified')
        self.assertFalse(out['controller_certificate_issued'])
        self.assertEqual(out['proof_scope'],'declared_cartesian_route_domain')
        huge = diagnose_finite_route_domain(dimensions={'route':list(range(10001))},
            candidates=[],evidence=[],now=NOW,evidence_verifier=lambda *_: True)
        self.assertEqual(huge['proof_check']['reason'],'domain_limit_exceeded')
    def check(self, candidates, ev=None, verifier=lambda *_: True):
        return verify_route_domain_failure(dimensions={'route':['a','b']},candidates=candidates,
            evidence=ev if ev is not None else [evidence(20)],now=NOW,evidence_verifier=verifier)

    def test_complete_finite_failure_only_under_verified_inputs(self):
        out=self.check([candidate('a',10),candidate('b',15)])
        self.assertTrue(out['verified'])
        self.assertEqual(out['proof_scope'],'declared_cartesian_route_domain')
        self.assertFalse(out['execution_confirmed'])
        self.assertFalse(self.check([candidate('a',10),candidate('b',15)], verifier=None)['verified'])

    def test_missing_candidate_or_passing_candidate_rejects_proof(self):
        self.assertEqual(self.check([candidate('a',10)])['reason'],'domain_not_exhaustive')
        self.assertEqual(self.check([candidate('a',10),candidate('b',25)])['reason'],'candidate_not_shown_to_fail')

    def test_conflicting_or_stale_routes_cannot_prove(self):
        cases=[candidate('a',10),candidate('b',15)]
        self.assertEqual(self.check(cases,[evidence(20),evidence(5)])['reason'],'route_evidence_missing_or_conflicting')
        stale=evidence(20);stale['valid_until']='2026-11-02T09:54:00+08:00'
        self.assertFalse(self.check(cases,[stale])['verified'])

    def test_context_requires_exact_string_typed_route_scope(self):
        cases=[candidate('a',10),candidate('b',15)]
        bad=candidate('a',10)
        bad['legs'][0]['context']['origin']=True
        self.assertEqual(self.check([bad,cases[1]])['reason'],'leg_context_malformed')
        malformed=evidence(20)
        malformed['context']['mode']=1
        self.assertEqual(self.check(cases,[malformed])['reason'],'evidence_malformed')
        long_context=dict(CTX);long_context['origin']='x'*513
        oversized={'choices':{'route':'a'},'legs':[{'context':long_context,
                                                       'max_duration_minutes':10}]}
        self.assertEqual(self.check([oversized,cases[1]])['reason'],'leg_context_malformed')

    def test_json_confusable_domain_values_remain_distinct(self):
        dims={'choice':[True,1]}
        candidates=[{'choices':{'choice':True},'legs':[{'context':dict(CTX),'max_duration_minutes':10}]},
                    {'choices':{'choice':1},'legs':[{'context':dict(CTX),'max_duration_minutes':10}]}]
        result=verify_route_domain_failure(dimensions=dims,candidates=candidates,
            evidence=[evidence(20)],now=NOW,evidence_verifier=lambda *_:True)
        self.assertTrue(result['verified'])
        bad=[candidates[0], {'choices':{'choice':1.0},'legs':candidates[1]['legs']}]
        self.assertEqual(verify_route_domain_failure(dimensions=dims,candidates=bad,
            evidence=[evidence(20)],now=NOW,evidence_verifier=lambda *_:True)['reason'],
            'candidate_outside_domain_or_duplicate')

    def test_search_and_evidence_inputs_have_hard_bounds(self):
        out=verify_route_domain_failure(dimensions={'route':['a']},candidates=[candidate('a',10)],
            evidence=[evidence(20)]*65,now=NOW,evidence_verifier=lambda *_:True)
        self.assertEqual(out['reason'],'input_limit_exceeded')
        too_high=diagnose_finite_route_domain(dimensions={'route':['a']},
            candidates=[candidate('a',10)],evidence=[evidence(20)],now=NOW,
            evidence_verifier=lambda *_:True,max_assignments=10001)
        self.assertEqual(too_high['status'],'solver_incomplete')
        self.assertFalse(too_high['proof_check']['verified'])

    def test_malformed_inputs_do_not_reach_secondary_solver(self):
        with patch('shorttrip.strict_route_solver.solve_finite_route_domain') as solve:
            out=diagnose_finite_route_domain(dimensions={'route':['a']},
                candidates=[candidate('a',10)],evidence=[{'context':{}}],
                now=NOW,evidence_verifier=lambda *_:True)
        self.assertEqual(out['status'],'solver_incomplete')
        self.assertEqual(out['proof_check']['reason'],'evidence_malformed')
        solve.assert_not_called()

    def test_missing_assignment_is_not_repaired_by_duplicate_candidates(self):
        cases=[candidate('a',10),candidate('a',10)]
        self.assertEqual(self.check(cases)['reason'],'candidate_outside_domain_or_duplicate')

    def test_deep_malformed_candidate_choice_fails_closed(self):
        nested=[]
        cursor=nested
        for _ in range(5000):
            child=[]
            cursor.append(child)
            cursor=child
        malformed={'choices':{'route':nested},'legs':[]}
        result=verify_route_domain_failure(dimensions={'route':['a']},
            candidates=[malformed],evidence=[evidence(20)],now=NOW,
            evidence_verifier=lambda *_:True)
        self.assertFalse(result['verified'])
        self.assertIsNone(result['proof_scope'])


if __name__ == '__main__':
    unittest.main()
