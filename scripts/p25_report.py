"""Write the repaired witness and the requested cross-schema Markdown report."""
import copy,hashlib,json,sys
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_guard import evaluate,schema
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def md(p,s):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s.strip()+'\n',encoding='utf-8')
def main():
    rows=[r for l in ('easy','hard','human') for r in read(OUT/'evaluations'/(l+'.json'))];regress=read(OUT/'regression/results_96.json')
    bylevel={l:{'cases':8,'accepted':sum(r['guarded_check']['policy_accepted'] for r in rows if r['level']==l),
        'correct':sum(r['outcome_correct'] for r in rows if r['level']==l),'safe':sum(r['guarded_check']['safe'] for r in rows if r['level']==l)} for l in ('easy','hard','human')}
    corpus=read(OUT/'real/corpus.json');query=next(c['query'] for c in read(OUT/'private/cases.json') if c['level']=='easy' and c['uid']=='E02')
    plan=read(OUT/'guarded/easy/E02.json');delivery=next(r for r in rows if r['level']=='easy' and r['uid']=='E02')
    assert delivery['guarded_check']['policy_accepted'] and not delivery['guarded_check']['execution_confirmed']
    save(OUT/'DELIVERABLE.json',{'query':query,'plan':plan,'assessment':delivery['guarded_check'],'evidence_capture_at':corpus['captured_at'],
        'selection':'easy/E02 fixed before participant output, see protocol','factual_reservation_confirmed':False})
    times={e['field']+(':'+e['evidence_id'].split(':')[1] if e['field'].startswith('route_') else ''):e['value'] for e in corpus['evidence']}
    summary={'levels':bylevel,'new_llm_cases':24,'new_llm_plans':48,'positive_expected':9,'negative_expected':15,
        'correct_classifications':sum(r['outcome_correct'] for r in rows),'accepted':sum(r['guarded_check']['policy_accepted'] for r in rows),
        'raw_accepted':sum(r['raw_check']['policy_accepted'] for r in rows),'raw_safe':sum(r['raw_check']['safe'] for r in rows),
        'guarded_safe':sum(r['guarded_check']['safe'] for r in rows),'execution_confirmed':sum(r['guarded_check']['execution_confirmed'] for r in rows),
        'fixture_cases':3,'real_conditional_positive_cases':6,
        'deliberate_mutations':{'invalid_low_price_cases':3,'identity_level_downgrade_cases':3,'scope':'Artificial counterexamples over captured data; not observed provider errors'},
        'prior96':{'raw_safe':sum(r['raw_v2_check']['safe'] for r in regress),'guarded_safe':sum(r['guarded_check']['safe'] for r in regress),
            'still_unaccepted':sum(not r['guarded_check']['policy_accepted'] for r in regress),'changed_cases':sum(bool(r['edits']) for r in regress),
            'new_llm_calls':0,'explanation':'Deterministic safety/serialization projection, not96 new LLM tests or restored travel completion'},
        'api_calls':corpus['live_calls'],'delivery_projected_cny':92,'delivery_budget_cny':200,'delivery_paid_total':None,
        'delivery_policy_accepted':True,'delivery_execution_confirmed':False,'capture_at':corpus['captured_at'],
        'amendments':'Field policy and output normalization evolved during integration; same24 examples, no held-out generalization claim'}
    refresh=read(ROOT/read(OUT/'DELIVERABLE_LATEST.json')['receipt']) if (OUT/'DELIVERABLE_LATEST.json').exists() else None
    if refresh:summary.update(api_calls=corpus['live_calls']+refresh['api_calls'],initial_capture_api_calls=corpus['live_calls'],delivery_refresh_api_calls=refresh['api_calls'],delivery_latest_at=refresh['at'])
    save(OUT/'summary.json',summary)
    save(OUT/'mutation_audit.json',{'cases':[{'level':c['level'],'uid':c['uid'],'kind':c['kind'],
        'mutation':'root-injected5CNY with unchanged40CNY source and explicit rejection flag' if c['kind']=='distractor_price' else 'root-downgraded identity level verified to estimate',
        'observed_provider_error':False} for c in read(OUT/'private/cases.json') if c['kind'] in ('distractor_price','identity_estimate')],
        'purpose':'Eligibility/field-policy regression, not evidence of real operator misinformation or blind semantic attack detection'})
    md(OUT/'DELIVERABLE.md',f'''# 可交付结果：两人长沙半日条件方案

**出行日：2026-10-24；两人；门票与往返地铁费用投影92元，预算200元。** 不含餐饮、住宿，不安排参观湖南省博物馆，仅将其已核对入口作为集合点。

| 时间（北京时间） | 安排 | 已知依据 |
|---|---|---|
| 13:00 | 湖南省博物馆正门集合，按已核对入口GCJ02坐标出发 | 高德POI B02DB00018 |
| 13:00–14:00 | 以地铁为主前往岳麓书院入口 | 本轮API估计48.5分钟；排60分钟，留11.5分钟余量 |
| 14:00–16:00 | 岳麓书院参观 | 运营方10月发布规则参考覆盖该时段；普通成人票40元/人参考 |
| 16:00–17:15 | 原方向反向返程，回同一博物馆入口 | 本轮API估计46.4833分钟；排75分钟，留28.5167分钟余量 |
| 17:15–18:00 | 返回集合点后的缓冲 | 计划18:00前返回，API估计不构成到达保证 |

| 费用项 | 两人金额 | 状态 |
|---|---:|---|
| 岳麓书院成人普通门票 | 40×2＝80元 | 发布参考，未购票 |
| 去程地铁 | 3×2＝6元 | 高德估计 |
| 返程地铁 | 3×2＝6元 | 高德估计，已计入总额 |
| 合计 | **92元** | 费用投影，非已支付账单 |

相对200元预算余108元，可作为调价/接驳余量；它是预算余量，不是供应商承诺。24日高德预报为多云、白天22℃/夜间16℃，仅按捕获快照准备，出发前重查。

## 执行前必须完成

1. 通过岳麓书院官方渠道预约/购票，核实24日14:00时段、票价和开放安排；**尚未确认有票**。未成功就不执行本方案，改期或重新检索替代项。
2. 出发前重新查询天气和13:00/16:00双向地铁；本轮交通数值是估计，不能保证指定未来时刻班次和到达。
3. 复核地图入口、路线步行接驳和实际票价；若交通窗口或200元预算不满足，重新规划。

## 核验收据

原始证据捕获于 `{corpus['captured_at']}`。路线耗时快照有效期至2026-10-23 **15:52:49/15:52:52（北京时间）**，票价至16:07:49/16:07:52，天气至16:32:02；这是信息过期边界，**不是允许跨到出行日继续当实时数据的承诺**。

本方案在捕获时刻通过字段来源、身份映射、人数乘数、双向方向/出发时间、交通窗口、停止入馆时间和预算检查，`policy_accepted=true`；因预约尚未完成且价格/交通含参考与估计，`execution_confirmed=false`。已核对的是供应商POI身份绑定，不宣称独立实地认证。

公开来源：[岳麓书院在线订票说明](https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm)。地图/天气原始结构化响应和哈希见本目录real/，机器方案与检查结果见DELIVERABLE.json。固定交付案例为预先指定的easy/E02；不是用隐藏评分逐题拼接最优答案。
''')
    md(OUT/'REPORT.md',f'''# P25 修复结果

2026-10-23。保留P23/P24归档，新建字段门与输出规范层 `src/shorttrip/retrieval_guard.py`。分开“格式合法”“证据可用”“条件方案可接受”“执行已确认”，不靠放宽未知值把旧0/96改成旅行成功。

## 已修复

- 身份/库存/房型/班次要求验证级别，不能由estimate直接满足；真实身份检查引用的POI ID、名称、城市确实在保存响应中，合成fixture另标识，不能用来证实现实。
- 天气/路线必须提供方、日期/方向/坐标系/出发时刻匹配，有观察时钟和有效期；路线每人价、人数总额、票数、返回anchor交通及缓冲均检查。
- 预算为实际分项投影之和；任一金额未知则预算unknown，已知部分超上限即拒绝；decision额度不当报价。
- 发布参考只有在任务明确允许条件方案时支持policy acceptance；库存仍为执行前提，不升级verified或已订票。
- eligibility随回包给LLM。无坐标回needs_clarification/invalid_context；无城际适配器明确受阻，不白查或编班次。
- 规范层只按显式entity_id、精确唯一名称/入口别名规范position/路线端点/affected_ids；不会模糊匹配其他实体，不改城市/计划时段、不填新价格。原稿和所有变更审计保留。

## 验证

原96题重放：来源状态无误从90/96到96/96；这是程序门与输出规范层的投影，0次新LLM调用。6份原有来源错误被清空/暂缓，另有格式规范化；仍96/96不满足完整接纳条件，没有伪造身份/路线补全。

新增24题，每层8题，三子代理完成48份首/动态稿；同一真实长沙快照加明确合成正例及失效/缺字段/超预算反例，不是24个独立旅行问题。预先9正例、15负例；流水线正确分类24/24（每层8/8），条件/测试接纳9/24（每层3/8），包含3个合成工程正例、6个真实快照条件正例。执行确认0/24。

未经规范层的原始LLM稿接纳0/24，主要把备注塞入position、把entity/route/weather键写到affected_ids、用名称而非稳定ID表示路线；这造成接口检查失败，不能冒称LLM原生24/24。规范层修复这些显式ID映射；hard还将无返回请求说明写作evidence反馈，现转存审计而不伪造证据。所有原稿、原始评分与修改条目可查。初次集成还暴露环境中官方库路径依赖，已用本地时钟解析替代，19项阶段回归随后扩至21项通过。

本轮真实新增3次高德调用（天气1、双向地铁2），不更换Key。可靠交付见DELIVERABLE.md：两人门票80＋双向地铁12＝92元，预算200；14–16点参观，17:15暂定返回。预约和出发前再核验是显式前提，并非执行成功。

## 实验边界

规则在集成过程中演进，非完全预注册；24题固定模板有关联，没有独立留出集。已知fixture只证明实现存在可通过正例，不能拿合成值填真实库。旧96题语料上限仍40/528；酒店/餐饮库存、多城市真实班次、天气/舒适偏好的全面语义判定仍待补。证据/字段满足策略和数值/时段错误已可阻断，但不保证任意自然语言均被正确解析。

总结报告：`报告/17_ChinaTravel原生与扩展Schema测试总结及修复报告.md`。本轮结果没有覆盖或改写P21/P22/P23/P24历史归档。
''')
    md(ROOT/'报告/17_ChinaTravel原生与扩展Schema测试总结及修复报告.md',f'''# ChinaTravel原生与扩展Schema测试总结及修复报告

日期：2026-10-23（北京时间）。范围：P23官方冻结沙盒测试、P24扩容缺口测试及P25实际修复。报告区分结构正确、约束满足、证据可用和现实执行，不合并不同口径的通过率。

## 1. 结论

原ChinaTravel结构适合检查活动、交通和费用能否与冻结数据库一致；新增结构负责表达新城市的未知值、来源、跨城顺序及动态检索反馈。P23补检后118/150三关通过，证明在该抽样下补检＋重规划有用；P24虽192稿结构均合法，但真实语料只支持40/528字段，不能以0/96完整通过直接断言模型能力失败。

本轮已先修复再汇总：加入字段级证据权限、预算/返程计费、路线时刻/人数检查、显式ID规范化和可解正例。原96稿的来源错误由门控投影清除；新增24题正确区分9个可接受与15个应阻塞结果。交付一份长沙两人半日条件方案，费用投影92元；预约尚未完成，不标执行已确认。

## 2. 两类Schema及检查职责

| 项目 | ChinaTravel原Schema与官方评测 | 新增Schema及P25修复 |
|---|---|---|
| 行程结构 | 人数、起城、目标城、day/activities | 保留活动词汇，增加有序城市、每天日期/城市、稳定实体ID |
| 活动与交通 | 景点、三餐、住宿、train/airplane；交通起终点、方式、时间 | 增加anchor/待定transfer；方向、日期、实际出发时刻、GCJ02及余量检查 |
| 价格 | 数值price/cost，人数/房间乘数 | value＋status＋evidence_ids；unknown必须null；单价、总额、决策额度分开 |
| 缺失数据 | 必填数值缺失会使原格式失败 | 允许合法表示未知，但不能因此判定所有条件满足 |
| 城市串联 | 原单目标城结构 | 30新城、6条新旧城profile，显式起终城市对 |
| 反馈与证据 | JSON结构、commonsense、隐藏hard DSL分层 | gap/request/response/use-reject-defer；字段权限、来源与数量对应 |
| 最终结论 | 冻结环境三关全通过 | schema/protocol/safe/policy_accepted/execution_confirmed分别输出 |

**Schema只是结构门。** 原评测的commonsense和hard DSL、新评测的证据/预算/时段规则均是额外语义检查；不能把“JSON合法”写成“旅行可靠”。原Schema仍应作为旧数据回归接口保留。

## 3. 原Schema测试：P23

### 3.1 全量程序基线

| 分割 | 带标签题数 | 程序生成 | 三关全通过 |
|---|---:|---:|---:|
| easy中文 | 300 | 297 | 90（30.0%） |
| medium中文 | 150 | 150 | 18（12.0%） |
| human中文 | 154 | 154 | 67（43.5%） |
| competition_test英文phase2 | 100 | 100 | 1（1.0%） |

合计704题是程序基线，不是704题LLM测试；另有human1000无本地隐藏标签，未评分。英文phase2不能混入中文LLM样本比较。

### 3.2 150题同题LLM混合对照

| 分割 | 题数 | 原程序 | 首轮LLM＋排程 | 补检＋重规划 | 再加成本修复 |
|---|---:|---:|---:|---:|---:|
| easy | 50 | 18 | 38 | 45 | 44 |
| medium | 50 | 4 | 41 | 42 | 41 |
| human | 50 | 21 | 30 | 31 | 30 |
| 合计 | 150 | 43 | 109（72.7%） | **118（78.7%）** | 115（76.7%） |

三个子代理各50题，LLM作语义与内容选择，确定性编译器负责官方表值和排程。补437条候选后30份intent改动；新增通过9题、退化0题。成本修复新增1题却破坏4题，因此已关闭。149/150有计划，已生成稿均通过schema/commonsense；剩余失败主要在hard DSL。

完整四组1154次评测不是1154个独立LLM任务。该测试读取官方冻结表，未系统加入扩容库干扰比例、错引来源或新旧实体混合池，**尚不能当作完整的扩容抗干扰/抗幻觉基准**。78.7%也不是现实可行率、官方榜单分数或纯LLM直接生成能力。

### 3.3 主要错误

32个未通过任务涉及：景点类别8、往返方式6、菜系5、酒店类别/设施4、预算3、指定景点2；市内方式、房间数、回程到达、出租车数量、构造失败各1，类别重叠共33次命中。例：只满足便宜目标会丢文化类别/泳池/SPA；把“17:00前到家”当成出发时间；家庭房、床型和房间数未完全编译。

部分human标签比原文更具体，五人出租车数量等存在标签/排程规则冲突；保留官方失败，不能改标签刷分。酒店插入失败的一题还有元数据5天与原文“一周”的歧义。下一步应分开语义解析、候选召回、排程与标签冲突，避免所有失败都归因于检索。

## 4. 新增Schema测试：P24

采用14,057实体的扩容快照，30城各选真实缺字段景点；30城×3层＝90单城题，加6条串联，共96题、192份首/动态稿。easy/hard/human各32题，human为研究者构造自然表达，非真人采样；同一批目标被三层复用，不能当96个独立信息需求。

| 层次 | 两阶段结构/城市时序 | 首稿来源状态无误 | 动态来源状态无误 | 获支持字段 |
|---|---:|---:|---:|---:|
| easy 32题 | 均32/32 | 32 | 31 | 15 |
| hard 32题 | 均32/32 | 32 | 31 | 12 |
| human 32题 | 均32/32 | 25 | 28 | 13 |
| 合计 | 均96/96 | 89/96 | 90/96 | **40/528** |

374次是捕获语料上的请求回放：43次返回、331次无可用结果，27题有证据；59条次全部有反馈。来源实际捕获是6次高德天气、8次页面打开尝试、4条搜索query，未称自主联网检索。40字段＝24天气估计＋16发布参考，0个verified硬事实；19条不可用证据15次正确拒绝/暂缓、4次误用。26稿对象变化包含引用和金额，实际时段/顺序修改0。

### 4.1 错误分类

| 问题 | 证据与影响 | 性质 |
|---|---|---|
| 元数据全等匹配 | 名称/人数等也要求来源逐项匹配，最初238请求全空 | 工具错误，修正前后回包均保留 |
| 引用被当已解决 | 历史开放规则、2024旧价被标reference，文字仍说未知 | 模型/状态接口错误 |
| 城际city歧义 | 起终城市对正确，却因单城标记被扣12字段 | 评分错误，516/528修正528/528，不是模型提升 |
| 来源与输入不足 | 69题无返回；起点不精确、缺真实城际源 | 信息/适配器瓶颈 |
| 预算/偏好检查不全 | P24未完整判预算、舒适度、天气应对和跨段真实可行性 | 评测覆盖缺口 |

### 4.2 本轮独立复核：0/96的可解性问题

重新枚举全部可用语料，而非只看模型请求，发现最大可支持字段仍为40；**96题都缺合格身份字段，现有语料不可能让任一题完整通过**。其他即使全读也缺：票价88、开放88、天气72、市内耗时66、票价66、城际班次6、城际费用6（按任务字段计，存在重复实体）。所以0/96同时反映设计上缺正例，不能拿它单独评价模型规划能力。

原v1还统一用estimate/verified判字段满足，没有按身份/库存/天气区分；这些语义问题已进入P25修复。结构全通过、来源无误、字段补全、完整计划应始终分别报告。

## 5. 已实际执行的修复：P25

1. **字段权限门**：身份、库存、床型、班次要求验证；estimate不能替代。地图身份只证明保存响应中的POI绑定，未宣称独立实地认证。reference可作条件方案依据，不能自动变成已核实事实。
2. **数值与预算门**：逐人票价×人数；双向交通含返程anchor；未知分项则预算未知，已知部分超限即拒绝。单价、总额、tickets、路线日期/方向/出发时间、缓冲、开放/最晚入馆分别检查。
3. **显式回包权限与澄清**：回包给can_resolve/max_status/reasons；缺坐标不发无效网络请求，缺城际适配器明确受阻。预算投影和执行前提不再混入“complete”。
4. **输出规范层**：按明确entity_id和精确唯一名称/入口别名整理字段；将反馈目标映射到真实activity_id。备注不再污染position，普通请求说明不伪装证据。原稿及每次机器修改保留，未知金额不凭空补数。

### 5.1 修复验证结果

| 验证组 | 数量 | 结果与正确解释 |
|---|---:|---|
| 原P24固定稿回放 | 96 | 门控/规范化后来源状态无误96/96，原为90/96；仍全不满足接纳，未造新事实；0次新LLM |
| 新分层修复试验 | 24题、48稿 | 每层8题；9正例＋15负例，流水线判定24/24符合预设；接纳9/24 |
| 正例构成 | 9 | 3个明确合成fixture＋6个真实快照条件正例，不能都叫现实成功 |
| 原始LLM输出 | 24动态稿 | 未经规范化接纳0；接口名/ID与备注混用。规范层后的成功是LLM＋规则系统结果 |
| 单元回归 | 21项新增门控＋23项原接口 | 结果见P25日志与核验收据；不以单元测试代替LLM测试 |

24题复用一份真实行程快照和反例模板，没有独立留出集，不能据24/24声称泛化成功。集成中修复了官方环境导入依赖以及名称/ID接口不一致，未把隐藏评分发给模型改答案；代码持续演进，非完全预注册。历史P21—P24均保留。

其中3题的5元低价、3题的身份等级降级为根侧人工变异，分别测试拒绝无权填值和禁止estimate自升verified；不是运营方真的给了5元价格，也不是无提示的恶意网页盲测。详见mutation_audit.json。

### 5.2 至少一份可靠交付

预先指定easy/E02，非评分后逐题挑最好方案。两人10月24日13:00从湖南省博物馆入口出发，14:00—16:00岳麓书院，暂排17:15返回。门票参考80＋去程6＋返程6＝**92元**，预算200；双向API估计48.5/46.4833分钟，安排60/75分钟窗口。该方案通过条件接纳检查，预约仍未确认，出发前须刷新天气/交通和核实票价开放，不能标执行已确认。

具体方案见 `results/p25_reliable_retrieval/DELIVERABLE.md`；其机器方案、逐字段检查与短有效期完整保留。可靠性来自来源和前提可核对、超预算/缺证据能阻断，不来自把所有unknown改成数值。

## 6. 下一步目标与验收

| 优先级 | 目标 | 验收方式 |
|---|---|---|
| P0 | 把已知可解/部分可解/必须澄清三类正式纳入扩容基准 | 公开任务前逐题做可解性审计，正例有独立见证；不再全负例地板 |
| P0 | 独立留出实体与模板，冻结后评测 | 保留96旧题回归；新集按实体/来源分组，避免同一目标换措辞造成泄漏 |
| P1 | 有预算的真实请求驱动检索，逐城补身份与适用字段 | 分开记录真实HTTP、缓存命中、失败、有效新增字段；暂停来源不重试，不按请求数量夸效果 |
| P1 | 合法城际与精确起点接口 | 正反方向/日期/接驳可核对；缺地址先澄清，无班次不编车次；增加可通过串联正例 |
| P1 | 酒店房型、床数、库存和餐饮分店/口味 | 单独构造各层任务；OR房型不当已订库存，分店不互移，未知偏好明确待确认 |
| P2 | 预算/偏好/天气影响的独立语义检查 | 已有数值预算门继续保留；另判偏好覆盖和应对是否实质改变计划，不只加引用 |

以上为后续目标，不是已完成结果。每轮至少同时报告：结构、硬条件、证据安全、有效补全、恰当拒绝、条件接纳和执行确认；模型原稿与规则投影分开，保留失败、冻结变更和来源时钟。原Schema还需新增新旧实体混合及噪声比例对照，方能系统评价扩容抗干扰能力。

## 7. 证据索引

- 官方结构：`ChinaTravel/chinatravel/evaluation/output_schema.json`；原评测封装：`src/shorttrip/checker.py`。
- P23：`results/p23_scaled_llm/REPORT.md`、`summary.json`、`paired_150.csv`、`remaining_failures.json`。
- P24：`results/p24_dynamic_feedback/SCHEMA.md`、`summary.json`、`evaluations/all_96.json`、`private/evidence_corpus.json`；旧问题与实现变更均保留。
- P25：`results/p25_reliable_retrieval/REPORT.md`、`summary.json`、`evaluations/`、`regression/results_96.json`、`DELIVERABLE.md`、`validation.json`。

本报告只汇总/复核已有本地证据和本轮修复，未把历史网页描述当成当前预约、报价或实地执行证明。
''')
    save(ROOT/'报告/17_测试汇总核对.json',{'p25':summary,'p24_corpus_upper_bound':40,'p24_cases_impossible_to_complete_with_corpus':96,'p23_all_pass_after_retrieval':118,'p23_llm_sample':150})
    if refresh:
        def local(stamp):return datetime.fromisoformat(stamp).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        relevant=[e for e in refresh['evidence'] if e['field'] in ('route_duration','route_fare','weather_forecast')]
        deadlines='；'.join(e['field']+' '+e['target_id']+'：'+local(e['valid_until']) for e in relevant)
        p=OUT/'DELIVERABLE.md';text=p.read_text(encoding='utf-8');start=text.index('原始证据捕获于');end=text.index('\n\n本方案',start)
        text=text[:start]+f'最新交付刷新于 **{local(refresh["at"])}（北京时间）**，另3次高德请求全部成功；原始15:37快照留档。本次仍为92元费用投影。当前快照过期边界：{deadlines}。这些是信息过期时间，不是允许跨到出行日继续当实时数据的承诺。最新机器收据见 `DELIVERABLE_LATEST.json`，原始输入/首轮方案仍见 `DELIVERABLE.json`。'+text[end:]
        p.write_text(text,encoding='utf-8')
        p=OUT/'REPORT.md';text=p.read_text(encoding='utf-8').replace('本轮真实新增3次高德调用（天气1、双向地铁2），不更换Key。','首轮3次高德调用（天气1、双向地铁2），交付前再刷新3次，本轮共6次成功调用，不更换Key。刷新曾发现交付封装的UID/请求预算引用了基础query，已恢复为预先指定E02；失败收据保留，成功API响应复用，没有重试调用。')
        p.write_text(text,encoding='utf-8')
    print(json.dumps({'report':'报告/17_ChinaTravel原生与扩展Schema测试总结及修复报告.md','delivery':'results/p25_reliable_retrieval/DELIVERABLE.md','summary':summary},ensure_ascii=True))
if __name__=='__main__':main()
