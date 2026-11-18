"""Historical same-day multi-interval opening rules for the sandbox."""
import json

def _mins(s):
    h,m=map(int,str(s).split(':'))
    if h<0 or h>24 or m<0 or m>59 or (h==24 and m):raise ValueError('invalid time')
    return h*60+m
def _clock(n):return f'{n//60:02d}:{n%60:02d}'
def segments(row):
    value=row.get('opening_segments_json')
    if not isinstance(value,str) or not value.strip():return None
    parsed=json.loads(value)
    if not isinstance(parsed,list) or not parsed:raise ValueError('invalid segments')
    result=[]
    for a,b in parsed:
        a,b=int(a),int(b)
        if not 0<=a<b<=1440:raise ValueError('invalid segment')
        result.append((a,b))
    result.sort()
    if any(x[1]>y[0] for x,y in zip(result,result[1:])):raise ValueError('overlapping segments')
    return result
def contains_point(row,when):
    windows=segments(row)
    if windows is None:return None
    n=_mins(when)
    return any(a<=n<b for a,b in windows)
def contains_visit(frame,start,end):
    windows=segments(frame.iloc[0])
    if windows is None:return None
    a,b=_mins(start),_mins(end)
    return b>a and any(x<=a and b<=y for x,y in windows)
def all_windows(row):
    found=segments(row)
    if found is not None:return found
    a,b=_mins(row['opentime']),_mins(row['endtime'])
    return [(a,b if b>a else b+1440)]
def next_window(row,arrival,kind=None,min_duration=30):
    """Choose a real segment with sufficient time for the requested visit."""
    windows=segments(row)
    if windows is None:return (row['opentime'],row['endtime'])
    floor={'breakfast':360,'lunch':660,'dinner':1020}.get(kind,0)
    when=max(_mins(arrival),floor)
    for a,b in windows:
        if b-max(a,when)>=min_duration:return (_clock(a),_clock(b))
    return None
def open_or_later(row,when):
    try:
        windows=segments(row)
        return None if windows is None else next_window(row,when) is not None
    except (ValueError,TypeError,KeyError):return False
def total_segment_minutes(row):
    windows=segments(row)
    if windows is None:return None
    return sum(b-a for a,b in windows)
def meal_slot(row,arrival,lo,hi,duration):
    for a,b in all_windows(row):
        start=max(arrival,lo,a);end=start+duration
        if start<hi and end<=b:return start,end
    return None
