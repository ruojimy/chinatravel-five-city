"""Independent meal applicability and absolute-date audit shared by A/B/C."""
import math

WINDOWS={'breakfast':(360,540,30),'lunch':(660,840,60),'dinner':(1020,1200,60)}
INTERCITY={'train','airplane'}
ATTRACTION_START=480
ATTRACTION_END=1260

def clock(value):
    h,m=map(int,str(value).split(':'))
    if h<0 or not 0<=m<60:
        raise ValueError('Invalid clock')
    return 60*h+m

def hhmm(minutes):
    return f'{minutes//60:02d}:{minutes%60:02d}'

def attraction_slot(arrived,opens,closes,duration):
    start=max(clock(arrived),clock(opens),ATTRACTION_START)
    end=min(start+duration,clock(closes),ATTRACTION_END)
    return (hhmm(start),hhmm(end)) if end>start else None

def ticket_interval(activity,day):
    start=(day-1)*1440+clock(activity['start_time'])
    endclock=clock(activity['end_time'])
    source='same_day'
    end=None
    discrepancy=None
    for key in ('end_day_offset','arrival_day_offset','EndDayOffset'):
        value=activity.get(key)
        if value is not None and isinstance(value,(int,float)) and math.isfinite(value):
            end=(day-1+int(value))*1440+endclock
            source=key
            break
    if end is None and activity.get('duration_minutes') is not None:
        end=start+float(activity['duration_minutes'])
        source='duration_minutes'
        if int(end)%1440!=endclock%1440:
            raise ValueError('Duration and arrival clock disagree')
    hours=activity.get('duration_hours')
    if end is None and hours is None and (activity.get('TrainID') or activity.get('FlightID')):
        from catalog import lookup
        hours=lookup(activity)
        source='sandbox_Duration'
    if end is None and hours is not None:
        duration=float(hours)*60
        if not math.isfinite(duration) or duration<=0:
            raise ValueError('Invalid known duration')
        offset=round((clock(activity['start_time'])+duration-endclock)/1440)
        end=(day-1+offset)*1440+endclock
        discrepancy=abs(end-start-duration)
        # This benchmark's synthetic Duration is approximate. It selects the
        # calendar rollover; raw departure/arrival clocks remain authoritative.
        if discrepancy>60:
            raise ValueError('Ambiguous date: Duration and arrival clock disagree by over60minutes')
        if source!='sandbox_Duration':source='duration_hours'
    if end is None:
        if endclock==clock(activity['start_time']):
            raise ValueError('Equal clocks without reliable date or duration')
        end=(day-1)*1440+endclock
        if end<start:
            end+=1440
            source='inferred_next_day'
    if end<=start:
        raise ValueError('Non-positive intercity interval')
    return dict(start=start,end=end,start_day=int(start)//1440+1,end_day=int(end)//1440+1,date_source=source,duration_clock_discrepancy_minutes=discrepancy)

def timeline(plan):
    rows=[]
    for day in plan.get('itinerary',[]):
        for index,a in enumerate(day.get('activities',[])):
            if a['type'] in INTERCITY:
                row=ticket_interval(a,day['day'])
            else:
                start=(day['day']-1)*1440+clock(a['start_time'])
                end=(day['day']-1)*1440+clock(a['end_time'])
                if end<start:
                    end+=1440
                row=dict(start=start,end=end,start_day=int(start)//1440+1,end_day=int(end)//1440+1,date_source='itinerary_day')
            rows.append(dict(row,kind=a['type'],day=day['day'],index=index,activity=a))
    return rows

def subtract(interval,blocked):
    pieces=[interval]
    for b,e in sorted(blocked):
        new=[]
        for x,y in pieces:
            if e<=x or b>=y:
                new.append((x,y))
            else:
                if x<b:new.append((x,b))
                if e<y:new.append((e,y))
        pieces=new
    return pieces

def meal_obligations(plan):
    rows=timeline(plan)
    traffic=[r for r in rows if r['kind'] in INTERCITY]
    if len(traffic)<2:
        raise ValueError('Outbound and return required')
    begin,end=traffic[0]['start'],traffic[-1]['end']
    blocked=[(r['start'],r['end']) for r in traffic]
    obligations=[]
    for day in range(int(begin)//1440+1,int(end)//1440+2):
        base=(day-1)*1440
        for kind,(lo,hi,duration) in WINDOWS.items():
            x,y=max(begin,base+lo),min(end,base+hi)
            pieces=subtract((x,y),blocked) if y>x else []
            if y<=x:status='outside_journey'
            elif y-x<duration:status='boundary_not_applicable'
            elif not any(e-b>=duration for b,e in pieces):status='traffic_exempt'
            else:status='required'
            obligations.append(dict(day=day,kind=kind,status=status,window=[base+lo,base+hi],available=[list(p) for p in pieces],free_intervals=[list(p) for p in subtract((begin,end),blocked)],duration=duration))
    return obligations

def meal_fits(obligation,start,end):
    lo,hi=obligation['window']
    return lo<=start<hi and end-start>=obligation['duration'] and any(b<=start and end<=e for b,e in obligation['free_intervals'])

def future_meal_possible(obligation,now):
    lo,hi=obligation['window']
    return any(max(b,lo,now)<=min(hi-1,e-obligation['duration']) for b,e in obligation['free_intervals'])

def access_timeline(rows):
    intervals=[]
    valid=True
    for index,row in enumerate(rows):
        cursor=row['start']
        access=[]
        for legindex,leg in reversed(list(enumerate(row['activity'].get('transports',[])))):
            end=(int(cursor)//1440)*1440+clock(leg['end_time'])
            if end>cursor:end-=1440
            start=(int(end)//1440)*1440+clock(leg['start_time'])
            if start>end:start-=1440
            access.append(dict(day=row['day'],activity_index=row['index'],leg_index=legindex,start=start,end=end,start_day=int(start)//1440+1,end_day=int(end)//1440+1,date_source='backward_from_activity'))
            cursor=start
        access.reverse()
        if access and index and access[0]['start']<rows[index-1]['end']:
            valid=False
        intervals.extend(access)
    return intervals,valid

def audit(plan,requested_days):
    violations=[]
    try:
        rows=timeline(plan)
        traffic=[r for r in rows if r['kind'] in INTERCITY]
        if len(traffic)!=2:
            raise ValueError('Exactly two intercity tickets expected')
        begin,end=traffic[0]['start'],traffic[-1]['end']
        if end<=begin:raise ValueError('Journey order invalid')
        date_pass=all(r['start']>=rows[i-1]['end'] for i,r in enumerate(rows) if i)
        date_pass=date_pass and all(r['end']>r['start'] for r in rows)
        access,access_pass=access_timeline(rows)
        date_pass=date_pass and access_pass
        day_limit_pass=int(end-1)//1440+1<=requested_days
        obligations=meal_obligations(plan)
        meals=[r for r in rows if r['kind'] in WINDOWS]
        for r in meals:
            lo,hi,duration=WINDOWS[r['kind']]
            offset=(r['day']-1)*1440
            if not (offset+lo<=r['start']<offset+hi and r['end']-r['start']>=duration and begin<=r['start'] and r['end']<=end):
                violations.append(dict(rule='invalid_meal_time',day=r['day'],kind=r['kind']))
            if any(r['start']<t['end'] and r['end']>t['start'] for t in traffic):
                violations.append(dict(rule='meal_overlaps_intercity',day=r['day'],kind=r['kind']))
        for o in obligations:
            present=[r for r in meals if r['day']==o['day'] and r['kind']==o['kind']]
            if len(present)>1:
                violations.append(dict(rule='duplicate_meal',day=o['day'],kind=o['kind']))
            if o['status']=='required' and not present:
                violations.append(dict(rule='missing_meal',day=o['day'],kind=o['kind']))
        meal_pass=not violations
        attraction_violations=[]
        for r in rows:
            if r['kind']=='attraction':
                offset=(r['day']-1)*1440
                if not (offset+ATTRACTION_START<=r['start']<r['end']<=offset+ATTRACTION_END):
                    attraction_violations.append(dict(rule='attraction_outside_daytime',day=r['day'],start=r['start'],end=r['end']))
        violations.extend(attraction_violations)
        return dict(meal_pass=meal_pass,date_pass=date_pass,day_limit_pass=day_limit_pass,attraction_hours_pass=not attraction_violations,
                    all_pass=not violations and date_pass and day_limit_pass,violations=violations,
                    obligations=obligations,timeline=[{k:v for k,v in r.items() if k!='activity'} for r in rows],access_timeline=access)
    except (ValueError,KeyError,TypeError) as exc:
        return dict(meal_pass=False,date_pass=False,day_limit_pass=False,attraction_hours_pass=False,all_pass=False,violations=[dict(rule='invalid_timeline',message=str(exc))],obligations=[],timeline=[])
