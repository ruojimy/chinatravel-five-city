"""Hotel room-type lookup + live price query.

Usage:
  python scripts/hotel_dynamic_price.py rooms --hotel "西安威斯汀大酒店"
  python scripts/hotel_dynamic_price.py price --hotel "..." --checkin 2026-11-10 --checkout 2026-11-11

`rooms` reads the catalog side table (no network).
`price` queries Trip.com live, appends an observation, and returns a band from recent
observations. It never invents a number: on failure it returns status=unknown with the
last observation and its age.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "results/xian_gapfill_20261109/snapshot_v7/catalog.sqlite3"
CACHE = ROOT / "data" / "hotel_price_cache.jsonl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rooms(snapshot: Path, hotel: str) -> dict:
    con = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    rows = con.execute("""select room_id, room_name, bed_text, bed_count, area, window,
                          is_primary, observed_at from room_types where hotel_name=?""",
                       (hotel,)).fetchall()
    con.close()
    if not rows:
        return {"hotel": hotel, "status": "no_room_types", "rooms": []}
    keys = ["room_id", "room_name", "bed_text", "bed_count", "area", "window", "is_primary", "observed_at"]
    return {"hotel": hotel, "status": "ok", "rooms": [dict(zip(keys, r)) for r in rows]}


def last_observation(hotel: str) -> dict | None:
    con = sqlite3.connect(SNAP.resolve().as_uri() + "?mode=ro", uri=True)
    row = con.execute("""select price, observed_at, source_url from hotel_price_observations
                         where hotel_name=? order by observed_at desc limit 1""", (hotel,)).fetchone()
    band = con.execute("""select min(price), max(price), count(*) from hotel_price_observations
                          where hotel_name=?""", (hotel,)).fetchone()
    con.close()
    if not row:
        con = sqlite3.connect(SNAP.resolve().as_uri() + "?mode=ro", uri=True)
        est = con.execute("""select low, high, mid, confidence, n_comparables, method
                             from hotel_price_estimates where hotel_name=?""", (hotel,)).fetchone()
        con.close()
        if est:
            return {"price": est[2], "estimated": True, "range": [est[0], est[1]],
                    "confidence": est[3], "n_comparables": est[4], "method": est[5],
                    "observed_at": None}
        return None
    return {"price": row[0], "observed_at": row[1], "source_url": row[2],
            "band": {"min": band[0], "max": band[1], "n": band[2]}}


def resolve(hotel: str) -> tuple[int | None, str]:
    url = ("https://m.ctrip.com/restapi/h5api/globalsearch/search?action=json&keyword="
           + quote("西安 " + re.sub(r"[A-Za-z0-9\s\-'’|]+", "", hotel)))
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        return None, f"resolve_http_{r.status_code}"
    try:
        data = r.json().get("data") or []
    except ValueError:
        return None, "resolve_bad_json"
    for c in data:
        if c.get("type") == "hotel" and c.get("cityName") == "西安":
            return int(c["id"]), c.get("word") or hotel
    return None, "resolve_no_hotel"


def live_price(hotel: str, checkin: str, checkout: str, delay: float = 2.0) -> dict:
    hid, where = resolve(hotel)
    if not hid:
        return {"status": "unknown", "reason": where}
    time.sleep(delay)
    url = (f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hid}/?locale=zh-CN&curr=CNY"
           f"&checkin={checkin}&checkout={checkout}")
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=25)
    if r.status_code != 200:
        return {"status": "unknown", "reason": f"detail_http_{r.status_code}", "hotel_id": hid}
    text = r.text.replace('\\"', '"')
    m = re.search(r'"minPrice"\s*:\s*([\d.]+)', text)
    basis = "minPrice"
    if not m:
        m = re.search(r'"priceRange"\s*:\s*"[^"]*?CNY\s*([\d.]+)', text)
        basis = "jsonld_price_range"
    if not m:
        m = re.search(r"起始平均價格.{0,160}?CNY\s*([\d.]+)", text)
        basis = "starting_average_price"
    if not m:
        m = re.search(r"起始平均价格.{0,160}?CNY\s*([\d.]+)", text)
        basis = "starting_average_price"
    if not m:
        return {"status": "unknown", "reason": "no_price_in_page", "hotel_id": hid}
    price = float(m.group(1))
    stamp = now()
    raw_dir = ROOT / "results" / "xian_gapfill_20261109" / "live"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{hashlib.sha256((hotel + checkin).encode()).hexdigest()[:16]}.html"
    raw_path.write_text(r.text, encoding="utf-8")
    rec = {"hotel": hotel, "hotel_id": hid, "price": price, "checkin": checkin,
           "checkout": checkout, "observed_at": stamp, "basis": basis,
           "source_url": url, "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/")}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"status": "ok", **rec, "where": where}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["rooms", "price"])
    ap.add_argument("--hotel", required=True)
    ap.add_argument("--checkin")
    ap.add_argument("--checkout")
    ap.add_argument("--snapshot", default=str(SNAP))
    ap.add_argument("--no-network", action="store_true")
    args = ap.parse_args()
    snapshot = Path(args.snapshot)

    if args.action == "rooms":
        print(json.dumps(rooms(snapshot, args.hotel), ensure_ascii=False, indent=1))
        return 0

    if args.no_network:
        last = last_observation(args.hotel)
        status = "estimated" if last and last.get("estimated") else ("cached" if last else "unknown")
        print(json.dumps({"status": status, "last": last}, ensure_ascii=False, indent=1))
        return 0
    if not args.checkin or not args.checkout:
        print(json.dumps({"status": "error", "reason": "checkin/checkout required"}, ensure_ascii=False))
        return 2
    out = live_price(args.hotel, args.checkin, args.checkout)
    if out.get("status") == "ok":
        out["previous"] = last_observation(args.hotel)
    else:
        out["last"] = last_observation(args.hotel)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
