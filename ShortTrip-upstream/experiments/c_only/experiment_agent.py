"""Experimental B/C agents extending the original LLMNeSy soft-search agent."""
import copy
import sys
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
from chinatravel.soft_constraints.agent import SoftLLMDrivenAgent
from chinatravel.agent.nesy_agent.nesy_agent import NesyAgent
from chinatravel.agent.nesy_agent.utils import add_time_delta
import dfs_snapshot
from rules import WINDOWS, clock, hhmm, audit, meal_obligations, ticket_interval, meal_fits, future_meal_possible, attraction_slot

def ticket(transport):
    result=dict(start_time=transport['BeginTime'],end_time=transport['EndTime'])
    if transport.get('Duration') is not None:result['duration_hours']=transport['Duration']
    return result

def prefer_go(indices,rows):
    positions={int(idx):rank for rank,idx in enumerate(indices)}
    def key(idx):
        row=rows.iloc[idx] if hasattr(rows,'iloc') else rows[idx]
        iv=ticket_interval(ticket(row),1)
        return (not 360<=iv['start']<720,iv['end'],iv['end']-iv['start'],positions[int(idx)])
    return sorted(indices,key=key)

def prefer_back(indices,rows):
    positions={int(idx):rank for rank,idx in enumerate(indices)}
    def key(idx):
        row=rows.iloc[idx] if hasattr(rows,'iloc') else rows[idx]
        start=clock(row['BeginTime'])
        iv=ticket_interval(ticket(row),1)
        return (not 1080<=start<1440,-start,iv['end']-iv['start'],positions[int(idx)])
    return sorted(indices,key=key)

