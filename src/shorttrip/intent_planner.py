"""LLM content intents -> official sandbox plans, with no access to hidden DSL.

All timings/prices/routes are materialised by the existing frozen sandbox
scheduler. Official checker results are computed only after a proposal exists.
"""
from __future__ import annotations
import math
import pandas as pd
from .env import minutes
from .planner import PlannerOptions, SkeletonPlanner


def nonempty_list(value):
    return [str(x) for x in value] if isinstance(value,list) else []


class IntentPlanner(SkeletonPlanner):
    def __init__(self,env,intent):
        self.intent=intent
        self.retrieval_events=[]
        max_stops=int(intent.get('max_attractions_per_day') or 3)
        super().__init__(env,PlannerOptions(max_attractions_per_day=max(1,min(max_stops,6)),max_combos=6,
            prefer_mode=intent.get('mode_preference') or 'metro'))

    def _pick_intercity(self,frm,to,window=None,reverse=False):
        direction='return' if reverse else 'outbound'
        requested=self.intent.get(direction+'_mode','any')
        if requested in ('airplane','flight'):modes=['airplane']
        elif requested in ('G','D','train'):modes=['train']
        else:modes=['train','airplane']
        pool=[]
        for mode in modes:
            rows=self.env.trains(frm,to) if mode=='train' else self.env.flights(frm,to)
            pool.extend(dict(r,_p23_mode=mode) for r in rows)
        prefixes=nonempty_list(self.intent.get('train_prefixes'))
        if requested in ('G','D'):prefixes=[requested]
        if prefixes:
            pool=[r for r in pool if r['_p23_mode']!='train' or any(str(r.get('TrainID','')).startswith(p) for p in prefixes)]
        for key,operator in ((direction+'_after',lambda a,b:a>=b),(direction+'_before',lambda a,b:a<=b)):
            value=self.intent.get(key)
            if value:
                bound=minutes(str(value));pool=[r for r in pool if operator(minutes(r['BeginTime']),bound)]
        if not any(self.intent.get(direction+x) for x in ('_after','_before')) and window:
            feasible=[r for r in pool if window[0]<=minutes(r['BeginTime'])<=window[1]]
            if feasible:pool=feasible
        if reverse:pool.sort(key=lambda r:(-minutes(r['BeginTime']),float(r['Cost'])))
        else:pool.sort(key=lambda r:(minutes(r['BeginTime']),float(r['Cost'])))
        self.retrieval_events.append({'tool':'intercity','from':frm,'to':to,'direction':direction,'matches':len(pool),'returned':min(5,len(pool)),'fields_used':['mode','departure','cost']})
        return pool[:5]

    def _intercity_activity(self,record,kind,people,transports):
        return super()._intercity_activity(record,record.get('_p23_mode',kind),people,transports)

    def _pick_hotels(self,city):
        table=self.env.accommodation_table(city).copy()
        table['price']=pd.to_numeric(table['price'],errors='coerce');table=table.dropna(subset=['price'])
        room_type=self.intent.get('room_type')
        if room_type is not None:table=table[pd.to_numeric(table['numbed'],errors='coerce')==int(room_type)]
        banned=nonempty_list(self.intent.get('forbidden_hotels'))
        table=table[~table['name'].astype(str).isin(banned)]
        names=nonempty_list(self.intent.get('hotel_names'));types=nonempty_list(self.intent.get('hotel_types'))
        rows=table.to_dict('records')
        def rank(r):
            return (0 if r['name'] in names else 1,
                    0 if any(t in str(r.get('featurehoteltype','')) for t in types) else 1,float(r['price']))
        rows.sort(key=rank)
        self.retrieval_events.append({'tool':'hotels','city':city,'matches':len(rows),'returned':min(12,len(rows))})
        return rows[:12]

    def _first_reachable_hotel(self,builder,hotels,anchor):
        # Preserve participant priorities. The old helper re-sorted them by distance.
        for row in hotels:
            name=str(row['name']);mode=self.env.best_mode(builder.city,builder.position or anchor,name,builder.mode_preference)
            dur=self.env.trip_seconds(builder.city,builder.position or anchor,name,mode) if mode else None
            if dur is not None and minutes(builder.time)+dur*60<22*60+40:return row
        return None

    def _ranked(self,frame,city,anchor,radius_km):
        kind='attraction' if 'recommendmintime' in frame.columns else 'restaurant'
        field='type' if kind=='attraction' else 'cuisine'
        plural=kind+'s'
        required=nonempty_list(self.intent.get('required_'+plural))
        preferred=nonempty_list(self.intent.get('preferred_'+plural))
        types=nonempty_list(self.intent.get(kind+'_types'))
        banned=nonempty_list(self.intent.get('forbidden_'+plural))
        banned_types=nonempty_list(self.intent.get('forbidden_'+kind+'_types'))
        subset=frame[~frame['name'].astype(str).isin(banned)].copy()
        if banned_types:
            subset=subset[~subset[field].astype(str).apply(lambda v:any(t in v for t in banned_types))]
        local=super()._ranked(subset,city,anchor,radius_km)
        rows=subset.to_dict('records')
        exact=[r for r in rows if str(r['name']) in required+preferred or any(t in str(r.get(field,'')) for t in types)]
        merged={str(r['name']):r for r in exact+local}
        order={str(r['name']):i for i,r in enumerate(local)}
        def key(r):
            name=str(r['name'])
            return (0 if name in required else 1,0 if name in preferred else 1,
                    preferred.index(name) if name in preferred else 999,
                    0 if any(t in str(r.get(field,'')) for t in types) else 1,order.get(name,999))
        ranked=sorted(merged.values(),key=key)
        self.retrieval_events.append({'tool':plural,'city':city,'query_names':required+preferred,'query_types':types,'candidate_rows':len(rows),'returned':len(ranked)})
        return ranked

    def _fill_day(self,builder,query,**kwargs):
        builder.mode_preference=self.intent.get('mode_preference') or 'metro'
        saved=self.options.max_attractions_per_day
        counts=self.intent.get('day_attraction_counts') or {}
        value=counts.get(str(builder.day_index+1))
        total=self.intent.get('attraction_count')
        if value is not None:self.options.max_attractions_per_day=max(0,int(value))
        elif total is not None:
            used=len(kwargs['used_attractions']);left=int(query['days'])-builder.day_index
            self.options.max_attractions_per_day=max(0,math.ceil((int(total)-used)/left))
        try:super()._fill_day(builder,query,**kwargs)
        finally:self.options.max_attractions_per_day=saved

    def build_proposal(self,public_query):
        # Explicit allowlist: no DSL/oracle can enter the planning object.
        query={k:public_query[k] for k in ('uid','start_city','target_city','days','people_number','nature_language')}
        result=super().build(query,deep_check=False)
        if result.plan:
            rooms=self.intent.get('rooms')
            for day in result.plan['itinerary']:
                for a in day['activities']:
                    if a['type']=='accommodation' and rooms is not None:
                        a['rooms']=max(1,int(rooms));a['cost']=a['price']*a['rooms']
        return result
