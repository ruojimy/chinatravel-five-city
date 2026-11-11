"""Freeze three selected episodes before new source capture. Never edit P24/P25."""
import copy,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_guard import schema,VERSION
OUT=ROOT/'results/p27_focused_deep_retrieval'
def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    if (OUT/'private/freeze.json').exists():raise FileExistsError('Preserve the selected cases')
    qs=json.loads((ROOT/'results/p24_dynamic_feedback/private/queries_96.json').read_text(encoding='utf-8'))
    chosen=[('easy','E20',12),('hard','H08',18),('human','H29',18)]
    rows=[]
    for level,uid,cap in chosen:
        original=next(q for q in qs if q['level']==level and q['uid']==uid)
        q=copy.deepcopy(original);q['schema_version']=VERSION
        q['retrieval_budget']=cap
        q['uid']='P27-'+level
        public={k:v for k,v in q.items() if k!='requirements'}
        public.update(experiment_scope='Three focused episodes, max3 source-feedback rounds; preserve unknown origin until explicit clarification. No private labels/old results permitted.',max_source_requests=cap,max_rounds=3)
        save(OUT/'public'/level/'query.json',public)
        save(OUT/'private'/level/'original_query.json',original)
        save(OUT/'private'/level/'query.json',q)
        rows.append({'level':level,'original_uid':uid,'uid':q['uid'],'city':q['city_sequence'][0],
                     'target_entity':q['candidates'][0]['entity_id'],'source_request_cap':cap,
                     'original_query_sha256':hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True).encode()).hexdigest()})
    save(OUT/'public/plan.schema.json',schema())
    prompt='''你是被测LLM。只读本目录public/LEVEL/query.json、public/plan.schema.json、自己的participants/LEVEL/已保存稿，以及根代理后续明确开放的responses/LEVEL/文件。禁止读private、capture、实现、旧实验、其他参与者；不要联网或调用API，不读评分和隐藏标签。根代理执行你提出的检索并返回原始证据及字段权限。
逐轮输出完整v2 plan，保存participants/LEVEL/round0.json等，初稿stage=static后续dynamic。所有语义、时段、取舍、缺口和反馈由你决定；可用Python序列化，禁止调用现成规划器。quantity的unknown必须value=null、evidence_ids=[]。price为每人，cost为组总额；交通price/票数/总额区分。可行时允许conditional，不声称已预约或保证执行。
首轮识别身份、票价、营业、天气以及任务要求的路线缺口，不按记忆补数字。起点不精确就提出澄清，不能私自选地铁站。日期、城市、实体必须原样；实体名用候选的canonical name，说明写reason而非position。反馈affected_ids必须是自己的activity_id。额外输出decision_round0.json含本轮每个请求的具体检索词/来源类型、依赖前提、期待改变的决策，以及集中澄清项；后续decision_roundN.json记录使用/拒绝/未解决及是否需下一轮。不要读未开放回包，不评价自己通过率。
每次收到回包后先核entity/date/单位/价格范围/最晚入场。对返回证据逐项use/reject/defer；不要将request_id当evidence_id。已知不同日期/错误实体的数值不得复制。评估天气是否要改时段或方案，无法解析偏好要说明。两人门票+交通预算按题；不加未要求餐饮住宿，也不编0元填缺口。方案和决策文件都需写入，勿改旧稿。'''
    (OUT/'public/participant_prompt.txt').write_text(prompt,encoding='utf-8')
    save(OUT/'private/freeze.json',{'at':datetime.now(timezone.utc).isoformat(),'cases':rows,
        'selection_rationale':'Haikou first full identity/operational chain on a museum; Xiamen botanical garden with transit; Changsha prior entity with a different origin as positive-control replication, not a new independent city discovery.',
        'max_source_requests':48,'max_amap_calls':20,'max_feedback_rounds':3,
        'source_counting':'Each requested search query or page open or actual HTTP/API attempt counts1; tool calls and evidence-field rows are reported separately; deduplicated cache replay is not new HTTP.',
        'clarification_policy':'Do not infer missing original origins. Score original unchanged separately. After round1 provide explicitly labelled researcher-supplied origin/time variants; never count those as unmodified original solves.',
        'conditional_policy':'Reference operator price/opening rules may support a clearly conditional proposal; inventory remains unconfirmed. Identity and route numeric context remain strict.',
        'no_key_rotation':True,'no_resume_previously_paused_sources':True})
    print(json.dumps(rows,ensure_ascii=False))
if __name__=='__main__':main()
