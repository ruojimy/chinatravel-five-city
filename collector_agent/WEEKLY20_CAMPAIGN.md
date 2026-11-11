# 单代理20个百分点周预算任务

**2026-11-03新授权已替代本文件的旧预算与工作重点：请先读`WEEKLY20_20261103.md`。新campaign=weekly20_20261103，真实26%起、20点、目标46%；单Terra/high、无时限。用户要求规模扩容，不能停留每城每类20条。以下11月2日内容和旧9%→29%只作历史，不作为当前停止/预算。**

## 2026-11-02 最新续跑纠正：历史停止消息已失效

用户在协调聊天纠正“它根本没跑到完结就提前收工了”。请继续本任务。11月1日11:36Z的“本轮收个尾”只适用于旧轮；11月2日14:27Z上下文压缩把它留在新environment_context后，代理误当成当前消息，于14:29Z提前退出。本次并无新的真实用户叫停。原始消息时序见`results/weekly20_20261102/premature_exit_audit_20261102.md`，旧报告/user_stop_report保留为失败证据，不能反过来当成新停止授权。

恢复使用weekly20_20261102_run03及原campaign，实际起点9%、目标29%、最近13%，不重设基线、不派worker、不设时限。现无active session，先读最新真实usage再begin。继续batch09残留和最新batch08数据快照；新旧快照/固定题比较分别记录参考字段与合格依赖。发生压缩仍以本次带日期的续跑指令和状态接续，不重复执行已被后续授权覆盖的旧收尾。未来真实新到的用户停止指令照常立即执行，不删除用户停止出口。

用户2026-11-02最新指令：本次不设时间要求，单个agent持续推进，累计使用20个百分点的周额度。保留GPT-6.1 Terra/high，禁止派子代理或委派其他聊天处理业务；原Luna/双worker安排失效。已有其他项目不受本任务控制。

本任务的唯一累计预算为 `weekly20_20261102`。在用户发出本次指令时，真实账户周窗口已用9%，预算目标为约29%；这是账户共享窗口，包含其他并行任务，本项目不能声称精确归因。初始化文件由协调端保存，运行代理只能check/resume，不能重新创建baseline、每批再领20点、消耗免费reset或购买额度。真实测量在逻辑阶段边界进行，接近目标时缩短工作批次；测量存在刷新/取整与单次调用粒度，不能保证精确硬截在29.000%。

没有50/60分钟期限、最短时长、8小时工作间隔、5h增量、周单轮1点或余额保留线。不要把旧CORE/记忆/交接或P44建议稿中的时间/并行限制恢复回来。仅本周预算可作常规停止条件；实际平台不可用或没有合法可继续工作时保留阻塞，不以重复测试/无意义输出凑额度。真实周窗口发生重置时保存账本和未用预算，不自动在新周再领取20点。

## 控制入口

工作目录 `C:\Users\xiech\Downloads\计算机软件工程概论\reproduction`。复用共享数据库与运行锁，单代理运行。周窗口按windowDurationMins=10080识别，可能位于primary，也可能位于secondary，不硬编码secondary。

先用实际get_usage_limits工具返回保存精简JSON（去掉accountId、credits等无关项），然后使用：

```powershell
.\.venv\Scripts\python.exe scripts\collection_session.py campaign-status weekly20_20261102
.\.venv\Scripts\python.exe scripts\collection_session.py begin <run_id> --usage-file <real_usage.json>
.\.venv\Scripts\python.exe scripts\collection_agent.py begin-run <run_id>
# 每个补采/重跑阶段及批次边界取真实新快照。
.\.venv\Scripts\python.exe scripts\collection_session.py check <run_id> --usage-file <real_usage.json>
# 累计20点到达、工件已保存后：
.\.venv\Scripts\python.exe scripts\collection_session.py end <run_id> --reason weekly_budget_reached --workers-stopped
```

begin/check中的deadline_epoch为null且不按耗时停止。run内不同补采批次分别保留输入/输出，预算始终同一个campaign；中断恢复先检查旧锁/上下文与账本，只复用既有baseline，不绕过未结束的会话。

## 业务目标与范围

