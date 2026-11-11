"""Independent artifact, minimum-selection and HTML completeness checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from chinatravel.soft_constraints.pool import fingerprint,snapshot


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    spec=importlib.util.spec_from_file_location('baseline_verifier',ROOT/'reproduction/verify.py')
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    bundle=load(OUT/'all_results.json')
    assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in bundle['module_sha256'].items())
    expected={x['split']:x['uid'] for x in load(ROOT/'reproduction/manifest.json')['samples']}
    assert {c['split']:c['uid'] for c in bundle['cases']}==expected and len(bundle['cases'])==3
    report=(OUT/'itineraries.html').read_text(encoding='utf-8')
    parser=baseline.ReportParser();parser.feed(report)
    checks=[]
    for item in bundle['cases']:
        split=item['split'];pool=item['candidates'];selection=item['selection']
        assert len(pool)==20 and len({fingerprint(c['plan']) for c in pool})==20
        assert sorted(c['ordinal'] for c in pool)==list(range(1,21))
        for c in pool:
            assert fingerprint(c['plan'])==c['fingerprint']
            score=c['score'];weights=score['configuration']['weights']
            raw={key:sum(d['penalty'] for d in score['details'] if d['category']==key) for key in score['categories']}
            for key,value in score['categories'].items():
                assert abs(value-raw[key]*weights[key])<0.00001
            assert abs(score['total_penalty']-sum(score['categories'].values()))<0.00001
            assert c['audit']['schema'] and c['audit']['original_commonsense'] and all(c['audit']['translated_hard_constraints'])
            assert f'id="{split}-candidate-{c["ordinal"]}"' in report
        winner=min(pool,key=lambda c:(c['score']['total_penalty'],c['ordinal']))
        assert winner['ordinal']==selection['selected_ordinal']
        assert winner['score']['total_penalty']==selection['minimum_penalty']
        assert winner['fingerprint']==selection['selected_fingerprint']
        actual=load(ROOT/item['status']['result'])
        assert snapshot(actual)==winner['plan'] and actual==item['selected_plan']
        assert json.loads(parser.json_text[split])==actual
        total=baseline.verify_case(actual,parser.counts[split],parser.totals[split],parser.days[split])
        provenance=item['status']['translation_cache']
        assert hashlib.sha256((ROOT/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
        checks.append({'split':split,'unique_feasible_candidates':20,'selected_ordinal':winner['ordinal'],
                       'minimum_penalty':winner['score']['total_penalty'],'minimum_selection_verified':True,
                       'html_exact':True,'activities':parser.counts[split]['activities'],
                       'transports':parser.counts[split]['transports'],'cost':str(total),
                       'selected_official_hard_constraints_pass':all(winner['audit']['official_hard_constraints']),
                       'official_hard_pass_candidates':sum(all(c['audit']['official_hard_constraints']) for c in pool)})
    core=load(ROOT/'reproduction/core_checksums.json')
    assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in core.items())
    inputs=load(ROOT/'reproduction/format_input_checksums.json')
    assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in inputs.items())
    for path in [ROOT.parent/'.env.local',ROOT/'.env.local']:
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                key,sep,value=line.partition('=')
                if sep and 'API_KEY' in key and len(value.strip())>10:
                    secret=value.strip().strip('\"\'')
                    for artifact in list(OUT.glob('*.html'))+list(OUT.glob('*.json'))+list(OUT.glob('*.log')):
                        assert secret not in artifact.read_text(encoding='utf-8',errors='replace')
    result={'cases':checks,'original_core_files_unchanged':len(core),'baseline_artifacts_unchanged':len(inputs),
            'credential_scan':'passed','browser_visual_qa':'unavailable: no enabled browser surface'}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
