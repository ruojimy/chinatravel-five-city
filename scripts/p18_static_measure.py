"""Real frozen lookup and task counts. No search relevance or network savings claim."""
import collections,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.static_lookup import lookup,verification_tasks
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file

def main():
 out=ROOT/'results/p18_dynamic_eval/static_lookup';out.mkdir(exist_ok=False)
 protocol=json.loads((out.parent/'protocol.json').read_text());pointer=protocol['catalogue_basis'];catalog=ROOT/pointer['catalog']
 if digest_file(catalog)!=pointer['sha256']:raise ValueError('Frozen catalogue changed')
 cases=[('S01','长沙','attraction','history'),('S02','厦门','attraction','nature'),('S03','无锡','attraction','history'),('S04','昆明','attraction','unknown_accessibility_tag'),
        ('S05','厦门','restaurant','cuisine'),('S06','广州','restaurant','food_category'),('S07','佛山','restaurant','dietary_category_unverified'),('S08','宁波','restaurant','unknown_allergen_free_tag'),
        ('S09','厦门','accommodation','room_type_name'),('S10','海口','accommodation','bed_configuration'),('S11','宁波','accommodation','unknown_accessibility_tag'),('S12','合肥','accommodation','room_type_name')]
 results=[]
 for cid,city,kind,tag in cases:
  start=time.perf_counter();response=lookup(catalog,city,kind,tag=tag,limit=6,now=protocol['frozen_at']);tasks=verification_tasks(response,travel_date='2026-10-24')
  full={'case_id':cid,'query':{'city':city,'kind':kind,'tag':tag,'limit':6,'travel_date':'2026-10-24'},'lookup':response,'tasks':tasks,
    'elapsed_seconds':round(time.perf_counter()-start,4),'network_requests':0}
  (out/(cid+'.json')).write_text(json.dumps(full,ensure_ascii=False,indent=2),encoding='utf-8')
  counts=collections.Counter(t['field'] for t in tasks)
  results.append({'case_id':cid,'city':city,'kind':kind,'tag':tag,'candidates':len(response['candidates']),
    'matched_candidates':sum(x['tag_match'] for x in response['candidates']),'unknown_exploration_candidates':sum(not x['tag_match'] for x in response['candidates']),
    'planning_ready':sum(x['gate']['planning_ready'] for x in response['candidates']),'uncovered_tags':response['uncovered_query_tags'],
    'logical_tasks':len(tasks),'task_fields':dict(counts),'entity_verification_tasks':sum(t['field'] not in ('weather_forecast','route_duration_and_fare') for t in tasks)})
 report={'at':utcnow(),'catalogue_basis':pointer,'protocol_sha256':digest_file(out.parent/'protocol.json'),
  'queries':12,'results':results,'network_requests':0,'actual_dynamic_calls_saved':None,'relevance_accuracy':None,
  'total_returned_candidate_occurrences':sum(r['candidates'] for r in results),'total_logical_tasks':sum(r['logical_tasks'] for r in results),
  'observation':'Current verification_tasks unconditionally emits five policy tasks per candidate, plus three hotel tasks. It does not inspect each field freshness before scheduling.',
  'limitations':['TAG is an attribute key only: no requested value, negation or hard/soft preference parameter in this API.','Unknown-city entities are excluded by default; empty recall does not prove no real venue exists.','Logical tasks are not network requests. No measured savings against a same-workload live baseline.']}
 (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('results','limitations')},ensure_ascii=False))
if __name__=='__main__':main()
