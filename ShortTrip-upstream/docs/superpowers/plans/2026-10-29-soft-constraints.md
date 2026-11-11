# Soft Constraints Implementation Plan

> Execute inline with superpowers:executing-plans. No Git metadata exists; work in the requested directory.

**Goal:** Collect 20 unique feasible original-DFS plans for each existing case, select minimum deterministic soft penalty, evaluate and render table HTML.

**Architecture:** Add standalone scoring and candidate-pool modules, subclass LLMDrivenAgent at its existing complete-plan validation hook, and use an isolated reproduction runner/report. Preserve baseline files and core entrypoints.

**Tech Stack:** Python 3.12, existing sandbox/LLM adapter/evaluator, standard library HTML.

**Spec:** ../specs/2026-10-29-soft-constraints-design.md (approved; mode A, target 20, no extra 20-minute wall cap).

## Global constraints
- No Oracle fields enter planning/candidate selection. Original independent evaluation remains authoritative.
- Preserve original default LLMNeSy behavior and original results.
- Four configurable nonnegative penalty categories; unknown values remain null with coverage.
- Save deep snapshots, unique fingerprints, all candidates and exact winning score.
- Use the same three UIDs, pinned official sandbox, deepseek-flash, thinking disabled, max_tokens 4096.

## Tasks
- [x] 1. Add failing tests for long commutes/walking/waits, playable empty day, missing meals, real meal detour baseline, interval unions, scoring sums and weights. Implement chinatravel/soft_constraints/scoring.py and defaults.
- [x] 2. Test unique/deep candidate pool, stable min selection, count limit, incomplete status. Implement pool.py and agent.py using original validation and DFS backtracking; bypass first-result fallback and old timeout only in soft mode.
- [x] 3. Add isolated reproduction/soft_constraints/run.py. Call original model factory with existing overrides; load fixed local queries without Oracle; save all20, selected schema-compatible plan, logs and original eval output. Persist candidates as collected.
- [x] 4. Run targeted/regression checks and three actual generations. Do not pad fewer candidates or misreport failure. Review implementation using a fresh read-only reviewer as required by executing-plans.
- [x] 5. Render selected plans using the confirmed four-column layout, add per-category penalties and all candidate rankings/details. Independently verify fingerprints, minimum selection, all activity/transport/day/cost data and baseline hashes; document evidence.

## Review focus
- Both original complete-plan validation callers must reach collector.
- Snapshot must survive DFS mutations; default least_plan_logic must not replace winner.
- No double-counting intervals or consecutive meal detours; 24:00 and early return handled.
- Unknown counterfactual routes never become fictitious zero detours.
- Exact20 required for success claim; all failures/statuses explicit; API requests bounded individually.
