"""Field-level freshness and evidence gates, separate from benchmark truth."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import hashlib,json,math
from urllib.parse import urlparse

VERSION='travel-freshness-v1'
# Project defaults, not guarantees made by source providers. Seconds.
POLICIES={
 'identity':(90*86400,False),'coordinates':(90*86400,False),
 'theme':(180*86400,False),'experience':(90*86400,False),
 'opening_hours':(86400,True),'closure':(3600,True),
 'price':(86400,True),'inventory':(300,True),
 'dynamic_price':(300,True),'room_configuration':(30*86400,False),
 'weather_now':(900,True),'weather_forecast':(3600,True),'weather_alert':(600,True),
 'route_duration':(900,True),'route_fare':(1800,True),'route_disruption':(600,True),
 'intercity_schedule':(6*3600,True),'queue':(600,True),'accessibility':(7*86400,True),
}
REQUIRED_AMAP={'route_duration','route_fare'}
CONTEXT_REQUIRED={
 'weather_forecast':('adcode','travel_date'),
 'weather_now':('adcode',),'weather_alert':('adcode',),
 'route_duration':('origin','destination','coord_system','mode','departure_at'),
 'route_fare':('origin','destination','coord_system','mode','departure_at'),
 'inventory':('travel_date',),'intercity_schedule':('travel_date',),
 'opening_hours':('travel_date',),'closure':('travel_date',),'price':('travel_date',),
 'dynamic_price':('travel_date','party_size'),
}

def utcnow():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(value):return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()
def parse_time(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError,TypeError):return None

def field_policy(field,kind=''):
    if field in ('Cost','price') and kind in ('flight','train','accommodation'):return 'dynamic_price'
    if field in ('lat','lon','position'):return 'coordinates'
    if kind in ('train','flight'):return 'intercity_schedule'
    if kind=='metro_station':return 'route_disruption'
    if field in ('opentime','endtime','hours'):return 'opening_hours'
    if field in ('price','Cost'):return 'price'
    if field in ('duration','Duration','BeginTime','EndTime'):return 'intercity_schedule'
    if field in ('type','cuisine','featurehoteltype','recommendmintime','recommendmaxtime'):return 'theme'
    if field in ('numbed',):return 'room_configuration'
    return 'identity'

def fresh_state(record,field,*,now=None,context=None):
    """A retrieval/import timestamp cannot refresh an unknown source observation."""
    now=parse_time(now or utcnow())
    if now is None:raise ValueError('now must include timezone')
    ttl,mandatory=POLICIES[field]
    source_at=parse_time(record.get('observed_at') or record.get('source_updated_at'))
    retrieved=parse_time(record.get('retrieved_at'))
    reasons=[]
    if source_at is None:reasons.append('unknown_source_time')
    if source_at and source_at>now+timedelta(minutes=5):reasons.append('future_source_time')
    if retrieved and retrieved>now+timedelta(minutes=5):reasons.append('future_retrieval_time')
    # Checking both clocks prevents repeated downloads of old data renewing it.
    anchors=[t for t in (source_at,retrieved) if t]
    deadline=min(anchors)+timedelta(seconds=ttl) if source_at else None
    declared=record.get('valid_until')
    if declared and not parse_time(declared):reasons.append('invalid_valid_until')
    if parse_time(declared):deadline=min(deadline,parse_time(declared)) if deadline else parse_time(declared)
    if deadline and now>=deadline:reasons.append('expired')
    if CONTEXT_REQUIRED.get(field) and context is None:reasons.append('missing_request_context')
    if context is not None:
        actual=record.get('context',{})
        for key in CONTEXT_REQUIRED.get(field,()):
            if not context.get(key) or not actual.get(key) or actual[key]!=context[key]:reasons.append('context_mismatch:'+key)
        for key in ('travel_date','origin','destination','mode','departure_at','adcode','coord_system'):
            if key in actual and key in context and actual[key]!=context[key]:
                issue='context_mismatch:'+key
                if issue not in reasons:reasons.append(issue)
    if field=='weather_forecast' and context is not None:
        if context.get('travel_date') not in (record.get('coverage_dates') or []):reasons.append('outside_forecast_horizon')
    if context is not None and context.get('travel_date'):
        day=context['travel_date']
        if record.get('applies_from') and day<record['applies_from']:reasons.append('before_applicability_window')
        if record.get('applies_until') and day>record['applies_until']:reasons.append('after_applicability_window')
    return {'status':'fresh' if not reasons else 'unusable','reasons':reasons,
            'ttl_seconds':ttl,'valid_until':deadline.isoformat() if deadline else None,
            'mandatory_dynamic':mandatory,'retrieval_required':bool(reasons) or mandatory}

def check_claim(claim,field,registry,*,now=None,context=None):
    """Quality dimensions are explicit; authority is never an accuracy probability."""
    reasons=[];source=registry.get(claim.get('source_id'),{})
    if claim.get('field')!=field:reasons.append('wrong_field')
    if not parse_time(claim.get('retrieved_at')):reasons.append('unknown_retrieval_time')
    if not source:reasons.append('unregistered_source')
    allowed_hosts=source.get('allowed_hosts',[])
    if allowed_hosts and urlparse(claim.get('source_url','')).hostname not in allowed_hosts:reasons.append('source_host_mismatch')
    if field not in source.get('supports',[]):reasons.append('source_not_authoritative_for_field')
    if claim.get('entity_verified') is not True:reasons.append('entity_unverified')
    if claim.get('licence_status') not in ('allowed','api_terms'):reasons.append('usage_rights_unknown')
    raw=claim.get('raw_text','');quote=claim.get('quote','')
    if not quote or quote not in raw:reasons.append('unsupported_quote')
    if claim.get('raw_sha256')!=hashlib.sha256(raw.encode('utf-8')).hexdigest():reasons.append('raw_digest_mismatch')
    if claim.get('extraction_verified') is not True:reasons.append('extraction_unverified')
    if claim.get('conflict'):reasons.append('known_conflict')
    if field in REQUIRED_AMAP and claim.get('source_id')!='amap':reasons.append('amap_api_required')
    if field in ('route_duration','route_fare'):
        if (claim.get('context') or {}).get('coord_system')!='GCJ02':reasons.append('unverified_coordinate_system')
        value=claim.get('value')
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0:
            reasons.append('invalid_numeric_value')
        if field=='route_duration' and claim.get('unit')!='minutes':reasons.append('invalid_unit')
        if field=='route_fare' and claim.get('unit')!='CNY':reasons.append('invalid_unit')
    freshness=fresh_state(claim,field,now=now,context=context)
    reasons.extend(freshness['reasons'])
    return {'usable':not reasons,'reasons':list(dict.fromkeys(reasons)),
            'freshness':freshness,'authority':source.get('authority','unknown'),
            'independence_group':source.get('field_independence_groups',{}).get(field,source.get('independence_group')),
            'not_accuracy_probability':True}

def reconcile(claims,field,registry,*,now=None,context=None,entity_id=None):
    checked=[];eligible=[]
    for c in claims:
        gate=check_claim(c,field,registry,now=now,context=context)
        if entity_id is not None and c.get('entity_id')!=entity_id:
            gate['usable']=False;gate['reasons'].append('wrong_entity')
        checked.append({'claim_id':c.get('claim_id'),'source_id':c.get('source_id'),
                        'source_url':c.get('source_url'),'value':c.get('value'),'unit':c.get('unit'),
                        'observed_at':c.get('observed_at'),'source_updated_at':c.get('source_updated_at'),
                        'retrieved_at':c.get('retrieved_at'),**gate})
        if gate['usable']:eligible.append((c,gate))
    # Preserve history, but an older same-source observation cannot vote against
    # its newer observation. Equal-clock disagreements remain visible conflicts.
    latest={}
    for c,g in eligible:
        key=(c.get('source_id'),c.get('entity_id'),canonical(c.get('context',{})))
        stamp=parse_time(c.get('observed_at') or c.get('source_updated_at'))
        latest[key]=max(latest.get(key,stamp),stamp)
    eligible=[(c,g) for c,g in eligible if parse_time(c.get('observed_at') or c.get('source_updated_at'))==
              latest[(c.get('source_id'),c.get('entity_id'),canonical(c.get('context',{})))]]
    # Without an explicit requested identity, never fuse different entities.
    identity_conflict=len({c.get('entity_id') for c,_ in eligible})>1
    values={canonical(c.get('value')) for c,_ in eligible}
    # Conservative exact equality for facts. Retain differing estimates as conflict.
    conflict=identity_conflict or len(values)>1
    groups={g['independence_group'] for _,g in eligible if g['independence_group']}
    primary=any(g['authority'] in ('primary_operator','official_api','official_agency') for _,g in eligible)
    if conflict:status='conflict'
    elif not eligible:status='unverified'
    elif field in REQUIRED_AMAP or field.startswith('weather_'):status='source_estimate' if primary else 'unverified'
    elif primary and len(groups)>=2:status='corroborated'
    else:status='single_source'
    ask=status in ('conflict','unverified','single_source')
    return {'status':status,'value':eligible[0][0].get('value') if eligible and not conflict else None,
            'independent_source_groups':sorted(groups),'needs_user_confirmation':ask,
            'usable_as_hard_fact':status=='corroborated',
            'usable_as_labelled_estimate':status=='source_estimate',
            'checks':checked,'accuracy':None,
            'question':('该信息仍未核实或来源有冲突。可选择暂按明确标注的估计继续、换候选，或补充可核验资料；确认不会把事实改为已核实。' if ask else None)}

def retrieval_task(entity,field,*,reasons,context=None,tags=None):
    context=context or {};tags=tags or []
    terms={'identity':'官网 地址 分店','opening_hours':'官方 营业时间 预约','closure':'临时闭馆 停运 官方公告',
           'price':'官方 门票价格 票种','inventory':'官方 预约 余票 房态','dynamic_price':'当日 报价 票价 房型 人数',
           'intercity_schedule':'官方 车次 航班 日期 时刻','weather_now':'实时天气 观测 发布时间',
           'weather_forecast':'天气预报 发布时刻','weather_alert':'气象预警 官方',
           'accessibility':'无障碍 电梯 通道 运营 状态','route_duration':'地铁 运营调整 接驳',
           'experience':'游览 交通 体验'}.get(field,field)
    labels={'walking_intensity':'步行强度','queue_report':'排队 高峰','nature':'自然风光',
            'walk_minutes':'交通 接驳 步行','history':'历史文化','photography':'摄影','stairs':'台阶 无障碍'}
    tag_terms=' '.join(dict.fromkeys(labels.get(t.get('aspect',t.get('tag','')),t.get('aspect',''))
                                   for t in tags if t.get('aspect',t.get('tag','')) in labels))
    local=' '.join(str(entity.get(k,'')) for k in ('city','name','origin_city','destination_city')).strip()
    if not local:local=str(context.get('adcode') or entity.get('entity_id') or '')
    date=str(context.get('travel_date') or '')
    queries=list(dict.fromkeys([' '.join(v for v in (local,terms,date) if v),
        ' '.join(v for v in (str(entity.get('city','')),tag_terms,terms,date) if v)]))
    return {'task_id':sha([entity,field,context])[:20],'entity':entity,'field':field,
            'context':context,'tags':tags,'reasons':reasons,
            'search_queries':queries,'expand_if_no_trusted_hit':'broaden from exact name to city/category TAGs; retain uncertainty',
            'depth':'deep_multi_source','required_provider':'amap' if field in REQUIRED_AMAP else None,
            'source_order':(['amap','metro_operator_notice'] if field in REQUIRED_AMAP else
                            ['weather_provider','official_weather_agency'] if field.startswith('weather_') else
                            ['primary_operator','independent_structured_provider','recent_licensed_review']),
            'min_independent_sources':2,'max_sources':3,'max_candidates':8,
            'stop_when':'fresh applicable evidence; or budget/auth/rate limit reached',
            'fallback':'mark unverified and batch questions for affected user decisions; never invent facts'}

def uncertainty_question(entity,field,verdict):
    if not verdict.get('needs_user_confirmation'):return None
    return {'entity':entity,'field':field,'status':verdict['status'],'checks':verdict['checks'],
            'prompt':'该字段未能核实或来源冲突，会影响本次选择。请决定按明确标注的估计继续、换候选，或补充资料。',
            'choices':['accept_labelled_uncertainty','replace_candidate','provide_evidence'],
            'confirmation_changes_factual_status':False}

def user_decision(question,choice,*,note='',at=None):
    if choice not in question['choices']:raise ValueError('invalid decision')
    return {'recorded_at':at or utcnow(),'question':question,'choice':choice,'note':note,
            'evidence_status_after':question['status'],'hard_constraints_certified':False}
