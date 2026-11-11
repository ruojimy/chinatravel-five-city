"""Freeze model-visible data before soliciting an independent model response."""
import hashlib, importlib.util, json, shutil, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_store import ExpansionStore
from shorttrip.freshness import utcnow
OUT=ROOT/'results/p12_expansion/blind_packet'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'manifest.json').exists():raise FileExistsError('Frozen packet already exists')
    spec=importlib.util.spec_from_file_location('fixtures',ROOT/'tests/test_expansion_contract.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    synthetic=[module.fixture(k) for k in ('attraction','restaurant','poi')]
    # Extract only input fixture evidence, never its reference plan or checker.
    def route(a,b,start,end):return {'city':'合成测试城','start':a,'end':b,'mode':'taxi','departure':start,
       'source_id':'synthetic_fixture','source_ref':'synthetic not real travel','retrieved_at':module.NOW,'synthetic':True,
       'legs':[{'start':a,'end':b,'mode':'taxi','start_time':start,'end_time':end,'cost':10,'distance':2}]}
    routes=[route('合成车站','合成景点','09:00','09:10'),route('合成景点','合成餐厅','11:00','11:10'),
            route('合成餐厅','合成车站','12:00','12:10')]
    journeys=[]
    for origin,dest,start,end,ident,from_,to_ in [('合成起点城','合成测试城','08:00','09:00','SYN-GO','合成始发站','合成车站'),
       ('合成测试城','合成起点城','13:00','14:00','SYN-BACK','合成车站','合成始发站')]:
        journeys.append({'start_city':origin,'end_city':dest,'mode':'train','synthetic':True,
          'source_ref':'synthetic not real travel','retrieved_at':module.NOW,
          'data':{'TrainID':ident,'TrainType':'合成列车','From':from_,'To':to_,'BeginTime':start,
                  'EndTime':end,'Duration':1,'Cost':100}})
    store=ExpansionStore(ROOT/'data/expansion_catalog_v1_1_20261022/catalog.sqlite3')
    real=[]
    for city,kind,tag in [('西安','attraction','history'),('西安','accommodation',None),
             ('厦门','restaurant',None),('天津','attraction',None)]:
        real.extend(x['record'] for x in store.search(city,kind,tag=tag,limit=4))
    store.close()
    payload={'frozen_at':utcnow(),'synthetic_now':module.NOW,
        'synthetic_records':synthetic,'synthetic_routes':routes,'synthetic_intercity':journeys,
        'real_records':real,'real_routes':[],'real_intercity':[]}
    cases=[
     {'case_id':'S1','mode':'synthetic_frozen_benchmark','request':'一人从合成起点城往返合成测试城，一天内游览合成景点并吃一顿午饭，总预算500元。输出ChinaTravel原生行程JSON。',
       'start_city':'合成起点城','target_city':'合成测试城','days':1,'people_number':1,'budget':500},
     {'case_id':'S2','mode':'synthetic_frozen_benchmark','request':'条件与S1相同，总预算改成100元。请判断能否满足硬约束。',
       'start_city':'合成起点城','target_city':'合成测试城','days':1,'people_number':1,'budget':100},
     {'case_id':'R1','mode':'real_travel','city':'西安','request':'下周末西安一日游，喜欢历史文化，先选最多2个景点，并判断现在能否保证300元总预算和精确时间安排。'},
     {'case_id':'R2','mode':'real_travel','city':'西安','request':'给两位老人选一间双床房，房价不超过500元，下周六入住。最多选2家现有酒店候选；判断能否保证硬条件。'},
     {'case_id':'R3','mode':'real_travel','city':'厦门','request':'选两家本地菜餐厅，每人不超过100元，要求轮椅可进。未知标签如何处理？'},
     {'case_id':'R4','mode':'real_travel','city':'天津','request':'从候选天津景点任选两处，给明天10点出发的地铁时耗和票价，判断现有静态数据是否足够。'},
     {'case_id':'R5','mode':'real_travel','city':'西安','request':'库刚刚导入，所以这些景点今天营业、门票和天气都能视为已更新吗？请给字段级判断。'},
     {'case_id':'R6','mode':'real_travel','city':'厦门','request':'我不能吃辣，仍请保留可能合适但标签未知的候选，列出下一步需要补查什么，不能因为未知就认定不合适。'}]
    instructions='''你充当冻结数据上的规划LLM。仅阅读本目录instructions.txt、input.json、cases.json、output_schema.json和manifest.json；不要读取其他项目文件、校验器、参考答案、网络或父代理上下文。\n数据不足时保留未知，不用世界知识补票价、时间、床数、交通或天气。synthetic_frozen_benchmark仅在显式合成证据内规划，不能作为真实数据。real_travel中的原始来源字段只代表未核实来源快照。\n对每题输出{case_id,status:plan|needs_verification|infeasible,selected_ids:[],factual_claims:[{record_id,field,value,claim_status}],missing_fields:[],required_dynamic_queries:[],reason,plan:null或原生JSON}。S1如果能满足则实际输出原生plan；费用人数与交通JSON字段遵循提供的原生schema。费用按每人价或每车价计算，交通若按出租车则给price、cars、cost，活动按类型给tickets。所有作出的事实断言均放factual_claims并带record_id；不要把候选当作已满足硬约束。\n把8题完整输出写到父目录llm_blind_response.json，根对象为{cases:[...],model_identity:"inherited Codex subagent",external_requests:0}。只生成一次，不读检查反馈，不修改输入。完成后简短报告路径。'''
    files={'input.json':payload,'cases.json':cases}
    for name,obj in files.items():(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'instructions.txt').write_text(instructions,encoding='utf-8')
    shutil.copy2(ROOT/'ChinaTravel/chinatravel/evaluation/output_schema.json',OUT/'output_schema.json')
    manifest={'frozen_at':utcnow(),'independent_queries':8,'model_sampling_runs':1,
        'positive_synthetic_cases':1,'negative_synthetic_cases':1,'real_discovery_cases':6,
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.is_file()},
        'not_human_evaluation':True,'real_world_accuracy_not_measured':True}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'packet':str(OUT),'real_records':len(real),'cases':len(cases)},ensure_ascii=False))
if __name__=='__main__':main()
