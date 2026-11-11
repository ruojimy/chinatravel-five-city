"""Scan all 240 observed-price Xi'an hotels for an Amap per-capita cost.

If a hotel POI itself returns `business.cost`, pair it with the room price and
report the ratio. This is the only way to fit a per-capita -> room-price rule
from our own data.
"""
import csv, json, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT = ROOT / "results/amap_hotel_cost_scan_20261111.json"
UA = "ShortTripAssistant/1.0 (hotel cost scan)"


def key():
    return (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def query(name):
    params = {"key": key(), "keywords": name, "region": "西安", "city_limit": "true",
              "show_fields": "business", "page_size": "3", "page": "1"}
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8"))
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), None)
    if not best:
        return {"matched": None, "cost": None, "type": None}
    try:
        cost = float(((best.get("business") or {}).get("cost") or "").strip())
    except ValueError:
        cost = None
    return {"matched": best.get("name"), "cost": cost,
            "type": best.get("type"), "rating": (best.get("business") or {}).get("rating")}


def main():
    rows = [r for r in csv.DictReader(open(HOTELS, encoding="utf-8-sig"))
            if r["price_status"] == "source_value"]
    out, with_cost = [], []
    for i, r in enumerate(rows, 1):
        try:
            got = query(r["name"])
        except Exception as exc:  # noqa: BLE001
            got = {"error": f"{type(exc).__name__}: {exc}"}
        rec = {"name": r["name"], "room_price": float(r["price"]),
               "numbed": r.get("numbed"), "class": r.get("featurehoteltype") or "", **got}
        out.append(rec)
        if got.get("cost"):
            rec["ratio"] = round(float(r["price"]) / got["cost"], 2)
            with_cost.append(rec)
        if i % 40 == 0:
            print(f"{i}/{len(rows)} done, with_cost={len(with_cost)}", flush=True)
        time.sleep(0.2)

    report = {"scanned": len(rows), "with_cost": len(with_cost), "pairs": with_cost}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"scanned": len(rows), "with_cost": len(with_cost)}, ensure_ascii=False))
    for p in with_cost:
        print(f"  {p['name'][:32]:<34} room={p['room_price']:>7.0f} cost={p['cost']:>6.1f} "
              f"ratio={p['ratio']:>5} type={p['type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
