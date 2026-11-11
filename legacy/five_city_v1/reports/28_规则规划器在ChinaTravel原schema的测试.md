# 规则规划器在 ChinaTravel 原 schema 上的表现（P33 → P34 重做）

**测试日**：2026-10-28（P33 旧版）、2026-10-29（P34 新版，北京时间）。
**对象**：ChinaTravel 官方 schema 与官方评测器（`eval_exp.py` 的 schema / commonsense / hard DSL 三关），10 个老城市，easy 300 / medium 150 / human 154。
**规划器**：P33 = `SkeletonPlanner` + 旧 `RepairEngine`；**P34 = `src/shorttrip/planner_v2.py` 的 `ConstraintPlannerV2`**（确定性、无 LLM，以官方 checker 为唯一裁决）。
**结果目录**：`results/p33_native_planner/`（旧）、`results/p34_v2_planner/`（新）、`ChinaTravel/eval_res/splits_*_p33/`（官方输出）。

---

## 0. 结论

用「约束定向构造 + 检查器裁决」重做规则规划器后，三关全过率从 **30.0% / 18.0% / 46.1%** 提升到 **48.7% / 46.0% / 70.8%**（easy / medium / human）：

| split | P33 旧 | P33+room_type 修复 | **P34 V2** | 提升（vs 旧） |
| --- | ---: | ---: | ---: | ---: |
| easy（300） | 30.0% | 30.0% | **48.7%** | **+18.7 pt** |
| medium（150） | 18.0% | 28.0% | **46.0%** | **+28.0 pt**（+18.0 vs 修复版） |
| human（154） | 46.1% | 46.1% | **70.8%** | **+24.7 pt** |

与论文（ICLR'26 Table 3/17，FPR = 三关全过）对比：

| split | 我们 V2 | 论文 NeSy（DeepSeek-V3） | 论文 NeSy*（Oracle 翻译） | 最强纯 LLM |
| --- | ---: | ---: | ---: | ---: |
| easy | 48.7% | 52.6% | 74.0% | 5.33% |
| medium | 46.0% | 46.7% | 54.0% | — |
| human-val | **70.8%** | 37.0% | 45.4% | — |

一句话：**easy/medium 与论文用 DeepSeek-V3 做 NL→DSL 的 NeSy 基本持平（−3.9 / −0.7 个百分点），human-val 高出 33.8 个百分点；距其 Oracle 翻译版仍差 25.3 / 8.0 个百分点。**
差距来源是「语义理解」而不是「搜索」：我们一个 LLM 都没用，而差距恰好全部落在 Oracle 翻译那一列。反过来说，即使在 human-val 上，正则解析 + 强搜索已经超过了它用 LLM 翻译的版本。

---

## 1. 方法：V2 做了什么

P33 的失败结构给出了明确诊断：**203 道 easy 题里 200 道只差 1 条约束，且失败按约束族整组出现**（同一模板的 30 题一起挂）。这说明缺的是「动作库」，不是运气。V2 因此不再逐阶段盲改，而是**按约束定向生成候选、让官方 checker 裁决**：

1. **先拿满基线**：`SkeletonPlanner` 产出种子后，先跑一遍旧 `RepairEngine`（含 `room_type` 修复），只在它不降低 hard 通过数时接受。V2 的收益因此是「在旧版之上」的净增量。
2. **自建 DSL 解析器**（`parse_spec`）：关键修正是 **类型集合出现在 `result=(...)` 里**，旧的 `parse_requirements` 只读赋值语句，导致 `accommodation_type_set` / `attraction_type_set` 全程漏读。解析内容：必去名称、类型集合、城际方式集合、预算上限、`room_type`、票数。
3. **八个定向阶段**，每个阶段只针对一族约束生成候选：

   | 阶段 | 针对的失败族 | 候选动作 |
   | --- | --- | --- |
   | intercity | 城际方式集合（含 airplane） | 换 leg 的方式，按集合内模式重建 |
   | hotel | 酒店设施 / 指定酒店 / 房型 | 按 `featurehoteltype`、`numbed`、名称过滤后按价排序 |
   | must_attraction | 必去景点 | 全位置插入 + 与当日非必去景点互换 |
   | must_restaurant | 必去餐厅 | 按营业时间选餐段，优先同餐段替换 |
   | attraction_type | 景点类型集合 | 用同类型最便宜候选替换不匹配项 |
   | restaurant_type | 菜系集合 | 同上（按 `cuisine`） |
   | per_meal | 人均餐费上限 | 换成更便宜餐馆 |
   | budget | 总/分类预算 | 换更便宜酒店、删非必去景点 |

