"""P32: build per-task final packs using the evidence that matches the LLM's own order.

Routes come from the P31 cache when the LLM kept the rule planner's order, otherwise from
the 90 calls fetched by p32_retrieve.py. Weather / place / detail evidence is shared.
"""
from __future__ import annotations

import json
from pathlib import Path

from p31_common import haversine_km, read_json, write_json
from p31_static import coord_of_cand, hhmm_to_min

from p32_build_packs import P31, P32, hhmm_windows, slim_task
from p32_retrieve import day1_legs, normalized_order

P32_FINAL = P32 / "packs"


def all_responses():
    by_uid = {}
    for base in (P31 / "retrieval/responses", P32 / "retrieval/responses"):
        if not base.exists():
            continue
        for f in base.rglob("*.json"):
            d = read_json(f)
            by_uid.setdefault(d["uid"], []).append(d)
    return by_uid


def details_by_uid():
    out = {}
    for f in (P31 / "retrieval/details").rglob("*.json"):
        d = read_json(f)
        out.setdefault(d["uid"], []).append(d)
    return out


def route_view(d, name_by_eid, coord_by_name):
    p = d.get("parsed") or {}
    r = d["request"]
    lines = [] if not p.get("ok") else [x.get("name") for x in (p.get("lines") or [])]
    dist = None
    a, b = r.get("from_coord"), r.get("to_coord")
    a = a or coord_by_name.get(r["from"])
    b = b or coord_by_name.get(r["to"])
    try:
        dist = round(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), 2)
    except Exception:
        pass
    return {
        "from": r["from"], "to": r["to"],
        "status": "ok" if p.get("ok") else "no_transit_route",
        "duration_min": p.get("duration_min"), "fare_cny": p.get("fare"),
        "modes": p.get("modes"), "lines": lines, "straight_line_km": dist,
        "departure": r.get("departure"), "req_id": d["req_id"],
    }


def main():
    tasks = {t["uid"]: t for t in read_json(P31 / "tasks/all_96.json")}
    responses = all_responses()
    details = details_by_uid()
    built, missing = 0, []
    for uid, t in tasks.items():
        sp = P32 / "out" / f"{uid}_static.json"
        if not sp.exists():
            missing.append(uid)
            continue
        s = read_json(sp)
        order = normalized_order(t, s.get("order"))
        legs = day1_legs(t, order, s.get("lunch_after"))
        name_by_eid = {c["entity_id"]: c["name"] for c in t["candidates"]}
        coord_by_name = {t["start"]["name"]: {"lat": t["start"]["position_wgs84"][0],
                                              "lon": t["start"]["position_wgs84"][1]}}
        for c in t["candidates"]:
            co = coord_of_cand(c)
            if co:
                coord_by_name[c["name"]] = co
        by_pair = {}
        for d in responses.get(uid, []):
            if d["type"] == "route":
                by_pair[(d["request"]["from"], d["request"]["to"])] = d
        route_views = []
        for lg in legs:
            d = by_pair.get((lg["from"], lg["to"]))
            if d:
                route_views.append(route_view(d, name_by_eid, coord_by_name))
        weather, places = [], []
        for d in responses.get(uid, []):
            p = d.get("parsed") or {}
            if d["type"] == "weather":
                v = p.get("value") or {}
                weather.append({"city": d["request"]["city"], "date": d["request"]["date"],
                                "ok": bool(v), "dayweather": v.get("dayweather"),
                                "nightweather": v.get("nightweather"),
                                "daytemp": v.get("daytemp"), "nighttemp": v.get("nighttemp"),
                                "daywind": v.get("daywind"), "daypower": v.get("daypower"),
                                "reporttime": p.get("reporttime"), "req_id": d["req_id"]})
            elif d["type"] == "place":
                eid = d["request"]["entity_id"]
                places.append({"entity": name_by_eid.get(eid, d["request"]["name"]),
                               "matched": p.get("ok"), "matched_name": p.get("name"),
                               "match_score": p.get("match_score"),
                               "location_gcj02": p.get("location_gcj02"),
                               "opentime_text": p.get("opentime_text"),
                               "opentime_windows": hhmm_windows(p.get("opentime_windows")),
                               "address": p.get("address"), "type": p.get("type"),
                               "req_id": d["req_id"]})
        dets = [{"entity": name_by_eid.get(d["entity_id"], d.get("name")),
                 "hours_text": d.get("hours_text"),
                 "hours_window": hhmm_windows([d["hours_window"]] if d.get("hours_window") else None),
                 "cost_text": d.get("cost_text"), "rating": d.get("rating"),
                 "poi_id": d.get("poi_id"), "retrieved_at": d.get("retrieved_at")}
                for d in details.get(uid, [])]
        weather.sort(key=lambda x: (x["date"], x["city"]))
        route_views.sort(key=lambda x: (x["from"], x["to"]))
        pack = {
            "schema": "p32-llm-pack-v1", "uid": uid, "stage": "final",
            "note": "静态候选 + 冻结高德证据；路线证据按你第一阶段方案的顺序抓取。",
            "task": slim_task(t),
            "evidence": {
                "source": "高德 Web 服务（weatherInfo / direction/transit/integrated / place/text / place/detail）",
                "retrieved_at_range": sorted({d.get("retrieved_at") for d in responses.get(uid, []) if d.get("retrieved_at")})[:1]
                + sorted({d.get("retrieved_at") for d in responses.get(uid, []) if d.get("retrieved_at")})[-1:],
                "coverage_note": "路线只覆盖你静态方案的 day-1 段；若改顺序，没有列出的段没有实测。",
                "legs_requested": legs,
                "weather": weather, "routes": route_views, "places": places, "details": dets,
            },
        }
        write_json(P32_FINAL / f"{uid}_final.json", pack)
        built += 1
    print(json.dumps({"final_packs": built, "missing_static": missing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
