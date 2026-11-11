from pathlib import Path
import unittest
import os
os.chdir(Path(__file__).resolve().parents[2])
from test_rules import activity,plan
try:
    from experiment_agent import ExperimentAgent, prefer_go, prefer_back
except ImportError:
    ExperimentAgent=prefer_go=prefer_back=None

class AgentIntegration(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ExperimentAgent,'Experiment agent not implemented')

    def test_morning_go_and_evening_return(self):
        rows=[dict(BeginTime='00:30',EndTime='02:00'),dict(BeginTime='08:00',EndTime='09:00'),dict(BeginTime='18:00',EndTime='19:00')]
        self.assertEqual(prefer_go([0,2,1],rows)[0],1)
        self.assertEqual(prefer_back([0,1,2],rows)[0],2)

    def test_overnight_go_uses_arrival_day(self):
        agent=ExperimentAgent.__new__(ExperimentAgent)
        d,t=agent.outbound_next(dict(BeginTime='22:00',EndTime='08:00'))
        self.assertEqual((d,t),(1,'08:00'))

    def test_missing_meals_block_day_close(self):
        agent=ExperimentAgent.__new__(ExperimentAgent)
        agent.query={'days':1}
        poi={'go_transport':dict(BeginTime='06:00',EndTime='07:00'), 'back_transport':dict(BeginTime='20:00',EndTime='22:00')}
        p=[dict(day=1,activities=[activity('train','06:00','07:00')])]
        self.assertFalse(agent.close_day_allowed(p,poi,0))

    def test_breakfast_is_searchable(self):
        import dfs_snapshot
        import inspect
        self.assertIn('candidates_type.append("breakfast")',inspect.getsource(dfs_snapshot.dfs_poi))

    def test_first_day_breakfast_uses_real_restaurant(self):
        import inspect
        source=inspect.getsource(ExperimentAgent.add_restaurant)
        self.assertIn('WINDOWS',source)
        self.assertIn('poi_sel',source)

    def test_c_delayed_restaurant_keeps_full_meal_duration(self):
        agent=ExperimentAgent.__new__(ExperimentAgent)
        agent.group='C';agent.query=dict(days=1,people_number=1,target_city='X')
        poi={'go_transport':dict(BeginTime='06:00',EndTime='07:00'), 'back_transport':dict(BeginTime='20:00',EndTime='22:00')}
        p=[dict(day=1,activities=[activity('train','06:00','07:00')])]
        agent._context=(p,poi,0,'09:00','A')
        agent.collect_innercity_transport=lambda *args:[dict(start='A',end='R',mode='taxi',start_time='10:50',end_time='11:00',price=1,cost=1,distance=1)]
        row=dict(name='R',opentime='11:00',endtime='22:00',price=10)
        actual=agent.add_restaurant(p,'lunch',row,0,'09:10',[dict(start='A',end='R',mode='taxi',start_time='09:00',end_time='09:10')])
        meal=actual[0]['activities'][-1]
        self.assertEqual((meal['start_time'],meal['end_time']),('11:00','12:00'))

    def test_lunch_precedes_original_return_shortcut(self):
        agent=ExperimentAgent.__new__(ExperimentAgent)
        agent.group='B';agent.query=dict(days=1)
        poi={'go_transport':dict(BeginTime='06:00',EndTime='07:00'), 'back_transport':dict(BeginTime='14:00',EndTime='16:00')}
        p=[dict(day=1,activities=[activity('train','06:00','07:00'),activity('breakfast','08:00','08:30')])]
        selected,options=agent.select_next_poi_type(['attraction','lunch','dinner','back-intercity-transport'],p,poi,0,'12:00','A')
        self.assertEqual(selected,'lunch')
        self.assertNotIn('back-intercity-transport',options)

    def test_lunch_may_end_after_start_window(self):
        agent=ExperimentAgent.__new__(ExperimentAgent)
        agent.group='B';agent.query=dict(days=1,people_number=1)
        poi={'go_transport':dict(BeginTime='06:00',EndTime='07:00'), 'back_transport':dict(BeginTime='20:00',EndTime='22:00')}
        p=[dict(day=1,activities=[activity('train','06:00','07:00')])]
        agent._context=(p,poi,0,'13:30','A')
        actual=agent.add_restaurant(p,'lunch',dict(name='R',opentime='11:00',endtime='23:00',price=10),0,'13:30',[])
        self.assertEqual(actual[0]['activities'][-1]['end_time'],'14:30')

    def test_dfs_signature_accepts_original_outer_caller(self):
        import inspect
        inspect.signature(ExperimentAgent.dfs_poi).bind(object(),{}, {},plan=[],current_time='',current_position='')

if __name__=='__main__':unittest.main()
