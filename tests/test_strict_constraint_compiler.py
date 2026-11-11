import unittest
from decimal import Decimal
from shorttrip.strict_constraint_compiler import compile_constraint


class CompilerTests(unittest.TestCase):
    def test_unrecognized_constraint_fields_are_not_silently_discarded(self):
        constraint = {'id':'b','strength':'hard',
            'scope':{'currency':'CNY','people':1,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':100,'people':1,'includes':['tickets']}},
            'qualifier':'unmapped condition'}
        self.assertEqual(compile_constraint(constraint)['reason'], 'constraint_has_unsupported_fields')

    def test_unknown_constraint_identifier_is_not_compiled(self):
        constraint = {'id':'unknown', 'strength':'hard',
            'scope':{'currency':'CNY','people':1,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':100,'people':1,'includes':['tickets']}}}
        self.assertEqual(compile_constraint(constraint)['status'], 'unsupported')

    def test_budget_party_scope_does_not_coerce_bool_or_float(self):
        for people in (True, 1.0, Decimal('1')):
            constraint = {'id':'b','strength':'hard',
                'scope':{'currency':'CNY','people':people,'unit':'total_trip_cost'},
                'expression':{'op':'total_cost_at_most','args':{'CNY':100,'people':1,'includes':['tickets']}}}
            with self.subTest(people=people):
                self.assertEqual(compile_constraint(constraint)['status'], 'unsupported')

    def test_budget_compiles_only_exact_semantics(self):
        c={'id':'b','strength':'hard','scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
           'expression':{'op':'total_cost_at_most','args':{'CNY':6000,'people':2,'includes':['meals','rooms']}},
           'compiler_status':'unmapped'}
        out=compile_constraint(c)
        self.assertEqual(out['status'],'supported')
        self.assertFalse(out['natural_language_equivalence_verified'])
        self.assertEqual(c['compiler_status'],'unmapped')
        c['scope']['people']=3
        self.assertEqual(compile_constraint(c)['status'],'unsupported')

    def test_negation_any_and_bad_strength_rejected(self):
        c={'id':'n','strength':'hard','scope':{'domain':'trip','quantifier':'any'},
           'expression':{'op':'exclude_tag','args':{'tag':'night'}}}
        self.assertEqual(compile_constraint(c)['reason'],'trip_exclusion_requires_all')
        c['scope']['quantifier']='all'
        self.assertEqual(compile_constraint(c)['status'],'supported')
        c['strength']='soft'
        self.assertEqual(compile_constraint(c)['status'],'unsupported')

    def test_optional_item_kind_scope_is_supported_only_for_known_kinds(self):
        c={'id':'food','strength':'soft','scope':{'domain':'trip','quantifier':'any',
             'item_kind':'restaurant'},
           'expression':{'op':'prefer_tag','args':{'tag':'local_food'}},
           'compiler_status':'unmapped'}
        out=compile_constraint(c)
        self.assertEqual(out['status'],'supported')
        self.assertFalse(out['natural_language_equivalence_verified'])
        self.assertEqual(c['compiler_status'],'unmapped')
        c['scope']['item_kind']='unknown_kind'
        self.assertEqual(compile_constraint(c)['reason'],'tag_scope_item_kind_invalid')

    def test_unknown_operator_is_not_promoted(self):
        self.assertEqual(compile_constraint({'id':'x','strength':'hard','scope':{},
            'expression':{'op':'implies','args':{}}})['status'],'unsupported')


if __name__ == '__main__':
    unittest.main()
