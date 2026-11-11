"""Five-city, development-only synthetic assembly/search control smoke.

Real v6 development-selected IDs and read-only v4 records exercise the local
assembler/development-orchestrator/search path. Every time and movement is a
synthetic control. No identity or factual verifier is enabled; outputs are
aggregate only and never contain per-task plans, records, or holdout rows.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import strict_multiday_v4_control_smoke as prior_control
from shorttrip.strict_plan_assembler import assemble_strict_plan
from shorttrip.strict_search_orchestrator import search_development_assignments
from shorttrip.strict_v4_reader import V4Reader


DEFAULT_COHORT = ROOT / "results/p43_timeonly_1030/cohort_v6_syntax_compiled.json"
DEFAULT_CATALOG = ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3"
DEFAULT_OUT = ROOT / "results/manual_20261031_1332/assembler_v4_control"
START_KIND_ORDER = ("poi", "metro_station", "train", "flight")
TIMEZONE = "+08:00"
NOW = "2026-10-31T00:00:00Z"
AXES = ("data", "adapter", "solver", "context")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    """Hash a stable JSON representation of aggregate structural metadata."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _runtime_manifest() -> dict[str, Any]:
    entries = [
        {"module": "__main__", "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
         "sha256": _sha256_file(Path(__file__).resolve())},
        {"module": "strict_multiday_v4_control_smoke",
         "path": prior_control.__file__ and Path(prior_control.__file__).resolve().relative_to(ROOT).as_posix(),
         "sha256": _sha256_file(Path(prior_control.__file__).resolve())},
    ]
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
                            "sha256": _sha256_file(path)})
    entries.sort(key=lambda item: (item["module"], item["path"]))
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return {"classification": "engineering_code_snapshot_not_formal_freeze",
            "module_count_including_scripts": len(entries),
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "modules": entries}


def _dates(task: dict[str, Any]) -> list[str] | None:
    if task.get("days") != 3 or not isinstance(task.get("start_date"), str):
        return None
    try:
        start = date.fromisoformat(task["start_date"])
    except ValueError:
        return None
    if start.isoformat() != task["start_date"]:
        return None
    return [(start + timedelta(days=i)).isoformat() for i in range(3)]


def _selected(task: dict[str, Any]) -> tuple[dict[str, tuple[str, dict]], dict[str, str]]:
    by_id = prior_control._selected_by_id(task)
    by_kind: dict[str, str] = {}
    for entity_id, (kind, _item) in by_id.items():
        if kind in by_kind:
            raise ValueError("more_than_one_selected_id_for_kind")
        by_kind[kind] = entity_id
    declared = task.get("candidate_selection", {}).get("required_entity_ids", [])
    if not isinstance(declared, list) or set(declared) != set(by_id):
        raise ValueError("candidate_selection_id_mapping_mismatch")
    return by_id, by_kind


