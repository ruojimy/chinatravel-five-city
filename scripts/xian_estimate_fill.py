"""Fill missing accommodation price with a class-aware comparable estimate + range.

Policy (2026-11-09):
  * observed price wins; never overwrite
  * missing price -> estimated range, main record stores the median
  * comparables are same-class hotels first (luxury / mid / budget), then city prior
  * missing numbed -> primary room bed count if known, else default 1
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.expansion_contract import validate_record  # noqa: E402

LUX = ("威斯汀", "索菲特", "丽思", "万豪", "希尔顿", "洲际", "皇冠", "凯宾", "悦榕", "香格里拉",
       "瑞吉", "康莱德", "华尔道夫", "柏悦", "君悦", "凯悦", "四季", "温德姆", "豪生", "戴斯",
       "华邑", "传奇", "五星", "豪华", "泳池", "行政酒廊")
BUDGET = ("宾馆", "旅馆", "招待所", "青旅", "青年旅舍", "民宿", "公寓", "客栈", "快捷", "连锁",
          "OYO", "7天", "如家", "汉庭", "锦江之星", "城市便捷", "家庭旅馆", "旅社")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist(a, b, c, d):
    dx = (a - c) * 111320 * math.cos(math.radians((b + d) / 2))
    dy = (b - d) * 110540
    return math.hypot(dx, dy)


def hotel_class(name: str, feature: str | None) -> str:
    text = f"{feature or ''} {name or ''}"
    if any(t in text for t in LUX):
        return "luxury"
    if any(t in text for t in BUDGET):
        return "budget"
    return "mid"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap

    attempted = {}
    for log in sorted((ROOT / "results/xian_gapfill_20261109/staging").glob("hotel_batch_*/run_log.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            j = json.loads(line)
            if j.get("stage") == "done":
                attempted[j["hotel"]] = (str(log.relative_to(ROOT)).replace("\\", "/"), j.get("hotel_id"), "detail_no_price")
            elif j.get("error") == "no_candidate" and j["hotel"] not in attempted:
                attempted[j["hotel"]] = (str(log.relative_to(ROOT)).replace("\\", "/"), None, "no_candidate")

    con = sqlite3.connect(str(snap))
    prior_estimates = []
    try:
        prior_estimates = con.execute("""select hotel_name, hotel_class, low, high, mid,
            n_comparables, method, confidence, created_at, attempt_ref
            from hotel_price_estimates""").fetchall()
        prior_estimates = [tuple(p) + (None,) for p in prior_estimates]
    except sqlite3.OperationalError:
        pass
    rows = []
    for rid, name, payload in con.execute(
            "select id,name,payload from records where city='西安' and kind='accommodation'"):
        parsed = json.loads(payload)
        rows.append({"id": rid, "name": name, "data": parsed.get("data") or {}, "payload": parsed})

    for r in rows:
        r["class"] = hotel_class(r["name"], r["data"].get("featurehoteltype"))

    priced = [r for r in rows if r["data"].get("price") not in (None, "")]
    city_prices = [float(r["data"]["price"]) for r in priced]
    city_med = pct(city_prices, 0.5) or 245
    by_class = defaultdict(list)
    for p in priced:
        by_class[p["class"]].append(float(p["data"]["price"]))
    class_prior = {c: {"p25": pct(v, 0.25), "p50": pct(v, 0.5), "p75": pct(v, 0.75)}
                   for c, v in by_class.items() if len(v) >= 3}
    factors = {"luxury": 2.4, "mid": 1.0, "budget": 0.45}

    stamp = now()
    estimates = []
    filled_price = filled_bed = 0
    for r in rows:
        d = r["data"]
        lat, lon = d.get("lat"), d.get("lon")
        cls = r["class"]
        if d.get("price") in (None, "") and r["name"] in attempted:
            cands = []
            if lat and lon:
                for p in priced:
                    if p["class"] != cls:
                        continue
                    pd = p["data"]
                    if not (pd.get("lat") and pd.get("lon")):
                        continue
                    dd = dist(lat, lon, float(pd["lat"]), float(pd["lon"]))
                    if dd <= 8000:
                        cands.append((dd, float(pd["price"])))
            cands.sort()
            near = [v for _, v in cands[:12]]
            attempt_type = attempted[r["name"]][2]
            if len(near) >= 4:
                low, high, mid = pct(near, 0.25), pct(near, 0.75), pct(near, 0.5)
                method = f"same_class_nearest_p25_p75:{cls}"
                confidence = "high" if len(near) >= 8 else "medium"
                if len(near) < 8:
                    low, high = low * 0.85, high * 1.15
                if attempt_type == "no_candidate":
                    low, high = low * 0.75, high * 1.25
                    confidence = "low"
            elif cls in class_prior:
                pr = class_prior[cls]
                low, high, mid = pr["p25"], pr["p75"], pr["p50"]
                method = f"same_class_city_p25_p75:{cls}"
                confidence = "medium"
            else:
                mid = city_med * factors.get(cls, 1.0)
                low, high = mid * 0.65, mid * 1.55
                method = f"city_prior_factor:{cls}"
                confidence = "low"
            if low is None or high is None or mid is None:
                continue
            low = max(1, round(low / 10) * 10)
            high = max(low + 10, round(high / 10) * 10)
            mid = int(round(mid))
            estimates.append({"hotel": r["name"], "hotel_class": cls,
                              "low": low, "high": high, "mid": mid,
                              "n_comparables": len(near), "method": method,
                              "confidence": confidence, "created_at": stamp,
                              "attempt_type": attempt_type,
                              "hotel_id": attempted[r["name"]][1]})
            d["price"] = mid
            prov = r["payload"].setdefault("field_provenance", {})["price"]
            prov.update({"source_id": None, "source_url": None, "observed_at": stamp,
                         "status": "estimated", "evidence_id": None, "quote": None,
                         "valid_until": None, "method": method, "hotel_class": cls,
                         "range": [low, high], "n_comparables": len(near),
                         "confidence": confidence,
                         "attempt_ref": attempted[r["name"]][0],
                         "attempt_type": attempt_type,
                         "hotel_id": attempted[r["name"]][1]})
            filled_price += 1

        if d.get("numbed") in (None, ""):
            primary = con.execute(
                "select bed_count from room_types where hotel_name=? and is_primary=1 and bed_count is not null limit 1",
                (r["name"],)).fetchone()
            bed = int(primary[0]) if primary else 1
            d["numbed"] = bed
            prov = r["payload"].setdefault("field_provenance", {})["numbed"]
            prov.update({"source_id": None, "source_url": None, "observed_at": stamp,
                         "status": "estimated", "evidence_id": None, "quote": None,
                         "valid_until": None,
                         "basis": "primary_room" if primary else "default_single_bed"})
            filled_bed += 1

        gate = validate_record(r["payload"], now=stamp)
        con.execute("update records set payload=?,gate=?,planning_ready=? where id=?",
                    (json.dumps(r["payload"], ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
                     1 if gate["planning_ready"] else 0, r["id"]))

    con.execute("drop table if exists hotel_price_estimates")
    con.execute("""create table hotel_price_estimates (
        hotel_name text primary key, hotel_class text, low real, high real, mid real,
        n_comparables integer, method text, confidence text, created_at text, attempt_ref text, attempt_type text)""")
    con.executemany("""insert or replace into hotel_price_estimates
        (hotel_name, hotel_class, low, high, mid, n_comparables, method, confidence, created_at, attempt_ref, attempt_type)
        values (?,?,?,?,?,?,?,?,?,?,?)""", [
        (e["hotel"], e["hotel_class"], e["low"], e["high"], e["mid"], e["n_comparables"],
         e["method"], e["confidence"], e["created_at"], e.get("attempt_ref"), e.get("attempt_type")) for e in estimates]
        + [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10]) for p in prior_estimates])
    con.commit()
    con.close()
    print(json.dumps({"price_filled": filled_price, "numbed_filled": filled_bed,
                      "estimates": len(estimates),
                      "by_class": {c: sum(1 for e in estimates if e["hotel_class"] == c)
                                   for c in ("luxury", "mid", "budget")},
                      "sample": estimates[:5]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
