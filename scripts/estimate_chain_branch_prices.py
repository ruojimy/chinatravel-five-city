"""Estimate unknown hotel prices from other branches of the same chain.

Only strict brand prefixes are used (no generic words like "青年旅舍"), and
donors must be `source_value` hotels whose name contains the same chain token.
Hostels without a chain donor fall back to the hostel-category median.

Status: `estimated_chain_branch` / `estimated_hostel_comparable`, never
source_value. Writes an evidence CSV and updates the main table only with
--apply.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
PROV = CSV_PATH.parent / "price_provenance.csv"
QUEUE = CSV_PATH.parent / "dynamic_price_queue.csv"
EVIDENCE = CSV_PATH.parent / "price_chain_branch_estimates.csv"
REPORT = ROOT / "results/chain_branch_fill_20261111.json"

# token in name -> token that must appear in donor names
CHAINS = {
    "易休太空舱": "易休太空舱",
    "布丁": "布丁",
    "oyo": "oyo",
    "尚客优": "尚客优",
    "维也纳国际": "维也纳国际",
}
HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")
SUBVENUE = ("大堂", "前台", "停车场", "餐厅", "宴会厅", "售票处", "服务中心")


def load():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    fields, rows = load()
    for r in rows:
        r["price_f"] = float(r["price"]) if float(r["price"]) > 0 else None
    known = [r for r in rows if r["price_status"] == "source_value" and r["price_f"]]

    targets = []
    for r in rows:
        if r["price_status"] != "unknown":
            continue
        name = r["name"]
        if any(k in name for k in SUBVENUE):
            continue
        low = name.lower()
        chain = next((tok for tok in CHAINS if tok in low), None)
        if chain:
            donors = [d["price_f"] for d in known if CHAINS[chain] in d["name"].lower()]
            if donors:
                med = statistics.median(donors)
                targets.append({"name": name, "kind": "chain", "brand": chain,
                                "donors": donors, "price": med,
                                "range": [min(donors), max(donors)],
                                "status": "estimated_chain_branch"})
                continue
        if any(k in name for k in HOSTEL):
            donors = [d["price_f"] for d in known if any(k in d["name"] for k in HOSTEL)]
            med = statistics.median(donors)
            targets.append({"name": name, "kind": "hostel_category", "brand": "hostel",
                            "donors": donors, "price": med,
                            "range": [min(donors), max(donors)],
                            "status": "estimated_hostel_comparable"})

    print(f"targets={len(targets)}")
    for t in targets:
        print(f"  {t['name'][:34]:<36} {t['status']:<28} price={t['price']:.0f} "
              f"range={t['range'][0]:.0f}-{t['range'][1]:.0f} donors={t['donors']}")

    if args.apply and targets:
        by_name = {r["name"]: r for r in rows}
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        for t in targets:
            r = by_name[t["name"]]
            r["price"] = f"{t['price']:.1f}"
            r["price_status"] = t["status"]
        with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
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
                           price_mid=f"{t['price']:.1f}", confidence="medium",
                           n_comparables=str(len(t["donors"])),
                           method=f"chain_branch_median:{t['brand']}",
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
                "name", "price", "price_status", "brand", "n_donors",
                "range_low", "range_high", "donor_prices", "observed_at"])
            writer.writeheader()
            for t in targets:
                writer.writerow({"name": t["name"], "price": t["price"],
                                 "price_status": t["status"], "brand": t["brand"],
                                 "n_donors": len(t["donors"]),
                                 "range_low": t["range"][0], "range_high": t["range"][1],
                                 "donor_prices": "|".join(str(x) for x in t["donors"]),
                                 "observed_at": stamp})

    report = {"candidates": len(targets), "applied": args.apply,
              "status": dict(Counter(t["status"] for t in targets)),
              "items": targets}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": len(targets), "applied": args.apply,
                      "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