def _synthetic_daily(task: dict[str, Any], by_id: dict[str, tuple[str, dict]],
                     by_kind: dict[str, str], dates: list[str], start_id: str) -> list[dict]:
    attraction_id, restaurant_id, hotel_id = (by_kind["attraction"],
                                               by_kind["restaurant"],
                                               by_kind["accommodation"])
    days = []
    for day_index, day in enumerate(dates):
        first_id = start_id if day_index == 0 else hotel_id
        first_kind = by_id[first_id][0]
        first_entrance = "synthetic-start-entrance" if day_index == 0 else "synthetic-lodging-entrance"
        prefix = f"control-day-{day_index + 1}"
        timeline = [
            {"occurrence_id": prefix + "-route-to-attraction", "type": "travel",
             "origin_id": first_id, "origin_kind": first_kind,
             "origin_entrance_id": first_entrance,
             "destination_id": attraction_id, "destination_kind": "attraction",
             "destination_entrance_id": "synthetic-attraction-entrance",
             "start": "09:00:00" + TIMEZONE, "end": "09:30:00" + TIMEZONE,
             "mode": "synthetic-control-mode"},
            {"occurrence_id": prefix + "-visit", "type": "visit",
             "entity_id": attraction_id, "entity_kind": "attraction",
             "entrance_id": "synthetic-attraction-entrance",
             "start": "09:30:00" + TIMEZONE, "end": "10:30:00" + TIMEZONE},
            {"occurrence_id": prefix + "-route-to-restaurant", "type": "travel",
             "origin_id": attraction_id, "origin_kind": "attraction",
             "origin_entrance_id": "synthetic-attraction-entrance",
             "destination_id": restaurant_id, "destination_kind": "restaurant",
             "destination_entrance_id": "synthetic-restaurant-entrance",
             "start": "10:30:00" + TIMEZONE, "end": "10:50:00" + TIMEZONE,
             "mode": "synthetic-control-mode"},
            {"occurrence_id": prefix + "-lunch", "type": "lunch",
             "entity_id": restaurant_id, "entity_kind": "restaurant",
             "entrance_id": "synthetic-restaurant-entrance",
             "start": "10:50:00" + TIMEZONE, "end": "11:30:00" + TIMEZONE},
            {"occurrence_id": prefix + "-route-to-lodging", "type": "travel",
             "origin_id": restaurant_id, "origin_kind": "restaurant",
             "origin_entrance_id": "synthetic-restaurant-entrance",
             "destination_id": hotel_id, "destination_kind": "accommodation",
             "destination_entrance_id": "synthetic-lodging-entrance",
             "start": "11:30:00" + TIMEZONE, "end": "12:00:00" + TIMEZONE,
             "mode": "synthetic-control-mode"},
        ]
        days.append({"date": day, "city": task["target_city"],
                     "start_location": {"entity_id": first_id, "kind": first_kind,
                                        "entrance_id": first_entrance},
                     "timeline": timeline})
    return days


def _bindings(task: dict[str, Any], plan: dict, by_id: dict[str, tuple[str, dict]],
              reader: V4Reader) -> tuple[list[dict], dict[str, int]]:
    refs: dict[str, list[dict]] = {}

    def add(entity_id: str, day_index: int, item_index: int, role: str):
        day = plan["days"][day_index]["date"]
        refs.setdefault(entity_id, []).append({
            "day_index": day_index, "item_index": item_index, "role": role,
            "requirements": [{"native_field": "synthetic_control_field",
                "policy_field": "synthetic_control_requirement",
                "scope": {"travel_date": day, "occurrence_role": role,
                          "control_only": True}}],
        })

    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] in {"visit", "attraction", "breakfast", "lunch", "dinner", "meal"}:
                add(item["entity_id"], day_index, item_index, "activity")
            elif item["type"] == "travel":
                add(item["origin_id"], day_index, item_index, "travel_origin")
                add(item["destination_id"], day_index, item_index, "travel_destination")

    output, matches, load_errors = [], 0, 0
    structural_checks = []
    for entity_id, occurrences in sorted(refs.items()):
        selected = by_id.get(entity_id)
        if selected is None:
            load_errors += 1
            continue
        expected_kind = selected[0]
        try:
            record = reader.get(entity_id)
        except Exception:
            load_errors += 1
            structural_checks.append({"entity_id": entity_id, "kind": expected_kind,
                "city": task.get("target_city"), "record_loaded": False,
                "id_matches": False, "kind_matches": False, "city_matches": False})
            continue
        id_matches = record.get("id") == entity_id
        kind_matches = record.get("kind") == expected_kind
        city_matches = record.get("city") == task.get("target_city")
        structural_checks.append({"entity_id": entity_id, "kind": expected_kind,
            "city": task.get("target_city"), "record_loaded": True,
            "id_matches": id_matches, "kind_matches": kind_matches,
            "city_matches": city_matches})
        if id_matches and kind_matches and city_matches:
            matches += 1
        output.append({"entity_id": entity_id, "kind": expected_kind,
                       "record": record, "occurrences": occurrences})
    occurrence_scopes = []
    for entity_id, occurrences in sorted(refs.items()):
        kind = by_id.get(entity_id, (None,))[0]
        for occurrence in occurrences:
            requirement = occurrence["requirements"][0]
            scope = requirement["scope"]
            occurrence_scopes.append({"date": scope["travel_date"],
                "role": scope["occurrence_role"],
                "native_field": requirement["native_field"],
                "policy_field": requirement["policy_field"],
                "control_only": scope["control_only"]})
    distribution_counts: dict[tuple[str, str, str, str], int] = {}
    for item in occurrence_scopes:
        key = (item["date"], item["role"], item["native_field"], item["policy_field"])
        distribution_counts[key] = distribution_counts.get(key, 0) + 1
    scope_distribution = [{"date": key[0], "role": key[1],
        "native_field": key[2], "policy_field": key[3], "count": count,
        "control_only": True}
        for key, count in sorted(distribution_counts.items())]
    candidate_check_summary = {
        "checks": structural_checks,
        "canonical_sha256": _canonical_sha256(structural_checks),
    }
    scope_summary = {
        "distribution": scope_distribution,
        "occurrence_count": len(occurrence_scopes),
        "canonical_sha256": _canonical_sha256(sorted(occurrence_scopes,
            key=lambda item: (item["date"], item["role"], item["native_field"],
                              item["policy_field"], item["control_only"]))),
    }
    return output, {"referenced_entity_count": len(refs),
                    "records_loaded": len(output),
                    "structural_id_kind_city_matches": matches,
                    "record_load_errors": load_errors,
                    "independent_identity_verified_count": 0,
                    "candidate_structure": candidate_check_summary,
                    "occurrence_scope_audit": scope_summary}


