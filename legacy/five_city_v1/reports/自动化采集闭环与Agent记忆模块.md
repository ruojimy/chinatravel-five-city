# 自动化采集闭环与 Agent 记忆模块

日期：2026-10-29。范围：基于既有五城采集经验，改进协调提示词，建立项目记忆和离线控制面。原《静态数据库5城市扩张.md》作为历史证据阅读，本轮未覆盖该文件或重跑其采集方法。

## 结论

这个方向可行。应优化“固定任务集上，可归因且可修复的数据阻塞下降”，而不是单独优化城市数、非空字段数或计划通过率。五步闭环增加三条主线：冻结任务与评价政策、区分数据/工程/约束原因、以阈值或边际收益结束本批。

`项目记忆启动 → 多代理互补组采集 → 逐字段可靠性门 → 冻结查询任务 → 规则器多轴诊断 → 合并并排序数据缺口 → 定向补采 → 同题重跑 → 阈值/饱和/预算换批 → 保存残留与旧回归`。

## 对原五步流程的改进

| 环节 | 建议执行方式 |
|---|---|
| 1. 多组数据 | 最多3个worker，按城市×业务链分工；同网站家族单owner。预算由共享SQLite预留，所有失败也计费。先用已有证据与缓存，根agent统一验收发布新版本。 |
| 2. query schema | easy 1条额外逻辑要求；medium默认3–5条；human表示真实请求来源，模拟题标synthetic_human_style。正式开发集默认60题，独立留出30题；存储合约、query结构、语义编译、可行性分开验证。 |
| 3. 规则器定位block | 逐字段检查“为什么不能继续”。已知超预算/超窗是候选约束失败；缺价格/错房型/无合格引文才是数据问题；已有跨夜原文但解析不了是适配问题。各轴可同时存在。 |
| 4. 缺口补全 | 按实体+字段+适用范围+证据政策跨题合并，再按解锁影响、来源能力和成本排序。只补能修复的静态缺口；不为硬约束通过寻找不适用的低价，不反复向地图问票价。 |
| 5. 结束并换批 | 初始建议：含数据block题率≤10%、各城市×层级/业务类型≤20%、覆盖下限满足，连续2轮稳定；或连续2轮改善<1个百分点/预算耗尽/没有可行动静态项时按saturated或budget换批。保留未解项，不能宣布全库完成。 |

这些阈值是运行参数，不是论文标准。每个城市×层级只有4题时，20%意味着该层必须0题block，应在正式试跑前审阅这一离散效应；不能在看到结果后临时改阈值。每批最多4轮修复，每次执行最多3批，避免无限循环。

