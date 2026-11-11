"""Entity-scoped business facts; structured hours preserve gaps and midnight."""
import hashlib,math,re
from functools import lru_cache
from opencc import OpenCC
from datetime import date
from bs4 import BeautifulSoup
from .business_archives import name_aliases,parse_hours
from .dynamic.opendata import gcj02_to_wgs84
from .freshness import parse_time

# Agent-reviewed name variants for this frozen batch, never an identity certificate.
REVIEWED_VARIANTS={
 ('青岛','老船夫1927'):'老船夫1927(东海东路店)',
 ('南宁','粉之都 七星店'):'粉之都(076七星店)',
 ('宁波','味蔵'):'味藏日本料理店',
 ('宁波','走马楼'):'走马楼饭庄',
 ('哈尔滨','波特曼餐廳'):'波特曼西餐厅(道里店)',
 ('大连','麺道場'):'面道场(日本一条街店)',
 ('太原','山西會馆'):'山西会馆·晋菜·晋商宴·牌匾博物馆(胜利东街店)',
 ('乌鲁木齐','穆沙烧烤 Musa BBQ'):'穆沙烧烤·新疆烧烤(友好店)',
 ('福州','依强牛肉店'):'老牌依强牛肉店(达道店)',
 ('西安','方中山胡辣汤'):'方中山胡辣汤(西安一店)',
}

_T2S=OpenCC('t2s')
@lru_cache(maxsize=10000)
def matching_aliases(name):
    """Orthographic normalization only; no translation or dropped branch names."""
    aliases=name_aliases(name)|name_aliases(_T2S.convert(name or ''))
    bilingual=re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'\-]+\s+([\u4e00-\u9fff].*)",name or '')
    if bilingual:aliases|=name_aliases(bilingual[1])|name_aliases(_T2S.convert(bilingual[1]))
    return aliases

def provider_aliases(poi):
    aliases=matching_aliases(poi.get('name',''))
    extra=(poi.get('business') or {}).get('alias')
    if isinstance(extra,str):
        for item in re.split(r'[,，;；|]',extra):aliases=aliases|matching_aliases(item.strip())
    return aliases

def today_hours(text):
    """Only a provider's explicit today field; no weekday/season extrapolation."""
    raw=(text or '').strip();segments=[];issues=[]
    if raw in ('24小时营业','24小时开放','全天开放','全天营业'):
        segments=[{'start_minute':0,'end_minute':1440,'end_day_offset':0}]
    else:
        pattern=r'(\d{1,2}):([0-5]\d)\s*[-—~至]{1,2}\s*(\d{1,2}):([0-5]\d)'
        matched=list(re.finditer(pattern,raw))
        remainder=re.sub(pattern,'',raw)
        if not matched or remainder.strip(' ,，;；、\t\n'):
            return {'raw':raw,'segments':[],'native_values':{},'issues':['unsupported_qualified_hours_rule'],'scope':'provider_today_only'}
        for m in matched:
            h1,m1,h2,m2=map(int,m.groups());start=h1*60+m1;end=h2*60+m2
            if h1>=24 or h2>24 or h2==24 and m2 or start==end:
                return {'raw':raw,'segments':[],'native_values':{},'issues':['invalid_or_ambiguous_clock_pair'],'scope':'provider_today_only'}
            offset=int(end<start)
            seg={'start_minute':start,'end_minute':end,'end_day_offset':offset}
            if seg not in segments:segments.append(seg)
    native={}
    if len(segments)==1:
        s=segments[0]
        if not s['end_day_offset'] and 0<=s['start_minute']<s['end_minute']<1440:
            a=s['start_minute'];b=s['end_minute']
            native={'opentime':f'{a//60:02}:{a%60:02}','endtime':f'{b//60:02}:{b%60:02}'}
        else:issues.append('full_day_or_midnight_not_representable_as_native_pair')
    else:issues.append('split_hours_not_a_continuous_window')
    return {'raw':raw,'segments':segments,'native_values':native,'issues':issues,'scope':'provider_today_only'}

def match_target(target,pois):
    candidates=[];rejected=[]
    for p in pois:
        if not p.get('id') or not p.get('name'):
            rejected.append({'reason':'provider_entity_id_or_name_missing'});continue
        if not p.get('location'):continue
        try:lon,lat=map(float,p['location'].split(','));lon,lat=gcj02_to_wgs84(lon,lat)
        except (TypeError,ValueError):continue
        d=111195*math.hypot(lat-target['latitude_wgs84'],(lon-target['longitude_wgs84'])*math.cos(math.radians(lat)))
        exact=bool(matching_aliases(target['name'])&provider_aliases(p))
        reviewed=REVIEWED_VARIANTS.get((target['city'],target['name']))==p['name']
        city=p.get('cityname','').removesuffix('市')==target['city']
        restaurant=p.get('type','').startswith('餐饮服务;')
        accepted=city and restaurant and ((exact and d<=150) or (reviewed and d<=50))
        item={'poi_id':p['id'],'name':p['name'],'distance_metres':round(d,3),'same_city':city,
              'restaurant_type':restaurant,'exact_alias':exact,'reviewed_variant':reviewed,'accepted_candidate':accepted}
        if accepted:candidates.append((p,item))
        elif exact or reviewed or d<=150:rejected.append(item)
    if len(candidates)==1:
        p,meta=candidates[0]
        return {'matched':True,'poi':p,'binding':meta,'entity_verified':False,
           'method':'name_variant_and_near_coordinates_candidate_binding','rejected':rejected}
    return {'matched':False,'reason':'ambiguous' if candidates else 'no_safe_entity_match',
         'candidate_count':len(candidates),'rejected':rejected,'entity_verified':False}

