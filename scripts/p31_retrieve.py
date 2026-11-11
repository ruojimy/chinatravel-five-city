"""P31 dynamic retrieval: execute the explicit Amap requests within a budget.

Design:
  * one persisted ledger, one call per request, no retries, no key rotation;
  * weather / transit / place-text only; intercity schedules stay frozen;
  * every raw response is saved with request params, retrieved_at and sha256.

Usage:
  python p31_retrieve.py --level easy --max-calls 200
  python p31_retrieve.py --tasks E01,D31,N01 --max-calls 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from p31_common import CST, OUT, ROOT, min_to_hhmm, parse_amap_hours, read_json, wgs84_to_gcj02, write_json

sys.path.insert(0, str(ROOT / "src"))
from shorttrip.live_amap import LiveAmapClient, LiveAmapError  # noqa: E402

ADCODE = {"西安": "610100", "厦门": "350200", "宁波": "330200", "长沙": "430100", "青岛": "370200",
          "北京": "110000", "上海": "310000", "杭州": "330100", "广州": "440100"}
MAX_CALLS_DEFAULT = 500


def gcj(coord):
    if coord is None:
        return None
    lat, lon = float(coord["lat"]), float(coord["lon"])
    if coord.get("system") == "GCJ02":
        return lon, lat
    g = wgs84_to_gcj02(lat, lon)
    return g[1], g[0]


def safe(name):
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:70]
    return base + "-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def parse_weather(data, date):
    rows = (data.get("forecasts") or [{}])[0].get("casts") or []
    hit = next((c for c in rows if c.get("date") == date), None)
    return {"coverage": [c.get("date") for c in rows], "value": hit,
            "miss": hit is None, "reporttime": (data.get("forecasts") or [{}])[0].get("reporttime")}


def parse_route(data):
    route = data.get("route") or {}
    transits = route.get("transits") or []
    if not transits:
        return {"ok": False, "reason": "no_transit_route"}
    t = transits[0]
    cost = t.get("cost") or {}
    try:
        dur = float(cost.get("duration") or t.get("duration") or 0) / 60.0
    except (TypeError, ValueError):
        dur = None
    try:
        fare = float(cost.get("transit_fee")) if cost.get("transit_fee") not in (None, "", []) else None
    except (TypeError, ValueError):
        fare = None
    lines = []
    for seg in t.get("segments") or []:
        for bl in ((seg.get("bus") or {}).get("buslines") or []):
            lines.append({"name": bl.get("name"), "type": bl.get("type")})
    modes = sorted({("metro" if ("地铁" in str(x["type"]) or "subway" in str(x["type"]).lower()) else "bus")
                    for x in lines}) if lines else ["walk"]
    return {"ok": True, "duration_min": round(dur, 1) if dur else None, "fare": fare,
            "distance_m": route.get("distance"), "lines": lines[:6], "modes": modes,
            "walk_distance_m": (t.get("walking_distance") or None)}


def _norm(s):
    return re.sub(r"[\s（）()·\-—]", "", str(s or "")).lower()


def parse_place(data, name, city):
    pois = data.get("pois") or []
    best, score = None, 0.0
    for p in pois:
        n = _norm(p.get("name"))
        target = _norm(name)
        s = 0.0
        if n == target:
            s = 1.0
        elif target and (target in n or n in target):
            s = 0.8
        if s > score:
            best, score = p, s
    if not best:
        return {"ok": False, "reason": "no_name_match", "count": len(pois)}
    loc = best.get("location") or ""
    lat = lon = None
    if "," in loc:
        lon, lat = [float(x) for x in loc.split(",")[:2]]
    biz = best.get("business") or {}
    return {"ok": True, "match_score": score, "name": best.get("name"),
            "location_gcj02": [lat, lon] if lat is not None else None,
            "address": best.get("address"), "type": best.get("type"),
            "opentime_text": biz.get("opentime"), "opentime_windows": parse_amap_hours(biz.get("opentime")),
            "cost_text": biz.get("cost"), "tel": biz.get("tel"), "poi_id": best.get("id")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["easy", "hard", "human"])
    ap.add_argument("--tasks", default="")
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS_DEFAULT)
    ap.add_argument("--task-budget", type=int, default=8)
    ap.add_argument("--resume", action="store_true", default=True)
    a = ap.parse_args()

    plans = read_json(OUT / "static" / (f"plans_{a.level}.json" if a.level else "plans_all_96.json"))
    if a.tasks:
        wanted = set(x.strip() for x in a.tasks.split(",") if x.strip())
        plans = [p for p in plans if p["uid"] in wanted]

    rdir = OUT / "retrieval"
    resp_dir = rdir / "responses"
    resp_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = rdir / "ledger.json"
    ledger = read_json(ledger_path) if ledger_path.exists() else {
        "max_calls": a.max_calls, "spent": 0, "stopped": False, "per_task": {}, "calls": []}
    if ledger.get("stopped"):
        print("ledger already stopped:", ledger.get("stop_reason"))
        return

    remaining = a.max_calls - ledger["spent"]
    client = LiveAmapClient(ROOT, budget=max(0, remaining))
    log_path = rdir / "requests.jsonl"
    new_calls = 0

    for plan in plans:
        uid = plan["uid"]
        task_spent = ledger["per_task"].get(uid, {}).get("spent", 0)
        for req in plan["requests"]:
            if task_spent >= a.task_budget:
                break
            if ledger["spent"] >= a.max_calls or client.stopped:
                break
            fname = resp_dir / uid / f"{safe(req['req_id'])}.json"
            if fname.exists():
                continue
            rtype = req["type"]
            if rtype == "weather":
                params = {"city": req["adcode"], "extensions": "all", "output": "JSON"}
                endpoint_path = "/v3/weather/weatherInfo"
            elif rtype == "route":
                o, d = gcj(req["from_coord"]), gcj(req["to_coord"])
                if not o or not d:
                    continue
                dep = req.get("departure") or "09:00"
                params = {"origin": f"{o[0]:.6f},{o[1]:.6f}", "destination": f"{d[0]:.6f},{d[1]:.6f}",
                          "city1": req["adcode"] if "adcode" in req else ADCODE[req["city"]],
                          "city2": req["adcode"] if "adcode" in req else ADCODE[req["city"]],
                          "strategy": "0", "date": req["date"], "time": dep.replace(":", "-"),
                          "show_fields": "cost", "AlternativeRoute": "1", "output": "JSON"}
                endpoint_path = "/v5/direction/transit/integrated"
            elif rtype == "place":
                params = {"keywords": req["name"], "region": req["adcode"], "city_limit": "true",
                          "page_size": "5", "show_fields": "business,children", "output": "JSON"}
                endpoint_path = "/v5/place/text"
            else:
                continue
            started = datetime.now(CST).isoformat(timespec="seconds")
            try:
                data, meta = client._call(endpoint_path, params)
                raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
                parsed = (parse_weather(data, req["date"]) if rtype == "weather"
                          else parse_route(data) if rtype == "route"
                          else parse_place(data, req["name"], req["city"]))
                rec = {"req_id": req["req_id"], "uid": uid, "type": rtype, "request": req,
                       "endpoint": meta["endpoint"], "params": meta["params"], "retrieved_at": meta["retrieved_at"],
                       "infocode": meta["infocode"], "ok": meta["ok"], "started_at": started,
                       "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "parsed": parsed}
                write_json(fname, rec)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({k: rec[k] for k in ("req_id", "uid", "type", "retrieved_at", "infocode", "ok")},
                                        ensure_ascii=False) + "\n")
                new_calls += 1
                task_spent += 1
                ledger["spent"] += 1
                ledger["calls"].append({"req_id": req["req_id"], "uid": uid, "type": rtype,
                                        "at": meta["retrieved_at"], "ok": True})
            except LiveAmapError as exc:
                ledger["calls"].append({"req_id": req["req_id"], "uid": uid, "type": rtype,
                                        "at": datetime.now(CST).isoformat(timespec="seconds"),
                                        "ok": False, "error": str(exc)})
                if client.stopped:
                    ledger["stopped"] = True
                    ledger["stop_reason"] = str(exc)
                break
            finally:
                ledger["per_task"].setdefault(uid, {"spent": 0})["spent"] = task_spent
                write_json(ledger_path, ledger)
        if client.stopped or ledger["spent"] >= a.max_calls:
            break

    write_json(ledger_path, ledger)
    print(json.dumps({"tasks": len(plans), "new_calls": new_calls, "spent_total": ledger["spent"],
                      "stopped": ledger["stopped"], "stop_reason": ledger.get("stop_reason")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
