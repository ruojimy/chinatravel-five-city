# Constraint translation repair scope

Implements the approved five changes within the translation stage only:

1. Always derive days/people/tickets/cars from input metadata. Never derive rooms.
2. Build a source coverage checklist for recognizable explicit budget, database
   place mentions, standard attraction types, transport, return deadline and train
   prefix requirements. Missing entries reject extraction, rather than silently
   weakening it. Unrecognized complex requirements still require model evidence;
   this bounded checklist is not a proof of arbitrary natural-language coverage.
3. Use database-backed aliases and small canonical candidate lists. Same-university
   campus options remain OR alternatives when the user has not specified a campus.
   Unresolved ambiguity remains pending; no arbitrary POI selection.
4. Lock grounded extraction items across retries; only failed/missing items need
   correction. Lock validated Python programs during subsequent code repair too.
5. Compile return departure limits, train prefixes and named-place OR groups with
   deterministic templates. Keep existing complex-constraint model fallback.

No changes to meals, DFS, transport routes or soft scoring. Testing repeats the
same ten local-Qwen inputs and the exact same126 logical probes in
translation_module_test/probes.py. No dataset annotations are fed to the model.
The full itinerary experiment remains paused.
