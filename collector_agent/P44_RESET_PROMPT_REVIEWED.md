# ChinaTravel 五城补采闭环：10题纠偏试验建议稿

你是 ChinaTravel 五城采集闭环的执行代理。本轮把工作转回“具体字段缺口 → 真实补采 → 合并新证据 → 同题重跑”。只做10题探索性试验，不跑60题，不扩human或event domain，不建设新的通用verifier、金额框架或事件框架。测试通过、写helper、把旧block改名都不是本轮产出。

工作目录：`C:\Users\xiech\Downloads\计算机软件工程概论\reproduction`。
先读 `collector_agent/memory/CORE.md`、`collector_agent/memory/HANDOFF.md`、`collector_agent/memory/state.json`、`collector_agent/config.json`、`collector_agent/SOURCES.md`。本轮范围优先于旧记忆中继续开发核验器/60题/事件域的工作安排；保留原有来源暂停、证据真实性和原库保护规则。账户额度基线仍全部取消，不查询或编造usage文件，不为凑时长工作。

活动库固定为 `data/five_city_reference_v4_20261026/catalog.sqlite3`，完整SHA256为 `58a368a7d3d8ec66208fc7a42da3556b44f5b299b7fed849de32c868003dbdac`；校验manifest，不用陈旧P29 current指针。run_id为 `p44_reset_<YYYYMMDD_HHMM>`。先确认上一轮worker/共享锁已结束，按既有collection_session与collection_agent登记；不另建运行或请求账本。

## 一、先分类，并直接检查任务依赖字段

从 `results/manual_20261101_1803/development_diagnostic_v3.json` 取原诊断，原文件保持不变。每个任务保留原outcome/reasons，另输出以下可并存的分析轴：

- DATA：本题需要的原生字段确实缺失，例如price、opentime/endtime、lat/lon、numbed、Cost、Duration、From/To。解析器不支持已有原文另列ERROR/adapter，不自动当缺值。记录是否有候选来源是另一个属性；来源暂不可用不会让缺值消失。
- VERIFY：值存在但身份、引用语义/值绑定、来源事实时间或许可适用性尚未闭合。值缺失且身份也未知时，DATA和VERIFY同时保留。
- CONTEXT：题目缺必要日期/起点/房型/票种/方向/路线范围，或规划器能力未接入。后者额外标adapter/solver子类，不能说成城市缺数据。费用聚合输入缺失须追溯到具体分量；没有缺失金额分量证据时，不能直接算DATA。
- ERROR：坏JSON、无法读取、哈希不一致或程序异常单列。保留实际硬约束失败，不派给采集器，也不算DATA。

不要只重命名旧data_block。旧报告目前没有逐实体的明确字段需求，identity被放进data、静态补采队列为空。对本轮候选逐一读取v4的`payload.data`，只为题目确实依赖的字段建立`native_field + unit + scope`清单，检查实际值和相关claim。只做一个本轮读表/映射薄层，不能因此启动通用核验器开发。

本轮主要指标命名为`missing_field_task_count/rate`，分母始终固定10；同题无论缺几个字段只计1题。VERIFY、CONTEXT不计入该指标的分子，但必须另列`any_blocked_task_count`与原严格outcome；它们不能被删除或改成pass。不得将新口径的10题结果与旧口径60/60直接比较。

## 二、选择并固定10题

五城各2题，只选easy/medium，优先每城各1题。选择确实存在明确DATA需求、所比较的字段依赖可以被现有诊断入口读取的任务，不选仅身份/上下文/事件域受阻的题。整计划仍有unsupported时保留CONTEXT，它不否决有明确字段依赖的采集试验，但不得声称本轮证明整题可规划。

如果某题缺上下文，可在选题冻结前将它明确构造成新的researcher_generated探索题，记录原题id、修改内容和日期/房型等情境；不能假称是原题。仍有不可支持要求的题排除并记录原因。不足10道合格题时如实报告可选数，不凑题、不扩大成60题、不隐瞒城市缺项。

选择完成后固定原文、约束、任务字段需求、必选/允许备选实体id、情境、证据政策、分类映射和实际评价命令。存`cohort.json`与`cohort_manifest.json`及hash。标签为`exploratory_collection_pilot`、`formal_score:null`。这是本轮输入封存，不是正式论文freeze；不要调用当前会无条件拒绝正式冻结的接口后转去建设框架，也不能把合成FIX题冒充正式题。重复使用实际可运行的规则器/诊断入口，结果存在能力限制就如实列出。

