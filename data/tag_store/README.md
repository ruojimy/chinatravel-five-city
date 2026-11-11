# tag_store — TAG 层原型库（2026-10-22）

两个 SQLite 原型，用来验证「TAG 必须带证据、许可与有效期」这条约束；后续正式数据在
`data/business_catalog_v1_7/`（42,576 条）和 `data/xian11_merged_v17_tags/`（7,173 条）。

| 文件 | snapshot | TAG 行 | 说明 |
|---|---:|---:|---|
| `tag_store.sqlite` | 3 | 46 | v1：P2 开放数据层（OSM ODbL + Wikidata CC0）+ P5 评论语料层 |
| `tag_store_v2.sqlite` | 1 | 26 | v2：`poi_mapping_v2`，把 OSM/Wikidata 标签挂到沙盒 POI 上 |

## 表结构

- `tags`：`tag_uid / snapshot_id / local_poi_id / city / poi_name / tag_id / tag_group / value / value_type /
  polarity / evidence_kind / status / confidence / context / source_name / source_url / evidence_id /
  excerpt / raw_digest / licence_status / observed_at / retrieved_at / valid_until / gates / payload`
- `snapshots`：`snapshot_id / created_at / note / n_records / n_accept / n_quarantine / n_reject /
  extractor_version / schema_version`

## 闸门与许可

- `gates` 六道：`T1_licence`（许可可再分发）、`T2_excerpt`（有逐字引文）、`T3_semantics`（标签语义对得上）、
  `T4_time_context`（时间/上下文可解释）、`T5_conflict`（与其它来源不冲突）、`T6_review`（复核）。
  `status = accept` 表示六闸全过；`quarantine` 是证据不足被隔离。
- `licence_status` 逐条记录：`odbl`（© OpenStreetMap contributors）、`cc0`（Wikidata）、`cc_by`（Zenodo 评论语料，
  DOI 见 `source_url`）。
- `local_poi_id` 形如 `sandbox:上海:中山公园` 或 `corpus:张家界国家森林公园`，只做本地实体对齐，不是外部 ID。
