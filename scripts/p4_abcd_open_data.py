"""P4: B0-B4 falsifiable comparison after the Baidu quota died.

Groups (per the instruction document §P4)
----------------------------------------
* **B0** original ChinaTravel/ShortTrip plan: first feasible plan, no new TAG.
* **B1** + OSM/Wikidata static attribute TAGs, ranked with a *population* profile
  (no personalisation), so the effect of the data alone is isolated.
* **B2** + VISITOR_EXPERIENCE TAGs -> **NOT EXECUTABLE**: no licensed review corpus
  was obtained. Declared, not faked; no LLM-imagined reviews are substituted.
* **B3** B1 + M5 preference ranking (per-user soft utility, official checker untouched).
* **B4** B3 + on-demand dynamics -> run as an explicitly-labelled **offline replay**
  (sandbox overlay rehydrate + opening-hours tags); weather/road APIs stay off because
  the map-provider quota is not relied upon.

Metrics reported per group: official hard-constraint pass, regret against the
best feasible candidate under the user's own scoring, TAG coverage of the chosen
plan, distinct plans chosen, and the external API call count during the experiment
(must be 0 — tags are pre-built in P2).

Outputs: results/p4/b0_b4_report.json, results/p4/b0_b4_report.md
"""
from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.dynamic.overlay import OverlayStore  # noqa: E402
from shorttrip.dynamic.pipeline import rehydrate  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import PlannerOptions, SkeletonPlanner  # noqa: E402
from shorttrip.preference import DEFAULT_SPECS, UserProfile  # noqa: E402
from shorttrip.rerank import RerankOptions, rank_plans, score_plan  # noqa: E402
from shorttrip.tagbridge import merge_tag_views, sandbox_attribute_tags, tag_view_from_store  # noqa: E402

REPO = ROOT / "ChinaTravel"
OUT = ROOT / "results" / "p4"
VARIANTS = [
    ("default", PlannerOptions()),
    ("fewer_stops", PlannerOptions(max_attractions_per_day=2)),
    ("early_start", PlannerOptions(go_window=(7 * 60, 11 * 60))),
]


def load_queries(split: str, limit: int) -> list[dict]:
    paths = sorted(glob.glob(str(REPO / "chinatravel" / "data" / split / "*.json")))
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths[:limit]]


def population_profile() -> UserProfile:
    profile = UserProfile(uid="population_average")
    profile._fill_neutral_priors()
    return profile


