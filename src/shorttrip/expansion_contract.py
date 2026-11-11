"""Strict expansion envelope: discovery is useful; completeness is not truth.

No enrichment, replacement defaults, network, or benchmark-file writes occur here.
"""
from __future__ import annotations

import math
import re
import json
from datetime import datetime, timezone
from .freshness import POLICIES, field_policy, parse_time, utcnow

VERSION = 'travel-expansion-v1'
FIELDS = {
    'attraction': ('id','name','type','lat','lon','opentime','endtime','price',
                   'recommendmintime','recommendmaxtime'),
    'restaurant': ('id','name','lat','lon','price','cuisine','opentime','endtime','recommendedfood'),
    'accommodation': ('id','name','hotelname_en','featurehoteltype','lat','lon','price','numbed'),
    'poi': ('name','position'),
    'metro_station': ('name','position','line'),
    'train': ('TrainID','TrainType','From','To','BeginTime','EndTime','Duration','Cost'),
    'flight': ('FlightID','From','To','BeginTime','EndTime','Duration','Cost'),
}
# These descriptive fields may honestly be empty; no empty critical fields allowed.
OPTIONAL_VALUES = {'hotelname_en', 'recommendedfood'}
METADATA = ('record_id','language','kind','city','name','source_id','source_url','source_locator',
            'source_published_at','source_updated_at','observed_at','retrieved_at','catalogued_at',
            'valid_from','valid_until','field_policies','field_provenance','authority','licence_status',
            'coordinate_system','coordinate_order','trust_status','entity_verified',
            'needs_live_verification','uncertainty_flags','synthetic','tags')
CLOCKS = ('source_published_at','source_updated_at','observed_at','retrieved_at','catalogued_at',
          'valid_from','valid_until')
HHMM = re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d$')

def _known(v):
    return v is not None and v != ''

def _number(v):
    return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)

def _json_value(v):
    try:json.dumps(v,allow_nan=False);return True
    except (TypeError,ValueError):return False

def _text(v):return isinstance(v,str) and bool(v.strip())

def _clock(v):return isinstance(v,str) and parse_time(v) is not None

