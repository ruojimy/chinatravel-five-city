import copy
import importlib
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TranslationContractTests(unittest.TestCase):
    def modules(self):
        return [importlib.import_module('chinatravel.agent.nesy_agent.'+name)
                for name in ('nl2sl_hybrid','nl2sl_hybrid_en')]

    def query(self):
        return dict(days=2,people_number=2,start_city='南京',target_city='重庆',
                    nature_language='南京到重庆，两人两天，火车。',hard_logic=['days==2'])

    def test_itinerary_dict_and_expression_cannot_pass_execution_check(self):
        for module in self.modules():
            for code in ("{'type':'train','position':'南京 - 重庆'}",'day_count(plan)==2',
                         'result=1','result=True',"result={'type':'train'}"):
                with self.subTest(module=module.__name__,code=code):
                    q=self.query();q['hard_logic_py']=[code]
                    self.assertTrue(module.check(q)[0])

    def test_valid_false_is_not_a_translation_error(self):
        for module in self.modules():
            q=self.query();q['hard_logic_py']=['result=(day_count(plan)==99)']
            self.assertEqual(module.check(q)[0],[])

    def test_parse_strings_without_splitting_brackets_inside_code(self):
        code="result=(activity_type(allactivities(plan)[0]) in ['train', 'airplane'])"
        for module in self.modules():
            q=self.query();q['hard_logic']=['custom_check']
            def llm(messages,**kwargs):return json.dumps({'hard_logic_py':[code]})
            self.assertEqual(module.nl2sl_step2(q,llm)['hard_logic_py'],[code])

    def test_bad_output_is_repaired_before_search(self):
        for module in self.modules():
            q=self.query();q['hard_logic_py']=["{'type':'train'}"]
            def llm(messages,**kwargs):return json.dumps({'hard_logic_py':['result=(day_count(plan)==2)']})
            checker=SimpleNamespace(check=lambda c:([],[]))
            result=module.nl2sl_step3(q,llm,checker,max_trails=1)
            self.assertEqual(result['hard_logic_py'],['result=(day_count(plan)==2)'])

    def test_missing_or_extra_program_requires_repair(self):
        for module in self.modules():
            q=self.query();q['hard_logic_py']=['result=(day_count(plan)==2)','result=(people_count(plan)==2)']
            self.assertTrue(module.check(q)[0])

    def test_local_qwen_request_schema_enforces_one_string_per_constraint(self):
        for module in self.modules():
            class LLM:
                _client_kwargs={'base_url':'http://127.0.0.1:18080/v1'}
                def __call__(self,messages,**kwargs):
                    self.kwargs=kwargs
                    return json.dumps({'hard_logic_py':['result=(day_count(plan)==2)']})
            q=self.query();q['hard_logic']=['custom_check']
            llm=LLM();module.nl2sl_step2(q,llm)
            fmt=llm.kwargs.get('response_format',{})
            self.assertEqual(fmt.get('type'),'json_schema')
            schema=fmt['json_schema']['schema']['properties']['hard_logic_py']
            self.assertEqual((schema['minItems'],schema['maxItems']),(1,1))

    def test_persistent_bad_output_raises_instead_of_dropping_constraints(self):
        for module in self.modules():
            for codes in ([],["{'type':'train'}"],[{'type':'train'}]):
                with self.subTest(module=module.__name__,codes=codes):
                    q=self.query();q['hard_logic_py']=copy.deepcopy(codes)
                    checker=SimpleNamespace(check=lambda c:([],[]))
                    def llm(messages,**kwargs):return json.dumps([{'type':'train'}])
                    with self.assertRaisesRegex(ValueError,'translation|Translation'):
                        module.nl2sl_step3(q,llm,checker,max_trails=1)

    def test_stage_one_does_not_silently_accept_empty_constraints(self):
        for module in self.modules():
            def llm(messages,**kwargs):return '{}'
            with self.assertRaisesRegex(ValueError,'translation|Translation'):
                module.nl2sl_step1(self.query(),llm)

    def test_default_repair_budget_is_three_calls(self):
        for module in self.modules():
            q=self.query();q['hard_logic']=['custom_check'];q['hard_logic_py']=["{'type':'train'}"]
            calls=[]
            def llm(messages,**kwargs):
                calls.append(messages)
                return json.dumps({'hard_logic_py':["{'type':'train'}"]})
            with self.assertRaises(ValueError):
                module.nl2sl_step3(q,llm,SimpleNamespace(check=lambda c:([],[])))
            self.assertEqual(len(calls),3)

    def test_english_checker_failure_is_not_silently_accepted(self):
        module=self.modules()[1]
        q=self.query();q.update(start_city='Nanjing',target_city='Chongqing',
                               hard_logic_py=['result=(day_count(plan)==2)'])
        with (patch.object(module,'nl2sl_step1',return_value=q),
              patch.object(module,'nl2sl_step2',return_value=q),
              patch.object(module,'HardLogicPyChecker',side_effect=RuntimeError('checker unavailable'))):
            with self.assertRaisesRegex(ValueError,'Translation'):
                module.nl2sl_reflect(q,None)

    def test_bad_cached_translation_is_rejected_at_agent_boundary(self):
        from chinatravel.agent.nesy_agent.nesy_agent import NesyAgent
        with tempfile.TemporaryDirectory() as folder:
            agent=NesyAgent.__new__(NesyAgent)
            agent.cache_dir=folder;agent.lang='zh'
            agent.backbone_llm=SimpleNamespace(name='stub')
            q=self.query();q['uid']='test';q['hard_logic_py']=["{'type':'train'}"]
            path=Path(folder)/'translation_stub_reflect'/'test.json'
            path.parent.mkdir();path.write_text(json.dumps(q),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'translation|Translation'):
                agent.translate_nl2sl(q,load_cache=True)

if __name__=='__main__':unittest.main()
