# Strict TAG scope safety audit (2026-11-01)

## Scope and tests

Read-only review of `strict_tag_constraints.py` and `tests/test_strict_tag_constraints.py`; ran the focused suite (20 tests, all passed). Additional isolated fixtures exercised unknown condition sentinels, bool/int mixing, empty and duplicate inventory/facts, and callbacks that mutate caller-owned objects through closures. No network access and no source changes.

## Synthetic results

| Attempt | Result |
|---|---|
| Valid hard `exclude_tag`, all scope items explicitly verified absent | `pass` baseline |
| `present=0` (integer) instead of literal `False` | `unknown`, `tag_fact_value_or_scope_invalid` |
| Empty `scope_items` / duplicate item IDs | `unknown`, `scope_items_missing` / `scope_items_invalid_or_duplicated` |
| Missing scoped tag fact / duplicate fact for one item | `unknown`, `tag_fact_scope_incomplete` / `duplicate_tag_fact_for_scope_item` |
| Conditional expected `True`, fact value `1` | `unknown`, `condition_fact_expected_type_mismatch` |
| Condition values `unknown`, whitespace/case variant ` UNKNOWN `, `unspecified`, `not_known`, `n/a`, `未知`, `不明`, empty string or `None` | `unknown`, `condition_fact_scope_or_value_invalid` |
| Fact verifier closure changes original fact; scope verifier closure clears original item list; fact verifier closure changes original constraint | all `unknown`, `tag_original_inputs_mutated_or_unavailable`; no hard pass |
| Fact callback changes its isolated `present` from bool to integer | `unknown`, `tag_fact_mutated_during_verification` |

The test helpers and implementation use literal `is True` for verifier results. Embedded booleans are ignored. Scope completeness and per-fact verification are separate. `scope.item_kind` is checked against the project kind set, and each kind-scoped fact must carry the exact kind in both its own field and scope. `all`/`any` are explicit; every scope item still needs an independently verified fact, even for `any`.

## Conclusions and limits

No false hard pass was reproduced through unknown sentinels, bool/int equivalence, empty or repeated scope/fact inventory, or closure mutation. Unknown sentinels are accepted only as strings for validation and fail closed; arbitrary sentinel objects are rejected by scalar validation. Conditions intentionally treat int/float values as the same numeric family, but keep bool distinct from both (`True` is not numeric `1`).

The positive baseline relies on literal-True scope and fact verifier callbacks; those callbacks are trust boundaries. The module ensures they receive copies and detects mutations to original inputs even when the mutation is performed through an external closure, but it cannot establish whether a verifier's own positive attestation is semantically sound. Results remain marked `truth_certified=false` and `execution_confirmed=false`.

## 后续审阅补充：实体身份占位符（协调端修复后复核）

原先本审计中的 unknown sentinel 用例只覆盖了 condition fact 的 value（`unknown`、`n/a` 等），没有把 unknown sentinel 用作 `scope_items` 或 `tag_fact.item_id`。协调端发现旧版本仅要求这些 item ID 为非空字符串，故像 `'unknown'` 这样的占位符理论上可以在 verifier 一律返回 true 时被用来组成 hard exclusion pass；这是原报告未覆盖的漏洞边界。

协调端随后在 scope inventory 和 tag fact item ID 上加入 `identifier_is_known` 校验，并添加 `unknown`、`unresolved_id`、`待核验` 的 hard-exclusion 负例。只读复核当前代码确认两处均执行该校验；重新运行 `tests.test_strict_tag_constraints`，21 项全部通过。新负例在 scope verifier 与 fact verifier 均返回 true 时仍得到 `unknown`，因此该路径目前 fail closed。

此补充说明：前一节“各种 unknown sentinel”结论只适用于 condition value；未知实体/范围项是在协调端新增修复后才验证通过的。原先对 closure mutation、bool/int、空/重复范围与 facts 的结论仍由当前实现及定向测试支持。