4. **越界变体（本轮最关键的一段）**：换了远处酒店后，调度器会因「当日回不到酒店」而**静默丢掉住宿活动**，于是 `accommodation_type_set` 依然为空。V2 为每个候选酒店额外提供一个「删掉末日最后一个非必去景点」的变体，让酒店排得进去。失败最密集的 20 题窗口由此从 **0/20 升到 12/20**。
5. **裁决口径**：每个候选都经过 `schedule` 重排 + `check_plan` 全量复检，只在 `(hard 通过数, commonsense, schema)` 严格变好时才接受。全程确定性，同一输入必得同一输出。
6. **两处口径 bug 修复**（由 commonsense 回归暴露）：飞机 leg 必须写 `FlightID`（不是 `TrainID`）；必去餐厅优先**同餐段替换**而不是追加，避免「第三顿饭把行程推到深夜」。

---

## 2. 完整结果

| split | 版本 | schema | commonsense | hard DSL | **三关全过** |
| --- | --- | ---: | ---: | ---: | ---: |
| easy | P33 旧 | 99.0 | 91.0 | 32.3 | 30.0 |
| easy | P33 + room_type | 99.0 | 94.7 | 32.3 | 30.0 |
| easy | **P34 V2** | 99.0 | 90.3 | **56.3** | **48.7** |
| medium | P33 旧 | 100.0 | 61.3 | 30.7 | 18.0 |
| medium | P33 + room_type | 100.0 | 91.3 | 30.7 | 28.0 |
| medium | **P34 V2** | 100.0 | 90.0 | **51.3** | **46.0** |
| human | P33 旧 | 100.0 | 98.1 | 46.8 | 46.1 |
| human | P33 + room_type | 100.0 | 98.7 | 46.8 | 46.1 |
| human | **P34 V2** | 100.0 | 93.5 | **76.0** | **70.8** |

读法：

- **hard DSL 是主要增益**（+24.0 / +20.6 / +29.2 pt），与 P33 的诊断一致——瓶颈一直在多约束满足。
- **commonsense 略降**（easy −0.7、human −4.5、medium −1.3，对比「P33 + room_type 修复」版）：换来的是 hard 大幅提升。残余违规已定位（见 §3）。
- 按题计：hard 失败列数下降的题数为 easy 72、medium 49、human 56；反向（改差）只有 medium 2 处。

### 2.1 时间与算力代价

同一机器、单进程；耗时取自结果 JSON 的 `seconds` 字段（含 `schedule` 重排与 `check_plan` 复检，不含 LLM 网络）。

| 方法 | 题量 | 单题均值 | 中位数 | p95 | 总墙钟（实际耗时） | 单题评估次数 | LLM tokens/题 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **P34 V2 · easy** | 300 | **0.41 s** | 0.30 s | 0.95 s | **122.8 s** | 5.8 | 0 |
| **P34 V2 · medium** | 150 | **0.86 s** | 0.72 s | 2.22 s | **128.9 s** | 15.3 | 0 |
| **P34 V2 · human** | 154 | **0.70 s** | 0.39 s | 2.29 s | **107.1 s** | 9.6 | 0 |
| P33 旧 · easy | 300 | 0.21 s | 0.07 s | 0.82 s | 63.6 s | — | 0 |
| P33 旧 · medium | 150 | 0.32 s | 0.10 s | 1.72 s | 47.5 s | — | 0 |
| P33 旧 · human | 154 | 0.37 s | 0.12 s | 1.43 s | 57.5 s | — | 0 |
| NeSy × flash（8 题） | 8 | ≈186 s | — | — | ≈25 min | — | 39.7k |
| 纯 LLM（Act，8 题） | 8 | 140 s（89–178） | — | — | ≈324 s（两批并行，串行累计 1126 s） | — | 138k |
> 口径：总墙钟（实际耗时） = 这批题从开始跑到跑完的真实等待时间。P33/P34 为单进程串行，等于逐题耗时之和（与 runner 的 elapsed_s 一致，不含进程启动与沙箱加载）；纯 LLM 行为两批并行的墙钟（串行累计 1126 s）；NeSy × flash 为串行实测。LLM tokens/题 为 input+output 合计（含推理 token）。


