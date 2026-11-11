"""Experimental, opt-in evidence matching BEFORE timed itinerary construction.

Pure local rules; no API/model calls. Real review evidence, sandbox attributes and
synthetic calibration are labelled separately. Confidence is a rule weight, not
an empirically measured extraction accuracy. Unknown never means hard-pass.
"""
from dataclasses import dataclass, asdict
import re

VERSION='candidate-tags-v0.2'
LICENSES={'cc_by','cc0','odbl'}
ORDINAL={'low':0,'medium':1,'high':2}

@dataclass(frozen=True)
class Demand:
    aspect:str
    desired:object
    scope:str='poi'
    relation:str='eq'
    hard:bool=False
    weight:float=1.0
    excerpt:str=''

@dataclass(frozen=True)
class Evidence:
    target:str
    scope:str
    aspect:str
    value:object
    quote:str
    review_id:str
    licence:str
    confidence:float=0.7
    kind:str='visitor_review'
    origin:str|None=None
    mode:str|None=None
    context:dict|None=None

def query_demands(text):
    """Small explicitly bounded Chinese parser; unrecognised clauses remain out.

    Whole-day/budget limits are returned for the trip checker, never applied as
    per-leg caps. A full language understanding system is NOT claimed.
    """
    out=[]
    for clause in re.split(r'[，。；！？,;]|但是|不过|但',text):
        clause=clause.strip()
        if not clause:continue
        for aspect,pattern in [('nature',r'自然|风景|山水|森林|海边'),('history',r'历史|文化|博物馆'),('photography',r'拍照|摄影')]:
            hits=list(re.finditer(pattern,clause))
            if not hits:continue
            negative=any(re.search(r'(?:不喜欢|不想|不要|讨厌|不爱|排除|避开).{0,5}$',clause[:m.start()]) for m in hits)
            out.append(Demand(aspect,not negative,excerpt=clause))
        if re.search(r'(?:不喜欢|不想|不要|不爱|不能|不).{0,2}(?:爬山|徒步)',clause):
            out.append(Demand('hiking',False,hard=bool(re.search('不能|禁止',clause)),excerpt=clause))
        if re.search(r'少走路|少步行|步行少|不想走太多|不喜欢走太多',clause):
            out.extend([Demand('walking_intensity','low',excerpt=clause),Demand('walk_minutes',None,scope='access_route',relation='minimize',excerpt=clause)])
        if re.search(r'(?:不|避免|不要|不能).{0,2}(?:台阶|楼梯)',clause):
            out.append(Demand('stairs',False,scope='access_route',hard=bool(re.search('不能|不要',clause)),excerpt=clause))
        if re.search(r'少排队|不想排队|不要排队|怕排队',clause):
            out.append(Demand('queue_report','low',excerpt=clause))
        if re.search(r'少等车|不想等车|不想久候',clause):
            out.append(Demand('wait_minutes',None,scope='access_route',relation='minimize',excerpt=clause))
        for mode,word in [('metro','地铁'),('taxi','打车'),('walk','步行')]:
            if re.search(r'只(?:坐|用|选|能坐)'+word,clause):
                out.append(Demand('mode',mode,scope='access_route',hard=True,excerpt=clause))
            elif re.search(word+r'优先|优先'+word,clause):
                out.append(Demand('mode',mode,scope='access_route',excerpt=clause))
        for m in re.finditer(r'(每段(?:接驳)?|每天|全程)?步行(?:不超过|最多|≤)\s*(\d+)\s*分钟',clause):
            scope='access_route' if m.group(1) and m.group(1).startswith('每段') else 'trip'
            aspect='daily_walk_minutes' if m.group(1)=='每天' else 'walk_minutes'
            out.append(Demand(aspect,int(m.group(2)),scope=scope,relation='le',hard=True,excerpt=clause))
    # Last explicit mention of the same aspect/scope/relation wins.
    merged={}
    for demand in out:merged[(demand.scope,demand.aspect,demand.relation)]=demand
    return list(merged.values())

