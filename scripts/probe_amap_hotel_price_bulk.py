"""Broader test: do Amap/Baidu fill any hotel price at all?

Amap v5 `business.cost` and Baidu `detail_info.price` are generic per-capita
spend fields. This samples 30 Xi'an hotels (stratified by class) plus 10
restaurants as a positive control, and 6 hotels through Baidu.

Writes results/api_hotel_price_bulk_20261111.json.
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
os.environ.setdefault("BAIDU_REQUEST_BUDGET", "12")
os.environ.setdefault("BAIDU_OFFLINE", "0")
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials  # noqa: E402

HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
RESTAURANTS = ROOT / "data/xian11_merged_sandbox/restaurants/xian/restaurants_xian.csv"
OUT = ROOT / "results/api_hotel_price_bulk_20261111.json"
UA = "ShortTripAssistant/1.0 (price probe)"


def amap_key():
    return (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def call(url, params, timeout=20):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def amap_cost(name):
    body = call("https://restapi.amap.com/v5/place/text",
                {"key": amap_key(), "keywords": name, "region": "西安",
                 "city_limit": "true", "show_fields": "business",
                 "page_size": "3", "page": "1"})
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), pois[0] if pois else None)
    cost = ((best or {}).get("business") or {}).get("cost")
    return {"status": body.get("status"), "matched": (best or {}).get("name"),
            "cost": cost, "rating": ((best or {}).get("business") or {}).get("rating")}


def pick(rows, n):
    step = max(1, len(rows) // n)
    return rows[::step][:n]


def main() -> int:
    hotels = list(csv.DictReader(open(HOTELS, encoding="utf-8-sig")))
    hotels = [h for h in hotels if h["price_status"] == "source_value"]
    # stratify by the estimator's class rule
    sys.path.insert(0, str(ROOT / "scripts"))
    from hotel_price_candidates import hotel_class  # noqa: E402
    buckets = {"luxury": [], "mid": [], "budget": []}
    for h in hotels:
        buckets[hotel_class(h["name"], h.get("featurehoteltype"))].append(h)
    sample = []
    for cls, rows in buckets.items():
        sample += pick(rows, 10)
    restaurants = pick(list(csv.DictReader(open(RESTAURANTS, encoding="utf-8-sig"))), 10)

    report = {"hotels": [], "restaurants": [], "baidu_hotels": []}
    hotel_stats = Counter()
    for h in sample:
        try:
            got = amap_cost(h["name"])
        except Exception as exc:  # noqa: BLE001
            got = {"error": f"{type(exc).__name__}: {exc}"}
        got.update(name=h["name"], observed=float(h["price"]),
                   cls=hotel_class(h["name"], h.get("featurehoteltype")))
        report["hotels"].append(got)
        cost = str(got.get("cost") or "").strip()
        hotel_stats["total"] += 1
        hotel_stats["nonempty"] += bool(cost)
        hotel_stats["range"] += bool(re.search(r"\d+\s*[-~—至]\s*\d+", cost))
        time.sleep(0.25)

    rest_stats = Counter()
    for r in restaurants:
        try:
            got = amap_cost(r["name"])
        except Exception as exc:  # noqa: BLE001
            got = {"error": f"{type(exc).__name__}: {exc}"}
        got.update(name=r["name"], observed=r.get("price"))
        report["restaurants"].append(got)
        cost = str(got.get("cost") or "").strip()
        rest_stats["total"] += 1
        rest_stats["nonempty"] += bool(cost)
        rest_stats["range"] += bool(re.search(r"\d+\s*[-~—至]\s*\d+", cost))
        time.sleep(0.25)

    client = BaiduPlaceClient(credentials=load_credentials(), cache=False, max_calls=12)
    baidu_stats = Counter()
    for h in sample[:6]:
        try:
            found = client.search(h["name"], "西安", page_size=3)
            results = found.get("results") or []
            best = next((r for r in results if r.get("name") == h["name"]), results[0] if results else None)
            info = (best or {}).get("detail_info") or {}
            price = str(info.get("price") or "").strip()
            report["baidu_hotels"].append({"name": h["name"], "status": found.get("status"),
                                           "matched": (best or {}).get("name"),
                                           "price": price,
                                           "rating": info.get("overall_rating")})
            baidu_stats["total"] += 1
            baidu_stats["nonempty"] += bool(price)
            baidu_stats["range"] += bool(re.search(r"\d+\s*[-~—至]\s*\d+", price))
        except Exception as exc:  # noqa: BLE001
            report["baidu_hotels"].append({"name": h["name"], "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.6)

    summary = {"amap_hotels": dict(hotel_stats), "amap_restaurants": dict(rest_stats),
               "baidu_hotels": dict(baidu_stats), "baidu_calls": client.spent}
    report["summary"] = summary
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for row in report["hotels"][:8]:
        print(" hotel", row.get("name"), "->", repr(row.get("cost")))
    for row in report["restaurants"][:6]:
        print(" restaurant", row.get("name"), "->", repr(row.get("cost")))
    for row in report["baidu_hotels"][:6]:
        print(" baidu", row.get("name"), "->", repr(row.get("price")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
