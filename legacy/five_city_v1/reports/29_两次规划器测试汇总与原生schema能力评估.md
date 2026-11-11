# 两次规划器测试汇总：P31 扩展 schema 与 ChinaTravel 原生 schema

**测试窗口**：2026-10-26 至 10-28（北京时间）。**两次测试**：

| | P32（扩展 schema） | P33（原生 schema） |
| --- | --- | --- |
| 题目 | P31 五城 96 题（easy/hard/human 各 32） | ChinaTravel 官方 easy 300 / medium 150 / human 154 |
| 城市 | 西安、厦门、宁波、长沙、青岛 | 原沙盒 10 城（北上杭宁苏广深成渝汉） |
| 规划器 | P31 确定性规则规划器（`p31_static/finalize`） | ShortTrip `SkeletonPlanner` + `RepairEngine`（确定性、无 LLM） |
| 对照 | LLM 子代理 96 题 ×2 阶段（192 份稿） | 无 LLM；与论文 Table 3 的 LLM 基线对比 |
| 门控 | 自定义五项检查（字段/开放/路线/预算/天气） | 官方 `eval_exp.py`：schema + commonsense + hard DSL |
| 证据 | 2026-10-26 高德冻结证据 + 90 段补查 | 本地沙盒，纯离线 |
| 报告 | `27_规则规划器与LLM在P31_96题上的对照.md` | `28_规则规划器在ChinaTravel原schema的测试.md` |

**一句话总结**：P31 扩展 schema 上，规则规划器 72/96、LLM 73/96（严格口径 70，标签感知 77），完成率由数据和门控定义决定；到了 ChinaTravel 原生 schema，规则规划器的**结构交付 99–100%、环境一致 91/61/98%、逻辑约束 32/31/47%、三关全过 30/18/46%**。它的能力画像不是“会规划”，而是**“能稳定交付结构合法、沙盒一致的草案；不能稳定完成组合约束”**。与论文 Table 3 相比：Easy 上明显低于 LLM NeSy（52.6）和 Oracle NeSy（74.0）；Human-154 上与 Oracle NeSy 基本持平（46.1 vs 45.4），并高于标准 LLM NeSy（37.0）。

---

## 0. 关键数字一页

### 0.1 P32（扩展 schema，规则 vs LLM）

| 门控口径 | 规则 | LLM |
| --- | ---: | ---: |
| P31 原门控 | **72** | **73** |
| + 闭馆冲突判失败 | 72 | 70 |
| + 接受来源 24h 开放 | 76 | 77 |
| 两者都加 | 76 | 74 |

- 95/96 逐题状态相同；唯一差异 D19（规则超窗，LLM 换序后 18:30 回站，但门控记录了总督楼闭馆冲突）。
- LLM 自评 75，过度声称 2（D13、N21），严格口径 5；低报 0。
- LLM 软约束 32/32、澄清 540 条、答复 795 字/题；规则 0/0/0。

### 0.2 P33（原生 schema，规则规划器）

| split | 题数 | DR（schema） | EPR（commonsense） | LPR macro | C-LPR | FPR（三关全过） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| easy | 300 | 99.0% | 91.0% | 32.3% | 30.0% | **30.0%** |
| medium | 150 | 100% | 61.3% | 30.7% | 18.0% | **18.0%** |
| human | 154 | 100% | 98.1% | 46.8% | 46.1% | **46.1%** |

修复 `room_type` 后：EPR 94.7 / 91.3 / 98.7；FPR 30.0 / 28.0 / 46.1。

### 0.3 与论文（Easy/Human-Val，DeepSeek 首行）

![规则规划器 vs 论文 LLM](../results/p33_native_planner/fig_vs_paper.png)

