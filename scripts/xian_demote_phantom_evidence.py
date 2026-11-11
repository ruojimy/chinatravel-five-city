"""Downgrade source_value fields whose evidence has no usable raw file.

Legacy ingests recorded evidence_id but no raw_path (or a path that no longer
exists). Such a value cannot be re-inspected, so it must not claim
`status=source_value`; it becomes `legacy` and the quality checker stops
counting it as locally verifiable.

Idempotent: runs are cheap and only touch fields that still claim source_value.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap

    con = sqlite3.connect(str(snap))
    raw_cache: dict[str, str | None] = {}
    demoted = 0
    touched_records = 0
    skipped = 0

    rows = con.execute("select id,payload from records where city='西安'").fetchall()
    for rid, payload in rows:
        try:
            rec = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(rec, dict):
            skipped += 1
            continue
        prov_map = rec.get("field_provenance")
        if not isinstance(prov_map, dict):
            skipped += 1
            continue

        changed = False
        for field, prov in prov_map.items():
            if not isinstance(prov, dict) or prov.get("status") != "source_value":
                continue
            eid = prov.get("evidence_id")
            if eid not in raw_cache:
                raw = None
                if eid:
                    ev = con.execute("select payload from evidence where id=?", (eid,)).fetchone()
                    if ev:
                        try:
                            parsed = json.loads(ev[0])
                        except (TypeError, json.JSONDecodeError):
                            parsed = None
                        if isinstance(parsed, dict):
                            raw = parsed.get("raw_path")
                raw_cache[eid] = raw
            raw = raw_cache[eid]
            if raw and (Path(raw).exists() if not Path(raw).is_absolute() else Path(raw).exists()):
                continue
            prov["status"] = "legacy"
            prov["basis"] = "evidence_without_raw"
            demoted += 1
            changed = True

        if changed:
            con.execute("update records set payload=? where id=?",
                        (json.dumps(rec, ensure_ascii=False), rid))
            touched_records += 1

    con.commit()
    con.close()
    print(json.dumps({"snapshot": str(snap), "demoted_fields": demoted,
                      "records": touched_records, "skipped_payloads": skipped},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
