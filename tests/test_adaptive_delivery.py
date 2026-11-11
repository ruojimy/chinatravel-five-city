import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shorttrip.adaptive_delivery import (normalized_stage, stage_instruction, prioritize_tasks,
    canonical_id, evidence_view, rank_candidates, repair_anchors, revision_locks, evaluate_delivery,select_diverse)


class AdaptiveTests(unittest.TestCase):
    def test_dynamic_mapping_dispatches_real_instruction(self):
        self.assertEqual(normalized_stage('dynamic'), normalized_stage('dynamic_first'))
        self.assertIn('动态证据', stage_instruction('dynamic_first'))

    def test_weather_combines_dates_not_cities(self):
        tasks = [{'provider':'amap','kind':'weather','context':{'city':city,'travel_date':day},'covers':[city+day]}
                 for city in ('长沙','厦门') for day in ('2026-10-24','2026-10-25')]
        r=prioritize_tasks(tasks,budget=2)
        self.assertEqual(len(r['selected']),2)
        self.assertEqual(len(r['covered_fields']),4)

    def test_route_direction_and_departure_never_deduplicated(self):
        ctx={'origin':[1,2],'destination':[3,4],'departure_at':'2026-10-24T13:00:00+08:00','mode':'metro','coord_system':'GCJ02'}
        tasks=[]
        for i,c in enumerate((ctx,{**ctx,'origin':[3,4],'destination':[1,2]}, {**ctx,'departure_at':'2026-10-24T16:00:00+08:00'})):
            tasks.append({'kind':'route','provider':'amap','context':c,'covers':[str(i)]})
        self.assertEqual(prioritize_tasks(tasks,budget=3)['grouped_tasks'],3)

    def test_pause_needs_explicit_recovery(self):
        task={'provider':'amap','kind':'weather','context':{'city':'长沙'},'covers':['weather']}
        self.assertFalse(prioritize_tasks([task],budget=1,paused=['amap'])['selected'])
        self.assertTrue(prioritize_tasks([task],budget=1,paused=['amap'],recovered=['amap'])['selected'])

    def test_value_per_call_prioritizes_blocking_bundle(self):
        tasks=[{'provider':'web','kind':'operator','entity_id':'A','covers':['price','hours'],'field_weights':{'price':5,'hours':5}},
               {'provider':'web','kind':'operator','entity_id':'B','covers':['photo']}]
        self.assertEqual(prioritize_tasks(tasks,budget=1)['selected'][0]['entity_id'],'A')

    def test_shared_operator_page_covers_explicit_visit_group(self):
        tasks=[{'provider':'web','kind':'operator','entity_id':e,'resource_id':'one-official-page','covers':[e+':price']}
               for e in ('main-complex','inside-museum')]
        r=prioritize_tasks(tasks,budget=1)
        self.assertEqual(r['request_units'],1)
        self.assertEqual(len(r['covered_fields']),2)

    def test_diverse_selection_skips_second_name_for_same_visit(self):
        ranked=[{'entity_id':'a','visit_group_id':'one'},{'entity_id':'b','visit_group_id':'one'},{'entity_id':'c','visit_group_id':'two'}]
        self.assertEqual([x['entity_id'] for x in select_diverse(ranked,2)],['a','c'])

    def claim(self):
        raw='Adult ticket 40 CNY'
        return {'claim_id':'c','entity_id':'a','field':'price','value':40,'unit':'CNY','source_id':'operator',
          'source_url':'https://operator.example/guide','raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
          'entity_verified':True,'extraction_verified':True,'semantic_reviewed':True,'licence_status':'research_read_only_redistribution_unverified',
          'retrieved_at':'2026-10-23T05:00:00+00:00','observed_at':None,'context':{'travel_date':'2026-10-24'}}

    def registry(self):
        return {'operator':{'authority':'primary_operator','supports':['price'],'allowed_hosts':['operator.example'],'independence_group':'one'}}

    def view(self,c,registry=None):
        return evidence_view(c, registry if registry is not None else self.registry(),now='2026-10-23T05:01:00+00:00',context={'travel_date':'2026-10-24'})

    def test_dated_unknown_rights_reference_never_becomes_hard_fact(self):
        v=self.view(self.claim())
        self.assertEqual(v['evidence_use'],'published_reference')
        self.assertFalse(v['usable_as_hard_fact'])
        self.assertFalse(v['source_clock_known'])

    def test_wrong_branch_and_forged_quotes_quarantined(self):
        c=self.claim();c['entity_verified']=False
        self.assertEqual(self.view(c)['evidence_use'],'quarantined')
        c=self.claim();c['quote']='free'
        self.assertEqual(self.view(c)['evidence_use'],'quarantined')

    def test_wrong_date_and_unregistered_source_quarantined(self):
        c=self.claim();c['context']['travel_date']='2026-10-25'
        self.assertEqual(self.view(c)['evidence_use'],'quarantined')
        self.assertEqual(self.view(self.claim(),{})['evidence_use'],'quarantined')

    def test_alias_cycle_rejected(self):
        with self.assertRaises(ValueError):canonical_id('a',{'a':'b','b':'a'})

    def test_source_coverage_beats_arbitrary_alphabetical_candidate(self):
        candidates=[{'entity_id':'a','themes':['history']},{'entity_id':'b','themes':['history'],'branch_verified':True}]
        evidence=[{'entity_id':'b','field':'price','evidence_use':'published_reference'}]
        self.assertEqual(rank_candidates(candidates,requested_theme='history',evidence=evidence)[0]['entity_id'],'b')

    def test_anchor_repair_does_not_change_first_answer(self):
        old={'proposed_plan':{'itinerary':[{'activities':[{'type':'start','start_time':'09:50','end_time':'10:00','position':'X'},{'type':'end','position':'X'}]}]}}
        fixed,edits=repair_anchors(old,{'start_time':'10:00','anchor':'X'})
        self.assertEqual(old['proposed_plan']['itinerary'][0]['activities'][0]['start_time'],'09:50')
        self.assertEqual(fixed['proposed_plan']['itinerary'][0]['activities'][0]['start_time'],'10:00')
        self.assertEqual(len(edits),1)

    def test_revision_locks_from_actual_plan(self):
        p={'proposed_plan':{'itinerary':[{'activities':[{'type':'lunch','entity_id':'actual-lunch'},{'type':'accommodation','entity_id':'actual-hotel'},{'type':'attraction','entity_id':'sight'}]}]}}
        self.assertEqual(revision_locks(p),['actual-hotel','actual-lunch'])


if __name__=='__main__':unittest.main(verbosity=2)