| 方法 | DSL 来源 | Easy DR | Easy EPR Mac | Easy LPR Mac | Easy FPR | Human DR | Human EPR Mac | Human LPR Mac | Human FPR |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **本报告规则规划器** | **gold** | **99.0** | **91.0** | 32.3 | **30.0** | **100** | **98.1** | 46.8 | **46.1** |
| NeSy Planning（论文） | LLM | 75.3 | 75.3 | 52.6 | 52.6 | 51.9 | 52.5 | 37.6 | 37.0 |
| NeSy Planning*（论文，Oracle） | gold | 82.6 | 75.0 | 75.3 | 74.0 | 58.4 | 57.7 | 46.1 | 45.4 |
| ReAct one-shot | 无 | 77.5 | 6.00 | 52.3 | 5.33 | 55.2 | 57.3 | 44.2 | 2.59 |
| Act | 无 | 70.4 | 0 | 30.6 | 0 | — | — | — | — |
| LLM-Modulo*（Oracle Verifier） | 无 | 48.3 | 4.33 | 43.6 | 4.33 | 61.6 | 2.59 | 51.2 | 2.59 |
| TTG（oracle） | 无 | 18.3 | 8.66 | 15.0 | 8.66 | 9.09 | 2.59 | 5.19 | 1.29 |

> 指标对齐：DR = Delivery Rate（本报告 schema）、EPR = Environmental Pass Rate（commonsense）、LPR = Logical Pass Rate（hard DSL）、C-LPR = Conditional LPR、FPR = Final Pass Rate（三关全过）。论文数值取自 ICLR 2026 版 Table 3 的 DeepSeek 首行（Easy #300、Human-Val #154）。

### 0.4 这四个指标到底在说什么

把它们想成四道**串联的门**，每一道都只回答一个问题：

| 指标 | 一句话 | 具体查什么 |
| --- | --- | --- |
| **DR**（Delivery Rate / schema） | **计划交得出来吗？** | JSON 结构：`people_number`、`start_city`、`target_city`、`itinerary` 必须有；每天有 `activities`；每个活动有 `type`、`start_time`、`end_time`、`cost`、`price`、`transports`；每个 transport 有 `start`、`end`、`mode`、`start_time`、`end_time`、`price`、`cost`、`distance`。少字段、时间格式不对、活动类型不在枚举里 → 这题 DR=0。 |
| **EPR**（Environmental Pass Rate / commonsense） | **计划里写的是真的吗？** | 拿沙盒核对：景点/酒店/餐馆存在吗？访问时间在营业时间内吗？车次/航班 ID、起终站、价格、耗时对得上吗？酒店价格/房型/房数对得上吗？每段地铁/步行的时长和距离与 `goto` 一致吗？活动时间不重叠、不早于 0 点吗？27 个违规列，任一列=1 → 这题 EPR=0。 |
| **LPR**（Logical Pass Rate / hard DSL） | **用户的要求满足了吗？** | 把 query 的 `hard_logic_py` 逐条执行：天数、人数、总预算、必去景点/酒店/餐馆、房型/房数、城际方式、市内交通方式、人均每餐…… |
| **C-LPR**（Conditional LPR） | **先过环境关，再数逻辑关。** | 防止“假价格/假时间骗过预算”：预算写 800 就过 LPR，但 EPR 会发现沙盒价格是 1200。C-LPR 只在 EPR 已过的计划里数 LPR。**注意**：本仓库 `eval_exp.py` 的实现把分母取全部题（等于 EPR∧LPR 占比）；论文 Table 3 的 C-LPR 看起来按 EPR 过的题做分母（如 52.6/75.3≈70.4）。所以跨论文比较只看 FPR，C-LPR 只做本仓库内部参考。本次所有过 EPR 的计划都过了 DR，所以本仓库的 C-LPR 与 FPR 数值相同。 |
| **FPR**（Final Pass Rate） | **三关全过。** | 只有 DR=1 且 EPR=1 且 LPR=1 才算完成；这是唯一能说“这题做完了”的指标。 |

**macro 和 micro 的区别**：LPR 的 macro 是“**全部约束都过**才算这题过”（严格，用户视角）；micro 是“这题过了**多少比例**的约束”（部分分，诊断视角）。例：5 条约束过 4 条 → macro=0，micro=0.8。

**拿一道 Easy 题走一遍**：1 人、上海→杭州 1 天、预算 1500；`hard_logic_py` 5 条：`day_count==1`、`people_count==1`、`total_cost<=1500`、景点/火车票==1、地铁票==1。

