"""Controlled policy replay. All claims are synthetic, never travel evidence."""
import copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow,fresh_state,reconcile,POLICIES
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'results/p18_dynamic_eval/policy_replay'
NOW='2026-10-23T02:16:49+00:00'
REG={
 'owner':{'authority':'primary_operator','independence_group':'owner','allowed_hosts':['owner.example.invalid'],'supports':list(POLICIES)},
 'independent':{'authority':'structured_provider','independence_group':'independent','allowed_hosts':['independent.example.invalid'],'supports':list(POLICIES)},
 'mirror':{'authority':'structured_provider','independence_group':'owner','allowed_hosts':['mirror.example.invalid'],'supports':list(POLICIES)},
 'amap':{'authority':'official_api','independence_group':'amap','allowed_hosts':['restapi.amap.com'],'supports':['route_duration','route_fare','weather_now','weather_forecast']}}

def claim(field='theme',source='owner',value=True,**kw):
 raw=json.dumps({'value':value},ensure_ascii=False)
 c={'claim_id':source+'-'+field,'entity_id':'synthetic:venue','field':field,'source_id':source,
    'source_url':'https://restapi.amap.com/api' if source=='amap' else 'https://'+source+'.example.invalid/item',
    'entity_verified':True,'extraction_verified':True,'licence_status':'allowed','value':value,'unit':None,
    'raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
    'observed_at':'2026-10-23T02:15:00+00:00','source_updated_at':None,'source_published_at':None,
    'retrieved_at':'2026-10-23T02:16:00+00:00','context':{}}
 c.update(kw);return c

def pair(field='theme',value=True,**kw):return [claim(field,'owner',value,**kw),claim(field,'independent',value,**kw)]

