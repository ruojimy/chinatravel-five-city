# Cost expense inventory and occurrence binding audit (2026-11-01)

## Scope and tests

Read-only review of strict_trip_cost_aggregation.py and validate_expense_occurrence_bindings, with its lodging/intercity manifest handoffs. Ran tests.test_strict_trip_cost_aggregation, tests.test_strict_lodging_cost_manifest, and tests.test_strict_intercity_cost_manifest: 68 tests passed. Additional synthetic fixtures exercised all ordinary occurrence categories, missing/duplicate expense identifiers, inventory callback absence, plan-extra events, and closure mutation. No network access or source edits.

## Binding coverage by category

- tickets, meals, transport, and local_transport require a nonempty expense_ids list and an occurrence_bindings entry for each ID. Each binding must identify exactly one real plan timeline index and match its date, type, and entity_id. IDs are NFKC/trim/casefold normalized, unique inside and across categories; a plan occurrence cannot be assigned to two expenses.
- rooms/accommodation cannot use generic occurrence bindings. Aggregation reruns the two-night lodging manifest against the actual task/plan; each expense ID binds to a date, selected hotel, entrance, per-night quote and exact Decimal arithmetic.
- intercity cannot use generic occurrence bindings. Aggregation reruns the raw fare manifest and binds each unique expense ID to a verified intercity segment, with policy, inventory, segment, timetable and fare verifier gates.
- Required categories must exactly match the component inventory. Missing or extra categories, duplicate categories, empty IDs, duplicate normalized IDs, missing occurrence bindings, duplicated timeline indices, mismatched dates/entities, and undeclared special-category manifests all stop with status unknown and no total.

## Synthetic results

| Attempt | Result |
|---|---|
| Complete tickets + transport + meals baseline | arithmetic_evaluated, 950 CNY |
| Add local_transport with a separate dated timeline binding | arithmetic_evaluated, 1000 CNY, within_limit |
| Omit a required category | unknown / required_category_missing |
| Reuse one expense ID across categories | unknown / expense_id_duplicate_across_categories |
| Bind different expense IDs to the same plan timeline index | unknown / expense_occurrence_missing_or_duplicate |
| Omit inventory_verifier | unknown / independent_inventory_verifier_required |
| Inventory callback mutates the original plan through a closure | unknown / cost_original_inputs_mutated |
| Evidence callback mutates the original component amount through a closure | unknown / cost_original_inputs_mutated |

Declared duplicate/missing bindings cannot be used to produce a budget total. Inventory verifier exceptions, false returns, non-literal-True returns, or mutations of their isolated copies also fail closed in the focused tests.

## P2 trust-boundary limitation: unlisted cost-bearing plan events depend on inventory verifier semantics

The structural checker verifies every submitted expense binding, but does not infer which plan timeline items incur a charge or whether the submitted expense inventory contains every real cost. A synthetic plan with an additional meal/visit item and no corresponding expense still yields arithmetic_evaluated / within_limit when a deliberately permissive inventory callback returns true. That callback receives only (policy, components, scope), not plan/task; it cannot inspect the actual timeline through its arguments. It could capture the exact plan in a closure or consult another independent cost ledger, but that trust requirement is not enforced by the function. Without any callback the result is unknown, as tested; the permissive callback case is not evidence of an independent inventory review.

For an auditable complete-cost claim, the inventory verifier must be bound to the exact plan or another authoritative expense inventory and reject omitted charges. Consider passing task/plan explicitly to the callback or recording a separately pinned verifier result bound to their digest. This matters because the later cost-constraint bridge consumes the arithmetic total, although it separately requires a fact verifier and still returns no truth or trip certification.

## Input-change and precision checks

The aggregation snapshot covers policy, components, scope, plan, task and special manifests. It rechecks after lodging/intercity handoff, inventory verification, and every component evidence verifier; closure mutation of those original inputs returns unknown. Same-expense and same-occurrence tampering is rejected before arithmetic.

Amounts and budget limits are nonnegative integers or decimal strings, not binary floats. Totals and comparisons use Decimal. The lodging integration preserves each nightly Decimal and rejects component totals that differ by even a tiny decimal amount. No route through a duplicate binding, float conversion, or residual rounding was found that creates an arithmetic total.

## Conclusion

No bypass was found for missing/duplicate declared expenses, absent inventory verification, or verifier closure mutation. Ordinary expenses bind one-to-one to plan events; lodging and intercity use separately revalidated manifests. The remaining material boundary is semantic completeness: omitted real expenses cannot be inferred from a list of submitted bindings, and a supplied always-True callback can satisfy the syntactic gate. Full-cost conclusions depend on a genuinely independent verifier that can inspect/bind the actual plan or authoritative expense ledger.
## Inventory verifier full-context fix: read-only re-audit

Aggregation now invokes the inventory verifier with five isolated positional inputs: (policy, components, requested scope, task, plan). The docstring reflects this contract. The verifier input snapshot is checked for mutation, and the outer originals snapshot still catches closure mutation of task/plan/components/policy. Thus an implementation can inspect the exact plan timeline directly when checking inventory completeness.

Focused integration tests run after this change:
- strict_trip_cost_aggregation
- strict_cost_constraint_bridge
- strict_plan_diagnostics
- strict_p31_bridge
- strict_intercity_budget_integration
- strict_lodging_budget_integration
- strict_assembled_intercity_integration

All 114 tests passed. The updated negative test gives the verifier an extra unaccounted plan timeline event and returns false; aggregation is unknown with cost_inventory_unverified. A legacy three-argument verifier raises on the new call signature and is caught as unknown / inventory_verifier_failed. There is no fallback to the old contract, so legacy callbacks must be updated to accept and inspect task/plan; this is a deliberate fail-closed compatibility break. Existing test helpers using *args continue to work, so callback arity checks cannot force semantic use of task/plan. A callback that accepts five arguments but ignores the last two remains a caller trust-boundary risk; the module cannot establish verifier independence or honesty.

Independent checks confirmed the five callback values are snapshots, not original mutable references. A callback changing its supplied plan copy returns unknown / inventory_verifier_mutated_input; a closure changing the original plan returns unknown / cost_original_inputs_mutated. Cost bridge and diagnostic/P31 integration paths still pass the exact input task and plan through to aggregation; no stale three-argument adapter was found in source call sites. The bridge still requires its separate context/fact verifiers after arithmetic and does not certify truth or trip feasibility.

The P2 note above remains as a semantic boundary only for permissive callbacks that accept five inputs but do not actually inspect completeness. The missing-plan-argument issue itself is closed by this change.