- **DR**：JSON 结构齐全 → 1。
- **EPR**：杭州景点在沙盒且开放；G 字头车次在表里且起终站/价格/耗时一致；3 段地铁/步行与 `goto` 一致；时间不重叠 → 1。
- **LPR**：5 条全过 → macro=1；过 4 条 → macro=0，micro=0.8。
- **FPR**：三者都 1 → 1。

**为什么会出现“macro 32.3%、micro 86.4%”这种反差**：Easy 300 题里，只有 97 题**全部**约束都过（macro 32.3%）；但平均每份计划已经满足 86.4% 的约束（micro 86.4%）。203 个失败题里 200 个只差 1 条——**计划“几乎都对”，但没有一份“完全对”**。所以 FPR 低，不等于计划不可用；它表示“离完成还差最后一条”。

**我们表里的具体计数**：

| split | 题数 | DR 过 | EPR 过 | LPR 全过 | FPR 过 |
| --- | ---: | ---: | ---: | ---: | ---: |
| easy | 300 | 297 | 273 | 97 | 90 |
| medium | 150 | 150 | 92 | 46 | 27 |
| human | 154 | 154 | 151 | 72 | 71 |

- Easy：3 题没交计划（DR=0），所以 DR 297；EPR 273；LPR 全过 97；三关全过 90。
- Medium：DR 150，但 EPR 只有 92（58 题酒店 `room_type` 对不上）；LPR 全过 46；三关全过 27。
- Human：DR 154、EPR 151、LPR 全过 72、三关全过 71。

**为什么不能只看 DR**：ReAct one-shot 的 DR 是 77.5%，但 EPR Mac 只有 6.00%，FPR 5.33%——**格式对、内容假**。DR 高不代表计划能用；FPR 才是“真的做完”。

---

## 1. P32 回顾：扩展 schema 上规则与 LLM 的差异

### 1.1 规则规划器的水准

- 72/96 complete；20 blocked（只缺价 10、只缺时 5、两者都缺 5）、4 infeasible（D05、D13、D19、N17）。
- 静态 68/96 → 动态 72/96；450 请求 + 18 详情，0 重试；`build_plan` 重跑与存档的规范化 SHA256 完全一致。
- 每个失败都能归因到字段、路段或窗口；不换点、不砍点、不处理 32 道软约束、不解释、不提问、不读 24h 标签。

### 1.2 LLM 的增量与风险

- 增量：解释、澄清（5.62 问/题）、软约束（32/32）、缺口优先级、取舍建议（N17“放宽回站或压缩游览”）。
- 风险：2 次过度声称（D13 压缩停留做成、N21 接受 24h 标签）、4 次闭馆冲突（D11/D13/D15/D19）、同一类标签在 D18 判冲突、在 N21 判已核实。
- 95/96 逐题状态与规则相同；完成率上限由数据和证据决定，规划器只移动 ±3 题。

### 1.3 两个必须记住的修正

1. **“7 道靠详情补齐”不准确**：逐题复核只有 N10（厦门方特）是详情返回 9:30–21:00 救回的；D07/D17/N15/N20 是餐馆营业时间、D26/D32 是酒店坐标——最终门控根本不检查这两类字段。7 道“救回”里 6 道是门控口径变化。
2. **串联预算漏老城门票**：`budget_for(atts, None, hotel, leg)` 没算 `old_city`；把颐和园/东方明珠门票计入后，20 道串联题里 9 道实际超预算，其中 4 道仍被标 complete。

**P32 的结论**：扩展 schema 的 72/96 不是“规则规划器有 75% 的规划能力”，而是“在当时的字段供给和门控定义下，72 道题能凑齐五项检查”。它测的是数据与门控，不是原生 benchmark 的完整约束。

---

## 2. P33：规则规划器在原生 schema 上的能力剖面

### 2.1 四关拆开看

