# Publication verification

Verified on Windows with Python 3.12 on 2026-11-09.

- The project suite passed 151 tests, including 25 translation modality regressions.
- The C meal/date/daytime and coordinator suite passed 43 tests.
- The combined 194 tests passed with zero failures, errors or skips.
- Python syntax checks covered 150 files.
- Five published translation source files matched the current production source.
- Regression test paths resolve relative to the repository root.
- Model calls during publication verification numbered zero.
- Credential and private-key scans passed over the publication payload.
- Source inventory checks excluded datasets, virtual environments, response traces,
  caches, candidate pools and generated experiment results.
- Database junctions used for offline verification were removed afterward.

Translation regressions cover hard/soft classification, complete evidence clauses,
room and bed wording, source/value binding, local JSON output schemas, formatting
normalization and deterministic intercity-set compilation.

Original-text review has identified remaining scope ambiguity, incomplete taxi and
preference coverage, and meal-cap wording rejection. The unit suite measures its
specified cases. Semantic review and complete trip-generation evaluation have
separate saved experiment records.