def validate_record(record, *, now=None, allow_synthetic=False):
    """Return structural discovery eligibility and stricter planning completeness.

    planning_ready means usable in a frozen provenance-labelled experiment at
    ``now``. It does not certify today's availability, an authoritative fact, or
    exemption from P11 mandatory dynamic retrieval.
    """
    errors=[]; warnings=[]; missing=[]; blocked=[]
    if not isinstance(record,dict):
        return {'discovery_ok':False,'planning_ready':False,'errors':['record_not_object'],
                'warnings':[],'missing_planning_fields':[],'planning_blockers':['invalid_record']}
    kind=record.get('kind') if isinstance(record.get('kind'),str) else ''
    at=parse_time(now or utcnow())
    if at is None:raise ValueError('now requires ISO8601 timezone')
    if record.get('schema_version')!=VERSION:errors.append('schema_version')
    if not _json_value(record):errors.append('not_finite_json_value')
    for key in METADATA:
        if key not in record:errors.append('missing_metadata:'+key)
    for key in ('record_id','city','name','source_id','authority','trust_status','licence_status'):
        if not isinstance(record.get(key),str) or not record[key].strip():errors.append('invalid_metadata:'+key)
    if record.get('language') not in ('zh','en'):errors.append('language')
    if kind not in FIELDS:errors.append('kind')
    for key in ('entity_verified','needs_live_verification','synthetic'):
        if not isinstance(record.get(key),bool):errors.append('not_boolean:'+key)
    if not isinstance(record.get('source_locator'),dict):errors.append('source_locator')
    if isinstance(record.get('uncertainty_flags'),list):
        for flag in ('untrusted_website_source_requires_review','source_city_conflicts_with_research_window','source_property_address_conflicts_require_review'):
            if flag in record['uncertainty_flags']:blocked.append(flag)
    if 'today_hours_structured' in record:
        from .scoped_business import validate_hours
        hours_gate=validate_hours(record['today_hours_structured'],require_provenance=True)
        errors.extend('today_hours:'+e for e in hours_gate['errors'])
        if isinstance(record['today_hours_structured'],dict) and record['today_hours_structured'].get('entity_id')!=record.get('record_id'):
            errors.append('today_hours:entity_mismatch')
    if 'operator_assertions' in record:
        from .operator_assertions import validate_assertion
        assertions=record['operator_assertions']
        if not isinstance(assertions,list):errors.append('operator_assertions:list_required')
        else:
            for item in assertions:
                ag=validate_assertion(item);errors.extend('operator_assertion:'+e for e in ag['errors'])
                if isinstance(item,dict) and item.get('entity_id')!=record.get('record_id'):errors.append('operator_assertion:entity_mismatch')
            if assertions:blocked.append('operator_assertions_require_date_room_and_freshness_gate')
    if record.get('source_url') is not None and not isinstance(record.get('source_url'),str):errors.append('source_url')
    for key in CLOCKS:
        if record.get(key) is not None and not _clock(record[key]):errors.append('invalid_clock:'+key)
    for key in ('retrieved_at','catalogued_at'):
        if not parse_time(record.get(key)):errors.append('required_clock:'+key)
    for key in ('field_policies','field_provenance'):
        if not isinstance(record.get(key),dict):errors.append(key)
    if not isinstance(record.get('uncertainty_flags'),list) or not all(_text(x) for x in record['uncertainty_flags']):
        errors.append('uncertainty_flags')
    if record.get('coordinate_system') not in ('WGS84','GCJ02','BD09','unknown'):errors.append('coordinate_system')
    order={'poi':'latitude,longitude','metro_station':'longitude,latitude',
           'train':'not_applicable','flight':'not_applicable'}.get(kind,'named_lat_lon_columns')
    if record.get('coordinate_order')!=order:errors.append('coordinate_order')
    tags=record.get('tags')
    if not isinstance(tags,list):errors.append('tags')
    else:
        for index,tag in enumerate(tags):
            errors.extend('tag:'+str(index)+':'+e for e in validate_tag(tag)['errors'])
    data=record.get('data')
    if not isinstance(data,dict):errors.append('data');data={}
    required=FIELDS.get(kind,())
    policies=record.get('field_policies') or {}; provenance=record.get('field_provenance') or {}
    if not isinstance(policies,dict):policies={}
    if not isinstance(provenance,dict):provenance={}
    for key in required:
        if key not in data:errors.append('missing_data_key:'+key)
        value=data.get(key)
        if not _known(value) and key not in OPTIONAL_VALUES:missing.append(key)
        if policies.get(key) != field_policy(key,kind):errors.append('field_policy:'+key)
        p=provenance.get(key)
        if not isinstance(p,dict) or any(k not in p for k in ('source_id','source_url','observed_at','status')):
            errors.append('field_provenance:'+key);continue
        if p['observed_at'] is not None and not _clock(p['observed_at']):errors.append('field_clock:'+key)
        if p['source_id'] is not None and not _text(p['source_id']):errors.append('field_source_id:'+key)
        if p['source_url'] is not None and not _text(p['source_url']):errors.append('field_source_url:'+key)
        if (p['source_id']==record.get('source_id') and p['source_url'] and record.get('source_url')
                and p['source_url']!=record['source_url']):errors.append('field_source_url_mismatch:'+key)
        if p['source_id'] and p['source_id']!=record.get('source_id') and not p.get('evidence_id'):
            errors.append('field_external_source_requires_evidence_ref:'+key)
        if p.get('evidence_id') is not None and not _text(p['evidence_id']):errors.append('field_evidence_id:'+key)
        if p['status'] not in ('unknown','source_value','estimated','synthetic','derived'):
            errors.append('field_status:'+key)
        if _known(value) and key not in OPTIONAL_VALUES:
            if p['status'] not in ('source_value', 'synthetic'):
                blocked.append('unverified_field:'+key)
            if p['status']=='synthetic' and not (allow_synthetic and record.get('synthetic')):
                blocked.append('synthetic_field:'+key)
            if not p['source_id']:blocked.append('missing_field_source:'+key)
            observed=parse_time(p['observed_at'])
            if not observed:blocked.append('unknown_field_age:'+key)
            else:
                policy=policies.get(key)
                ttl=POLICIES.get(policy,(0,False))[0] if isinstance(policy,str) else 0
                age=(at-observed).total_seconds()
                if age < -300:blocked.append('future_field_time:'+key)
                if age>=ttl:blocked.append('expired_field:'+key)
            until=p.get('valid_until')
            if until is not None:
                end=parse_time(until)
                if not _clock(until):errors.append('field_expiry:'+key)
                elif at>=end:blocked.append('expired_field:'+key)
                if end and observed and end<observed:errors.append('field_validity_order:'+key)
    numeric_fields={'id','lat','lon','price','recommendmintime','recommendmaxtime','numbed','Duration','Cost'}
    for key in required:
        if key not in numeric_fields and key!='position' and _known(data.get(key)) and not isinstance(data[key],str):
            errors.append('string_required:'+key)
    name_field={'train':'TrainID','flight':'FlightID'}.get(kind,'name')
    if _known(data.get(name_field)) and data[name_field]!=record.get('name'):errors.append('name_mismatch')
    for key in ('lat','lon','price','recommendmintime','recommendmaxtime','numbed','id','Duration','Cost'):
        value=data.get(key)
        if not _known(value):continue
        if not _number(value):errors.append('invalid_number:'+key);continue
        if key=='lat' and not -90<=value<=90:errors.append('latitude_range')
        if key=='lon' and not -180<=value<=180:errors.append('longitude_range')
        if key in ('price','recommendmintime','recommendmaxtime','Duration','Cost') and value<0:errors.append('negative:'+key)
        if key=='recommendmintime' and value==0:errors.append('zero_visit_duration')
        if key in ('numbed','id') and not isinstance(value,int):errors.append('integer_required:'+key)
        if key=='numbed' and value<1:errors.append('invalid_numbed')
    if _number(data.get('recommendmintime')) and _number(data.get('recommendmaxtime')):
        if data['recommendmaxtime']<data['recommendmintime']:errors.append('visit_duration_order')
    for key in ('opentime','endtime','BeginTime','EndTime'):
        if _known(data.get(key)) and not HHMM.fullmatch(str(data[key])):errors.append('invalid_time:'+key)
    if record.get('kind') in ('poi','metro_station') and _known(data.get('position')):
        pos=data['position']
        if record['kind']=='metro_station':
            try:lon,lat=map(float,pos.split(','));valid=-90<=lat<=90 and -180<=lon<=180
            except (ValueError,TypeError,AttributeError):valid=False
        else:
            valid=(isinstance(pos,(list,tuple)) and len(pos)==2 and all(_number(x) for x in pos)
                   and -90<=pos[0]<=90 and -180<=pos[1]<=180)
        if not valid:errors.append('position_format_or_range')
    if record.get('kind') not in ('train','flight') and record.get('coordinate_system')!='WGS84':
        blocked.append('checker_requires_wgs84_coordinates')
    if record.get('exclude_from_static_planning'):
        blocked.append('reported_closure_requires_reopening_evidence')
    if record.get('kind') in ('train','flight'):
        for key in ('start_city','end_city'):
            if not record.get(key):blocked.append('intercity_scope_unknown:'+key)
            elif not _text(record[key]):errors.append('intercity_scope_type:'+key)
    if record.get('entity_verified') is not True:blocked.append('entity_unverified')
    if record.get('trust_status') in ('unverified','untrusted','conflict','rejected','discovery_only'):
        blocked.append('record_trust_not_planning_eligible')
    if record.get('licence_status') not in ('allowed','api_terms','cc_by','cc0','odbl'):
        blocked.append('usage_rights_unknown')
    if record.get('synthetic') and not allow_synthetic:blocked.append('synthetic_record')
    for key in ('source_published_at','source_updated_at','observed_at','retrieved_at','catalogued_at'):
        t=parse_time(record.get(key))
        if t and (t-at).total_seconds()>300:blocked.append('future_clock:'+key)
    if parse_time(record.get('valid_from')) and at<parse_time(record['valid_from']):blocked.append('not_yet_applicable')
    if parse_time(record.get('valid_until')) and at>=parse_time(record['valid_until']):blocked.append('record_expired')
    if parse_time(record.get('valid_from')) and parse_time(record.get('valid_until')):
        if parse_time(record['valid_until'])<parse_time(record['valid_from']):errors.append('record_validity_order')
    if not record.get('source_url') and not record.get('source_locator'):blocked.append('source_not_locatable')
    if record.get('needs_live_verification') is True:warnings.append('mandatory_live_fields_not_waived')
    if missing:warnings.append('discovery_only_missing_fields')
    return {'schema_version':VERSION,'discovery_ok':not errors,
            'planning_ready':not (errors or missing or blocked),
            'missing_planning_fields':missing,'planning_blockers':sorted(set(blocked)),
            'errors':sorted(set(errors)),'warnings':warnings,'checked_at':at.isoformat(),
            'real_world_accuracy_certified':False,'mandatory_dynamic_retrieval_waived':False}