| 关卡 | 含义 | 规则规划器 | 判断 |
| --- | --- | ---: | --- |
| DR | 能不能交出一份结构合法的计划 | 99.0 / 100 / 100 | **强**：几乎必交付 |
| EPR | 计划是否与沙盒一致（价格/时间/路线/房型） | 91.0 / 61.3 / 98.1（修复后 94.7 / 91.3 / 98.7） | **强**：确定性算术，修一个字段 bug 就回到 90+ |
| LPR | 是否满足全部 DSL 约束（macro） | 32.3 / 30.7 / 46.8 | **弱到中**：真正的瓶颈 |
| FPR | 三关全过 | 30.0 / 18.0 / 46.1 | **只能算“草稿生成器”** |

### 2.2 失败结构：不是不会做，是最后一条没修上

- easy 203 题有 hard 失败，其中 **200 题只差 1 条约束**；3 题无计划（返程车站当日不可达）。
- medium 104 题失败：56 题差 1 条、31 题差 2 条。
- human 82 题失败：59 题差 1 条。
- 合计 **315/389 个失败题只差一条约束**。

失败类型（题数，easy/medium/human）：

| 类型 | easy | medium | human |
| --- | ---: | ---: | ---: |
| 指定景点名 | 30 | 41 | 24 |
| 指定餐馆名 | 30 | 1 | 0 |
| 指定酒店名 | 30 | 0 | 0 |
| 酒店设施 | 30 | 21 | 4 |
| 景点类型 | 10 | 19 | 30 |
| 菜系 | 24 | 21 | 16 |
| 城际方式 | 17 | 31 | 14 |
| 市内交通方式 | 23 | 8 | 0 |
| 预算 | 9 | 21 | 19 |
| 人均每餐 | 0 | 12 | 0 |

同一模板的 30 题整组失败，说明是**修复器缺少该模板对应的能力**，不是随机误差。

### 2.3 五个可修缺陷

1. **`room_type` 只改字段不换酒店**（已修，可选开关）：medium 58 题 commonsense 全挂；修后 61.3% → 91.3%，FPR 18% → 28%。
2. **指定餐馆一律按午饭插入**：南京“小酒小肉烤串店”16:30 才开门，按午饭排会被调度丢掉（easy 30 题）。
3. **酒店设施没按 `featurehoteltype` 搜索**：`accommodation_type_set` 在 `_present_types` 里对 accommodation 直接跳过（easy 30、medium 21、human 4）。
4. **只插入、不替换/不砍点**：当天排满就放弃指定景点。重庆“人民大礼堂”在表里、08:00–18:00 开放，但两天行程已满，插不进去（easy 30、medium 41）。
5. **人均每餐上限没修**：`food_cost/food_count/people_count <= 60..100` 不在 budget 阶段（medium 12）。

另有 3 条 easy 无计划：返程车站与当日可达性冲突（如 15:15 前到南京站赶车，按沙盒 `goto` 18:14 才到）。

### 2.4 能力结论

> **规则规划器在原生 schema 上是一名“结构交付 + 沙盒一致性”很强的执行器，不是“组合约束求解器”。**
>
> - 交付：A（99–100%）
> - 环境一致性：A−（91–98%，修一个 bug 后 91–99%）
> - 逻辑约束：C（32–47% macro）
> - 三关全过：D+ ~ C（30% Easy、18% Medium、46% Human）

---

## 3. 与 ChinaTravel 论文的 LLM 结果对比

### 3.1 先对齐口径

- 论文 Table 3 的分裂：Easy #300、Human-Val #154、Human-Test #1000；本报告 P33 的 easy 300、human 154 与之一致（`human` 154 对应 Human-Val；未逐 uid 核对论文 split 文件，但数量与仓库 `default_splits/human.txt` 一致）。
- 指标：DR / EPR / LPR / C-LPR / FPR，定义与官方 checker 一致。
- 论文的 NeSy Planning 用 LLM 把自然语言译成 DSL；NeSy Planning* 用 **gold DSL**。我们的规划器直接读 query 的 `hard_logic_py`（gold DSL），所以**公平对照是 NeSy Planning\***，而不是标准 NeSy。

### 3.2 三个发现

