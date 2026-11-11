"""Freeze 24 focused LLM cases with positive witnesses and explicit failure classes."""
import copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_guard import VERSION,schema
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def fixture(field,value):
    raw=json.dumps(value,ensure_ascii=False)
    return {'evidence_id':'fixture:'+field,'target_id':'fixture:venue','city':'测试城','field':field,'value':value,'context':{},'level':'verified',
        'source_id':'synthetic_fixture','source_url':'fixture://p25/unit-witness','raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'synthetic':True,'fixture_validated':True,'scope':'ENGINEERING FIXTURE ONLY. No real travel fact.'}
def main():
    if (OUT/'private/cases.json').exists():raise FileExistsError('Already frozen')
    base=read(OUT/'real/query.json');corpus=read(OUT/'real/corpus.json');cases=[];public={}
    kinds=['known_fixture','real_conditional','over_budget','missing_identity','wrong_date','missing_coordinates','distractor_price','identity_estimate']
    for level,prefix in [('easy','E'),('hard','D'),('human','H')]:
        batch=[]
        for i,kind in enumerate(kinds,1):
            q=copy.deepcopy(base);q.update(uid=prefix+f'{i:02d}',level=level);evidence=copy.deepcopy(corpus['evidence']);expect=kind in ('known_fixture','real_conditional','distractor_price')
            if kind=='known_fixture':
                evidence=[fixture('identity',{'fixture_id':'venue'}),fixture('price',40),fixture('opening_hours',{'open':'09:00','close':'17:00','last_admission':'16:30'})]
                q.update(city_sequence=['测试城'],candidates=[{'entity_id':'fixture:venue','name':'工程测试馆','city':'测试城','dataset':'synthetic_fixture'}],budget_cny=100,route_buffer_minutes=0)
                q['requirements']=[{**{k:e[k] for k in ('target_id','city','field','context')},'accepted_levels':['verified'],'entity_required':True} for e in evidence]
                q['nature_language']='这是一条明确的合成工程测试，不代表真实旅行。两人24日10:00至12:00参观测试城工程测试馆，已在入口，无交通餐饮住宿，总预算100元。请检索并引用测试身份、票价与开放证据；不要把合成证据声称为现实核实。'
            elif kind=='over_budget':
                q['budget_cny']=80;q['nature_language']=q['nature_language'].replace('预算200元','预算80元')+'固定岳麓书院和往返地铁，不可删项或用预算额度冒充报价；预算不够就明确拒绝完整接受。'
            elif kind=='missing_identity':
                evidence=[e for e in evidence if e['field']!='identity'];q['nature_language']+='本题实体映射尚未核实，需要检索确认；不能只凭同名或候选ID认定映射已确认。'
            elif kind=='wrong_date':
                q=json.loads(json.dumps(q,ensure_ascii=False).replace('2026-10-24','2026-10-26').replace('10月24日','10月26日'));q['nature_language']+='注意日期是26日，24日证据不能挪用。'
            elif kind=='missing_coordinates':
                for r in q['requirements']:
                    if r['field'] in ('route_duration','route_fare'):r['context'].update(origin=None,destination=None)
                q['nature_language']+='本题撤销已核实入口坐标，起点和终点GCJ02均未知，不能使用另一任务的路线。请说明需要补充什么。'
            elif kind=='distractor_price':
                distractor=copy.deepcopy(next(e for e in evidence if e['field']=='price'));distractor.update(evidence_id='distractor:old-price',value=5,rejected_reason='wrong_ticket_class_or_date',level='reference');evidence.append(distractor)
                q['nature_language']+='检索回包可能有旧日期或不同票种的低价线索，必须服从eligibility，不能按最低价选用。'
            elif kind=='identity_estimate':
                for e in evidence:
                    if e['field']=='identity':e['level']='estimate';e['evidence_id']+=':estimated'
                q['nature_language']+='若只有推测的实体绑定，不得把estimate提升verified；应保留身份阻塞。'
            if level=='human':q['nature_language']='我和朋友想照这个安排去，别给我一个看起来完整但没证据的答案。'+q['nature_language']+'请用缺口和反馈说清楚不能确定什么。'
            if level=='hard':q['nature_language']+='必须检查所有分项单价/人数总额、返程交通、开放/停止入馆以及引用的日期/方向；不能偷删必需字段。'
            q['retrieval_budget']=6
            route_contexts=[{**{k:r[k] for k in ('target_id','city','field','context')}} for r in q['requirements'] if r['field'] in ('route_duration','route_fare')]
            pub={k:v for k,v in q.items() if k!='requirements'};pub['route_contexts']=route_contexts
            pub['allowed_output']='conditional plan with explicit prerequisites; complete means execution confirmed, not just all fields filled'
            batch.append(pub);cases.append({'level':level,'uid':q['uid'],'kind':kind,'query':q,'evidence':evidence,'expected_policy_accepted':expect})
        public[level]=batch;save(OUT/'public/levels'/(level+'.json'),batch)
    save(OUT/'private/cases.json',cases);save(OUT/'public/plan.schema.json',schema())
    prompt='''你是被测旅行规划LLM。只读分配的public/levels/LEVEL.json、public/plan.schema.json及本prompt；后续只可再读自己的首稿与responses/LEVEL.json。禁止读private、real目录、实现、评分、其他参与者和旧实验结果；不联网、不调用API。每层8题，逐题做完整计划、缺口和请求，不调现成planner。可用Python序列化和结构复用，但语义决定必须逐题由你作出。\nstatic阶段只能使用查询、候选和路线上下文，不能编数值；unknown=null。输出participants/LEVEL_static.json 8份完整plan。不要先猜某题是否可解。\n请求约定：identity用candidate.entity_id，无日期context；price/opening_hours用entity_id，context.travel_date。天气weather:长沙；路线target为route:起点entityID>终点entityID，上下文按route_contexts包含精确起终坐标/出发时间/GCJ02/方式。相同目标可合并字段请求。identity可用operator请求，天气/路线amap，fixture用static。合成测试身份/票价/开放没有日期context。\n原生计划schema_version=shorttrip-dynamic-v2。price是成人每人价；cost是人数总额。transport.price是每人票价，transport.cost是全组金额，tickets=人数；duration_minutes必须有来源。anchor可存入/返程transports，活动本身price/cost保持unknown即可，成本仍会统计它的交通。\n13:00起点anchor；14:00–16:00岳麓书院；终点anchor可暂排17:15，返程从16:00开始，交通窗口至少比API耗时多10min。不加未要求的餐饮/酒店/捏造0费用。fixture只需一段10:00–12:00活动，无交通。首稿所有需要查询的字段保留gaps，request预算6。\ndynamic阶段会给实际请求回包。每条有eligibility.can_resolve/max_status/reasons，禁止用不可用证据填数或标resolved；对每条反馈use/reject/defer。price/reference是参考，不是已付款；weather/routes仅estimate。库存/预约必须verified才算确认，没有证据需unavailable。即使预算或身份不满足，也可给blocked方案和正确的已知部分，不能声称complete。不要改首稿；输出participants/LEVEL_dynamic.json。'''
    (OUT/'public/participant_prompt.txt').write_text(prompt,encoding='utf-8')
    save(OUT/'protocol.json',{'cases':24,'levels':{'easy':8,'hard':8,'human':8},'design':'Focused repair pilot, shared counterexample templates; not independent24 journeys',
        'delivery_case':'easy/E02','positive_cases':9,'negative_cases':15,'known_fixture_cases':3,'real_conditional_positive_cases':6,
        'generation':'Direct LLM semantic decisions and full plan serialization, followed by separately-labelled deterministic safety projection',
        'frozen_now':corpus['captured_at'],'execution_confirmation_is_not_policy_acceptance':True})
    paths=[p for p in (OUT/'public').rglob('*') if p.is_file()]+[OUT/'private/cases.json',OUT/'protocol.json',ROOT/'src/shorttrip/retrieval_guard.py',Path(__file__)]
    save(OUT/'private/freeze.json',{'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    print(json.dumps({'cases':len(cases),'positive':sum(c['expected_policy_accepted'] for c in cases),'negative':sum(not c['expected_policy_accepted'] for c in cases)}))
if __name__=='__main__':main()