def validate_evidence(item):
    """Audit a stored source snapshot, independently of a provider truth claim."""
    import hashlib
    errors=[]
    if not isinstance(item,dict):return {'ok':False,'errors':['evidence_not_object']}
    for key in ('evidence_id','source_id','source_url','retrieved_at','raw_text','raw_sha256',
                'authority','licence_status','source_published_at','source_updated_at','observed_at'):
        if key not in item:errors.append('missing:'+key)
    for key in ('retrieved_at','source_published_at','source_updated_at','observed_at'):
        if item.get(key) is not None and not _clock(item[key]):errors.append('invalid_clock:'+key)
    if not parse_time(item.get('retrieved_at')):errors.append('required_clock:retrieved_at')
    for key in ('evidence_id','source_id','source_url','authority','licence_status'):
        if not _text(item.get(key)):errors.append('invalid_text:'+key)
    if not _json_value(item):errors.append('not_finite_json_value')
    raw=item.get('raw_text')
    if not isinstance(raw,str):errors.append('raw_text')
    elif item.get('raw_sha256')!=hashlib.sha256(raw.encode('utf-8')).hexdigest():errors.append('raw_digest_mismatch')
    return {'ok':not errors,'errors':errors,'truth_certified':False}


def validate_claim(item,evidence_by_id,*,now=None,registry=None):
    """Check exact quotation, provenance refs, policy and P11 semantic gates."""
    from .freshness import check_claim
    errors=[]
    if not isinstance(item,dict):return {'ok':False,'errors':['claim_not_object']}
    for key in ('claim_id','entity_id','evidence_id','field','value','unit','quote',
                'source_id','source_url','observed_at','retrieved_at','valid_until','context'):
        if key not in item:errors.append('missing:'+key)
    for key in ('claim_id','entity_id','evidence_id','field','quote','source_id','source_url'):
        if not _text(item.get(key)):errors.append('invalid_text:'+key)
    if item.get('unit') is not None and not isinstance(item['unit'],str):errors.append('unit_type')
    if not isinstance(item.get('context'),dict):errors.append('context_type')
    if not _json_value(item):errors.append('not_finite_json_value')
    evidence=evidence_by_id.get(item.get('evidence_id')) if isinstance(evidence_by_id,dict) and isinstance(item.get('evidence_id'),str) else None
    if not isinstance(evidence,dict):errors.append('unknown_evidence')
    else:
        ev=validate_evidence(evidence)
        errors.extend('evidence:'+e for e in ev['errors'])
        if not isinstance(item.get('quote'),str) or not isinstance(evidence.get('raw_text'),str) or not item['quote'] or item['quote'] not in evidence['raw_text']:
            errors.append('unsupported_quote')
        for key in ('source_id','source_url','observed_at','retrieved_at'):
            if item.get(key)!=evidence.get(key):errors.append('evidence_mismatch:'+key)
    if not isinstance(item.get('field'),str) or item['field'] not in POLICIES:errors.append('unknown_field_policy')
    for key in ('observed_at','retrieved_at','valid_until'):
        if item.get(key) is not None and not _clock(item[key]):errors.append('invalid_clock:'+key)
    gate=None
    if not errors and registry is not None:
        full={**evidence,**item}
        gate=check_claim(full,item['field'],registry,now=now,context=item.get('context'))
    return {'ok':not errors,'errors':errors,'p11_gate':gate,'truth_certified':False}


