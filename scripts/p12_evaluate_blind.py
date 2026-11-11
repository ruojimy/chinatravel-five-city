"""Preserve the first model response and evaluate without feedback or repair."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.checker import check_plan
from shorttrip.expanded_environment import ExpandedEnvironment
from shorttrip.freshness import utcnow
OUT=ROOT/'results/p12_expansion';PACKET=OUT/'blind_packet'
def read(name):return json.loads((PACKET/name).read_text(encoding='utf-8'))
def main():
    manifest=read('manifest.json')
    hashes={n:hashlib.sha256((PACKET/n).read_bytes()).hexdigest()==v for n,v in manifest['files'].items()}
    if not all(hashes.values()):raise ValueError('Frozen packet changed')
    data=read('input.json');cases=read('cases.json')
    response=json.loads((OUT/'llm_blind_response.json').read_text(encoding='utf-8'))
    answers={x['case_id']:x for x in response['cases']}
    query={'uid':'blind_synthetic_S1','days':1,'people_number':1,'start_city':'合成起点城','target_city':'合成测试城',
      'nature_language':cases[0]['request'],'hard_logic_py':['result=(day_count(plan)==1)','result=(people_count(plan)==1)',
      'total_cost=0\nfor activity in allactivities(plan):\n    total_cost+=activity_cost(activity)\n    total_cost+=innercity_transport_cost(activity_transports(activity))\nresult=(total_cost<=500)']}
    with ExpandedEnvironment(data['synthetic_records'],version='blind-frozen-synthetic-v1',
          now=data['synthetic_now'],allow_synthetic=True,city_slugs={'合成测试城':'synthetic-city'},
          routes=data['synthetic_routes'],intercity=data['synthetic_intercity']) as env:
        plan_gate=check_plan(query,answers['S1']['plan']).to_dict()
        register=env.registration_report
    # Evaluator checks reported literals, rather than substituting our own plan.
    records={x['record_id']:x for x in data['synthetic_records']+data['real_records']}
    records.update({f'synthetic_intercity[{i}]':r for i,r in enumerate(data['synthetic_intercity'])})
    records.update({f'synthetic_routes[{i}]':r for i,r in enumerate(data['synthetic_routes'])})
    literal_checks=[];derived=[]
    for case in response['cases']:
        for claim in case['factual_claims']:
            record=records.get(claim['record_id']);field=claim['field'];value=claim['value'];expected=None;found=False
            if record is not None:
                current=record;found=True
                for part in field.split('.'):
                    if isinstance(current,dict) and part in current:current=current[part]
                    else:found=False;break
                if found:expected=current
                elif field.startswith('tags.'):
                    matches=[t['value'] for t in record.get('tags',[]) if t['tag']==field[5:]]
                    expected=matches[0] if len(matches)==1 else None;found=True
                elif field=='data.coordinates':expected={k:record['data'][k] for k in ('lat','lon')};found=True
                elif field.startswith('metro_') and value is None:expected=None;found=True
                elif field=='operational_field_assessment':
                    expected={k:record['data'].get(k) for k in value};found=True
            if field.startswith('derived_'):
                derived.append({'case_id':case['case_id'],'field':field,'value':value,
                    'independent_check':'S1 official checker recomputes costs; S2 frozen round-trip train fares total 200>100'})
                continue
            literal_checks.append({'case_id':case['case_id'],'record_id':claim['record_id'],'field':field,
                'supported_by_frozen_input':found and expected==value,'claim_status':claim.get('claim_status')})
    real_checks=[]
    for case in cases[2:]:
        answer=answers[case['case_id']]
        real_checks.append({'case_id':case['case_id'],'status':answer['status'],
            'no_complete_plan_on_missing_data':answer.get('plan') is None and answer['status']=='needs_verification',
            'selected_ids_in_frozen_input':all(rid in records for rid in answer['selected_ids']),
            'requests_further_verification':bool(answer['required_dynamic_queries']),
            'missing_not_declared_impossible':answer['status']!='infeasible'})
    # Explicit route policy check for the transit query; weather query check is
    # scoped to the explicit weather question, not all hotel-only subtasks.
    r4=json.dumps(answers['R4']['required_dynamic_queries'],ensure_ascii=False)
    r5=json.dumps(answers['R5']['required_dynamic_queries'],ensure_ascii=False)
    lower_bound=sum(x['data']['Cost'] for x in data['synthetic_intercity'])
    report={'evaluated_at':utcnow(),'frozen_inputs_unchanged':hashes,'response_sha256':hashlib.sha256((OUT/'llm_blind_response.json').read_bytes()).hexdigest(),
      'model_runs':1,'cases':8,'real_fully_generated_plans':sum(bool(answers[x['case_id']].get('plan')) for x in cases[2:]),
      'synthetic_official_checker':plan_gate,'synthetic_registration':register,
      'S2_infeasibility_check':{'minimum_roundtrip_intercity_cost':lower_bound,'budget':100,
           'model_status':answers['S2']['status'],'correct':lower_bound>100 and answers['S2']['status']=='infeasible'},
      'real_discovery_case_checks':real_checks,'R4_requires_amap':'高德' in r4,
      'R5_requires_dynamic_weather':'weather' in r5,'literal_claim_checks':literal_checks,
      'unsupported_literal_claims':[x for x in literal_checks if not x['supported_by_frozen_input']],
      'derived_claims_separate':derived,'external_model_api_calls':0,'subagent_model_generation_runs':1,
      'human_annotations':0,'real_world_accuracy':None,'measured_dynamic_calls_saved':None,
      'limits':'One inherited-model subagent, one sample, 16 real discovery records, 2 synthetic and 6 insufficiency cases. No real feasible trip, no human truth labels, no measured online savings.'}
    (OUT/'llm_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'synthetic_all_ok':plan_gate['all_ok'],'real_cases':len(real_checks),
      'unsupported_literals':len(report['unsupported_literal_claims']),'real_complete_plans':report['real_fully_generated_plans'],
      'S2_correct':report['S2_infeasibility_check']['correct']},ensure_ascii=False))
if __name__=='__main__':main()
