# 保留证据时间字段抽样审阅（v3）

## 范围与复算

只读检查 `retained_evidence_triage_v3.json`、对应的 `development_diagnostic.json`、`scripts/strict_retained_evidence_triage.py`，并通过 `V4Reader` 重开同一 catalog 中队列涉及的证据。未联网、未修改源码或数据。

v3 共 555 条 claim-reference rows、148 个 unique evidence ID。`original_time_text_as_stored` 在 74 条引用中非空，但按 evidence ID 去重后是 **19 个 evidence**，并非 74 个独立时间源。按保存字符串本身的精度统计，不补零、不推导时区：

| `original_time_text` 标签 | 引用行 | unique evidence ID | 仅日期 | 到分钟 | 到秒 |
|---|---:|---:|---:|---:|---:|
| `source_published_at` | 32 | 12 | 5 | 6 | 1 |
| `source_updated_at` | 42 | 7 | 7 | 0 | 0 |
| 合计 | 74 | 19 | 12 | 6 | 1 |

15 个不同的原始时间字符串在 19 个 evidence ID 间有重复：日期精度例如 `2026-07-22`（4 个 evidence ID）和 `2026-08-11`（2 个）；分钟精度例如 `2025-04-13T14:30`、`2025-04-13T15:03`；秒精度为 `2020-11-27T17:18:13`。这些原始字符串均未带时区；本次没有把日期字符串擅自补成日末、把分钟值补成秒，或把本地时间换算成 UTC。

另有 **3 条引用、1 个 evidence ID** 的 `source_published_at_as_stored` 非空：`2024-12-10T15:04:00+08:00`；该 evidence 的 `original_time_text_as_stored` 为空。其原始保留摘录只展示“日游运营时间：8:00-17:00 / 夜游运营时间：18:00-22:00”等营业时间，没有显示该 2024-12-10 发布时间。故此值只能作为记录中明确标记的来源发布时间字段看待，不能改读为事实观察时刻。`source_updated_at_as_stored` 在本批 555 行中均为空。

重开后的 555 条 claim 与 evidence 上，`observed_at_present` 仍为 0。这里的零只反映所检查的直接 `observed_at` 字段，不代表嵌套 metadata、页面时间或原始响应已被完整审定；但 19 个带 `original_time_text` 的 evidence，其原始键明确都是 publication/update 标签，不是 observation 标签。

## 原始上下文抽样

- `p30-evidence:e1ec9d93…`（6 条 claim 引用）在保留文本中显示“更新时间：2026-07-22”紧接餐馆名称、价格、评分、地址等页面字段。这证明页面文本声称一个页面更新时间，不能证明每一项事实在当日逐项实测或确认。
- `p30-evidence:66e9ec2d…`（7 条引用）时间元数据为 `source_updated_at=2026-08-11`；对应内容是 Visit Xi'an 页面正文及推荐时长等事实。页面更新标签不将具体推荐时长绑定到该日的观察。
- `p30-evidence:38258abc…`（3 条引用）`source_published_at=2025-07-28T20:27`，保留文本含多个活动/施工日期和景区开放时间。这些是正文叙述或有效时段，不是来源在该时间观察开放时间的记录。
- `p30-evidence:b7f0780…`（2 条引用）原始时间为 `source_published_at=2024-11-19`；正文标题行写“发布时间:2024-11-19 15:05”，其 claims 是开放时段。发布时间是文章发布事件，不是景点营业时段的观测时刻。
- `p30-evidence:27d75925…`（3 条引用）单独保存 `source_published_at_as_stored=2024-12-10T15:04:00+08:00`，但当前保存的引文截取没有显示此时间。即使该字段准确，它仍是发布时间，不能成为营业时间事实的观察时间。

其他样本中的“开放时间”日期区间、营业时段、文章发布日期、页面“更新时间”都各自描述业务有效时间或页面生命周期；没有一个明确表述“这项被引事实于某时实地/直接观测”并把那个时刻绑定到该 claim。

## 结论与边界

本次在 555 个 claim 引用及其关联的 148 个 evidence ID 中，**没有找到可明确绑定到事实观察时刻的原始证据**。19 个 raw-time evidence 均提供 source publication/update metadata；另 1 个 unique evidence 有显式 publication timestamp。所有 555 个直接 `observed_at` 标记为 false。不得把上述发布时间、更新时间、正文中的营业时段/活动日期或抓取时间替代观察时间。

该结论仅表示在这份保留文本和所检查字段中未找到合格的 observation-time 证据；它不是对源站当前内容的判断，也不证明原始响应、来源身份、真实性、许可或 freshness。v3 本身标记 `holdout_per_task_results_generated=false`、`formal_freeze=false`、`original_http_response_certified=false`、`identity_or_truth_certified=false`、`network_requests=0`；因此没有 holdout 验证结果、来源授权或正式冻结可供声称。本次审阅也未产生这些授权或认证。