论文正文§2.4与附录D.4对medium分别写3–5和2–5；本流程默认正文，并保留显式附录变体。依据本地冻结 `.ppt-build/sources/01.txt`；[论文入口](https://openreview.net/forum?id=0YRVlxY9BH)。不把P31的hard改名后当作论文medium，也不把规则器读取结构化约束当作自然语言理解成绩。

## 旧经验怎样变成新规则

当前活动参考库已核对为v4，1914条记录、3598份证据、5790条claim、6072个TAG；`planning_ready=0`。P31的72 complete /20 blocked /4 infeasible仅是旧评估器归档标签，本轮没有重新认证。旧P29指针仍指v1，启动时以明确配置和manifest SHA交叉检查。

两名子代理已完成本地审阅：

- `results/p33_collection_workflow_design/block_audit.md`：默认90分钟、固定速度估算、多时段/跨夜营业解析、餐厅窗口、未知费用、路线情境绑定、只试单序就判无解等问题及代码位置。报告区分潜在代码路径与旧归档实际观察。
- `results/p33_collection_workflow_design/source_memory_audit.md`：来源角色、同源转载、许可、原文与模型投影、时钟、房型/日期、共享暂停；发现旧builder给所有来源赋予所有字段能力，新的注册表不继承这种 blanket whitelist。

高德历史10021、Trip/Ctrip挑战页及其他历史暂停保持有效，不因旧成功、换工具/子域、冷却结束或新批次自动解除。原生城际Duration使用小时，内部路线使用分钟；抓取/入库时间不代替来源观察时间，无时区或日期精度不伪造完整时钟。

## 来源清单与可靠性

已整理15个详细来源组；人工入口 `collector_agent/SOURCES.md`，机器入口 `results/p33_collection_workflow_design/seed_sources.json`。6组记录为历史暂停，其余本轮未核验；没有一个因本轮离线整理而自动获得正文抓取许可。共享索引另继承更早暂停条目，索引数量不等于独立发布者数。

每组包含域名、历史URL、字段候选能力、发布者角色、独立来源组、访问证据、许可、置信度各维度、查询困难度和恢复条件。可靠性依次核验结构/值、原文hash和引文、实体/分店、语义与单位、时间/范围、许可和冲突。TAG的来源和推导方式一起保存；类型TAG不能自动证明适老、无障碍或排队时长。

置信度不编成单一0.95：角色、身份、引文语义、时钟、范围、许可、冲突分开记录。困难度另列访问、解析、上下文绑定与成本。没有独立真值和带分母的请求账本时，准确率、成功率、延迟与成本保持null。

## 已建立的项目记忆

| 工件 | 用途 |
|---|---|
| `collector_agent/PROMPT.md` | 可直接交给负责项目agent的协调提示词 |
| `collector_agent/memory/CORE.md` | 压缩后仍需保留的目标、活动版本和稳定规则 |
| `collector_agent/memory/HANDOFF.md` | 启动顺序、当前进度、真实执行范围、下一工程步骤 |
| `collector_agent/memory/lessons.jsonl` | 12条带证据路径的历史教训 |
| `collector_agent/memory/agent.sqlite3` | 共享来源状态、事件、预算、请求预留、家族lease和教训索引 |
| `collector_agent/memory/state.json` | 当前断点；bootstrap校验来源但不清空已有批次 |
| `collector_agent/config.json` | 模式、固定分母、预算和换批参数 |
| `collector_agent/schemas/query-cohort.schema.json` | 项目query封装合约，保持原存储/计划合约独立 |
| `collector_agent/examples/query_templates.json` | 三类query各一题；只是schema例子，未编译或证明可行 |

这是项目内记忆，没有修改Codex全局个人memory。事件和证据引用追加保存；网页正文不提升为长期行为指令。SQLite能约束经此控制面发起的动作，不能阻止agent绕过CLI自行联网，因此协调提示词必须要求所有worker共用此入口。

## 验证与启动

在reproduction目录：

```powershell
.\.venv\Scripts\python.exe scripts\collection_agent.py bootstrap
.\.venv\Scripts\python.exe scripts\collection_agent.py recall "hotel"
.\.venv\Scripts\python.exe scripts\collection_agent.py validate-tasks "collector_agent/examples/query_templates.json"
.\.venv\Scripts\python.exe scripts\p33_verify_collection_workflow.py
```

结果：22项控制面/schema测试通过，三轮合成示例验证了数据block修复后仍可在候选超预算的情况下换批、同题号修改约束被拒绝、共享暂停/预算/家族lease生效。v4数据库与旧P31归档manifest的SHA保持不变。证据在 `results/p33_collection_workflow_design/verification.json` 和 `verification/unit_tests.log`。

本轮没有新联网请求、真实规划器试跑、官方基准评分或定时后台任务。离线控制面已可用；下一步是按审阅结果接好严格规则器适配器，再冻结正式开发题集，做首轮真实离线诊断。当前旧P31不能直接充当可靠的自动采集反馈器。完整操作说明见 `collector_agent/README.md`。

## 后续更新：定时任务已启用

2026-10-29用户确认采用独立本地项目自动化，已创建任务 `chinatravel`（ChinaTravel 五城采集闭环），状态ACTIVE。已回读保存配置，主控为gpt-6.1-terra/high，运行环境local，时间为北京时间每天00:00、08:00、16:00。任务提示词要求最多2个gpt-6-luna/medium子代理；其实际启动情况以后续每轮工件为准。

周期提示词见 `collector_agent/AUTOMATION_PROMPT.md`。首轮最多30分钟离线工程校准；后续目标45–60分钟，每轮1批、1次定向补采，所有worker共享60次web动作，API/HTTP预算0。新增共享运行锁和额度检查入口 `scripts/collection_session.py`，覆盖重复轮次、低/未知额度、跨reset、单轮/周软预算及worker释放。额度与时间属于合作式软控制，不能保证精确token硬限。

配置及27项离线测试的验证记录为 `results/p34_automation_setup/verification.json`；未启动实际定时轮次或新联网采集，旧v4库和P31归档保持不变。电脑及应用需保持运行。此前“未创建定时任务”是流程设计阶段的历史状态，本节更新当前调度状态。
