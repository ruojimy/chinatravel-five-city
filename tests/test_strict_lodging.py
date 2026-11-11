import unittest
from shorttrip.strict_lodging import check_lodging


def inputs():
    req={'entity_id':'h','room_type':'twin','check_in':'2026-11-01','check_out':'2026-11-03',
         'rooms':2,'guests_per_room':2,'minimum_beds':2,'eligibility':'public',
         'meal_plan':'no_breakfast','taxes_included':True,'mandatory_fees_included':True}
    claim={'entity_id':'h','room_type':'twin','check_in':'2026-11-01','check_out':'2026-11-03',
           'guests_per_room':2,'currency':'CNY','unit':'CNY/room/night','rate':400,'beds':2,'max_guests_per_room':2,
           'eligibility':'public','meal_plan':'no_breakfast','taxes_included':True,'mandatory_fees_included':True}
    return req,claim


class LodgingTests(unittest.TestCase):
    def test_rates_require_unambiguous_source_decimal_values(self):
        for value in (0.1, 1.0, True, '01.2', '1e2', '-1', 'NaN', '1,000', ' 1', '1' * 257):
            with self.subTest(value=value):
                requirement, claim = inputs()
                claim['rate'] = value
                self.assertEqual(check_lodging(requirement, claim,
                    claim_verifier=lambda *_: True)['state'], 'unknown')
        requirement, claim = inputs()
        claim['rate'] = '0.10000000000000001'
        result = check_lodging(requirement, claim, claim_verifier=lambda *_: True)
        self.assertEqual(result['total_decimal'], '0.40000000000000004')
        self.assertIsNone(result['total_cny'])

    def test_verifier_cannot_mutate_original_through_closure(self):
        requirement, claim = inputs()
        def mutate(_requirement, _claim):
            requirement['rooms'] = 10
            return True
        self.assertEqual(check_lodging(requirement, claim, claim_verifier=mutate)['state'], 'unknown')

    def test_unknown_identity_and_noncanonical_date_do_not_prove_a_quote(self):
        for field, value in (('entity_id', 'unresolved_id'), ('room_type', 'unknown'),
                             ('check_in', '20261101')):
            with self.subTest(field=field):
                requirement, claim = inputs()
                requirement[field] = claim[field] = value
                out = check_lodging(requirement, claim, claim_verifier=lambda *_: True)
                self.assertEqual(out['state'], 'unknown')

    def test_verifier_cannot_modify_room_count(self):
        r,c=inputs()
        def mutate(req,_claim):
            req['rooms']=1
            return True
        self.assertEqual(check_lodging(r,c,claim_verifier=mutate)['state'],'unknown')
        self.assertEqual(r['rooms'],2)
    def test_valid_scoped_quote_uses_room_nights(self):
        r,c=inputs();out=check_lodging(r,c,claim_verifier=lambda *_:True)
        self.assertEqual(out['total_cny'],1600)
        self.assertEqual(out['state'],'pass')
        self.assertFalse(out['execution_confirmed'])

    def test_mismatch_room_date_and_unit_remain_unknown(self):
        for key,value in [('room_type','king'),('check_out','2026-11-04'),('unit','CNY/room/day'),
                          ('eligibility','conference'),('meal_plan','breakfast'),('taxes_included',False)]:
            r,c=inputs();c[key]=value
            self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['state'],'unknown')

    def test_price_excluding_mandatory_charges_is_not_complete(self):
        r,c=inputs();r['taxes_included']=c['taxes_included']=False
        self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['reason'],'mandatory_charges_not_included')

    def test_no_verifier_or_unknown_price_is_not_free(self):
        r,c=inputs()
        self.assertEqual(check_lodging(r,c)['state'],'unknown')
        c['rate']=None
        self.assertIsNone(check_lodging(r,c,claim_verifier=lambda *_:True)['total_cny'])

    def test_same_room_bed_shortfall_is_a_hard_failure(self):
        r,c=inputs();c['beds']=1
        self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['state'],'fail')

    def test_scope_types_and_unknown_dimensions_fail_closed(self):
        for field, value in (('guests_per_room', True), ('taxes_included', 1),
                             ('mandatory_fees_included', 1)):
            with self.subTest(field=field):
                r,c=inputs()
                if field == 'guests_per_room':
                    r.update(guests_per_room=1, minimum_beds=1)
                    c['guests_per_room'] = value
                else:
                    c[field] = value
                self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['state'],'unknown')

        r,c=inputs();r['accessible_room']=True;c['accessible_room']=False
        self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['reason'],
                         'lodging_scope_has_unsupported_fields')
        r,c=inputs();c['accessible_room']=False
        self.assertEqual(check_lodging(r,c,claim_verifier=lambda *_:True)['reason'],
                         'lodging_scope_has_unsupported_fields')

    def test_verifier_bool_to_int_mutation_is_detected_without_input_change(self):
        r,c=inputs()
        original_r,original_c=__import__('copy').deepcopy(r),__import__('copy').deepcopy(c)
        def mutate(_requirement,claim):
            claim['taxes_included']=1
            return True
        out=check_lodging(r,c,claim_verifier=mutate)
        self.assertEqual(out['state'],'unknown')
        self.assertEqual(r,original_r)
        self.assertEqual(c,original_c)


if __name__ == '__main__':
    unittest.main()
