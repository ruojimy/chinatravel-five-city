"""Expansion invariants and official adapter wiring; fixtures are synthetic."""
from pathlib import Path
import copy,gzip,hashlib,importlib.util,json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.expansion_contract import (FIELDS,VERSION,validate_record,discovery_summary,
    validate_evidence,validate_claim,validate_tag)
from shorttrip.freshness import field_policy
NOW='2026-10-22T09:00:00+00:00'

def fixture(kind='attraction',*,complete=True,synthetic=True):
    values={'attraction':{'id':1,'name':'合成景点','type':'历史古迹','lat':30.1,'lon':110.1,
              'opentime':'09:00','endtime':'17:00','price':20,'recommendmintime':1,'recommendmaxtime':2},
      'restaurant':{'id':2,'name':'合成餐厅','lat':30.11,'lon':110.11,'price':30,'cuisine':'本地菜',
              'opentime':'10:00','endtime':'21:00','recommendedfood':''},
      'accommodation':{'id':3,'name':'合成酒店','hotelname_en':'','featurehoteltype':'经济型',
              'lat':30.12,'lon':110.12,'price':200,'numbed':2},
      'poi':{'name':'合成车站','position':[30.0,110.0]},
      'metro_station':{'name':'合成地铁站','position':'110.0,30.0','line':'合成一号线'},
      'train':{'TrainID':'SYN001','TrainType':'合成列车','From':'合成始发站','To':'合成到达站',
               'BeginTime':'08:00','EndTime':'09:00','Duration':1,'Cost':100},
      'flight':{'FlightID':'SYNFL001','From':'合成始发机场','To':'合成到达机场',
               'BeginTime':'08:00','EndTime':'09:00','Duration':1,'Cost':500}}
    data=values[kind]
    if not complete:
        for k in data:
            if k not in ('name','TrainID','FlightID'):data[k]=None
    name=data.get('name') or data.get('TrainID') or data.get('FlightID')
    policies={k:field_policy(k,kind) for k in data}
    return {'schema_version':VERSION,'record_id':'fixture:'+kind,'language':'zh','kind':kind,
      'city':'合成测试城','name':name,'data':data,
      'tags':[{'tag':'kind','value':kind,'basis':'dataset_section','status':'synthetic_fixture',
               'policy_id':'identity','source_time_ref':'record.observed_at','valid_until':None}],
      'source_id':'synthetic_fixture','source_url':'https://fixture.invalid/'+kind,
      'source_locator':{'fixture':'not_real_data'},'source_published_at':None,
      'source_updated_at':None,'observed_at':NOW,'retrieved_at':NOW,'catalogued_at':NOW,
      'valid_from':None,'valid_until':None,'field_policies':policies,
      'field_provenance':{k:{'source_id':'synthetic_fixture','source_url':'https://fixture.invalid/'+kind,
         'observed_at':NOW,'status':'synthetic' if synthetic else 'source_value'} for k in data},
      'authority':'synthetic_fixture','licence_status':'allowed','coordinate_system':'WGS84',
      'coordinate_order':{'poi':'latitude,longitude','metro_station':'longitude,latitude',
        'train':'not_applicable','flight':'not_applicable'}.get(kind,'named_lat_lon_columns'),
      'trust_status':'synthetic_fixture','entity_verified':complete,'needs_live_verification':True,
      'uncertainty_flags':['synthetic_not_real_expansion'],'synthetic':synthetic,
      **({'start_city':'合成起点城','end_city':'合成测试城'} if kind in ('train','flight') else {})}

