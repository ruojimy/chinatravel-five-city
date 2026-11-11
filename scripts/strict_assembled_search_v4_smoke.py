"""Five-city read-only v4 control using the strict assembled-search adapter.

Catalog IDs and records are structural references only. Every itinerary event,
time, route and entrance is a synthetic control. No factual verifier is enabled;
the report contains city aggregates only and excludes holdout task payloads.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import strict_assembler_v4_control_smoke as assembly_audit
import strict_multiday_v4_control_smoke as prior_control
from shorttrip.strict_assembled_search import search_assembled_development_assignments
from shorttrip.strict_plan_assembler import assemble_strict_plan
from shorttrip.strict_v4_reader import V4Reader


DEFAULT_COHORT = prior_control.DEFAULT_COHORT
DEFAULT_CATALOG = prior_control.DEFAULT_CATALOG
DEFAULT_OUT = ROOT / "results/manual_20261031_1332/assembled_search_v4_control"
AXES = ("data", "adapter", "solver", "context", "pipeline")
NOW = "2026-10-31T00:00:00Z"


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest() -> dict[str, Any]:
    paths = {Path(__file__).resolve(), Path(assembly_audit.__file__).resolve(),
             Path(prior_control.__file__).resolve()}
    entries = [{"path": path.relative_to(ROOT).as_posix(), "sha256": _file_sha(path)}
               for path in sorted(paths)]
    source_root = (ROOT / "src/shorttrip").resolve()
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("shorttrip") or not isinstance(module, types.ModuleType):
            continue
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix == ".py" and path.is_relative_to(source_root):
            entries.append({"path": path.relative_to(ROOT).as_posix(),
                            "module": name, "sha256": _file_sha(path)})
    entries.sort(key=lambda item: (item.get("module", "script"), item["path"]))
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return {"classification": "engineering_snapshot_not_freeze",
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "entries": entries}


def _city_run(city: str, task: dict[str, Any], reader: V4Reader) -> dict[str, Any]:
    dates = assembly_audit._dates(task)
    try:
        by_id, by_kind = assembly_audit._selected(task)
    except Exception as exc:
        return _incomplete(city, "candidate_selection_mapping_invalid", type(exc).__name__)
    needed = {"attraction", "restaurant", "accommodation"}
    starts = [by_kind[kind] for kind in assembly_audit.START_KIND_ORDER if kind in by_kind]
    if dates is None or not needed.issubset(by_kind) or not starts:
        return _incomplete(city, "required_three_day_control_inputs_unavailable")
    start_id = starts[0]
    context = {"uid": task.get("uid"), "level": task.get("level"),
        "start_city": task.get("start_city"), "target_city": task.get("target_city"),
        "start_date": task.get("start_date"), "days": task.get("days"),
        "people_number": task.get("people_number"), "start_location_id": start_id}
    entity_kinds = {entity_id: kind for entity_id, (kind, _) in by_id.items()}
    repeat_policy = {"allow_repeated_occurrence_entities": True}
    daily = assembly_audit._synthetic_daily(task, by_id, by_kind, dates, start_id)
    preview = assemble_strict_plan(copy.deepcopy(context), copy.deepcopy(daily),
        entity_kinds=copy.deepcopy(entity_kinds), repeat_policy=copy.deepcopy(repeat_policy))
    if preview.get("status") != "synthetic_plan_assembled_unverified":
        return _incomplete(city, "synthetic_control_assembly_blocked", preview.get("reason"))
    plan = preview["plan"]
    bindings, binding_counts = assembly_audit._bindings(task, plan, by_id, reader)
    diagnostic_inputs = assembly_audit._diagnostic_inputs(plan)
    # Exercise every existing search allowlist path; None means no supplied
    # claim/input and keeps its diagnostic unresolved where applicable.
    for key in ("lodging", "intercity", "finite_route_domain", "constraint_facts",
                "tag_evidence", "cost_aggregation"):
        diagnostic_inputs[key] = None

    def resolver(task_copy, assignment):
        events = copy.deepcopy(daily)
        if assignment.get("control_case") == "broken_transition":
            events[0]["timeline"].pop()  # Missing caller-supplied return transition.
        return {"plan_context": copy.deepcopy(context), "daily_items": events,
            "entity_kinds": copy.deepcopy(entity_kinds),
            "repeat_policy": copy.deepcopy(repeat_policy),
            "record_bindings": copy.deepcopy(bindings), "now": NOW,
            "registry": {}, "diagnostic_inputs": copy.deepcopy(diagnostic_inputs),
            "diagnostic_callbacks": {}}

    search = search_assembled_development_assignments(
        task, {"control_case": ["broken_transition", "synthetic_plan_no_verified_facts"]},
        resolver=resolver, decision_verifier=None, max_assignments=2)
    diagnostics = search.get("diagnostics") or []
    axis_totals = {axis: {"gap_count": 0, "reason_counts": {}} for axis in AXES}
    for item in diagnostics:
        diagnostic = item.get("diagnostic", {}) if isinstance(item, dict) else {}
        raw_axes = diagnostic.get("axes", {}) if isinstance(diagnostic, dict) else {}
        for axis in AXES:
            gaps = raw_axes.get(axis, [])
            axis_totals[axis]["gap_count"] += len(gaps) if isinstance(gaps, list) else 0
            reasons = _count_reasons(gaps)
            target = axis_totals[axis]["reason_counts"]
            for reason, count in reasons.items():
                target[reason] = target.get(reason, 0) + count
    for value in axis_totals.values():
        value["reason_counts"] = dict(sorted(value["reason_counts"].items()))
    counts = search.get("decision_counts", {})
    scope = binding_counts.get("occurrence_scope_audit", {})
    return {"city": city, "status": search.get("status"),
        "outcome_state": search.get("outcome_state"),
        "assignment_count": search.get("enumerated_assignment_count", 0),
        "decision_counts": {key: counts.get(key, 0) for key in ("pass", "fail", "unknown")},
        "unknown_assignment_count": search.get("unknown_assignment_count", 0),
        "axis_summary_over_assignments": axis_totals,
        "synthetic_three_day_count": len(plan["days"]),
        "synthetic_timeline_item_count": sum(len(day["timeline"]) for day in plan["days"]),
        "record_binding_occurrence_count": sum(len(item["occurrences"]) for item in bindings),
        "scope_distribution": scope.get("distribution", []),
        "scope_occurrence_count": scope.get("occurrence_count", 0),
        "scope_distribution_sha256": scope.get("canonical_sha256"),
        "candidate_structure_sha256": binding_counts.get("candidate_structure", {}).get("canonical_sha256"),
        "structural_v4_id_kind_city_matches": binding_counts.get("structural_id_kind_city_matches", 0),
        "v4_records_loaded": binding_counts.get("records_loaded", 0),
        "identity_verifier_enabled": False,
        "all_fact_verifiers_enabled": False,
        "synthetic_time_route_meal_entrance_only": True,
        "per_task_plan_or_record_emitted": False,
        "holdout_payload_used": False,
        "truth_certified": False, "execution_confirmed": False,
        "planner_complete": False, "domain_complete": False}


def _incomplete(city: str, reason: str, detail: str | None = None) -> dict[str, Any]:
    return {"city": city, "status": "solver_incomplete", "reason_code": reason,
        "detail_code": detail, "outcome_state": "unknown", "assignment_count": 0,
        "decision_counts": {"pass": 0, "fail": 0, "unknown": 1},
        "unknown_assignment_count": 1,
        "axis_summary_over_assignments": {}, "scope_distribution": [],
        "scope_occurrence_count": 0, "identity_verifier_enabled": False,
        "all_fact_verifiers_enabled": False,
        "synthetic_time_route_meal_entrance_only": True,
        "per_task_plan_or_record_emitted": False, "holdout_payload_used": False,
        "truth_certified": False, "execution_confirmed": False,
        "planner_complete": False, "domain_complete": False}


def _count_reasons(gaps: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(gaps, list):
        return counts
    for gap in gaps:
        if isinstance(gap, dict) and isinstance(gap.get("reason"), str):
            reason = gap["reason"]
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def run(cohort_path: Path, catalog_path: Path) -> dict[str, Any]:
    cohort_before, catalog_before = _file_sha(cohort_path), _file_sha(catalog_path)
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    tasks, summary = prior_control._choose_task_by_city(cohort)
    reader = V4Reader(catalog_path)
    try:
        cities = [_city_run(city, tasks[city], reader)
                  for city in sorted(prior_control.EXPECTED_CITIES)]
    finally:
        reader.close()
    cohort_after, catalog_after = _file_sha(cohort_path), _file_sha(catalog_path)
    if cohort_before != cohort_after or catalog_before != catalog_after:
        raise RuntimeError("cohort/catalog changed during read-only smoke")
    if any(item.get("decision_counts", {}).get("pass", 0) != 0 for item in cities):
        raise RuntimeError("unexpected pass while all real verifiers are disabled")
    return {"artifact": "strict-assembled-search-v4-control-v1",
        "label": "engineering_only",
        "mode": "read_only_v4_development_records_plus_synthetic_assembled_search",
        "source_inputs": {"cohort": str(cohort_path.resolve()),
            "cohort_sha256_before": cohort_before, "cohort_sha256_after": cohort_after,
            "catalog": str(catalog_path.resolve()), "catalog_sha256_before": catalog_before,
            "catalog_sha256_after": catalog_after, "inputs_unchanged": True},
        "development_task_count": summary[0]["development_task_count"],
        "city_count": len(cities), "cities": cities,
        "only_development_tasks_selected": True,
        "holdout_task_payload_used": False, "holdout_per_task_output_emitted": False,
        "synthetic_controls_are_not_facts_or_user_intent": True,
        "real_identity_and_factual_verifiers_enabled": False,
        "formal_evaluation_performed": False, "freeze_approved": False,
        "planner_complete": False, "domain_complete": False,
        "global_unsat_claimed": False, "truth_certified": False,
        "execution_confirmed": False, "runtime_code_snapshot": _manifest()}


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# 五城 assembled-search v4 合成控制冒烟", "",
        "只选 development split。v4 catalog ID/record 只用于结构绑定；三日时间、路线、餐次与入口全部是 synthetic controls。所有 identity/事实 verifier 关闭。输出不含逐题 plan、record payload 或 holdout 行；此结果不是完整 planner、真实可行性或域完备结论。", "",
        "## 输入哈希", "",
        f"- cohort SHA-256 前后相同：{report['source_inputs']['cohort_sha256_before'] == report['source_inputs']['cohort_sha256_after']}；`{report['source_inputs']['cohort_sha256_before']}`。",
        f"- catalog SHA-256 前后相同：{report['source_inputs']['catalog_sha256_before'] == report['source_inputs']['catalog_sha256_after']}；`{report['source_inputs']['catalog_sha256_before']}`。",
        f"- development task 数：{report['development_task_count']}；按城市汇总数：{report['city_count']}。", "",
        "## 城市汇总", "",
        "| 城市 | search | pass/fail/unknown | 3日事件 | bindings | scope occurrences | v4结构匹配 | data/adapter/solver/context/pipeline gap 总数 | scope SHA-256 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for row in report["cities"]:
        counts = row.get("decision_counts", {})
        axes = row.get("axis_summary_over_assignments", {})
        axis_text = ", ".join(f"{axis}:{axes.get(axis, {}).get('gap_count', 0)}"
                               for axis in AXES)
        lines.append(f"| {row['city']} | {row.get('status')} | {counts.get('pass',0)}/{counts.get('fail',0)}/{counts.get('unknown',0)} | {row.get('synthetic_timeline_item_count',0)} | {row.get('record_binding_occurrence_count',0)} | {row.get('scope_occurrence_count',0)} | {row.get('structural_v4_id_kind_city_matches',0)}/{row.get('v4_records_loaded',0)} | {axis_text} | `{row.get('scope_distribution_sha256')}` |")
    lines += ["", "## Scope 分布", "", "分布只包含日期、occurrence role、synthetic native/policy field 与计数。v4 结构匹配不构成实体身份或事实验证。", "",
        "| 城市 | 日期 | role | native field | policy field | count | control-only |",
        "|---|---|---|---|---|---:|---|"]
    for row in report["cities"]:
        for scope in row.get("scope_distribution", []):
            lines.append(f"| {row['city']} | {scope.get('date')} | {scope.get('role')} | {scope.get('native_field')} | {scope.get('policy_field')} | {scope.get('count')} | {scope.get('control_only')} |")
    lines += ["", "## 限制", "", "每城有限域包含一个因缺少显式转移而组装失败的候选，以及一个可组装但无真实证据的候选；两个分支都保留 unknown，没有候选被以无证据为由剪枝。search 仅枚举声明域。没有真实 identity、路线、开放时间、餐次、住宿、费用或上下文 verifier；synthetic inputs 不代表旅行事实。状态不得解释为三日规划完整、可行、域完备或全局无解。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    json_path = args.out_dir / "strict_assembled_search_v4_smoke.json"
    md_path = args.out_dir / "strict_assembled_search_v4_smoke.md"
    existing = [str(path) for path in (json_path, md_path) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing output: " + ", ".join(existing))
    report = run(args.cohort, args.catalog)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(md_path.resolve()),
        "cities": report["city_count"], "inputs_unchanged": report["source_inputs"]["inputs_unchanged"],
        "all_pass_counts_zero": all(not row.get("decision_counts", {}).get("pass", 0)
                                     for row in report["cities"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
