import importlib,json,unittest
from copy import deepcopy
from types import SimpleNamespace

class AlignmentTests(unittest.TestCase):
    def module(self):return importlib.import_module('chinatravel.agent.nesy_agent.extraction_alignment')
    def query(self,text='两个人去杭州玩两天，预算2000元，参观浙江大学和西湖，来回高铁(G)'):
        return dict(days=2,people_number=2,start_city='苏州',target_city='杭州',nature_language=text)
    def test_derived_constraints_are_always_present(self):
        s=self.module().ExtractionState(self.query('两个人去杭州玩两天'))
        result=s.accept({'hard_logic':[]})
        self.assertEqual(set(result['hard_logic']),{'days==2','people_number==2','tickets==2','taxi_cars==1'})
    def test_explicit_requirements_cannot_disappear(self):
        with self.assertRaisesRegex(ValueError,'Missing|missing'):
            self.module().ExtractionState(self.query()).accept({'hard_logic':[]})
    def test_database_aliases_and_campus_alternatives(self):
        s=self.module().ExtractionState(self.query('去杭州参观浙江大学和西湖'))
        result=s.accept({'hard_logic':["{'浙江大学','西湖'}<=attraction_names"]})
        code='\n'.join(result['hard_logic'])
        self.assertIn('玉泉校区',code);self.assertIn('之江校区',code)
        self.assertIn(' or ',code);self.assertIn('西湖风景名胜区',code)
    def test_abbreviated_boat_and_type_normalize_from_database(self):
        q=self.query('去杭州参观富春山居号游船和博物馆')
        result=self.module().ExtractionState(q).accept({'hard_logic':["{'富春山居号'}<=attraction_names","{'博物馆'}<=spot_type"]})
        self.assertIn("{'富春山居号游船'}<=attraction_names",result['hard_logic'])
        self.assertIn("{'博物馆/纪念馆'}<=spot_type",result['hard_logic'])
    def test_validated_budget_is_locked_across_corrections(self):
        s=self.module().ExtractionState(self.query('预算2000元去杭州参观西湖'))
        with self.assertRaises(ValueError):s.accept({'hard_logic':['cost<=2000']})
        result=s.accept({'hard_logic':["{'西湖'}<=attraction_names"]})
        self.assertIn('cost<=2000',result['hard_logic'])
    def test_unresolved_ambiguity_is_not_arbitrarily_selected(self):
        m=self.module()
        with self.assertRaisesRegex(ValueError,'ambiguous|Ambiguous'):
            m.resolve_name('华府','hotel_names',{'hotel_names':{'华府A店','华府B店'}})
    def test_return_time_and_G_prefix_programs_accept_and_reject(self):
        from chinatravel.agent.nesy_agent.constraint_compiler import compile_constraint
        from chinatravel.agent.nesy_agent.translation_contract import check_constraint
        from chinatravel.symbol_verification.concept_func import func_dict
        for code,field,good,bad in [('return_start_time<=\'19:00\'','start_time','19:00','19:01'),("train_type=={'G'}",'TrainID','G123','D123')]:
            program=compile_constraint(code);self.assertIsNotNone(program)
            plan=dict(target_city='杭州',itinerary=[dict(activities=[dict(type='train',start='杭州东站',end='苏州站',start_time='19:00',TrainID='G123')])])
            for value,want in [(good,True),(bad,False)]:
                variables=deepcopy(func_dict);variables['plan']=deepcopy(plan)
                variables['plan']['itinerary'][0]['activities'][0][field]=value
                check_constraint(program,variables);self.assertEqual(bool(variables['result']),want)
    def test_alternative_campus_template_does_not_require_both(self):
        from chinatravel.agent.nesy_agent.constraint_compiler import compile_constraint
        from chinatravel.agent.nesy_agent.translation_contract import check_constraint
        from chinatravel.symbol_verification.concept_func import func_dict
        program=compile_constraint("({'浙江大学(玉泉校区)'}<=attraction_names or {'浙江大学(之江校区)'}<=attraction_names)")
        self.assertIsNotNone(program)
        for name,want in [('浙江大学(玉泉校区)',True),('浙江大学(之江校区)',True),('西湖风景名胜区',False)]:
            v=deepcopy(func_dict);v['plan']={'itinerary':[{'activities':[dict(type='attraction',position=name)]}]}
            check_constraint(program,v);self.assertEqual(bool(v['result']),want)
    def test_no_hardening_of_food_wish_or_negated_attraction(self):
        q=self.query('去杭州玩两天，不去西湖，尽可能多体验当地美食')
        result=self.module().ExtractionState(q).accept({'hard_logic':[]})
        self.assertFalse(any('food_type' in c or '西湖' in c for c in result['hard_logic']))
    def test_unseen_budget_and_explicit_deadline_coverage(self):
        s=self.module().ExtractionState(self.query('预算4800元，返程不晚于17:30上火车'))
        with self.assertRaisesRegex(ValueError,'4800|17:30'):s.accept({'hard_logic':[]})
        result=s.accept({'hard_logic':['cost<=4800',"intercity_transport=={'train'}","return_start_time<='17:30'"]})
        self.assertIn("return_start_time<='17:30'",result['hard_logic'])
    def test_city_lookup_does_not_depend_on_global_execution_language(self):
        from chinatravel.symbol_verification import concept_func as c
        from chinatravel.agent.nesy_agent.constraint_compiler import _catalog
        old=c._current_lang
        try:
            c.set_concept_func_lang('en')
            self.assertIn('武汉大学',_catalog('武汉')['attraction_names'])
        finally:c.set_concept_func_lang(old)
    def test_code_repair_cannot_overwrite_an_already_valid_complex_program(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        q=self.query('去杭州两天');q['hard_logic']=['custom_one','custom_two']
        original='result=(day_count(plan)==2)'
        q['hard_logic_py']=[original,"{'bad':'program'}"]
        def llm(*args,**kwargs):return json.dumps({'hard_logic_py':['result=(day_count(plan)==99)','result=(people_count(plan)==2)']})
        result=m.nl2sl_step3(q,llm,SimpleNamespace(check=lambda c:([],[])),max_trails=1)
        self.assertEqual(result['hard_logic_py'][0],original)
if __name__=='__main__':unittest.main()
