"""Serial final checks with captured outputs; never invokes a model or network."""
from pathlib import Path
import hashlib,importlib.metadata,json,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p12_expansion'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow
def main():
    env=os.environ|{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','BAIDU_REQUEST_BUDGET':'0','BAIDU_OFFLINE':'1'}
    jobs=[('contract',['tests/test_expansion_contract.py']),('store',['tests/test_expansion_store.py']),
          ('legacy_load_gates',['tests/test_legacy_load_gates.py']),('p11_regression',['tests/test_freshness_live.py'])]
    checks=[]
    for name,args in jobs:
        run=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8')
        log=run.stdout+'\n'+run.stderr;(OUT/('final_'+name+'.log')).write_text(log,encoding='utf-8')
        n=re.search(r'Ran (\d+) tests?',log)
        checks.append({'name':name,'exit_code':run.returncode,'tests':int(n.group(1)) if n else None,'log':'final_'+name+'.log'})
    files=['src/shorttrip/checker.py','src/shorttrip/expansion_contract.py','src/shorttrip/expanded_environment.py',
       'src/shorttrip/expansion_store.py','src/shorttrip/static_lookup.py','src/shorttrip/travel_catalog.py',
       'src/shorttrip/live_amap.py','src/shorttrip/dynamic/overlay.py','src/shorttrip/dynamic/bus.py',
       'src/shorttrip/dynamic/pipeline.py','ChinaTravel/chinatravel/evaluation/output_schema.json',
       'ChinaTravel/chinatravel/symbol_verification/commonsense_constraint.py',
       'ChinaTravel/chinatravel/symbol_verification/concept_func.py','ChinaTravel/chinatravel/symbol_verification/hard_constraint.py']
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT/'ChinaTravel',capture_output=True,text=True)
    dirty=subprocess.run(['git','status','--short','--','chinatravel/evaluation','chinatravel/symbol_verification','chinatravel/environment/language.py'],cwd=ROOT/'ChinaTravel',capture_output=True,text=True)
    result={'checked_at':utcnow(),'checks':checks,'total_tests':sum(x['tests'] or 0 for x in checks),
      'all_passed':all(x['exit_code']==0 for x in checks),'network_calls':0,'model_generations':0,
      'python':sys.version,'ChinaTravel_HEAD':revision.stdout.strip(),'ChinaTravel_scoped_status':dirty.stdout.strip(),
      'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
      'packages':{name:importlib.metadata.version(name) for name in ('overturemaps','pyarrow','shapely','requests','orjson','tqdm')},
      'not_rerun':'Full historical P0-P10 experiments and old flat-overlay acceptance demonstrations were not rerun; prior output files remain historical.'}
    (OUT/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'all_passed':result['all_passed'],'total_tests':result['total_tests'],'checks':checks},ensure_ascii=False))
    if not result['all_passed']:raise SystemExit(1)
if __name__=='__main__':main()
