"""Offline integration assertions; no provider or model calls."""
import json, sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
EXP=ROOT/'expanded'
sys.path.insert(0,str(EXP))
from sandbox_adapter import Sandbox
import dynamic_runtime

snapshot=dynamic_runtime.load_snapshot()
s=Sandbox('G3')
db=s.db
old=ROOT.parent/'dynamic_v4/expanded/G3_ext11/chinatravel/environment/database'
for kind in ('attractions','restaurants','accommodations'):
    for path in (db/kind).rglob('*.csv'):
        assert sha256(path.read_bytes()).digest()==sha256((old/path.relative_to(db)).read_bytes()).digest(),path

item=s._record('attraction','西安',7)
data=item['payload']['data'];access=item['payload']['access']
assert item['record_id']=='attraction:xian:8'
assert (data['lat'],data['lon'])==(34.264587,108.936378)
assert access['dynamic_field_evidence']['coordinate_system']=='GCJ02'
assert access['dynamic_field_evidence']['field_conflicts'][0]['status']=='conflict_unresolved_do_not_treat_as_current'
assert s.catalog_preflight('attraction:xian:8')['access']['dynamic_field_evidence']['field_conflicts']
assert access['reference_fields']['lat']['status']=='derived'
assert access['grade']=='L2' and access['dynamic_required_by_grade']
poi=json.loads((db/'poi/xian/poi.json').read_text(encoding='utf-8-sig'))
assert next(x['position'] for x in poi if x['name']=='回民街')==[data['lat'],data['lon']]

sys.path.insert(0,str(EXP/'G3_ext11'))
from chinatravel.environment.planning_access import scoped_frame, blocked_poi_names
frame=pd.read_csv(db/'attractions/xian/attractions.csv')
p34=scoped_frame(frame,'attraction','xian','zh')
match=p34[p34['id']==8].iloc[0]
assert (match['lat'],match['lon'])==(data['lat'],data['lon'])
assert '回民街' not in blocked_poi_names('西安')

counts={}
for kind in ('attraction','restaurant','accommodation'):
    _,_,_,exact,_,_,_=s._catalog(kind,'西安')
    counts[kind]=dict(Counter(s._record(kind,'西安',idx)['payload']['access']['grade'] for idx,_ in exact))
assert counts['attraction']['L2']>=20
assert counts['accommodation']['L3']>=388
for index in (1,8,12):
    result=s._record('accommodation','西安',index)
    assert result['payload']['access']['grade']=='L3'
    assert result['payload']['access']['dynamic_required_by_grade']
assert s._record('accommodation','西安',12)['payload']['data']['price'] is None
assert s._record('accommodation','西安',12)['payload']['access']['estimated_price_reference'] is not None

for a,b,train,price in [('西安','重庆','K4518',102),('成都','西安','G322',285)]:
    rows=json.loads((db/'intercity_transport/train'/f'from_{a}_to_{b}.json').read_text(encoding='utf-8-sig'))
    matched=[x for x in rows if x.get('TrainID')==train]
    assert len(matched)==1 and matched[0]['Cost']==price
    assert dynamic_runtime.direct_train(a,b,matched[0])['trip_date'] is None
assert not any(x['record']['TrainID'] in ('D1711','C6022','G1836') for x in snapshot['direct_trains'])
assumption=next(x for x in snapshot['attraction_prices'] if x['record_id']=='attraction:xian:672')
assert assumption['price']==0 and assumption['status']=='user_authorized_zero_assumption_after_search'
assert len(snapshot['evidence_files'])>=11
print(json.dumps({'result':'pass','grade_counts':counts,'recovered_lodging':36,'trains_checked':2,'csv_hashes':'unchanged'},ensure_ascii=True))
