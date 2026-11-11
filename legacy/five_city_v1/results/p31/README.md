# P31 五城 96 题分层测试（结果目录）

本目录是 2026-10-26 的一次**规则规划器 + 高德动态检索**实验，测试扩张后的五城静态数据集（`data/five_city_reference_v4_20261026`）能否支撑 easy/hard/human 三层旅游需求，以及动态检索能补上哪些缺口。

## 结构

| 路径 | 内容 |
| --- | --- |
| `tasks/` | 96 题：`easy.json` / `hard.json` / `human.json` / `all_96.json`（每层 32 题） |
| `protocol.json` | 设计说明：城市、日期、分层、预算与检索口径 |
| `static/` | 静态阶段的草案计划与逐题请求（未联网） |
| `retrieval/responses/<uid>/` | 450 条高德响应原文（weather 116、route 311、place 23），含参数、`retrieved_at`、`infocode`、`sha256` |
| `retrieval/details/<uid>/` | 18 条补充详情调用（`/v3/place/detail`），用于补营业时间 |
| `retrieval/ledger.json` / `detail_ledger.json` | 逐次调用账本（无重试、无换 Key） |
| `final/plans_*.json` | 应用证据后的最终计划、校验与状态 |
| `evaluation_all_96.csv` | 逐题评估表 |
| `summary_all_96.json` | 分层/分城市汇总 |
| `validation.json` | 一致性校验：96 题 / 450 请求 / 450 响应 / 0 错误 |

## 结果摘要

- **72/96** 形成“字段、时段、预算、路线、天气”都通过的条件方案；**20** 因票价/营业时间缺失被阻断；**4** 因真实通行时间超出窗口不可行。
- 分层：easy **32/32**，hard **19/32**（10 blocked、3 infeasible），human **21/32**（10 blocked、1 infeasible）。
- 动态调用 **468 次**（450 主 + 18 详情），平均 **4.88 次/题**；天气 116/116 返回，路线 276 段动态 + 35 段短距步行，place 19/23 匹配到坐标，**0/23 返回营业时间**；详情调用 11/18 返回营业时间。
- 城市：西安 21/21、长沙 14/20、厦门 14/19、宁波 13/17、青岛 10/19。

## 复现

```bash
python scripts/p31_prepare.py      # 生成 96 题（读 v4 + 旧库，不联网）
python scripts/p31_static.py       # 静态草案与请求
python scripts/p31_retrieve.py --max-calls 520 --task-budget 8
python scripts/p31_detail.py --max-calls 40
python scripts/p31_finalize.py
python scripts/p31_validate.py
```

`p31_retrieve.py` 会跳过已存在的响应文件，可断点续跑；遇到配额/限流错误会写入 ledger 并停止，不重试、不换 Key。

## 边界

- `complete` 是规则校验结果（字段齐全、开放时段、预算、路线证据、天气），**不是现实可执行性认证**；票价与营业时间仍是静态参考或第三方提取。
- 规划器是确定性规则系统，不是 LLM；human 层是研究者写的自然表达，不是真人采样。
- 天气只覆盖 2026-10-26 至 10-29（高德预报窗口）；所有行程日期都在窗口内。
- 城际时刻沿用 v4 冻结记录，没有调用实时班次接口。
