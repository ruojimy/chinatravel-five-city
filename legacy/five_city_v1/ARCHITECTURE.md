# 架构说明

## 1. 五层结构

```
采集层       P29 检索器 / P30 直连 / API / 官方 PDF
  ↓
证据层       record + field_provenance + evidence + claim + tags
  ↓
规划层       P34 ConstraintPlannerV2（官方 DSL）
             strict_*（新 schema：多日业务链/成本/住宿/城际/事件）
  ↓
动态检索层   weather / transit / place / detail（高德），带预算与账本
  ↓
自动化层     collection_agent / collection_session / 运行锁 / 配额门
```

## 2. 采集与证据

- 采集以 worker 为单位，一城一目录，交付 `bundle.json + sources/ + requests.jsonl + README.md`；
- 每个字段必须有 `raw_text` 中的精确 quote；没有 quote 的字段走“本地派生”占位；旧记录同值走继承；
- `evidence_id = sha256(source_id + raw_text + 三个时钟 + retrieved_at)`；同一段原文只存一份；
- 状态：`source_value / estimated / derived / unknown / synthetic`；记录带 `entity_verified`、`trust_status`、`needs_live_verification`、`uncertainty_flags`。

## 3. TAG

- `tags = [{tag, value, basis:{source_index, quote}, status, policy_id, source_time_ref, valid_until}]`；
- 6072 个 TAG：结构性 `kind`、`native_fields_complete` 各 1914；地铁线路/网络各 970；业务 304；
- TAG 不是自由文本，必须带 quote 与状态；不能从品类推断体验。

## 4. 规划器

### P34（官方 schema）

`planner_v2.py`：`SkeletonPlanner` 种子构造 → 旧 9 阶段修复基线 → `parse_spec` 读 DSL → 八个定向阶段 → `schedule()` 重建 + `check_plan()` 全检。
能力：类型集合、必去名称、城际/市内方式、房型、预算、酒店越界变体、餐段选择。
边界：不读自然语言、无全局回溯、无强制打车、顺序不可搜索。

### strict（新 schema）

`strict_*` 模块：多日业务链、起点/房型、成本聚合、住宿清单、城际清单、跨日事件、身份/来源/时间/引文门、缺口分类（data/adapter/solver/context/pipeline）。
当前结果：60/60 `data_block`，用于诊断而不是通过。

## 5. 动态检索

- `live_amap.py`：预算化客户端，天气/公交/POI；失败即停，不换 key；
- `retrieval_benchmark.py`：证据等级/上下文/quote/TTL 校验；
- `p31_*`：96 题的任务、静态草案、请求、响应、最终计划、评估；
- 结果：468 次调用，72 complete / 20 blocked / 4 infeasible。

## 6. 自动化

- `collection_agent.py`：bootstrap、begin-run、阶段推进、checkpoint；
- `collection_session.py`：运行锁、配额门、begin/check/end；
- `collector_agent/`：PROMPT、SOURCES、config、memory；
- 规则：单轮 ≤1 批、≤2 worker、合计 60 次 web 动作、每缺口 ≤3 来源；暂停不重试、不换 key。

## 7. 模块索引

| 模块 | 作用 |
| --- | --- |
| `expansion_contract.py` | 七表字段、record/evidence/claim 校验 |
| `freshness.py` | 字段策略、TTL、时钟 |
| `live_amap.py` | 高德预算客户端 |
| `retrieval_benchmark.py` | 动态证据评估 |
| `planner.py` / `planner_v2.py` | P34 种子与 V2 规划器 |
| `scheduler.py` / `checker.py` | 时间链重建、官方三关 |
| `strict_*.py` | 新 schema 的严格适配/校验/成本/事件 |
| `tags.py` / `visitor_tags.py` | TAG 词表与抽取 |
| `collection_workflow.py` | 采集批处理与缺口队列 |
