"""Date-aware chronology for native plans, preserving uncertain date evidence.

Day numbers are 1-based departure/starting calendar days. An intercity leg with
end clock before its start has a next-day lower bound, not an assumed exact
arrival day. ``end_day`` / ``arrival_day`` or dates can make the day explicit.
The native schema permits extension fields but still enforces HH:MM time format.
"""
from __future__ import annotations
from datetime import date, timedelta
import re

def parse_amap_rail_clock(value, departure_day):
    """Losslessly convert provider's extended-hour clock to native HH:MM + day.

    Supports ``HH:MM`` and four-or-more-digit ``HHMM``. Does not infer date,
    departure, timetable validity or availability from the returned clock.
    """
    if not isinstance(departure_day,int) or isinstance(departure_day,bool) or departure_day<1:
        raise ValueError('departure day must be a positive integer')
    if not isinstance(value,str):raise ValueError('source clock must be a string')
    m=re.fullmatch(r'(\d{2,3}):?(\d{2})',value.strip())
    if not m:raise ValueError('unsupported source clock')
    hour,minute=map(int,m.groups())
    if minute>59:raise ValueError('invalid source minute')
    return {'clock':f'{hour%24:02d}:{minute:02d}','arrival_day':departure_day+hour//24,
            'source_clock':value,'day_offset':hour//24}

def _minutes(value, *, start=False):
    if not isinstance(value,str):return None
    m=re.fullmatch(r'(\d{2}):(\d{2})',value)
    if not m:return None
    h,minute=map(int,m.groups())
    if minute>59 or h>24 or (h==24 and (minute or start)):return None
    return h*60+minute

def _date(value):
    if not isinstance(value,str):return None
    try:return date.fromisoformat(value)
    except ValueError:return None

def validate_timeline(query,plan,duration_resolver=None):
    issues=[]
    def issue(state,code,day=None,index=None,detail=None):
        item={'state':state,'code':code}
        if day is not None:item['day']=day
        if index is not None:item['activity_index']=index
        if detail is not None:item['detail']=detail
        issues.append(item)
    days=query.get('days')
    if not isinstance(days,int) or isinstance(days,bool) or days<1:
        days=None
        issue('unknown','requested_days_missing')
    if not isinstance(plan,dict) or not isinstance(plan.get('itinerary'),list) or not plan['itinerary']:
        return {'state':'unknown','issues':[{'state':'unknown','code':'itinerary_missing'}]}
    itinerary=plan['itinerary']; numbers=[]
    for bucket in itinerary:
        n=bucket.get('day') if isinstance(bucket,dict) else None
        if not isinstance(n,int) or isinstance(n,bool) or n<1:
            issue('unknown','invalid_day_index');continue
        numbers.append(n)
    if len(numbers)==len(itinerary):
        if numbers!=list(range(1,len(numbers)+1)):
            issue('fail','day_indices_not_contiguous_in_order',detail=numbers)
        if days is not None and len(numbers)>days:
            issue('fail','day_count_mismatch',detail={'expected':days,'actual':len(numbers)})
    start_date=_date(query.get('start_date'))
    prior_end=None;prior_uncertain=False
    known_reached_day=max(numbers,default=0)
    uncertain_reached_day=0
    for bucket in itinerary:
        if not isinstance(bucket,dict) or not isinstance(bucket.get('day'),int):continue
        day=bucket['day']; acts=bucket.get('activities')
        if not isinstance(acts,list):issue('unknown','activities_missing',day);continue
        bucket_date=_date(bucket.get('date'))
        if bucket.get('date') is not None and bucket_date is None:issue('unknown','invalid_bucket_date',day)
        expected_date=start_date+timedelta(days=day-1) if start_date else None
        if bucket_date and expected_date and bucket_date!=expected_date:
            issue('fail','bucket_date_mismatch',day)
        reference_date=bucket_date or expected_date
        for index,activity in enumerate(acts,1):
            if not isinstance(activity,dict):issue('unknown','invalid_activity',day,index);continue
            start=_minutes(activity.get('start_time'),start=True);end=_minutes(activity.get('end_time'))
            if start is None or end is None:
                issue('unknown','invalid_activity_time',day,index);prior_end=None;prior_uncertain=True;continue
            absolute_start=(day-1)*1440+start
            kind=activity.get('type'); intercity=kind in ('train','airplane')
            declared=activity.get('end_day',activity.get('arrival_day'))
            if declared is not None and (not isinstance(declared,int) or isinstance(declared,bool) or declared<day):
                issue('fail','invalid_end_day',day,index);declared=None
            end_date=_date(activity.get('end_date') or activity.get('arrival_date'))
            if (activity.get('end_date') or activity.get('arrival_date')) and not end_date:
                issue('unknown','invalid_end_date',day,index)
            if end_date and reference_date:
                from_date=day+(end_date-reference_date).days
                if declared is not None and from_date!=declared:issue('fail','end_day_date_conflict',day,index)
                declared=from_date
            elif end_date and not reference_date:issue('unknown','end_date_without_start_date',day,index)
            duration=None
            if duration_resolver is not None and intercity:
                try:duration=duration_resolver(query,activity)
                except Exception:issue('unknown','duration_evidence_unavailable',day,index)
            if duration is not None:
                elapsed=duration.get('minutes')
                if not isinstance(elapsed,(int,float)) or isinstance(elapsed,bool) or elapsed<=0:
                    duration=None
                else:
                    # Compare the rounded duration to the recorded end clock
                    # and derive the integer day offset. This also handles
                    # trips over 24 hours whose end clock appears later.
                    delta = start + elapsed - end
                    offset = round(delta / 1440)
                    if offset < 0 or abs(delta - offset * 1440) > 1:
                        issue('unknown', 'source_duration_clock_conflict', day, index)
                        duration = None
                    else:
                        observed_day = day + offset
                        if declared is not None and declared != observed_day:
                            issue('fail', 'arrival_day_conflicts_with_source_duration', day, index,
                                  {'declared': declared, 'source_day': observed_day})
                        declared = observed_day
            if intercity and duration is None:
                issue('unknown', 'intercity_duration_evidence_missing', day, index)
            if declared is not None:
                absolute_end=(declared-1)*1440+end
                uncertain=False
            elif end<start and kind=='accommodation':
                # A nightly lodging activity that ends before its check-in
                # clock naturally checks out on the following calendar day.
                absolute_end=day*1440+end
                uncertain=False
            elif end<start and intercity:
                absolute_end=day*1440+end
                uncertain=True
            elif end>=start and intercity:
                # Clock order alone cannot distinguish a one-hour trip from
                # a 25-hour trip. No day/date or matching duration => unknown.
                absolute_end=(day-1)*1440+end
                uncertain=True
            else:
                absolute_end=(day-1)*1440+end
                uncertain=False
            if absolute_end<=absolute_start:
                if end==start and intercity and declared is None:
                    issue('unknown','intercity_equal_clock_duration_ambiguous',day,index)
                    prior_end=None;prior_uncertain=True;continue
                issue('fail','activity_nonpositive_duration',day,index)
            # Compare both known time and minimum possible arrival time. If the
            # latter already exceeds the start the overlap is definite.
            if prior_end is not None and absolute_start<prior_end:
                issue('fail','activity_overlaps_previous',day,index,
                      {'starts_at_minute':absolute_start,'previous_ends_at_minute':prior_end})
            elif prior_uncertain and prior_end is not None:
                issue('unknown','previous_arrival_day_not_explicit',day,index)
            # Transport legs attach to this activity and precede it.
            legs=activity.get('transports',[])
            if not isinstance(legs,list):issue('unknown','transport_list_missing',day,index);legs=[]
            leg_end=None
            for leg_no,leg in enumerate(legs,1):
                if not isinstance(leg,dict):issue('unknown','invalid_transport',day,index,leg_no);continue
                a=_minutes(leg.get('start_time'),start=True);b=_minutes(leg.get('end_time'))
                leg_start_day=leg.get('start_day',day);leg_end_day=leg.get('end_day',day)
                if (a is None or b is None or not isinstance(leg_start_day,int) or not isinstance(leg_end_day,int)
                    or leg_start_day<1 or leg_end_day<1):
                    issue('unknown','invalid_transport_time_or_day',day,index,leg_no);continue
                ls=(leg_start_day-1)*1440+a;le=(leg_end_day-1)*1440+b
                if le<ls:
                    if 'end_day' not in leg and b<a:
                        issue('unknown','transport_cross_day_without_marker',day,index,leg_no);continue
                    issue('fail','transport_negative_duration',day,index,leg_no)
                if prior_end is not None and ls<prior_end:
                    issue('fail','transport_overlaps_previous',day,index,
                          {'leg':leg_no,'departs_at_minute':ls,'previous_ends_at_minute':prior_end})
                elif prior_uncertain and prior_end is not None:issue('unknown','transport_after_uncertain_arrival',day,index,leg_no)
                if leg_end is not None and ls<leg_end:issue('fail','transport_legs_overlap',day,index,leg_no)
                if le>absolute_start:issue('fail','transport_ends_after_activity_starts',day,index,leg_no)
                leg_end=le
            if absolute_end>absolute_start:
                reached=int((absolute_end-0.000001)//1440)+1
                if uncertain:uncertain_reached_day=max(uncertain_reached_day,reached)
                else:known_reached_day=max(known_reached_day,reached)
            if days is not None and absolute_end>days*1440:
                issue('fail','activity_exceeds_trip_days',day,index,{'requested_days':days,'ends_on_day':int((absolute_end-1e-6)//1440)+1})
            elif days is None and absolute_end>len(itinerary)*1440:
                issue('unknown','activity_exceeds_known_day_buckets',day,index)
            if uncertain:issue('unknown','intercity_arrival_day_not_explicit',day,index)
            prior_end=absolute_end;prior_uncertain=uncertain
    # A final day represented solely by arrival from an overnight service need
    # not have an empty departure-day bucket. Do not count an uncertain arrival
    # as established coverage.
    if days is not None and len(numbers)<days and known_reached_day<days:
        issue('unknown' if uncertain_reached_day>=days else 'fail','day_count_mismatch',
              detail={'expected':days,'actual':len(numbers),'known_reached_day':known_reached_day})
    states={x['state'] for x in issues}
    return {'state':'fail' if 'fail' in states else 'unknown' if 'unknown' in states else 'pass',
            'issues':issues,'policy':'day is departure day; earlier intercity end clock has at least one-day rollover unless explicit end day/date determines it'}
