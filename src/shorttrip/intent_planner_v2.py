"""Bounded proposal repair against participant-extracted intent, never hidden DSL."""
from __future__ import annotations
import math
from .env import minutes
from .intent_planner import IntentPlanner,nonempty_list


def intent_penalty(plan,intent):
    if not plan:return 10**12
    acts=[a for d in plan['itinerary'] for a in d['activities']]
    names={a.get('position') for a in acts};penalty=0.0
    for key in ('required_attractions','required_restaurants','required_hotels'):
        penalty+=10000*len(set(nonempty_list(intent.get(key)))-names)
    groups={'attraction':sum(a['cost'] for a in acts if a['type']=='attraction'),
       'restaurant':sum(a['cost'] for a in acts if a['type'] in ('breakfast','lunch','dinner')),
       'hotel':sum(a['cost'] for a in acts if a['type']=='accommodation'),
       'transport':sum(t['cost'] for a in acts for t in a.get('transports',[]))}
    total=sum(a['cost'] for a in acts)+groups['transport']
    for key,cost in [('budget',total)]+[(k+'_budget',v) for k,v in groups.items()]:
        cap=intent.get(key)
        if isinstance(cap,(int,float)) and cost>cap:penalty+=1000+10*(cost-cap)
    count=sum(a['type']=='attraction' for a in acts)
    if intent.get('attraction_count') is not None:penalty+=2000*abs(count-int(intent['attraction_count']))
    elif count<1:penalty+=2000
    for day in plan['itinerary']:
        n=sum(a['type']=='attraction' for a in day['activities'])
        desired=(intent.get('day_attraction_counts') or {}).get(str(day['day']))
        if desired is not None:penalty+=2000*abs(n-int(desired))
    for a in acts:
        if a['type']=='accommodation':
            for name,field in [('rooms','rooms'),('room_type','room_type')]:
                expected=intent.get(name)
                if expected is not None and a.get(field)!=int(expected):penalty+=5000
    primary=[]
    for a in acts:
        modes={t['mode'] for t in a.get('transports',[])}
        if modes:primary.append('taxi' if 'taxi' in modes else 'metro' if 'metro' in modes else 'walk')
    preferred=intent.get('mode_preference')
    if preferred in ('metro','taxi') and preferred not in primary:penalty+=500
    return penalty+total*.0001


class IntentPlannerV2(IntentPlanner):
    def __init__(self,env,intent):
        super().__init__(env,intent);self.cheap=False;self.search_history=[]

    def _pick_intercity(self,frm,to,window=None,reverse=False):
        if not self.cheap:return super()._pick_intercity(frm,to,window,reverse)
        direction='return' if reverse else 'outbound';mode=self.intent.get(direction+'_mode','any')
        modes=['airplane'] if mode in ('flight','airplane') else ['train'] if mode in ('train','G','D') else ['train','airplane']
        rows=[]
        for m in modes:rows.extend(dict(r,_p23_mode=m) for r in (self.env.trains(frm,to) if m=='train' else self.env.flights(frm,to)))
        prefixes=nonempty_list(self.intent.get('train_prefixes'))
        if mode in ('G','D'):prefixes=[mode]
        if prefixes:rows=[r for r in rows if r['_p23_mode']!='train' or any(str(r.get('TrainID','')).startswith(p) for p in prefixes)]
        after,before=self.intent.get(direction+'_after'),self.intent.get(direction+'_before')
        if after:rows=[r for r in rows if minutes(r['BeginTime'])>=minutes(after)]
        if before:rows=[r for r in rows if minutes(r['BeginTime'])<=minutes(before)]
        if not after and not before and window:
            same=[r for r in rows if window[0]<=minutes(r['BeginTime'])<=window[1]]
            if same:rows=same
        rows.sort(key=lambda r:(float(r['Cost']),-minutes(r['BeginTime']) if reverse else minutes(r['BeginTime'])))
        self.retrieval_events.append({'tool':'intercity_budget_search','direction':direction,'from':frm,'to':to,'matches':len(rows),'returned':min(5,len(rows))})
        return rows[:5]

    def _pick_hotels(self,city):
        rows=super()._pick_hotels(city)
        required=nonempty_list(self.intent.get('required_hotels'))
        if required:
            table=self.env.accommodation_table(city);matches=table[table['name'].astype(str).isin(required)].to_dict('records')
            return matches or rows
        if self.cheap:
            rows.sort(key=lambda r:float(r['price']))
        return rows

    def _ranked(self,frame,city,anchor,radius_km):
        rows=super()._ranked(frame,city,anchor,radius_km)
        if not self.cheap:return rows
        kind='attraction' if 'recommendmintime' in frame.columns else 'restaurant'
        required=nonempty_list(self.intent.get('required_'+kind+'s'))
        types=nonempty_list(self.intent.get(kind+'_types'));field='type' if kind=='attraction' else 'cuisine'
        rows.sort(key=lambda r:(0 if r['name'] in required else 1,
            0 if types and any(t in str(r.get(field,'')) for t in types) else 1,float(r['price'])))
        return rows

    def build_proposal(self,public_query):
        best=None;best_score=math.inf;saved=self.options.max_attractions_per_day
        variants=[(False,saved),(True,saved)]
        if self.intent.get('attraction_count') is None and not self.intent.get('day_attraction_counts'):
            variants.append((True,max(1,min(2,saved))))
        for cheap,stops in variants:
            self.cheap=cheap;self.options.max_attractions_per_day=stops
            result=super().build_proposal(public_query)
            score=intent_penalty(result.plan,self.intent)
            if result.plan:
                city=public_query['target_city'];acts=[a for d in result.plan['itinerary'] for a in d['activities']]
                for key,kinds,table,field in [
                    ('attraction_types',{'attraction'},self.env.attraction_table(city),'type'),
                    ('restaurant_types',{'breakfast','lunch','dinner'},self.env.restaurant_table(city),'cuisine'),
                    ('hotel_types',{'accommodation'},self.env.accommodation_table(city),'featurehoteltype')]:
                    wanted=nonempty_list(self.intent.get(key))
                    positions={a.get('position') for a in acts if a['type'] in kinds}
                    observed=table[table['name'].astype(str).isin(positions)][field].astype(str).tolist()
                    score+=5000*sum(not any(t in v for v in observed) for t in wanted)
            self.search_history.append({'cheap':cheap,'max_stops':stops,'proposal_delivered':bool(result.plan),'intent_penalty':score,'note':'No official checker feedback used to select this proposal.'})
            if best is None or score<best_score:best,best_score=result,score
            if best_score<.5:break
        self.options.max_attractions_per_day=saved
        return best
