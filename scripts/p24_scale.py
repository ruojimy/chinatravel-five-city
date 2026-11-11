"""User-requested level/volume amendment, before any participant receives tasks."""
import copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import schemas
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    assert not (OUT/'participants').exists(),'Scale before any participant output'
    original=read(OUT/'public/queries.json');protocol=read(OUT/'protocol.json')
    save(OUT/'private/pre_scale_protocol.json',protocol);save(OUT/'private/pre_scale_freeze.json',read(OUT/'private/freeze.json'))
    levels={x:[] for x in ('easy','hard','human')};full=[]
    for level in levels:
        for i,base in enumerate([q for q in original if q['uid'].startswith('N')],1):
            q=copy.deepcopy(base);q['uid']=level[0].upper()+f'{i:02d}';q['level']=level
            entity=q['candidates'][0];city=entity['city'];name=entity['name'];date=q['dates'][0]
            if level=='easy':
                q['requirements']=[r for r in q['requirements'] if r['field'] not in ('route_duration','route_fare')]
                q['nature_language']=f'{date}，两人已经到达{city}的{name}入口，请安排一段参观。查清是否认对实体、几点开放、两人门票多少钱和当天的天气。给出计划时段和价格来源，信息缺失或旧了就提出检索；不需要市内或城际交通。'
                q['retrieval_budget']=4
            elif level=='hard':
                q['nature_language']+= '两人门票加地铁交通上限300元；只采用目标日期、目标实体的证据。其他城市或不同门店的数字不能替代，参考报价不能当已订票。'
                q['retrieval_budget']=6
            else:
                phrases=[f'我和家人这周末想去{city}的{name}看看，不想太赶。两个人门票和地铁尽量控制在200块，天气不适合时请提醒。早上9点从市中心出发，具体地址还没定。资料不全的话，先说还得查什么、我还需提供什么，再给可调整的安排。',
                    f'我们俩想在{date}去{city}逛{name}。上次看到的票价不一定准，别按记忆报数；希望查一下开门和天气，坐地铁，起点我稍后给。200元左右够不够？先留好没确认的地方。',
                    f'{date}和朋友两人去{city}，主要看{name}。想上午出发、主要坐地铁，市中心出发点还没确定。别太折腾，门票交通预算200元。请查近期能用的资料，碰到票种、实体或时间矛盾时告诉我影响。']
                q['nature_language']=phrases[(i-1)%3];q['retrieval_budget']=6
            # Wrong-city distractors are unmodified records, not synthetic facts.
            distractor=original[i%30]['candidates'][0]
            if level!='easy' and distractor['city']!=city:q['candidates'].append(copy.deepcopy(distractor))
            q['requirements'][0]['entity_required']=True
            full.append(q)
    for i,base in enumerate([q for q in original if q['uid'].startswith('M')]):
        level=list(levels)[i//2];q=copy.deepcopy(base);q['uid']=level[0].upper()+f'{31+i%2:02d}';q['level']=level
        if level=='human':q['nature_language']='和朋友两个人想这样玩：'+q['nature_language']+'没证实的票和时间别写死；请说清有什么信息需要我补充。'
        full.append(q)
    for q in full:
        public={k:v for k,v in q.items() if k!='requirements'};levels[q['level']].append(public)
    save(OUT/'private/queries_96.json',full)
    for level,queries in levels.items():save(OUT/'public/levels'/(level+'.json'),queries)
    schema=schemas()['query'];schema['required'].remove('requirements');schema['properties'].pop('requirements');schema['properties']['level']={'enum':list(levels)}
    save(OUT/'public/schemas/query.schema.json',schema)
    protocol.update(suite_queries=96,llm_queries=96,levels={k:len(v) for k,v in levels.items()},
        llm_uids=[q['uid'] for q in full],human_provenance='Researcher-authored human-style new-city requests, not a collected human dataset',
        participant_scope='All96 tasks: 30 new-city singles and 2 old/new chains per level; three LLM participants',
        gap_labels='requirements exist only under private; participants infer gaps from public NL and real candidate fields',
        limits=['96 authored benchmark tasks, not all possible journeys','Role isolation not OS sandbox','No current intercity inventory source','Ambiguous origin coordinates intentionally remain unresolved, not fabricated'])
    save(OUT/'protocol.json',protocol)
    prompt=(OUT/'public/participant_prompt.txt').read_text(encoding='utf-8')
    prompt=prompt.replace('public/batch_N.json','public/levels/LEVEL.json').replace('每批四份plan','每层32份plan').replace('participants/batch_N_static.json','participants/LEVEL_static.json')
    prompt+='''\n追加规模约定：你负责指定层32题。public没有隐藏requirements，必须从自然语言与候选字段自己识别缺口。gap/request target_id约定：实体字段用候选entity_id；天气用weather:城市；市内路线用route:anchor:城市>实体ID；城际用leg:起城>终城。日期放context.travel_date。市内路线context同时含departure_at=出行日T09:00:00+08:00,mode=metro；跨城context含origin/destination/travel_date（24日）。身份identity不用日期。价钱price指成人每人门票；opening_hours为开放时段。未知精确起点导致路线不能执行，是应报告的缺口，不是造坐标的理由。\n可以用Python作JSON序列化和结构复用，但每题的实体、时段、状态、缺口识别、请求、理由和后续证据动作应由你逐题作出，不能调用现成planner/评分器。单城只安排候选中的本城目标景点；干扰候选不等于需加入行程。严格按query日期/人数/城市排序。首稿只用static；后续dynamic读取自己的首稿及gateway响应，直接输出修订plan。可以分批构造并在工作文件中记录逐题决策，最终32题UID必须齐。'''
    (OUT/'public/participant_prompt.txt').write_text(prompt,encoding='utf-8')
    files=[p for p in (OUT/'public').rglob('*') if p.is_file()]+[OUT/'private/queries_96.json',OUT/'protocol.json',ROOT/'src/shorttrip/retrieval_benchmark.py',Path(__file__)]
    save(OUT/'private/freeze.json',{'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'amendment':'User requested easy/hard/human96 before first participant; original36 preparation retained separately'})
    print(json.dumps({'levels':protocol['levels'],'total':96}))
if __name__=='__main__':main()