def _diagnostic_inputs(plan: dict) -> dict[str, Any]:
    meal_events, boundaries = [], []
    for day_index, day in enumerate(plan["days"]):
        for item_index, item in enumerate(day["timeline"]):
            if item["type"] == "lunch":
                meal_events.append({"date": day["date"], "item_index": item_index,
                    "type": item["type"], "entity_id": item["entity_id"],
                    "event_id": f"synthetic-meal-event-{day_index + 1}", "slot": "lunch"})
    for index in range(2):
        previous, following = plan["days"][index], plan["days"][index + 1]
        last = previous["timeline"][-1]
        first = following["timeline"][0]
        boundaries.append({"previous_day": previous["date"], "next_day": following["date"],
            "last_endpoint": {"entity_id": last["destination_id"],
                "entrance_id": last["destination_entrance_id"],
                "datetime": previous["date"] + "T" + last["end"]},
            "first_endpoint": {"entity_id": first["origin_id"],
                "entrance_id": first["origin_entrance_id"],
                "datetime": following["date"] + "T" + first["start"]},
            "lodging_entrance_id": "synthetic-lodging-entrance",
            # No room type, eligibility, taxes or quote is inferred from the catalog.
            "lodging_requirement": None, "lodging_claim": None})
    return {"meal_coverage": {"required_slots": None, "events": meal_events},
            "overnight_boundaries": boundaries}


