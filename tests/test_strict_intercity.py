import copy
import unittest
from shorttrip.strict_intercity import check_intercity


def inputs():
    req={'origin_city':'A','destination_city':'B','origin_station':'A1','destination_station':'B1',
         'travel_date':'2026-11-01','departure_time':'23:00','clock_zone':'+08:00'}
    claim=dict(req,arrival_time='01:00',arrival_day_offset=1,Duration=2,Duration_unit='hours')
    return req,claim


class IntercityTests(unittest.TestCase):
    def test_timetable_clock_requires_explicit_ascii_minutes_and_known_offset(self):
        for key, value in (('departure_time', '23'), ('departure_time', '２３:００'),
                           ('clock_zone', '-00:00')):
            requirement, claim = inputs()
            requirement[key] = claim[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'unknown')
        requirement, claim = inputs()
        claim['arrival_time'] = '01'
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'unknown')

    def test_unknown_city_or_station_is_not_a_verified_timetable(self):
        for key in ('origin_city', 'destination_city', 'origin_station', 'destination_station'):
            requirement, claim = inputs()
            requirement[key] = claim[key] = 'unknown'
            with self.subTest(key=key):
                self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'unknown')

    def test_native_duration_requires_exact_value_and_no_tolerance(self):
        requirement, claim = inputs()
        claim['Duration'] = 2.0
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'unknown')
        claim['Duration'] = '2.0000000000000001'
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['reason'],
                         'duration_timetable_conflict')
        claim['Duration'] = '2.0'
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'pass')

    def test_overflowing_arrival_date_stays_unknown(self):
        requirement, claim = inputs()
        requirement['travel_date'] = claim['travel_date'] = '9999-12-31'
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=lambda *_: True)['state'], 'unknown')

    def test_verifier_cannot_mutate_original_and_copy(self):
        requirement, claim = inputs()
        def mutate(_req, copied_claim):
            claim['Duration'] = copied_claim['Duration'] = 1
            return True
        self.assertEqual(check_intercity(requirement, claim, claim_verifier=mutate)['state'], 'unknown')

    def test_hours_convert_only_with_qualified_complete_scope(self):
        req,claim=inputs()
        self.assertEqual(check_intercity(req,claim)['state'],'unknown')
        out=check_intercity(req,claim,claim_verifier=lambda *_:True)
        self.assertEqual(out['duration_minutes'],120)
        self.assertFalse(out['execution_confirmed'])

    def test_reverse_direction_wrong_station_or_wrong_unit_are_unknown(self):
        for key,value in [('destination_city','A'),('origin_station','A2'),('Duration_unit','minutes')]:
            req,claim=inputs();claim[key]=value
            self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['state'],'unknown')

    def test_timetable_mismatch_and_missing_day_offset_are_unknown(self):
        req,claim=inputs();claim['Duration']=409
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['reason'],'duration_timetable_conflict')
        req,claim=inputs();claim.pop('arrival_day_offset')
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['state'],'unknown')

    def test_missing_duration_is_not_a_unit_conflict(self):
        req,claim=inputs();claim['Duration']=None
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['reason'],'intercity_duration_missing')

    def test_unknown_timezone_and_unhandled_scope_fields_fail_closed(self):
        req,claim=inputs();req['clock_zone']=claim['clock_zone']='same_local_zone'
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['reason'],
                         'intercity_timezone_invalid_or_unverifiable')
        req,claim=inputs();req['seat_class']='first';claim['seat_class']='economy'
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['reason'],
                         'intercity_scope_has_unsupported_fields')
        req,claim=inputs();claim['seat_class']='first'
        self.assertEqual(check_intercity(req,claim,claim_verifier=lambda *_:True)['reason'],
                         'intercity_scope_has_unsupported_fields')

    def test_verifier_bool_to_int_mutation_is_detected_without_input_change(self):
        req,claim=inputs()
        original_req,original_claim=copy.deepcopy(req),copy.deepcopy(claim)
        def mutate(_requirement,claim_copy):
            claim_copy['arrival_day_offset']=True
            return True
        out=check_intercity(req,claim,claim_verifier=mutate)
        self.assertEqual(out['state'],'unknown')
        self.assertEqual(req,original_req)
        self.assertEqual(claim,original_claim)


if __name__ == '__main__':
    unittest.main()
