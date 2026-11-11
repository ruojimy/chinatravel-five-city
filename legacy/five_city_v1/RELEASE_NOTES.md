# Release Notes — v1 (2026-11-01)

## 包含

- **代码**：`src/shorttrip` 全量模块（采集、证据、TAG、P34 V2 规划器、strict 核验、动态检索、自动化）；
- **入口脚本**：P30 合并器、P31 五城 96 题全流程、P32/P33/P34 运行器、collection_agent/session；
- **数据**：五城 v4 脱敏导出（1914 records / 5790 claims / 6072 tags / 3598 evidence index）；
- **结果**：P31 96 题任务与最终计划、评估表、账本；P34 汇总/表格；
- **审计**：manual 开发集的 14 份审计摘要（身份、来源、引文、金额、时间、成本、城际、覆盖）；
- **报告**：24–33 号报告、验收与自动化说明；
- **自动化**：collector_agent 的 README/PROMPT/SOURCES、示例配置、运行入口。

## 不包含

- **原始网页正文 `raw_text`**：许可未明，避免再分发；只保留 evidence index + SHA256；
- `.secrets/`（API keys）、`.venv/`、`node_modules`、`__pycache__`；
- `ChinaTravel` 官方基准仓库与 `eval_exp.py`（P34 复现需另行获取）；
- 大量中间抓取目录（`p15_whole_catalog`、`p17_continuous` 等）；
- P31 的 Amap 原始响应（服务条款限制）；保留 ledger 与聚合结果。

## 已知问题

- 0/1914 有 `observed_at`；0/1914 `entity_verified=true`；554 条 evidence 许可 unknown；
- 216 条坐标非 WGS84；长沙 `G1692/G1693` Duration 单位异常；
- 同一 host 许可标注不一致（Nominatim/Overture）；
- manual 开发集 60/60 `data_block`，不是完整计划。

## 校验

- `MANIFEST.sha256` 覆盖本目录全部文件（除自身）；
- `data/validation.json` 是 v4 的构建校验；
- `data/counts.json` 是本包导出计数；
- 代码与报告均来自 `reproduction/` 的冻结版本，未做内容改写（仅移除数据中的 `raw_text`）。