class ContractTests(unittest.TestCase):
    def test_source_relevance_and_city_conflicts_block_even_complete_fresh_records(self):
        for flag in ('untrusted_website_source_requires_review','source_city_conflicts_with_research_window','source_property_address_conflicts_require_review'):
            r=fixture(synthetic=False)
            self.assertTrue(validate_record(r,now=NOW)['planning_ready'])
            r['uncertainty_flags'].append(flag)
            gate=validate_record(r,now=NOW)
            self.assertTrue(gate['discovery_ok']);self.assertFalse(gate['planning_ready'])
            self.assertIn(flag,gate['planning_blockers'])
    def test_seven_kinds_accept_explicit_unknowns_for_discovery(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                r=fixture(kind,complete=False)
                v=validate_record(r,now=NOW)
                self.assertTrue(v['discovery_ok'],v);self.assertFalse(v['planning_ready'])
    def test_seven_complete_fixtures_only_under_explicit_opt_in(self):
        for kind in FIELDS:
            with self.subTest(kind=kind):
                v=validate_record(fixture(kind),now=NOW,allow_synthetic=True)
                self.assertTrue(v['planning_ready'],v)
    def test_no_default_mutation(self):
        r=fixture(complete=False);before=copy.deepcopy(r);validate_record(r,now=NOW)
        self.assertEqual(r,before);self.assertIsNone(r['data']['price'])
    def test_synthetic_not_admitted_as_real(self):
        self.assertFalse(validate_record(fixture(),now=NOW)['planning_ready'])
    def test_real_zero_requires_source_evidence_not_default(self):
        r=fixture(synthetic=False);r['data']['price']=0
        self.assertTrue(validate_record(r,now=NOW)['planning_ready'])
        r['field_provenance']['price']['status']='estimated'
        self.assertFalse(validate_record(r,now=NOW)['planning_ready'])
    def test_import_time_does_not_renew_observed_time(self):
        r=fixture(synthetic=False)
        r['field_provenance']['price']['observed_at']=None
        self.assertIn('unknown_field_age:price',validate_record(r,now=NOW)['planning_blockers'])
    def test_expired_field_blocks_frozen_planning(self):
        r=fixture(synthetic=False);r['field_provenance']['price']['observed_at']='2026-10-20T09:00:00Z'
        self.assertIn('expired_field:price',validate_record(r,now=NOW)['planning_blockers'])
    def test_future_deadline_is_allowed(self):
        r=fixture(synthetic=False);r['valid_until']='2026-10-23T09:00:00Z'
        self.assertTrue(validate_record(r,now=NOW)['planning_ready'])
    def test_unsupported_coordinate_system_not_routable(self):
        r=fixture(synthetic=False);r['coordinate_system']='GCJ02'
        self.assertFalse(validate_record(r,now=NOW)['planning_ready'])
    def test_wrong_position_order_or_range_rejected(self):
        r=fixture('poi');r['data']['position']=[110,30]
        self.assertFalse(validate_record(r,now=NOW)['discovery_ok'])
    def test_malformed_clock_and_number_rejected(self):
        r=fixture();r['data']['opentime']='25:10';r['data']['price']=float('nan')
        self.assertFalse(validate_record(r,now=NOW)['discovery_ok'])
    def test_room_count_unknown_not_one_bed(self):
        r=fixture('accommodation');r['data']['numbed']=None
        self.assertIn('numbed',validate_record(r,now=NOW)['missing_planning_fields'])
    def test_missing_field_keys_rejected(self):
        r=fixture();del r['data']['endtime']
        self.assertIn('missing_data_key:endtime',validate_record(r,now=NOW)['errors'])
    def test_duplicate_ids_disclosed(self):
        self.assertFalse(discovery_summary([fixture(),fixture()],now=NOW)['complete'])
    def test_evidence_digest_and_claim_quote(self):
        raw='合成门票20元';e={'evidence_id':'e','source_id':'synthetic_fixture','source_url':'https://fixture.invalid',
          'retrieved_at':NOW,'raw_text':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
          'authority':'synthetic_fixture','licence_status':'allowed','source_published_at':None,
          'source_updated_at':None,'observed_at':NOW}
        c={'claim_id':'c','entity_id':'p','evidence_id':'e','field':'price','value':20,'unit':'CNY',
          'quote':raw,'source_id':e['source_id'],'source_url':e['source_url'],'observed_at':NOW,
          'retrieved_at':NOW,'valid_until':None,'context':{}}
        self.assertTrue(validate_evidence(e)['ok']);self.assertTrue(validate_claim(c,{'e':e})['ok'])
        c['quote']='价格99元';self.assertFalse(validate_claim(c,{'e':e})['ok'])
        e['raw_sha256']='x';self.assertFalse(validate_evidence(e)['ok'])
    def test_tag_unresolved_claim_rejected(self):
        tag=fixture()['tags'][0];tag['claim_id']='missing'
        self.assertFalse(validate_tag(tag,claims_by_id={})['ok'])
    def test_string_columns_reject_compound_or_numeric_values(self):
        for field,value in (('name',['景点']),('type',12),('opentime',{'time':'09:00'})):
            r=fixture();r['data'][field]=value
            self.assertFalse(validate_record(r,now=NOW)['discovery_ok'])
    def test_negative_nonfinite_and_bool_numbers_rejected(self):
        for value in (-1,float('inf'),float('-inf'),float('nan'),True,'20'):
            r=fixture();r['data']['price']=value
            self.assertFalse(validate_record(r,now=NOW)['discovery_ok'],value)
    def test_naive_datetime_rejected_for_every_clock(self):
        for field in ('source_published_at','source_updated_at','observed_at','retrieved_at','catalogued_at','valid_from','valid_until'):
            r=fixture();r[field]='2026-10-22T09:00:00'
            self.assertFalse(validate_record(r,now=NOW)['discovery_ok'],field)
    def test_field_source_url_disagreement_is_not_silently_accepted(self):
        r=fixture();r['field_provenance']['price']['source_url']='https://different.invalid/'
        self.assertIn('field_source_url_mismatch:price',validate_record(r,now=NOW)['errors'])
    def test_field_validity_cannot_end_before_observation(self):
        r=fixture();r['field_provenance']['price']['valid_until']='2026-10-20T08:00:00Z'
        self.assertIn('field_validity_order:price',validate_record(r,now=NOW)['errors'])
    def test_bad_compound_metadata_reports_errors_instead_of_crashing(self):
        for field,value in (('kind',[]),('field_policies',[]),('field_provenance',[]),
                            ('source_locator',[]),('uncertainty_flags',{}),('tags',{})):
            r=fixture();r[field]=value
            self.assertFalse(validate_record(r,now=NOW)['discovery_ok'],field)
        self.assertFalse(discovery_summary([None,{'record_id':[]}],now=NOW)['complete'])
    def test_bad_tag_compound_values_rejected(self):
        for field,value in (('policy_id',[]),('tag',{}),('basis',1),('value',float('nan'))):
            tag=fixture()['tags'][0];tag[field]=value
            self.assertFalse(validate_tag(tag)['ok'],field)
    def test_gzip_jsonl_stream_reader(self):
        spec=importlib.util.spec_from_file_location('p12_verify_schema',ROOT/'scripts/p12_verify_schema.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'records.jsonl.gz'
            with gzip.open(file,'wt',encoding='utf-8') as stream:
                stream.write(json.dumps(fixture(),ensure_ascii=False)+'\n')
                stream.write(json.dumps(fixture('restaurant'),ensure_ascii=False)+'\n')
            self.assertEqual(len(list(module.records(file))),2)
    def test_bad_evidence_text_clock_and_digest_rejected(self):
        e={'evidence_id':[],'source_id':'p','source_url':{},'retrieved_at':'2026-10-22T09:00:00',
           'raw_text':{},'raw_sha256':'x','authority':'p','licence_status':'allowed',
           'source_published_at':None,'source_updated_at':None,'observed_at':None}
        self.assertFalse(validate_evidence(e)['ok'])
    def test_claim_wrong_source_reference_and_compound_types_rejected(self):
        c={'claim_id':'c','entity_id':'p','evidence_id':[],'field':{},'value':float('inf'),
           'unit':{},'quote':[],'source_id':'p','source_url':'https://a.invalid',
           'observed_at':None,'retrieved_at':NOW,'valid_until':None,'context':[]}
        self.assertFalse(validate_claim(c,{})['ok'])
        self.assertFalse(validate_claim({'evidence_id':'e'},{'e':'not-an-object'})['ok'])
    def test_provenance_unknown_source_or_conflict_cannot_be_ready(self):
        r=fixture(synthetic=False);r['trust_status']='conflict'
        self.assertFalse(validate_record(r,now=NOW)['planning_ready'])
        r=fixture(synthetic=False);r['field_provenance']['price']['source_id']='not-referenced'
        self.assertIn('field_external_source_requires_evidence_ref:price',validate_record(r,now=NOW)['errors'])

class AdapterTests(unittest.TestCase):
    def test_invalid_record_rejects_batch_without_changing_global_tools(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        from chinatravel.symbol_verification import commonsense_constraint as common
        before=common.attractions
        bad=fixture('restaurant');del bad['data']['price']
        with self.assertRaises(ValueError):
            ExpandedEnvironment([fixture(),bad],version='rejected',now=NOW,allow_synthetic=True)
        self.assertIs(common.attractions,before)
    def test_real_raw_route_requires_gated_live_pipeline_even_if_named_amap(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        variants=[{'source_id':'amap','retrieved_at':NOW},
                  {'source_id':'amap','retrieved_at':'2020-01-01T00:00:00Z'},
                  {'source_id':'amap','retrieved_at':NOW,'travel_date':'2020-01-01'},
                  {'source_id':'fake','retrieved_at':NOW}]
        for extra in variants:
            with self.subTest(extra=extra),self.assertRaises(NotImplementedError):
                with ExpandedEnvironment([fixture()],version='reject',now=NOW,allow_synthetic=True,
                         city_slugs={'合成测试城':'synthetic-city'},
                         routes=[{'source_ref':'unproven','synthetic':False,**extra}]):pass
    def test_real_raw_intercity_not_allowed(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        with self.assertRaises(NotImplementedError):
            with ExpandedEnvironment([fixture()],version='reject',now=NOW,allow_synthetic=True,
                city_slugs={'合成测试城':'synthetic-city'},
                intercity=[{'source_ref':'not evidence','retrieved_at':NOW,'synthetic':False}]):pass
    def test_synthetic_route_cannot_impersonate_amap(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        with self.assertRaises(ValueError):
            with ExpandedEnvironment([fixture()],version='reject',now=NOW,allow_synthetic=True,
                city_slugs={'合成测试城':'synthetic-city'},routes=[{'source_id':'amap',
                'source_ref':'fake-amap','retrieved_at':NOW,'synthetic':True}]):pass

    def test_official_schema_commonsense_and_hard_dsl_on_synthetic_fixture(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        from shorttrip.checker import check_plan
        records=[fixture(),fixture('restaurant'),fixture('poi')]
        def route(a,b,depart,arrive):
            return {'city':'合成测试城','start':a,'end':b,'mode':'taxi','departure':depart,
              'source_id':'synthetic_fixture','source_ref':'explicit synthetic fixture only',
              'retrieved_at':NOW,'synthetic':True,'legs':[{'start':a,'end':b,'mode':'taxi',
                'start_time':depart,'end_time':arrive,'cost':10,'distance':2}]}
        routes=[route('合成车站','合成景点','09:00','09:10'),
                route('合成景点','合成餐厅','11:00','11:10'),
                route('合成餐厅','合成车站','12:00','12:10')]
        journeys=[]
        for origin,destination,start,end,ident,from_,to_ in (
          ('合成起点城','合成测试城','08:00','09:00','SYN-GO','合成始发站','合成车站'),
          ('合成测试城','合成起点城','13:00','14:00','SYN-BACK','合成车站','合成始发站')):
            journeys.append({'start_city':origin,'end_city':destination,'mode':'train',
              'source_ref':'synthetic not a real schedule','retrieved_at':NOW,'synthetic':True,
              'data':{'TrainID':ident,'TrainType':'合成列车','From':from_,'To':to_,
                      'BeginTime':start,'EndTime':end,'Duration':1,'Cost':100}})
        def transports(i):return [{**r,'price':r['cost'],'cars':1} for r in routes[i]['legs']]
        plan={'people_number':1,'start_city':'合成起点城','target_city':'合成测试城','itinerary':[
          {'day':1,'activities':[
           {'type':'train','TrainID':'SYN-GO','start':'合成始发站','end':'合成车站',
            'start_time':'08:00','end_time':'09:00','price':100,'cost':100,'tickets':1,'transports':[]},
           {'type':'attraction','position':'合成景点','start_time':'09:10','end_time':'11:00',
            'price':20,'cost':20,'tickets':1,'transports':transports(0)},
           {'type':'lunch','position':'合成餐厅','start_time':'11:30','end_time':'12:00',
            'price':30,'cost':30,'tickets':1,'transports':transports(1)},
           {'type':'train','TrainID':'SYN-BACK','start':'合成车站','end':'合成始发站',
            'start_time':'13:00','end_time':'14:00','price':100,'cost':100,'tickets':1,
            'transports':transports(2)}]}]}
        q={'uid':'synthetic_adapter_contract','days':1,'people_number':1,
           'start_city':'合成起点城','target_city':'合成测试城',
           'nature_language':'合成测试：一天、一人、预算500元。',
           'hard_logic_py':['result=(day_count(plan)==1)','result=(people_count(plan)==1)',
                'total_cost=0\nfor activity in allactivities(plan):\n    total_cost+=activity_cost(activity)\n    total_cost+=innercity_transport_cost(activity_transports(activity))\nresult=(total_cost<=500)']}
        with ExpandedEnvironment(records,version='synthetic-interface-test',now=NOW,allow_synthetic=True,
               city_slugs={'合成测试城':'synthetic-city'},routes=routes,intercity=journeys) as env:
            report=check_plan(q,plan).to_dict()
            self.assertTrue(report['all_ok'],report)
            wrong=copy.deepcopy(plan);wrong['itinerary'][0]['activities'][1]['price']=999
            bad=check_plan(q,wrong).to_dict()
            self.assertTrue(bad['schema_ok']);self.assertFalse(bad['commonsense_ok'])
            output=ROOT/'results/p12_expansion/synthetic_adapter_smoke.json'
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps({'synthetic':True,'count_as_real_expansion':False,
              'checked_at':NOW,'version':env.version,'query':q,'plan':plan,'report':report,
              'deliberately_corrupted_price_report':bad,'registration':env.registration_report},
              ensure_ascii=False,indent=2),encoding='utf-8')

    def test_every_verifier_and_world_see_same_snapshot_and_restore(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        from chinatravel.symbol_verification import commonsense_constraint as c,concept_func as f,hard_constraint as h
        from chinatravel.environment import language
        before=(c.attractions,c._TOOLS_BY_LANG,h._TOOLS_BY_LANG,f._TOOLS_BY_LANG,language.CITY_NAMES)
        records=[fixture(k) for k in ('attraction','restaurant','accommodation','poi')]
        with ExpandedEnvironment(records,version='synthetic-only',now=NOW,allow_synthetic=True,
                                 city_slugs={'合成测试城':'synthetic-city'}) as env:
            world=env.world()
            self.assertIs(world.attractions,c.attractions)
            self.assertIs(h._TOOLS_BY_LANG['zh'][2],c.attractions)
            self.assertIs(f._TOOLS_BY_LANG['zh']['attractions'],c.attractions)
            self.assertIn('合成景点',c.attractions.data['合成测试城']['name'].tolist())
            self.assertEqual(world.poi.search('合成测试城','合成景点'),(30.1,110.1))
            self.assertEqual(len(env.discover('合成测试城')),4)
            self.assertIsInstance(world.transportation.goto('合成测试城','合成车站','合成景点','09:00','taxi'),str)
            self.assertEqual(world.intercitytransport.select('上海','合成测试城','train').shape[0],0)
        self.assertIs(c.attractions,before[0]);self.assertIs(c._TOOLS_BY_LANG,before[1])
        self.assertIs(h._TOOLS_BY_LANG,before[2]);self.assertIs(f._TOOLS_BY_LANG,before[3])
        self.assertIs(language.CITY_NAMES,before[4])
    def test_discovery_only_not_in_official_planning_tables(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        with ExpandedEnvironment([fixture(complete=False)],version='discovery-only',now=NOW,
                     city_slugs={'合成测试城':'synthetic-city'}) as env:
            self.assertEqual(len(env.discover('合成测试城')),1)
            self.assertTrue(env.tools['attractions'].data['合成测试城'].empty)
            self.assertIsInstance(env.tools['poi'].search('合成测试城','合成景点'),str)
    def test_context_exception_restores_and_allows_next_run(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        with self.assertRaises(ValueError):
            with ExpandedEnvironment([fixture()],version='v',now=NOW,allow_synthetic=True):pass
        with ExpandedEnvironment([fixture()],version='v2',now=NOW,allow_synthetic=True,
                 city_slugs={'合成测试城':'synthetic-city'}) as env:self.assertTrue(env.tools)
    def test_exact_route_evidence_no_retiming(self):
        from shorttrip.expanded_environment import ExpandedEnvironment
        route={'city':'合成测试城','start':'合成车站','end':'合成景点','mode':'taxi','departure':'09:00',
          'source_id':'synthetic_fixture','source_ref':'explicit synthetic test','retrieved_at':NOW,'synthetic':True,
          'legs':[{'start':'合成车站','end':'合成景点','mode':'taxi','start_time':'09:00',
                   'end_time':'09:10','cost':10,'distance':2}]}
        with ExpandedEnvironment([fixture(),fixture('poi')],version='v',now=NOW,allow_synthetic=True,
                    city_slugs={'合成测试城':'synthetic-city'},routes=[route]) as env:
            t=env.tools['transportation']
            self.assertEqual(t.goto('合成测试城','合成车站','合成景点','09:00','taxi'),route['legs'])
            self.assertIsInstance(t.goto('合成测试城','合成车站','合成景点','09:01','taxi'),str)

if __name__=='__main__':unittest.main(verbosity=2)
