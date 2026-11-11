import copy
import importlib.util
import unittest


def activity(kind, start, end, position='P', transports=None):
    return {'type': kind, 'start_time': start, 'end_time': end, 'position': position,
            'cost': 0, 'price': 0, 'transports': transports or []}


def leg(start, end, mode='walk', distance=1, origin='P', destination='Q'):
    return {'start': origin, 'end': destination, 'mode': mode, 'start_time': start,
            'end_time': end, 'distance': distance, 'cost': 0, 'price': 0}


def plan(days):
    return {'start_city': 'A', 'target_city': 'B', 'people_number': 1,
            'itinerary': [{'day': n + 1, 'activities': acts} for n, acts in enumerate(days)]}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('chinatravel.soft_constraints'), 'soft module must exist')
        from chinatravel.soft_constraints.scoring import score_plan
        self.score = score_plan

    def test_empty_playable_hotel_day_and_missing_meals(self):
        p = plan([[activity('accommodation', '06:00', '24:00')]])
        result = self.score(p)
        reasons = {d['rule'] for d in result['details']}
        self.assertTrue({'no_attractions', 'missing_lunch', 'missing_dinner', 'idle_gap'} <= reasons)
        self.assertEqual(result['metrics']['days'][0]['playable_minutes'], 660)

    def test_early_return_day_is_not_empty_playable_day(self):
        outbound = activity('train', '06:00', '07:00'); outbound.update(start='A station', end='B station')
        back = activity('train', '07:00', '08:00'); back.update(start='B station', end='A station')
        result = self.score(plan([[outbound, activity('accommodation', '08:00', '24:00')], [back]]))
        self.assertEqual(result['metrics']['days'][1]['playable_minutes'], 0)
        self.assertFalse(any(d['day'] == 2 and d['rule'] in ('no_attractions','missing_lunch','missing_dinner') for d in result['details']))

    def test_commute_is_whole_chain_and_wait_is_separate(self):
        a = activity('attraction', '10:30', '12:00', transports=[leg('09:00','09:30'),leg('09:30','10:30','metro',10)])
        back = activity('train','18:00','19:00',transports=[leg('12:00','12:30','taxi',10)])
        back.update(start='B station',end='A station')
        go = activity('train','07:00','08:00');go.update(start='A station',end='B station')
        result = self.score(plan([[go,a,back]]))
        rules = [d for d in result['details'] if d['category']=='transport']
        self.assertEqual(next(d['penalty'] for d in rules if d['rule']=='long_commute'),2)
        self.assertEqual(next(d['penalty'] for d in rules if d['rule']=='long_walk'),1)
        self.assertEqual(next(d['actual'] for d in rules if d['rule']=='station_wait'),330)
        self.assertAlmostEqual(result['total_penalty'],sum(result['categories'].values()),places=5)

    def test_detour_uses_sandbox_counterfactual_and_groups_meals(self):
        calls=[]
        def route(city,start,end,time,mode):
            calls.append((start,end,mode))
            return [leg('10:00','10:10','metro',2)]
        p=plan([[activity('attraction','09:00','10:00','X'),
                 activity('lunch','11:00','12:00','R',[leg('10:00','10:40','metro',8)]),
                 activity('dinner','12:00','13:00','S',[leg('12:00','12:10','walk',1)]),
                 activity('attraction','14:00','15:00','Y',[leg('13:00','13:40','metro',8)])]])
        result=self.score(p,route_resolver=route)
        self.assertEqual(calls,[('X','Y','metro')])
        group=result['metrics']['meal_detours'][0]
        self.assertEqual(group['extra_minutes'],80)
        self.assertEqual(group['extra_km'],15)
        unknown=self.score(p)['metrics']['meal_detours'][0]
        self.assertIsNone(unknown['extra_minutes'])

    def test_overlap_is_union_and_weights_are_configurable(self):
        from chinatravel.soft_constraints.scoring import SoftConfig
        p=plan([[activity('attraction','09:00','12:00',transports=[leg('09:00','10:00','metro',5)])]])
        result=self.score(p)
        self.assertEqual(result['metrics']['days'][0]['busy_minutes'],180)
        weighted=self.score(p,config=SoftConfig(weights={'transport':2,'rhythm':0,'distribution':0,'efficiency':0}))
        self.assertAlmostEqual(weighted['total_penalty'],2*weighted['raw_categories']['transport'])

    def test_wait_uses_previous_day_and_midnight_access(self):
        go=activity('train','06:00','07:00');go.update(start='A station',end='B station')
        overnight=activity('accommodation','20:00','23:00','B station')
        back=activity('train','03:00','05:00');back.update(start='B station',end='A station')
        result=self.score(plan([[go,overnight],[back]]))
        self.assertEqual(result['metrics']['waits'][-1]['minutes'],240)
        crossing=activity('train','00:30','02:00',transports=[leg('23:40','00:10','taxi',10)])
        crossing.update(start='B station',end='A station')
        result=self.score(plan([[go,overnight],[crossing]]))
        self.assertEqual(result['metrics']['waits'][-1]['minutes'],20)

    def test_invalid_configuration_is_rejected(self):
        from chinatravel.soft_constraints.scoring import SoftConfig
        for kwargs in ({'weights':{'transport':-1}}, {'wait_unit':0}, {'walk_minutes':float('nan')}):
            with self.assertRaises(ValueError):
                SoftConfig(**kwargs)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('chinatravel.soft_constraints.pool'), 'candidate pool must exist')

    def test_pool_deduplicates_snapshots_and_selects_stable_minimum(self):
        from chinatravel.soft_constraints.pool import CandidatePool
        pool=CandidatePool(limit=2,scorer=lambda p: {'total_penalty':p['itinerary'][0]['activities'][0]['cost']})
        p=plan([[activity('attraction','09:00','10:00')]])
        p['itinerary'][0]['activities'][0]['cost']=5
        self.assertTrue(pool.add(p))
        changed=copy.deepcopy(p);changed['search_nodes']=999
        self.assertFalse(pool.add(changed))
        p['itinerary'][0]['activities'][0]['cost']=1
        p['itinerary'][0]['activities'][0]['position']='Different'
        self.assertTrue(pool.add(p));self.assertTrue(pool.full)
        p['itinerary'].clear()
        self.assertEqual(pool.items[0]['plan']['itinerary'][0]['activities'][0]['cost'],5)
        self.assertEqual(pool.best()['ordinal'],2)
        self.assertFalse(pool.add(plan([[activity('attraction','11:00','12:00')]])))

    def test_agent_collector_continues_until_limit_and_preserves_default(self):
        from unittest.mock import patch
        from chinatravel.soft_constraints.agent import SoftLLMDrivenAgent, CandidateCollectionComplete
        from chinatravel.agent.nesy_agent.llm_driven_rec import LLMDrivenAgent
        from chinatravel.soft_constraints.pool import CandidatePool
        agent=object.__new__(SoftLLMDrivenAgent)
        agent.pool=CandidatePool(limit=2,scorer=lambda p:{'total_penalty':0})
        agent.on_candidate=None
        p=plan([[activity('attraction','09:00','10:00')]])
        with patch.object(LLMDrivenAgent,'constraints_validation',return_value=(True,p)):
            self.assertFalse(agent.constraints_validation({},p['itinerary'],{})[0])
            self.assertFalse(agent.constraints_validation({},p['itinerary'],{})[0])
        p2=copy.deepcopy(p);p2['itinerary'][0]['activities'][0]['position']='Other'
        with patch.object(LLMDrivenAgent,'constraints_validation',return_value=(True,p2)):
            with self.assertRaises(CandidateCollectionComplete):
                agent.constraints_validation({},p2['itinerary'],{})
        self.assertEqual(len(agent.pool.items),2)

    def test_run_selects_pool_minimum_and_reports_empty_deadline(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from chinatravel.soft_constraints.agent import SoftLLMDrivenAgent, CandidateCollectionComplete,CandidateDeadline
        from chinatravel.agent.nesy_agent.llm_driven_rec import LLMDrivenAgent
        from chinatravel.soft_constraints.scoring import SoftConfig
        agent=object.__new__(SoftLLMDrivenAgent)
        agent.candidate_limit=2;agent.soft_config=SoftConfig();agent.wall_limit_seconds=None
        agent.backbone_llm=SimpleNamespace(input_token_count=0,output_token_count=0,input_token_maxx=0)
        agent._score=lambda p:{'total_penalty':p['itinerary'][0]['activities'][0]['cost']}
        def search(*args,**kwargs):
            for value in [5,1]:
                p=plan([[activity('attraction','09:00','10:00',str(value))]])
                p['itinerary'][0]['activities'][0]['cost']=value
                agent.pool.add(p)
            raise CandidateCollectionComplete()
        with patch.object(LLMDrivenAgent,'run',side_effect=search):
            success,result=agent.run({})
        self.assertTrue(success);self.assertEqual(result['itinerary'][0]['activities'][0]['position'],'1')
        self.assertEqual(agent.selection['selected_ordinal'],2)
        with patch.object(LLMDrivenAgent,'run',side_effect=CandidateDeadline):
            success,result=agent.run({})
        self.assertFalse(success);self.assertEqual(agent.selection['candidate_count'],0)
        self.assertEqual(agent.selection['stop_reason'],'wall_limit_reached')


if __name__=='__main__':
    unittest.main()