def extract_evidence(review,licence,*,allow_synthetic=False):
    """Extract short verbatim evidence; unbound transport hints never become routes.

    A route's origin/mode must come from explicit supplied metadata; it is not
    guessed from a review. Internal park transport is separately scoped.
    """
    if licence not in LICENSES and not (licence=='synthetic' and allow_synthetic):return []
    text=review.get('text','');poi=review.get('poi_hint');rid=review.get('review_id')
    if not poi or not rid:return []
    route=review.get('route') or {}
    context=review.get('context') or {}
    out=[]
    sentences=re.split(r'[。！？；;\n]|(?<=[.!?])\s+(?=[A-Z])',text)
    for sentence in sentences:
        quote=sentence.strip()
        if not quote:continue
        internal=bool(re.search(r'within the park|inside the park|throughout the park|园内|景区内',quote,re.I))
        transport=bool(re.search(r'\b(?:bus|shuttle|metro|subway|taxi|cable car|gondola)\b|地铁|摆渡|缆车|公交|接驳|出站',quote,re.I))
        scope='internal_transport' if internal else ('access_route' if route.get('origin') and route.get('mode') else ('access_hint' if transport else 'poi'))
        def add(aspect,value):
            assert quote in text
            out.append(Evidence(poi,scope,aspect,value,quote,rid,licence,
                kind='synthetic' if licence=='synthetic' else 'visitor_review',
                origin=route.get('origin') if scope=='access_route' else None,
                mode=route.get('mode') if scope=='access_route' else None,context=context))
        if scope=='poi':
            for aspect,pattern in [('nature',r'\bscenery\b|\bforest\b|natural beauty|自然风光|山水|森林'),('history',r'\bhistor(?:y|ical)\b|博物馆|历史文化'),('photography',r'great for photos|good for photos|适合拍照|适合摄影')]:
                match=re.search(pattern,quote,re.I)
                if match and not re.search(r'not|no |不|没',quote[:match.start()][-12:],re.I):add(aspect,True)
        if re.search(r'no stairs|without stairs|没有台阶|不用爬楼梯|无台阶',quote,re.I):add('stairs',False)
        elif re.search(r'\bstairs\b|many steps|台阶多|很多台阶|楼梯',quote,re.I):add('stairs',True)
        if re.search(r'flat path|(?:path|trail).{0,8}\bflat\b|平坦',quote,re.I) and not re.search(r'not flat|不平坦',quote,re.I):
            add('terrain_flat',True)
        if re.search(r'easy walk|not much walking|不用走太多|步行少',quote,re.I):add('walking_intensity','low')
        elif re.search(r'long walk|lots of walking|many stairs|\bsteep\b|走很多|步行很长|台阶多',quote,re.I):add('walking_intensity','high')
        if re.search(r'no hiking required|no need to hike|不用爬山|不必爬山',quote,re.I):add('hiking',False)
        else:
            hike=re.search(r'\bhik(?:e|ing)\b|爬山|徒步',quote,re.I)
            if hike and not re.search(r"did not|didn't|不|没",quote[:hike.start()][-12:],re.I):add('hiking',True)
        if re.search(r'no (?:need to )?queue|not crowded|不用排队|无需排队|不拥挤',quote,re.I):
            if re.search(r'queue|排队',quote,re.I):add('queue_report','low')
        elif re.search(r'long queue|long line|queue for|排队很久|等很久',quote,re.I):add('queue_report','high')
        wait=re.search(r'wait(?:ed|ing)?\s+(?:for\s+)?(?:(?:about|over)\s+)?(\d+|forty|thirty|twenty)\s+min',quote,re.I)
        if wait:
            number={'forty':40,'thirty':30,'twenty':20}.get(wait.group(1).lower())
            number=int(wait.group(1)) if number is None else number
            add('wait_minutes',number)
            if number>=30:add('queue_report','high')
    return out

def compatible(value,demand):
    if demand.relation=='le':return value<=demand.desired
    if demand.relation=='ge':return value>=demand.desired
    return value==demand.desired

