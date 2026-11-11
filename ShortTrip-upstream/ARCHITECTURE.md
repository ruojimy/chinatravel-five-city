# Current architecture

Natural-language request → grounded constraint extraction → deterministic standard
checks or validated model-generated DSL → sandbox retrieval → hard-compatible
ticket/hotel choices → DFS with C meal/date/daytime hooks → original complete-plan
validation and C audit → up to 20 distinct feasible candidates → minimum soft
penalty → independent evaluation → itinerary JSON and HTML.

## Translation

Input metadata supplies days and passenger counts. Non-derived requirements need
source evidence. A bounded source checklist catches recognizable omissions, and
database aliases normalize names while preserving unresolved campus alternatives.
Standard numeric, place, transport, train-prefix and return-deadline requirements
compile to templates. Complex requirements use validated model-generated DSL.
Repairs preserve already accepted requirements and programs.

## Meals and dates

Breakfast uses 06–09 with 30 minutes. Lunch uses 11–14 and dinner 17–20 with
60 minutes. Window upper bounds constrain meal starts. Journey boundaries run
from outbound departure through return arrival. Actual intercity occupation can
exempt meals under the existing opportunity rules.

C explores both meal/sightseeing orders. A proposed attraction must leave feasible
required meal access, opening times and full dining duration. Hotel breakfast
requires actual previous-night accommodation. Sightseeing uses 08–21 and actual
opening times. Absolute-date checks account for midnight transport and approximate
sandbox Duration rollover. Morning outbound and evening return remain preferences.

## Safe pruning

Ticket filtering precedes heuristic reranking. Supported standard rules can reject
incompatible intercity modes, train prefixes and return departure times. DFS
prefix checks use reserved/actual costs without double counting and reject
irreversible activity violations. Overnight outbound travel reduces reserved
hotel nights. The arbitrary 100-per-person/day remaining-budget gate was removed.

C preflight uses optimistic restaurant time windows and minimum dining costs,
assuming zero travel and relaxed reuse. Unknown information retains the branch.
Access checks consider every permitted local mode and interpret midnight rollover.
Metro access walking follows the existing primary-mode validation semantics.

`prune_counts` and `prune_examples` expose rejection reasons in soft selection
JSON. Complete-plan C audit failures also preserve diagnostic details.

## Limits

The source checklist recognizes a bounded vocabulary. Custom constraints and
missing future POIs still require complete validation. Passing optimistic meal
checks does not certify a real route. DFS may time out before finding a candidate
or before reaching 20. Exact-record deduplication permits semantically similar
itineraries. The existing sightseeing-duration selector initially returns 90
minutes, subject to scheduling limits.

The current soft collector excludes the legacy preference-search mode. Individual
user profiles and personalized scoring are design-stage follow-up work.
