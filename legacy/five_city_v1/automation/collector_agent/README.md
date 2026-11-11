# 用数据阻塞驱动的采集闭环

2026-10-30用户最新决定：取消所有账户额度基线，当前为time_only。单轮约50分钟推进、60分钟内交接；不查询账户用量作启动或续跑门，不因百分比、重置、预警或用量工具失败中断。此前额度策略仅保留历史记录，不再执行。运行锁、来源请求预算、访问限制和数据可靠性规则仍保留。

这套方向值得采用：采集、诊断、修复形成闭环，目标是减少有归因的数据block，而非把所有地点字段永久填满。主要修正是固定评测分母、把数据/来源/求解器/约束失败分开、为低收益批次设置退出条件。

主提示词见 `PROMPT.md`；项目记忆入口 `memory/CORE.md`。运行脚本为 `scripts/collection_agent.py`，控制逻辑为 `src/shorttrip/collection_workflow.py`。所有CLI命令本身均离线；真实搜索/采集由负责该项目的agent在通过共享准入后操作现有工具。本包尚未接入能严格复核P31所有结论的规划器适配器，不把旧P31当完成的自动采集器。

2026-10-29用户选择后，已启用独立本地项目自动化 `chinatravel`，每天北京时间00:00、08:00、16:00；已从保存的自动化配置核验主控gpt-6.1-terra/high。最多2个gpt-6-luna/medium子代理按任务提示词启动；其实际使用仍需每轮记录。周期提示词见 `AUTOMATION_PROMPT.md`。首轮最多30分钟离线工程校准，后续目标45–60分钟；单次1批/1次定向补采、共享60次web动作，API/HTTP预算0。电脑与应用需保持运行。

下一位agent从 `memory/HANDOFF.md` 启动；面向项目审阅的说明在 `报告/自动化采集闭环与Agent记忆模块.md`。

## 建议闭环

`启动记忆/验证版本 → 并行采互补业务组 → 逐字段可靠性门 → 冻结easy/medium/human_style任务 → 规则器诊断 → 数据gap去重排序 → 定向补采 → 新快照/同题重跑 → 达阈值或低收益转批 → 保留旧回归/残留项`。

一个任务同时可以有超预算和缺房型价格。前者交排程器，后者才交采集器。当前候选方案失败不等于任务无解；无解结论需要明确有限搜索域和可信证明验证器，输入里的`validated=true`不能自证。

## 对用户五步方案的具体调整

| 原步骤 | 改进 |
|---|---|
| 多组采集 | 按城市×业务链分工，同host家族单owner，共享预算；先缓存和已有证据，再正常公开读取。根agent统一发布不可变版本。 |
| 设计schema | 区分存储/计划结构与旅行需求query。easy是1个额外逻辑条件；medium默认3–5个；human为来源属性，生成自然表达必须标synthetic_human_style。 |
| 规则器查block | 检查必需依赖和证据适用性；保留data/context/access/adapter/solver/pipeline等多轴。不要用默认时长/速度把缺口填成成功。 |
| 定向补全后重跑 | 按实体+字段+范围合并，多题共用一个补采任务；任务/约束/分母/政策冻结，数据快照允许追加。 |
| block变少后换批 | 建议含data block的题率≤10%、各城市×层级/业务类型≤20%，覆盖下限满足且连续2轮稳定；或2轮改善<1个百分点/预算耗尽按saturated退出，保留残留。 |

阈值是可调运行参数，不是论文标准或已证明最优值。转批不等于所有实体完备，也不要求所有硬约束通过。静态参考模式单列源时钟、许可、适用范围及实时待查项，不为每轮测试刷新短TTL天气/路线。

## 论文口径