def validate_tag(item,*,claims_by_id=None):
    errors=[]
    if not isinstance(item,dict):return {'ok':False,'errors':['tag_not_object']}
    for key in ('tag','value','basis','status','policy_id','source_time_ref','valid_until'):
        if key not in item:errors.append('missing:'+key)
    for key in ('tag','basis','status','policy_id','source_time_ref'):
        if not _text(item.get(key)):errors.append('invalid_text:'+key)
    if not isinstance(item.get('policy_id'),str) or item['policy_id'] not in POLICIES:errors.append('unknown_policy')
    if not _json_value(item):errors.append('not_finite_json_value')
    if item.get('valid_until') is not None and not _clock(item['valid_until']):errors.append('invalid_expiry')
    if item.get('claim_id') is not None and not _text(item['claim_id']):errors.append('claim_id_type')
    elif item.get('claim_id') and claims_by_id is not None and item['claim_id'] not in claims_by_id:
        errors.append('unknown_claim')
    return {'ok':not errors,'errors':errors,'truth_certified':False}


def validate_inline_claim(item):
    """P11 inline raw snapshots obey the same evidence/claim contract on write.

    Validation never invents an observation clock or upgrades a truth verdict.
    Legacy saved payloads remain readable; a new write needs the full contract.
    """
    if not isinstance(item,dict):return {'ok':False,'errors':['claim_not_object']}
    evidence={key:item.get(key) for key in ('evidence_id','source_id','source_url',
        'retrieved_at','raw_text','raw_sha256','authority','licence_status',
        'source_published_at','source_updated_at','observed_at') if key in item}
    gate=validate_evidence(evidence)
    eid=item.get('evidence_id')
    claim_gate=validate_claim(item,{eid:evidence} if isinstance(eid,str) else {})
    errors=gate['errors']+claim_gate['errors']
    return {'ok':not errors,'errors':list(dict.fromkeys(errors)),
            'truth_certified':False,'fact_freshness_must_be_checked_at_use':True}

def discovery_summary(records, *, now=None):
    """One-record-at-a-time summary, preserving unknowns and error reasons."""
    from collections import Counter
    counts=Counter(); errors=Counter(); blockers=Counter(); missing=Counter(); ids=set(); duplicate=[]
    for record in records:
        verdict=validate_record(record,now=now)
        counts['records']+=1;counts['discovery_ok']+=verdict['discovery_ok']
        counts['planning_ready']+=verdict['planning_ready']
        counts[str(record.get('kind') if isinstance(record,dict) else 'invalid')]+=1
        rid=record.get('record_id') if isinstance(record,dict) else None
        if not isinstance(rid,str):rid='invalid-record:'+str(counts['records'])
        if rid in ids:duplicate.append(rid)
        ids.add(rid)
        errors.update(verdict['errors']);blockers.update(verdict['planning_blockers'])
        missing.update(verdict['missing_planning_fields'])
    return {'counts':dict(counts),'errors':dict(errors),'planning_blockers':dict(blockers),
            'missing_planning_fields':dict(missing),
            'duplicate_record_ids':duplicate,'complete':not errors and not duplicate}