def qunar_fields(html):
    """Labeled venue fields only. User reviews and ticket 'from' prices stay separate."""
    soup=BeautifulSoup(html,'html.parser');title=soup.title.get_text(' ',strip=True) if soup.title else ''
    m=re.match(r'\d{4}(.+?)门票,',title);name=m[1] if m else None
    address=soup.select_one('.address');rules={}
    for item in soup.select('li.list'):
        label=item.select_one('.item_tit');value=item.select_one('.item_cout')
        if label and value:
            key=label.get_text(' ',strip=True).rstrip('：:')
            if key in ('开放时间','门票','建议游览时间','建议游玩时间'):
                rules[key]=value.get_text(' ',strip=True)
    ticket=soup.select_one('.ticket-price');options=[]
    if ticket:
        text=ticket.get_text(' ',strip=True);m=re.search(r'[¥￥]\s*(\d+(?:\.\d+)?)',text)
        if m:options.append({'amount':float(m[1]),'currency':'CNY','lower_bound':True,
             'scope':'unidentified_ticket_product_from_price_not_adult_admission','quote':text})
    native={};issues=[]
    if rules.get('开放时间'):
        native,issues=parse_hours(rules['开放时间'])
        if native and native['endtime']<=native['opentime']:
            native={};issues+=['overnight_rule_requires_day_offset']
    return {'name':name,'address':address.get_text(' ',strip=True) if address else None,
       'labeled_rules':rules,'native_values':native,'ticket_options':options,
       'issues':issues,'fact_updated_at':None,'page_title_is_not_fact_timestamp':True}

def validate_hours(item,*,require_provenance=False):
    errors=[]
    if not isinstance(item,dict):return {'ok':False,'errors':['not_object']}
    if not isinstance(item.get('raw'),str):errors.append('raw_text_required')
    if item.get('scope')!='provider_today_only':errors.append('scope_required')
    if require_provenance:
        for key in ('schema_version','entity_id','source_id','source_url','evidence_id','raw_rule_sha256',
             'observed_at','source_updated_at','retrieved_at','policy_id','ttl_seconds','valid_until','provider_request_date'):
            if key not in item:errors.append('missing_metadata:'+key)
        if item.get('schema_version')!='business-hours-v1':errors.append('hours_schema_version')
        for key in ('entity_id','source_id','source_url','evidence_id','provider_request_date'):
            if not isinstance(item.get(key),str) or not item[key]:errors.append('invalid_metadata:'+key)
        if not parse_time(item.get('retrieved_at')):errors.append('retrieved_clock')
        for key in ('observed_at','source_updated_at','valid_until'):
            if item.get(key) is not None and not parse_time(item[key]):errors.append('invalid_clock:'+key)
        if item.get('policy_id')!='opening_hours' or item.get('ttl_seconds')!=86400:errors.append('hours_policy')
        if item.get('raw_rule_sha256')!=hashlib.sha256(item.get('raw','').encode()).hexdigest():errors.append('raw_rule_digest')
        try:date.fromisoformat(item.get('provider_request_date',''))
        except (ValueError,TypeError):errors.append('provider_date')
    if not isinstance(item.get('native_values'),dict):errors.append('native_values_required')
    if isinstance(item.get('raw'),str):
        expected=today_hours(item['raw'])
        if item.get('segments')!=expected['segments']:errors.append('segments_do_not_match_raw_rule')
        if item.get('native_values')!=expected['native_values']:errors.append('native_window_does_not_match_raw_rule')
    if not isinstance(item.get('segments'),list):errors.append('segments_required')
    else:
        for seg in item['segments']:
            if not isinstance(seg,dict):errors.append('invalid_segment');continue
            a=seg.get('start_minute');b=seg.get('end_minute');offset=seg.get('end_day_offset')
            if type(a) is not int or not 0<=a<1440:errors.append('invalid_start')
            if type(b) is not int or not 0<=b<=1440:errors.append('invalid_end')
            if type(offset) is not int or offset not in (0,1):errors.append('invalid_offset')
            if type(a) is int and type(b) is int and type(offset) is int and b+offset*1440<=a:errors.append('invalid_order')
    return {'ok':not errors,'errors':errors}
