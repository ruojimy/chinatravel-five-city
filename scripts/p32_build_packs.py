"""P32: build LLM input packs for the 96 P31 tasks.

Two packs per task:
  p32_llm_96/packs/<uid>_static.json  -- task only (no dynamic evidence)
  p32_llm_96/packs/<uid>_final.json   -- task + frozen Amap evidence (weather/route/place/detail)

Also writes p32_llm_96/baseline.json: the rule planner's per-task facts, used for comparison.

No network. Reads only the frozen P31 artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from p31_common import OUT as P31, haversine_km, read_json, write_json
from p31_static import fields_required, missing_fields

ROOT = Path(__file__).resolve().parents[1]
P32 = ROOT / "results/p32_llm_96"

KEEP_CAND_KEYS = ("entity_id", "name", "city", "kind", "data", "coordinate_system",
                  "missing_fields", "tags")


def slim_task(task):
    """Task view with provenance URLs removed (they carry no planning signal)."""
    out = {
        "uid": task["uid"],
        "level": task["level"],
        "nature_language": task["nature_language"],
        "people_number": task["people_number"],
        "city_sequence": task["city_sequence"],
        "dates": task["dates"],
        "start": task["start"],
        "constraints": task["constraints"],
        "static_estimate": task["static_estimate"],
        "retrieval_budget": task.get("retrieval_budget"),
        "candidates": [{k: c.get(k) for k in KEEP_CAND_KEYS} for c in task["candidates"]],
    }
    if task.get("intercity"):
        out["intercity"] = {k: task["intercity"].get(k) for k in KEEP_CAND_KEYS}
    if task.get("old_city"):
        out["old_city"] = {
            "city": task["old_city"]["city"],
            "attraction": {k: task["old_city"]["attraction"].get(k) for k in KEEP_CAND_KEYS},
        }
    return out


def hhmm_windows(w):
    if not w:
        return None
    return [f"{int(a)//60:02d}:{int(a)%60:02d}-{int(b)//60:02d}:{int(b)%60:02d}" for a, b in w]


def load_responses():
    by_uid = {}
    for f in (P31 / "retrieval/responses").rglob("*.json"):
        d = read_json(f)
        by_uid.setdefault(d["uid"], []).append(d)
    return by_uid


def load_details():
    by_uid = {}
    for f in (P31 / "retrieval/details").rglob("*.json"):
        d = read_json(f)
        by_uid.setdefault(d["uid"], []).append(d)
    return by_uid


def task_timeline_facts(plan):
    """Extract rule-planner order / lunch position from a static plan."""
    order, lunch_after = [], None
    n_visits = 0
    for x in plan["days"][0]["timeline"]:
        if x["type"] == "visit":
            order.append(x["entity"])
            n_visits += 1
        elif x["type"] == "meal":
            lunch_after = n_visits
    return order, lunch_after


def evidence_for(task, responses, details):
    uid = task["uid"]
    name_by_eid = {c["entity_id"]: c["name"] for c in task["candidates"]}
    weather, routes, places, dets = [], [], [], []
    stamps = []
    for d in responses:
        stamps.append(d.get("retrieved_at"))
        p = d.get("parsed") or {}
        if d["type"] == "weather":
            v = p.get("value") or {}
            weather.append({
                "city": d["request"]["city"], "date": d["request"]["date"],
                "ok": bool(v),
                "dayweather": v.get("dayweather"), "nightweather": v.get("nightweather"),
                "daytemp": v.get("daytemp"), "nighttemp": v.get("nighttemp"),
                "daywind": v.get("daywind"), "daypower": v.get("daypower"),
                "reporttime": p.get("reporttime"), "req_id": d["req_id"],
            })
        elif d["type"] == "route":
            r = d["request"]
            legs = [] if not p.get("ok") else [x.get("name") for x in (p.get("lines") or [])]
            dist = None
            try:
                a, b = r["from_coord"], r["to_coord"]
                dist = round(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), 2)
            except Exception:
                pass
            routes.append({
                "from": r["from"], "to": r["to"],
                "status": "ok" if p.get("ok") else "no_transit_route",
                "duration_min": p.get("duration_min"), "fare_cny": p.get("fare"),
                "modes": p.get("modes"), "lines": legs,
                "straight_line_km": dist,
                "departure": r.get("departure"), "req_id": d["req_id"],
            })
        elif d["type"] == "place":
            eid = d["request"]["entity_id"]
            places.append({
                "entity": name_by_eid.get(eid, d["request"]["name"]),
                "matched": p.get("ok"),
                "matched_name": p.get("name"), "match_score": p.get("match_score"),
                "location_gcj02": p.get("location_gcj02"),
                "opentime_text": p.get("opentime_text"),
                "opentime_windows": hhmm_windows(p.get("opentime_windows")),
                "address": p.get("address"), "type": p.get("type"),
                "req_id": d["req_id"],
            })
    for d in details:
        dets.append({
            "entity": name_by_eid.get(d["entity_id"], d.get("name")),
            "hours_text": d.get("hours_text"),
            "hours_window": hhmm_windows([d["hours_window"]] if d.get("hours_window") else None),
            "cost_text": d.get("cost_text"), "rating": d.get("rating"),
            "poi_id": d.get("poi_id"), "retrieved_at": d.get("retrieved_at"),
        })
    routes.sort(key=lambda x: (x["from"], x["to"]))
    weather.sort(key=lambda x: (x["date"], x["city"]))
    stamps = [s for s in stamps if s]
    return {
        "source": "高德 Web 服务（weatherInfo / direction/transit/integrated / place/text / place/detail）",
        "retrieved_at_range": [min(stamps), max(stamps)] if stamps else None,
        "coverage_note": "路线证据只覆盖下面 routes 列出的 (from,to) OD 对；没有列出的段没有实测，不能当作已知。",
        "weather": weather,
        "routes": routes,
        "places": places,
        "details": dets,
    }


def main():
    P32.mkdir(parents=True, exist_ok=True)
    (P32 / "packs").mkdir(exist_ok=True)
    tasks = read_json(P31 / "tasks/all_96.json")
    static = {p["uid"]: p for p in read_json(P31 / "static/plans_all_96.json")}
    finals = {f["uid"]: f for f in read_json(P31 / "final/plans_all_96.json")}
    responses = load_responses()
    details = load_details()

    baseline = []
    for t in tasks:
        uid = t["uid"]
        slim = slim_task(t)
        ev = evidence_for(t, responses.get(uid, []), details.get(uid, []))
        write_json(P32 / "packs" / f"{uid}_static.json", {
            "schema": "p32-llm-pack-v1", "uid": uid, "stage": "static",
            "note": "只有静态候选，没有任何动态证据；未知就是未知。",
            "task": slim,
        })
        write_json(P32 / "packs" / f"{uid}_final.json", {
            "schema": "p32-llm-pack-v1", "uid": uid, "stage": "final",
            "note": "静态候选 + 2026-10-26 冻结的高德证据。",
            "task": slim,
            "evidence": ev,
        })
        order, lunch_after = task_timeline_facts(static[uid])
        f = finals[uid]
        baseline.append({
            "uid": uid, "level": t["level"],
            "people_number": t["people_number"],
            "city_sequence": t["city_sequence"],
            "scope": "chain" if t.get("intercity") else "single_city",
            "order": order, "lunch_after": lunch_after,
            "status": f["status"], "end": f["end"], "deadline": f["deadline"],
            "reasons": f["reasons"],
            "checks": f["checks"], "cost": f["cost"],
            "static": static[uid]["static"],
            "requests": static[uid]["requests"],
            "required_fields": [{"entity_id": e, "field": fl} for e, fl in fields_required(t)],
            "required_gaps": missing_fields(t),
            "evidence_counts": {
                "weather": len(ev["weather"]), "route": len(ev["routes"]),
                "place": len(ev["places"]), "detail": len(ev["details"]),
                "route_ok": sum(1 for r in ev["routes"] if r["status"] == "ok"),
            },
        })
    write_json(P32 / "baseline.json", baseline)

    # manifest
    files = sorted((P32 / "packs").glob("*.json"))
    manifest = {
        "schema": "p32-llm-96",
        "created_at": "2026-10-26T23:10:00+08:00",
        "tasks": len(tasks),
        "packs": len(files),
        "levels": dict(Counter(t["level"] for t in tasks)),
        "baseline_status": dict(Counter(b["status"] for b in baseline)),
        "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
        "inputs": ["results/p31_five_city_96/tasks/all_96.json",
                   "results/p31_five_city_96/static/plans_all_96.json",
                   "results/p31_five_city_96/retrieval/responses/",
                   "results/p31_five_city_96/retrieval/details/"],
        "note": "source_url 已从 pack 中省略；字段、标签、缺口提示与 static_estimate 原样保留。",
    }
    write_json(P32 / "manifest_inputs.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("tasks", "packs", "levels", "baseline_status")},
                     ensure_ascii=False, indent=1))
    print("pack bytes total:", sum(f.stat().st_size for f in files))


if __name__ == "__main__":
    main()
