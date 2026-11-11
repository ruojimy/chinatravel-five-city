# ShortTrip/Qwen3.5-4B 开测就绪检查

- 时间：2026-11-11T05:01:37.594079+00:00
- **结果：READY 可以开测**

| 判据 | 结果 |
|---|---|
| price_capture_quiet | True |
| snapshot_set_quiet | True |
| data_trees_quiet | True |
| quiet_window_seconds | 60 |
| model_complete | True |
| server_alias | True |
| snapshot_stable_across_runs | True |
| coverage_stable_across_runs | True |
| coverage_explicitly_accepted | True |

## price 覆盖率（最新快照）

{
 "snapshot": "snapshot_v17",
 "attraction": {
  "price_present": 112,
  "total": 908,
  "pct": 12.3
 },
 "restaurant": {
  "price_present": 561,
  "total": 807,
  "pct": 69.5
 },
 "accommodation": {
  "price_present": 375,
  "total": 929,
  "pct": 40.4
 }
}

判据「静止」只证明补价写盘停止，不代表达到某个目标覆盖率。

还要求：快照号与覆盖率在**两次独立检查**之间不变，并由研究者用 `--accept-coverage "<说明>"` 显式接受当前覆盖率（该说明会写入记录）。
注意：补价脚本只处理餐厅；景点 price 覆盖率若长期不增长，属于已知开放缺口，必须由研究者确认是否接受，不能由脚本臆断完成。
