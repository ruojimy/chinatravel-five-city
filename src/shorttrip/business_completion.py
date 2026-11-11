"""Scope-aware business values: date/room joins and multi-window hours stay explicit."""
from __future__ import annotations
import copy,hashlib,json,math,re
from datetime import date
from .business_archives import parse_hours
from .expansion_contract import FIELDS,VERSION,validate_record
from .freshness import field_policy,parse_time,POLICIES

def complete_native(record):
    optional={'hotelname_en','recommendedfood'}
    return all(k in record['data'] and (k in optional or record['data'][k] not in (None,''))
               for k in FIELDS[record['kind']])

def validate_room_offer(offer,*,now=None):
    errors=[];blockers=[]
    for key in ('offer_id','entity_id','room_type_name','bed_count','rooms_reserved','adults','children',
           'checkin','checkout','nights','currency','rate_plan_name','price_breakdown','observed_at',
           'retrieved_at','valid_until','source_id','source_url','screenshot_evidence'):
        if key not in offer:errors.append('missing:'+key)
    for key in ('offer_id','entity_id','room_type_name','rate_plan_name','source_id','source_url','currency'):
        if not isinstance(offer.get(key),str) or not offer[key].strip():errors.append('invalid_text:'+key)
    for key in ('bed_count','rooms_reserved','adults','children','nights'):
        value=offer.get(key)
        if type(value) is not int or value<(0 if key=='children' else 1):errors.append('invalid_integer:'+key)
    try:
        nights=(date.fromisoformat(offer['checkout'])-date.fromisoformat(offer['checkin'])).days
        if nights<=0 or nights!=offer['nights']:errors.append('stay_duration_mismatch')
    except (KeyError,TypeError,ValueError):errors.append('invalid_stay_dates')
    for key in ('observed_at','retrieved_at','valid_until'):
        if not parse_time(offer.get(key)):errors.append('invalid_clock:'+key)
    breakdown=offer.get('price_breakdown') or {}
    total=breakdown.get('displayed_stay_total')
    if isinstance(total,bool) or not isinstance(total,(int,float)) or not math.isfinite(total) or total<0:
        errors.append('invalid_total')
    parts=[breakdown.get(k) for k in ('room_base','service_charge','tax_and_government_charge')]
    if all(type(x) in (int,float) and math.isfinite(x) for x in parts) and type(total) in (int,float):
        if abs(sum(parts)-total)>0.011:errors.append('arithmetic_mismatch')
        if any(x<0 for x in parts):errors.append('negative_price_component')
    else:blockers.append('price_components_not_fully_disclosed')
    if offer.get('membership_required') is not False:blockers.append('eligibility_not_unrestricted')
    if not offer.get('room_type_id'):blockers.append('room_identity_incomplete')
    # Preserve source-reported qualifications instead of treating them as errors.
    if offer.get('quote_status') and 'conditional' in offer['quote_status']:blockers.append('conditional_source_quote')
    context={'checkin':offer.get('checkin'),'checkout':offer.get('checkout'),'rooms':offer.get('rooms_reserved'),
       'adults':offer.get('adults'),'children':offer.get('children'),'room_type_id':offer.get('room_type_id'),
       'rate_plan_id':offer.get('rate_plan_id'),'currency':offer.get('currency')}
    if not isinstance(offer.get('screenshot_evidence'),list) or not offer.get('screenshot_evidence'):errors.append('screenshot_evidence_required')
    else:
        for item in offer['screenshot_evidence']:
            if not isinstance(item,dict) or not re.fullmatch(r'[0-9a-f]{64}',str(item.get('sha256',''))):errors.append('invalid_screenshot_ref')
    at=parse_time(now) if now else None;end=parse_time(offer.get('valid_until'));observed=parse_time(offer.get('observed_at'))
    if observed and end and (end-observed).total_seconds()>POLICIES['dynamic_price'][0]:errors.append('quote_ttl_extended')
    fresh=bool(at and end and observed and observed<=at<end)
    return {'ok':not errors,'errors':errors,'budget_use_blockers':blockers,'context':context,
         'current_quote_fresh':fresh,'native_price_per_room_night':total/offer['nights']/offer['rooms_reserved']
             if not errors and not blockers else None,
         'not_a_booking_or_guarantee':True}