**发现 1：规则规划器的“交付/接地”远好于论文方法。**
Easy 上 DR 99.0 vs NeSy 75.3 / Oracle 82.6；EPR Mac 91.0 vs 75.3 / 75.0。Human 上 DR 100 vs 51.9 / 58.4；EPR Mac 98.1 vs 52.5 / 57.7。规则规划器几乎不会交出“结构不合法/沙盒对不上”的计划，这是确定性算术的天然优势。

**发现 2：Easy 上逻辑约束明显落后，Human 上基本追平。**
- Easy LPR Mac：规则 32.3 vs 标准 NeSy 52.6 vs Oracle NeSy 75.3。差 20–43 个百分点。
- Human LPR Mac：规则 46.8 vs 标准 NeSy 37.6 vs Oracle NeSy 46.1。规则略高于标准 NeSy、与 Oracle 持平。
- 这说明：**Easy 的差距是搜索能力**（NeSy 会回溯/组合搜索，规则只做单阶段贪心修复）；**Human 的差距主要是 NL→DSL 翻译**（标准 NeSy 丢掉约束，规则直接用 gold DSL，所以反超）。

**发现 3：FPR 的排序与 LPR 基本一致。**
- Easy：规则 30.0 < 标准 NeSy 52.6 < Oracle NeSy 74.0。
- Human：标准 NeSy 37.0 < 规则 46.1 ≈ Oracle NeSy 45.4。

也就是说：**在 Easy 上，规则规划器落后于论文的 LLM+搜索；在 Human 上，它大致等于“LLM 译 DSL + 搜索”的 oracle 上限，并高于标准 LLM 版。** 不能简单说“规则规划器比 LLM 强/弱”，要看 split 和 DSL 来源。

### 3.3 为什么 Easy 会差这么多

Easy 的 hard 约束以“指定景点名/餐馆名/酒店名/酒店设施/票数/预算”为主，约束数量少但要求精确。NeSy 的深度优先搜索会为一条必去约束重排整天、换酒店、换车次；规则修复器只会：

- 在 day 0 的位置 0/1/末尾试插；
- 不替换已有景点；
- 不重选返程车次；
- 指定餐馆一律按午饭；
- 酒店设施不搜。

于是 200/203 个 Easy 失败只差一条约束，但就是修不上。**差距不在“会不会生成计划”，而在“会不会为一条约束重排整个计划”。**

### 3.4 其他论文方法的位置

- Act / ReAct / LLM-Modulo / TTG 的 Easy FPR 都在 0–8.66%，说明原 benchmark 的难点是**逻辑约束 + 环境一致性同时满足**；只有 NeSy 家族能到 50%+。
- ReAct one-shot 的 DR 77.5、LPR Mac 52.3 看起来不低，但 EPR Mac 只有 6.00，FPR 5.33——**结构合法不等于沙盒一致**。规则规划器的 EPR 91.0 是它相对这些 LLM-only 方法的真正优势。
- LLM-Modulo 的 EPR Mic 94.5、EPR Mac 4.33，也是“大部分约束满足、但几乎没有一份全过”的典型。

---

## 4. 两次测试合起来说明什么

1. **P31 的 72/96 不能外推成“规则规划器有 75% 的 ChinaTravel 能力”。** 扩展 schema 的门控更宽、数据供给更好、没有原 benchmark 的组合硬约束；换到原生 schema，三关全过是 30/18/46。
2. **规则规划器的强项是“接地”而不是“求解”。** DR 99–100、EPR 91–98；LPR 32–47。它的失败几乎都能归因到一条具体约束，而不是“计划不可用”。
3. **Easy 与 Human 的差异说明瓶颈会转移。** Easy 缺的是搜索/回溯；Human 缺的是 NL→DSL 翻译——规则规划器因为拿到 gold DSL，反而在 Human 上追平 Oracle NeSy。
4. **论文的 LLM+NeSy 仍然是原生 schema 上的更强方案**：Easy 52.6/74.0 vs 规则 30.0；Human 标准版 37.0 低于规则 46.1，但 Oracle 版 45.4 与规则持平。**规则规划器适合做 oracle-DSL、无 LLM、可复算的基线，不适合替代搜索。**

