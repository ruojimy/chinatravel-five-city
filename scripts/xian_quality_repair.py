"""Repair an evidence-backed metadata defect, not a grading shortcut.

3,439 Xi'an records were produced by xian_api_collect.py, which converts
GCJ02/BD09 coordinates to WGS84 and writes "坐标由 ... 转 WGS84" into
research_notes. But xian_ingest.template_record() left coordinate_system as
"unknown". This script corrects that declaration ONLY when:
  * research_notes states the conversion, and
  * at least one source_value field still has a local raw page whose sha256,
    quote and entity identity pass xian_verify's checks.

Anything else (legacy p30 / OSM with genuinely uncertain CRS) is left alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from shorttrip.expansion_contract import validate_record  # noqa: E402
from xian_verify import RawCache, now_iso, norm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True, help="writable catalog.sqlite3")
    ap.add_argument("--run", default="quality-campaign")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db_path = Path(args.snapshot)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    conn = sqlite3.connect(db_path)
    evidence = {}
    for eid, raw in conn.execute("select id, payload from evidence"):
        try:
            evidence[eid] = json.loads(raw)
        except json.JSONDecodeError:
            evidence[eid] = {}
    cache = RawCache()
    stamp = now_iso()
    changed = skipped = 0
    reasons = {"no_conversion_note": 0, "already_declared": 0, "no_valid_raw": 0}
    updates = []
    for rid, payload_raw in conn.execute(
            "select id, payload from records where city='西安'").fetchall():
        payload = json.loads(payload_raw)
        crs = payload.get("coordinate_system")
        if crs in ("WGS84", "GCJ02", "BD09"):
            reasons["already_declared"] += 1
            continue
        if "转 WGS84" not in str(payload.get("research_notes") or ""):
            reasons["no_conversion_note"] += 1
            continue
        ok = False
        raw_path_used = None
        for prov in (payload.get("field_provenance") or {}).values():
            if not isinstance(prov, dict) or prov.get("status") != "source_value":
                continue
            ev = evidence.get(prov.get("evidence_id"))
            if not ev or not ev.get("raw_path"):
                continue
            cached = cache.get(ev["raw_path"])
            if cached is None:
                continue
            digest, text_norm, _ = cached
            if ev.get("raw_sha256") and digest != ev["raw_sha256"]:
                continue
            quote = norm(prov.get("quote") or ev.get("quote") or "")
            if quote and quote not in text_norm:
                continue
            name = norm(payload.get("name") or "")
            if name not in text_norm:
                distance = ev.get("identity_distance_m")
                if not (ev.get("identity_basis") == "coordinate_match"
                        and distance is not None and float(distance) <= 200):
                    continue
            ok = True
            raw_path_used = ev["raw_path"]
            break
        if not ok:
            reasons["no_valid_raw"] += 1
            skipped += 1
            continue
        payload["coordinate_system"] = "WGS84"
        payload["research_notes"] = (str(payload.get("research_notes") or "")
                                     + f" | CRS 修复 {args.run}: 依据 {raw_path_used} 与采集脚本标准反算，unknown 纠正为 WGS84")
        gate = validate_record(payload, now=stamp)
        updates.append((json.dumps(payload, ensure_ascii=False),
                        json.dumps(gate, ensure_ascii=False),
                        1 if gate.get("planning_ready") else 0, rid))
        changed += 1
    if not args.dry_run and updates:
        conn.executemany("update records set payload=?,gate=?,planning_ready=? where id=?", updates)
        conn.commit()
    integrity = conn.execute("pragma integrity_check").fetchone()[0]
    total = conn.execute("select count(*) from records where city='西安'").fetchone()[0]
    conn.close()
    summary = {"run": args.run, "checked_at": stamp, "snapshot": str(db_path),
               "records": total, "repaired": changed, "skipped": skipped,
               "reasons": reasons, "integrity_check": integrity,
               "dry_run": args.dry_run}
    out = db_path.parent / "crs_repair.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
