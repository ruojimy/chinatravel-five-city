import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'experiments/c_only'))
os.chdir(PROJECT)

import pandas as pd
from chinatravel.agent.nesy_agent.nesy_agent import NesyAgent


def train(code='G1', start='08:00', end='10:00', cost=50):
    return dict(TrainID=code, FlightID=float('nan'), BeginTime=start,
                EndTime=end, Duration=2, Cost=cost, From='A', To='B')


def flight(start='21:55', end='23:25', cost=70):
    return dict(TrainID=float('nan'), FlightID='FL1', BeginTime=start,
                EndTime=end, Duration=1.5, Cost=cost, From='B', To='A')


def query(*constraints):
    return dict(days=2, people_number=2, hard_logic=list(constraints), hard_logic_py=[],
                start_city='A', target_city='B', uid='test')


class EarlyFiltering(unittest.TestCase):
    def agent(self, q):
        agent = NesyAgent.__new__(NesyAgent)
        agent.query = q
        return agent

    def test_train_only_filters_flight_before_detailed_search(self):
        q = query("intercity_transport=={'train'}")
        a = self.agent(q)
        rows = pd.DataFrame([flight(), train()])
        self.assertEqual(a.reranking_intercity_transport_back_with_constraints(
            [0, 1], rows, q, pd.Series(train('D2373'))), [1])

    def test_g_train_requirement_filters_d_train_but_keeps_g(self):
        q = query("train_type=={'G'}")
        a = self.agent(q)
        self.assertEqual(a.reranking_intercity_transport_go_with_constraints(
            [0, 1], pd.DataFrame([train('D2'), train('G2')]), q), [1])

    def test_return_departure_deadline_is_inclusive_and_filters_late(self):
        q = query("return_start_time<='19:00'")
        a = self.agent(q)
        rows = pd.DataFrame([train(start='19:01'), train(start='19:00')])
        self.assertEqual(a.reranking_intercity_transport_back_with_constraints(
            [0, 1], rows, q, pd.Series(train())), [1])

    def test_mixed_modes_can_be_completed_by_return_ticket(self):
        q = query("intercity_transport=={'train','airplane'}")
        a = self.agent(q)
        self.assertEqual(a.reranking_intercity_transport_go_with_constraints(
            [0], pd.DataFrame([train()]), q), [0])
        self.assertEqual(a.reranking_intercity_transport_back_with_constraints(
            [0, 1], pd.DataFrame([train(), flight()]), q, pd.Series(train())), [1])

    def test_unvisited_named_attraction_and_custom_constraint_do_not_prune(self):
        q = query("{'some museum'}<=attraction_names", 'complex_rule(plan)')
        a = self.agent(q)
        self.assertEqual(a.reranking_intercity_transport_back_with_constraints(
            [0], pd.DataFrame([train()]), q, pd.Series(train())), [0])

    def test_train_prefix_does_not_require_go_to_be_train(self):
        q = query("train_type=={'G'}")
        a = self.agent(q)
        self.assertEqual(a.reranking_intercity_transport_go_with_constraints(
            [0], pd.DataFrame([flight()]), q), [0])
        self.assertEqual(a.reranking_intercity_transport_back_with_constraints(
            [0, 1], pd.DataFrame([flight(), train()]), q, pd.Series(flight())), [1])


