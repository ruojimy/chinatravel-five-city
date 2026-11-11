"""Re-anchor metro `line` provenance to a stable copy of subways.json.

The merged sandbox is rebuilt and its bytes change; evidence hashes must point at
an immutable capture, not at a generated file.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.expansion_contract import validate_record  # noqa: E402

STABLE = ROOT / "results/xian_gapfill_20261109/raw/recovery/subways_used_20261109.json"


def main() -> int:
    snap = Path(sys.argv[1] if len(sys.argv) > 1 else
                "results/xian_gapfill_20261109/snapshot_v6/catalog.sqlite3")
    if not snap.is_absolute():
        snap = ROOT / snap
    raw = STABLE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    rel = str(STABLE.relative_to(ROOT)).replace("\\", "/")

    con = sqlite3.connect(str(snap))
    rows = con.execute("select id,payload from records where city='西安' and kind='metro_station'").fetchall()
    fixed = 0
    for rid, payload_raw in rows:
        payload = json.loads(payload_raw)
        data = payload.get("data") or {}
        prov = (payload.get("field_provenance") or {}).get("line")
        if not data.get("line") or not isinstance(prov, dict):
            continue
        name = payload.get("name") or data.get("name") or ""
        quote = prov.get("quote") or name
        if quote not in text:
            continue
        url = prov.get("source_url") or "https://map.amap.com/subway/index.html"
        new_id = "xian-evidence:" + hashlib.sha256(
            f"{url}|{quote}|{sha}".encode("utf-8")).hexdigest()[:40]
        prov["evidence_id"] = new_id
        prov["quote"] = quote
        payload["field_provenance"]["line"] = prov
        evidence = {
            "evidence_id": new_id,
            "source_url": url,
            "publisher": "高德",
            "authority": "public_timetable",
            "licence_status": "public_timetable",
            "raw_path": rel,
            "raw_sha256": sha,
            "raw_bytes": len(raw),
            "text_sha256": text_sha,
            "quote": quote,
            "quote_match": "raw",
            "locator": "subways.xian[].stations[].name",
            "captured_at": "2026-11-09T00:00:00+08:00",
            "truth_certified": False,
            "entity_verified": False,
        }
        gate = validate_record(payload, now="2026-11-09T17:00:00+08:00")
        con.execute("insert or replace into evidence (id,payload) values (?,?)",
                    (new_id, json.dumps(evidence, ensure_ascii=False)))
        con.execute("update records set payload=?,gate=?,planning_ready=? where id=?",
                    (json.dumps(payload, ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
                     1 if gate["planning_ready"] else 0, rid))
        fixed += 1
    con.commit()
    con.close()
    print(json.dumps({"fixed": fixed, "sha256": sha, "stable": rel}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
