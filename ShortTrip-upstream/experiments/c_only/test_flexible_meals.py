import unittest
import pandas as pd
from experiment_agent import ExperimentAgent

class FlexibleMeals(unittest.TestCase):
    def agent(self):
        a=ExperimentAgent.__new__(ExperimentAgent)
        a.group='C';a.query=dict(days=1,target_city='武汉',nature_language='武汉一日游')
        a.llm_inference_time_count=0;a.llm_rec_count=0
        a.backbone_llm=lambda *args,**kw:'Thought: can explore first\nType: attraction'
        a.innercity_transports_ranking_from_query=['metro','taxi']
        a.restaurants_visiting=[];a._deadline_check=lambda:None
        a.memory={'restaurants':pd.DataFrame([dict(name='R',opentime='11:00',endtime='22:00')])}
        a.collect_innercity_transport=lambda city,s,e,t,m:[dict(start_time=t,end_time='13:30')]
        return a
    def obligation(self,end=1440):
        return dict(kind='lunch',day=1,status='required',window=[660,840],duration=60,free_intervals=[[420,end]])
    def test_eleven_does_not_force_lunch_and_keeps_both_branches(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        selected,options=a.select_next_poi_type(['attraction','lunch','hotel'],[],{},0,'11:00','A')
        self.assertEqual(selected,'attraction');self.assertIn('lunch',options)
        self.assertNotIn('hotel',options)
    def test_failed_attraction_branch_can_try_meal(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        selected,options=a.select_next_poi_type(['lunch'],[],{},0,'11:00','A')
        self.assertEqual((selected,options),('lunch',['lunch']))
    def test_full_visit_then_real_access_still_allows_lunch(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        self.assertTrue(a.meals_possible_after([],{},0,'13:00','景点'))
    def test_access_can_push_meal_past_deadline(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        a.collect_innercity_transport=lambda *args:[dict(end_time='14:05')]
        self.assertFalse(a.meals_possible_after([],{},0,'13:45','景点'))
    def test_full_meal_must_fit_before_return(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation(810)]
        self.assertFalse(a.meals_possible_after([],{},0,'13:00','景点'))
    def test_closed_restaurant_and_reused_restaurant_not_witnesses(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        a.memory['restaurants'].loc[0,'endtime']='13:45'
        self.assertFalse(a.meals_possible_after([],{},0,'13:00','景点'))
        a.memory['restaurants'].loc[0,'endtime']='22:00';a.restaurants_visiting=[0]
        self.assertFalse(a.meals_possible_after([],{},0,'13:00','景点'))
    def test_an_alternative_transport_may_save_meal(self):
        a=self.agent();a.missing_today=lambda *args:[self.obligation()]
        a.collect_innercity_transport=lambda city,s,e,t,m:[dict(end_time='14:10' if m=='metro' else '13:40')]
        self.assertTrue(a.meals_possible_after([],{},0,'13:00','景点'))
if __name__=='__main__':unittest.main()
