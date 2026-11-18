"""Optional dated official fare overlays for the shared intercity selector."""
from __future__ import annotations
import hashlib,json,math,os,re
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from functools import lru_cache
import pandas as pd

ENDPOINT='https://kyfw.12306.cn/otn/leftTicketPrice/queryAllPublicPrice'
JS_SHA='6d8dba71a501294a15334ca1f222331be7db61cb5d96ef32e64f004ef3af8dee'
STATION_SHA='b23aab2792d1c5646b20aa5117a5088dbe5124453b950ddd4eecdb4b24fc17be'

def _station(s):
    if not isinstance(s,str):return None
    s=s.strip()
    return s[:-1] if s.endswith('站') else s

def _verify(q):
    try:
        if q['official_js_sha256']!=JS_SHA or q['station_dictionary_sha256']!=STATION_SHA:return False
        raw=Path(q['response_path']).read_bytes();rec=json.loads(Path(q['receipt_path']).read_text(encoding='utf8'))
        if hashlib.sha256(raw).hexdigest()!=q['response_sha256'] or rec['response_sha256']!=q['response_sha256']:return False
        if rec.get('endpoint',rec.get('url'))!=ENDPOINT or rec.get('http_status')!=200:return False
        if rec.get('departure_date',rec.get('date'))!=q['query_date']:return False
        if rec.get('observed_at_utc')!=q.get('observed_at_utc'):return False
        if rec.get('from_station',rec.get('from_station_code'))!=q['query_from_code'] or rec.get('to_station',rec.get('to_station_code'))!=q['query_to_code']:return False
        body=json.loads(raw)
        if body.get('status') is not True or body.get('messages'):return False
        row=body['data'][q['row_index']]['queryLeftNewDTO']
        for source,field in [('station_train_code','train_id'),('train_no','train_no'),('from_station_name','from_station'),('to_station_name','to_station'),('from_station_telecode','from_code'),('to_station_telecode','to_code'),('start_time','start_time'),('arrive_time','end_time')]:
            if row.get(source)!=q[field]:return False
        amounts={int(x[1:6]) for x in row.get('infoAll_list','').split('#') if len(x)==10 and x[0]==q['seat_code'] and x[9]=='0' and x[1:6].isdigit() and int(x[1:6])>0}
        return len(amounts)==1 and next(iter(amounts))==q['published_fare_tenths_yuan']
    except (OSError,KeyError,TypeError,ValueError,IndexError):return False

DISPLAY_JS_SHA='3d0e247abad7661828e082f31191aa6c6526ae3a1050dc5dc96ea0923e6e9f47'

@lru_cache(maxsize=8)
def _assets(response_path):
    for parent in Path(response_path).resolve().parents:
        station=parent/'station_dictionary_001/station_name.js'
        if station.is_file():
            raw=station.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=STATION_SHA:return None
            cities={}
            for token in raw.decode('utf8').split('@')[1:]:
                c=token.split('|')
                if len(c)>7 and c[7]:cities.setdefault((c[2],c[1]),set()).add(c[7])
            return parent,cities
    return None

def _verify_new(q,origin,destination):
    if not _verify(q):return False
    try:
        assets=_assets(q['response_path'])
        if not assets:return False
        root,cities=assets
        if cities.get((q['from_code'],q['from_station']))!={origin} or cities.get((q['to_code'],q['to_station']))!={destination}:return False
        raw=json.loads(Path(q['response_path']).read_bytes())
        r=raw['data'][q['row_index']]['queryLeftNewDTO']
        sh,sm=map(int,q['start_time'].split(':'));eh,em=map(int,q['end_time'].split(':'))
        hh,mm=map(int,r['lishi'].split(':'));duration=hh*60+mm;offset=int(r['day_difference'])
        return (0<=sh<24 and 0<=eh<24 and 0<=sm<60 and 0<=em<60 and 0<=mm<60 and duration>0
                and offset>=0 and eh*60+em+offset*1440-(sh*60+sm)==duration
                and duration==q['duration_minutes'] and offset==q['arrival_day_offset'])
    except (KeyError,ValueError,TypeError,IndexError,OSError):return False

