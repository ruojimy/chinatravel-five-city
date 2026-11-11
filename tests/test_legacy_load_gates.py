"""Legacy entry points cannot promote unqualified records. All data fictional."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from test_expansion_contract import fixture,NOW
from shorttrip.dynamic import bus
from shorttrip.dynamic.overlay import OverlayStore
from shorttrip.dynamic.records import DataRequest,CandidateRecord,FieldValue,QualityReport

def update(record):
    return {'request':{'kind':record['kind'],'city':record['city'],'name':record['name']},
            'expansion_envelope':record,'record':record,'evidence':[]}

def tool(kind='Attractions'):
    result=type(kind,(),{})();result.lang='zh'
    if kind=='Poi':result.data={'合成测试城':{}}
    else:result.data={'合成测试城':pd.DataFrame(columns=list(fixture()['data']))}
    return result

class BusGates(unittest.TestCase):
    def test_flat_legacy_apply_and_row_builder_rejected(self):
        flat={'kind':'attraction','city':'合成测试城','name':'合成景点','lat':30,'lon':110}
        target=tool()
        with patch.object(bus,'discover',return_value=[target]):
            self.assertEqual(bus.apply(flat).patched,0)
            with self.assertRaises(ValueError):bus._row_for('attraction',flat,target.data['合成测试城'],'合成测试城','zh')
        self.assertTrue(target.data['合成测试城'].empty)
    def test_discovery_unknowns_not_injected_or_defaulted(self):
        r=fixture(complete=False);target=tool();before=copy.deepcopy(r)
        with patch.object(bus,'discover',return_value=[target]):
            result=bus.apply(r,now=NOW,allow_synthetic=True)
        self.assertEqual(result.patched,0);self.assertEqual(r,before)
        self.assertTrue(target.data['合成测试城'].empty)
    def test_complete_synthetic_requires_opt_in_and_preserves_exact_values(self):
        r=fixture();r['data']['price']=0;r['data']['recommendmintime']=1.25;r['data']['recommendmaxtime']=4
        target=tool();poi=tool('Poi')
        with patch.object(bus,'discover',return_value=[target,poi]):
            self.assertEqual(bus.apply(r,now=NOW).patched,0)
            result=bus.apply(r,now=NOW,allow_synthetic=True)
        self.assertEqual(result.patched,2);self.assertEqual(result.status,'synthetic_fixture')
        row=target.data['合成测试城'].iloc[0].to_dict()
        self.assertEqual(row,r['data']);self.assertEqual(poi.data['合成测试城']['合成景点'],(30.1,110.1))
    def test_contradictory_flat_wrapper_cannot_override_envelope(self):
        result=bus.apply({'expansion_envelope':fixture(),'price':999},now=NOW,allow_synthetic=True)
        self.assertEqual(result.patched,0)
        self.assertIn('wrapper_data_mismatch:price',result.gate['errors'])
    def test_unregistered_city_preflight_causes_no_partial_poi_write(self):
        r=fixture();target=tool();target.data={};poi=tool('Poi')
        with patch.object(bus,'discover',return_value=[poi,target]):
            self.assertEqual(bus.apply(r,now=NOW,allow_synthetic=True).patched,0)
        self.assertEqual(poi.data['合成测试城'],{})

class OverlayGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=OverlayStore(Path(self.temp.name)/'overlay.sqlite')
    def tearDown(self):self.store.conn.close();self.temp.cleanup()
    def test_flat_legacy_add_is_quarantined_not_active(self):
        value={'request':{'kind':'attraction','city':'合成测试城'},'record':{'name':'旧记录','price':None}}
        self.store.add(value,now=NOW)
        self.assertEqual(self.store.last_gate['effective_status'],'quarantine')
        self.assertEqual(self.store.active(now=NOW),[])
        self.assertEqual(len(self.store.historical()),1)
    def test_unknown_envelope_quarantined(self):
        self.store.add(update(fixture(complete=False)),now=NOW)
        self.assertFalse(self.store.last_gate['planning_ready']);self.assertEqual(self.store.active(now=NOW),[])
    def test_synthetic_fixture_read_requires_opt_in_and_expiry_is_rechecked(self):
        self.store.add(update(fixture()),now=NOW,allow_synthetic=True)
        self.assertEqual(self.store.active(now=NOW),[])
        self.assertEqual(len(self.store.active(now=NOW,allow_synthetic=True)),1)
        self.assertEqual(self.store.active(now='2026-10-24T09:00:00Z',allow_synthetic=True),[])
    def test_request_scope_or_evidence_digest_mismatch_blocks(self):
        value=update(fixture());value['request']['city']='另一个城市'
        self.store.add(value,now=NOW,allow_synthetic=True)
        self.assertEqual(self.store.last_gate['effective_status'],'quarantine')
        value=update(fixture());value['evidence']=[{'source_id':'amap','raw_text':'anything','raw_sha256':'wrong'}]
        self.store.add(value,now=NOW,allow_synthetic=True)
        self.assertEqual(self.store.last_gate['effective_status'],'quarantine')
    def test_existing_legacy_active_row_readable_but_never_rehydrates(self):
        from shorttrip.dynamic.pipeline import rehydrate
        payload={'request':{'kind':'attraction','city':'合成测试城'},'record':{'name':'旧记录','price':0}}
        self.store.conn.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)',
            ('legacy','old','attraction','合成测试城','旧记录','active',json.dumps(payload),'{}',NOW))
        self.store.conn.commit()
        self.assertEqual(len(self.store.historical(status='active')),1)
        self.assertEqual(self.store.active(now=NOW),[])
        env=type('Env',(),{'invalidate':lambda self:None})()
        with patch.object(bus,'apply',side_effect=AssertionError('must not replay legacy flat record')):
            self.assertEqual(rehydrate(self.store,env,now=NOW),0)
        self.assertEqual(self.store.conn.execute("SELECT status FROM records WHERE uid='legacy'").fetchone()[0],'active')
    def test_nonfinite_bad_record_retained_only_as_quarantine_evidence(self):
        value=update(fixture());value['expansion_envelope']['data']['price']=float('nan')
        self.store.add(value,now=NOW,allow_synthetic=True)
        self.assertEqual(self.store.last_gate['effective_status'],'quarantine')
        self.assertIn('quarantine_raw_repr',self.store.historical()[0]['payload'])

class PipelineGates(unittest.TestCase):
    def test_bus_blocked_verdict_downgrades_the_pipeline_result(self):
        from shorttrip.dynamic.pipeline import UpdatePipeline
        from shorttrip.dynamic.bus import PatchOutcome
        request=DataRequest('合成测试城','attraction','合成景点',('name',),'mocked final-gate seam')
        candidate=CandidateRecord(request,{'name':FieldValue('合成景点')},'explicit synthetic seam')
        extractor=type('Extractor',(),{'extract':lambda self,*args:candidate})()
        gate=type('Gate',(),{'evaluate':lambda self,*args:QualityReport('accept',[])})()
        env=type('Env',(),{'attraction_table':lambda self,city:pd.DataFrame(),
                         'restaurant_table':lambda self,city:pd.DataFrame(),
                         'accommodation_table':lambda self,city:pd.DataFrame()})()
        # Mock only the earlier store seam to test propagation of a later bus
        # failure; no fictional data are passed through as real stored evidence.
        class FakeStore:
            last_gate={'planning_ready':True,'effective_status':'active','errors':[]}
            demoted=False
            def add(self,payload):return 'mocked-version'
            def quarantine_version(self,*args):
                self.demoted=True
                self.last_gate={'planning_ready':False,'effective_status':'quarantine','errors':['bus_blocked']}
        with tempfile.TemporaryDirectory() as tmp:
            store=FakeStore()
            pipeline=UpdatePipeline(env,store,sources=[],extractor=extractor,gate=gate,
                                   use_llm=False,record_dir=Path(tmp))
            with patch.object(bus,'apply',return_value=PatchOutcome(0,['blocked'],{},'blocked')):
                result=pipeline.run(request,expansion_envelope=fixture())
            self.assertFalse(result.accepted);self.assertEqual(result.quality.decision,'quarantine')
            self.assertTrue(store.demoted)

    def test_legacy_quality_accept_does_not_override_final_contract_quarantine(self):
        from shorttrip.dynamic.pipeline import UpdatePipeline
        request=DataRequest('合成测试城','attraction','合成景点',('name',),'synthetic gate test')
        candidate=CandidateRecord(request,{'name':FieldValue('合成景点')},'synthetic fixture')
        extractor=type('Extractor',(),{'extract':lambda self,*args:candidate})()
        gate=type('Gate',(),{'evaluate':lambda self,*args:QualityReport('accept',[])})()
        env=type('Env',(),{'attraction_table':lambda self,city:pd.DataFrame(),
                         'restaurant_table':lambda self,city:pd.DataFrame(),
                         'accommodation_table':lambda self,city:pd.DataFrame()})()
        with tempfile.TemporaryDirectory() as tmp:
            store=OverlayStore(Path(tmp)/'overlay.sqlite')
            pipeline=UpdatePipeline(env,store,sources=[],extractor=extractor,gate=gate,
                                   use_llm=False,record_dir=Path(tmp)/'logs')
            with patch.object(bus,'apply',side_effect=AssertionError('must block before live tools')):
                result=pipeline.run(request)
            self.assertFalse(result.accepted);self.assertEqual(result.quality.decision,'quarantine')
            self.assertEqual(result.patched_instances,0)
            saved=json.loads(next((Path(tmp)/'logs').glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(saved['load_gate']['effective_status'],'quarantine')
            self.assertEqual(saved['quality']['decision'],'quarantine')
            store.conn.close()

class AmbiguousNames(unittest.TestCase):
    def test_same_named_branches_retained_discovery_but_not_planning(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        a=fixture('accommodation');b=copy.deepcopy(a);b['record_id']='different-branch';b['data']['lat']=30.2
        env=ExpandedEnvironment([a,b],version='synthetic-name-test',now=NOW,allow_synthetic=True,
                                city_slugs={'合成测试城':'synthetic-city'})
        self.assertEqual(len(env.discover('合成测试城')),2);self.assertEqual(env.ready,[])
        self.assertEqual(len(env.ambiguous_names),1)
    def test_duplicate_record_id_still_rejected(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        a=fixture();b=copy.deepcopy(a)
        with self.assertRaises(ValueError):ExpandedEnvironment([a,b],version='bad',now=NOW)

if __name__=='__main__':unittest.main(verbosity=2)
