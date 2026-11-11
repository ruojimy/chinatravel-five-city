# business_catalog_v1_7 — 30 城业务库（含 TAG 层）

来源：本地 `data/business_catalog_v1_7_20261023T021649Z/`（`manifest.built_at = 2026-10-23T02:16:49Z`，继承 v1.4）。
仓库只放压缩包，避免 188 MB 二进制进 Git（与 `catalog_v1_1_20261022/` 同一约定）。

| 项 | 数值 |
|---|---:|
| 实体 `records` | 14,057 |
| ├ 住宿 | 6,080 |
| ├ 餐厅 | 4,601 |
| └ 景点 | 3,376 |
| 城市 | 30 |
| TAG 行 `tags` | 42,576 |
| 不同 TAG 种数 | 47 |
| 证据 `evidence` | 5,187 |
| 字段断言 `field_assertions` | 1,288 |
| 富化发现 `enrichment_findings` | 1,306 |

城市：佛山 3,123 / 无锡 1,367 / 东莞 1,171 / 厦门 957 / 西安 823 / 珠海 736 / 天津 568 / 青岛 476 /
昆明 416 / 宁波 404 / 三亚 369 / 长沙 369 / 大连 338 / 福州 316 / 沈阳 258 / 南宁 237 / 哈尔滨 236 /
海口 206 / 济南 201 / 郑州 201 / 合肥 192 / 太原 142 / 贵阳 137 / 温州 130 / 南昌 129 / 长春 127 /
乌鲁木齐 126 / 石家庄 115 / 兰州 110 / 呼和浩特 77。

TAG 分布（前几位）：`category` 13,800、`kind` 13,800、`cuisine` 5,412、`room_type_name` 1,813、
`history` 1,809、`bed_configuration` 1,316、`nature` 1,261、`food_category` 1,154。

## 还原与查询

```bash
gunzip -k catalog.sqlite3.gz
sqlite3 catalog.sqlite3 "select city, kind, count(*) from records group by 1,2 order by 3 desc limit 12;"
sqlite3 catalog.sqlite3 "select tag, count(*) c from tags group by 1 order by c desc limit 20;"
```

表：`records`（`id/kind/city/name/planning_ready/payload/gate`）、`tags(record_id, tag, value, payload)`、
`evidence`、`field_assertions`、`enrichment_findings`、`historical_references`、`official_operator_fields`、
`room_offers`、`identity_checks`、`claims`、`metadata`。

校验：`SHA256SUMS`（gz 与 3 个元数据文件）。

```text
catalog.sqlite3.gz          d8a26bcb87c247399cb1cb52369c192221e26fb4d52933e00f3bac7450dca7de
catalog.sqlite3(解压后)      bd8e6e97f9cc708c666d51db16b9f51a48ff4bf28dea60574d073505468b9210
```

## 口径提醒

- `manifest.json` 里 `full_completion = false`：这是增量补齐快照，**查询 ≠ 完成**。
- `records.payload` 是 JSON，逐字段带 `field_provenance`（`evidence_id / quote / status / valid_until`）；
  只有 `status=source_value` 才算来源原值，`derived_recall_hint` 只是召回提示。
- `operators` 断言（8,548 条 / 4,320 实体）不等于现实库存，酒店人均也不转房价（见 `docs/hotel_roomtype_dynamic_price.md`）。
