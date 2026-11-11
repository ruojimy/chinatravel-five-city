# 数据目录说明

本目录是 v4 五城参考库的**脱敏导出**，用于查看结构与复现统计；不是完整原始库。

| 文件 | 内容 |
| --- | --- |
| `records.jsonl.gz` | 1,914 条 record payload（含 field_provenance、tags、scope、时钟） |
| `claims.jsonl.gz` | 5,790 条字段 claim（含 quote、unit、context） |
| `tags.csv.gz` | 6,072 条 TAG（record_id / tag / value / status / policy / valid_until） |
| `evidence_index.jsonl.gz` | 3,598 条 evidence 元数据；**不含 raw_text**，保留 source_url、retrieved_at、licence、authority、capture_method、raw_sha256 |
| `counts.json` | 本包计数 |
| `validation.json` | v4 构建校验 |
| `city_coverage.csv` | 城市 × 类型覆盖 |
| `field_coverage.csv` | 字段级非空率 |
| `manifest.json` | v4 原始 manifest（文件哈希） |

## 为什么没有 `raw_text`

`raw_text` 是第三方网页正文；许可 554 条 unknown，公开发布会超出研究引用范围。删除后：

- 仍可核对“这条值来自哪个 URL、什么时候抓的、哪条 evidence、哈希是多少”；
- 不能在本地重跑 quote 子串门（需要原始快照），但可在拥有完整库的本地环境复核。

完整 `catalog.sqlite3` 不随包发布；如需，请在授权范围内从本地 `data/five_city_reference_v4_20261026/` 取用，并遵守 `DATASET_CARD.md` 的许可说明。