先读state及最新handoff，按 `collector_agent/P44_RESET_PROMPT_REVIEWED.md` 执行“真实字段缺口 → 补数据 → 新快照 → 同题重跑”。该建议稿中“最多2个worker”“60分钟”“10分钟修复”等限制，本次均由单代理＋唯一20点周预算替代；来源安全预算、证据门和固定题集要求不变。不能回去扩通用verifier、金额框架、event domain或跑60题，用这些工作耗满额度。

先完成5城×2题easy/medium探索批次。DATA、VERIFY、CONTEXT、ERROR分开，按实体/字段/适用范围去重，冻结10题和统计口径。旧60/60的身份和聚合问题不能只改名当数据改善；先读取v4原生字段，找真实缺值。没有approved来源时可正常预检非paused公开运营方入口，不能伪造准入或绕暂停；仅最小修复直接阻挡补采/新快照读取的接入错误，不能重建庞大核验系统。

每批最多60次共享Web动作，每缺口最多3个相关来源，api_http=0，不调高德。批次预算用尽仍完成合并和重跑，之后有合格新任务可另登记下一小批，仍使用同一个20点campaign。旧暂停、captcha/限流/拒绝不得绕过；不换Key/账号/工具/子域/UA/镜像。不把所有来源赋accessible。

### 2026-11-02 公开参考检索入口修复

run01只试5个robots地址后退出，不能证明没有其他可执行采集。登记器依赖尚未接通的独立verifier，导致unknown来源永远不能正文读取；这是项目接入错误。现在静态参考模式显式启用`public_web_reference_reads`，沿用同一reserve→Web工具→finish账本，普通公开检索不再以accessible/robots成功为前提。默认严格source_check、事实接纳及源状态不变；这项读取授权不授予转载许可、身份资格或严格规划资格。实际页面许可限制仍需遵守；未知保留unknown/reference。

```powershell
# URL为查询目标家族根，query是真实Web搜索语句；不能拿主页fetch冒充search。
.\.venv\Scripts\python.exe scripts\collection_agent.py reserve <run> <id> https://www.example.org/ --channel web_action --action search --field opentime --reference-only --query 'site:example.org 实体 开放时间'
# 随后调用web.search_query的同一查询，保存原始工具文本并finish。
.\.venv\Scripts\python.exe scripts\collection_agent.py reserve <run> <id> https://www.example.org/public-page --channel web_action --action fetch --field opentime --reference-only
# 随后调用web.open同一URL，保存原始工具文本并finish。
```

家族暂停仍拒绝search/fetch；实际超时、拒绝、验证码、限流等照实finish并暂停，不切工具/子域规避。工具仅报robots URL不可读且源站状态未知，不得编造成源站403或全网不可用。搜索摘要只作线索，事实必须有正文与精确quote。公开参考检索本身不更新sources为accessible，也不能将licence unknown改成allowed。不继续建设来源授权verifier；检索失败时改查其他未暂停且相关的公开来源。

修复后重新固定同批诊断代码，并对原v4与新快照两端重算。旧10题候选集尚未证明每个缺口都是题目实际必需，先通过原题约束明确所选分店/房型/日期与依赖；缺上下文的标CONTEXT，不猜、不用旧10/10作合格P44分母。正常补充明确依赖后另存exploratory manifest，保留原文，不重跑旧60题或放行formal freeze。

新证据保留真实原文/方法、URL、hash、精确quote、值与单位、TAG、来源时间精度、坐标系统与顺序、身份/分店/票种/房型/日期/方向/许可。未知不猜；冲突双方保留。保存规则器实际可读的不可变新快照，不改v4/P29/P30/P31原件。比对同10题的baseline/after，确认实际读取新快照，分别报告缺字段题数、合格依赖推进和总体阻塞。

一个10题批次完成不是整个campaign完成。还有可合法推进的缺口就继续该批修复，饱和后再封存下一10题小批，不换掉已冻结的题来刷改善。遇真实来源/上下文阻塞且不存在其他独立可做的数据任务，保存具体证据与下一步，不能无意义烧完20点。

## 交接

在 `results/weekly20_20261102/` 保存真实usage快照、预算状态、每批run_id、动作、原文/quote/范围、快照、baseline/after/recheck、合格/拒绝及残留。每阶段写checkpoint和state；最终report.md给出周用量起止/增量（标明账户共享）、补了哪些数据、同题变化、来源失败和未完成项。禁止用synthetic测试、锁或单纯重分类冒充真实补采。禁止为这个任务自建无限调度或增加其他agent。
