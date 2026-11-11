"""Estimate Xi'an chain hotels from same-brand branches in other cities.

Donor pool: the 10-city extended catalog (7,732 hotels). Each donor price is
normalized by city median so a Beijing branch does not directly set a Xi'an
price:  norm = price * median(Xi'an source_value) / median(donor city).

Only reliable chain tokens are used; suspicious names (凯悦宾馆/万豪宾馆/雷派)
and sub-venues (大堂/前台/停车场/餐厅) are excluded. Status:
`estimated_chain_cross_city`, never source_value.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XIAN = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
CATALOG = ROOT / "data/catalog_v1_1_20261022/catalog.sqlite3"
PROV = XIAN.parent / "price_provenance.csv"
QUEUE = XIAN.parent / "dynamic_price_queue.csv"
EVIDENCE = XIAN.parent / "price_cross_city_estimates.csv"
REPORT = ROOT / "results/cross_city_chain_fill_20261111.json"

CHAINS = {
    "如家": "如家", "汉庭": "汉庭", "宜必思": "宜必思", "星程": "星程",
    "都市118": "都市118", "锦江之星": "锦江之星",
}
SUBVENUE = ("大堂", "前台", "停车场", "餐厅", "宴会厅", "售票处", "服务中心")
HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")


def load_xian():
    with XIAN.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def load_donors():
    con = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    out = []
    for city, payload in con.execute("select city,payload from records where kind='accommodation'"):
        d = json.loads(payload).get("data") or {}
        name = d.get("name") or ""
        try:
            price = float(d.get("price"))
        except (TypeError, ValueError):
            continue
        if price > 0:
            out.append({"city": city, "name": name, "price": price})
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    fields, rows = load_xian()
    for r in rows:
        r["price_f"] = float(r["price"]) if float(r["price"]) > 0 else None
    xi_known = [r["price_f"] for r in rows if r["price_status"] == "source_value" and r["price_f"]]
    xi_med = statistics.median(xi_known)

    donors = load_donors()
    by_city = defaultdict(list)
    for d in donors:
        by_city[d["city"]].append(d["price"])
    city_med = {c: statistics.median(v) for c, v in by_city.items()}

    targets = []
    for r in rows:
        if r["price_status"] != "unknown":
            continue
        name = r["name"]
        if any(k in name for k in SUBVENUE) or any(k in name for k in HOSTEL):
            continue
        chain = next((tok for tok in CHAINS if tok in name), None)
        if not chain:
            continue
        ds = [d for d in donors if CHAINS[chain] in d["name"]]
        if not ds:
            continue
        norm = [d["price"] * xi_med / city_med[d["city"]] for d in ds]
        price = statistics.median(norm)
        targets.append({"name": name, "brand": chain, "n_donors": len(ds),
                        "cities": dict(Counter(d["city"] for d in ds)),
                        "price": price, "range": [min(norm), max(norm)],
                        "donors": [(d["city"], d["name"], d["price"]) for d in ds[:5]],
                        "status": "estimated_chain_cross_city"})

    print(f"xi_median={xi_med:.0f} targets={len(targets)}")
    for t in sorted(targets, key=lambda x: -x["n_donors"]):
        print(f"  {t['name'][:32]:<34} {t['brand']:<7} donors={t['n_donors']:2d} "
              f"price={t['price']:>5.0f} range={t['range'][0]:.0f}-{t['range'][1]:.0f} cities={t['cities']}")

    if args.apply and targets:
        by_name = {r["name"]: r for r in rows}
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        for t in targets:
            r = by_name[t["name"]]
            r["price"] = f"{t['price']:.1f}"
            r["price_status"] = t["status"]
        with XIAN.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows([{k: r[k] for k in fields} for r in rows])

        if PROV.exists():
            with PROV.open(encoding="utf-8-sig", newline="") as fh:
                preader = csv.DictReader(fh)
                pfields = list(preader.fieldnames or [])
                prows = list(preader)
            for row in prows:
                t = next((x for x in targets if x["name"] == row["name"]), None)
                if not t:
                    continue
                row.update(price=f"{t['price']:.1f}", price_status=t["status"],
                           price_low=f"{t['range'][0]:.1f}", price_high=f"{t['range'][1]:.1f}",
                           price_mid=f"{t['price']:.1f}",
                           confidence="medium" if t["n_donors"] >= 3 else "low",
                           n_comparables=str(t["n_donors"]),
                           method=f"cross_city_chain_median:{t['brand']}",
                           observed_at=stamp, source_url="")
            with PROV.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=pfields)
                writer.writeheader()
                writer.writerows(prows)

        if QUEUE.exists():
            with QUEUE.open(encoding="utf-8-sig", newline="") as fh:
                qreader = csv.DictReader(fh)
                qfields = list(qreader.fieldnames or [])
                names = {t["name"] for t in targets}
                qrows = [r for r in qreader if r["name"] not in names]
            with QUEUE.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=qfields)
                writer.writeheader()
                writer.writerows(qrows)

        with EVIDENCE.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "name", "price", "price_status", "brand", "n_donors", "cities",
                "range_low", "range_high", "donor_examples", "observed_at"])
            writer.writeheader()
            for t in targets:
                writer.writerow({"name": t["name"], "price": t["price"],
                                 "price_status": t["status"], "brand": t["brand"],
                                 "n_donors": t["n_donors"],
                                 "cities": json.dumps(t["cities"], ensure_ascii=False),
                                 "range_low": round(t["range"][0], 1),
                                 "range_high": round(t["range"][1], 1),
                                 "donor_examples": json.dumps(t["donors"], ensure_ascii=False),
                                 "observed_at": stamp})

    report = {"xi_median": xi_med, "candidates": len(targets), "applied": args.apply,
              "status": dict(Counter(t["status"] for t in targets)), "items": targets}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": len(targets), "applied": args.apply}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
