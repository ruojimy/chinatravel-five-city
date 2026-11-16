from copy import deepcopy
from pathlib import Path
import json,os,sys,unittest

HERE=Path(__file__).resolve().parent
REPO=HERE.parent
FIXTURES=HERE/'fixtures/multileg'
profile=os.environ.get('CT_SANDBOX_TEST_PROFILE')
if not profile:
    raise unittest.SkipTest('set CT_SANDBOX_TEST_PROFILE to a verified eleven-city profile')
sys.path.insert(0,str(REPO/'scripts'))
from g3_sandbox import configure
configure(profile)
sys.path.insert(0,str(REPO/'ShortTrip-upstream'))
from chinatravel.symbol_verification import commonsense_constraint as common
from chinatravel.environment.tools.transportation.apis import (
    Transportation, _normalize_station_position, _city_poi_reference)


class MultiLegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider=Transportation()
        cls.query={'start_city':'重庆','target_city':'西安','people_number':3}

    def leg(self,start,end,mode,start_time):
        answer=self.provider.goto(city='西安',start=start,end=end,start_time=start_time,transport_type=mode)
        self.assertIsInstance(answer,list,answer)
        result=[]
        for row in answer:
            row=deepcopy(row);row['price']=row['cost']
            if row['mode']=='taxi':row['cars']=1
            if row['mode']=='metro':row['tickets']=3;row['cost']*=3
            result.append(row)
        return result

    def plan(self,legs,activity_start='11:00'):
        return {'itinerary':[{'day':1,'activities':[{'type':'attraction','start_time':activity_start,
                'end_time':'12:00','position':legs[-1]['end'],'transports':legs}]}]}

    def assertPass(self,plan):
        table,messages=common.Is_transport_correct(self.query,plan)
        self.assertEqual(int(table.loc[0].sum()),0,messages)

    def assertFail(self,plan):
        table,_=common.Is_transport_correct(self.query,plan)
        self.assertGreater(int(table.loc[0].sum()),0)

    def test_real_walk_taxi_chain_and_single_leg_compatibility(self):
        walk=self.leg('西安站','西安钟楼','walk','09:00')
        taxi=self.leg('西安钟楼','大雁塔','taxi','09:40')
        self.assertPass(self.plan(walk+taxi))
        old,_=common._single_segment_Is_transport_correct(self.query,self.plan(taxi))
        new,_=common.Is_transport_correct(self.query,self.plan(taxi))
        self.assertEqual(list(old.loc[0]),list(new.loc[0]))

    def test_real_xian_metro_and_taxi_chain(self):
        metro=self.leg('西安钟楼','大雁塔','metro','09:00')
        self.assertEqual([x['mode'] for x in metro],['walk','metro','walk'])
        taxi=self.leg('大雁塔','大兴善寺','taxi','09:25')
        self.assertPass(self.plan(metro+taxi))

    def test_explicit_cross_midnight_uses_real_sandbox_clock(self):
        walk=self.leg('西安站','西安钟楼','walk','23:45')
        self.assertTrue(walk[0]['end_time'].startswith('24:'))
        walk[0]['end_time']='00:'+walk[0]['end_time'][-2:]
        walk[0]['start_day']=1;walk[0]['end_day']=2
        plan={'itinerary':[{'day':1,'activities':[]},{'day':2,'activities':[
            {'type':'attraction','start_time':'00:30','end_time':'01:30',
             'position':'西安钟楼','transports':walk}]}]}
        self.assertPass(plan)
        walk[0].pop('start_day');walk[0].pop('end_day')
        with self.assertRaises(LookupError):common.Is_transport_correct(self.query,plan)

    def test_disconnected_metro_is_not_fabricated(self):
        answer=self.provider.goto(city='西安',start='西安站',end='大雁塔',
                                  start_time='09:00',transport_type='metro')
        self.assertEqual(answer,'No solution: disconnected subway graph')

    def test_endpoint_time_and_cost_errors_still_fail(self):
        walk=self.leg('西安站','西安钟楼','walk','09:00')
        taxi=self.leg('西安钟楼','大雁塔','taxi','09:40')
        for mutation in ('gap','overlap','after_activity','price','zero_cars','nan'):
            legs=deepcopy(walk+taxi)
            if mutation=='gap':legs[1]['start']='大兴善寺'
            if mutation=='overlap':legs[1]['start_time']='09:20'
            if mutation=='after_activity':legs[1]['end_time']='11:05'
            if mutation=='price':legs[1]['price']+=9
            if mutation=='zero_cars':legs[1]['cars']=0
            if mutation=='nan':legs[1]['price']=float('nan')
            self.assertFail(self.plan(legs))

    def test_metro_ticket_count_must_cover_party(self):
        metro=self.leg('西安钟楼','大雁塔','metro','09:00')
        metro[1]['tickets']=2;metro[1]['cost']=metro[1]['price']*2
        self.assertFail(self.plan(metro))

    def test_missing_lookup_is_unknown(self):
        taxi=self.leg('西安钟楼','大雁塔','taxi','09:00')
        taxi[0]['end']='不存在的地点'
        with self.assertRaises(LookupError):common.Is_transport_correct(self.query,self.plan(taxi))

    def test_incomplete_metro_is_not_accepted(self):
        metro=self.leg('西安钟楼','大雁塔','metro','09:00')
        self.assertFail(self.plan(metro[:-1]))

    def test_historical_malformed_multileg_still_fails(self):
        plan=json.loads((FIXTURES/'x11e026.plan.json').read_text(encoding='utf-8'))
        query=json.loads((FIXTURES/'x11e026.query.json').read_text(encoding='utf-8'))
        table,_=common.Is_transport_correct(query,plan)
        self.assertGreater(int(table.loc[0].sum()),0)

    def test_real_outbound_transfer_still_uses_origin_city(self):
        plan=json.loads((FIXTURES/'x11h004.plan.json').read_text(encoding='utf-8'))
        query=json.loads((FIXTURES/'x11h004.query.json').read_text(encoding='utf-8'))
        table,messages=common.Is_transport_correct(query,plan)
        self.assertEqual(int(table.loc[0].sum()),0,messages)


class CoordinateTests(unittest.TestCase):
    def test_order_determined_per_record(self):
        ref={'latitude':34.25,'longitude':108.95}
        a=_normalize_station_position('34.18466,108.94125',ref)
        b=_normalize_station_position('108.94125,34.18466',ref)
        self.assertEqual(a['coordinate_order'],'latitude_longitude')
        self.assertEqual(b['coordinate_order'],'longitude_latitude')
        self.assertEqual(a['normalized_position'],b['normalized_position'])
    def test_invalid_and_wrong_city_are_unknown(self):
        ref={'latitude':34.25,'longitude':108.95}
        for s in ('nan,108.9','120.1,30.2','34.2,34.3','bad',''):
            self.assertEqual(_normalize_station_position(s,ref)['state'],'unknown',s)
        self.assertEqual(_normalize_station_position('34.2,108.9',None)['state'],'unknown')
    def test_raw_source_and_evidence_retained(self):
        provider=Transportation();record=provider.station_coordinate_evidence['xian'][0]
        self.assertEqual(record['raw_position'],'34.18466,108.94125')
        self.assertEqual(record['normalized_position'],[34.18466,108.94125])
        self.assertEqual(len(record['source_sha256']),64)
        self.assertEqual(len(record['reference']['source_sha256']),64)

if __name__=='__main__':unittest.main()