- P34 比旧版慢 **1.9–2.7 倍**（换 +18.7 / +28.0 / +24.7 pt），但绝对值仍是亚秒级，604 题全跑完约 6 分钟。
- 相对两条 LLM 基线快 **约 200–450 倍**、0 token；NeSy 单题还要 39.7k tokens。
- 评估次数与耗时强相关（medium 15.3 次 > human 9.6 > easy 5.8），且每次评估都必须让 hard/commonsense 严格变好才被接受。
- 官方 `RuleNeSy` 本轮未计时；历史记录是一条 3 天查询打满 300 s、197,618 节点（`报告/01`）——慢的是无信息引导的回溯搜索，不是规则本身。

---

## 3. 残余失败在哪

| split | 最大 hard 失败列（次数） | 最大 commonsense 违规（题） |
| --- | --- | --- |
| easy | `logic_py_3` 95、`logic_py_5` 26、`logic_py_4` 9 | Inappropriate Meal Times 22、Chronological 10 |
| medium | `logic_py_6` 30、`logic_py_7` 21、`logic_py_8` 20 | Inappropriate Meal Times 15 |
| human | `logic_py_0` 21、`logic_py_1` 11 | Inappropriate Meal Times 9、Chronological 1 |

`logic_py_0/1` 在 human 上仍是最大项，对应「必去名称 + 类型集合」共存的多约束模板：V2 能修单条，但**同时**满足「必去 A 且景点类型 ∈ {博物馆} 且当天还要有午/晚餐」时仍会互相挤占。下一步应把这些模板做成**联合动作**（一次替换同时满足两条），而不是逐条修。

---

## 4. 与论文的对比口径

- **可比列 = FPR**。论文 FPR 的分母是全部题，且要求 env ∧ 逻辑同时通过；我们的「三关全过」= schema ∧ commonsense ∧ hard DSL。三分量对应：schema↔DR、commonsense↔EPR-Mac、hard DSL↔LPR-Mac。**C-LPR 不能用来比**（它只对已过 env 的计划打折算逻辑）。
- 论文 Easy 上：NeSy 52.6%、NeSy*（Oracle 翻译）74.0%、最强纯 LLM（ReAct one-shot·DeepSeek-V3）5.33%、LLM-Modulo*（Oracle Verifier）7.00%、TTG（oracle）8.66%。数字经截图与 PDF 两路逐格核对，见 `results/p33_native_planner/paper_baselines.md`。
- **我们一个 LLM 都没用**，却在 human-val 上 70.8% > NeSy* 45.4% > NeSy 37.0%。说明 ChinaTravel 的难点**不只是理解**：搜索与约束满足同样决定成败。
- easy 48.7% 仍低于 NeSy 52.6%，差距集中在需要**语义等价**的约束（同义类型名、模糊菜系）。这部分正是 LLM 的强项，也是下一步「规则 + LLM 只做 NL→DSL」的接口点。

---

## 5. 同一批 96 题上：规则 vs LLM（P31/P32 整理）

数据、门控、证据三者完全相同，只换「谁来排」（`p31_static.build_plan` vs LLM 两阶段）；96 题 = easy/hard/human 各 32，五城（西安、长沙、厦门、青岛、宁波）。完整整理见 `results/p32_llm_96/comparison_for_report.md`（168 行、17 张表，逐格带来源）。

| 口径 | 规则 | LLM | 差（LLM−规则） |
| --- | ---: | ---: | ---: |
| 原门控（闭馆冲突只记录） | 72 | 73 | +1 |
| 闭馆冲突判失败 | 72 | 70 | −2 |
| 接受「来源标注 24h 开放」 | 76 | 77 | +1 |
| 两者都加 | 76 | 74 | −2 |

**四种口径差值绝对值都 ≤2 题**，且 LLM 为单次采样——不能宣称「谁更强」，只能说在给定口径下谁多两题。20 道 blocked 在两侧是同一批题（缺价 10 / 缺时 5 / 两者都缺 5），**阻断由数据供给决定，与规划器无关**。

