"""Bulk-resolve Xi'an hotel names to Trip.com hotelIds via the public global-search JSON.

Runs a fixed set of district/brand queries (one request each, >=2.6 s apart), saves every
response under raw/hotel2/resolve/, and matches the candidate hotels against
targets/hotel_missing.csv by (core name, coordinate <=200 m).

Usage:
  python scripts/xian_gapfill_hotel2_resolve.py [--dry] [--max-queries 30]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import opencc

ROOT = Path(__file__).resolve().parents[1]
RUN = "results/xian_gapfill_20261109"
PY = str(ROOT / ".venv/Scripts/python.exe")
FETCH = ROOT / "scripts/xian_gapfill_fetch.py"
GAP = 2.6
CC = opencc.OpenCC("t2s")

QUERIES = [
    "西安钟楼酒店", "西安回民街酒店", "西安大雁塔酒店", "西安大唐不夜城酒店",
    "西安曲江酒店", "西安高新区酒店", "西安小寨酒店", "西安火车站酒店",
    "西安北站酒店", "西安浐灞酒店", "西安经开区酒店", "西安城墙酒店",
    "西安南门酒店", "西安交通大学酒店", "西安咸阳机场酒店", "西安大明宫酒店",
    "西安雁塔区酒店", "西安碑林区酒店", "西安莲湖区酒店", "西安新城区酒店",
    "西安未央区酒店", "西安宾馆", "西安饭店", "西安民宿",
    "西安商务酒店", "西安五星级酒店", "西安四星级酒店", "西安连锁酒店",
    "西安温泉酒店", "西安度假酒店", "西安汉庭酒店", "西安如家酒店",
    "西安全季酒店", "西安维也纳酒店", "西安亚朵酒店", "西安锦江之星",
]


def norm(s: str) -> str:
    return re.sub(r"[\s\u3000（）()·・\-,，.。、|]", "", s or "").lower()


def core(name: str) -> str:
    n = CC.convert(name or "")
    n = re.sub(r"[（(][^）)]*[）)]", "", n)
    n = re.sub(r"^(西安市|西安|陕西)", "", n)
    n = re.sub(r"(酒店|宾馆|饭店|旅馆|民宿)$", "", n)
    return norm(n)


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def slug(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:60]


def fetch_json(url: str, out_rel: str) -> dict | None:
    proc = subprocess.run([PY, str(FETCH), "--url", url, "--out", out_rel],
                          capture_output=True, text=True, cwd=str(ROOT))
    lines = (proc.stdout or "").strip().splitlines()
    try:
        rec = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        return None
    if not rec.get("ok"):
        return None
    try:
        return json.loads((ROOT / rec["path"]).read_bytes().decode("utf-8", "replace"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-queries", type=int, default=len(QUERIES))
    args = ap.parse_args()

    import urllib.parse

    targets = []
    with open(ROOT / RUN / "targets/hotel_missing.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if "price" in (row.get("missing") or ""):
                targets.append(row)
    done = set()
    items_path = ROOT / RUN / "staging/hotel/items.jsonl"
    if items_path.exists():
        for line in items_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["name"])
    items2 = ROOT / RUN / "staging/hotel2/items.jsonl"
    if items2.exists():
        for line in items2.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["name"])
    targets = [t for t in targets if t["name"] not in done]

    resolve_dir = ROOT / RUN / "raw/hotel2/resolve"
    resolve_dir.mkdir(parents=True, exist_ok=True)

    cands: dict[str, dict] = {}
    for i, q in enumerate(QUERIES[:args.max_queries], 1):
        out = f"{RUN}/raw/hotel2/resolve/q{i:02d}_{slug(q)}.json"
        url = ("https://hk.trip.com/restapi/h5api/globalsearch/search?action=json&keyword="
               + urllib.parse.quote(q))
        payload = fetch_json(url, out)
        if payload is None:
            print(f"[q{i}] {q} -> FAILED", flush=True)
            time.sleep(GAP)
            continue
        added = 0
        for e in payload.get("data") or []:
            if e.get("type") != "hotel" or int(e.get("cityId") or 0) != 10:
                continue
            hid = str(e.get("id") or "")
            if not hid or hid == "0":
                continue
            if hid in cands:
                continue
            cands[hid] = {
                "hotel_id": hid,
                "word": e.get("word") or "",
                "lat": float(e.get("lat") or 0),
                "lon": float(e.get("lon") or 0),
                "score": e.get("commentScore"),
                "count": e.get("commentCount"),
                "query": q,
            }
            added += 1
        print(f"[q{i}] {q} -> {len(payload.get('data') or [])} entries, +{added} new "
              f"(total {len(cands)})", flush=True)
        time.sleep(GAP)

    (ROOT / RUN / "raw/hotel2/resolve/_candidates.json").write_text(
        json.dumps(list(cands.values()), ensure_ascii=False, indent=1), encoding="utf-8")

    matches = []
    for t in targets:
        tc = core(t["name"])
        try:
            tlat, tlon = float(t["lat"]), float(t["lon"])
        except (TypeError, ValueError):
            tlat = tlon = None
        best = None
        for c in cands.values():
            cc = core(c["word"])
            if not tc or not cc:
                continue
            if tc == cc:
                base = 100
            elif len(tc) >= 4 and (tc in cc or cc in tc):
                base = 60
            else:
                continue
            dist = None
            if tlat is not None and c["lat"] and c["lon"]:
                dist = haversine((tlat, tlon), (c["lat"], c["lon"]))
            if dist is not None and dist > 200:
                continue
            score = base + (10 if dist is not None else 0) + (5 if base == 100 else 0)
            if best is None or score > best[0]:
                best = (score, c, dist)
        if best:
            matches.append({
                "name": t["name"], "hotel_id": best[1]["hotel_id"],
                "word": best[1]["word"], "dist_m": round(best[2], 1) if best[2] is not None else None,
                "score": best[0], "lat": tlat, "lon": tlon,
            })

    matches.sort(key=lambda m: -m["score"])
    (ROOT / RUN / "raw/hotel2/_matches.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"targets_pending={len(targets)} candidates={len(cands)} matched={len(matches)}")
    for m in matches[:15]:
        print(f"  {m['score']:>3} {m['dist_m']} {m['name']}  <-  {m['word']} [{m['hotel_id']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
