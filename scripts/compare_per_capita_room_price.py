"""Compare hotel room price with Amap/Baidu per-capita where both exist.

Samples 30 Xi'an hotels with an observed room price (stratified by class and
bed count), queries Amap v5 `business.cost` and Baidu `detail_info.price`,
keeps only exact-name hotel POIs, and reports the ratio room_price / per_capita.

Writes results/per_capita_vs_room_price_20261111.json
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BAIDU_REQUEST_BUDGET", "40")
os.environ.setdefault("BAIDU_OFFLINE", "0")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials  # noqa: E402
from hotel_price_candidates import hotel_class  # noqa: E402

HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT = ROOT / "results/per_capita_vs_room_price_20261111.json"
UA = "ShortTripAssistant/1.0 (per-capita comparison)"
HOTEL_TYPE = re.compile(r"酒店|宾馆|住宿|旅馆|民宿|公寓|客栈|青旅|旅舍")


def amap_key():
    return (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def amap_cost(name):
    params = {"key": amap_key(), "keywords": name, "region": "西安",
              "city_limit": "true", "show_fields": "business",
              "page_size": "3", "page": "1"}
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), None)
    if not best:
        return None
    business = best.get("business") or {}
    try:
        cost = float(business.get("cost") or "")
    except ValueError:
        cost = None
    return {"cost": cost, "type": best.get("type"), "rating": business.get("rating")}


def main():
    rows = [r for r in csv.DictReader(open(HOTELS, encoding="utf-8-sig"))
            if r["price_status"] == "source_value"]
    for r in rows:
        r["price_f"] = float(r["price"])
        r["class"] = hotel_class(r["name"], r.get("featurehoteltype"))
        r["beds"] = int(float(r["numbed"])) if str(r.get("numbed") or "").strip() else None

    # stratify by class x bed count (1 vs 2+)
    groups = {}
    for r in rows:
        key = (r["class"], "1" if r["beds"] == 1 else "2+")
        groups.setdefault(key, []).append(r)
    sample = []
    for key, items in sorted(groups.items()):
        step = max(1, len(items) // 5)
        sample += items[::step][:5]
    sample = sample[:30]

    client = BaiduPlaceClient(credentials=load_credentials(), cache=False, max_calls=40)
    out = []
    for r in sample:
        rec = {"name": r["name"], "class": r["class"], "beds": r["beds"],
               "room_price": r["price_f"], "star": r.get("hotelstar") or ""}
        try:
            a = amap_cost(r["name"])
        except Exception as exc:  # noqa: BLE001
            a = {"error": f"{type(exc).__name__}: {exc}"}
        rec["amap"] = a
        try:
            found = client.search(r["name"], "西安", page_size=3)
            results = found.get("results") or []
            best = next((x for x in results if x.get("name") == r["name"]), None)
            info = (best or {}).get("detail_info") or {}
            try:
                price = float(info.get("price") or "")
            except ValueError:
                price = None
            rec["baidu"] = {"status": found.get("status"), "matched": (best or {}).get("name"),
                            "price": price, "type": (best or {}).get("type"),
                            "tag": info.get("tag")}
        except Exception as exc:  # noqa: BLE001
            rec["baidu"] = {"error": f"{type(exc).__name__}: {exc}"}
        out.append(rec)
        time.sleep(0.8)

    pairs = []
    for rec in out:
        pc = None
        source = None
        a = rec.get("amap") or {}
        b = rec.get("baidu") or {}
        if a.get("cost") and HOTEL_TYPE.search(str(a.get("type") or "")):
            pc, source = a["cost"], "amap"
        elif b.get("price") and b.get("matched") == rec["name"] and HOTEL_TYPE.search(str(b.get("type") or "")):
            pc, source = b["price"], "baidu"
        if pc and pc > 0:
            pairs.append({**rec, "per_capita": pc, "source": source,
                          "ratio": round(rec["room_price"] / pc, 2)})

    summary = {"sample": len(sample), "amap_cost": sum(1 for r in out if (r.get("amap") or {}).get("cost")),
               "baidu_price": sum(1 for r in out if (r.get("baidu") or {}).get("price")),
               "pairs": len(pairs)}
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "summary": summary, "pairs": pairs, "all": out,
              "baidu_calls": client.spent}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for p in pairs:
        print(f"  {p['name'][:30]:<32} room={p['room_price']:>7.0f} percap={p['per_capita']:>7.1f} "
              f"ratio={p['ratio']:>5} beds={p['beds']} {p['class']} {p['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
