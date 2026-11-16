"""Multi-leg local transit validation using the unchanged native route checker.

Each walk/taxi leg and each walk-metro-walk group is verified independently
against the actual sandbox's goto result.  No route or fare is synthesized.
The aggregate verdict stays compatible with the native table-plus-messages API.
Unknown lookup or clock evidence raises LookupError for the three-state scorer.
"""
import math
import pandas as pd

COLUMNS = ['Unavailable Inner-City Transport',
           'Incorrect Information of Inner-City Transporton on price, distance, and duration',
           'Inccorrect cost information of Inner-City Transport']


def _clock(value, day):
    if not isinstance(day, int) or isinstance(day, bool) or day < 1:
        raise LookupError('TRANSPORT_TIME_UNKNOWN: invalid day marker')
    if (not isinstance(value, str) or len(value) != 5 or value[2] != ':'
            or not value[:2].isdigit() or not value[3:].isdigit()):
        raise LookupError('TRANSPORT_TIME_UNKNOWN: invalid clock')
    try:
        h, m = int(value[:2]), int(value[3:])
    except ValueError as exc:
        raise LookupError('TRANSPORT_TIME_UNKNOWN: invalid clock') from exc
    if not (0 <= h <= 24 and 0 <= m <= 59) or (h == 24 and m != 0):
        raise LookupError('TRANSPORT_TIME_UNKNOWN: invalid clock')
    return (day - 1) * 1440 + h * 60 + m


def _segments(legs):
    """Group a native metro route as a unit, all other legs independently."""
    out=[]; i=0
    while i < len(legs):
        if not isinstance(legs[i],dict):
            raise ValueError('route leg is not an object')
        modes=[x.get('mode') if isinstance(x,dict) else None for x in legs[i:i+3]]
        if modes == ['walk','metro','walk']:
            out.append(legs[i:i+3]); i+=3
        elif legs[i].get('mode') in ('walk','taxi'):
            out.append([legs[i]]); i+=1
        else:
            raise ValueError(f'incomplete or unsupported route segment at index {i}')
    return out


def _number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        return None
    return float(value)


def _legacy_segment(segment,activity_day):
    """Express explicit rollover as the sandbox provider's 24+ hour clocks."""
    start_day=segment[0].get('start_day',activity_day)
    midnight=(start_day-1)*1440
    result=[]
    for leg in segment:
        item=dict(leg)
        for name,day_name in (('start_time','start_day'),('end_time','end_day')):
            minute=_clock(leg.get(name),leg.get(day_name,activity_day))-midnight
            if minute<0:raise LookupError('TRANSPORT_TIME_UNKNOWN: segment precedes its start day')
            item[name]=f'{minute//60:02d}:{minute%60:02d}'
        result.append(item)
    return result