class PrefixPruning(unittest.TestCase):
    def check(self, q, activities=(), poi=None, rooms=None):
        from chinatravel.agent.nesy_agent.pruning import prefix_reason
        return prefix_reason(q, [dict(day=1, activities=list(activities))], poi or {}, rooms)

    def test_reserved_cost_and_local_fares_count_once(self):
        q = query('cost<=300')
        poi = dict(go_transport=train(cost=50), back_transport=train(cost=50),
                   accommodation=dict(price=50, numbed=2))
        acts = [dict(type='train', cost=100, transports=[]),
                dict(type='accommodation', cost=50, transports=[]),
                dict(type='lunch', cost=40, transports=[dict(mode='taxi', cost=10)])]
        self.assertIsNone(self.check(q, acts, poi, 1))
        acts[-1]['transports'][0]['cost'] = 11
        rejected = self.check(q, acts, poi, 1)
        self.assertEqual(rejected['details']['lower_bound'], 301)

    def test_budget_lower_bound_handles_equal_strict_and_unknown_future(self):
        activity = dict(type='lunch', cost=100, transports=[])
        self.assertIsNone(self.check(query('cost<=100'), [activity]))
        self.assertEqual(self.check(query('cost<100'), [activity])['rule'], 'budget_lower_bound')
        self.assertIsNone(self.check(query('cost>=1000'), [activity]))
        self.assertIsNone(self.check(query('cost==1000'), [activity]))

    def test_metro_access_walk_allowed_but_taxi_rejected(self):
        q = query("transport_type<={'metro'}")
        acts = [dict(type='attraction', cost=0, transports=[
            dict(mode='walk', cost=0), dict(mode='metro', cost=2), dict(mode='walk', cost=0)])]
        self.assertIsNone(self.check(q, acts))
        acts[0]['transports'] = [dict(mode='taxi', cost=1)]
        self.assertEqual(self.check(q, acts)['rule'], 'local_mode')

    def test_local_equality_does_not_require_unseen_mode_yet(self):
        q = query("transport_type=={'metro','taxi'}")
        self.assertIsNone(self.check(q, [dict(type='lunch', cost=1,
                                            transports=[dict(mode='taxi', cost=1)])]))

    def test_executed_ticket_and_car_counts_are_irreversible(self):
        a = dict(type='attraction', cost=0, tickets=1, transports=[])
        self.assertEqual(self.check(query('tickets==2'), [a])['rule'], 'executed_activity')
        a['tickets'] = 2
        a['transports'] = [dict(mode='taxi', cost=1, cars=2)]
        self.assertEqual(self.check(query('taxi_cars==1'), [a])['rule'], 'executed_transport')

    def test_fixed_hotel_limits_prune_without_visiting_it(self):
        poi = dict(accommodation=dict(price=201, numbed=1))
        self.assertEqual(self.check(query('hotel_price<=200'), poi=poi, rooms=1)['rule'], 'hotel_selection')
        self.assertEqual(self.check(query('room_type==2'), poi=poi, rooms=1)['rule'], 'hotel_selection')
        self.assertIsNone(self.check(query('hotel_price<=200'), poi=dict(accommodation=dict(price=200.99, numbed=2)), rooms=1))

    def test_missing_future_requirements_are_not_false_on_prefix(self):
        self.assertIsNone(self.check(query("{'museum'}<=attraction_names", "{'food'}<=food_type")))

    def test_model_mode_omissions_do_not_ban_allowed_alternatives(self):
        from chinatravel.agent.nesy_agent.pruning import local_ranking
        self.assertEqual(local_ranking(query(), ['metro']), ['metro', 'taxi', 'walk'])
        self.assertEqual(local_ranking(query("transport_type<={'metro'}"), ['taxi']), ['metro'])
        self.assertEqual(local_ranking(query(), ['taxi', 'taxi', 'invalid']), ['taxi', 'metro', 'walk'])

    def test_overnight_outbound_does_not_reserve_nonexistent_hotel_night(self):
        q = query('cost<=300')
        go = train(start='22:00', end='08:00', cost=50)
        go['Duration'] = 10
        poi = dict(go_transport=go, back_transport=train(cost=50),
                   accommodation=dict(price=200, numbed=2))
        self.assertIsNone(self.check(q, poi=poi, rooms=1))


