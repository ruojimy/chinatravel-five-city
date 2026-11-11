"""Paired offline recall and adapter registration, not network-savings claims."""
from pathlib import Path
import collections, hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.static_lookup import lookup,verification_tasks
from shorttrip.expanded_environment import ExpandedEnvironment
from shorttrip.travel_catalog import digest_file
from shorttrip.freshness import utcnow
def main():
    out=ROOT/'results/p12_expansion';base=ROOT/'data/catalog_v1_1_20261022/catalog.sqlite3'
    expansion=ROOT/'data/expansion_catalog_v1_1_20261022/catalog.sqlite3'
    before={str(p.relative_to(ROOT)):digest_file(p) for p in (base,expansion)}
    rows=[]
    for city,kind,tag in [('西安','attraction','history'),('天津','attraction',None),
          ('厦门','restaurant',None),('西安','accommodation',None),('长沙','attraction','wheelchair'),
          ('佛山','accommodation',None)]:
        result=lookup(expansion,city,kind,baseline=base,tag=tag,limit=6)
        result['retrieval_tasks']=verification_tasks(result,travel_date='2026-10-24')
        rows.append(result)
    inputs=json.loads((out/'blind_packet/input.json').read_text(encoding='utf-8'))
    records=inputs['real_records']
    with ExpandedEnvironment(records,version='real-discovery-registration-v1',
             city_slugs={'西安':'xian','天津':'tianjin','厦门':'xiamen'}) as env:
        adapter={'registration':env.registration_report,'discovery_records':len(env.records),
                 'planning_ready_records':len(env.ready),'ambiguous_names':env.ambiguous_names,
                 'new_city_official_activity_rows':{city:{key:len(env.tools[key].data[city]) for key in
                       ('attractions','restaurants','accommodations')} for city in ('西安','天津','厦门')},
                 'unknown_route_result':env.tools['transportation'].goto('西安','任一起点','任一终点','10:00','metro')}
    result={'executed_at':utcnow(),'requests':rows,'new_city_baseline_candidate_rows':[r['baseline_city_kind_rows'] for r in rows],
        'after_local_candidate_counts':[len(r['candidates']) for r in rows],'network_requests':0,
        'real_plans_generated':0,'dynamic_requests_actually_saved':None,'adapter_smoke':adapter,
        'source_database_hashes_unchanged':{name:digest_file(ROOT/name)==digest for name,digest in before.items()},
        'interpretation':'New-city local discovery works and narrows source searches; unknown fact ages and missing operational fields still trigger verification. Offline recall is not measured online request reduction.'}
    (out/'lookup_trial.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('new_city_baseline_candidate_rows','after_local_candidate_counts','source_database_hashes_unchanged')},ensure_ascii=False))
if __name__=='__main__':main()
