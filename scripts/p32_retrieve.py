"""P32 retrieval: fetch the route evidence each LLM plan actually needs.

The rule planner requested one route per leg of its own order.  The LLM may pick a
different order, so this script derives the LLM's day-1 legs from its static output,
reuses any cached P31 response for the same (from,to), and calls Amap only for the rest.

Usage:
  python p32_retrieve.py --plan-only
  python p32_retrieve.py --max-calls 300 --task-budget 8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from p31_common import CST, hhmm_to_min, known, read_json, write_json, wgs84_to_gcj02
from p31_static import _run_sequence, coord_of_cand, travel_estimate
from p31_retrieve import ADCODE, parse_route, safe

ROOT = Path(__file__).resolve().parents[1]
P31 = ROOT / "results/p31_five_city_96"
P32 = ROOT / "results/p32_llm_96"
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.live_amap import LiveAmapClient, LiveAmapError  # noqa: E402


def normalized_order(task, order):
    pool = {c["name"] for c in task["candidates"] if c["kind"] == "attraction"}
    return [n for n in (order or []) if n in pool]


def day1_legs(task, order, lunch_after):
    """Return [{from,to,departure}] for the LLM's day-1 sequence, using estimates only."""
    cons = task["constraints"]
    start_min = hhmm_to_min(cons.get("start_time") or "09:00")
    deadline = hhmm_to_min(cons["window"][1])
    start = task["start"]
    start_coord = {"lat": start["position_wgs84"][0], "lon": start["position_wgs84"][1],
                   "system": "WGS84"}
    by_name = {c["name"]: c for c in task["candidates"]}
    rest = next((c for c in task["candidates"] if c["kind"] == "restaurant"), None)
    lunch = lunch_after if rest and isinstance(lunch_after, int) else None
    before = [by_name[n] for n in order[:lunch]] if lunch is not None else [by_name[n] for n in order]
    after = [by_name[n] for n in order[lunch:]] if lunch is not None else []
    r = _run_sequence(before, rest if lunch is not None else None, after,
                      start_coord, start_min, deadline)
    legs = []
    for x in r["timeline"]:
        if x["type"] != "travel":
            continue
        legs.append({
            "from": start["name"] if x["from"] == "start" else x["from"],
            "to": start["name"] if x["to"] == "start" else x["to"],
            "departure": x["start"],
        })
    return legs


def cached_routes(uid):
    out = {}
    for f in (P31 / "retrieval/responses" / uid).glob("*.json") if (P31 / "retrieval/responses" / uid).exists() else []:
        d = read_json(f)
        if d["type"] == "route":
            out[(d["request"]["from"], d["request"]["to"])] = d
    for f in (P32 / "retrieval/responses" / uid).glob("*.json") if (P32 / "retrieval/responses" / uid).exists() else []:
        d = read_json(f)
        if d["type"] == "route":
            out[(d["request"]["from"], d["request"]["to"])] = d
    return out


def place_by_entity(uid):
    out = {}
    for base in (P31 / "retrieval/responses" / uid, P32 / "retrieval/responses" / uid):
        if not base.exists():
            continue
        for f in base.glob("*.json"):
            d = read_json(f)
            if d["type"] == "place":
                out[d["request"]["entity_id"]] = d
    return out


