# 来源预检账本核对（2026-11-01）

## 核对范围与方法

只读检查共享 SQLite 账本 `collector_agent/memory/agent.sqlite3` 中 run `manual_20261101_1803` 的请求行和事件行，并与保存的 `chinahighlights_robots_01.json`、`chemsoc_robots_01.json`、`checkpoint.json`、`robots_design.md` 对照。没有联网，也没有更改账本、源记录或工件。

## 账本与工件对照

| request ID | 账本结果 | 预留 → 完成（北京时间） | 保存工件所表达的结果 |
|---|---|---|---|
| `chinahighlights_robots_01` | `web_action / success` | 18:04:33 → 18:04:47 | Web 工具返回抽取摘录；明确不是原始响应字节，源站请求及状态为 unknown |
| `chemsoc_robots_01` | `web_action / failed` | 18:06:52 → 18:07:02 | Web 工具报 URL 不可访问；明确不是源站响应，源站请求及状态为 unknown |

两条请求行与各自的 `request_reserved`、`request_finished` 事件均存在，request ID、域名、URL、工件路径和最终状态相互对应。所存 JSON 的 `source_activation` 均为 false；两域名在 `sources` 表中都没有已登记源记录。没有发现重试或悬挂预约。

## 关键判定

ChinaHighlights 的账本 `success` 只表示这次 Web 工具动作成功返回了内容摘录。工件记录 `capture_method=web_tool_extracted_excerpt_not_original_bytes`、`origin_http_request=unknown`、`origin_response_status=unknown`、`robots_permission_decision=unknown`，且明确摘录不完整、工具报告内容约三周前抓取。因此不能把它写成实时源站 HTTP 200、完整的当前 robots.txt、路径许可结论或源站授权；`robots_design.md` 对此的表述与证据一致。

Chemsoc 是一条 `failed`，失败原因是 Web 工具不可访问该 URL。账本和 JSON 都把源站响应留作 unknown；这不是源站返回非 200、拒绝访问或 robots 禁止的证据。

## 数量与 checkpoint 时序

截至当前共享 ledger，run `manual_20261101_1803` 总计 2 条请求：`success=1`、`failed=1`、`pending=0`。全局 `pending` 请求也为 0。Run 预算为 `web_action=60`、`api_http=0`；该 run 已消耗 2 次 web 工具动作，剩余 58 次预算。它们是工具动作计数，不是可确认的源站 HTTP 请求数。

`checkpoint.json` 的快照时间为 18:05:19，当时记载 `web_action_attempts=1`、`pending_reservations=0`。ChinaHighlights 请求在快照之前完成；Chemsoc 请求于 18:06:52 才预留、18:07:02 才完成。因此 checkpoint 的 1 次计数对其快照时点正确，但在 Chemsoc 后已经过期；当前账本总数应为 2。其 `pending_reservations=0` 与当前 ledger 一致。后续汇总应采用当前 ledger 的 2 次工具动作、1 成功、1 失败、0 pending，而不是把旧 checkpoint 的 1 次计数当作最终数。

## 结论

共享 ledger 与两个保存工件一致。未发现把 ChinaHighlights 工具成功误作实时原始 HTTP 200 或许可的证据；现有设计记录也没有这样表述。Chemsoc 计为 1 条失败，当前 pending 为 0。唯一需要保留的时间边界是：checkpoint 先于 Chemsoc 动作，不能拿其 `web_action_attempts=1` 代表本轮最终总量。
