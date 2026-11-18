"""Opening windows for planning, including the gap between separate shifts."""
from __future__ import annotations
import json
import math

def _minutes(value):
    h,m=map(int,str(value).split(':'))
    if h<0 or h>24 or m<0 or m>59 or (h==24 and m):raise ValueError('invalid time')
    return h*60+m

def windows(row):
    raw=row.get('opening_segments_json')
    # NaN is how pandas represents a missing optional column.
    if raw is None or (isinstance(raw,float) and math.isnan(raw)) or raw=='':
        a,b=_minutes(row['opentime']),_minutes(row['endtime'])
        return [(a,b if b>a else b+1440)]
    if isinstance(raw,str):raw=json.loads(raw)
    if not isinstance(raw,list) or not raw:raise ValueError('invalid opening segments')
    out=[]
    for item in raw:
        a,b=map(int,item)
        if not 0<=a<b<=1440:raise ValueError('invalid opening interval')
        out.append((a,b))
    out.sort()
    if any(a[1]>b[0] for a,b in zip(out,out[1:])):raise ValueError('overlapping intervals')
    return out

def fits(row,start,duration):
    return any(a<=start and start+duration<=b for a,b in windows(row))

def earliest_visit(row,arrival,duration,cutoff,min_duration=30):
    """Prefer a full visit in the earliest valid segment; else use a safe partial."""
    partial=None
    for a,b in windows(row):
        start=max(arrival,a);end=min(start+duration,b,cutoff)
        if end-start>=duration:return start,end
        if partial is None and end-start>=min_duration:partial=(start,end)
    return partial
