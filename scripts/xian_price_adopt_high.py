"""Adopt only high-confidence price estimates; demote the rest to on-request.

User policy (2026-11-10): real neighbour-based estimates are acceptable, but
only high-confidence ones may be adopted. Everything else keeps its estimate
for ranking/audit but must not present a price.

Calibration note: leave-one-out on 240 verified prices shows the current
confidence label (n_comparables >= 8) does NOT improve interval coverage
(high 44.2% vs medium 50.0%), so `calibrated_coverage` is recorded next to
every adopted estimate instead of implying precision.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.expansion_contract import validate_record  # noqa: E402

COVERAGE = {"high": 0.442, "medium": 0.500, "low": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap

    con = sqlite3.connect(str(snap))
    cols = {r[1] for r in con.execute("pragma table_info(hotel_price_estimates)")}
    if "adopted" not in cols:
        con.execute("alter table hotel_price_estimates add column adopted integer default 0")

    stats = {"kept_high": 0, "demoted_medium": 0, "demoted_low": 0, "untouched_verified": 0}
    stamp = "2026-11-10T23:30:00+08:00"

    for rid, name, payload in con.execute(
            "select id,name,payload from records where city='西安' and kind='accommodation'").fetchall():
        p = json.loads(payload)
        prov = p["field_provenance"].get("price") or {}
        status = prov.get("status")
        if status == "source_value":
            stats["untouched_verified"] += 1
            continue
        if status != "estimated":
            continue
        conf = prov.get("confidence") or "low"
        if conf == "high":
            prov["adopted"] = True
            prov["calibrated_coverage"] = COVERAGE["high"]
            prov["adoption_rule"] = "high_confidence_only_v1"
            stats["kept_high"] += 1
        else:
            p["data"]["price"] = None
            kept = {k: prov.get(k) for k in
                    ("method", "hotel_class", "range", "n_comparables", "confidence",
                     "attempt_ref", "attempt_type", "hotel_id")}
            p["field_provenance"]["price"] = {
                "source_id": None, "source_url": None, "observed_at": None,
                "status": "unknown", "evidence_id": None, "quote": None,
                "valid_until": None, "basis": "estimate_not_adopted",
                "estimate": kept,
            }
            stats["demoted_" + conf] = stats.get("demoted_" + conf, 0) + 1
        p["field_provenance"]["price"] = prov if conf == "high" else p["field_provenance"]["price"]
        gate = validate_record(p, now=stamp)
        con.execute("update records set payload=?,gate=?,planning_ready=? where id=?",
                    (json.dumps(p, ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
                     1 if gate["planning_ready"] else 0, rid))

    con.execute("update hotel_price_estimates set adopted=1 where confidence='high'")
    con.execute("update hotel_price_estimates set adopted=0 where confidence!='high'")
    con.commit()

    rows = [json.loads(r[0]) for r in con.execute(
        "select payload from records where city='西安' and kind='accommodation'")]
    out = {
        **stats,
        "price_present": sum(1 for p in rows if p["data"].get("price") not in (None, "")),
        "status": {
            "source_value": sum(1 for p in rows if p["field_provenance"]["price"].get("status") == "source_value"),
            "estimated_adopted": sum(1 for p in rows if p["field_provenance"]["price"].get("status") == "estimated"),
            "unknown": sum(1 for p in rows if p["field_provenance"]["price"].get("status") == "unknown"),
        },
    }
    con.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
