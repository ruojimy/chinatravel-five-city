import collections,json,sqlite3,gzip
from pathlib import Path
root=Path(__file__).resolve().parents[1]
db=sqlite3.connect(root/'data/business_catalog_v1_4_20261022/catalog.sqlite3')
c=collections.Counter();example=None;replacements=collections.Counter()
for payload, in db.execute('SELECT payload FROM records'):
    x=json.loads(payload)
    replacements[x['kind']]+= '\ufffd' in x['name']
    if x['record_id'].startswith('overture:') and example is None:example=x['source_locator']
    for k in x['source_locator']:c[k]+=1
print(json.dumps({'source_locator_keys':dict(c),'example':example,'replacement_character_names':dict(replacements)},ensure_ascii=True))
with gzip.open(root/example['raw_file'],'rt',encoding='utf-8') as f:
    for i,line in enumerate(f,1):
        if i==example['raw_line']:
            row=json.loads(line);print(json.dumps(row,ensure_ascii=True)[:12000]);break
