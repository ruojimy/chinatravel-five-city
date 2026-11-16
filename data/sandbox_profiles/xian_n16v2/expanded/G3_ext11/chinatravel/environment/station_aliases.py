"""City-scoped railway-station aliases with reproducible source evidence.

The station name must occur as an actual endpoint in a city-pair train record.
The two spellings must each have exactly one same-city POI entry within 25 m.
This proximity is supporting evidence of identity, not independent map
verification. An ordinary same-location business is never an alias merely
because it shares coordinates.  Missing/ambiguous evidence remains unknown.
"""
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json, math, re

CITIES={'北京':'beijing','上海':'shanghai','南京':'nanjing','苏州':'suzhou','杭州':'hangzhou',
        '深圳':'shenzhen','成都':'chengdu','武汉':'wuhan','广州':'guangzhou','重庆':'chongqing','西安':'xian'}
SLUG_TO_CITY={v:k for k,v in CITIES.items()}

def _sha(data):return sha256(data).hexdigest()
def _valid_position(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2:return None
    try:a,b=map(float,value)
    except (TypeError,ValueError):return None
    if not all(math.isfinite(x) for x in (a,b)) or not (-90<=a<=90 and -180<=b<=180):return None
    return (a,b)

def _pair(name):
    if not isinstance(name,str) or not name:return None
    alt=name[:-1] if name.endswith('站') else name+'站'
    return tuple(sorted((name,alt))) if alt else None

def _distance_m(a,b):
    lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2*6371000*math.asin(min(1,math.sqrt(h)))

@lru_cache(maxsize=16)
def build_index(root):
    """Build from immutable root; evidence includes train and POI file hashes."""
    root=Path(root).resolve(); db=root/'chinatravel/environment/database'
    tr=db/'intercity_transport/train'; poi=db/'poi'
    if not tr.is_dir() or not poi.is_dir():raise FileNotFoundError('train or POI database not found')
    train_names=defaultdict(lambda:defaultdict(list))
    for path in sorted(tr.glob('from_*_to_*.json')):
        match=re.fullmatch(r'from_(.+)_to_(.+)\.json',path.name)
        if not match:continue
        origin,dest=match.groups()
        if origin not in CITIES or dest not in CITIES:continue
        raw=path.read_bytes(); digest=_sha(raw)
        for row in json.loads(raw.decode('utf-8-sig')):
            if not isinstance(row,dict) or not row.get('TrainID'):continue
            for city,key in ((origin,'From'),(dest,'To')):
                name=row.get(key)
                if isinstance(name,str) and name.strip():
                    train_names[city][name.strip()].append({'file':str(path.relative_to(root)),
                        'sha256':digest,'train_id':str(row['TrainID']),'field':key})
    mapped={};unresolved={};pairs=[]
    for city,slug in CITIES.items():
        path=poi/slug/'poi.json'
        if not path.is_file():continue
        raw=path.read_bytes();phash=_sha(raw);names=defaultdict(list)
        for row in json.loads(raw.decode('utf-8-sig')):
            if isinstance(row,dict) and isinstance(row.get('name'),str):
                names[row['name']].append(_valid_position(row.get('position')))
        seen=set()
        for station in sorted(train_names[city]):
            pair=_pair(station)
            if pair is None or pair in seen:continue
            seen.add(pair); left,right=pair;la,lb=names.get(left,[]),names.get(right,[])
            key=(city,left,right)
            distance=(_distance_m(la[0],lb[0]) if len(la)==len(lb)==1
                      and la[0] is not None and lb[0] is not None else None)
            if distance is not None and distance<=25:
                canonical=right if right.endswith('站') else left
                proof={'city':city,'names':[left,right],'canonical':canonical,'position':list(la[0]),
                       'positions':[list(la[0]),list(lb[0])],
                       'distance_m':round(distance,3),'position_tolerance_m':25,
                       'identity_basis':'unique city POIs, train endpoint, suffix and proximity; inferred',
                       'poi_file':str(path.relative_to(root)),'poi_sha256':phash,
                       'train_evidence':train_names[city][station][0]}
                mapped[(city,left)]=proof;mapped[(city,right)]=proof;pairs.append(proof)
            else:
                unresolved[key]={'city':city,'names':[left,right],
                    'reason':'missing_ambiguous_invalid_or_different_poi_coordinates',
                    'poi_counts':[len(la),len(lb)],'train_evidence':train_names[city][station][0]}
    return {'root':str(root),'mapped':mapped,'unresolved':unresolved,'pairs':pairs,'train_names':train_names}

def compare(root,city,left,right,*,station_context=False):
    """Return pass/fail/unknown with proof for a spatial endpoint comparison."""
    if not isinstance(left,str) or not isinstance(right,str):return {'state':'unknown','reason':'missing_endpoint'}
    if left==right:return {'state':'pass','reason':'literal_equal'}
    city=SLUG_TO_CITY.get(city,city)
    if city not in CITIES:return {'state':'unknown','reason':'unsupported_city'}
    idx=build_index(str(Path(root).resolve()))
    a,b=idx['mapped'].get((city,left)),idx['mapped'].get((city,right))
    if station_context and a is not None and a is b:
        return {'state':'pass','reason':'verified_station_alias','evidence':a}
    pair=tuple(sorted((left,right)))
    if station_context and (city,*pair) in idx['unresolved']:
        return {'state':'unknown','reason':'station_alias_not_proven','evidence':idx['unresolved'][(city,*pair)]}
    return {'state':'fail','reason':'different_locations'}

def resolve_for_poi(root,city,name,available):
    """Try only a proved same-city train alias that remains permitted by POI gate."""
    city=SLUG_TO_CITY.get(city,city)
    if name in available:return name
    if city not in CITIES:return None
    proof=build_index(str(Path(root).resolve()))['mapped'].get((city,name))
    if proof is None:return None
    candidates=[x for x in proof['names'] if x in available]
    return candidates[0] if len(candidates)==1 else None

def station_alias_info(root,city,name):
    city=SLUG_TO_CITY.get(city,city)
    if city not in CITIES or not isinstance(name,str):return None
    return build_index(str(Path(root).resolve()))['mapped'].get((city,name))

def _verdict(states):
    return 'fail' if 'fail' in states else 'unknown' if 'unknown' in states else 'pass'

def validate_space(query,plan,root):
    """Match native first/last intercity and local continuity contracts.

    Alias reasoning applies only when the compared endpoint participates in a
    train activity; identical coordinates of ordinary POIs do not merge them.
    """
    issues=[];evidence=[]
    def issue(state,code,day,index,detail=None):
        x={'state':state,'code':code,'day':day,'activity_index':index}
        if detail is not None:x['detail']=detail
        issues.append(x)
    if not isinstance(plan,dict) or not isinstance(plan.get('itinerary'),list) or not plan['itinerary']:
        return {'state':'unknown','issues':[{'state':'unknown','code':'missing_itinerary'}],'station_alias_evidence':[]}
    city=query.get('target_city');previous=None;previous_type=None;days=plan['itinerary']
    activity_locations=[(di,ai) for di,bucket in enumerate(days) if isinstance(bucket,dict)
                        and isinstance(bucket.get('activities'),list)
                        for ai,_ in enumerate(bucket['activities'])]
    for day_index,day in enumerate(days):
        if not isinstance(day,dict) or not isinstance(day.get('activities'),list):
            issue('unknown','invalid_day',day_index+1,0);continue
        acts=day['activities']
        for index,act in enumerate(acts):
            if not isinstance(act,dict):issue('unknown','invalid_activity',day_index+1,index+1);continue
            kind=act.get('type'); intercity=kind in ('train','airplane')
            first=bool(activity_locations and (day_index,index)==activity_locations[0])
            last=bool(activity_locations and (day_index,index)==activity_locations[-1])
            if intercity and not (first or last):issue('fail','intercity_not_first_or_last',day_index+1,index+1)
            if 'position' in act:current=act.get('position')
            elif intercity:current=act.get('start')
            else:
                issue('fail','missing_position_non_intercity',day_index+1,index+1)
                previous=None;previous_type=kind;continue
            legs=act.get('transports')
            if not isinstance(legs,list):
                issue('fail','missing_transports',day_index+1,index+1);legs=[]
            def eq(left,right,context,which):
                result=compare(root,city,left,right,station_context=context)
                if result.get('evidence'):
                    evidence.append({'day':day_index+1,'activity_index':index+1,'comparison':which,**result})
                return result['state']
            if first and intercity and legs:
                if not isinstance(legs[-1],dict):
                    issue('unknown','invalid_outbound_transport_leg',day_index+1,index+1)
                else:
                    origin_city=query.get('start_city')
                    result=compare(root,origin_city,legs[-1].get('end'),current,
                                   station_context=(kind=='train'))
                    if result['state']!='pass':
                        issue(result['state'],'outbound_transport_end_mismatch',day_index+1,index+1)
            if previous is not None:
                same=eq(previous,current,previous_type=='train' or kind=='train','activity_positions')
                if same=='pass':
                    if legs:issue('fail','transport_between_identical_positions',day_index+1,index+1)
                elif same=='unknown':
                    issue('unknown','station_identity_unresolved',day_index+1,index+1)
                elif not legs:issue('fail','missing_transport_between_positions',day_index+1,index+1)
                else:
                    if not isinstance(legs[0],dict) or not isinstance(legs[-1],dict):
                        issue('unknown','invalid_transport_leg',day_index+1,index+1)
                    else:
                        start=eq(legs[0].get('start'),previous,previous_type=='train','transport_start')
                        end=eq(legs[-1].get('end'),current,kind=='train','transport_end')
                        if start!='pass':issue(start,'transport_start_mismatch',day_index+1,index+1)
                        if end!='pass':issue(end,'transport_end_mismatch',day_index+1,index+1)
            previous=act.get('position') if 'position' in act else act.get('end')
            if previous is None:issue('unknown','missing_previous_position',day_index+1,index+1)
            previous_type=kind
    return {'state':_verdict([x['state'] for x in issues]),'issues':issues,'station_alias_evidence':evidence,
            'policy':'Native spatial contract, with verified same-city train-station aliases and unknown for missing alias evidence.'}
