"""Apply arithmetic-derived Duration values (minutes -> hours) to a snapshot copy.

Only fills null Duration. Provenance is marked `derived` with the formula and the
BeginTime/EndTime basis, never `source_value`.
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


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--derived", required=True)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap
    src = Path(args.derived)
    if not src.is_absolute():
        src = ROOT / src

    rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    conn = sqlite3.connect(str(snap))
    applied = []
    skipped = []
    stamp = now_iso()
    for row in rows:
        kind, name = row.get("kind"), row.get("name")
        if row.get("field") != "Duration":
            skipped.append({"name": name, "reason": "not_duration"})
            continue
        hit = conn.execute(
            "select id, payload from records where city='西安' and kind=? and name=?",
            (kind, name)).fetchall()
        if not hit:
            skipped.append({"name": name, "reason": "not_found"})
            continue
        minutes = float(row["value"])
        hours = round(minutes / 60.0, 2)
        for record_id, payload_raw in hit:
            payload = json.loads(payload_raw)
            data = payload.setdefault("data", {})
            if data.get("Duration") not in (None, ""):
                skipped.append({"name": name, "reason": "already_known", "record_id": record_id})
                continue
            data["Duration"] = hours
            payload.setdefault("field_policies", {})["Duration"] = "intercity_schedule"
            payload.setdefault("field_provenance", {})["Duration"] = {
                "source_id": None,
                "source_url": None,
                "observed_at": None,
                "status": "derived",
                "evidence_id": None,
                "quote": None,
                "valid_until": None,
                "formula": row.get("formula"),
                "basis": row.get("basis"),
                "note": f"{minutes:g} minutes / 60 = {hours} hours",
            }
            gate = validate_record(payload, now=stamp)
            conn.execute(
                "update records set payload=?, gate=?, planning_ready=? where id=?",
                (json.dumps(payload, ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
                 1 if gate["planning_ready"] else 0, record_id))
            applied.append({"name": name, "record_id": record_id, "hours": hours})
    conn.commit()
    conn.close()
    print(json.dumps({"applied": len(applied), "skipped": len(skipped),
                      "skipped_detail": skipped[:20],
                      "sample": applied[:5]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
