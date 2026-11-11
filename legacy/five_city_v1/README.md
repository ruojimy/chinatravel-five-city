# ChinaTravel 五城静态参考与规划器复现包

**版本**：v1（2026-11-01）
**范围**：西安、厦门、宁波、长沙、青岛 × ChinaTravel 七类原生表
**内容**：数据采集与结构化代码、TAG、规则规划器、动态检索测试、自动化采集闭环、报告与评估工件。

> 这是一个**研究性复现包**，不是可商用的旅行数据产品。数据中的第三方来源权利未被本包授予；原始网页正文已从发布数据中移除，只保留来源索引与哈希。

---

## 1. 这个包解决什么问题

ChinaTravel 原始沙盒只有 10 个城市。本项目做三件事：

1. **把五座新城市补成 ChinaTravel 原生七表**（景点、餐厅、酒店、POI、地铁、火车、航班），每条值带来源、抓取时间、字段级证据；
2. **给数据加 TAG 与置信度**：字段状态、证据等级、实体核验、时钟/TTL、许可、不确定性标记；
3. **用规则规划器 + 动态检索测试数据和 schema**：P31 五城 96 题、P34 官方 schema 604 题、以及 manual 开发集的严格诊断。

## 2. 关键数字

| 项 | 数值 |
| --- | ---: |
| v4 记录 | 1,914（地铁 970、POI 494、餐厅 125、景点 123、火车 74、航班 64、酒店 64） |
| 证据 / claim / TAG | 3,598 / 5,790 / 6,072 |
| 全字段非空记录 | 1,607 |
| 被合规拒绝实体 | 37（厦门 24、长沙 8、西安 5） |
| `planning_ready` | **0**（设计门槛：缺观察时间/实体核验/许可） |
| P31 五城 96 题 | **72 complete / 20 blocked / 4 infeasible** |
| P34 官方 schema 三关全过 | easy 48.7% / medium 46.0% / human 70.8% |
| 动态调用（P31） | 468 次（450 主 + 18 详情） |

## 3. 目录

```
code/src/shorttrip/       采集、证据、TAG、规划器、严格核验、动态检索模块
code/scripts/             P30–P34 与 collection_agent 入口
data/                     五城 v4 的脱敏导出（records/claims/tags/evidence index）
results/p31/              96 题任务、最终计划、评估表、调用账本
results/p34/              官方 schema 规划器汇总与表格
results/manual/           manual 开发集的审计摘要（不含原始网页）
reports/                  24–33 号报告与验收/自动化说明
automation/               采集闭环的 README、prompt、来源清单、示例配置
```

## 4. 快速开始

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

- **只想看数据**：`data/records.jsonl.gz`、`claims.jsonl.gz`、`tags.csv.gz`、`evidence_index.jsonl.gz`。
- **想复现 P31 评估**：先准备本地完整 v4 catalog（本包因许可原因未放 `raw_text`，无法直接重跑 quote 门），再运行 `code/scripts/p31_prepare.py → p31_static.py → p31_retrieve.py → p31_detail.py → p31_finalize.py`。
- **想复现 P34**：需要 ChinaTravel 官方仓库与 `eval_exp.py`；本包只放规划器与运行脚本，不包含官方基准数据。
- **想看规划器**：`code/src/shorttrip/planner_v2.py`（P34 V2）、`strict_*`（新 schema 严格核验）。

## 5. 数据与许可（务必读）

- 本包**不包含**原始网页正文（`raw_text`）；`evidence_index.jsonl.gz` 只保留 `source_url`、`retrieved_at`、`licence_status`、`authority`、`capture_method`、`raw_sha256`。
- 第三方来源的权利未随本包授予；许可未知的证据有 554 条，使用前需逐条确认。
- 代码（`code/`）按 MIT 发布；数据（`data/`）仅供研究与复现，不构成再分发授权。
- 本包中的价格、营业时间、班次都是**静态参考**，不是实时库存/票价；不能直接用于真实出行。

## 6. 已知边界

- `planning_ready=0`：0/1914 有 `observed_at`，0/1914 `entity_verified=true`；这不是数据为空，而是门要求实时核验。
- 37 个实体因合规剔除整条拒绝；7 个实体部分剥离。
- 1 条单位异常：长沙 `G1692/G1693` 的 `Duration=409` 是分钟，不是小时。
- 216 条坐标非 WGS84（餐厅 68、酒店 24、POI 117、景点 7）。
- manual 开发集 60/60 `data_block`，没有形成完整计划；它测的是核验/上下文缺口，不是新地点采集。

## 7. 引用

如果用于课程/论文，请引用本仓库与 `reports/` 中的对应报告；数据来源请按 `DATASET_CARD.md` 的逐项许可说明处理。
