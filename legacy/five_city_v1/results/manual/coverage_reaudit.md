# 三日夜宿与餐饮覆盖复审（2026-11-01）

## 审阅范围与测试

只读审阅 strict_overnight_continuity.py、strict_lodging_cost_manifest.py、strict_meal_coverage.py，并参考底层 strict_lodging.py。运行聚焦测试 tests.test_strict_overnight_continuity、tests.test_strict_lodging_cost_manifest、tests.test_strict_meal_coverage：36 项全部通过。另以现有合成 fixture 测试重复/遗漏边界、日期偏移、未验证餐饮事件、verifier 闭包修改和高精度房价。未联网、未改源码。

## 发现与优先级

### P2 — 独立 overnight checker 接受重复或不完整的边界清单，但结果只对已提交边界有效

Fixture 是 2026-11-15 到 2026-11-17 的两夜住宿要求。只提交 15→16 的一个合法边界，函数返回 pass；把同一个边界复制两次提交，也返回 pass，并列出两个相同的 passing result。它不会知道三日行程还应有 16→17 的第二个不同边界，也没有重复边界键检查。

这不是完整行程 false-pass：输出明确含 complete_itinerary_certified=false，函数文档说只检查显式提供的边界。但调用方若把 aggregate state=pass 当作覆盖所有夜宿边界，重复/遗漏会让报告过度表达。若该 API 用于全行程夜宿结论，建议额外传入完整 itinerary date inventory，要求每个相邻日期对恰好出现一次并拒绝重复；否则必须保留“仅已提交边界通过”的展示范围。

### P3 — 外部 verifier 仍是语义信任边界

Valid synthetic baseline 在所有 callback literal-True 时可以得到 pass，这是预期；函数检查副本不被修改，并检测 closure 改 caller 对象。各范围仍要求独立 verifier：overnight endpoint/stay fact 与 lodging claim；每夜 lodging claim 与整个 inventory；meal inventory 与每个 event。缺少 verifier 或 verifier 返回 false 均不会 pass。回调本身返回 true 的语义是否可信不由这些函数认证，所有结果均标 truth_certified=false / execution_confirmed=false。

## 其他合成验证

| 用例 | 实际结果 | 判定 |
|---|---|---|
| 三日住宿缺第二夜 manifest | unknown / lodging_night_inventory_incomplete | 缺夜不会通过 |
| 重复夜晚日期或归一化后重复 expense ID | unknown | 重复被拒绝 |
| 夜晚 claim/check-in/date、酒店、入口或 timeline endpoint 错位 | unknown | 日期/端点/酒店绑定被拒绝 |
| overnight endpoint 日期偏到 11-17 而声明 next day 为 11-16 | unknown / endpoint_scope_missing_or_invalid | 日期偏移被拒绝 |
| overnight 不同时区 offset 导致 first endpoint 的绝对时间早于 last endpoint | unknown / endpoint_time_order_invalid | 按绝对时刻比较，不被本地日期顺序骗过 |
| meal event verifier 缺失或返回 false | unknown | 未验证 event 不会 pass |
| 有必需午餐但 event 列表为空，inventory verifier literal true | fail / verified_required_meal_slots_missing | 只在 inventory callback 确认清单完整后报告缺槽，不会误 pass |
| 餐饮事件日期偏一天 | fail，required 日期仍在 missing_slots | 错日不满足原槽位 |
| overnight/room claim/inventory/meal inventory/event callback 通过闭包修改原始输入 | unknown | 输入快照检查阻止利用闭包保留 pass |
| 两夜每夜费率精确 0.10000000000000001，component amount 0.20000000000000001 | unknown / lodging_cost_amount_conflict | 微小金额差异精确发现 |
| 同费率，component amount 精确 0.20000000000000002 | pass，total_decimal 同值，total_cny=null | 精确字符串算术通过，不丢小数 |
| 费率为 float 300.0 或负值 | unknown / lodging_night_quote_invalid_or_conflicting | float/负费率 fail closed |

日期、夜数和房价方面，manifest 要求三天连续且规范日期、正好两个夜晚，并把每个 night 日期、酒店、入口、expense ID 与计划清单及相邻时间线端点逐一绑定。底层 check_lodging 拒绝 float 费率，cost manifest 使用 Decimal 精确乘房间数和夜数，并拒绝与组件总金额不等的输入。没有发现房间精度或舍入导致错误 pass 的路径。

## 结论

三项 coverage 的聚焦测试与合成路径未复现缺夜、错日、未验证事件、闭包改写或金额舍入导致的错误 pass。需保留的具体范围风险是 standalone overnight continuity 对重复/遗漏边界清单只返回“已提交边界通过”；其自身明确不认证完整行程。三日 lodging manifest 对两夜有显式完整性检查，meal coverage 对必需槽位有完整性差集检查。
## Overnight boundary duplicate fix: read-only recheck

Coordination added a pre-check that rejects repeated (previous_day, next_day) pairs with unknown / overnight_boundary_duplicate. The new targeted negative test covers a repeated pair being counted twice toward two nights. Re-ran tests.test_strict_overnight_continuity after the change: all 10 tests passed. The prior exact-duplicate repro now returns unknown.

## Residual horizon boundary

The checker still has no declared itinerary date horizon or expected adjacent-date-pair inventory. A synthetic list with two individually valid but disjoint pairs (2026-11-15→16 and 2026-11-17→18), with valid matching two-night lodging claims for each pair, returns state=pass / verified_overnight_continuity. The missing 2026-11-16→17 boundary is not detectable from current inputs. The result nevertheless always has complete_itinerary_certified=false. This is consistent with the documented function scope, but a consumer must not display this bare pass as complete stay coverage.

For clear machine and user-facing scope, retain the current false flag and consider returning explicit metadata such as coverage_scope=provided_boundaries_only, boundaries_checked, and itinerary_horizon_known=false; phrase pass as “all supplied boundaries passed; itinerary-wide coverage not checked.” If itinerary-wide coverage is needed, pass the expected itinerary dates or exact required boundary pairs and require exact coverage (no missing, extra, duplicate, or disconnected pair). The duplicate-pair fix closes repeated-count inflation; it does not prove no leading, internal, or trailing omission without that inventory.
