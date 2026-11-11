"""Evaluate saved participant drafts unchanged; no planner or safe projection."""
import copy,json,sys,hashlib,subprocess
from pathlib import Path
from datetime import datetime
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from shorttrip.retrieval_guard import evaluate,gate
B=R/'results/p27_focused_deep_retrieval'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
results=[];coverage=[];checks=[]
for level in ['easy','hard','human']:
 q=read(B/'private'/level/'query.json')
 q['required_entities']=[[q['city_sequence'][0],q['candidates'][0]['entity_id']]]
 if level!='easy':q['budget_cny']=300 if level=='hard' else 200
 for req in q['requirements']:
  if req['field'] in ('price','opening_hours'):req['accepted_levels']=['reference','verified']
 ledger={};events=[]
 for n in range(4):
  plan=read(B/'participants'/level/f'round{n}.json')
  if n:
   packet=read(B/'responses'/level/f'round{n}.json');now=packet['evaluated_at'];events.append({'evidence':packet['evidence']})
   ledger.update({e['evidence_id']:e for e in packet['evidence']})
  else:now=read(B/'private/freeze.json')['at']
  eq=read(B/'private'/level/'evaluation_query_round2.json') if n>=2 else q
  score=evaluate(eq,plan,list(ledger.values()),events,now=now)
  item={'level':level,'round':n,'variant':'clarified' if n>=2 and level!='easy' else 'original','snapshot_at':now,'score':score}
  results.append(item);save(B/'evaluations'/level/f'round{n}.json',item)
  checks.append({'check':f'{level}/round{n} schema','ok':score['schema_ok']})
  if n==3:
   core=[r for r in eq['requirements'] if not r.get('prerequisite_only')];usable=[]
   for req in core:
    matches=[e for e in packet['evidence'] if gate(e,req,now)['usable'] and e['level'] in req.get('accepted_levels',['verified','estimate'] if req['field'] in ('weather_forecast','route_duration','route_fare') else ['verified'])]
    usable.append({'target_id':req['target_id'],'field':req['field'],'usable':bool(matches),'evidence_ids':[e['evidence_id'] for e in matches]})
   coverage.append({'level':level,'core_required':len(core),'core_source_covered':sum(x['usable'] for x in usable),'source_fields':usable})
 for n in range(4):checks.append({'check':f'{level}/decision_round{n} exists','ok':(B/'participants'/level/f'decision_round{n}.json').exists()})
frozen=read(B/'private/freeze.json')
for c in frozen['cases']:
 p=B/'private'/c['level']/'original_query.json';original=read(p)
 checks.append({'check':c['level']+' original canonical query hash preserved','ok':hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True).encode()).hexdigest()==c['original_query_sha256']})
 p24=read(R/'results/p24_dynamic_feedback/private/queries_96.json')
 checks.append({'check':c['level']+' original equals P24 source','ok':original==next(x for x in p24 if x['uid']==c['original_uid'] and x['level']==c['level'])})
api=read(B/'capture/amap_ledger.json');checks.append({'check':'Amap within20 calls','ok':api['spent']<=20})
final=[r for r in results if r['round']==3]
checks.append({'check':'No execution confirmed','ok':not any(r['score']['execution_confirmed'] for r in results)})
checks.append({'check':'Human conditional proposal accepted raw','ok':next(x for x in final if x['level']=='human')['score']['policy_accepted']})
checks.append({'check':'Easy and hard remain blocked','ok':not any(x['score']['policy_accepted'] for x in final if x['level']!='human')})
summary={'created_at':datetime.now().astimezone().isoformat(),'cases':3,'llm_initial_plans':3,'feedback_rounds_per_case':3,'llm_dynamic_plans':9,'llm_total_plans':12,'external_llm_api_calls':0,'llm_method':'3 Codex participant subagents; token/call cost not directly metered as external API','source_requests':{'search_queries':16,'page_opens':8,'web_page_successes':4,'web_page_failures':4,'amap_http_attempts':api['spent'],'total':16+8+api['spent'],'global_cap':48},'original_round1_conditional_accepted':sum(r['score']['policy_accepted'] for r in results if r['round']==1),'final_raw_conditional_accepted':sum(r['score']['policy_accepted'] for r in final),'execution_confirmed':0,'source_coverage':coverage,'final_results':final,'limitations':['Not a randomized matched-budget experiment; adaptive researcher orchestration and clarified origins are disclosed.','Per-case web-attempt allocation was not persistently logged before dispatch, so the12/18/18 individual caps cannot be certified; only aggregate43/48 and Amap19/20 are auditable.','First3-query search response was not saved as a capture; its attempts count in43, and it supplies no accepted evidence.','Source gate evolved after a real bus fallback was discovered; not a held-out evaluation.','Changsha reuses the prior Yuelu entity with a different origin; not independent-city generalization.']}
save(B/'summary.json',summary);save(B/'validation.json',{'passed':sum(x['ok'] for x in checks),'total':len(checks),'checks':checks})
print(json.dumps({'final_results':final,'coverage':[(c['level'],c['core_source_covered'],c['core_required']) for c in coverage],'validation':(sum(x['ok'] for x in checks),len(checks))},ensure_ascii=False,indent=2))