def build_requests():
    tasks = read_json(P31 / "tasks/all_96.json")
    reqs = []
    for t in tasks:
        uid = t["uid"]
        sp = P32 / "out" / f"{uid}_static.json"
        if not sp.exists():
            continue
        s = read_json(sp)
        order = normalized_order(t, s.get("order"))
        if len(order) != sum(1 for c in t["candidates"] if c["kind"] == "attraction"):
            continue
        legs = day1_legs(t, order, s.get("lunch_after"))
        have = cached_routes(uid)
        for i, lg in enumerate(legs):
            if (lg["from"], lg["to"]) in have:
                continue
            reqs.append({"uid": uid, "req_id": f"{uid}-LR-{i}", "type": "route", **lg,
                         "city": t["city_sequence"][0], "date": t["dates"][0]})
    return reqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--max-calls", type=int, default=300)
    ap.add_argument("--task-budget", type=int, default=8)
    a = ap.parse_args()

    reqs = build_requests()
    by_uid = {}
    for r in reqs:
        by_uid.setdefault(r["uid"], []).append(r)
    print(json.dumps({"new_route_requests": len(reqs), "tasks": len(by_uid),
                      "per_task": {k: len(v) for k, v in sorted(by_uid.items())}},
                     ensure_ascii=False))
    if a.plan_only:
        write_json(P32 / "retrieval/planned_requests.json", reqs)
        return

    rdir = P32 / "retrieval"
    (rdir / "responses").mkdir(parents=True, exist_ok=True)
    ledger_path = rdir / "ledger.json"
    ledger = read_json(ledger_path) if ledger_path.exists() else {
        "max_calls": a.max_calls, "spent": 0, "stopped": False, "per_task": {}, "calls": []}
    if ledger.get("stopped"):
        print("ledger already stopped:", ledger.get("stop_reason"))
        return
    remaining = a.max_calls - ledger["spent"]
    client = LiveAmapClient(ROOT, budget=max(0, remaining), key=None)
    log_path = rdir / "requests.jsonl"
    new_calls = 0
    tasks = {t["uid"]: t for t in read_json(P31 / "tasks/all_96.json")}

    for r in reqs:
        uid = r["uid"]
        if ledger["spent"] >= a.max_calls or client.stopped:
            break
        task_spent = ledger["per_task"].get(uid, {}).get("spent", 0)
        if task_spent >= a.task_budget:
            continue
        fname = rdir / "responses" / uid / f"{safe(r['req_id'])}.json"
        if fname.exists():
            continue
        t = tasks[uid]
        by_name = {c["name"]: c for c in t["candidates"]}
        cfrom = ({"lat": t["start"]["position_wgs84"][0], "lon": t["start"]["position_wgs84"][1],
                  "system": "WGS84"} if r["from"] == t["start"]["name"] else coord_of_cand(by_name[r["from"]]))
        cto = ({"lat": t["start"]["position_wgs84"][0], "lon": t["start"]["position_wgs84"][1],
                "system": "WGS84"} if r["to"] == t["start"]["name"] else coord_of_cand(by_name[r["to"]]))
        if not cfrom or not cto:
            continue
        o = wgs84_to_gcj02(cfrom["lat"], cfrom["lon"])
        d = wgs84_to_gcj02(cto["lat"], cto["lon"])
        ad = ADCODE[r["city"]]
        params = {"origin": f"{o[1]:.6f},{o[0]:.6f}", "destination": f"{d[1]:.6f},{d[0]:.6f}",
                  "city1": ad, "city2": ad, "strategy": "0", "date": r["date"],
                  "time": r["departure"].replace(":", "-"), "show_fields": "cost",
                  "AlternativeRoute": "1", "output": "JSON"}
        started = datetime.now(CST).isoformat(timespec="seconds")
        try:
            data, meta = client._call("/v5/direction/transit/integrated", params)
            raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
            rec = {"req_id": r["req_id"], "uid": uid, "type": "route", "request": r,
                   "endpoint": meta["endpoint"], "params": meta["params"],
                   "retrieved_at": meta["retrieved_at"], "infocode": meta["infocode"],
                   "ok": meta["ok"], "started_at": started,
                   "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                   "parsed": parse_route(data)}
            write_json(fname, rec)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({k: rec[k] for k in ("req_id", "uid", "type", "retrieved_at",
                                                          "infocode", "ok")}, ensure_ascii=False) + "\n")
            new_calls += 1
            task_spent += 1
            ledger["spent"] += 1
            ledger["calls"].append({"req_id": r["req_id"], "uid": uid, "type": "route",
                                    "at": meta["retrieved_at"], "ok": True})
        except LiveAmapError as exc:
            ledger["calls"].append({"req_id": r["req_id"], "uid": uid, "type": "route",
                                    "at": datetime.now(CST).isoformat(timespec="seconds"),
                                    "ok": False, "error": str(exc)})
            if client.stopped:
                ledger["stopped"] = True
                ledger["stop_reason"] = str(exc)
            break
        finally:
            ledger["per_task"].setdefault(uid, {"spent": 0})["spent"] = task_spent
            write_json(ledger_path, ledger)

    write_json(ledger_path, ledger)
    print(json.dumps({"new_calls": new_calls, "spent_total": ledger["spent"],
                      "stopped": ledger["stopped"], "stop_reason": ledger.get("stop_reason")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