def _display_evidence(q, rows, as_of=None):
    # Matching analysis is merely an index. Re-extract price and seat status
    # from the saved official response, checking the receipt and decoder bytes.
    matches=[d for d in rows if d.get('query_departure_date')==q['query_date']
      and d.get('TrainID')==q['train_id'] and d.get('train_no')==q['train_no']
      and d.get('from_station_telecode')==q['from_code'] and d.get('to_station_telecode')==q['to_code']
      and d.get('BeginTime')==q['start_time'] and d.get('EndTime')==q['end_time']
      and d.get('seat_code')==q['seat_code'] and d.get('published_response_sha256')==q['response_sha256']]
    if len(matches)!=1:return None
    d=matches[0]
    try:
        root,_=_assets(q['response_path']);js=(root/'queryLeftTicket_end_js.js').read_bytes()
        if hashlib.sha256(js).hexdigest()!=DISPLAY_JS_SHA or d['official_decoder_sha256']!=DISPLAY_JS_SHA:return None
        source=Path(d['source_response']);raw=source.read_bytes();receipt=json.loads((source.parent/'receipt.json').read_text(encoding='utf8'))
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=d['source_raw_sha256'] or digest!=receipt['response_sha256'] or receipt['http_status']!=200 or receipt.get('status') not in ('ok','structured_result'):return None
        endpoint='https://kyfw.12306.cn/otn/leftTicket/queryZ'
        receipt_url=receipt.get('url')
        if receipt_url is not None:
            if receipt_url!=endpoint:return None
            endpoint_proof='receipt';collector_hash=None
        else:
            collector=(source.parent.parent/'official_12306_probe.py').read_bytes()
            if endpoint.encode() not in collector:return None
            endpoint_proof='collector_source_not_independent_receipt';collector_hash=hashlib.sha256(collector).hexdigest()
        if receipt.get('date',receipt.get('sample_departure_date'))!=q['query_date']:return None
        if receipt.get('from_station_code',receipt.get('origin_station_telecode'))!=q['query_from_code']:return None
        if receipt.get('to_station_code',receipt.get('destination_station_telecode'))!=q['query_to_code']:return None
        observed=receipt.get('observed_at_utc',receipt.get('retrieved_at_utc'))
        if observed!=d['observed_at_utc']:return None
        observed_dt=datetime.fromisoformat(observed.replace('Z','+00:00'))
        if observed_dt.tzinfo is None or (as_of is not None and observed_dt>as_of):return None
        body=json.loads(raw);data=body['data'];names=data['map']
        if body.get('status') is not True or names.get(q['from_code'])!=q['from_station'] or names.get(q['to_code'])!=q['to_station']:return None
        found=[]
        for encoded in data['result']:
            r=encoded.split('|')
            if len(r)>=40 and (r[2],r[3],r[6],r[7],r[8],r[9])==(q['train_no'],q['train_id'],q['from_code'],q['to_code'],q['start_time'],q['end_time']):found.append(r)
        if len(found)!=1:return None
        r=found[0];hh,mm=map(int,r[10].split(':'))
        if hh*60+mm!=q['duration_minutes']:return None
        tokens=r[39]
        if len(tokens)%10:return None
        amounts=set()
        for i in range(0,len(tokens),10):
            t=tokens[i:i+10]
            if len(t)!=10 or not t[1:6].isdigit():return None
            seat='W' if t[6]=='3' else t[0]
            if seat==q['seat_code'] and int(t[1:6])>0:amounts.add(int(t[1:6]))
        if len(amounts)!=1:return None
        amount=next(iter(amounts))
        if amount>q['published_fare_tenths_yuan'] or amount!=round(float(d['display_price_yuan'])*10):return None
        status=r[30 if q['seat_code']=='O' else 29] or '--'
        positive=status=='有' or (status.isdigit() and int(status)>0)
        local=timezone(timedelta(hours=8));departure=datetime.fromisoformat(q['query_date']+'T'+q['start_time']).replace(tzinfo=local)
        at_time_available=positive and r[11]=='Y' and observed_dt<departure
        if observed_dt>=departure:availability='observed_departed'
        elif at_time_available:availability='observed_available'
        elif status in ('无','0'):availability='observed_no_seats'
        elif status=='候补':availability='observed_waitlist'
        else:availability='unknown'
        return {'display_price':amount/10,'display_availability':availability,'seat_status_raw':status,
                'can_web_buy_raw':r[11],'observed_at_utc':observed,'display_response_sha256':digest,
                'display_response_path':str(source),'actual_bookability':'unknown',
                'display_endpoint_evidence':endpoint_proof,'display_collector_sha256':collector_hash}
    except (OSError,KeyError,TypeError,ValueError,IndexError):return None