def _city_run(city: str, task: dict, reader: V4Reader) -> dict[str, Any]:
    dates = _dates(task)
    try:
        by_id, by_kind = _selected(task)
    except Exception as exc:
        return _incomplete_city(city, "candidate_selection_mapping_invalid", type(exc).__name__)
    needed = {"attraction", "restaurant", "accommodation"}
    starts = [by_kind[k] for k in START_KIND_ORDER if k in by_kind]
    if dates is None:
        return _incomplete_city(city, "three_day_dates_missing_or_invalid")
    if not needed.issubset(by_kind) or not starts:
        return _incomplete_city(city, "required_synthetic_control_kind_unavailable")
    start_id = starts[0]
    context = {"uid": task.get("uid"), "level": task.get("level"),
        "start_city": task.get("start_city"), "target_city": task.get("target_city"),
        "start_date": task.get("start_date"), "days": task.get("days"),
        "people_number": task.get("people_number"), "start_location_id": start_id}
    assembled = assemble_strict_plan(context,
        _synthetic_daily(task, by_id, by_kind, dates, start_id),
        entity_kinds={key: value[0] for key, value in by_id.items()},
        repeat_policy={"allow_repeated_occurrence_entities": True})
    if assembled.get("status") != "synthetic_plan_assembled_unverified":
        return _incomplete_city(city, "assembler_blocked", assembled.get("reason"))
    plan = assembled["plan"]
    bindings, binding_counts = _bindings(task, plan, by_id, reader)
    plan_context = {"start_city": task.get("start_city"),
        "target_city": task.get("target_city"), "start_date": task.get("start_date"),
        "days": task.get("days"), "people_number": task.get("people_number"),
        "start_location_id": start_id, "control_marker": "synthetic_v4_control"}

    def resolver(task_copy, assignment):
        if set(assignment) != {"control_case"}:
            raise ValueError("synthetic_assignment_shape_invalid")
        return {"plan": copy.deepcopy(plan), "plan_context": copy.deepcopy(plan_context),
            "record_bindings": copy.deepcopy(bindings), "now": NOW, "registry": {},
            "diagnostic_inputs": _diagnostic_inputs(plan),
            "diagnostic_callbacks": {}}

    search = search_development_assignments(task, {"control_case": ["one-synthetic-case"]},
        resolver=resolver, decision_verifier=None, max_assignments=2)
    diagnostics = search.get("diagnostics") or []
    diagnostic = diagnostics[0].get("diagnostic", {}) if diagnostics else {}
    raw_axes = diagnostic.get("axes", {}) if isinstance(diagnostic, dict) else {}
    axes = {axis: {"gap_count": len(raw_axes.get(axis, [])),
                   "reason_counts": _count_reasons(raw_axes.get(axis, []))}
            for axis in AXES}
    checks = (list(diagnostic.get("hard_failures", [])) +
              list(diagnostic.get("unknown_checks", []))) if isinstance(diagnostic, dict) else []
    counts = search.get("decision_counts") or {}
    return {"city": city, "status": search.get("status"),
        "assignment_count": search.get("enumerated_assignment_count", 0),
        "decision_counts": {key: counts.get(key, 0) for key in ("pass", "fail", "unknown")},
        "search_unknown_assignment_count": search.get("unknown_assignment_count", 0),
        "diagnostic_check_count": len(checks),
        "diagnostic_unknown_check_count": sum(1 for item in checks
            if isinstance(item, dict) and item.get("state") == "unknown"),
        "axes": axes,
        "assembled_day_count": len(plan["days"]),
        "assembled_timeline_item_count": sum(len(day["timeline"]) for day in plan["days"]),
        "occurrence_binding_count": sum(len(item["occurrences"]) for item in bindings),
        "meal_event_count": len(_diagnostic_inputs(plan)["meal_coverage"]["events"]),
        "binding_counts": binding_counts,
        "all_real_identity_and_fact_verifiers_disabled": True,
        "synthetic_times_routes_meals_and_entrances": True,
        "plan_or_record_payload_emitted": False,
        "truth_certified": False, "execution_confirmed": False,
        "complete_planner_integrated": False}


