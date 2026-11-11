# snapshot_v17 — 西安第 11 城（v17 口径）

`REPORT.md` 里所有数字都来自这个快照。仓库只放 gzip（88 MB → **7.5 MB**），其余为当日产物原件。

| 项 | 数值 |
|---|---:|
| `records` | 6,549 |
| ├ 西安 | 4,771 |
| ├ 长沙 / 宁波 / 青岛 / 厦门 | 485 / 455 / 420 / 418 |
| `tags` | 7,173（68 种，见 `data/xian11_merged_v17_tags/`） |
| `evidence` | 10,503 |
| `claims` | 7,667 |
| `hotel_price_observations` | 555 |
| `hotel_price_estimates` | 456（352 unknown 中可算出邻店区间的部分） |
| `room_types` | 2,243 |

## 还原

```bash
gunzip -k catalog.sqlite3.gz
sqlite3 catalog.sqlite3 "select city, kind, count(*) from records group by 1,2 order by 3 desc;"
```

`SHA256SUMS` 覆盖全部文件；解压后 sqlite 的哈希是
`7066073951dce28bddbe326de0af888e28d8c212f77515a18ada87b85056b5a5`，
与 2026-11-11 23:50 起跑的厦门单城采集所引用的父库哈希一致（见
`results/xiamen_claude_20261111_2350/README.md` 的本地副本）。

## 同目录小文件

- `manifest.json` / `ingest_report.json`：构建输入与载入门结果。
- `GRADE_INDEX.json`：评级标准 v1 的索引。
- `quality_report.json` / `quality_grades.jsonl`：逐实体质量分级（A/B/C/D）。
- `verify_report.json`：独立校验（硬失败 0 的那一份）。
