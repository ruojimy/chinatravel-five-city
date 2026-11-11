# ChinaTravel 持续工作任务：只按时间推进

用户最新指令：不再设计任何模型额度基线，让任务有足够时间推进。本文件替代此前所有5h/周百分比、预警、临时保留线和reset检查规则；旧handoff、旧聊天与旧自动化memory中的额度规则全部失效。不要再读取账户额度来决定是否启动、是否派子代理或是否继续，也不因额度工具缺失/失败而停。仅当平台实际拒绝继续执行时，保存真实错误并交接，不改账号、Key或付费方式。

工作目录为 `<repo>`。主控GPT-6.1 Terra/high，最多2个GPT-6 Luna/medium子代理；显式使用model=gpt-6-luna、reasoning_effort=medium、fork_turns=none，给出短上下文、文件边界、验收条件。不要自动改更贵模型或Fast模式。

## 运行方式

读取 `collector_agent/config.json`、`collector_agent/memory/CORE.md`、`collector_agent/memory/HANDOFF.md`、`collector_agent/memory/state.json`，并读取state指向的最新handoff及相关lessons。按真实阶段续接已有worker成果，不重写已完成模块，不从陈旧的control_plane_ready或旧pilot重新开始。只用实际工件证明进度。

每轮给出约50分钟实质工作窗口，50分钟开始停止派新任务、回收worker并保存，60分钟内交接。开始记录时间，在阶段边界检查已用时间，不高频检查账户额度，不空等凑时长。完成小补丁、几项测试或一次checkpoint不算整轮完成；有已授权ready工作就继续下一项，主控与子代理保持实质推进。单批完成后可在剩余工作窗口接下一项/下一批，冻结批次分别记账，不能混合评价分母。

先核查现有worker与共享运行锁，不能与另一轮工程重入。原协调聊天只做调度时，即使显示active也不等于采集重入，以真实锁/worker为准。使用唯一run_id，在reproduction目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\collection_session.py begin <run_id>
.\.venv\Scripts\python.exe scripts\collection_agent.py begin-run <run_id>
# 阶段边界保存checkpoint并检查时间，继续ready工作。
.\.venv\Scripts\python.exe scripts\collection_session.py check <run_id>
# worker已确认停止、交接已保存后释放锁。
.\.venv\Scripts\python.exe scripts\collection_session.py end <run_id> --reason time_budget_reached --workers-stopped
```

以上入口不需要usage-file；旧usage-file参数即使被传入也会被忽略。没有任何额度百分比门、预警或临时基线。旧锁不自动过期清除，遇旧锁先核实worker与交接，不杀用户其他进程。

时间边界前只有端到端目标已完成且该批没有ready工作，或明确外部/运行阻塞且没有独立安全工作，才能提前结束；必须提交有artifact路径/hash与pending_actionable_items=0的stop_report。小helper不能标完整里程碑。结束理由为time_budget_reached、batch_goal_complete、no_safe_work_remaining或runtime_blocked；usage_budget_reached已废止。控制门只验证结构/工件完整性，主控仍须核对真实语义，不编造完成标记或0项ready。

## 实质工作队列

优先接入最新成果：严格字段证据/身份/日期/房型门、路线完整上下文/TTL、多时段与跨夜营业、未知费用、城际Duration小时、候选失败与有限域无解分类。复用当前src/shorttrip的strict组件和最新worker交付，保留原ChinaTravel基准、v4原库、原证据与P31归档。

工程目标为检查实际接入规则规划器，并对v4至少5个覆盖五城的真实数据工程样例运行，输出多轴诊断、缺口队列和负例结果；engineering_smoke不叫论文成绩。接通后生成正式开发60题/独立留出30题：easy 1条额外逻辑要求，medium默认3–5（附录2–5另列），生成human表达标synthetic_human_style。冻结题集全文、约束、证据政策与实际评价器hash；留出逐题结果不反馈采集。

继续循环：规则器诊断 → 区分data/context/access/adapter/solver/pipeline及硬约束失败 → 跨题合并实体/字段/范围/政策gap → 多代理互补补采 → 逐字段验收 → 不可变新快照 → 同冻结题集重跑。超预算/超窗不算数据缺口，已有原文但解析不支持交工程，运行时天气/路线不展开静态全库刷新。按已冻结阈值或边际收益换批，仍有时间和ready工作时继续下一准备项，不以最多1批/1次修复为提前收尾理由。

网站访问预算和可靠性规则仍有效：全部worker共享60次web动作、每缺口最多3个来源、API/HTTP预算0；请求先reserve、再工具、后finish，同家族单owner/lease。来源预算用尽只停止新联网，继续独立离线解析、验收、接入和诊断。历史暂停不恢复，不换工具/Key/UA/子域/镜像规避；新来源正常核对政策。来源能力不能 blanket whitelist，保存真实原文/方法、URL、hash、引文、TAG、来源时间精度、实体/票种/房型/日期/单位/方向/许可与冲突；未知概率不编分数。

## 交接与验收

阶段边界保存实际产物及下一ready工作。结束核实worker停止，更新state/handoff/事件，释放运行锁。追加 `报告/2026-10-30早间验收.md`：实际更新时间、模型/worker、代码接入与验证、真实诊断/采集数量、证据路径、仍阻塞项和下一步；保留此前快照，未完成项如实写明，不把合成测试当真实采集成绩。不再为额度设计新脚本或花工作时间调百分比。

常规定时00/08/16和已有一次性04:00记录保持；不要自建无限调度。每轮最多60分钟，不连续8小时占着任务空转。
