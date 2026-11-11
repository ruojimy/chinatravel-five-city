# Route Decimal fix read-only re-audit (2026-11-01)

## Focused tests

Ran `tests.test_strict_route_solver` and `tests.test_strict_route_proof`: all 38 tests passed (0.023 seconds). Additional isolated fixtures checked equivalent decimal spellings, tiny over-limit values, legacy floats, and missing/negative values. No source files were changed.

## Numeric and conflict results

- **Equivalent spellings do not conflict.** Two observations for the same context with `duration_minutes="20.0"` and `"20.00"` both parse to equal Decimals. With limit `"20.000"`, solver returns `candidate_feasible`. Output retains the first input spelling (`"20.0"`), while comparison remains exact.
- **Tiny excess is preserved.** Duration `"20.0000000000000005"` against limit `"20"` produces `candidate_constraint_fail`, not `candidate_feasible`. `verify_route_domain_failure` returns scoped `verified=true`; `diagnose_finite_route_domain` returns `finite_route_domain_failure_verified` with `declared_cartesian_route_domain`. The result still has `candidate_domain_mapping_independently_verified=false`, `controller_certificate_issued=false`, and `execution_confirmed=false`.
- **Missing and negative values fail closed.** Missing duration, float `20.0`, negative integer `-1`, and text `"-0.1"` all leave the solver `solver_incomplete` because no eligible route duration remains. Missing, float, negative integer, and negative text limits return proof `verified=false, reason=leg_limit_invalid`.
- **The old precision-loss case is rejected.** Float `20.0000000000000005` rounded to `20.0` is no longer accepted. The exact value must be supplied as decimal text.

## Compatibility notes

This intentionally tightens accepted inputs: integers remain valid; fractional values must be plain decimal strings such as `"20.0000000000000005"`; every float is rejected, including apparently harmless `20.0`. A `Decimal` instance returned by JSON `parse_float=Decimal` is also outside `exact_money`'s supported types and must be converted losslessly to decimal text before passing it in. Do not convert it through float. Output duration lists preserve input type and spelling, so callers that assume every duration is an int/float should be checked.

## Conclusion

Focused checks support the precision fix: numerically equal spellings do not conflict, tiny excess correctly fails, and negative, missing, or legacy float inputs do not lead to a feasible result or failure proof. The main compatibility cost is migrating float callers to integer or decimal-text values while keeping the raw-token verifier bound to that text.
