"""Fill the priority gap: hostels/beds/capsules and numbed=2 hotels from per-capita.

Targets = hotels whose price_status is unknown AND (name contains 青旅/旅舍/
床位/太空舱/胶囊 OR numbed == 2).

For each target, try Amap v5 cost -> Amap v3 biz_ext.cost -> Baidu search price
-> Baidu detail price, keeping only exact-name hotel POIs with a positive value.
Conversion: hostel/bed -> x1, numbed==2 -> x2; output is
`price_status=reference_per_capita` (never source_value) with a +/-25% range.

Usage:
  python scripts/fill_target_hotels_from_per_capita.py          # dry run
  python scripts/fill_target_hotels_from_per_capita.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BAIDU_REQUEST_BUDGET", "20")
os.environ.setdefault("BAIDU_OFFLINE", "0")
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials  # noqa: E402

CSV_PATH = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
PROV = CSV_PATH.parent / "price_reference_per_capita.csv"
REPORT = ROOT / "results/per_capita_target_fill_20261111.json"
UA = "ShortTripAssistant/1.0 (per-capita fill)"
HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")
HOTEL_TYPE = re.compile(r"住宿|酒店|宾馆|旅馆|民宿|公寓|客栈|青旅|旅舍")


def amap_key():
    return (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def amap(name, version="v5"):
    if version == "v5":
        url = "https://restapi.amap.com/v5/place/text"
        params = {"key": amap_key(), "keywords": name, "region": "西安",
                  "city_limit": "true", "show_fields": "business",
                  "page_size": "3", "page": "1"}
    else:
        url = "https://restapi.amap.com/v3/place/text"
        params = {"key": amap_key(), "keywords": name, "city": "西安",
                  "citylimit": "true", "extensions": "all", "offset": "3", "page": "1"}
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), None)
    if not best:
        return {"matched": None, "cost": None, "type": None}
    if version == "v5":
        raw = ((best.get("business") or {}).get("cost") or "").strip()
    else:
        raw = ((best.get("biz_ext") or {}).get("cost") or "").strip()
    try:
        cost = float(raw)
    except ValueError:
        cost = None
    return {"matched": best.get("name"), "cost": cost,
            "type": best.get("type"), "rating": ((best.get("business") or {}).get("rating"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    targets = [r for r in rows if r["price_status"] == "unknown"
               and (any(k in r["name"] for k in HOSTEL) or str(r["numbed"]).strip() == "2")]
    print(f"targets={len(targets)}")
    client = BaiduPlaceClient(credentials=load_credentials(), cache=False, max_calls=20)
    findings, filled = [], 0
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    for r in targets:
        name = r["name"]
        is_hostel = any(k in name for k in HOSTEL)
        factor = 1.0 if is_hostel else 2.0
        rec = {"name": name, "numbed": r.get("numbed"), "hostel": is_hostel,
               "factor": factor, "amap_v5": None, "amap_v3": None, "baidu": None}
        try:
            rec["amap_v5"] = amap(name, "v5")
        except Exception as exc:  # noqa: BLE001
            rec["amap_v5"] = {"error": f"{type(exc).__name__}: {exc}"}
        time.sleep(0.3)
        try:
            rec["amap_v3"] = amap(name, "v3")
        except Exception as exc:  # noqa: BLE001
            rec["amap_v3"] = {"error": f"{type(exc).__name__}: {exc}"}
        time.sleep(0.3)
        try:
            found = client.search(name, "西安", page_size=3)
            results = found.get("results") or []
            best = next((x for x in results if x.get("name") == name), None)
            info = (best or {}).get("detail_info") or {}
            try:
                bprice = float(info.get("price") or "")
            except ValueError:
                bprice = None
            rec["baidu"] = {"status": found.get("status"), "matched": (best or {}).get("name"),
                            "price": bprice, "type": (best or {}).get("type")}
        except Exception as exc:  # noqa: BLE001
            rec["baidu"] = {"error": f"{type(exc).__name__}: {exc}"}

        per_capita = None
        if (rec["amap_v5"] or {}).get("cost") and (rec["amap_v5"] or {}).get("matched") == name:
            per_capita = rec["amap_v5"]["cost"]
        elif (rec["amap_v3"] or {}).get("cost") and (rec["amap_v3"] or {}).get("matched") == name:
            per_capita = rec["amap_v3"]["cost"]
        elif ((rec["baidu"] or {}).get("price") and (rec["baidu"] or {}).get("matched") == name
              and HOTEL_TYPE.search(str((rec["baidu"] or {}).get("type") or ""))):
            per_capita = rec["baidu"]["price"]

        rec["per_capita"] = per_capita
        if per_capita:
            price = round(per_capita * factor)
            rec.update(room_price_reference=price,
                       range=[round(price * 0.75), round(price * 1.25)],
                       price_status="reference_per_capita")
            if args.apply:
                r["price"] = f"{price}"
                r["price_status"] = "reference_per_capita"
                filled += 1
        findings.append(rec)
        time.sleep(0.4)

    if args.apply and filled:
        with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        prov_rows = []
        for rec in findings:
            if rec.get("per_capita"):
                prov_rows.append({"name": rec["name"], "price": rec["room_price_reference"],
                                  "price_status": "reference_per_capita",
                                  "per_capita": rec["per_capita"], "factor": rec["factor"],
                                  "range_low": rec["range"][0], "range_high": rec["range"][1],
                                  "source": "amap" if rec["amap_v5"] and rec["amap_v5"].get("cost") else
                                            "amap_v3" if rec["amap_v3"] and rec["amap_v3"].get("cost") else "baidu",
                                  "observed_at": stamp})
        with PROV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(prov_rows[0].keys()))
            writer.writeheader()
            writer.writerows(prov_rows)

    report = {"targets": len(targets), "filled": filled,
              "with_per_capita": sum(1 for r in findings if r.get("per_capita")),
              "details": findings}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"targets": len(targets), "with_per_capita": report["with_per_capita"],
                      "filled": filled}, ensure_ascii=False))
    for r in findings:
        print(f"  {r['name'][:34]:<36} hostel={r['hostel']} numbed={r['numbed']} "
              f"percap={r['per_capita']} ref={r.get('room_price_reference')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
