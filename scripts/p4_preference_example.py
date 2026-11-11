"""P4 appendix: two users, same hard constraints, two different rankings.

Requirement (§4): "相同硬约束下两名不同偏好用户的两套排序、评分解释和来源定位；
如果证据覆盖不足，标记'不足以区分'".

The script picks a query, builds the same candidate pool, proves every candidate
passes the official checker, then re-ranks the pool for two profiles and prints
1) the ordering, 2) the per-attraction explanation, 3) the evidence location
(source URL / OSM id / Wikidata QID) behind each tag that moved the score.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import PlannerOptions, SkeletonPlanner  # noqa: E402
from shorttrip.preference import UserProfile  # noqa: E402
from shorttrip.rerank import rank_plans, score_plan  # noqa: E402
from shorttrip.tagbridge import merge_tag_views, sandbox_attribute_tags, tag_view_from_store  # noqa: E402

OUT = ROOT / "results" / "p4" / "preference_example.json"
PROFILES = [
    {"uid": "history_buff_no_walk", "people": 2, "with_elders": True, "walking_tolerance": 0.2,
     "max_queue": 0.25, "price_sensitivity": 0.3,
     "interests": {"history_culture": 1.0, "architecture": 0.4}},
    {"uid": "nature_photo_active", "people": 2, "walking_tolerance": 0.9, "max_queue": 0.8,
     "price_sensitivity": 0.2, "night_preference": True,
     "interests": {"nature": 1.0, "photography": 1.0}},
]


def main() -> int:
    env = get_env("zh")
    store = TagStore(ROOT / "data" / "tag_store.sqlite")
    snapshot = store.latest_snapshot()
    external = tag_view_from_store(store, snapshot)
    payloads = {(row["local_poi_id"], row["tag_id"]): row
                for row in store.payloads(snapshot, status="accept")}

    queries = [json.loads(Path(p).read_text(encoding="utf-8"))
               for p in sorted(glob.glob(str(ROOT / "ChinaTravel" / "chinatravel" / "data" / "easy_short" / "*.json")))]

    chosen_query = None
    chosen_pool = None
    for query in queries:
        city = query["target_city"]
        merged = merge_tag_views(sandbox_attribute_tags(env, city), external)
        city_view = {p: t for p, t in merged.items() if p.startswith(f"sandbox:{city}:")}
        pool = []
        for label, options in (("default", PlannerOptions()),
                               ("fewer_stops", PlannerOptions(max_attractions_per_day=2)),
                               ("early_start", PlannerOptions(go_window=(7 * 60, 11 * 60)))):
            built = SkeletonPlanner(env, options).build(query, deep_check=False)
            if built.plan is None:
                continue
            report = check_plan(query, built.plan)
            if report.all_ok:
                pool.append({"variant": label, "plan": built.plan, "report": report})
        if len(pool) < 2:
            continue
        # prefer a query whose candidates actually differ in tagged attractions
        profiles = [UserProfile.from_spec(spec) for spec in PROFILES]
        rankings = []
        for profile in profiles:
            rankings.append([row["candidate"] for row in
                             rank_plans([c["plan"] for c in pool], profile, city_view, city=city)])
        if rankings[0] != rankings[1]:
            chosen_query, chosen_pool = query, pool
            break
    if chosen_query is None:
        print("不足以区分：在 easy_short 上未找到两位用户排序不同的查询")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"conclusion": "不足以区分", "reason": "所有查询两用户排序一致"},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    city = chosen_query["target_city"]
    merged = merge_tag_views(sandbox_attribute_tags(env, city), external)
    city_view = {p: t for p, t in merged.items() if p.startswith(f"sandbox:{city}:")}

    result = {"query": {"uid": chosen_query.get("uid"), "city": city,
                        "days": chosen_query.get("days"),
                        "nature_language": chosen_query.get("nature_language")},
              "candidates": [{"variant": c["variant"], "hard_ok": c["report"].all_ok} for c in chosen_pool],
              "profiles": []}

    for spec in PROFILES:
        profile = UserProfile.from_spec(spec)
        rows = rank_plans([c["plan"] for c in chosen_pool], profile, city_view, city=city)
        entry = {"uid": profile.uid, "summary": profile.summary(),
                 "weights": profile.weights(), "ranking": []}
        print(f"\n=== {profile.uid}  ({profile.summary()})")
        for row in rows:
            variant = chosen_pool[row["candidate"]]["variant"]
            scored = score_plan(row["plan"], profile, city_view, city=city)
            print(f"  #{row['rank']} {variant:12s} Q={row['Q']:+.4f} "
                  f"match={scored['components']['match']:.3f} "
                  f"coverage={scored['coverage']['rate']:.2f}")
            evidence = []
            for explanation in scored["explanations"]:
                poi_name = explanation["poi"]
                poi_id = f"sandbox:{city}:{poi_name}"
                tags = city_view.get(poi_id) or {}
                refs = []
                for tag_id, tag_payload in tags.items():
                    key = (poi_id, tag_id)
                    if key not in payloads:
                        continue
                    refs.append({"tag_id": tag_id, "value": tag_payload.get("value"),
                                 "confidence": tag_payload.get("confidence"),
                                 "evidence_class": payloads[key].get("evidence_class"),
                                 "source": payloads[key].get("source_name"),
                                 "source_record_id": payloads[key].get("source_record_id"),
                                 "source_url": payloads[key].get("source_url"),
                                 "licence": payloads[key].get("licence_status")})
                evidence.append({"poi": poi_name, "match": explanation["match"],
                                 "why": explanation["why"], "tags": refs})
            entry["ranking"].append({
                "rank": row["rank"], "variant": variant, "Q": row["Q"],
                "selection_reason": row.get("penalties") and {
                    key: value for key, value in row["penalties"].items() if value > 0},
                "components": scored["components"], "coverage": scored["coverage"],
                "uncertainty": scored["uncertainty"],
                "itinerary_change": scored["itinerary_change"],
                "evidence": evidence,
            })
        result["profiles"].append(entry)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