---

## 5. 建议

### 5.1 对规则规划器

1. 修 5 个缺陷：`room_type` 换酒店（已做）、指定餐馆按营业时间选 meal slot、酒店设施索引、允许替换/砍非必去项、人均每餐预算。
2. 给 `names` 阶段加“为一条必去约束重排当天/改返程车次”的动作；这是 200 道 Easy 题的直接来源。
3. 评测时同时报 DR/EPR/LPR/FPR；只看 DR 会把“结构合法但沙盒不一致”的方法排到前面（ReAct 就是例子）。

### 5.2 对 P31 扩展 schema

1. 先修门控：闭馆冲突入 status、24h/免费受控通道、串联预算含老城门票。
2. 再谈“规则 vs LLM”的完成率；当前 72/73 的差异在门控口径内不稳健（严格 72/70，标签 76/77）。

### 5.3 对系统架构

- **LLM 负责 NL→DSL、解释、澄清、软约束；符号搜索负责组合约束；规则门控负责接地、算术、拒绝与留痕。**
- 规则规划器的正确位置是“交付前的确定性检查器 + oracle-DSL 基线”，不是“替代 NeSy 搜索”。

---

## 6. 文件与复现

| 内容 | 路径 |
| --- | --- |
| P32 报告（扩展 schema，规则 vs LLM） | `报告/27_规则规划器与LLM在P31_96题上的对照.md` |
| P33 报告（原生 schema，规则） | `报告/28_规则规划器在ChinaTravel原schema的测试.md` |
| P32 数据 | `results/p32_llm_96/`（192 稿、评分、对照、补查证据） |
| P33 数据 | `results/p33_native_planner/`（逐题结果、aggregate、failure_structure） |
| 原生 schema 计划 | `ChinaTravel/results/ShortTrip_*` |
| 官方 eval CSV | `ChinaTravel/eval_res/splits_*_p33/ShortTrip_*` |
| 论文 Table 3 截图 | `results/p33_native_planner/paper_table3.png` |
| 对比图 | `results/p33_native_planner/fig_vs_paper.png` |
| P32 归档 | `规则规划器与LLM对照_P32_20261026.zip` |
| P33 归档 | `规则规划器原schema测试_P33_20261028.zip` |

复现命令见两份分报告；P33 的核心命令：

```bash
# 从 reproduction/ChinaTravel
python ../scripts/p33_run_native_planner.py --split easy   --method ShortTrip_easy
python ../scripts/p33_run_native_planner.py --split medium --method ShortTrip_medium
python ../scripts/p33_run_native_planner.py --split human  --method ShortTrip_human
python eval_exp.py --splits easy_p33   --method ShortTrip_easy   --lang zh
python eval_exp.py --splits medium_p33 --method ShortTrip_medium --lang zh
python eval_exp.py --splits human_p33  --method ShortTrip_human  --lang zh
python ../scripts/p33_aggregate.py
python ../scripts/p33_failure_structure.py
```

---

## 7. 局限

- 两次测试用的是**两个不同的规划器**：P32 是 `p31_static/finalize`，P33 是 ShortTrip `SkeletonPlanner + RepairEngine`；不能把 P32 的 72/96 与 P33 的 30/18/46 当成同一系统的两个分数。
- P33 的规则规划器直接读 gold `hard_logic_py`，因此对照论文的 **Oracle Translation** 行，而不是标准 LLM 行；这不是“规则规划器优于 LLM”的证据。
- 论文 Table 3 的 Human-Val 154 与仓库 `human` 154 按数量对齐，未逐 uid 核对论文 split 文件。
- 论文数值是单次运行；本报告规则规划器是确定性单次运行（P33 无方差，P32 LLM 只有单次采样）。
- 原生 schema 测试使用本地 split 目录（官方 query 副本）以避开 HuggingFace 拉取；官方评分代码未改。
- `complete`/`FPR` 是 checker 通过，不是现实可执行认证。
