import json
import unittest
from shorttrip.strict_constraints import evaluate_constraint


class StrictConstraintTests(unittest.TestCase):
    def test_unknown_destination_or_count_kind_cannot_pass(self):
        arrival = {'strength':'hard','expression':{'op':'arrive_by','args':
                   {'day':1,'destination':'待核验','time':'19:00'}}}
        fact = {'value':'18:00','unit':'local_time','context':{'day':1,'destination':'待核验'}}
        self.assertEqual(evaluate_constraint(arrival, fact, fact_verifier=lambda *_: True)['state'], 'unknown')
        count = {'strength':'hard','expression':{'op':'count_at_least','args':
                 {'kind':'unknown','count':1}}}
        fact = {'value':1,'unit':'count','context':{'kind':'unknown'}}
        self.assertEqual(evaluate_constraint(count, fact, fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_arrival_requires_ascii_clock_and_type_exact_day_context(self):
        constraint = {'strength':'hard','expression':{'op':'arrive_by','args':
                      {'day':1,'destination':'hotel','time':'19:00'}}}
        fact = {'value':'18:00','unit':'local_time','context':{'day':True,'destination':'hotel'}}
        self.assertEqual(evaluate_constraint(constraint, fact, fact_verifier=lambda *_: True)['state'], 'unknown')
        fact['context']['day'] = 1
        for clock in ('１８:００', '1 :00'):
            fact['value'] = clock
            with self.subTest(clock=clock):
                self.assertEqual(evaluate_constraint(constraint, fact, fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_count_scope_does_not_coerce_boolean_to_integer(self):
        constraint = {'strength':'hard','expression':{'op':'count_at_least','args':
                      {'day':1,'kind':'restaurant','count':1}}}
        fact = {'value':1,'unit':'count','context':{'day':True,'kind':'restaurant'}}
        self.assertEqual(evaluate_constraint(constraint, fact, fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_json_float_with_lost_money_lexeme_is_unknown(self):
        source_token = "1.0000000000000001"
        value = json.loads(source_token)
        constraint = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
            {'CNY': 1, 'people': 1, 'includes': ['tickets']}}}
        fact = {'value': value, 'unit': 'CNY',
                'context': {'people': 1, 'includes': ['tickets']}}

        result = evaluate_constraint(constraint, fact, fact_verifier=lambda *_: True)

        self.assertEqual(value, 1.0)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['reason'], 'cost_value_invalid')

    def test_raw_decimal_text_compares_exactly_and_float_limit_is_rejected(self):
        constraint = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
            {'CNY': '0.1', 'people': 1, 'includes': ['tickets']}}}
        fact = {'value': '0.100000000000000005', 'unit': 'CNY',
                'context': {'people': 1, 'includes': ['tickets']}}

        result = evaluate_constraint(constraint, fact, fact_verifier=lambda *_: True)

        self.assertEqual(result['state'], 'fail')
        self.assertEqual(result['reason'], 'verified_cost_comparison')

        float_limit = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
            {'CNY': 0.1, 'people': 1, 'includes': ['tickets']}}}
        at_limit = {'value': '0.1', 'unit': 'CNY',
                    'context': {'people': 1, 'includes': ['tickets']}}
        rejected = evaluate_constraint(float_limit, at_limit,
                                       fact_verifier=lambda *_: True)
        self.assertEqual(rejected['state'], 'unknown')
        self.assertEqual(rejected['reason'], 'cost_value_invalid')

    def test_fact_verifier_cannot_change_original_and_copy_together(self):
        constraint = {'strength':'hard','expression':{'op':'total_cost_at_most','args':
            {'CNY':100,'people':2,'includes':['rooms']}}}
        fact = {'value':200,'unit':'CNY','context':{'people':2,'includes':['rooms']}}
        def mutate(_constraint_copy, fact_copy):
            fact['value'] = fact_copy['value'] = 1
            return True
        self.assertEqual(evaluate_constraint(constraint, fact, fact_verifier=mutate)['state'], 'unknown')

    def test_verifier_cannot_replace_cost_fact(self):
        c={'strength':'hard','expression':{'op':'total_cost_at_most','args':
           {'CNY':100,'people':2,'includes':['rooms']}}}
        f={'value':200,'unit':'CNY','context':{'people':2,'includes':['rooms']}}
        def mutate(_c, fact):
            fact['value']=1
            return True
        self.assertEqual(evaluate_constraint(c,f,fact_verifier=mutate)['state'],'unknown')
        self.assertEqual(f['value'],200)

    def test_verifier_bool_int_mutation_is_detected_and_input_is_unchanged(self):
        c = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
             {'CNY': 10, 'people': 1, 'includes': ['rooms']}}}
        f = {'value': 5, 'unit': 'CNY',
             'context': {'people': 1, 'includes': ['rooms']}}

        def change_people_type(_constraint, fact):
            fact['context']['people'] = True
            return True

        out = evaluate_constraint(c, f, fact_verifier=change_people_type)
        self.assertEqual(out['state'], 'unknown')
        self.assertEqual(f['context']['people'], 1)
        f['context']['people'] = True
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_cyclic_and_deep_verifier_facts_fail_closed_without_mutating_input(self):
        c = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
             {'CNY': 10, 'people': 1, 'includes': ['rooms']}}}
        f = {'value': 5, 'unit': 'CNY',
             'context': {'people': 1, 'includes': ['rooms']}}
        cycle = {}
        cycle['self'] = cycle
        f['opaque'] = cycle
        out = evaluate_constraint(c, f, fact_verifier=lambda *_: True)
        self.assertEqual(out['state'], 'unknown')
        self.assertIs(f['opaque']['self'], f['opaque'])

        nested = []
        cursor = nested
        for _ in range(300):
            child = []
            cursor.append(child)
            cursor = child
        f['opaque'] = nested
        out = evaluate_constraint(c, f, fact_verifier=lambda *_: True)
        self.assertEqual(out['state'], 'unknown')
        self.assertEqual(len(nested[0][0]), 1)
    def test_budget_requires_all_explicit_components_and_verified_fact(self):
        c = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
             {'CNY': 300, 'people': 2, 'includes': ['rooms', 'fare']}}}
        f = {'value': 350, 'unit': 'CNY', 'context': {'people': 2, 'includes': ['fare', 'rooms']}}
        self.assertEqual(evaluate_constraint(c, f)['state'], 'unknown')
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'fail')
        f['context']['includes'] = ['rooms']
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_count_and_arrival_use_exact_scope(self):
        c = {'strength': 'hard', 'expression': {'op': 'count_at_least', 'args':
             {'kind': 'restaurant', 'cuisine': 'local', 'count': 1}}}
        f = {'value': 1, 'unit': 'count', 'context': {'kind': 'restaurant', 'cuisine': 'other'}}
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'unknown')
        f['context']['cuisine'] = 'local'
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'pass')
        c = {'strength': 'hard', 'expression': {'op': 'arrive_by', 'args':
             {'day': 2, 'destination': 'hotel', 'time': '19:00'}}}
        f = {'value': '19:01', 'unit': 'local_time', 'context': {'day': 2, 'destination': 'hotel'}}
        self.assertEqual(evaluate_constraint(c, f, fact_verifier=lambda *_: True)['state'], 'fail')

    def test_unrecognized_operator_arguments_do_not_allow_false_passes(self):
        arrival = {'strength': 'hard', 'expression': {'op': 'arrive_by', 'args':
                   {'day': 1, 'destination': 'hotel', 'time': '18:00',
                    'timezone': 'Asia/Shanghai'}}}
        local_arrival = {'value': '17:00', 'unit': 'local_time',
                         'context': {'day': 1, 'destination': 'hotel'}}
        self.assertEqual(evaluate_constraint(arrival, local_arrival,
            fact_verifier=lambda *_: True)['state'], 'unknown')

        budget = {'strength': 'hard', 'expression': {'op': 'total_cost_at_most', 'args':
                  {'CNY': 500, 'people': 2, 'includes': ['rooms'],
                   'taxes_included': True}}}
        room_cost = {'value': 300, 'unit': 'CNY',
                     'context': {'people': 2, 'includes': ['rooms']}}
        self.assertEqual(evaluate_constraint(budget, room_cost,
            fact_verifier=lambda *_: True)['state'], 'unknown')

    def test_unsupported_soft_and_bad_values_remain_unknown(self):
        self.assertEqual(evaluate_constraint({'strength': 'hard', 'expression': {'op': 'implies', 'args': {}}},
                                             {}, fact_verifier=lambda *_: True)['reason'], 'operator_unsupported')
        c = {'strength': 'soft', 'expression': {'op': 'count_at_least', 'args': {}}}
        self.assertEqual(evaluate_constraint(c, {}, fact_verifier=lambda *_: True)['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