def main():
 OUT.mkdir(exist_ok=False);protocol=json.loads((OUT.parent/'protocol.json').read_text());cases=[]
 def add(cid,description,claims,field='theme',context=None,expected=True,status=None):
  cases.append({'case_id':cid,'fixture':True,'description':description,'field':field,'claims':claims,'context':context or {},
     'expected_retrieval_required':expected,'expected_status':status,'label_basis':'Explicit research policy and fixture interventions, not human-labelled real-world truth'})
 add('P01','Fresh independent theme support: reuse static',pair(),expected=False,status='corroborated')
 add('P02','Absent field',[],status='unverified')
 add('P03','Expired theme observations',pair(observed_at='2025-01-01T00:00:00+00:00'),status='unverified')
 add('P04','Unknown source clocks',pair(observed_at=None),status='unverified')
 add('P05','New retrieval must not renew old observation',pair(observed_at='2025-01-01T00:00:00+00:00',retrieved_at=NOW),status='unverified')
 add('P06','Same owner and mirror do not create independence',[claim(),claim(source='mirror')],status='single_source')
 add('P07','Conflicting independently sourced values',[claim(),claim(source='independent',value=False)],status='conflict')
 add('P08','Wrong requested entity',[claim(entity_id='synthetic:other')],status='unverified')
 add('P09','Claimed authority with wrong URL host',[claim(source_url='https://unregistered.example.invalid/')],status='unverified')
 add('P10','Unsupported source-field authority',[claim('theme',source='amap')],status='unverified')
 add('P11','Tampered quote',[claim(quote='not present in original')],status='unverified')
 add('P12','Tampered evidence hash',[claim(raw_sha256='0'*64)],status='unverified')
 weather={'adcode':'430100','travel_date':'2026-10-24'}
 add('P13','Forecast outside coverage',[claim('weather_forecast','amap',{},context=weather,coverage_dates=['2026-10-23'])],field='weather_forecast',context=weather,status='unverified')
 add('P14','Fresh weather still requires dynamic action',[claim('weather_now','amap',{},context={'adcode':'430100'})],field='weather_now',context={'adcode':'430100'},status='source_estimate')
 route={'origin':[113.0,28.0],'destination':[113.1,28.1],'mode':'metro','coord_system':'GCJ02','departure_at':'2026-10-24T09:00:00+08:00'}
 add('P15','Fresh Amap route is estimate and dynamic',[claim('route_duration','amap',25,unit='minutes',context=route)],field='route_duration',context=route,status='source_estimate')
 add('P16','Non-Amap travel time cannot substitute',[claim('route_duration','owner',25,unit='minutes',context=route)],field='route_duration',context=route,status='unverified')
 add('P17','Incorrect route units',[claim('route_duration','amap',1500,unit='seconds',context=route)],field='route_duration',context=route,status='unverified')
 add('P18','Different departure context',[claim('route_duration','amap',25,unit='minutes',context={**route,'departure_at':'2026-10-23T09:00:00+08:00'})],field='route_duration',context=route,status='unverified')
 add('P19','Fresh explicit room configuration reusable for metadata only',pair('room_configuration',{'named_room':'synthetic twin','physical_beds':2}),field='room_configuration',expected=False,status='corroborated')
 hotel={'travel_date':'2026-10-24','party_size':2}
 add('P20','Date-bound quote for another day',pair('dynamic_price',400,context={**hotel,'travel_date':'2026-10-23'}),field='dynamic_price',context=hotel,status='unverified')
 add('P21','Fresh admission price still dynamic',pair('price',50,context={'travel_date':'2026-10-24'}),field='price',context={'travel_date':'2026-10-24'},status='corroborated')
 add('P22','Fresh independent identity reusable',pair('identity',{'name':'synthetic venue'}),field='identity',expected=False,status='corroborated')
 add('P23','Derived or unverified entity label cannot certify dietary need',pair(entity_verified=False),status='unverified')
 add('P24','Opening rule outside applicability date',pair('opening_hours','09:00-17:00',context={'travel_date':'2026-10-24'},applies_until='2026-10-23'),field='opening_hours',context={'travel_date':'2026-10-24'},status='unverified')
 (OUT/'cases.json').write_text(json.dumps({'frozen_at':utcnow(),'cases':cases,'registry_fixture':REG,'now':NOW,'network_requests':0},ensure_ascii=False,indent=2),encoding='utf-8')
 results=[]
 for case in cases:
  verdict=reconcile(case['claims'],case['field'],REG,now=NOW,context=case['context'],entity_id='synthetic:venue')
  mandatory=POLICIES[case['field']][1]
  retrieve=mandatory or verdict['status'] not in ('corroborated','source_estimate')
  result={**case,'verdict':verdict,'method_retrieval_required':retrieve,'mandatory_dynamic':mandatory,
      'trigger_correct':retrieve==case['expected_retrieval_required'],'status_correct':verdict['status']==case['expected_status']}
  results.append(result)
 positive=sum(c['expected_retrieval_required'] for c in cases);negative=len(cases)-positive
 report={'at':utcnow(),'cases':len(cases),'synthetic_only':True,'network_requests':0,'real_world_accuracy':None,
  'protocol_sha256':digest_file(OUT.parent/'protocol.json'),'implementation_sha256':digest_file(ROOT/'src/shorttrip/freshness.py'),
  'labels_frozen_before_engine_evaluation':True,'policy_trigger_expected_positive':positive,'policy_trigger_expected_negative':negative,
  'method_trigger_correct':sum(r['trigger_correct'] for r in results),'method_status_correct':sum(r['status_correct'] for r in results),
  'always_retrieve_trigger_correct':positive,'never_retrieve_trigger_correct':negative,
  'controlled_logical_tasks_avoided_vs_always':sum(not r['method_retrieval_required'] for r in results),
  'actual_network_call_savings':None,'results':results,
  'limitations':['Synthetic policy conformance only; cases overlap known invariant families.','No blind human labels, independent model runs, real query distribution, or measured network savings.','This invokes gate/reconcile functions; current CLI static lookup task generation is measured separately and may not implement selective scheduling.']}
 (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('results','limitations')},ensure_ascii=False))
if __name__=='__main__':main()
