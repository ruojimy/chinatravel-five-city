# Flexible meal order in C

User approved removing early meal priority and keeping both sightseeing-first
and meal-first DFS branches. Existing meal start windows/durations, journey
boundaries, transport exemptions, daylight/opening rules, wait handling and
final hard audits remain unchanged. Translation guards remain enabled.

Remove C's window-minus30 compulsory meal choice. Let the existing model rank
the remaining types with an authoritative C-rule supplement. Keep all eligible
types for ordinary DFS backtracking. Before adding an attraction at its actual
full selected visit end, require a database-grounded restaurant/access witness
for each outstanding meal. Account for opening, unused restaurants, permitted
transport modes, full meal duration and actual intercity occupancy. This is
an optimistic necessary check; final full-plan audits still enforce all meals
together and user constraints. Do not prune on unknown route data.

Tests cover11am branch choice, fallback to meal, real access/closing/departure
limits, used restaurants and alternate modes. Run same10 original inputs with
fresh caches once each, local Qwen Q8,20candidates/30min maximum per case,
incremental full itinerary HTML. No cloud calls, no restored transport module.