新分类映射和输入准备完成后，先跑一次这10题的baseline，保存原始完整结果，再开始定向补采。前后比较均使用同一个分类口径。

## 三、最多20个缺口，优先5–8个依赖组

去重键为`entity_id + native_field_or_semantic_group + normalized_scope + evidence_policy`。scope包含相关房型/人数/票种/日期/单位/方向；路线另含有序端点、入口、方式和时刻。不能把不同房型或日期的同名price并成一个gap。

每个gap列城市、kind、实体id/名称、字段、当前值、确切缺少项、适用scope、关联题id、候选来源/家族及状态、预计动作数、优先级、后续VERIFY/CONTEXT依赖。lat/lon作为一个坐标缺口、同一营业窗口作为一个依赖组；同时保留原生字段明细，不能靠拆单元格/引文刷“3个补全”。

按能解除多少实际字段依赖、来源适配性和成本选5–8组先做，不平均摊。明确区分“补后字段依赖可推进”和“补后整题可继续”，仍有VERIFY/CONTEXT时不能承诺整题解锁。

## 四、来源准入与真实补采

当前SOURCES.md是历史清单，实际SQLite没有accessible来源。不能只写“只用active/approved”然后因空名单结束，也不能把unknown直接当approved。先用最多12次计入总预算的正常Web动作，查找/核实1–2个与优先gap直接相关的非paused运营方/机构来源，正常核对公开访问及适用政策，在现有流程按实际结果登记本次URL/用途范围。准入依据和事实许可不伪造；页面可访问不等于claim可靠。

有访问资格的既有源直接使用；非paused的unknown或新公开官方源允许正常政策预检。任何历史家族暂停都优先，ctrip/trip、qunar、visitxian、wikidata、osm_services等按实际最新账本不请求；不换子域/工具/UA/Key/镜像规避。

若现有登记器因为缺通用独立verifier而拒绝所有正常正文读取，记录具体命令、错误和受影响gap；只允许针对本轮URL范围的最小接入修复，不改变robots/平台访问限制或事实证据标准，不给所有来源批量赋accessible。单项接入修复最多10分钟；仍无法获得合法入口就保存为访问/接入阻塞，继续现有可安全执行的数据工作或据实结束，不能再花整轮建设核验系统。

不调用高德/API；api_http=0，只用Web工具。全部worker共享60次web动作，search/open/click/预检/失败按实际query或动作逐项计数，每缺口最多3个相关来源；同源独立性不重复计数。最多2个worker，沿用Terra/high与Luna/medium设置，明确不同来源/文件边界。请求遵循共享reserve→实际工具→finish，不另建预算；collection_log.jsonl只是共享账本的可读工件。

每个新值保存source_url、raw_text或明确方法的原始工具文本、raw_sha256、retrieved_at、精确quote、原生字段、value、unit、坐标系统和顺序、licence状态/依据、实体/分店/房型/票种/日期/方向/范围。quote必须是raw_text精确子串，还须语义支持该值。摘要不当原文、模型不冒充原始响应。

来源只给日期或无时区时间时，存original_time_text和精度，observed_at可为null，不补午夜或时区；只接纳为相应静态参考，不自动升级为严格规划事实。冲突双方各自保留完整证据与适用范围，选择一方须写理由，不平均、不只把另一方塞进notes丢掉证据。

查不到就null/unresolved；旧值不被无证据推测覆盖，不用最近点、异店、错房型/票种或不适用旧价顶替。新实体仅在冻结题集预先允许的备选域内使用，不能为成绩换必选实体。区分新增实体数、已有实体补字段数与新证据数。

## 五、新快照与同题重跑

候选证据写入`results/<run_id>/snapshot_v1/`，保留逐字段来源链，不修改v4或P29/P30/P31归档。保存parent_catalog_sha256、补丁/新工件hash、接纳与隔离清单。该目录必须有规则器实际可读的增量覆盖或新catalog入口，不能只放JSON文件但重跑仍读旧v4。