class ExperimentAgent(SoftLLMDrivenAgent):
    def __init__(self,*,group,**kwargs):
        assert group in {'B','C'}
        self.group=group
        self.rule_rejections=0
        self._obligation_cache={}
        super().__init__(**kwargs)

    def outbound_next(self,transport):
        iv=ticket_interval(ticket(transport),1)
        return iv['end_day']-1,hhmm(int(iv['end'])%1440)

    def requirements(self,poi_plan):
        go,back=poi_plan['go_transport'],poi_plan['back_transport']
        key=(str(go['BeginTime']),str(go['EndTime']),str(go.get('Duration')),str(back['BeginTime']),str(back['EndTime']),str(back.get('Duration')),self.query['days'])
        cache=getattr(self,'_obligation_cache',{})
        if key not in cache:
            skeleton=dict(itinerary=[dict(day=1,activities=[dict(type='train',**ticket(go))]),dict(day=self.query['days'],activities=[dict(type='train',**ticket(back))])])
            cache[key]=meal_obligations(skeleton)
            self._obligation_cache=cache
        return cache[key]

    def missing_today(self,plan,poi_plan,current_day):
        acts=plan[current_day]['activities'] if current_day<len(plan) else []
        eaten={a['type'] for a in acts if a['type'] in WINDOWS}
        return [o for o in self.requirements(poi_plan) if o['day']==current_day+1 and o['status']=='required' and o['kind'] not in eaten]

    def close_day_allowed(self,plan,poi_plan,current_day):
        return not self.missing_today(plan,poi_plan,current_day)

    def meals_possible_after(self,plan,poi_plan,current_day,end_time,position):
        """Necessary, optimistic meal witnesses after a complete attraction visit.

        Waiting caps are not applied here: intervening activities can fill time
        before a later meal. Actual meal scheduling and final audits still apply.
        Unknown database/route information must not prove impossibility.
        """
        if self.group!='C':return True
        now=current_day*1440+clock(end_time)
        rows=getattr(self,'memory',{}).get('restaurants')
        for obligation in self.missing_today(plan,poi_plan,current_day):
            if not future_meal_possible(obligation,now):
                self.record_prune(dict(rule='meal_after_attraction',constraint=obligation['kind'],details=dict(day=obligation['day'],end_time=end_time,position=position,cause='no remaining time slot')))
                return False
            if rows is None:continue
            used=tuple(sorted(getattr(self,'restaurants_visiting',[])))
            key=(self.query['target_city'],position,end_time,current_day,used,
                 obligation['kind'],tuple(obligation['window']),
                 tuple(map(tuple,obligation['free_intervals'])),
                 tuple(self.innercity_transports_ranking_from_query))
            cache=getattr(self,'_meal_feasibility_cache',{})
            if key in cache:
                if not cache[key]:
                    self.record_prune(dict(rule='meal_after_attraction',constraint=obligation['kind'],details=dict(day=obligation['day'],end_time=end_time,position=position,cause='no restaurant/access witness')))
                    return False
                continue
            possible=False;unknown=False
            for index,row in rows.iterrows():
                self._deadline_check()
                if index in used:continue
                for mode in self.innercity_transports_ranking_from_query:
                    try:
                        route=self.collect_innercity_transport(self.query['target_city'],position,row['name'],end_time,mode)
                        if not isinstance(route,list):continue
                        arrived=clock(route[-1]['end_time']) if route else clock(end_time)
                        if arrived<clock(end_time):arrived+=1440
                        start=max(now,current_day*1440+arrived,
                                  current_day*1440+clock(row['opentime']),obligation['window'][0])
                        finish=start+obligation['duration']
                        if (finish<=current_day*1440+clock(row['endtime'])
                                and meal_fits(obligation,start,finish)):
                            possible=True;break
                    except (ValueError,KeyError,TypeError,IndexError):
                        unknown=True
                if possible:break
            cache[key]=possible or unknown
            self._meal_feasibility_cache=cache
            if not cache[key]:
                self.record_prune(dict(rule='meal_after_attraction',constraint=obligation['kind'],details=dict(day=obligation['day'],end_time=end_time,position=position,cause='no restaurant/access witness')))
                return False
        return True

    def day_resume_time(self,plan,poi_plan,current_day,current_time):
        if current_time!='00:00' or current_day==0 or current_day>len(plan)-1:
            return current_time
        previous=plan[current_day-1]['activities']
        if not previous or previous[-1]['type']!='accommodation':return current_time
        # An explicitly early return may still need overnight access; sightseeing
        # remains independently forbidden before08:00 in both scheduling/audit.
        if current_day==self.query['days']-1:
            back=poi_plan['back_transport']
            begin=clock(back['BeginTime'])
            if begin<360:return current_time
            source=previous[-1].get('position')
            if source and back.get('From') and self.query.get('target_city'):
                modes=getattr(self,'innercity_transports_ranking_from_query',['metro','taxi','walk'])
                buffer=120 if str(back.get('FlightID','nan'))!='nan' else 60
                fits=False
                for mode in modes:
                    route=self.collect_innercity_transport(self.query['target_city'],source,back['From'],'06:00',mode)
                    if isinstance(route,list):
                        arrival=clock(route[-1]['end_time']) if route else 360
                        if arrival+buffer<=begin:
                            fits=True
                            break
                if not fits:return current_time
            elif begin<540:
                return current_time
        return '06:00'

    def attraction_slot(self,arrived,opens,closes,duration):
        return attraction_slot(arrived,opens,closes,duration)

    def dfs_poi(self,query,poi_plan,plan,current_time,current_position,current_day=0):
        self._deadline_check()
        if self.prune_partial(query, plan, poi_plan):return False,plan
        if self.group=='C' and not plan and current_time=='':
            from meal_pruning import preflight
            rejected=preflight(self,query,poi_plan)
            if rejected:
                self.record_prune(rejected)
                return False,plan
        if current_day>=query['days']:
            return False,plan
        while len(plan)<=current_day and current_time!='':
            plan.append(dict(day=len(plan)+1,activities=[]))
        was_midnight=current_time=='00:00'
        current_time=self.day_resume_time(plan,poi_plan,current_day,current_time)
        if current_time!='':
            now=current_day*1440+clock(current_time)
            for o in self.missing_today(plan,poi_plan,current_day):
                if not future_meal_possible(o,now):
                    self.rule_rejections+=1
                    self.record_prune(dict(rule='meal_deadline',constraint=o['kind'],details=dict(day=o['day'],now=now)))
                    return False,plan
        # Preserve genuine hotel breakfast, but only when the previous night was
        # actually at this hotel and 08:00 fits the journey/traffic opportunity.
        if was_midnight and current_day>0:
            previous=plan[current_day-1]['activities']
            hotel=poi_plan.get('accommodation')
            morning=current_day*1440+480
            required=self.missing_today(plan,poi_plan,current_day)
            fits=any(o['kind']=='breakfast' and any(b<=morning and morning+30<=e for b,e in o['available']) for o in required)
            if hotel is not None and fits and current_position==hotel['name'] and previous and previous[-1]['type']=='accommodation':
                with_breakfast=copy.deepcopy(plan)
                with_breakfast[current_day]['activities']=self.add_poi(with_breakfast[current_day]['activities'],hotel['name'],'breakfast',0,0,'08:00','08:30',innercity_transports=[])
                success,result=self.dfs_poi(query,poi_plan,with_breakfast,'08:30',current_position,current_day)
                if success:return success,result
        self._context=(plan,poi_plan,current_day,current_time,current_position)
        return dfs_snapshot.dfs_poi(self,query,poi_plan,plan,current_time,current_position,current_day)

    def select_next_poi_type(self,candidates_type,plan,poi_plan,current_day,current_time,current_position):
        # Remove already missed/exempt meals, and block closing a day with a meal due.
        missing=self.missing_today(plan,poi_plan,current_day)
        required={o['kind'] for o in missing}
        candidates_type[:]=[t for t in candidates_type if t not in WINDOWS or t in required]
        if missing:
            candidates_type[:]=[t for t in candidates_type if t not in {'hotel','back-intercity-transport'}]
        now=current_day*1440+clock(current_time)
        for o in sorted(missing,key=lambda o:o['window'][1]):
            if self.group!='C' and o['kind'] in candidates_type and now>=o['window'][0]-30:
                return o['kind'],candidates_type
        if not candidates_type:
            # A failed required meal branch cannot be bypassed by another activity.
            return 'attraction',[]
        if self.group=='C' and 'hotel' in candidates_type and clock(current_time)<1200:
            candidates_type.remove('hotel')
            candidates_type.append('hotel')
        # Mandatory meal rules must run before the original 180-minute return shortcut.
        if missing:
            # Invoke the same existing model prompt and parser without the shortcut.
            import re,time
            from chinatravel.agent.nesy_agent import llm_driven_rec as rec
            before=time.time()
            content=rec.NEXT_POI_TYPE_INSTRUCTION.format(self.query['nature_language'],poi_plan,current_day+1,current_time,current_position,candidates_type)
            if self.group=='C':
                content+='\n【当前C组实际规则，覆盖上文冲突规则】\n'
                content+='三餐必须完成，但进入饭点不代表必须立即吃饭。早餐也是可搜索类型。\n'
                content+='当前仍需用餐：'+str([o['kind'] for o in missing])+'；实际窗口和时长：'+str(WINDOWS)+'（分钟，自午夜起；窗口上界为开始截止）。\n'
                content+='可比较先景点后吃饭、先吃饭后景点。后续代码会按完整参观、真实交通、餐厅营业和完整用餐时长检查是否来得及；不要仅因11点到来强制午餐，也不要假定13点截止。保留用餐所需时间；仍需用餐时不能直接结束当天或返程。\n'
            answer=self.backbone_llm([dict(role='user',content=content)],one_line=False)
            self.llm_inference_time_count+=time.time()-before
            self.llm_rec_count+=1
            match=re.search(r'Type:\s*(\w+)',answer)
            selected=match.group(1) if match else None
            return (selected if selected in candidates_type else candidates_type[0]),candidates_type
        return super().select_next_poi_type(candidates_type,plan,poi_plan,current_day,current_time,current_position)

    def add_restaurant(self,current_plan,poi_type,poi_sel,current_day,arrived_time,transports_sel):
        lo,hi,duration=WINDOWS[poi_type]
        start=max(clock(arrived_time),clock(poi_sel['opentime']),lo)
        if self.group=='C' and start-clock(arrived_time)>60 and transports_sel:
            # Waiting is moved before departure only when the same real route
            # recomputed at that time still reaches the open restaurant.
            access_duration=max(0,clock(transports_sel[-1]['end_time'])-clock(transports_sel[0]['start_time']))
            depart=max(clock(transports_sel[0]['start_time']),start-access_duration)
            mode='metro' if any(t['mode']=='metro' for t in transports_sel) else 'taxi' if any(t['mode']=='taxi' for t in transports_sel) else 'walk'
            revised=self.collect_innercity_transport(self.query['target_city'],transports_sel[0]['start'],poi_sel['name'],hhmm(depart),mode)
            if isinstance(revised,list) and revised:
                transports_sel=revised
                arrived_time=revised[-1]['end_time']
                start=max(clock(arrived_time),clock(poi_sel['opentime']),lo)
        end=start+duration
        if start>=hi or end>clock(poi_sel['endtime']) or not self.allow_wait(arrived_time,hhmm(start)):
            raise ValueError('Meal cannot fit opening/start window')
        # Required meals must finish before the next intercity event.
        poi_plan=self._context[1]
        absolute=current_day*1440+start
        valid=any(o['kind']==poi_type and o['day']==current_day+1 and meal_fits(o,absolute,absolute+duration) for o in self.requirements(poi_plan))
        if not valid:raise ValueError('Meal overlaps traffic/boundary')
        # A searched restaurant keeps its true identity, price and access legs.
        price=int(poi_sel['price']);name=poi_sel['name']
        updated=copy.deepcopy(current_plan)
        updated[current_day]['activities']=self.add_poi(updated[current_day]['activities'],name,poi_type,price,price*self.query['people_number'],hhmm(start),hhmm(end),innercity_transports=transports_sel)
        return updated

    def allow_wait(self,arrived,start):
        return self.group!='C' or clock(start)-clock(arrived)<=60

    def constraints_validation(self,query,plan,poi_plan):
        check=audit(dict(itinerary=plan),query['days'])
        if not check['all_pass']:
            self.rule_rejections+=1
            self.record_prune(dict(rule='final_C_audit',constraint='meal/date/daytime',details=dict(violations=check['violations'][:5],date_pass=check['date_pass'],day_limit_pass=check['day_limit_pass'])))
            return False,plan
        return super().constraints_validation(query,plan,poi_plan)

    def reranking_intercity_transport_go_with_constraints(self,indices,info,query):
        valid=[]
        for idx in indices:
            row=info.iloc[idx]
            try:
                if self.outbound_next(row)[0]<query['days']:valid.append(idx)
            except ValueError:pass
        if not valid:return []
        result=super().reranking_intercity_transport_go_with_constraints(valid,info,query)
        return prefer_go(result,info) if self.group=='C' else result

    def reranking_intercity_transport_back_with_constraints(self,indices,info,query,go):
        valid=[]
        for idx in indices:
            row=info.iloc[idx]
            try:
                iv=ticket_interval(ticket(row),query['days'])
                if iv['end']<=query['days']*1440:valid.append(idx)
            except ValueError:pass
        if not valid:return []
        result=super().reranking_intercity_transport_back_with_constraints(valid,info,query,go)
        return prefer_back(result,info) if self.group=='C' else result

    def add_intercity_transport(self,activities,intercity_info,innercity_transports=None,tickets=1):
        legs=innercity_transports or []
        if self.group=='C' and activities and legs:
            # All actual nonempty-access intercity additions in DFS are the return.
            goal=clock(intercity_info['BeginTime'])-(60 if str(intercity_info.get('TrainID','nan'))!='nan' else 120)
            duration=clock(legs[-1]['end_time'])-clock(legs[0]['start_time'])
            original=clock(legs[0]['start_time'])
            depart=max(original,goal-max(0,duration))
            mode='metro' if any(t['mode']=='metro' for t in legs) else 'taxi' if any(t['mode']=='taxi' for t in legs) else 'walk'
            for _ in range(3):
                if depart>=1440:break
                revised=self.collect_innercity_transport(self.query['target_city'],legs[0]['start'],intercity_info['From'],hhmm(depart),mode)
                if not isinstance(revised,list) or not revised:break
                arrived=clock(revised[-1]['end_time'])
                if arrived<=goal:
                    legs=revised
                    break
                depart=max(original,depart-(arrived-goal))
        return super().add_intercity_transport(activities,intercity_info,legs,tickets)
