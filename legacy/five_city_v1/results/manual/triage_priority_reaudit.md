# 保留证据与身份优先级工件复审（2026-11-01）

## 范围与复核方式

只读检查 `scripts/strict_retained_evidence_triage.py`、`retained_evidence_triage_v3.json`、`retained_evidence_triage_v5.json`、`identity_review_priorities.json`、当前 `development_diagnostic.json`，以及前一日保存的 `identity_review_queue.json`。通过本地 SHA-256、文件时间、V4Reader 和队列映射复算核对。未联网、未更改源码或数据。

## 哈希与输入时序

- v5 triage 中的 `diagnostic_sha256`、`catalog_sha256`、`triage_script_sha256` 均与当前 `development_diagnostic.json`、catalog 和 triage 脚本字节哈希一致。
- 身份优先级工件的 `catalog_sha256` 与当前 catalog 一致；其 `input_sha256.identity_queue` 等于 `results/manual_20261031_2107/identity_review_queue.json` 的文件哈希，也等于前一日 identity summary 所记的 `queue_sha256`。该旧队列与当前 diagnostic 嵌入的 120 条身份队列在 entity ID 与逐实体 affected-task 映射上完全相同。
- `input_sha256.text_triage` **匹配 v3 的字节哈希，不匹配 v5**。本机文件时间依次为：v3 18:09:24、identity priorities 18:09:48、v4 18:10:12、v5 18:11:32（北京时间）。因此不能把 identity priorities 描述成“由 v5 生成”；它使用的是早于它的 v3。
- 这次输入版本差异没有造成计数差异：v3 与 v5 的 555 行键集合、所有汇总计数、notes 和逐行既有字段相同；v5 只多了顶层 `triage_script_sha256`，并给每行加了 `value_literal_not_applicable_reason` 字段。两者的 `value_literal_not_in_quote=232` 完全相同。priority 可以与 v5 按数值对账，但其直接哈希来源仍应标成 v3。

身份优先级工件记录的 `identity_queue` hash 可以通过已保存的旧 queue 文件重现。v5 自身则提供了其诊断、catalog、脚本输入哈希。两份工件都没有 `generated_at` 字段；共享时应明确版本名和上述更新时间顺序，避免仅凭所在目录误以为它们在同一时刻从同一文本 triage 生成。

## 实体、任务、claim 与 source-family 数量

- 当前开发 diagnostic 有 60 个 development reports、120 个 identity queue entities。identity-priority 工件也是 120 行、120 个唯一实体。逐实体 affected-task count 与当前 queue 完全一致；240 条 entity-task 关联覆盖同样的 60 个 development task IDs，未发现任务归属越界或遗漏。
- v5 triage 是 555 条 claim-reference 行、148 个全局唯一 evidence ID，覆盖 104 个有 claim 的实体；priority 汇总的 claim-reference count 逐实体对得上。priority 中另外 16 个实体没有历史 source family，且这 16 个实体的 claim-reference count 全为 0。
- priority 的 family-count 分布为：36 个实体有至少 2 个（其中 10 个为 3 个、26 个为 2 个），68 个为 1 个，16 个为 0 个，共 120 个实体；family 关联数合计 150。该工件自己的说明明确说不同存储 family 名只是线索，不证明来源独立。不要把 36 个多 family 实体表述成有独立交叉印证。
- priority `distinct_evidence_id_count` 是逐实体去重数，合计 153；v5 的 148 是跨所有实体全局去重数。两者口径不同，不是矛盾或 153 个全局证据。

## “value literal 未出现在 quote”的 232 条

v5/v3 统计为：321 条简单字面命中、232 条 `str(claim.value) in quote` 为 false、2 条不适用（value 不是可支持标量等）。脚本把这项明确定义为“Value substring is only a triage signal”；identity-priority 的 label 也是 `offline_identity_triage_not_dispatch_or_evidence_acceptance`，其排序字段是 affected development task count 和历史 family 数量，不含 value literal 项。故 232 条只能作为人工核查线索，不能解释为“有 232 条事实值无引文支持”、证据拒绝数或需派发抓取的任务数。

同一批里 555 条直接 `observed_at_present` 都是 0；有 `source_published_at` 的 3 条、有 `source_updated_at` 的 0 条。脚本 notes 明确不把来源发布时间/更新时间当作事实观察时间，也不认证原始 HTTP 响应、身份、真实性、许可或 freshness。

## 结论

任务归属和实体数可与当前 development diagnostic 完整对账；120 个实体的 family-count 分布、555 条引用与 148 个全局唯一 evidence ID 也自洽。232 是纯字面子串未命中线索。需要在交付说明中保留一个版本注明：identity priorities 的文本 triage 输入哈希指向 v3；v5 后来生成，虽然与 v3 的既有计数/字段值一致，但 hash 不同且 v5 增加了说明字段。两份工件都应按各自声明的离线 triage 使用，不能转述为身份核验、独立来源证明或抓取授权。