def _as_of(value=None):
    if value is None:value=os.environ.get('CT_OFFICIAL_FARE_AS_OF_UTC')
    if value is None:return datetime.now(timezone.utc)
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError as exc:raise ValueError('Invalid CT_OFFICIAL_FARE_AS_OF_UTC') from exc
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Fare as-of time requires an explicit UTC offset')
    return value.astimezone(timezone.utc)

def _departed_as_of(frame,travel_date,clock):
    out=frame.copy();local=timezone(timedelta(hours=8))
    for i,row in out.iterrows():
        try:
            time=row.get('BeginTime')
            if not isinstance(time,str) or not re.fullmatch(r'\d{2}:\d{2}',time):continue
            departure=datetime.fromisoformat(travel_date+'T'+time).replace(tzinfo=local)
        except (ValueError,TypeError):continue
        if clock>=departure:
            old=row.get('Cost')
            if old is not None and not pd.isna(old):out.at[i,'CostHistoricalReference']=old
            out.at[i,'Cost']=float('nan')
            out.at[i,'CostEvidenceState']='reference_only_departed_as_of'
            out.at[i,'CostAsOfUTC']=clock.isoformat()
    return out

def _before_clock(q,clock):
    try:
        observed=datetime.fromisoformat(q['observed_at_utc'].replace('Z','+00:00'))
        return observed.tzinfo is not None and observed<=clock
    except (KeyError,ValueError,TypeError,AttributeError):return False

def apply(frame, *, travel_date=None, seat_code=None, sidecar=None, origin_city=None, destination_city=None, add_new=False, display_sidecar=None, as_of=None):
    """Date-scoped candidates only. This function never mutates the input frame."""
    if not travel_date or seat_code not in ('O','1'):return frame
    try:
        if date.fromisoformat(travel_date).isoformat()!=travel_date:return frame
    except (ValueError,TypeError):return frame
    clock=_as_of(as_of)
    path=Path(sidecar or os.environ.get('CT_OFFICIAL_FARE_SIDECAR',''))
    if not path.is_file():return _departed_as_of(frame,travel_date,clock)
    try: quotes=json.loads(path.read_text(encoding='utf8'))
    except (ValueError,OSError):return _departed_as_of(frame,travel_date,clock)
    if not isinstance(quotes,list):return _departed_as_of(frame,travel_date,clock)
    display_path=Path(display_sidecar or os.environ.get('CT_OFFICIAL_DISPLAY_SIDECAR',''))
    displays=[]
    if display_path.is_file():
        try:
            content=json.loads(display_path.read_text(encoding='utf8'))
            displays=content.get('accepted',[]) if isinstance(content,dict) else []
        except (ValueError,OSError):pass
    out=frame.copy().reset_index(drop=True)
    selected=[q for q in quotes if q.get('query_date')==travel_date and q.get('seat_code')==seat_code and _before_clock(q,clock)]
    # Every conflict is isolated in the returned dated view, preserving the base frame.
    seen_ids=set()
    for i,row in out.iterrows():
        ident=row.get('TrainID');seen_ids.add(ident)
        related=[q for q in selected if q.get('train_id')==ident and
          (not origin_city or not destination_city or _verify_new(q,origin_city,destination_city))]
        same_stations=[q for q in related if _station(q.get('from_station'))==_station(row.get('From'))
                       and _station(q.get('to_station'))==_station(row.get('To'))]
        exact=[q for q in same_stations if q.get('start_time')==row.get('BeginTime') and q.get('end_time')==row.get('EndTime')
               and (row.get('train_no') is None or pd.isna(row.get('train_no')) or row.get('train_no')==q.get('train_no'))
               and (row.get('Duration') is None or pd.isna(row.get('Duration')) or abs(float(row.get('Duration'))-q.get('duration_minutes',0)/60)<0.02)]
        if not related:continue
        if len(exact)!=1 or len(same_stations)!=1 or not _verify(exact[0]):
            out.at[i,'CostHistoricalReference']=row.get('Cost');out.at[i,'Cost']=float('nan')
            out.at[i,'CostEvidenceState']='dated_identity_or_schedule_conflict';continue
        q=exact[0];existing=row.get('Cost');published=q['published_fare_tenths_yuan']/10
        display=_display_evidence(q,displays,clock) if displays else None
        if display and display['display_availability'] in ('observed_no_seats','observed_waitlist','observed_departed'):
            if existing is not None and not pd.isna(existing):out.at[i,'CostHistoricalReference']=existing
            _put(out,i,q,displays,clock);continue
        reference=(display['display_price'] if display and display['display_availability']=='observed_available' else published)
        if existing is not None and not pd.isna(existing) and float(existing)!=reference:
            out.at[i,'CostHistoricalReference']=existing;out.at[i,'Cost']=float('nan')
            out.at[i,'CostEvidenceState']='historical_vs_current_observation_conflict' if display else 'historical_vs_published_conflict';continue
        if existing is None or pd.isna(existing):_put(out,i,q,displays,clock)
    if add_new and origin_city and destination_city:
        groups={}
        for q in selected:
            if q.get('train_id') in seen_ids:continue
            if not _verify_new(q,origin_city,destination_city):continue
            groups.setdefault((q['train_id'],q['from_code'],q['to_code']),[]).append(q)
        additions=[]
        for identity,items in groups.items():
            if len(items)!=1:continue
            q=items[0];ident=q['train_id']
            record={'TrainID':ident,'TrainType':'高铁' if ident.startswith(('G','D','C')) else '普速',
              'From':q['from_station'] if q['from_station'].endswith('站') else q['from_station']+'站',
              'To':q['to_station'] if q['to_station'].endswith('站') else q['to_station']+'站',
              'BeginTime':q['start_time'],'EndTime':q['end_time'],'Duration':q['duration_minutes']/60,
              'Cost':float('nan'),'TravelDate':travel_date,'CostEvidenceState':'verified_official_new_candidate',
              'train_no':q['train_no'],'FromTelecode':q['from_code'],'ToTelecode':q['to_code'],
              'ArrivalDayOffset':q['arrival_day_offset']}
            f=pd.DataFrame([record]);_put(f,0,q,displays,clock);additions.append(f)
        if additions:out=pd.concat([out,*additions],ignore_index=True,sort=False)
    return _departed_as_of(out,travel_date,clock)

