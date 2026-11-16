from copy import deepcopy
from datetime import date,timedelta
from hashlib import sha256
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1]/'src/sandbox_runtime/evaluator'
sys.path.insert(0,str(HERE))
from date_timeline import validate_timeline,parse_amap_rail_clock
from score_date_v4 import merge
from source_duration import DurationResolver
from attraction_prices import AttractionPriceEvidence

def train(clock_start='18:20',clock_end='06:51',**kw):
    return dict(type='train',start_time=clock_start,end_time=clock_end,transports=[],**kw)
def attraction(start='07:29',end='08:29',transports=None,**kw):
    return dict(type='attraction',start_time=start,end_time=end,transports=transports or [],**kw)
def plan(*days):return {'itinerary':[{'day':i+1,'activities':list(acts)} for i,acts in enumerate(days)]}

class TimelineTests(unittest.TestCase):
    def test_normal_day(self):
        z=validate_timeline({'days':1},plan([train('07:00','08:00',arrival_day=1),attraction('09:00','10:00')]))
        self.assertEqual(z['state'],'pass')
    def test_valid_overnight_explicit_day(self):
        z=validate_timeline({'days':2},plan([train(arrival_day=2)],[attraction()]))
        self.assertEqual(z['state'],'pass')
    def test_overnight_same_day_activity_fails_even_with_no_arrival_day(self):
        z=validate_timeline({'days':2},plan([train(),attraction()],[]))
        self.assertEqual(z['state'],'fail')
        self.assertIn('activity_overlaps_previous',[x['code'] for x in z['issues']])
    def test_final_day_overrun_fails(self):
        z=validate_timeline({'days':1},plan([train()]))
        self.assertEqual(z['state'],'fail')
        self.assertIn('activity_exceeds_trip_days',[x['code'] for x in z['issues']])
    def test_missing_arrival_evidence_unknown_not_automatically_pass(self):
        z=validate_timeline({'days':2},plan([train()],[attraction()]))
        self.assertEqual(z['state'],'unknown')
        self.assertIn('intercity_arrival_day_not_explicit',[x['code'] for x in z['issues']])
    def test_explicit_iso_dates(self):
        z=validate_timeline({'days':2,'start_date':'2026-11-20'},
                            plan([train(end_date='2026-11-21')],[attraction()]))
        self.assertEqual(z['state'],'pass')
    def test_conflicting_day_and_date_fails(self):
        z=validate_timeline({'days':2,'start_date':'2026-11-20'},
                            plan([train(end_date='2026-11-21',arrival_day=1)],[attraction()]))
        self.assertEqual(z['state'],'fail')
        self.assertIn('end_day_date_conflict',[x['code'] for x in z['issues']])
    def test_unknown_duration_when_days_missing(self):
        z=validate_timeline({},plan([train()]))
        self.assertEqual(z['state'],'unknown')
    def test_arrival_day_explicit_but_overlap_fails(self):
        z=validate_timeline({'days':2},plan([train(arrival_day=2)],[attraction('06:00','08:00')]))
        self.assertEqual(z['state'],'fail')
    def test_previous_overnight_collision_with_local_transport(self):
        legs=[{'start_time':'06:30','end_time':'07:15'}]
        z=validate_timeline({'days':2},plan([train(arrival_day=2)],[attraction('07:20','08:20',legs)]))
        self.assertEqual(z['state'],'fail')
        self.assertIn('transport_overlaps_previous',[x['code'] for x in z['issues']])
    def test_end_time_positive_same_day(self):
        z=validate_timeline({'days':1},plan([attraction('09:00','09:00')]))
        self.assertEqual(z['state'],'fail')
    def test_extended_amap_clock_is_preserved_and_normalized(self):
        self.assertEqual(parse_amap_rail_clock('30:51',1),
                         {'clock':'06:51','arrival_day':2,'source_clock':'30:51','day_offset':1})
        self.assertEqual(parse_amap_rail_clock('5051',2)['arrival_day'],4)
        with self.assertRaises(ValueError):parse_amap_rail_clock('24:60',1)
    def test_raw_extended_clock_not_mistaken_for_native_plan_time(self):
        z=validate_timeline({'days':2},plan([train(clock_end='30:51')],[]))
        self.assertEqual(z['state'],'unknown')
        self.assertIn('invalid_activity_time',[x['code'] for x in z['issues']])
    def test_positive_clock_order_can_still_mean_more_than_24_hours(self):
        act=train('08:00','09:00')
        resolver=lambda q,a:{'minutes':25*60}
        valid=validate_timeline({'days':2},plan([act],[attraction('10:00','11:00')]),resolver)
        self.assertEqual(valid['state'],'pass')
        invalid=validate_timeline({'days':2},plan([train('08:00','09:00'),attraction('10:00','11:00')],[]),resolver)
        self.assertEqual(invalid['state'],'fail')
        self.assertIn('activity_overlaps_previous',[x['code'] for x in invalid['issues']])
    def test_positive_clock_order_without_duration_unknown(self):
        z=validate_timeline({'days':1},plan([train('08:00','09:00')]))
        self.assertEqual(z['state'],'unknown')
    def test_explicit_arrival_day_conflicts_with_verified_duration(self):
        z=validate_timeline({'days':2},plan([train('08:00','09:00',arrival_day=1)],[]),
                            lambda q,a:{'minutes':25*60})
        self.assertEqual(z['state'],'fail')
        self.assertIn('arrival_day_conflicts_with_source_duration',[x['code'] for x in z['issues']])
    def test_2400_boundary_allows_next_day_midnight(self):
        z=validate_timeline({'days':2},plan([attraction('23:00','24:00')],
                                            [attraction('00:00','01:00')]))
        self.assertEqual(z['state'],'pass')
    @patch.dict(os.environ, {'CHINATRAVEL_DATABASE_ROOT': ''})
    def test_source_duration_exact_record_and_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'chinatravel/environment/database/intercity_transport/train';db.mkdir(parents=True)
            rows=[{'TrainID':'G1','From':'甲站','To':'乙站','BeginTime':'08:00','EndTime':'09:00','Duration':25}]
            (db/'from_甲_to_乙.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
            resolver=DurationResolver(Path(td));q={'start_city':'甲','target_city':'乙'}
            a=train('08:00','09:00',TrainID='G1',start='甲站',end='乙站')
            self.assertEqual(resolver(q,a)['minutes'],1500)
            a['end']='其他站';self.assertIsNone(resolver(q,a))
    def test_missing_day_and_intercity_zero_clock_unknown(self):
        z=validate_timeline({'days':1},plan([train('12:00','12:00')]))
        self.assertEqual(z['state'],'unknown')
    def test_existing_definite_failure_is_preserved(self):
        base={'schema':{'state':'fail'},'commonsense':{'state':'pass'},'hard':{'state':'pass'},
              'groups':[{'name':'Is_time_correct','state':'pass'}]}
        out=merge(base,{'days':2},plan([train(arrival_day=2)],[attraction()]))
        self.assertEqual(out['overall'],'fail')
        self.assertEqual(base['groups'][0]['state'],'pass')

class WrapperTests(unittest.TestCase):
    def test_write_once_and_hash_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=root/'query.json';p=root/'plan.json';a=root/'audit.json';b=root/'base.json';out=root/'final.json'
            def write(path,obj):path.write_text(json.dumps(obj),encoding='utf-8')
            write(q,{'uid':'q1','days':2});write(p,plan([train()],[attraction(price=0,position='unknown')]));write(a,{'uid':'q1'})
            h=lambda path:sha256(path.read_bytes()).hexdigest()
            write(b,{'target_root':str(root),'query_sha256':h(q),'plan_sha256':h(p),'query_audit_sha256':h(a),
                     'schema':{'state':'pass'},'commonsense':{'state':'pass'},'hard':{'state':'pass'},
                     'groups':[{'name':'Is_time_correct','state':'pass'},
                               {'name':'Is_attractions_correct','state':'pass','cells':{'Incorrect price Information of attraction':0}}],
                     'overall':'pass'})
            before=b.read_bytes();cmd=[sys.executable,str(HERE/'score_date_v4.py'),'--target-root',str(root),
                 '--query',str(q),'--plan',str(p),'--audit',str(a),'--output',str(out),'--base-score',str(b)]
            first=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['overall'],'unknown')
            self.assertEqual(b.read_bytes(),before)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
            q.write_text('{}',encoding='utf-8');out.unlink()
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)

    @patch.dict(os.environ, {'CHINATRAVEL_DATABASE_ROOT': ''})
    def test_zero_assumption_is_unknown_but_other_failure_survives(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'chinatravel/environment/database/attractions/xian';folder.mkdir(parents=True)
            (folder/'attractions.csv').write_text('id,name,price\n12,测试景点,\n',encoding='utf-8')
            evidence=root/'search.json';evidence.write_text(json.dumps({'searched_at':'2026-11-15T14:00:00Z',
                  'request_queries':['测试景点 票价','测试景点 门票'],'shiyuan_search':'no matching price'},ensure_ascii=False),encoding='utf-8')
            snapshot=root/'snapshot.json'
            snapshot.write_text(json.dumps({'attraction_prices':[{'city':'西安','name':'测试景点','record_id':'attraction:xian:12',
                'price':0,'status':'user_authorized_zero_assumption_after_search','evidence_path':'search.json',
                'evidence_sha256':sha256(evidence.read_bytes()).hexdigest()}]},ensure_ascii=False),encoding='utf-8')
            prices=AttractionPriceEvidence(root,snapshot);q={'days':1,'target_city':'西安'}
            a=attraction('09:00','10:00',position='测试景点',price=0)
            model=plan([a]);legacy={'name':'Is_attractions_correct','state':'fail','cells':
                  {'Incorrect price Information of attraction':1,'Visiting attraction in their closed time':0}}
            base={'schema':{'state':'pass'},'hard':{'state':'pass'},'groups':[{'name':'Is_time_correct','state':'pass'},legacy]}
            result=merge(base,q,model,None,prices)
            self.assertEqual(result['overall'],'unknown')
            self.assertEqual(result['conditional_zero_assumption']['overall'],'pass')
            self.assertTrue(result['conditional_zero_assumption']['applied'])
            self.assertEqual(result['groups'][1]['price_evidence'][0]['reason'],'assumed_or_undated_reference_price')
            broken=deepcopy(base);broken['groups'][1]['cells']['Visiting attraction in their closed time']=1
            self.assertEqual(merge(broken,q,model,None,prices)['overall'],'fail')
            self.assertEqual(merge(broken,q,model,None,prices)['conditional_zero_assumption']['overall'],'fail')

if __name__=='__main__':unittest.main()
