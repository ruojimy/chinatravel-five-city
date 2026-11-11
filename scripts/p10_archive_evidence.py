"""Package bounded P10 evidence, validate frozen inputs, never include secrets."""
from pathlib import Path
from datetime import datetime
import json,hashlib,re,zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/p10_tag_matching'

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

def main():
    frozen=read(OUT/'refined_semantics/real_probe_manifest.json')
    corpus=ROOT/'data/visitor_reviews_raw/zhangjiajie_reviews.jsonl'
    assert digest(corpus)==frozen['corpus_sha256']
    assert digest(ROOT/'src/shorttrip/candidate_matching.py')==frozen['extractor_sha256']
    wanted=set(frozen['selected_review_ids']);selected={}
    with corpus.open(encoding='utf-8') as stream:
        for line in stream:
            item=json.loads(line)
            if item['review_id'] in wanted:selected[item['review_id']]=item
    assert len(selected)==len(wanted)==200
    with (OUT/'selected_reviews_raw.jsonl').open('w',encoding='utf-8') as stream:
        for key in frozen['selected_review_ids']:stream.write(json.dumps(selected[key],ensure_ascii=False)+'\n')
    probe=read(OUT/'refined_semantics/real_review_probe.json')
    assert len(probe['evidence'])==106
    assert all(e['quote'] in selected[e['review_id']]['text'] for e in probe['evidence'])
    attribution={k:probe[k] for k in ('source','licence_as_recorded_locally','attribution','licence_reverified_online_this_run')}
    attribution['modifications']='Selected 200 records from local normalized JSONL; derived provisional TAGs. Text and corpus POI hints are unverified.'
    write(OUT/'source_attribution.json',attribution)
    effects=[]
    for label,folder in [('initial',OUT),('window_filtered',OUT/'feasible_case')]:
        arms={name:read(folder/f'sandbox_{name}.json') for name in ('baseline','poi_only','poi_and_route')}
        assert all(a['ok'] and a['official_report']['all_ok'] for a in arms.values())
        mealcounts={};intercity={};intercity_core={}
        for name,a in arms.items():
            activities=[v for d in a['plan']['itinerary'] for v in d['activities']]
            mealcounts[name]=[v for v in activities if v['type'] in ('breakfast','lunch','dinner')]
            intercity[name]=[v for v in activities if v['type'] in ('train','airplane','flight','intercity_transport','intercity')]
            # Return-station access transfers can differ even when trains do not.
            intercity_core[name]=[{k:v for k,v in a.items() if k!='transports'} for a in intercity[name]]
        assert all(len(v)==2 for v in intercity.values())
        effects.append({'case':label,'meals':mealcounts,'intercity_activities':intercity,
                       'intercity_identical_across_arms':len({json.dumps(v,sort_keys=True) for v in intercity.values()})==1,
                       'intercity_service_without_access_legs':intercity_core,
                       'same_intercity_service_times_and_costs':len({json.dumps(v,sort_keys=True) for v in intercity_core.values()})==1,
                       'note':'Cost changes are confounded by activity/timing changes. Not a recommendation quality score.'})
    write(OUT/'controlled_effect_audit.json',effects)
    test_counts={'test_tags_preference.py.log':54,'test_open_data_extractor.py.log':16,
                 'test_visitor_tags.py.log':12,'test_matching_v2.py.log':12,
                 'test_candidate_matching_v02.py.log':22,'test_p7_preference_analysis.py.log':5}
    for filename,count in test_counts.items():
        log=(OUT/filename).read_text(encoding='utf-8')
        assert f'PASS {count}  FAIL 0' in log or (re.search(rf'Ran {count} tests\b',log) and re.search(r'\bOK\b',log))
    regression=read(OUT/'baseline_regression.json')
    assert regression['exact_equal']==regression['official_pass']==regression['historical_plans']==54
    assert regression['historical_source_unchanged']
    pool=read(OUT/'sandbox_pool_control.json')
    assert pool['ok'] and pool['official_report']['all_ok']
    assert all(v['plan_identical_to_original_baseline'] for v in pool['comparisons'].values())
    write(OUT/'validation_summary.json',{
        'test_counts':test_counts,'total_current_checks':sum(test_counts.values()),
        'historical_matching_18_not_double_counted':True,'primary_control_plans':6,
        'additional_pool_control_plans':1,'official_pass_control_plans':7,'independent_control_queries':1,
        'historical_plans_exact_replay':54,'selected_texts_packaged':200,'derived_evidence_items':106,
        'all_quotes_in_raw_text':True,'frozen_extractor_sha256_matches':True,
        'human_labels':0,'extraction_accuracy':None,'external_api_calls':0,
        'packaged_at':datetime.now().astimezone().isoformat(),
        'test_evidence':'Existing captured logs checked; no duplicate rerun during archive.'})
    names=['src/shorttrip/candidate_matching.py','src/shorttrip/planner.py',
           'src/shorttrip/preference.py','src/shorttrip/visitor_tags.py','tests/test_candidate_matching.py',
           'scripts/p10_probe_review_matching.py','scripts/p10_sandbox_matching_experiment.py',
           'scripts/p10_pool_control.py','scripts/p10_regression_baseline.py','scripts/p10_archive_evidence.py',
           'scripts/p5_extract_visitor_tags.py','报告/10_评论TAG前置匹配与交通实验.md',
           'docs/评论TAG驱动的景区与交通匹配.md','STATE.md',
           'ChinaTravel/chinatravel/data/easy_short/e20241028160248698752.json']
    files=[ROOT/n for n in names]
    files.extend(p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact_manifest.json' and '__pycache__' not in p.parts)
    manifest=[{'path':p.relative_to(ROOT.parent).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(set(files))]
    write(OUT/'artifact_manifest.json',{'algorithm':'SHA256','self_excluded':True,'files':manifest})
    files.append(OUT/'artifact_manifest.json')
    archive=ROOT.parent/'评论TAG与交通匹配_实验批次_20261022.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(set(files)):z.write(p,p.relative_to(ROOT.parent).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for entry in manifest:assert hashlib.sha256(z.read(entry['path'])).hexdigest()==entry['sha256']
        count=len(z.namelist())
    verification={'archive':archive.name,'bytes':archive.stat().st_size,'sha256':digest(archive),
                  'file_count':count,'zip_crc_verified':True,'all_manifest_hashes_verified':True}
    write(archive.with_suffix('.delivery_verification.json'),verification)
    print(json.dumps(verification,ensure_ascii=False))

if __name__=='__main__':main()