def check(symbolic_input, plan_json, legacy_checker, verbose=False):
    table=pd.DataFrame([[0,0,0]],columns=COLUMNS); messages=[]; unknown=[]
    def fail(column,message):
        table.loc[0,column]=1; messages.append(message)
    if not isinstance(plan_json,dict) or not isinstance(plan_json.get('itinerary'),list):
        table.loc[0,:]=1
        return table,['Error plan type, must provide itinerary']
    people=symbolic_input.get('people_number')
    if not isinstance(people,int) or isinstance(people,bool) or people<1:
        people=None
    for day_index,bucket in enumerate(plan_json['itinerary']):
        if not isinstance(bucket,dict) or not isinstance(bucket.get('activities'),list):
            fail(COLUMNS[0],f'day {day_index+1}: invalid activities'); continue
        day=bucket.get('day',day_index+1)
        for activity_index,activity in enumerate(bucket['activities']):
            if not isinstance(activity,dict):
                fail(COLUMNS[0],f'day {day_index+1}: invalid activity'); continue
            legs=activity.get('transports',[])
            if not isinstance(legs,list):
                fail(COLUMNS[0],f'day {day_index+1}: invalid transport list'); continue
            if not legs:continue
            try:
                segments=_segments(legs)
            except ValueError as exc:
                fail(COLUMNS[0],str(exc)); continue
            route_city=(symbolic_input.get('start_city')
                        if day_index==0 and activity_index==0 and activity.get('type') in ('train','airplane')
                        else symbolic_input.get('target_city'))
            leg_intervals=[];unresolved_legs=set()
            for i,leg in enumerate(legs):
                if not isinstance(leg.get('start'),str) or not isinstance(leg.get('end'),str):
                    fail(COLUMNS[0],f'leg {i+1} missing start/end'); continue
                if i and legs[i-1].get('end')!=leg.get('start'):
                    fail(COLUMNS[0],f'legs {i} and {i+1} have different endpoints')
                try:
                    start=_clock(leg.get('start_time'),leg.get('start_day',day))
                    end=_clock(leg.get('end_time'),leg.get('end_day',day))
                    if end<start and 'end_day' not in leg and leg.get('end_time')<leg.get('start_time'):
                        raise LookupError('TRANSPORT_TIME_UNKNOWN: cross-day leg has no end_day')
                    if end<start:
                        fail(COLUMNS[1],f'leg {i+1} ends before it starts')
                    if leg_intervals and leg_intervals[-1][1] is not None and start<leg_intervals[-1][1]:
                        fail(COLUMNS[1],f'legs {i} and {i+1} overlap')
                    leg_intervals.append((start,end))
                except LookupError as exc:
                    unknown.append(str(exc));leg_intervals.append((None,None));unresolved_legs.add(id(leg))
                mode=leg.get('mode')
                for field in ('price','cost','distance'):
                    val=_number(leg.get(field))
                    if val is None or val<0:
                        fail(COLUMNS[1] if field!='cost' else COLUMNS[2],f'leg {i+1} invalid {field}')
                if mode=='metro':
                    tickets=leg.get('tickets')
                    if not isinstance(tickets,int) or isinstance(tickets,bool) or tickets<1:
                        fail(COLUMNS[2],f'leg {i+1} has invalid metro ticket count')
                    elif people is not None and tickets<people:
                        fail(COLUMNS[2],f'leg {i+1} metro tickets do not cover party')
                if mode=='taxi':
                    cars=leg.get('cars')
                    if not isinstance(cars,int) or isinstance(cars,bool) or cars<1:
                        fail(COLUMNS[2],f'leg {i+1} has invalid taxi car count')
            if leg_intervals and leg_intervals[-1][1] is not None and activity.get('start_time') is not None:
                try:
                    if leg_intervals[-1][1]>_clock(activity['start_time'],day):
                        fail(COLUMNS[1],'route ends after activity starts')
                except LookupError as exc:unknown.append(str(exc))
            # The actual legacy checker compares each route segment's endpoint,
            # minute-level timings, distance, unit fare and total against goto.
            context=dict(symbolic_input,start_city=route_city,target_city=route_city)
            for index,segment in enumerate(segments):
                if any(id(leg) in unresolved_legs for leg in segment):continue
                try:
                    synthetic_segment=_legacy_segment(segment,day)
                    synthetic={'itinerary':[{'day':day,'activities':[{'type':activity.get('type'),
                                                                       'transports':synthetic_segment}]}]}
                    sub,notes=legacy_checker(context,synthetic,verbose=False)
                except Exception as exc:
                    unknown.append(f'TRANSPORT_LOOKUP_UNAVAILABLE: segment {index+1}: {type(exc).__name__}: {exc}')
                    continue
                if not isinstance(sub,pd.DataFrame) or len(sub)!=1 or any(c not in sub for c in COLUMNS):
                    unknown.append(f'TRANSPORT_LOOKUP_UNAVAILABLE: invalid checker response for segment {index+1}')
                    continue
                for column in COLUMNS:
                    if bool(sub.loc[0,column]):table.loc[0,column]=1
                messages.extend(f'segment {index+1}: {note}' for note in notes)
    if unknown and not any(int(table.loc[0,c]) for c in COLUMNS):
        raise LookupError('; '.join(unknown))
    messages.extend(unknown)
    if verbose and messages:print(messages)
    return table,messages
