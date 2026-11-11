"""Freeze real expansion-gap tasks and a multi-city schema before participation."""
import hashlib,json,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.retrieval_benchmark import VERSION,schemas
from shorttrip.env import get_env
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if OUT.exists():raise FileExistsError('P24 already prepared; preserve original trial')
    dbpath=ROOT/'data/business_catalog_v1_7_20261023T021649Z/catalog.sqlite3'
    db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
    allrows=[(json.loads(r[0]),json.loads(r[1])) for r in db.execute("select payload,gate from records where kind='attraction' order by city,id")]
    cities=sorted({r['city'] for r,g in allrows});official=get_env('zh')
    preferred={'长沙':'overture:dbff3d67-d928-4b8e-a90e-92a853af0c27','厦门':'overture:f107cf72-41d7-4eb5-805b-14d5e5645cad',
        '西安':'overture:82bd76b3-ece6-4e15-8ad7-c229208d27d6','昆明':'overture:770db114-4284-4218-bbfc-d2a27173c93c',
        '宁波':'overture:a0b73b34-359b-4285-8999-306c366e65d3','海口':'overture:59c3bd14-c203-45f5-8639-debdfc9a3be8'}
    chosen={};queries=[];labels=[]
    def card(r,g):
        return {'entity_id':r['record_id'],'name':r['name'],'city':r['city'],'kind':r['kind'],'data':r['data'],
                'source_url':r['source_url'],'observed_at':r['observed_at'],'entity_verified':r['entity_verified'],
                'coordinate_system':r['coordinate_system'],'missing_fields':g['missing_planning_fields'],
                'planning_blockers':g['planning_blockers'],'tags':r['tags'],'dataset':'expansion_discovery'}
    def req(target,city,field,**ctx):return {'target_id':target,'city':city,'field':field,'context':ctx}
    for index,city in enumerate(cities,1):
        options=[(r,g) for r,g in allrows if r['city']==city and g['missing_planning_fields']]
        if not options:raise ValueError('No natural-gap record in '+city)
        r,g=next(((r,g) for r,g in options if r['record_id']==preferred.get(city)),options[0]);chosen[city]=(r,g)
        uid=f'N{index:02d}';date='2026-10-24';route='route:anchor:'+city+'>'+r['record_id']
        requirements=[req(r['record_id'],city,'price',travel_date=date),req(r['record_id'],city,'opening_hours',travel_date=date),
            req(r['record_id'],city,'identity'),req('weather:'+city,city,'weather_forecast',travel_date=date),
            req(route,city,'route_duration',travel_date=date,departure_at=date+'T09:00:00+08:00',mode='metro'),
            req(route,city,'route_fare',travel_date=date,departure_at=date+'T09:00:00+08:00',mode='metro')]
        requirements[0]['entity_required']=True
        q={'schema_version':VERSION,'uid':uid,'nature_language':f'2026年10月24日两人在{city}市内游览{r["name"]}。计划09:00从市中心待核验起点出发，18:00前结束，主要乘地铁。请核实实体、开放时段、两人门票、天气与到达交通；未知值不要猜。城市起点尚无精确坐标，应说明交通核验受什么信息阻碍，给出可修改的候选计划。',
            'people_number':2,'city_sequence':[city],'dates':[date],'candidates':[card(r,g)],'requirements':requirements,'retrieval_budget':6}
        queries.append(q);labels.append({'uid':uid,'natural_missing_fields':g['missing_planning_fields'],'no_artificial_masking':True,'record_id':r['record_id']})
    pairs=[('武汉','长沙'),('上海','厦门'),('北京','西安'),('成都','昆明'),('杭州','宁波'),('广州','海口')]
    for i,(old,new) in enumerate(pairs,1):
        r,g=chosen[new];base=next(q for q in queries if q['city_sequence']==[new]);requirements=json.loads(json.dumps(base['requirements']).replace('2026-10-24','2026-10-25'))
        table=official.attraction_table(old);o=table.iloc[0].to_dict();oldid='legacy:'+old+':'+str(o['id']);link='leg:'+old+'>'+new
        requirements.extend([req(link,new,'intercity_schedule',travel_date='2026-10-24',origin=old,destination=new),req(link,new,'intercity_fare',travel_date='2026-10-24',origin=old,destination=new)])
        q={'schema_version':VERSION,'uid':f'M{i:02d}','nature_language':f'两人10月24日在{old}游览{o["name"]}，随后前往{new}，25日游览{r["name"]}。请串联新旧城市，跨城方式未限定；核对真实班次和价格、25日景点与地铁接驳及天气。住宿自理且不纳入本次规划范围。旧城沙盒数值只能注明冻结沙盒，不能移植为新城或现实报价。没有班次或坐标证据时保留待定连接，切勿编造车次。',
            'people_number':2,'city_sequence':[old,new],'dates':['2026-10-24','2026-10-25'],
            'candidates':[{'entity_id':oldid,'name':o['name'],'city':old,'kind':'attraction','data':o,'dataset':'legacy_frozen_sandbox','real_world_verified':False},card(r,g)],
            'requirements':requirements,'retrieval_budget':8}
        queries.append(q);labels.append({'uid':q['uid'],'natural_missing_fields':g['missing_planning_fields'],'no_artificial_masking':True,'record_id':r['record_id'],'old_city':old,'new_city':new})
    db.close()
    for name,schema in schemas().items():save(OUT/'public/schemas'/(name+'.schema.json'),schema)
    save(OUT/'public/queries.json',queries);save(OUT/'private/gap_audit.json',labels)
    sample=[next(q for q in queries if q['city_sequence']==[new]) for old,new in pairs]+[q for q in queries if q['uid'].startswith('M')]
    batches=[[sample[0],sample[3],sample[6],sample[9]],[sample[1],sample[4],sample[7],sample[10]],[sample[2],sample[5],sample[8],sample[11]]]
    for i,b in enumerate(batches,1):save(OUT/f'public/batch_{i}.json',b)
    prompt='''你是被测旅行规划LLM，直接生成完整plan，不用确定性编译器代写。仅可读指定 public/batch_N.json、public/schemas/plan.schema.json 以及本prompt；禁止读private、评分器、其他实验答案或实现；不要联网或调用API，不读模型凭据。\n先按静态候选完成static阶段，所有待核实要求在gaps逐项表达，并给出有预算的retrieval_requests。未知数量为{value:null,status:"unknown",evidence_ids:[]}，计划时刻是安排，不代表已核实开放或路线。参考数据不能变成verified，旧城市sandbox值需注明sandbox。start_city=city_sequence[0]；逐日city与dates匹配。mixed第一天末安排type=transfer且start_city/end_city明确，但班次/时刻只是待定计划，不编车次。\n每个requirement用target_id+field表示同一个缺口，request应精确带对应context。建议同目标的price/opening_hours一并请求operator；天气amap；路线缺少精确起点/GCJ02坐标应说明不可执行，不能捏造数值。可以写request让gateway返回不可用。最多预算见query。\n活动必须引用候选entity_id和原名；新城必选景点安排为暂定时段。price为每人价，cost为人数总额；都允许unknown。住宿自理不另加虚构酒店。\n输出每批四份plan的JSON列表到指定participants/batch_N_static.json，另把简短选择/未决项写在同目录notes。不要输出长推理。后续dynamic时你将只得到自己的上一版和实际request响应；要逐条反馈use/reject/defer及受影响activity_id，修改相应时段/费用并保持没有新证据的缺口。返回你的文件路径即可。'''
    (OUT/'public/participant_prompt.txt').write_text(prompt,encoding='utf-8')
    protocol={'at':datetime.now(timezone.utc).isoformat(),'suite_queries':len(queries),'new_cities':cities,'new_city_count':len(cities),
        'mixed_routes':pairs,'llm_queries':len(sample),'llm_uids':[q['uid'] for q in sample],
        'design':'Real native missing fields, no masking; static -> model requests -> captured evidence replay -> direct LLM revision',
        'official_compatibility':'Retains activity vocabulary, price/cost multiplicity and daily itinerary; extended unknown/provenance/multicity schema is not original official scoring',
        'baseline_db':str(dbpath.relative_to(ROOT)),'baseline_sha256':digest(dbpath),
        'not_preregistered_science':'New engineering protocol frozen before participants; no random sample or generalization claim',
        'network_budget':{'amap':6,'operator_pages_max':8,'search_queries_max':8},
        'limits':['12 LLM cases not full 36-query suite','Role isolation not OS sandbox','No current intercity ticket inventory source','No invented precise route anchors'],
        'independent_checks':'schema + ordering/city links + evidence safety + field gap/request/feedback metrics, no aggregate binary travel success substitution'}
    save(OUT/'protocol.json',protocol)
    paths=list((OUT/'public').rglob('*'))+[OUT/'protocol.json',OUT/'private/gap_audit.json',ROOT/'src/shorttrip/retrieval_benchmark.py',Path(__file__)]
    save(OUT/'private/freeze.json',{'files':{p.relative_to(ROOT).as_posix():digest(p) for p in paths if p.is_file()}})
    print(json.dumps({'suite':len(queries),'llm':len(sample),'batches':[[q['uid'] for q in b] for b in batches]},ensure_ascii=True))
if __name__=='__main__':main()
