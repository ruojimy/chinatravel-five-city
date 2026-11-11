"""Freeze the first dynamic-retrieval pilot's inputs and measurement boundaries."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file

def main():
 out=ROOT/'results/p18_dynamic_eval';out.mkdir(exist_ok=True);target=out/'protocol.json'
 if target.exists():raise FileExistsError('Protocol is immutable')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text())
 files=['src/shorttrip/freshness.py','src/shorttrip/static_lookup.py','src/shorttrip/travel_catalog.py','src/shorttrip/expansion_store.py','src/shorttrip/expansion_contract.py',
        '../.agents/skills/travel-live-retrieval/SKILL.md']
 protocol={'frozen_at':utcnow(),'version':'p18-pilot-v1','catalogue_basis':pointer,'catalogue_hash_verified':digest_file(ROOT/pointer['catalog'])==pointer['sha256'],
  'implementation_hashes':{f:digest_file(ROOT/f) for f in files},
  'objective':'Measure whether TAG, freshness, identity and source gates trigger useful bounded retrieval without claiming unverified facts.',
  'arms':[
   {'id':'static_only','method':'Read the same immutable starting catalogue; no new network; report missing/aged/conflicting information explicitly.'},
   {'id':'existing_task_generator','method':'Run current static_lookup.lookup and verification_tasks unchanged. Count logical tasks only, not actual network requests or measured cost savings.'},
   {'id':'skill_guided_live','method':'Apply current travel-live-retrieval skill to the same starting conditions; real normal search/open, bounded source budget, original evidence retained.'}],
  'sections':[
   {'id':'controlled_policy_replay','type':'synthetic_counterfactual_QA','planned_cases':24,'network_requests':0,
    'labels':'Explicit source clocks, same-source mirrors, conflicts, identity errors, dynamic weather/routes and scope changes created as fixtures. These labels test policy behavior, never real-world travel accuracy.'},
   {'id':'real_static_tag_recall','type':'actual_snapshot_lookup','planned_queries':12,'network_requests':0,
    'metrics':['returned candidates','TAG matches','unknown exploration slots','logical verification tasks','strict planning_ready count'],
    'no_relevance_ground_truth':True},
   {'id':'real_live_cases','type':'purposive_finite_pilot','planned_cases':9,'allocation':{'attraction':3,'restaurant':3,'accommodation':3},
    'case_rationale':'Actual observed catalogue defects; selected intentionally, not random or held-out.',
    'per_case_max_source_opens':3,'preferred_independent_sources':2,
    'metrics':['retrieval trigger and query','actual search tool calls','actual source-open attempts','source groups','elapsed collection window','strictly resolved fields','scoped reference additions','unresolved or blocked fields','unsupported hard claims'],
    'outcomes':['verified_for_context','scoped_reference_only','conflict_retained','blocked_by_access','insufficient_evidence'],
    'no_human_ground_truth':True}],
  'rules':[
   'Static snapshot remains frozen even if collection later advances. Do not repair failed cases or tune rules before recording the first result.',
   'Pause broad static collection. Finish only already captured evidence reviews and controlled pilot retrieval.',
   'No new model API or local model. Subagents use the current authorized model; do not switch to evade capacity or quota.',
   'Do not bypass any paused source, login, CAPTCHA, robots, 403/429 or previous automatic-review rejection.',
   'Missing website publication or observation time remains null; retrieval time is not a renewed fact clock.',
   'Weather is dynamic. Metro travel duration and fare require Amap; a paused Amap provider is a blocked outcome, not a substitute web estimate.',
   'Dates, party size, room configuration, cancellation and discounts bind hotel quotes. Conditional floor prices are not eligible totals.',
   'A source quote match establishes provenance, not truth. Independent groups and applicable dates must be checked.',
   'Task-count reduction, actual request savings, field correctness and end-to-end feasible itinerary success are distinct measurements.',
   'Report case selection bias, small sample size and the absence of independent human truth labels. No real-world accuracy percentage or full completion claim.'
  ],'full_catalog_completion':False,'real_world_accuracy_known':False}
 target.write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'protocol':str(target.relative_to(ROOT)),'sha256':digest_file(target),'catalogue_basis':pointer},ensure_ascii=False))
if __name__=='__main__':main()
