import importlib,json,unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import patch

class ConstraintCompilerTests(unittest.TestCase):
    def module(self):return importlib.import_module('chinatravel.agent.nesy_agent.constraint_compiler')
    def query(self):return dict(days=2,people_number=4,target_city='深圳',start_city='广州',nature_language='我们四个人从广州去深圳两天，市内只坐地铁。')
    def test_templates_need_no_model_and_preserve_metro_restriction(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        q=self.query();q['hard_logic']=['days==2','people_number==4','tickets==4',"transport_type<={'metro'}",'taxi_cars==1']
        def llm(*a,**kw):self.fail('Common constraints must not need model-generated Python')
        result=m.nl2sl_step2(q,llm)
        self.assertEqual(m.check(result)[0],[])
        self.assertIn("{'metro'}",result['hard_logic_py'][3])
        self.assertIn('metro_tickets(activity_transports(activity))',result['hard_logic_py'][2])
    def test_named_entities_compile_position_not_type(self):
        c=self.module()
        for text in ("{'富春山居号游船'}<=attraction_names","{'久久日本料理'}<=restaurant_names"):
            code=c.compile_constraint(text)
            self.assertIn('activity_position(activity)',code)
            self.assertNotIn('attraction_type(',code);self.assertNotIn('restaurant_type(',code)
    def test_budget_is_whole_plan_total_without_people_multiplier(self):
        from chinatravel.symbol_verification.concept_func import func_dict
        from chinatravel.agent.nesy_agent.translation_contract import check_constraint
        code=self.module().compile_constraint('cost<=3000')
        v=deepcopy(func_dict);v['plan']=dict(people_number=2,itinerary=[dict(activities=[dict(cost=1000,transports=[dict(mode='taxi',cost=20)]),dict(cost=1900,transports=[])])])
        check_constraint(code,v);self.assertTrue(v['result'])
        v['plan']['itinerary'][0]['activities'][1]['cost']=2000
        check_constraint(code,v);self.assertFalse(v['result'])
    def test_invented_budget_and_rooms_are_rejected(self):
        c=self.module();q=self.query()
        for expression in ('cost<=0','rooms==0','rooms==2'):
            parsed=dict(hard_logic=[expression],hard_logic_evidence=[dict(constraint=expression,source=q['nature_language'])])
            with self.subTest(expression=expression),self.assertRaises(ValueError):c.validate_extraction(q,parsed)
    def test_non_derived_requirement_needs_verbatim_evidence(self):
        q=self.query();q['nature_language']='两人去武汉，预算3000元';q['people_number']=2
        e='cost<=3000'
        with self.assertRaises(ValueError):self.module().validate_extraction(q,dict(hard_logic=['cost<=2999']))
        out=self.module().validate_extraction(q,dict(hard_logic=[e],hard_logic_evidence=[dict(constraint=e,source='预算3000元')]))
        self.assertIn(e,out['hard_logic'])
    def test_name_misclassified_as_cuisine_rejected_with_specific_feedback(self):
        q=self.query();q.update(target_city='重庆',nature_language='想吃久久日本料理')
        e="{'久久日本料理'}<=food_type"
        with self.assertRaisesRegex(ValueError,'restaurant_names'):
            self.module().validate_extraction(q,dict(hard_logic=[e],hard_logic_evidence=[dict(constraint=e,source='久久日本料理')]))
    def test_stage_one_retries_extraction_instead_of_repairing_wrong_code(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        q=self.query();calls=[]
        def llm(messages,**kw):
            calls.append(messages)
            return json.dumps(dict(hard_logic=['rooms==2'] if len(calls)==1 else ['days==2','people_number==4',"transport_type<={'metro'}"]))
        result=m.nl2sl_step1(q,llm)
        self.assertEqual(len(calls),2);self.assertNotIn('rooms==2',result['hard_logic'])
    def test_parameter_error_feedback_identifies_function_constraint_and_program(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        q=self.query();q['hard_logic']=['custom_check'];q['hard_logic_py']=["result=True\nfor activity in allactivities(plan):\n  for leg in activity_transports(activity):\n    if leg['mode']=='metro' and metro_tickets(leg)!=4: result=False"]
        errors,_=m.check(q)
        self.assertIn('metro_tickets',errors[0]);self.assertIn('custom_check',errors[0]);self.assertIn('list',errors[0])

    def test_mixed_standard_and_complex_program_keeps_standard_templates(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        q=self.query();q['hard_logic']=['people_number==4','custom_check']
        def llm(*args,**kw):return json.dumps({'hard_logic_py':['result=(people_count(plan)==99)','result=(day_count(plan)>0)']})
        result=m.nl2sl_step2(q,llm)
        self.assertEqual(result['hard_logic_py'][0],'result=(people_count(plan)==4)')
        self.assertEqual(result['translation_program_sources'],['template','model'])

    def test_room_count_is_not_inferred_from_traveller_count_even_with_quote(self):
        c=self.module();q=self.query();q['nature_language']='我们四个人旅行两天'
        e='rooms==4'
        with self.assertRaises(ValueError):c.validate_extraction(q,dict(hard_logic=[e],hard_logic_evidence=[dict(constraint=e,source='我们四个人')]))

    def test_explicit_chinese_room_count_and_bed_type_are_allowed(self):
        q=self.query();q['nature_language']='开一间双床房'
        parsed=dict(hard_logic=['rooms==1','room_type==2'],hard_logic_evidence=[dict(constraint=e,source=q['nature_language']) for e in ['rooms==1','room_type==2']])
        self.assertTrue(set(parsed['hard_logic'])<=set(self.module().validate_extraction(q,parsed)['hard_logic']))

    def test_evidence_numbers_respect_units_and_english_room_counts(self):
        c=self.module()
        self.assertFalse(c._number_present(1,'预算1万元'))
        self.assertTrue(c._number_present(10000,'预算1万元'))
        self.assertTrue(c._number_present(1,'one room'))

    def test_old_cache_cannot_bypass_source_grounding(self):
        from chinatravel.agent.nesy_agent.nesy_agent import NesyAgent
        with tempfile.TemporaryDirectory() as folder:
            a=NesyAgent.__new__(NesyAgent);a.cache_dir=folder;a.lang='zh';a.backbone_llm=SimpleNamespace(name='stub')
            q=self.query();q.update(uid='cached',hard_logic=['cost<=0'],hard_logic_py=['result=(people_count(plan)>0)'])
            p=Path(folder)/'translation_stub_reflect/cached.json';p.parent.mkdir();p.write_text(json.dumps(q),encoding='utf-8')
            with self.assertRaises(ValueError):a.translate_nl2sl(q,load_cache=True)

    def test_grounded_failed_case_requirements_compile_end_to_end_without_python_calls(self):
        from chinatravel.agent.nesy_agent import nl2sl_hybrid as m
        cases=[
            ('重庆','杭州',3,1,'从重庆到杭州三天，想去富春山居号游船',"{'富春山居号游船'}<=attraction_names",'富春山居号游船'),
            ('广州','重庆',2,1,'广州去重庆两天，想吃久久日本料理',"{'久久日本料理'}<=restaurant_names",'久久日本料理'),
            ('成都','武汉',3,2,'两人从成都去武汉三天，预算3000元，希望参观武汉大学','cost<=3000','预算3000元')]
        for start,target,days,people,text,extra,quote in cases:
            with self.subTest(target=target,extra=extra):
                q=dict(start_city=start,target_city=target,days=days,people_number=people,nature_language=text)
                codes=[f'days=={days}',f'people_number=={people}',f'tickets=={people}','taxi_cars==1',extra]
                parsed=dict(hard_logic=codes,hard_logic_evidence=[dict(constraint=extra,source=quote)])
                if '武汉大学' in text:
                    parsed['hard_logic'].append("{'武汉大学'}<=attraction_names")
                calls=[]
                def llm(*args,**kwargs):
                    calls.append(args)
                    self.assertEqual(len(calls),1,'Only extraction should use the LLM for standard constraints')
                    return json.dumps(parsed,ensure_ascii=False)
                result=m.nl2sl_reflect(q,llm)
                self.assertEqual(result['translation_program_sources'],['template']*len(result['hard_logic']))
                self.assertEqual(result['reflect_cnt'],0)

if __name__=='__main__':unittest.main()