def api_restaurant(row,meta):
    """AMap human cost is an average per-person reference, never a room rate."""
    if not row.get('type','').startswith('餐饮服务;'):return None
    sid='amap_business_snapshot';rid='amap:'+row['id'];kind='restaurant';b=row.get('business') or {}
    data={key:None for key in FIELDS[kind]}
    lon,lat=map(float,row['location'].split(','));price=None
    if re.fullmatch(r'\d+(?:\.\d{1,2})?',str(b.get('cost',''))):price=float(b['cost'])
    hours,flags=parse_hours(b.get('opentime_today'))
    category=row.get('type','').split(';')[-1]
    cuisine=b.get('keytag') if b.get('keytag') and ',' not in b['keytag'] else category
    if cuisine in ('餐饮相关','餐饮相关场所','餐饮服务'):cuisine=None
    data.update(id=int(hashlib.sha256(rid.encode()).hexdigest()[:12],16),name=row['name'],
        lat=lat,lon=lon,price=price,cuisine=cuisine,recommendedfood=b.get('tag') or '')
    data.update(hours)
    fields={key:field_policy(key,kind) for key in data}
    prov={key:{'source_id':sid,'source_url':meta['endpoint'],'observed_at':None,'valid_until':None,
       'status':'unknown' if value is None else 'source_value','source_property':key} for key,value in data.items()}
    prov['id']['status']='derived';prov['id']['source_property']='stable_local_hash_of_amap_id'
    at=meta['retrieved_at'];city=row['cityname'].removesuffix('市')
    record={'schema_version':VERSION,'record_id':rid,'language':'zh','kind':kind,'city':city,
      'name':row['name'],'data':data,'tags':[{'tag':'cuisine','value':cuisine,'basis':'business.keytag_or_type',
          'status':'source_attribute_unverified','policy_id':'theme','source_time_ref':'record.observed_at','valid_until':None}],
      'source_id':sid,'source_url':meta['endpoint'],'source_locator':{'amap_id':row['id'],'provider_city_match':True,
          'raw_poi':row,'raw_sha256':hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
          'business_cost_semantics':'provider_average_per_person_reference_CNY_not_bill_or_maximum',
          'opening_hours_scope':'provider_today_'+at[:10]+'; not automatically applicable to future travel dates'},
      'source_published_at':None,'source_updated_at':None,'observed_at':None,'retrieved_at':at,'catalogued_at':at,
      'valid_from':None,'valid_until':None,'field_policies':fields,'field_provenance':prov,
      'authority':'structured_map_provider','licence_status':'api_terms','coordinate_system':'GCJ02',
      'coordinate_order':'named_lat_lon_columns','trust_status':'discovery_only','entity_verified':False,
      'needs_live_verification':True,'synthetic':False,'uncertainty_flags':[
       'unknown_provider_fact_observation_time','average_spend_not_guaranteed_bill','future_hours_need_date_verification']+flags,
      'business_rules':{'opentime_today':b.get('opentime_today'),'opentime_week':b.get('opentime_week'),
          'price_currency':'CNY','price_basis':'average_per_person_reference','source_type':row.get('type')}}
    return record

def validate_operator_field(item):
    errors=[]
    for key in ('entity_scope','field','value','unit','scope','quote','source_url','source_id',
                'source_published_at','source_updated_at','observed_at','retrieved_at','raw_page_sha256',
                'quality_status','native_projection_allowed'):
        if key not in item:errors.append('missing:'+key)
    for key in ('entity_scope','field','scope','quote','source_url','source_id','quality_status'):
        if not isinstance(item.get(key),str) or not item[key].strip():errors.append('invalid_text:'+key)
    for key in ('observed_at','source_published_at','source_updated_at','retrieved_at'):
        if item.get(key) is not None and not parse_time(item[key]):errors.append('invalid_clock:'+key)
    if not parse_time(item.get('retrieved_at')):errors.append('retrieved_clock_required')
    if not re.fullmatch(r'[a-f0-9]{64}',str(item.get('raw_page_sha256'))):errors.append('raw_digest_required')
    if type(item.get('native_projection_allowed')) is not bool:errors.append('projection_flag_boolean')
    try:json.dumps(item,allow_nan=False)
    except (ValueError,TypeError):errors.append('finite_json_required')
    return {'ok':not errors,'errors':errors,'binding_required_before_projection':True}

def details(path,entity_id,*,now=None):
    import sqlite3
    from pathlib import Path
    from .freshness import utcnow
    at=now or utcnow();db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        row=db.execute('SELECT payload FROM records WHERE id=?',(entity_id,)).fetchone()
        if not row:raise ValueError('Unknown record_id')
        record=json.loads(row['payload']);offers=[]
        for item in db.execute('SELECT payload FROM room_offers WHERE entity_id=?',(entity_id,)):
            offer=json.loads(item['payload']);offers.append({'offer':offer,'current_gate':validate_room_offer(offer,now=at)})
        histories=[json.loads(x[0]) for x in db.execute('SELECT payload FROM historical_references WHERE entity_id=?',(entity_id,))]
        return {'checked_at':at,'record':record,'current_record_gate':validate_record(record,now=at),
            'native_operational_complete':complete_native(record),'room_offers':offers,'historical_references':histories,
            'network_calls':0,'recommendation_ready':False,
            'price_note':'A stored amount can be a dated reference or expired quote. Check the same room/date/guest/rate context and current validity before budgeting.'}
    finally:db.close()