def _count_reasons(gaps: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(gaps, list):
        return result
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        reason = gap.get("reason")
        if isinstance(reason, str):
            result[reason] = result.get(reason, 0) + 1
    return dict(sorted(result.items()))


def _incomplete_city(city: str, reason: str, detail: str | None = None) -> dict[str, Any]:
    return {"city": city, "status": "solver_incomplete", "reason_code": reason,
            "detail_code": detail, "decision_counts": {"pass": 0, "fail": 0, "unknown": 1},
            "all_real_identity_and_fact_verifiers_disabled": True,
            "synthetic_times_routes_meals_and_entrances": True,
            "plan_or_record_payload_emitted": False,
            "truth_certified": False, "execution_confirmed": False,
            "complete_planner_integrated": False}


def run(cohort_path: Path, catalog_path: Path) -> dict[str, Any]:
    cohort_before = _sha256_file(cohort_path)
    catalog_before = _sha256_file(catalog_path)
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    tasks_by_city, summary = prior_control._choose_task_by_city(cohort)
    reader = V4Reader(catalog_path)
    try:
        cities = [_city_run(city, tasks_by_city[city], reader)
                  for city in sorted(prior_control.EXPECTED_CITIES)]
    finally:
        reader.close()
    cohort_after = _sha256_file(cohort_path)
    catalog_after = _sha256_file(catalog_path)
    if cohort_before != cohort_after or catalog_before != catalog_after:
        raise RuntimeError("cohort or catalog changed during read-only control smoke")
    if any(item.get("decision_counts", {}).get("pass", 0) != 0 for item in cities):
        raise RuntimeError("unexpected pass with factual verifiers disabled")
    return {"artifact": "strict-assembler-v4-development-control-smoke-v1",
        "label": "engineering_only", "mode": "read_only_v4_records_and_development_only_synthetic_assembly_search",
        "source_inputs": {"cohort": str(cohort_path.resolve()),
            "cohort_sha256_before": cohort_before, "cohort_sha256_after": cohort_after,
            "catalog": str(catalog_path.resolve()), "catalog_sha256_before": catalog_before,
            "catalog_sha256_after": catalog_after, "inputs_unchanged": True},
        "development_task_count": summary[0]["development_task_count"],
        "city_count": len(cities), "cities": cities,
        "all_real_identity_and_fact_verifiers_disabled": True,
        "synthetic_controls_are_not_facts_or_user_intent": True,
        "holdout_task_payload_used": False, "holdout_per_task_output_emitted": False,
        "per_task_plan_or_record_output_emitted": False,
        "formal_evaluation_performed": False, "freeze_approved": False,
        "global_unsat_claimed": False, "truth_certified": False,
        "execution_confirmed": False, "runtime_code_snapshot": _runtime_manifest()}


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# 五城 v4 三日 assembler/search 工程冒烟", "",
        "本报告只包含开发 split 的城市级聚合结果。task 选择的 catalog ID 和 v4 record 仅用于类型/日期/occurrence 结构接线；不输出逐题 plan、record payload 或 holdout 信息。每日 start、餐次、路线、entrance 与时间均为合成控制值，不是用户意图或旅行事实。所有真实 identity、field、route、opening、meal、overnight 和其他事实 verifier 均关闭。", "",
        "## 输入完整性", "",
        f"- development cohort task 数：{report['development_task_count']}；输出城市行：{report['city_count']}（只选 development/purpose=development）。",
        f"- cohort SHA-256 前后相同：{report['source_inputs']['cohort_sha256_before'] == report['source_inputs']['cohort_sha256_after']} (`{report['source_inputs']['cohort_sha256_before']}`)。",
        f"- read-only v4 catalog SHA-256 前后相同：{report['source_inputs']['catalog_sha256_before'] == report['source_inputs']['catalog_sha256_after']} (`{report['source_inputs']['catalog_sha256_before']}`)。",
        "- 每城严格复用 development task 的候选 ID；候选结构每 kind 一个 ID。v4 ID/kind/city 只记录结构对应计数，不等于独立身份验证。", "",
        "## 城市级结果", "",
        "| 城市 | 搜索状态 | pass/fail/unknown | timeline 项 | occurrence bindings | meal events | ID-kind-city 对应 | 轴缺口 data/adapter/solver/context |",
        "|---|---|---:|---:|---:|---:|---:|---|"]
    for row in report["cities"]:
        counts = row.get("decision_counts", {})
        bindings = row.get("binding_counts", {})
        axis_summary = ", ".join(f"{axis}:{row.get('axes', {}).get(axis, {}).get('gap_count', 0)}"
                                  for axis in AXES)
        match = (f"{bindings.get('structural_id_kind_city_matches', 0)}/"
                 f"{bindings.get('records_loaded', 0)} (identity verifier off)")
        lines.append(f"| {row['city']} | {row.get('status')} | {counts.get('pass',0)}/{counts.get('fail',0)}/{counts.get('unknown',0)} | {row.get('assembled_timeline_item_count',0)} | {row.get('occurrence_binding_count',0)} | {row.get('meal_event_count',0)} | {match} | {axis_summary} |")
    lines += ["", "## Occurrence scope 与候选结构审计", "",
        "下表只给日期、occurrence 角色、合成字段名及计数，不含计划、record payload 或 holdout 内容。每城 scope 摘要哈希以 canonical JSON（UTF-8、键排序、紧凑分隔符）计算；候选结构哈希覆盖有序的 ID/kind/目标城市及各结构检查布尔值。哈希用于复核此控制输入的稳定性，不是事实或身份认证。", "",
        "| 城市 | 日期 | 角色 | native_field | policy_field | 数量 | control_only |",
        "|---|---|---|---|---|---:|---|"]
    for row in report["cities"]:
        audit = row.get("binding_counts", {}).get("occurrence_scope_audit", {})
        for item in audit.get("distribution", []):
            lines.append(f"| {row['city']} | {item['date']} | {item['role']} | {item['native_field']} | {item['policy_field']} | {item['count']} | {item['control_only']} |")
        structure = row.get("binding_counts", {}).get("candidate_structure", {})
        lines.append("")
        lines.append(f"**{row['city']} scope**：{audit.get('occurrence_count', 0)} occurrences；canonical SHA-256 `{audit.get('canonical_sha256', 'unavailable')}`。")
        lines.append(f"**{row['city']} candidate structure**：canonical SHA-256 `{structure.get('canonical_sha256', 'unavailable')}`；" + ", ".join(
            f"`{check.get('entity_id')}` / {check.get('kind')} / {check.get('city')} (loaded={check.get('record_loaded')}, id={check.get('id_matches')}, kind={check.get('kind_matches')}, city={check.get('city_matches')})"
            for check in structure.get("checks", [])) + ".")
    lines += ["", "## 解释与限制", "",
        "预期 search 结果是 `solver_incomplete`：没有真实 verifier，因此 field/identity/route/chronology/meal/overnight 组件保持 unknown；未知分支没有被剪枝。所有城市统一采用 synthetic mode、固定 offset 时间与 synthetic entrance。饭次事件仅表达输入中有一条合成 lunch；任务没有可安全识别的 required meal-slot policy 时，不推导每日必餐。住宿 claim/房型不由目录推测，overnight scope 因此保持 unknown。",
        "v4 ID-kind-city 对应仅是 record binding 的结构检查，不证明 ID 对应现实实体；catalog 内记录和 claims 不构成此冒烟的已验证事实。固定 planner/coverage gap、task scope/context gap 与所有 diagnostic axes 均按 search/orchestrator 输出保留。没有三日规划完整性、可行性、域完备、正式评分、冻结或全局无解结论。", "",
        "## 复现", "", "```powershell", "$env:PYTHONPATH='src'",
        "python scripts/strict_assembler_v4_control_smoke.py", "```", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    json_path = args.out_dir / "strict_assembler_v4_control_smoke.json"
    markdown_path = args.out_dir / "strict_assembler_v4_control_smoke.md"
    existing = [str(path) for path in (json_path, markdown_path) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing artifact(s): " + ", ".join(existing))
    report = run(args.cohort, args.catalog)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path.resolve()),
                      "markdown": str(markdown_path.resolve()),
                      "city_count": report["city_count"],
                      "inputs_unchanged": report["source_inputs"]["inputs_unchanged"],
                      "all_pass_counts_zero": all(
                          item.get("decision_counts", {}).get("pass", 0) == 0
                          for item in report["cities"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