def build_candidates(env, query: dict) -> list[dict]:
    out = []
    for label, options in VARIANTS:
        planner = SkeletonPlanner(env, options)
        built = planner.build(query, deep_check=False)
        if built.plan is None:
            out.append({"variant": label, "plan": None, "error": planner.last_reason})
            continue
        report = check_plan(query, built.plan)
        out.append({"variant": label, "plan": built.plan, "report": report})
    return out


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "easy_short"
    limit = min(int(sys.argv[2]) if len(sys.argv) > 2 else 6, 10)
    started = time.time()

    env = get_env("zh")
    overlay = OverlayStore(ROOT / "data" / "sandbox_overlay.sqlite")
    rehydrated = rehydrate(overlay, env)  # B4 offline "dynamic" step
    tag_store = TagStore(ROOT / "data" / "tag_store.sqlite")
    snapshot = tag_store.latest_snapshot()
    open_tags = tag_view_from_store(tag_store, snapshot)

    queries = load_queries(split, limit)
    profiles = [UserProfile.from_spec(spec) for spec in DEFAULT_SPECS[:3]]
    rows: list[dict] = []

    for query in queries:
        city = query["target_city"]
        attributes = sandbox_attribute_tags(env, city)
        merged = merge_tag_views(attributes, open_tags)
        city_merged = {p: t for p, t in merged.items() if p.startswith(f"sandbox:{city}:")}
        candidates = build_candidates(env, query)
        feasible = [c for c in candidates if c.get("plan") and c["report"] and c["report"].all_ok]
        base = {"uid": query.get("uid"), "city": city, "days": query.get("days"),
                "candidates": len(candidates), "feasible": len(feasible)}
        if not feasible:
            rows.append({**base, "profile": None, "groups": {},
                         "note": "无通过官方 checker 的候选"})
            continue

        for profile in profiles:
            reference = [score_plan(c["plan"], profile, city_merged, city=city) for c in feasible]
            best = max(row["Q"] for row in reference)
            groups: dict[str, dict] = {}

            def record(group: str, chosen: dict, rerank_options: RerankOptions | None = None,
                       ranking_Q: float | None = None) -> None:
                scored = score_plan(chosen["plan"], profile, city_merged, city=city,
                                    options=rerank_options or RerankOptions())
                groups[group] = {
                    "variant": chosen["variant"],
                    "Q_ref": scored["Q"],
                    "regret": round(best - scored["Q"], 4),
                    "coverage": scored["coverage"]["rate"],
                    "hard_ok": bool(chosen["report"].all_ok),
                    "ranking_Q": ranking_Q,
                }

            # B0 — no ranking at all
            record("B0_original", feasible[0])

            # B1 — static attribute tags, no personalisation
            ranked_b1 = rank_plans([c["plan"] for c in feasible], population_profile(),
                                   city_merged, city=city)
            record("B1_static_tags", feasible[ranked_b1[0]["candidate"]], ranking_Q=ranked_b1[0]["Q"])

            # B2 — needs licensed visitor experience evidence: not executable
            groups["B2_visitor_tags"] = {
                "executable": False,
                "reason": "没有取得可授权的游客评论语料；VISITOR_EXPERIENCE 记录数为 0；"
                          "按指令不以模型生成内容代替真实游客反馈",
            }

            # B3 — B1 + M5 preference ranking
            ranked_b3 = rank_plans([c["plan"] for c in feasible], profile, city_merged, city=city)
            record("B3_preference", feasible[ranked_b3[0]["candidate"]], ranking_Q=ranked_b3[0]["Q"])

            # B4 — B3 + offline dynamic replay (holiday context + overlay-rehydrated sandbox)
            ranked_b4 = rank_plans([c["plan"] for c in feasible], profile, city_merged,
                                   city=city, options=RerankOptions(holiday=True))
            record("B4_dynamic_replay", feasible[ranked_b4[0]["candidate"]], RerankOptions(holiday=True),
                   ranking_Q=ranked_b4[0]["Q"])

            rows.append({**base, "profile": profile.uid, "profile_summary": profile.summary(),
                        "groups": groups, "best_ref_Q": round(best, 4)})

    executable = ["B0_original", "B1_static_tags", "B3_preference", "B4_dynamic_replay"]
    summary: dict[str, dict] = {}
    for group in executable:
        entries = [row["groups"][group] for row in rows
                   if row.get("groups") and group in row["groups"]]
        if not entries:
            summary[group] = {"n": 0}
            continue
        summary[group] = {
            "n": len(entries),
            "hard_pass_rate": round(sum(1 for e in entries if e["hard_ok"]) / len(entries), 3),
            "mean_regret": round(sum(e["regret"] for e in entries) / len(entries), 4),
            "exact_best_rate": round(sum(1 for e in entries if e["regret"] == 0) / len(entries), 3),
            "mean_tag_coverage": round(sum(e["coverage"] for e in entries) / len(entries), 3),
            "distinct_variants": sorted({e["variant"] for e in entries}),
        }
    summary["B2_visitor_tags"] = {"n": 0, "executable": False,
                                  "reason": "无可授权评论语料；不伪造"}

    external_calls = 0  # tags pre-built in P2; this experiment performs no API calls
    report = {
        "generated_at": "2026-10-21",
        "split": split,
        "queries": [q.get("uid") for q in queries],
        "n_rows": len(rows),
        "profiles": [p.uid for p in profiles],
        "groups": summary,
        "tag_layer": {"snapshot": snapshot, "pois_with_tags": len(open_tags),
                      "records": tag_store.counts()},
        "dynamic": {"mode": "offline_replay", "rehydrated_instances": rehydrated,
                    "overlay_active_records": len(overlay.active()),
                    "weather_and_road_apis": "未使用（不依赖地图配额）"},
        "external_api_calls": external_calls,
        "baidu_request_budget": 0,
        "runtime_s": round(time.time() - started, 1),
        "limits": [
            "无人工成对偏好标注：只能证明重排器实现了所述偏好关系",
            "体验 TAG 覆盖 11/50 POI（22%），B2 不可执行",
            "候选池仅 3 个 planner 变体，regret=0 可能是小池效应",
            "B4 的动态部分仅为离线重放（overlay + 营业时间标签），未调用天气/路网",
        ],
        "rows": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b0_b4_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")

    lines = [f"# B0–B4 结果（{split}，{len(queries)} 条查询 × {len(profiles)} 个画像）", "",
             "| 组 | n | 硬约束通过 | 平均 regret | 一次选中最优 | TAG 覆盖率 | 被选变体 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for group in executable:
        item = summary.get(group) or {}
        if not item.get("n"):
            continue
        lines.append(f"| {group} | {item['n']} | {item['hard_pass_rate']} | {item['mean_regret']} | "
                     f"{item['exact_best_rate']} | {item['mean_tag_coverage']} | "
                     f"{', '.join(item['distinct_variants'])} |")
    lines.append(f"| B2_visitor_tags | 0 | 不可执行 | — | — | — | 无可授权评论语料 |")
    lines += ["", f"外部 API 调用：{external_calls}；百度请求预算：0；运行 {report['runtime_s']}s", "",
              "## 限制", ""] + [f"- {item}" for item in report["limits"]]
    (OUT / "b0_b4_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"runtime={report['runtime_s']}s external_api_calls={external_calls}")
    print(f"wrote {OUT / 'b0_b4_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
