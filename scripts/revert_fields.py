"""Revert specific field claims that the audit could not re-derive.

`xian_verify.py` is the authority: if a record's name is not verbatim in its
saved raw, or the raw belongs to a different branch, the claim is not
established and must go back to null rather than be defended. This writes a new
snapshot (never edits the parent) with those fields cleared, their provenance
dropped, and the gate recomputed.

Usage:
  XT_CITY=厦门 python scripts/revert_fields.py \
      --parent results/<run>/snapshot_v3/catalog.sqlite3 \
      --out results/<run>/snapshot_v4 \
      --reason "official page lacks venue name" \
      --revert 'attraction|鼓浪屿风琴博物馆|price' \
      --revert 'restaurant|遇见西木美式餐厅（ioi店）|cuisine'
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from shorttrip.expansion_contract import validate_record  # noqa: E402
from xt_city import city as _city  # noqa: E402

CITY = _city()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--revert", action="append", default=[],
                    help="kind|name|field  (repeatable)")
    ap.add_argument("--reason", default=None)
    args = ap.parse_args()

    parent = Path(args.parent)
    if not parent.is_absolute():
        parent = ROOT / parent
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing snapshot: {out}")
    out.mkdir(parents=True)
    target = out / "catalog.sqlite3"
    shutil.copy2(parent, target)

    wanted: list[tuple[str, str, str]] = []
    for spec in args.revert:
        kind, name, field = spec.split("|", 2)
        wanted.append((kind.strip(), name.strip(), field.strip()))

    stamp = now_iso()
    conn = sqlite3.connect(target)
    reverted, missing = [], []
    for kind, name, field in wanted:
        hit = conn.execute(
            "select id, payload from records where city=? and kind=? and name=?",
            (CITY, kind, name)).fetchone()
        if hit is None:
            missing.append({"kind": kind, "name": name, "reason": "record_not_found"})
            continue
        rid, raw = hit
        payload = json.loads(raw)
        data = payload.get("data") or {}
        if data.get(field) in (None, ""):
            missing.append({"kind": kind, "name": name, "field": field,
                            "reason": "already_null"})
            continue
        previous = data[field]
        data[field] = None
        payload["data"] = data
        (payload.get("field_provenance") or {}).pop(field, None)
        (payload.get("field_policies") or {}).pop(field, None)
        gate = validate_record(payload, now=stamp)
        conn.execute(
            "update records set payload=?, gate=?, planning_ready=? where id=?",
            (json.dumps(payload, ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
             1 if gate["planning_ready"] else 0, rid))
        reverted.append({"kind": kind, "name": name, "field": field, "was": previous})
    conn.commit()
    conn.close()

    (out / "manifest.json").write_text(json.dumps({
        "parent": str(parent.relative_to(ROOT)).replace("\\", "/"),
        "created_at": stamp,
        "label": f"revert: {args.reason or 'audit hard failure'}",
        "city": CITY,
        "reverted": reverted,
        "missing": missing,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps({"snapshot": str(target.relative_to(ROOT)).replace("\\", "/"),
                      "reverted": len(reverted), "missing": missing}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