逐字段检查原文/hash、quote及值语义、单位、坐标系统、日期/房型等scope。正常的来源不支持、quote/value不匹配或范围不适用属于证据拒绝，进入VERIFY；只有程序确实没按合约处理才记ERROR，不把所有拒绝归成工程失败。

保存`baseline.json`、`after.json`与执行命令/输入hash。同一10题、同约束、同分类和同评价器前后比较，只允许数据/证据快照变化。若必须最小修复评价器或输入映射，先固定修复后的代码，然后将原v4与新快照两端都重新计算；不拿修复前baseline与修复后结果比较。

新值缺少严格资格可保留为有出处的reference；分别报告`new_reference_fields`、`qualified_required_gaps_closed`、`planner_dependency_advanced`、`tasks_unblocked_overall`，不能将有值、通过quote检查、严格可用和整题解锁混为一谈。

## 六、判定与停止

固定分母10，给出before/after的DATA字段缺失题数、唯一依赖gap数、VERIFY题数、CONTEXT题数、ERROR题数和总体阻塞题数；多轴允许重叠，不要求相加为10。

- 闭环改善：相同口径DATA缺失题数相对下降≥30%，即减少至少ceil(before×0.3)题；before=0时该比例不适用，不能宣称100%改善。总体仍受VERIFY/CONTEXT卡住须同时报告。
- 采集部分有效：至少3个不同、真实必需且在匹配scope下合格的依赖缺口得到新证据补全，并在同题重跑中确认字段依赖前进。它不能替代“闭环改善”或被说成整题可执行；只填了不被题使用的字段或不合格reference不算这3个。

最多60分钟为上限，不设最低运行时间、不为凑时长继续建设框架。60次Web动作耗尽时停止新请求，但仍须合并、校验、跑after和交付。两个worker交付不是停止条件；baseline的10题跑完也不是停止条件。停止于“本次补采完成或相关来源穷尽＋合并后同题重跑＋工件交付”，或明确无法继续的外部阻塞/实际平台限制/时间上限。无改善必须写具体原因，仍保存after或可复现的重跑失败，不能只说下一轮再补。

checkpoint不是退出理由，但这次固定试验已经完成后也不强迫工作满50分钟。用既有session end登记本次pilot完成/无安全工作/时间退出；若旧end枚举只认完整规划器里程碑，只做本轮语义清楚的最小流程适配，不伪称strict_adapter_integrated，不强行填0个ready。固定批次外的残留写backlog，不能隐去。

## 七、交付

`results/<run_id>/`至少包含：

- `cohort.json`、`cohort_manifest.json`：10题完整输入、字段需求、选择理由/排除项、情境与hash，探索试验标签。
- `gap_plan.json`：最多20个按scope去重的DATA依赖，优先5–8组；VERIFY/CONTEXT/ERROR另列。
- `collection_log.jsonl`：真实reserve→工具→finish、URL/query、状态、动作数、共享账本引用；未发送请求不能写success。
- `snapshot_v1/`：规则器可读的补丁/入口、新证据、字段、TAG、quote、时间戳、licence、scope、接纳与隔离结果。
- `baseline.json`、`after.json`、`recheck.json`：同10题原始结果、分类映射版本、实际运行命令/输入快照hash、前后统计和依赖前进证据。
- `report.md`：一页说明补了什么、是否真正被重跑读取、补动/没补动、来源失败、仍有的VERIFY/CONTEXT、下一轮5个gap。

更新state.json/HANDOFF.md，保存本轮run_id、动作数、新实体/参考字段/合格依赖数、DATA前后、总体阻塞、未解决项与下一步。使用新日期，不继续向10月30日早间报告追加新轮结果。

## 八、禁止与短摘要

不新增通用verifier功能，不扩事件域，不跑60题，不回用P31旧72/96标签；只有直接挡住本次来源准入、快照读取或重跑的错误才做限时最小修复，标为工程修复，不算数据补全。小范围输入封存和分类输出不等于放宽既有证据接纳。

不把VERIFY/CONTEXT重分类造成的数值下降说成补采改善，不绕过暂停/验证码/限流，不恢复账户额度基线，不自建无限循环。汇报只给短摘要：run_id、固定10题DATA缺失前后及总体阻塞、补了哪些合格依赖、来源与动作数、失败点、下一轮5个gap。
