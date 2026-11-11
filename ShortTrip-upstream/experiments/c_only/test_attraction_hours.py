from pathlib import Path
import unittest
import rules
from test_rules import activity,plan

class AttractionHours(unittest.TestCase):
    def test_overnight_attraction_is_rejected_even_if_open24hours(self):
        p=plan(activity('train','06:00','07:00'),activity('train','20:00','22:00'),lastday=2)
        p['itinerary'][0]['activities'].append(activity('accommodation','21:00','24:00'))
        p['itinerary'][1]['activities'][:0]=[activity('attraction','01:20','02:50')]
        result=rules.audit(p,2)
        self.assertFalse(result.get('attraction_hours_pass',True))
        self.assertFalse(result['all_pass'])

    def test_slot_uses08_as_earliest_start(self):
        self.assertTrue(hasattr(rules,'attraction_slot'),'Attraction scheduling gate missing')
        self.assertEqual(rules.attraction_slot('01:20','00:00','24:00',90),('08:00','09:30'))

    def test_slot_caps_visit_at21(self):
        self.assertTrue(hasattr(rules,'attraction_slot'),'Attraction scheduling gate missing')
        self.assertEqual(rules.attraction_slot('20:30','00:00','24:00',90),('20:30','21:00'))

    def test_slot_rejects_visit_after21(self):
        self.assertTrue(hasattr(rules,'attraction_slot'),'Attraction scheduling gate missing')
        self.assertIsNone(rules.attraction_slot('21:00','00:00','24:00',90))

    def test_slot_keeps_actual_opening_hours(self):
        self.assertTrue(hasattr(rules,'attraction_slot'),'Attraction scheduling gate missing')
        self.assertEqual(rules.attraction_slot('08:00','10:00','17:00',90),('10:00','11:30'))

    def test_source_gate_checks_slot_before_adding_attraction(self):
        import dfs_snapshot,inspect
        source=inspect.getsource(dfs_snapshot.dfs_poi)
        self.assertIn('self.attraction_slot(',source)

    def test_midnight_after_hotel_resumes_at06(self):
        import os
        os.chdir(Path(__file__).resolve().parents[2])
        from experiment_agent import ExperimentAgent
        self.assertTrue(hasattr(ExperimentAgent,'day_resume_time'),'Midnight hotel restart not guarded')
        agent=ExperimentAgent.__new__(ExperimentAgent);agent.query={'days':2}
        p=[dict(day=1,activities=[activity('accommodation','21:00','24:00')]),dict(day=2,activities=[])]
        self.assertEqual(agent.day_resume_time(p,{'back_transport':dict(BeginTime='19:00')},1,'00:00'),'06:00')

    def test_early_return_transport_not_blocked(self):
        import os
        os.chdir(Path(__file__).resolve().parents[2])
        from experiment_agent import ExperimentAgent
        self.assertTrue(hasattr(ExperimentAgent,'day_resume_time'),'Midnight hotel restart not guarded')
        agent=ExperimentAgent.__new__(ExperimentAgent);agent.query={'days':2}
        p=[dict(day=1,activities=[activity('accommodation','21:00','24:00')]),dict(day=2,activities=[])]
        self.assertEqual(agent.day_resume_time(p,{'back_transport':dict(BeginTime='04:00')},1,'00:00'),'00:00')

    def test_return_access_before06_remains_possible(self):
        from experiment_agent import ExperimentAgent
        agent=ExperimentAgent.__new__(ExperimentAgent);agent.query={'days':2,'target_city':'X'}
        p=[dict(day=1,activities=[activity('accommodation','21:00','24:00',position='H')]),dict(day=2,activities=[])]
        agent.collect_innercity_transport=lambda *args:[dict(start_time='06:00',end_time='06:30')]
        agent.innercity_transports_ranking_from_query=['metro']
        self.assertEqual(agent.day_resume_time(p,{'back_transport':dict(BeginTime='06:10',From='S',TrainID='T1')},1,'00:00'),'00:00')

if __name__=='__main__':unittest.main()
