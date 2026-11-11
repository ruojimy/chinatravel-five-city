"""P31 supplementary detail stage: resolve opening hours for matched POIs.

The v5 place-text response returns coordinates but no opening hours. A v3 place
detail call returns biz_ext.opentime2 for many POIs. This stage performs that
second call for POIs already matched by name, and records it separately.

Usage: python p31_detail.py --max-calls 40
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from p31_common import OUT, ROOT, read_json, write_json

sys.path.insert(0, str(ROOT / "src"))
from shorttrip.live_amap import LiveAmapClient, LiveAmapError  # noqa: E402


def parse_hours(text):
    if not text:
        return None
    t = str(text)
    if "全天" in t or "24小时" in t:
        return [0, 24 * 60]
    pairs = re.findall(r"(\d{1,2}):(\d{2})", t)
    if not pairs:
        return None
    mins = [int(h) * 60 + int(m) for h, m in pairs]
    return [min(mins), max(mins)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=40)
    a = ap.parse_args()
    rdir = OUT / "retrieval"
    ledger_path = rdir / "detail_ledger.json"
    ledger = read_json(ledger_path) if ledger_path.exists() else {"spent": 0, "stopped": False, "calls": []}
    if ledger.get("stopped"):
        print("detail ledger stopped"); return
    client = LiveAmapClient(ROOT, budget=max(0, a.max_calls - ledger["spent"]))
    out_dir = rdir / "details"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {}
    for f in (rdir / "responses").rglob("*.json"):
        d = read_json(f)
        if d["type"] != "place" or not d["parsed"].get("ok"):
            continue
        poi = d["parsed"].get("poi_id")
        if poi:
            targets[(d["uid"], d["request"]["entity_id"])] = {"poi_id": poi, "name": d["request"]["name"],
                                                              "city": d["request"]["city"], "place_req": d["req_id"]}
    new = 0
    for (uid, eid), t in sorted(targets.items()):
        if ledger["spent"] >= a.max_calls or client.stopped:
            break
        fname = out_dir / uid / f"{t['poi_id']}.json"
        if fname.exists():
            continue
        try:
            data, meta = client._call("/v3/place/detail", {"id": t["poi_id"], "extensions": "all", "output": "JSON"})
            pois = data.get("pois") or []
            p = pois[0] if pois else {}
            biz = p.get("biz_ext") or {}
            hours_text = biz.get("opentime2") or biz.get("opentime") or p.get("opentime")
            rec = {"uid": uid, "entity_id": eid, "name": t["name"], "city": t["city"], "poi_id": t["poi_id"],
                   "place_req": t["place_req"], "retrieved_at": meta["retrieved_at"], "infocode": meta["infocode"],
                   "hours_text": hours_text, "hours_window": parse_hours(hours_text),
                   "cost_text": biz.get("cost"), "rating": biz.get("rating"),
                   "raw_sha256": hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
            write_json(fname, rec)
            ledger["spent"] += 1; new += 1
            ledger["calls"].append({"uid": uid, "poi_id": t["poi_id"], "ok": True, "hours": rec["hours_window"]})
        except LiveAmapError as exc:
            ledger["calls"].append({"uid": uid, "poi_id": t["poi_id"], "ok": False, "error": str(exc)})
            if client.stopped:
                ledger["stopped"] = True
            break
        finally:
            write_json(ledger_path, ledger)
    write_json(ledger_path, ledger)
    print(json.dumps({"targets": len(targets), "new": new, "spent": ledger["spent"], "stopped": ledger["stopped"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
