"""Batch-resolve Xi'an hotels on Trip.com/Ctrip and capture room types + price.

For each catalog hotel name missing price:
  1. resolve name -> hotelId via m.ctrip.com globalsearch JSON
  2. fetch the hk.trip.com detail page (same hotelId), save raw HTML
  3. parse min price + every room type (name, bed text, bed count, area, window)
  4. emit price / numbed enrich items ONLY when the catalog name appears in the raw page
     (avoids the traditional-vs-simplified name hard failure), and room-type rows always

Outputs (append-only JSONL):
  results/<run>/staging/hotel_batch/items.jsonl
  results/<run>/staging/hotel_batch/room_types.jsonl
  results/<run>/staging/hotel_batch/run_log.jsonl
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "xian_gapfill_20261109"
OUT = RUN / "staging" / "hotel_batch"
RAW = RUN / "raw" / "hotel_batch"
SNAP = RUN / "snapshot_v5" / "catalog.sqlite3"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm_name(s: str) -> str:
    s = re.sub(r"[A-Za-z0-9\s\-\'’|]+", "", s or "")
    return re.sub(r"[\s\-·、,，.。()（）]", "", s).lower()


def dist(a, b, c, d):
    import math
    dx = (a - c) * 111320 * math.cos(math.radians((b + d) / 2))
    dy = (b - d) * 110540
    return math.hypot(dx, dy)


def http(url: str, path: Path, delay: float) -> tuple[int, str]:
    time.sleep(delay)
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                     timeout=25, allow_redirects=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.status_code, r.text


def parse_rooms(text: str) -> list[dict]:
    text = text.replace('\\"', '"')
    rooms, seen = [], set()
    for m in re.finditer(r'"(\d{7,})":\{"id":\1,"name":"([^"]{1,60})"', text):
        rid, name = m.group(1), m.group(2)
        if rid in seen:
            continue
        seen.add(rid)
        seg = text[m.end():m.end() + 2600]
        bed = re.search(r'"bedInfo":\{[^}]*?"title":"([^"]+)"', seg)
        area = re.search(r'"areaInfo":\{[^}]*?"title":"([^"]+)"', seg)
        win = re.search(r'"windowInfo":\{[^}]*?"title":"([^"]+)"', seg)
        bed_text = bed.group(1) if bed else None
        counts = re.findall(r"(\d+)\s*[張张]", bed_text or "")
        bed_count = int(counts[0]) if counts and len(set(counts)) == 1 else None
        if bed_text and ("或" in bed_text or "和" in bed_text):
            bed_count = None
        rooms.append({
            "room_id": rid, "room_name": name, "bed_text": bed_text,
            "bed_count": bed_count,
            "area": (area.group(1) if area else None),
            "window": (win.group(1) if win else None),
        })
    return rooms


def parse_price(text: str) -> tuple[float | None, str | None]:
    text2 = text.replace('\\"', '"')
    for pat, basis in ((r"房[價价]只需\s*CNY\s*([\d.]+)", "visible_header"),
                       (r'"minPrice"\s*:\s*([\d.]+)', "minPrice"),
                       (r'"priceRange"\s*:\s*"[^"]*?CNY\s*([\d.]+)', "jsonld_price_range"),
                       (r"起始平均價格.{0,160}?CNY\s*([\d.]+)", "starting_average_price"),
                       (r"起始平均价格.{0,160}?CNY\s*([\d.]+)", "starting_average_price")):
        m = re.search(pat, text2)
        if m:
            try:
                return float(m.group(1)), basis
            except ValueError:
                pass
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--tag", default="a")
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    args = ap.parse_args()

    global OUT, RAW
    OUT = RUN / "staging" / f"hotel_batch_{args.tag}"
    RAW = RUN / "raw" / f"hotel_batch_{args.tag}"
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    for name in ("items.jsonl", "room_types.jsonl", "run_log.jsonl"):
        (OUT / name).touch(exist_ok=True)

    done = set()
    for extra in (RUN / "staging/hotel/items.jsonl", RUN / "staging/hotel2/items.jsonl",
                  RUN / "staging/merged/items.jsonl", OUT / "items.jsonl"):
        if not extra.exists():
            continue
        for line in extra.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["name"])
                except (json.JSONDecodeError, KeyError):
                    pass

    con = sqlite3.connect(SNAP)
    hotels = []
    for name, payload in con.execute("select name,payload from records where city='西安' and kind='accommodation'"):
        d = json.loads(payload)["data"]
        if d.get("lat") and d.get("lon") and name not in done:
            hotels.append((name, float(d["lat"]), float(d["lon"]), d))
    con.close()
    processed = set()
    for log in sorted((RUN / "staging").glob("hotel_batch_*/run_log.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    processed.add(json.loads(line)["hotel"])
                except (KeyError, json.JSONDecodeError):
                    pass
    hotels = [h for h in hotels if h[0] not in processed]
    hotels.sort(key=lambda x: x[0])
    if args.shard_count > 1:
        hotels = [h for h in hotels
                  if int(hashlib.md5(h[0].encode("utf-8")).hexdigest(), 16) % args.shard_count == args.shard_index]
    batch = hotels[args.offset:args.offset + args.limit]

    ok = skipped = 0
    for name, lat, lon, data in batch:
        base = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        query_name = re.sub(r"[A-Za-z0-9\s\-\'’|]+", "", name).strip() or name
        resolve_url = ("https://m.ctrip.com/restapi/h5api/globalsearch/search?action=json&keyword="
                       + quote("西安 " + query_name))
        try:
            status, body = http(resolve_url, RAW / "resolve" / f"{base}.json", args.delay)
        except Exception as exc:
            (OUT / "run_log.jsonl").open("a", encoding="utf-8").write(json.dumps(
                {"hotel": name, "stage": "resolve", "error": type(exc).__name__}, ensure_ascii=False) + "\n")
            skipped += 1
            continue
        if status != 200:
            skipped += 1
            continue
        try:
            cands = json.loads(body).get("data") or []
        except json.JSONDecodeError:
            skipped += 1
            continue
        best = None
        for c in cands:
            if c.get("type") != "hotel" or c.get("cityName") != "西安":
                continue
            try:
                dd = dist(lat, lon, float(c["lat"]), float(c["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            qn, wn = norm_name(name), norm_name(c.get("word") or "")
            name_ok = bool(qn) and qn in wn
            if not name_ok and len(qn) <= 4:
                name_ok = dd <= 150
            if name_ok and dd <= 2000 and (best is None or dd < best[0]):
                best = (dd, c)
        if not best:
            (OUT / "run_log.jsonl").open("a", encoding="utf-8").write(json.dumps(
                {"hotel": name, "stage": "resolve", "error": "no_candidate"}, ensure_ascii=False) + "\n")
            skipped += 1
            continue
        dd, cand = best
        hid = cand["id"]
        detail_url = f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hid}/?locale=zh-CN&curr=CNY"
        try:
            status, html = http(detail_url, RAW / f"{hid}.html", args.delay)
        except Exception as exc:
            skipped += 1
            continue
        if status != 200:
            skipped += 1
            continue

        price, basis = parse_price(html)
        rooms = parse_rooms(html)
        beds = [r["bed_count"] for r in rooms if r["bed_count"]]
        primary = None
        if beds:
            modal, n = Counter(beds).most_common(1)[0]
            if list(Counter(beds).values()).count(n) == 1:
                pool = [r for r in rooms if r["bed_count"] == modal]
                pool.sort(key=lambda r: (float(re.search(r"([\d.]+)", r.get("area") or "").group(1)) if re.search(r"([\d.]+)", r.get("area") or "") else 999999))
                primary = pool[0]

        stamp = now()
        for r in rooms:
            row = {"hotel": name, "city": "西安", "source_url": detail_url,
                   "raw_path": str((RAW / f"{hid}.html").relative_to(ROOT)).replace("\\", "/"),
                   "observed_at": stamp, "hotel_id": hid,
                   "resolved_name": cand.get("word"), "distance_m": round(dd, 1),
                   **r, "is_primary": 1 if primary and r["room_id"] == primary["room_id"] else 0}
            (OUT / "room_types.jsonl").open("a", encoding="utf-8").write(
                json.dumps(row, ensure_ascii=False) + "\n")

        raw_text = html
        name_present = name in raw_text
        if price and name_present:
            pm = re.search(r".{0,40}CNY\s*" + re.escape(str(int(price))) + r".{0,40}", html.replace('\\"', '"'))
            quote_text = pm.group(0) if pm else f"CNY{int(price)}"
            item = {"kind": "accommodation", "name": name, "data": {"price": int(price)},
                    "source": {"url": detail_url, "publisher": "Trip.com（携程集团）",
                               "authority": "travel_marketplace_display",
                               "licence_status": "public_page_reuse_unverified",
                               "observed_at": stamp},
                    "evidence": {"raw_path": row["raw_path"], "quote": quote_text,
                                 "locator": f"price_basis:{basis}", "identity_basis": "hotel_id+distance<=300m",
                                 "matched_name": cand.get("word")},
                    "notes": f"price_basis={basis}; resolved={cand.get('word')}; distance_m={dd:.0f}"}
            (OUT / "items.jsonl").open("a", encoding="utf-8").write(
                json.dumps(item, ensure_ascii=False) + "\n")

        if primary and name_present:
            q = primary.get("bed_text") or ""
            if q:
                item = {"kind": "accommodation", "name": name, "data": {"numbed": primary["bed_count"]},
                        "source": {"url": detail_url, "publisher": "Trip.com（携程集团）",
                                   "authority": "travel_marketplace_display",
                                   "licence_status": "public_page_reuse_unverified",
                                   "observed_at": stamp},
                        "evidence": {"raw_path": row["raw_path"], "quote": q,
                                     "locator": f"room:{primary['room_id']}.bedInfo",
                                     "identity_basis": "primary_room=modal_bed_count+smallest_area"},
                        "notes": f"primary_room={primary['room_name']}; selection=modal bed count, smallest area"}
                (OUT / "items.jsonl").open("a", encoding="utf-8").write(
                    json.dumps(item, ensure_ascii=False) + "\n")

        (OUT / "run_log.jsonl").open("a", encoding="utf-8").write(json.dumps(
            {"hotel": name, "stage": "done", "hotel_id": hid, "rooms": len(rooms),
             "price": price, "basis": basis, "name_present": name_present,
             "primary_bed": primary["bed_count"] if primary else None,
             "distance_m": round(dd, 1)}, ensure_ascii=False) + "\n")
        ok += 1
        print(f"[{ok}/{len(batch)}] {name} rooms={len(rooms)} price={price} primary={primary['bed_count'] if primary else None}")

    print(json.dumps({"done": ok, "skipped": skipped, "batch": len(batch)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