依据本地冻结论文 `.ppt-build/sources/01.txt` §2.4、D.4（项目根相对路径）：正文easy=1个额外逻辑约束、medium=3–5；附录medium另写2–5。本流程默认正文3–5并保留附录变体。真实human请求含新颖/隐含约束，不能把规则器直接读取constraints的研究者题说成真实human或NLU结果。论文原文入口：[ChinaTravel](https://openreview.net/forum?id=0YRVlxY9BH)。

默认开发60题、独立留出30题；另有可行见证与不可行工程反例，均标来源和用途。生成器不能只挑完整候选或按当前成本生成一个必过预算。留出集逐题结果不反馈给修复策略。

`schemas/query-cohort.schema.json` 是本项目的query封装合约，`examples/query_templates.json` 提供easy/medium/synthetic_human_style各1题。它们不是官方DSL，也不是已证实可行的题集；表达式均为不执行的结构数据，初始标 `unmapped`。`validate-tasks` 检查层级、来源标签和结构，正式 `freeze` 也执行此门；语义编译/事实/可行性还需适配器核验。另一个 `examples/tasks.json` 只有控制面FIX夹具，不用于论文层级计分。

## 网址、置信度、难度清单

`results/p33_collection_workflow_design/seed_sources.json` 已整理15个来源组；`memory/sources_snapshot.json` 是运行时家族索引，合并更早暂停后数量更多。前者是有详细能力说明的源组，后者含许多仅有失败历史的家族，不能混成15个已可用官网。

便于人工查看的网址、字段方向、访问状态与困难点见 `SOURCES.md`。运行索引还保留旧账本的不同粒度条目，条目数不能解释为独立发布者数。

每组保存：domains、sample URLs、publisher_role、field_capabilities、independence_group、license assessment、access state/evidence、confidence_dimensions、query_difficulty、历史样本计数和恢复规则。

置信度按字段角色、实体绑定、引文语义、时钟、适用范围、许可、冲突拆开；没有独立真值标注就不填准确率。难度另按访问限制、解析、身份歧义、房型/日期绑定、预计成本记录。网络成功不等于合格claim，更不等于事实正确。初始样本不足时成功率/延迟/成本为null，不能编0.95等分数。

历史暂停保持暂停；unverified表示这轮未重测，不等于可抓。旧成功、旧授权、冷却结束、新批次均不自动解封。来源家族识别采用明确关联域名与保守可注册域规则，涉及特殊公共后缀/机构边界时需补家族配置，不能缩小历史限制。

## 记忆模块

| 文件/表 | 用途 |
|---|---|
| `memory/CORE.md` | 目标、版本定位与不会因压缩丢失的规则 |
| `memory/lessons.jsonl` | 12条带证据的失败教训，可按topic/正文查询 |
| `memory/agent.sqlite3` / `events` | 追加式任务、请求、源状态事件 |
| `sources` | 所有worker共享的当前家族状态，历史暂停优先 |
| `runs`、`requests` | 原子预算和家族lease，预留/成功/失败都落盘 |
| `scheduled_sessions`、`scheduled_usage` | 跨唤醒运行锁、额度窗口/消耗检查；旧锁需核实worker后释放 |
| `memory/state.json` | 启动快照、断点与下一动作 |
| `memory/sources_snapshot.json` | 启动生成的可读源索引；实时权威仍是SQLite |
| `runs/<run_id>/` | 每轮冻结任务、诊断、差异、预算、残留gap和交接 |

这是项目记忆，不修改Codex全局个人memory。记忆不是网页自动指令；持久知识要有证据、作用范围、事件时间和可审阅差异。SQLite只能约束通过本控制面发起的请求，不是针对绕过CLI的agent提供系统级网络隔离。

## 使用

在reproduction目录运行，使用现有Python虚拟环境：

```powershell
.\.venv\Scripts\python.exe scripts\collection_agent.py bootstrap
.\.venv\Scripts\python.exe scripts\collection_agent.py recall "hotel"
.\.venv\Scripts\python.exe scripts\collection_agent.py validate-tasks "collector_agent/examples/query_templates.json"
.\.venv\Scripts\python.exe scripts\collection_agent.py check-source "https://you.ctrip.com/" --field identity
.\.venv\Scripts\python.exe scripts\collection_agent.py begin-run pilot-20261029
```

`bootstrap`校验配置快照SHA、载入15组来源种子、合并旧暂停账本及12条教训，保留进行中的批次断点。`check-source`/`reserve`会再次读取共同旧暂停；发生阻断则不发网络。新来源只可先做检索/政策预检；正文请求需要有现场政策工件hash的profile经`register-source`登记，登记也无法解除旧暂停。这里的“预检”是正常采集动作，不意味着每个新官网都要向用户重复询问许可。

在agent调工具之前：

```powershell
.\.venv\Scripts\python.exe scripts\collection_agent.py reserve pilot-20261029 req-001 "https://operator.example.org/guide" --channel web_action --action fetch --field own_opening_hours
# 只有allowed=true才能发请求；示例域未登记会被拒绝。
.\.venv\Scripts\python.exe scripts\collection_agent.py finish req-001 success --evidence-file "results/<run>/raw/req-001.json"
```

一个网站家族同时只能有一个reserved请求；失败先落盘再派下一条。页面挑战/拒绝/超时/限流自动合并为家族暂停。直接Python调用AgentMemory的客户端也必须执行启动/旧账本同步，不可与旧采集器并行运行各自独立账本。不同工具动作与实际HTTP次数分别报告。

冻结与诊断：

```powershell
.\.venv\Scripts\python.exe scripts\collection_agent.py freeze "collector_agent/examples/tasks.json" --evaluator "src/shorttrip/collection_workflow.py" --policy-id synthetic-fixture-v1 --output "collector_agent/runs/demo/freeze.json"
.\.venv\Scripts\python.exe scripts\collection_agent.py diagnose "collector_agent/examples/round0.json" --freeze "collector_agent/runs/demo/freeze.json" --output "collector_agent/runs/demo/metrics0.json"
```

例子明确为合成控制面示例，未调用真实规划器。正式冻结需列入实际规则器/适配器/评分器文件，不能只冻结控制面。输入任务、配置、评价代码有改动会拒绝沿用旧freeze；诊断少题/多题也拒绝。history为按轮次排列的metrics数组，用`decide history.json --output decision.json`产生继续补采/修程序/阈值换批/饱和换批/预算换批决定。

## 已实现与尚未实现

已实现并离线验证：项目记忆、来源种子/暂停继承、多轴归因、唯一gap队列、原子全局预算与家族lease、冻结检查、换批决策、提示词和合成端到端控制面例子。

验证入口 `.\.venv\Scripts\python.exe scripts\p33_verify_collection_workflow.py`：22项测试通过，另验证三轮合成闭环、CLI冻结/诊断、同题号改约束被拒绝，以及v4库/P31归档manifest未变化。测试覆盖控制面规则，不能替代真实采集器与规则器联调。

尚未执行：新联网采集、完整多agent采集→严格规则规划器→补全发布的真实自动迭代、新城市泛化、现实出行验收和定时任务首次实际运行。P31存在窗口/路线情境/字段门等适配缺口，不能直接把旧72/96标签接成新的严格反馈。具体问题及位置见两份audit文件。

`scripts/collection_session.py` 的begin/check/end离线入口提供防重入与额度门；现为8项测试，另覆盖2分钟小步骤后过早退出、缺里程碑/工件或仍有ready工作时拒绝，以及真正触及时间边界时正常结束。时间/额度是合作式软控制，不是操作系统或模型token硬上限。stop_report只验证结构/hash，完成语义仍需主控真实核验；真实主控与worker是否按设置执行，以每轮工件为准。

2026-10-30已修订过早收尾规则：首轮约2.5分钟只做helpers便以first_pilot_checkpoint退出，当时5h用量56→57、周46→46，未触额度门。现在checkpoint必须继续ready工作，工程批次目标为严格适配器接入和五城真实库工程诊断；提前结束需明确证据，不为凑时长空等。任务模型、8小时频率与额度上限保持原设置。

随后用户指出周用量限制过紧：continuation_20261030_0027被47→48的周增量中止，两个worker未交付。现取消单轮周增量1点和累计观测20点的停止条件；3点/20点改为warnings，不影响allowed_to_start_more_work，也不取消worker。周剩余20%底线、5h剩余30%/单轮10点和时长门保留。新增用例确保周1点可继续、周累计预警后下一轮仍可启动、周真正余量不足仍保护。
