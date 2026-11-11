"""Adversarial mutations of the delivered plan, not implementation-mirroring tests."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.adaptive_delivery import evaluate_delivery,normalize_delivery_anchors


class DeliveryMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out=ROOT/'results/p22_adaptive_delivery'
        cls.inp=json.loads((out/'participant_input.json').read_text(encoding='utf-8'))
        cls.original=json.loads((out/'plans/D01/deliverable.json').read_text(encoding='utf-8'))

    def evaluate(self,p,entities=None,refs=None):
        return evaluate_delivery(p,self.inp['request'],entities=entities or self.inp['entities'],references=refs or self.inp['references'])

    def test_delivered_positive_witness(self):self.assertTrue(self.evaluate(self.original)['proposal_ok'])

    def test_wrong_travel_date_detected(self):
        p=copy.deepcopy(self.original);p['date']='2026-10-25'
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_shortening_transfer_below_api_and_buffer_detected(self):
        p=copy.deepcopy(self.original)
        t=next(x for x in p['schedule'] if x['type']=='travel');t['end_time']='13:40'
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_wrong_departure_not_reusing_other_time_route(self):
        p=copy.deepcopy(self.original)
        t=next(x for x in p['schedule'] if x['type']=='travel');t['start_time']='13:01'
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_same_complex_cannot_count_as_two_attractions(self):
        entities=copy.deepcopy(self.inp['entities'])
        for e in entities.values():e['visit_group_id']='one-complex'
        self.assertFalse(self.evaluate(self.original,entities=entities)['proposal_ok'])

    def test_two_person_budget_arithmetic_and_limit_detected(self):
        p=copy.deepcopy(self.original);p['budget']['items'][1]['amount_cny']=800
        self.assertFalse(self.evaluate(p)['proposal_ok'])
        p['budget']['projection_cny']=1040
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_budget_decision_not_confirmed_quote(self):
        p=copy.deepcopy(self.original);p['budget']['confirmed_total_cny']=320;p['budget']['conditional']=False
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_nonexistent_evidence_detected(self):
        p=copy.deepcopy(self.original);p['budget']['items'][0]['evidence_refs']=['invented:price']
        self.assertFalse(self.evaluate(p)['proposal_ok'])

    def test_earlier_activities_not_hidden_by_anchor_compilation(self):
        p=copy.deepcopy(self.original);p['schedule']=[x for x in p['schedule'] if x['type']!='start'];p['schedule'][0]['start_time']='08:50'
        p,_=normalize_delivery_anchors(p,self.inp['request'])
        self.assertFalse(self.evaluate(p)['proposal_ok'])


if __name__=='__main__':unittest.main(verbosity=2)
