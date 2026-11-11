"""Verify the actual frozen native shapes before claiming contract compatibility."""
import collections,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.travel_catalog import iter_rows,digest_file
from shorttrip.expansion_contract import FIELDS
from shorttrip.freshness import utcnow
def main():
    counts=collections.Counter();missing=collections.Counter();types=collections.defaultdict(collections.Counter);examples={}
    for lang,folder in [('zh','database'),('en','database_en')]:
        base=ROOT/'ChinaTravel/chinatravel/environment'/folder
        for path in sorted(base.rglob('*')):
            if not path.is_file():continue
            for kind,city,index,row in iter_rows(path,base):
                counts[lang+':'+kind]+=1
                for field in FIELDS[kind]:
                    if field not in row:missing[lang+':'+kind+':'+field]+=1
                    else:types[kind+':'+field][type(row[field]).__name__]+=1
                if kind in ('train','flight') and lang=='zh' and kind not in examples:examples[kind]=row
    root=ROOT/'results/p12_expansion'
    result={'checked_at':utcnow(),'counts':dict(counts),'missing_required_native_keys':dict(missing),
      'native_value_types':dict(types),'native_intercity_examples':examples,
      'meaning':'Original files checked read-only. Raw CSV numbers are text and require an explicit typed converter at a new-load boundary. Does not refresh fact ages or certify real-world facts.'}
    (root/'native_structure_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'counts':dict(counts),'missing':dict(missing),'examples':examples},ensure_ascii=False))
if __name__=='__main__':main()
