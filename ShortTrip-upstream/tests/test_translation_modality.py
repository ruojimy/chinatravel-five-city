import json
import os
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
os.chdir(PROJECT)

from chinatravel.agent.nesy_agent.extraction_alignment import ExtractionState, coverage, extract_with_repair, resolve_name
from chinatravel.agent.nesy_agent.constraint_compiler import _catalog
from chinatravel.agent.nesy_agent.translation_contract import TranslationValidationError


def query(text, city='北京'):
    return dict(start_city='上海',target_city=city,days=2,people_number=2,nature_language=text)


def parsed(code, source, soft=False):
    key='soft_logic' if soft else 'hard_logic'
    return {key:[code],key+'_evidence':[dict(constraint=code,source=source)],
            ('hard_logic' if soft else 'soft_logic'):[]}


class ModalityTest(unittest.TestCase):
    def test_intercity_set_inclusion_uses_a_deterministic_template(self):
        from copy import deepcopy
        from chinatravel.agent.nesy_agent.constraint_compiler import compile_constraint
        from chinatravel.agent.nesy_agent.translation_contract import check_constraint
        from chinatravel.symbol_verification.concept_func import func_dict
        program=compile_constraint("{'train'}<=intercity_transport")
        self.assertIsNotNone(program)
        for modes,expected in [(['train'],True),(['airplane'],False),(['train','airplane'],True)]:
            variables=deepcopy(func_dict)
            variables['plan']={'itinerary':[{'activities':[{'type':mode} for mode in modes]}]}
            check_constraint(program,variables)
            self.assertEqual(bool(variables['result']),expected)

    def test_evidence_spacing_recovers_the_actual_source_text(self):
        q=query('想去北京全聚德(前门店)吃饭。')
        code="{'北京全聚德 (前门店)'}<=restaurant_names"
        result=ExtractionState(q).accept(parsed(code,'北京全聚德 (前门店)'))
        canonical="{'北京全聚德(前门店)'}<=restaurant_names"
        self.assertIn(canonical,result['hard_logic'])
        evidence=next(e for e in result['hard_logic_evidence'] if e['constraint']==canonical)
        self.assertEqual(evidence['source'],'北京全聚德(前门店)')

    def test_english_museum_alias_is_grounded(self):
        q=query('We must visit museums.',city='Beijing')
        q['start_city']='Shanghai'
        code="{'Museum/Memorial Hall'}<=spot_type"
        result=ExtractionState(q).accept(parsed(code,'We must visit museums'))
        self.assertIn(code,result['hard_logic'])

    def test_category_cannot_use_an_unrelated_quote_as_evidence(self):
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('预算8000人民币。')).accept(dict(hard_logic=['cost<=8000',"{'北京菜'}<=food_type"],hard_logic_evidence=[dict(constraint='cost<=8000',source='预算8000'),dict(constraint="{'北京菜'}<=food_type",source='预算8000人民币')]))

    def test_number_elsewhere_in_sentence_is_not_a_budget(self):
        q=query('两个人预算8000元。')
        with self.assertRaises(TranslationValidationError):
            ExtractionState(q).accept(dict(hard_logic=['cost<=8000','cost<=2'],hard_logic_evidence=[dict(constraint=code,source=q['nature_language']) for code in ['cost<=8000','cost<=2']]))

    def test_name_spacing_is_normalized_without_guessing_a_different_place(self):
        result=resolve_name('北京全聚德 (前门店)','restaurant_names',{'restaurant_names':{'北京全聚德(前门店)'}})
        self.assertEqual(result,({'北京全聚德(前门店)'},False))

    def test_local_extraction_schema_requires_string_lists(self):
        from types import SimpleNamespace
        from chinatravel.agent.nesy_agent.translation_contract import extraction_output_options
        llm=SimpleNamespace(_client_kwargs=dict(base_url='http://127.0.0.1:18080/v1'))
        schema=extraction_output_options(llm)['response_format']['json_schema']['schema']
        for name in ['hard_logic','soft_logic']:
            self.assertEqual(schema['properties'][name]['items']['type'],'string')
        self.assertEqual(schema['properties']['hard_logic_evidence']['items']['properties']['source']['type'],'string')

    def test_postfix_preference_does_not_create_hard_coverage(self):
        for text in ['酒店有管家服务最好。','Use the subway as much as possible.','Book one room if possible.','Prefer a budget of 3000 yuan.']:
            with self.subTest(text=text):
                self.assertEqual(coverage(query(text),_catalog('北京')),[])

    def test_requirement_after_preference_is_still_hard(self):
        q=query('Prefer Butler Service and require one room.')
        self.assertIn('rooms==1',{e['code'] for e in coverage(q,_catalog('北京'))})

    def test_repeated_mention_keeps_later_hard_requirement(self):
        q=query('酒店最好有管家服务。酒店必须有管家服务。')
        payload=parsed("{'管家服务'}<=hotel_feature",'酒店必须有管家服务')
        payload.update(soft_logic=["{'管家服务'}<=hotel_feature"],soft_logic_evidence=[dict(constraint="{'管家服务'}<=hotel_feature",source='酒店最好有管家服务')])
        result=ExtractionState(q).accept(payload)
        self.assertIn("{'管家服务'}<=hotel_feature",result['hard_logic'])

    def test_exhibition_rooms_are_not_hotel_rooms(self):
        self.assertFalse(any(e['field']=='rooms' for e in coverage(query('参观三间展厅。'),_catalog('北京'))))

    def test_room_quantity_does_not_supply_a_bed_count(self):
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('开两间大床房。')).accept(dict(hard_logic=['rooms==2','room_type==1','room_type==2'],hard_logic_evidence=[dict(constraint=e,source='开两间大床房') for e in ['rooms==2','room_type==1','room_type==2']]))

    def test_short_quote_cannot_hide_soft_modifier(self):
        for text in ['酒店最好有管家服务。','酒店尽量有管家服务。','酒店优先选择有管家服务的。']:
            with self.subTest(text=text), self.assertRaises(TranslationValidationError):
                ExtractionState(query(text)).accept(parsed("{'管家服务'}<=hotel_feature",'管家服务'))

    def test_explicit_hotel_requirement_remains_hard(self):
        result=ExtractionState(query('酒店必须有管家服务。')).accept(parsed("{'管家服务'}<=hotel_feature",'管家服务'))
        self.assertIn("{'管家服务'}<=hotel_feature",result['hard_logic'])

    def test_preference_is_preserved(self):
        result=ExtractionState(query('酒店最好有管家服务。')).accept(parsed("{'管家服务'}<=hotel_feature",'酒店最好有管家服务',True))
        self.assertEqual(result['soft_logic'],["{'管家服务'}<=hotel_feature"])
        self.assertNotIn("{'管家服务'}<=hotel_feature",result['hard_logic'])

    def test_missing_preference_is_detected(self):
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('酒店最好有管家服务。')).accept(dict(hard_logic=[]))

    def test_mainly_metro_is_not_exclusive(self):
        q=query('市内主要使用地铁。')
        self.assertFalse(any(e['field']=='transport_type' for e in coverage(q,_catalog('北京'))))
        with self.assertRaises(TranslationValidationError):
            ExtractionState(q).accept(parsed("transport_type<={'metro'}",'地铁'))

    def test_only_metro_remains_hard(self):
        result=ExtractionState(query('市内只能坐地铁。')).accept(parsed("transport_type<={'metro'}",'地铁'))
        self.assertIn("transport_type<={'metro'}",result['hard_logic'])

    def test_room_count_and_bed_coverage(self):
        for text,codes in [('开三间大床房。',{'rooms==3','room_type==1'}),
                           ('开一间房。',{'rooms==1'}),('住大床房。',{'room_type==1'}),
                           ('住两间双床房。',{'rooms==2','room_type==2'})]:
            with self.subTest(text=text):
                actual={e['code'] for e in coverage(query(text),_catalog('北京'))}
                self.assertTrue(codes<=actual,(codes,actual))

    def test_missing_room_count_is_rejected(self):
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('开一间房。')).accept(dict(hard_logic=[]))

    def test_occupancy_does_not_imply_two_beds(self):
        entries=coverage(query('住一间酒店，双人间就行。'),_catalog('北京'))
        self.assertFalse(any(e['field']=='room_type' for e in entries))
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('住一间酒店，双人间就行。')).accept(parsed('room_type==2','双人间'))

    def test_negated_mode_is_not_a_positive_requirement(self):
        for text,source in [('不坐地铁。','地铁'),('You must not take the metro.','metro')]:
            with self.subTest(text=text), self.assertRaises(TranslationValidationError):
                ExtractionState(query(text)).accept(parsed("transport_type<={'metro'}",source))

    def test_hard_cannot_be_placed_in_soft_list(self):
        with self.assertRaises(TranslationValidationError):
            ExtractionState(query('酒店必须有管家服务。')).accept(parsed("{'管家服务'}<=hotel_feature",'管家服务',True))

    def test_english_preference_and_hard_room(self):
        q=query('Prefer a hotel with Butler Service. Book one twin room.',city='Beijing')
        q['start_city']='Shanghai'
        entries=coverage(q,_catalog('Beijing'))
        self.assertTrue({'rooms==1','room_type==2'}<={e['code'] for e in entries})
        with self.assertRaises(TranslationValidationError):
            ExtractionState(q).accept(parsed("{'Butler Service'}<=hotel_feature",'Butler Service'))

    def test_soft_fields_survive_normal_entry(self):
        payload=parsed("{'管家服务'}<=hotel_feature",'酒店最好有管家服务',True)
        def model(*args,**kwargs):
            return json.dumps(payload,ensure_ascii=False)
        result=extract_with_repair(query('酒店最好有管家服务。'),model,'test')
        self.assertEqual(result['soft_logic'],payload['soft_logic'])


if __name__=='__main__':
    unittest.main()
