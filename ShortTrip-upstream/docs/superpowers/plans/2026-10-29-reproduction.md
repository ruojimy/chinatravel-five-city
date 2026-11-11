# ChinaTravel Reproduction Implementation Plan

> Execute inline using superpowers:executing-plans.

**Goal:** Run the approved original LLMNeSy pipeline for one fixed easy, medium, human case using DeepSeek V4.1 Flash and export complete offline HTML.

**Architecture:** Keep core agents and evaluators unchanged. A preparation script pins official data, normalizes CSV serialization into local JSON, and invokes original command line entrypoints. A renderer consumes actual results.

**Tech Stack:** Python 3.12, existing project requirements, standard library HTML generation.

**Spec:** ../specs/2026-10-29-reproduction-design.md

## Global Constraints

- Work in current directory; no Git repository exists.
- Use original LLMNeSy, no oracle translation, no synthetic plans, no sample substitution.
- Credentials remain in environment or ignored local file.
- Preserve actual failures and evaluate original annotations.

## Tasks

- [x] 1. Create .venv and install exact project requirements. Verify imports.
- [x] 2. Download pinned official Chinese sandbox and Query CSV; validate archive SHA-256, safely extract, normalize list/numeric/bool fields, write three local split lists and provenance manifest.
- [x] 3. Add orchestration and local model configuration; verify preflight reports missing credentials clearly. Invoke original run_exp.py for each fixed local split with deepseek-flash; invoke eval_exp.py for each split. Preserve logs and outputs.
- [x] 4. Render actual JSON into self-contained HTML, retaining all activity and transport fields, original requirements, evaluation, totals and raw JSON. Verify counts and costs. Browser layout inspection unavailable because no browser surface is enabled; documented rather than claimed.
- [x] 5. Run relevant existing regressions and end-to-end verification. Record status, commands and limitations in reproduction/README.zh-CN.md.

## Review Focus

- CSV escapes must become executable code, without unsafe eval or altering constraints.
- Downloads and ZIP extraction remain under the project.
- Missing credentials never trigger substitute models or invented results.
- Partial plans and failed evaluations remain visible.
- HTML escapes untrusted text and contains all days and transport segments.
