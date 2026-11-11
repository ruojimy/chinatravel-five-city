"""Bounded offline probe on local CC-BY-labelled corpus, no writes to TAG store."""
from pathlib import Path
import sys,json,hashlib,importlib.util
from collections import Counter
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.candidate_matching import extract_evidence,VERSION

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()

def main():
    corpus=ROOT/'data/visitor_reviews_raw/zhangjiajie_reviews.jsonl'
    stats=json.loads((corpus.parent/'zhangjiajie_stats.json').read_text(encoding='utf-8'))
    with corpus.open(encoding='utf-8') as f:reviews=[json.loads(line) for line in f if line.strip()]
    spec=importlib.util.spec_from_file_location('p5_sampling',ROOT/'scripts/p5_extract_visitor_tags.py')
    previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
    used={r['review_id'] for r in previous.stratified_sample(reviews,800)}
    seed='p10-real-probe-v1'
    remaining=[r for r in reviews if r['review_id'] not in used]
    selected=sorted(remaining,key=lambda r:hashlib.sha256((seed+r['review_id']).encode()).hexdigest())[:200]
    out=ROOT/'results/p10_tag_matching'
    if '--refined' in sys.argv:out=out/'refined_semantics'
    out.mkdir(parents=True,exist_ok=True)
    manifest={'seed':seed,'corpus_sha256':digest(corpus),'selected_review_ids':[r['review_id'] for r in selected],
        'overlap_with_p5_800':len(used & {r['review_id'] for r in selected}),
        'code_version':VERSION,'extractor_sha256':digest(ROOT/'src/shorttrip/candidate_matching.py'),
        'note':'Selection frozen before this probe extracts text; excludes known P5 sample, not a claim of complete historical holdout. No independent human labels.'}
    (out/'real_probe_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=[]
    for r in selected:
        for e in extract_evidence(r,'cc_by'):
            assert e.quote in r['text']
            evidence.append(asdict(e))
    result={'selected_reviews':len(selected),'reviews_with_any_extraction':len({e['review_id'] for e in evidence}),
        'evidence_items':len(evidence),'scope_counts':dict(Counter(e['scope'] for e in evidence)),
        'aspect_counts':dict(Counter(e['aspect'] for e in evidence)),
        'verbatim_substring_check':True,'route_identity_metadata_present':0,
        'published_to_tag_store':0,'target_identity_verified':False,'accuracy':None,'human_labels':0,
        'source':stats['source'],'licence_as_recorded_locally':stats['licence'],
        'attribution':stats['attribution'],'licence_reverified_online_this_run':False,
        'note':'Extraction/coverage probe only. Cannot equate phrase hits or literal quotation with semantic correctness or reliable POI identity.',
        'evidence':evidence}
    (out/'real_review_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='evidence'},ensure_ascii=False))

if __name__=='__main__':main()
