# Strict money / citation binding audit (2026-11-01)

Scope: read-only review of `strict_money.py`, `strict_evidence.py`, `strict_independent_verifier.py`, `strict_trip_cost_aggregation.py`, and `strict_cost_constraint_bridge.py`. No network access and no source edits. A small isolated Python fixture exercised the monetary parser and the quote/value binding helper directly.

## Finding: equivalent decimal spellings are rejected by quote binding

`strict_money.exact_money` parses monetary strings into `Decimal`, so the following pairs are mathematically equal and both values are valid inputs. However, `_value_occurs` requires the quote to contain the exact character spelling of the claim value. The fixture produced:

| Claim value | Quote | Parsed value | Citation binding |
|---|---|---:|---|
| `1.00` | `1元` | 1.00 | false |
| `0.10` | `0.1元` | 0.10 | false |
| `1` | `1.00元` | 1 | false |
| `1.00` | `1.00元` | 1.00 | true |

This is a real decimal compatibility false negative in `verify_evidence`: an otherwise complete capture and semantic review cannot get past mechanical `value_binding` when publisher and reviewed claim format the same amount at different decimal scale. No incorrect pass was observed in the tested exact-match path. This binding is conservative, but it is stricter than numeric equality and can reject ordinary currency formatting such as whole-yuan amounts displayed with `.00` or fractional amounts with differing trailing zeros.

## Precision handling reviewed

- `exact_money` rejects binary floats and accepts only nonnegative integers or bounded canonical decimal text (up to 1024 characters); this preserves original decimal precision.
- `strict_evidence` applies this parser to price/cost claim fields; malformed, float, signed, exponent, and noncanonical leading-zero spellings fail closed.
- The independent verifier requires exactly one currency-marked amount in the quote, rejects several obvious conditional/discount contexts, and binds the semantic review digest to the claim value, quote, entity, scope, unit, and response digest.
- Cost aggregation computes totals and budget comparisons with `Decimal`; the public float `total` is marked when approximate, while the bridge passes `total_decimal` to `evaluate_constraint`, whose comparison is also Decimal based. I found no float-rounding route to a false budget pass in these paths.
- Intercity decimal component strings are checked against the recomputed manifest total; ordinary components reject floats through `exact_money`.

## Limits of this audit

The synthetic check isolates the actual helper behavior rather than constructing the large end-to-end evidence fixture needed to satisfy policy pins, rights, scope, freshness, and semantic review simultaneously. The mismatch is nevertheless on the exact mechanical gate used by that end-to-end verifier. This was a focused read-only audit, not a full test-suite run.