class MealPreflight(unittest.TestCase):
    def meal(self, kind='lunch', lo=660, hi=840, duration=60, free=(420, 1440), day=1):
        return dict(day=day, kind=kind, status='required', window=[lo, hi], duration=duration,
                    free_intervals=[list(free)])

    def check(self, meals, rows, begin=420, end=1300, hotels=()):
        from meal_pruning import meal_lower_bound
        return meal_lower_bound(meals, None if rows is None else pd.DataFrame(rows), begin, end, hotels)

    def test_restaurant_opens_after_return_rejects_before_search(self):
        rejected, _ = self.check([self.meal()], [dict(opentime='14:00', endtime='22:00', price=10)], end=780)
        self.assertEqual(rejected['rule'], 'meal_combination_infeasible')

    def test_late_lunch_may_finish_after_start_window(self):
        rejected, cost = self.check([self.meal()], [dict(opentime='13:30', endtime='22:00', price=10)])
        self.assertIsNone(rejected)
        self.assertEqual(cost, 10)

    def test_unknown_opening_information_retains_branch(self):
        for rows in (None, [dict(price=10)], [dict(opentime='20:00', endtime='02:00', price=10)]):
            self.assertIsNone(self.check([self.meal()], rows)[0])

    def test_breakfast_before_early_return_and_hotel_breakfast(self):
        b = self.meal('breakfast', 1800, 1980, 30, (444, 1833), 2)
        rows = [dict(opentime='08:00', endtime='22:00', price=10)]
        self.assertIsNotNone(self.check([b], rows, end=1833, hotels=[2])[0])
        self.assertIsNone(self.check([b], [dict(opentime='06:00', endtime='22:00', price=10)], end=1833)[0])
        b['free_intervals'] = [[444, 2600]]
        self.assertEqual(self.check([b], [], end=2600, hotels=[2]), (None, 0))

    def test_traffic_exemption_not_converted_into_required_meal(self):
        o = self.meal()
        o['status'] = 'traffic_exempt'
        self.assertEqual(self.check([o], []), (None, 0))

    def test_minimum_meal_prices_relax_reuse(self):
        meals = [self.meal(), self.meal('dinner', 1020, 1200)]
        self.assertEqual(self.check(meals, [dict(opentime='06:00', endtime='23:00', price=10)]), (None, 20))

    def test_meal_price_lower_bound_matches_integer_billing(self):
        self.assertEqual(self.check([self.meal()], [dict(opentime='06:00', endtime='23:00', price=10.99)]), (None, 10))

    def test_c_root_applies_preflight_before_dfs(self):
        from experiment_agent import ExperimentAgent
        from unittest.mock import patch
        a = ExperimentAgent.__new__(ExperimentAgent)
        a.group = 'C'
        a._deadline_check = lambda: None
        a.query = query()
        a.memory = dict(restaurants=pd.DataFrame([dict(opentime='08:00', endtime='23:00', price=10)]))
        poi = dict(go_transport=train(start='06:00', end='07:24'),
                   back_transport=train(start='06:33', end='07:23'),
                   accommodation=dict(price=30, numbed=2))
        poi['back_transport']['Duration'] = .83
        with patch('dfs_snapshot.dfs_poi', side_effect=AssertionError('must reject before detailed search')):
            success, _ = a.dfs_poi(a.query, poi, [], '', '')
        self.assertFalse(success)
        self.assertEqual(a.prune_counts['meal_combination_infeasible'], 1)
        self.assertEqual(a.prune_examples['meal_combination_infeasible'][0]['details']['day'], 2)


class AccessPruning(unittest.TestCase):
    def agent(self, arrivals):
        a = NesyAgent.__new__(NesyAgent)
        a.innercity_transports_ranking_from_query = ['metro', 'taxi']
        a.search_nodes = 0
        a.backtrack_count = 0
        a.collect_innercity_transport = lambda city, source, target, time, mode: [dict(end_time=arrivals[mode])]
        return a

    def test_return_kept_if_later_mode_can_arrive_in_time(self):
        a = self.agent(dict(metro='20:30', taxi='19:30'))
        self.assertFalse(a.check_if_too_late(query(), 1, '19:00', 'X',
                                           dict(back_transport=dict(From='Y', BeginTime='20:00'))))

    def test_hotel_kept_if_later_mode_can_arrive_before_midnight(self):
        a = self.agent(dict(metro='24:30', taxi='23:30'))
        self.assertFalse(a.check_if_too_late(query(), 0, '22:00', 'X',
                                           dict(accommodation=dict(name='Y'), back_transport={})))

    def test_all_modes_late_reject_and_midnight_wrap_is_late(self):
        a = self.agent(dict(metro='20:30', taxi='00:30'))
        self.assertTrue(a.check_if_too_late(query(), 1, '19:00', 'X',
                                          dict(back_transport=dict(From='Y', BeginTime='20:00'))))

    def test_unknown_route_error_is_not_proof_of_impossibility(self):
        a = self.agent({})
        a.collect_innercity_transport = lambda *args: (_ for _ in ()).throw(ValueError('unknown route'))
        self.assertFalse(a.check_if_too_late(query(), 1, '19:00', 'X',
                                           dict(back_transport=dict(From='Y', BeginTime='20:00'))))


if __name__ == '__main__':
    unittest.main()
