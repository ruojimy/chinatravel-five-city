"""Checker façade over the official ChinaTravel evaluator.

Three independent gates, exactly as `eval_exp.py` runs them:

1. schema     -> `chinatravel.evaluation.schema_constraint`
2. commonsense-> `chinatravel.evaluation.commonsense_constraint` (8 structural/
                 sandbox-grounded checks, 27 violation columns)
3. hard DSL   -> `chinatravel.evaluation.hard_constraint.evaluate_hard_constraints_v2`

The module returns structured reports so the ShortTrip pipeline can use the
checker both as an acceptance test and as repair feedback.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2] / "ChinaTravel"
SCHEMA_PATH = REPO / "chinatravel" / "evaluation" / "output_schema.json"

from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py


@dataclass
class CheckReport:
    schema_ok: bool
    commonsense_ok: bool
    commonsense_violations: list[str] = field(default_factory=list)
    hard_results: list[bool] = field(default_factory=list)
    hard_codes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def hard_ok(self) -> bool:
        return all(self.hard_results)

    @property
    def hard_pass_count(self) -> int:
        return sum(1 for r in self.hard_results if r)

    @property
    def all_ok(self) -> bool:
        return self.schema_ok and self.commonsense_ok and self.hard_ok

    def to_dict(self) -> dict:
        return {
            "schema_ok": self.schema_ok,
            "commonsense_ok": self.commonsense_ok,
            "commonsense_violations": self.commonsense_violations,
            "hard_results": self.hard_results,
            "hard_pass_count": self.hard_pass_count,
            "hard_total": len(self.hard_results),
            "hard_ok": self.hard_ok,
            "all_ok": self.all_ok,
            "error": self.error,
        }


_schema_cache: dict | None = None
_quiet = True


def _schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema_cache


def check_plan(query: dict, plan: dict, *, lang: str = "zh") -> CheckReport:
    """Run all three gates for one plan."""
    uid = query.get("uid", "query")
    if not plan or not plan.get("itinerary"):
        return CheckReport(False, False, ["empty plan"], error="empty plan")

    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            schema_df = None
            rate, schema_agg, schema_pass = evaluate_schema_constraints(
                [uid], {uid: plan}, schema=_schema()
            )
            schema_ok = uid in set(schema_pass)
    except Exception as exc:  # noqa: BLE001
        return CheckReport(False, False, [f"schema evaluator crashed: {exc}"], error=str(exc))

    violations: list[str] = []
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            macro, micro, comm_agg, comm_pass = evaluate_commonsense_constraints(
                [uid], {uid: query}, {uid: plan}, verbose=False, lang=lang
            )
        if comm_pass:
            commonsense_ok = True
        else:
            commonsense_ok = False
            row = comm_agg.iloc[0]
            for column in comm_agg.columns:
                if column == "data_id":
                    continue
                if int(row[column]) != 0:
                    violations.append(str(column))
    except Exception as exc:  # noqa: BLE001
        return CheckReport(
            schema_ok, False, violations + [f"commonsense crashed: {exc}"], error=str(exc)
        )

    hard_results: list[bool] = []
    hard_codes = list(query.get("hard_logic_py") or [])
    if hard_codes:
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                hard_results = [bool(x) for x in evaluate_constraints_py(hard_codes, plan)]
        except Exception as exc:  # noqa: BLE001
            hard_results = [False] * len(hard_codes)
            violations.append(f"hard evaluator crashed: {exc}")

    return CheckReport(
        schema_ok=schema_ok,
        commonsense_ok=commonsense_ok,
        commonsense_violations=violations,
        hard_results=hard_results,
        hard_codes=hard_codes,
    )


def hard_vector(query: dict, plan: dict) -> list[bool]:
    """Cheap DSL-only evaluation (no sandbox-heavy commonsense checks)."""
    codes = list(query.get("hard_logic_py") or [])
    if not codes:
        return []
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return [bool(x) for x in evaluate_constraints_py(codes, plan)]
    except Exception:
        return [False] * len(codes)