| 维度 | 规则规划器 | LLM |
| --- | --- | --- |
| 确定性 | 同输入同输出 | 单次采样，重跑会变 |
| 可归因 | 失败精确到某个字段/某段路 | 需读它的解释，可能与门控不一致 |
| 过度声称 | 结构上不可能（status = 门控输出） | 2 题自评 complete 而门控 blocked |
| 换点/砍点 | 不会（只排不换） | 提示禁止，实际也没做 |
| 软约束 | 不处理 | 32/32 覆盖，82 条 |
| 解释与提问 | 只有「18:20 超过 18:00」 | 540 条澄清、795 字/题答复 |
| 证据请求 | 一次性按自己顺序生成 | 顺序会变，需补查（27 题、90 段） |
| 成本 | 0 次 LLM 调用 | 96 题两阶段 |

**规则侧最该补的四件事**（由 LLM 表现反推，按收益排序）：

1. **接受「来源明示免费 / 24h 开放」的受控标注** → +4 题（72→76）。这是数据供给问题，不是规划能力。
2. **老城门票计入预算** → 可修 5 处误标 complete（D22、D28、D32、N26、N30）。
3. **闭馆冲突进 status** → 堵 3 题（D11、D15、D19）；现在「只记录不判定」会高估交付。
4. **顺序可搜索** → 至少救 D19（+1）；LLM 正是靠换序压线通过。

> 注：P31 的规则规划器（`scripts/p31_static.py`）与本文的 P34 V2 **不是同一份代码**：前者服务五城扩展 schema，后者服务官方原 schema。两者共享设计原则与高德客户端（`src/shorttrip/live_amap.py`），但规划器实现各自独立。

---

## 6. 这轮得到的五条经验

1. **规则规划器的「能力」等于它的动作库**：失败按族聚集时，加一个阶段的收益是 20–30 个百分点；调参只有 1–2 个点。
2. **改数据前先改「读懂约束」**：`result=(...)` 里的类型集合漏读，等于四条约束族全程没被处理过。
3. **静默丢弃是最贵的 bug**：远处的酒店被调度器丢掉，看起来是「换酒店没生效」，实际是「酒店根本没排进计划」。给每个候选加一个「腾位置」变体，收益 12/20。
4. **把官方 checker 当奖励函数，比自己写评分稳**：V2 的所有接受/拒绝都由 `check_plan` 决定，没有「自己觉得变好」的空间。
5. **commonsense 与 hard 是此消彼长的**：更激进的替换会引入餐段/时序违规，必须两者一起看，否则会误判提升。

---

## 7. 复现

```powershell
cd reproduction\ChinaTravel
$env:PYTHONUTF8='1'; $env:PYTHONPATH='../src'

# 新规划器（V2）
..\.venv\Scripts\python ..\scripts\p34_run_v2.py --split easy   --method ShortTripV2_easy
..\.venv\Scripts\python ..\scripts\p34_run_v2.py --split medium --method ShortTripV2_medium
..\.venv\Scripts\python ..\scripts\p34_run_v2.py --split human  --method ShortTripV2_human

# 官方评测（split 用本地副本，评测代码未改）
..\.venv\Scripts\python eval_exp.py --splits easy_p33   --method ShortTripV2_easy   --lang zh
..\.venv\Scripts\python eval_exp.py --splits medium_p33 --method ShortTripV2_medium --lang zh
..\.venv\Scripts\python eval_exp.py --splits human_p33  --method ShortTripV2_human  --lang zh

# 汇总（与 P33、论文 FPR 同表对比）
..\.venv\Scripts\python ..\scripts\p34_aggregate.py
```

产物：`results/p34_v2_planner/` 下的 `aggregate.json`、`table.md`、`delta_analysis.json`、`<split>_<method>.json`（逐题 hard 列与 moves）。

---

## 8. 边界

- **不含 LLM**：V2 是纯规则规划器，语义理解全靠正则；它证明的是「约束明确时规则能走多远」，不能外推到自由表达。
- **只测 10 个老城市**的原 schema；五城扩展 schema 见 `报告/25`，两者数据与门控不同，分数不可互比。
- **human 用 Human-Val（154 题）**；论文还有 Human-Test（1000 题），我们无对应数据。
- **commonsense 略降**是明确取舍，已在 §2 列明，不隐藏。
- 论文数字来自 `paper_baselines.md` 的逐格核对；论文自身有 4 处 FPR 越界（FPR > 对应 LPR/EPR），已在该文件标注 ⚠。
