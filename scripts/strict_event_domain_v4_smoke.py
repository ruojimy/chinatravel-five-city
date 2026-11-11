"""Five-city v4 synthetic smoke for explicit bounded event-slot domains.

Real selected catalog IDs and read-only records are used only as structural
references. Slot alternatives contain caller-authored synthetic timelines; all
real identity/factual verifiers remain disabled. The report is city aggregate
only and does not include holdout rows, plans, or record payloads.
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
from shorttrip.strict_event_domain import search_explicit_event_domain
from shorttrip.strict_v4_reader import V4Reader


DEFAULT_COHORT = prior_control.DEFAULT_COHORT
DEFAULT_CATALOG = prior_control.DEFAULT_CATALOG
DEFAULT_OUT = ROOT / "results/manual_20261031_1332/event_domain_v4_control"
NOW = "2026-10-31T00:00:00Z"
AXES = ("data", "adapter", "solver", "context", "pipeline")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_manifest():
    paths = {Path(__file__).resolve(), Path(assembly_audit.__file__).resolve(),
             Path(prior_control.__file__).resolve()}
    entries = [{"path": path.relative_to(ROOT).as_posix(), "sha256": _sha(path)}
               for path in paths]
    source_root = (ROOT / "src/shorttrip").resolve()
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("shorttrip") or not isinstance(module, types.ModuleType):
            continue
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix == ".py" and path.is_relative_to(source_root):
            entries.append({"module": name, "path": path.relative_to(ROOT).as_posix(),
                            "sha256": _sha(path)})
    entries.sort(key=lambda item: (item.get("module", "script"), item["path"]))
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return {"classification": "engineering_snapshot_not_freeze",
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "entries": entries}


def _context(task, start_id):
    return {"uid": task.get("uid"), "level": task.get("level"),
        "start_city": task.get("start_city"), "target_city": task.get("target_city"),
        "start_date": task.get("start_date"), "days": task.get("days"),
        "people_number": task.get("people_number"), "start_location_id": start_id}


def _slots(daily):
    slots = []
    for index, day in enumerate(daily):
        complete = copy.deepcopy(day["timeline"])
        broken = copy.deepcopy(day["timeline"])
        del broken[2]  # Omit the explicit leg into the restaurant.
        slots.append({"slot_id": f"synthetic-day-slot-{index + 1}",
            "date": day["date"],
            "candidates": [
                {"candidate_id": f"day-{index + 1}-complete-explicit-events",
                 "events": complete},
                {"candidate_id": f"day-{index + 1}-missing-middle-transition",
                 "events": broken},
            ]})
    return slots


def _city_run(city: str, task: dict[str, Any], reader: V4Reader) -> dict[str, Any]:
    dates = assembly_audit._dates(task)
    try:
        by_id, by_kind = assembly_audit._selected(task)
    except Exception as exc:
        return _incomplete(city, "candidate_selection_mapping_invalid", type(exc).__name__)
    needed = {"attraction", "restaurant", "accommodation"}
    starts = [by_kind[kind] for kind in assembly_audit.START_KIND_ORDER if kind in by_kind]
    if dates is None or not needed.issubset(by_kind) or not starts:
        return _incomplete(city, "three_day_structural_candidates_missing")
    start_id = starts[0]
    context = _context(task, start_id)
    daily = assembly_audit._synthetic_daily(task, by_id, by_kind, dates, start_id)
    anchors = [{"date": day["date"], "city": day["city"],
                "start_location": copy.deepcopy(day["start_location"])} for day in daily]
    entity_kinds = {entity_id: kind for entity_id, (kind, _) in by_id.items()}
    repeat_policy = {"allow_repeated_occurrence_entities": True}

    # Preview only the all-complete choice to calculate one safe aggregate
    # scope summary. During search the resolver factory is called separately
    # on each successfully assembled assignment plan.
    preview, preview_counts = assembly_audit._bindings(
        task, assembly_audit.assemble_strict_plan(context, daily,
            entity_kinds=entity_kinds, repeat_policy=repeat_policy)["plan"],
        by_id, reader)
    baseline_scopes = preview_counts.get("occurrence_scope_audit", {})

    def bindings_factory(task_copy, assignment_copy, actual_plan):
        bindings, _counts = assembly_audit._bindings(task_copy, actual_plan, by_id, reader)
        return bindings

    # No meal/overnight scope claims or other factual diagnostics are supplied;
    # all allowlisted input paths are still forwarded explicitly as null.
    diagnostic_inputs = {key: None for key in (
        "overnight_boundaries", "meal_coverage", "lodging", "intercity",
        "finite_route_domain", "constraint_facts", "tag_evidence", "cost_aggregation")}

    result = search_explicit_event_domain(
        task, context, anchors, _slots(daily), entity_kinds=entity_kinds,
        repeat_policy=repeat_policy, record_bindings_resolver=bindings_factory,
        now=NOW, registry={}, diagnostic_inputs=diagnostic_inputs,
        diagnostic_callbacks={}, max_assignments=8)
    diagnostics = result.get("diagnostics", [])
    axes_summary = {axis: {"gap_count": 0, "reason_counts": {}} for axis in AXES}
    for record in diagnostics:
        diagnostic = record.get("diagnostic", {}) if isinstance(record, dict) else {}
        raw_axes = diagnostic.get("axes", {}) if isinstance(diagnostic, dict) else {}
        for axis in AXES:
            gaps = raw_axes.get(axis, [])
            axes_summary[axis]["gap_count"] += len(gaps) if isinstance(gaps, list) else 0
            for reason, count in _count_reasons(gaps).items():
                target = axes_summary[axis]["reason_counts"]
                target[reason] = target.get(reason, 0) + count
    for value in axes_summary.values():
        value["reason_counts"] = dict(sorted(value["reason_counts"].items()))
    counts = result.get("decision_counts", {})
    return {"city": city, "status": result.get("status"),
        "outcome_state": result.get("outcome_state"),
        "assignment_count": result.get("enumerated_assignment_count", 0),
        "declared_assignment_combinations": result.get("declared_assignment_combinations"),
        "decision_counts": {key: counts.get(key, 0) for key in ("pass", "fail", "unknown")},
        "unknown_assignment_count": result.get("unknown_assignment_count", 0),
        "axis_summary_over_assignments": axes_summary,
        "slot_count": result.get("declared_slot_count", 0),
        "candidate_option_count": result.get("declared_candidate_option_count", 0),
        "explicit_complete_plan_timeline_items": sum(len(day["timeline"]) for day in daily),
        "record_binding_occurrence_count_per_assembled_plan": sum(
            len(binding["occurrences"]) for binding in preview),
        "scope_distribution": baseline_scopes.get("distribution", []),
        "scope_occurrence_count": baseline_scopes.get("occurrence_count", 0),
        "scope_distribution_sha256": baseline_scopes.get("canonical_sha256"),
        "candidate_structure_sha256": preview_counts.get("candidate_structure", {}).get("canonical_sha256"),
        "structural_v4_id_kind_city_matches": preview_counts.get("structural_id_kind_city_matches", 0),
        "v4_records_loaded": preview_counts.get("records_loaded", 0),
        "identity_verifier_enabled": False, "factual_verifiers_enabled": False,
        "synthetic_times_routes_meals_entrances": True,
        "per_task_plan_or_record_emitted": False, "holdout_payload_used": False,
        "event_domain_complete": result.get("event_domain_complete", False),
        "task_domain_complete": result.get("task_domain_complete", False),
        "planner_complete": result.get("planner_complete", False),
        "truth_certified": False, "execution_confirmed": False}


def _count_reasons(gaps):
    result = {}
    if not isinstance(gaps, list):
        return result
    for gap in gaps:
        if isinstance(gap, dict) and isinstance(gap.get("reason"), str):
            reason = gap["reason"]
            result[reason] = result.get(reason, 0) + 1
    return dict(sorted(result.items()))


def _incomplete(city, reason, detail=None):
    return {"city": city, "status": "solver_incomplete", "outcome_state": "unknown",
        "reason_code": reason, "detail_code": detail, "assignment_count": 0,
        "decision_counts": {"pass": 0, "fail": 0, "unknown": 1},
        "unknown_assignment_count": 1, "axis_summary_over_assignments": {},
        "scope_distribution": [], "scope_occurrence_count": 0,
        "identity_verifier_enabled": False, "factual_verifiers_enabled": False,
        "synthetic_times_routes_meals_entrances": True,
        "per_task_plan_or_record_emitted": False, "holdout_payload_used": False,
        "event_domain_complete": False, "task_domain_complete": False,
        "planner_complete": False, "truth_certified": False, "execution_confirmed": False}


def run(cohort_path: Path, catalog_path: Path):
    cohort_before, catalog_before = _sha(cohort_path), _sha(catalog_path)
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    tasks, summary = prior_control._choose_task_by_city(cohort)
    reader = V4Reader(catalog_path)
    try:
        cities = [_city_run(city, tasks[city], reader)
                  for city in sorted(prior_control.EXPECTED_CITIES)]
    finally:
        reader.close()
    cohort_after, catalog_after = _sha(cohort_path), _sha(catalog_path)
    if cohort_before != cohort_after or catalog_before != catalog_after:
        raise RuntimeError("cohort or catalog changed during read-only event-domain smoke")
    if any(row.get("decision_counts", {}).get("pass", 0) for row in cities):
        raise RuntimeError("unexpected candidate pass with factual verifiers disabled")
    return {"artifact": "strict-event-domain-v4-control-v1", "label": "engineering_only",
        "mode": "read_only_v4_development_records_and_synthetic_event_domain_search",
        "source_inputs": {"cohort": str(cohort_path.resolve()),
            "cohort_sha256_before": cohort_before, "cohort_sha256_after": cohort_after,
            "catalog": str(catalog_path.resolve()), "catalog_sha256_before": catalog_before,
            "catalog_sha256_after": catalog_after, "inputs_unchanged": True},
        "development_task_count": summary[0]["development_task_count"],
        "city_count": len(cities), "cities": cities,
        "only_development_tasks_selected": True,
        "holdout_task_payload_used": False, "holdout_per_task_output_emitted": False,
        "real_identity_and_fact_verifiers_enabled": False,
        "synthetic_controls_are_not_facts_or_user_intent": True,
        "event_domain_complete": False, "task_domain_complete": False,
        "planner_complete": False, "formal_evaluation_performed": False,
        "freeze_approved": False, "global_unsat_claimed": False,
        "truth_certified": False, "execution_confirmed": False,
        "runtime_code_snapshot": _runtime_manifest()}


def _markdown(report):
    lines = ["# 五城 v4 explicit event-domain 合成控制冒烟", "",
        "只使用 development split。v4 ID/record 仅作为结构参照；slot 候选中的三日时间、路线、餐次与入口都是 synthetic controls。真实 identity/事实 verifier 全关闭。每城枚举 3 个日 slot 的完整片段与缺中间转移片段组合；逐 occurrence record bindings 由 resolver 针对实际 assemble plan 生成。", "",
        "## 输入完整性", "",
        f"- cohort SHA-256 前后相同：{report['source_inputs']['cohort_sha256_before'] == report['source_inputs']['cohort_sha256_after']}；`{report['source_inputs']['cohort_sha256_before']}`。",
        f"- catalog SHA-256 前后相同：{report['source_inputs']['catalog_sha256_before'] == report['source_inputs']['catalog_sha256_after']}；`{report['source_inputs']['catalog_sha256_before']}`。",
        f"- development task 数：{report['development_task_count']}；城市数：{report['city_count']}。holdout 未逐题读取或输出。", "",
        "## 城市聚合", "",
        "| 城市 | search | pass/fail/unknown | 组合数 | slots/options | timeline items | occurrence bindings | ID-kind-city 结构匹配 | data/adapter/solver/context/pipeline gaps | scope SHA-256 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for row in report["cities"]:
        counts = row.get("decision_counts", {})
        axes = row.get("axis_summary_over_assignments", {})
        axes_text = ", ".join(f"{axis}:{axes.get(axis, {}).get('gap_count',0)}" for axis in AXES)
        lines.append(f"| {row['city']} | {row.get('status')} | {counts.get('pass',0)}/{counts.get('fail',0)}/{counts.get('unknown',0)} | {row.get('declared_assignment_combinations',0)} | {row.get('slot_count',0)}/{row.get('candidate_option_count',0)} | {row.get('explicit_complete_plan_timeline_items',0)} | {row.get('record_binding_occurrence_count_per_assembled_plan',0)} | {row.get('structural_v4_id_kind_city_matches',0)}/{row.get('v4_records_loaded',0)} | {axes_text} | `{row.get('scope_distribution_sha256')}` |")
    lines += ["", "## Scope 分布", "", "日期、occurrence role、synthetic native/policy field 与计数；无逐题 plan 或 record。哈希仅用于复核结构摘要。", "",
        "| 城市 | 日期 | role | native field | policy field | count | control-only |",
        "|---|---|---|---|---|---:|---|"]
    for row in report["cities"]:
        for scope in row.get("scope_distribution", []):
            lines.append(f"| {row['city']} | {scope.get('date')} | {scope.get('role')} | {scope.get('native_field')} | {scope.get('policy_field')} | {scope.get('count')} | {scope.get('control_only')} |")
    lines += ["", "## 限制", "", "有限域包含完整的 synthetic 事件片段以及删去餐馆转移段的显式负例。缺转移的组合因 assembler 失败保持 unknown；完整结构组合因真实事实/evidence verifier 关闭仍 unknown，不被剪枝。该枚举只覆盖本次声明的 slot options，不说明真实任务候选空间穷尽；不代表行程完整性、可行性、真实证据或全局无解。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    json_path = args.out_dir / "strict_event_domain_v4_smoke.json"
    md_path = args.out_dir / "strict_event_domain_v4_smoke.md"
    existing = [str(path) for path in (json_path, md_path) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing artifact(s): " + ", ".join(existing))
    report = run(args.cohort, args.catalog)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(md_path.resolve()),
        "city_count": report["city_count"], "inputs_unchanged": report["source_inputs"]["inputs_unchanged"],
        "all_pass_counts_zero": all(not row.get("decision_counts", {}).get("pass", 0)
                                     for row in report["cities"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