def _put(out,i,q,displays,clock):
    display=_display_evidence(q,displays,clock) if displays else None
    published=q['published_fare_tenths_yuan']/10
    blocked=bool(display and display['display_availability'] in ('observed_no_seats','observed_waitlist','observed_departed'))
    out.at[i,'Cost']=(float('nan') if blocked else display['display_price'] if display and display['display_availability']=='observed_available' else published)
    out.at[i,'CostSource']='12306_official_display_observed' if display and display['display_availability']=='observed_available' else '12306_official_published_reference'
    if blocked:out.at[i,'CostEvidenceState']='reference_only_'+display['display_availability']
    out.at[i,'CostDate']=q['query_date'];out.at[i,'CostSeatCode']=q['seat_code'];out.at[i,'CostAsOfUTC']=clock.isoformat()
    out.at[i,'CostPublishedReference']=published
    out.at[i,'PublishedEvidenceSHA256']=q['response_sha256'];out.at[i,'PublishedEvidencePath']=q['response_path']
    out.at[i,'CostEvidenceSHA256']=(display['display_response_sha256'] if display and display['display_availability']=='observed_available' else q['response_sha256'])
    out.at[i,'CostEvidencePath']=(display['display_response_path'] if display and display['display_availability']=='observed_available' else q['response_path'])
    out.at[i,'CostAvailability']='unknown';out.at[i,'CostActualPurchasePrice']='unknown'
    if display:
        out.at[i,'DisplayPrice']=display['display_price'];out.at[i,'DisplayAvailabilityAtObservation']=display['display_availability']
        out.at[i,'DisplayObservedAtUTC']=display['observed_at_utc'];out.at[i,'DisplaySeatStatusRaw']=display['seat_status_raw']
        out.at[i,'DisplayEvidenceSHA256']=display['display_response_sha256'];out.at[i,'DisplayEvidencePath']=display['display_response_path']
        out.at[i,'DisplayEndpointEvidence']=display['display_endpoint_evidence'];out.at[i,'DisplayCollectorSHA256']=display['display_collector_sha256']
