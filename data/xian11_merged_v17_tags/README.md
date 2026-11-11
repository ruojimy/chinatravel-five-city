# xian11 v17 TAG 层导出

`results/xian_gapfill_20261109/snapshot_v17/catalog.sqlite3` 的 `tags` 表导出。
仓库不放 88 MB 的 v17 sqlite 本体（可复现，见 `results/xian_gapfill_20261109/REPORT.md`），
只留 TAG 层，便于核对评级与证据口径。

| 项 | 数值 |
|---|---:|
| TAG 行 | 7,173 |
| 不同 tag | 68 |
| 覆盖 record_id | 2,371 |
| 城市分布 | 西安 1,915 / 宁波 1,500 / 长沙 1,406 / 青岛 1,276 / 厦门 1,076 |

文件：

- `tags_v17.jsonl.gz`：每行 `{record_id, city, tag, value, payload}`，`payload` 保留
  `basis / evidence_id / status / policy_id / valid_until`。
- `tags_summary.json`：行数、tag 直方图、城市分布。

## 口径提醒

- 高频项 `kind`（2,325）、`native_fields_complete`（1,914）、`metro_line` / `metro_network`（各 970）
  多为 `status = derived_recall_hint`，即**派生召回提示，不是来源事实**。
- 只有 `status = source_value` 的 TAG 带逐字段证据（`evidence_id` 指向 `evidence` 表）；
  规划里不能把派生提示当核验结论。