class CandidateMatcher:
    """Joint POI/access ranking; route feasibility is supplied by SandboxEnv.

    Hard limits use supplied operational facts, not review consensus as a proof.
    Reviews can reveal risk, but cannot certify accessibility. Whole-trip hard
    limits remain explicitly deferred to the planner/checker.
    """
    def __init__(self,evidence=(),*,include_routes=True,allow_synthetic=False,max_candidates=40):
        self.evidence=[e for e in evidence if e.quote and e.review_id and 0<=e.confidence<=1 and
                       (e.licence in LICENSES or (allow_synthetic and e.licence=='synthetic'))]
        self.include_routes=include_routes
        self.max_candidates=max_candidates
        self.trace=[]

    def score(self,poi,origin,mode,demands,operational):
        checks=[];score=0.;total=0.;blocked=False
        for d in demands:
            if d.scope=='trip':
                checks.append({'demand':asdict(d),'status':'deferred_trip_checker'});continue
            if d.scope=='access_route' and not self.include_routes and not d.hard:
                checks.append({'demand':asdict(d),'status':'ablation_omitted'});continue
            total+=d.weight
            rows=[e for e in self.evidence if e.target==poi and e.scope==d.scope and e.aspect==d.aspect and (e.scope!='access_route' or (e.origin==origin and e.mode==mode))]
            # Conditional crowd/wait observations do not generalise to arbitrary
            # trip conditions. This version uses only unconditioned observations.
            rows=[e for e in rows if not e.context]
            if d.scope=='access_route' and d.aspect in operational:
                values=[operational[d.aspect]];source='sandbox_operational';confidence=1.
            else:
                values=[e.value for e in rows];source='review_evidence';confidence=min((e.confidence for e in rows),default=0.)
            if d.relation=='minimize' and values:
                status='measured_preference'
            elif not values:status='unknown'
            elif any(compatible(v,d) for v in values) and any(not compatible(v,d) for v in values):status='conflict'
            else:status='match' if all(compatible(v,d) for v in values) else 'mismatch'
            # A review assertion is not an operational hard-satisfaction proof.
            if d.hard and source!='sandbox_operational' and status=='match':status='unknown_hard'
            if d.hard and status!='match':blocked=True
            contribution=confidence*d.weight*(1 if status=='match' else -1 if status=='mismatch' else 0)
            if status=='measured_preference':
                # Monotone soft burden, with no invented hard minute limit.
                value=max(float(v) for v in values)
                contribution=confidence*d.weight/(1+value)
            score+=contribution
            checks.append({'demand':asdict(d),'status':status,'source':source,'contribution':contribution,
                           'evidence':[asdict(e) for e in rows]})
        known=sum(c['status'] in ('match','mismatch','measured_preference') for c in checks)
        return {'score':round(score/max(total,1.),6),'blocked':blocked,'decision':'insufficient_evidence' if not known else 'scored_from_evidence',
                'checks':checks,'whole_trip_verified':False}

    def rank_rows(self,rows,*,city,origin,env,query):
        demands=query_demands(query.get('nature_language',''));ranked=[]
        if not any(d.scope!='trip' for d in demands):
            self.trace.append({'city':city,'origin':origin,'decision':'no_local_demands_preserved_baseline'})
            return rows
        route_requested=any(d.scope=='access_route' for d in demands)
        for base_index,row in enumerate(rows[:self.max_candidates]):
            poi=str(row['name']);options=[]
            modes=('metro','taxi','walk') if self.include_routes else ('metro','walk','taxi')
            for mode_index,mode in enumerate(modes):
                legs=env.leg_templates(city,origin,poi,mode)
                if not legs:continue
                # LegTemplate.seconds is historical naming: values are hours.
                operational={'mode':mode,'walk_minutes':sum(l.seconds*60 for l in legs if l.mode=='walk')}
                result=self.score(poi,origin,mode,demands,operational)
                if not result['blocked']:options.append((result,mode,sum(l.seconds for l in legs),mode_index))
                if (not self.include_routes or not route_requested) and options:break
            if not options:continue
            best,mode,hours,_=min(options,key=lambda o:(-o[0]['score'],o[3]))
            ranked.append((best['score'],base_index,{**row,'_tagmatch_mode':mode,'_tagmatch_result':best}))
        ranked.sort(key=lambda item:(-item[0],item[1]))
        self.trace.append({'city':city,'origin':origin,'query':query.get('nature_language',''),
            'input_candidates':len(rows),'pool_limit':self.max_candidates,
            'demands':[asdict(d) for d in demands],
            'ranked':[{'poi':r['name'],'mode':r['_tagmatch_mode'],**r['_tagmatch_result']} for _,_,r in ranked]})
        return [r for _,_,r in ranked]

    def audit_plan(self,query,plan):
        """New explicit hard demands get a separate, full-plan local audit.

        Does not alter the official checker's denominator. Ordinal review-only
        guarantees (e.g. absolutely no stairs) remain unknown rather than pass.
        """
        demands=[d for d in query_demands(query.get('nature_language','')) if d.hard]
        def minutes(t):
            h,m=map(int,str(t).split(':')[:2]);return h*60+m
        days=[];access=[]
        for day in plan.get('itinerary',[]):
            walked=0.
            for a in day.get('activities',[]):
                legs=a.get('transports') or []
                if not legs:continue
                walk=sum(max(0,minutes(l['end_time'])-minutes(l['start_time'])) for l in legs if l['mode']=='walk')
                walked+=walk
                mode='taxi' if any(l['mode']=='taxi' for l in legs) else ('metro' if any(l['mode']=='metro' for l in legs) else 'walk')
                access.append({'walk_minutes':walk,'mode':mode})
            days.append(walked)
        checks=[]
        for d in demands:
            if d.scope=='trip' and d.aspect in ('walk_minutes','daily_walk_minutes'):
                values=days if d.aspect=='daily_walk_minutes' else [sum(days)]
            elif d.scope=='access_route' and d.aspect in ('mode','walk_minutes'):
                values=[a[d.aspect] for a in access]
            else:values=[]
            status='unknown' if not values else ('pass' if all(compatible(v,d) for v in values) else 'fail')
            checks.append({'demand':asdict(d),'values':values,'status':status})
        return {'all_hard_satisfied':all(c['status']=='pass' for c in checks),'checks':checks,
                'domain':'given sandbox schedule only; not a live accessibility certificate'}
