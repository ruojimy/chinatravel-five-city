"""Grade every Xi'an record as L1-L4 and decide sandbox exposure.

Standard: docs/data_grading_standard.md (approved 2026-11-10).

  P0 定位   missing -> L4 (cannot be routed)
  P1 时序   missing -> L4 (planner parses HH:MM and would crash)
  P2 属性   missing -> L3 (usable, attribute shown as "to confirm")
  else L1 if every P0-P2 value is source_value, otherwise L2 (derived/estimate)

L2 and L3 records carry `dynamic_fetch`, which the planner must honour before
showing a value: the standard says such records open dynamic search by default.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPEC = {
    "attraction": {"P0": ["lat", "lon"], "P1": ["opentime", "endtime"], "P2": ["type"]},
    "restaurant": {"P0": ["lat", "lon"], "P1": ["opentime", "endtime"], "P2": ["cuisine"]},
    "accommodation": {"P0": ["lat", "lon"], "P1": [], "P2": ["price"]},
    "poi": {"P0": ["position"], "P1": [], "P2": ["name"]},
    "metro_station": {"P0": ["position"], "P1": [], "P2": ["line"]},
    "train": {"P0": ["TrainID", "From", "To"], "P1": ["BeginTime", "EndTime", "Duration"], "P2": []},
    "flight": {"P0": ["FlightID", "From", "To"], "P1": ["BeginTime", "EndTime", "Duration"], "P2": []},
}

TOOLS = {
    "accommodation": {"tool": "hotel_dynamic_price", "ttl_hours": 24},
    "restaurant": {"tool": "poi_dynamic_lookup", "ttl_hours": 168},
    "attraction": {"tool": "poi_dynamic_lookup", "ttl_hours": 72},
    "metro_station": {"tool": "metro_line_lookup", "ttl_hours": 720},
    "train": {"tool": "train_schedule_lookup", "ttl_hours": 24},
    "flight": {"tool": "flight_schedule_lookup", "ttl_hours": 6},
    "poi": {"tool": None, "ttl_hours": None},
}

# Fields whose value is only valid for a while; expiry downgrades the display.
# Freshness differs by what the price means: a room rate moves daily, a
# restaurant per-capita moves seasonally, a ticket price yearly.
TTL = {"price": 24, "Cost": 24, "opentime": 2160, "endtime": 2160,
       "BeginTime": 24, "EndTime": 24, "Duration": 24, "line": 17520}
TTL_BY_KIND = {
    "accommodation": {"price": 24},
    "restaurant": {"price": 2160},
    "attraction": {"price": 4320},
}


def present(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    return bool(s) and s.lower() not in {"nan", "none", "null", "unknown"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def grade_record(kind: str, payload: dict) -> dict:
    spec = SPEC[kind]
    data = payload.get("data") or {}
    prov = payload.get("field_provenance") or {}

    def status(field: str) -> str:
        return (prov.get(field) or {}).get("status") or "unknown"

    missing_p0 = [f for f in spec["P0"] if not present(data.get(f))]
    missing_p1 = [f for f in spec["P1"] if not present(data.get(f))]
    missing_p2 = [f for f in spec["P2"] if not present(data.get(f))]

    if missing_p0 or missing_p1:
        grade, exposure = "L4", "reference_only"
    elif missing_p2:
        grade, exposure = "L3", "main"
    else:
        graded = spec["P0"] + spec["P1"] + spec["P2"]
        all_src = all(status(f) == "source_value" for f in graded)
        grade, exposure = ("L1", "main") if all_src else ("L2", "main")

    non_source = {f: status(f) for f in spec["P0"] + spec["P1"] + spec["P2"]
                  if status(f) != "source_value"}
    expired = []
    ttl_map = {**TTL, **TTL_BY_KIND.get(kind, {})}
    for field, hours in ttl_map.items():
        if field not in data:
            continue
        stamp = (prov.get(field) or {}).get("observed_at")
        if not stamp:
            continue
        try:
            seen = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        age = (datetime.now(timezone.utc) - seen.astimezone(timezone.utc)).total_seconds() / 3600
        if age > hours:
            expired.append({"field": field, "age_hours": round(age, 1), "ttl_hours": hours})

    dynamic = None
    if grade in {"L2", "L3"}:
        meta = TOOLS[kind]
        dynamic = {
            "required": True,
            "trigger": "on_access",
            "tool": meta["tool"],
            "ttl_hours": meta["ttl_hours"],
            "reason": f"grade_{grade}",
            "on_failure": "show_as_unconfirmed",
        }
    elif expired and TOOLS[kind]["tool"]:
        dynamic = {
            "required": True,
            "trigger": "on_access",
            "tool": TOOLS[kind]["tool"],
            "ttl_hours": TOOLS[kind]["ttl_hours"],
            "reason": "ttl_expired",
            "on_failure": "show_as_unconfirmed",
        }

    return {
        "grade": grade,
        "exposure": exposure,
        "dynamic_fetch": dynamic,
        "non_source_fields": non_source,
        "missing_p2": missing_p2,
        "expired_fields": expired,
        "graded_at": now_iso(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out-index", default=None)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap

    con = sqlite3.connect(str(snap))
    summary: dict[str, Counter] = defaultdict(Counter)
    records: dict[str, list] = defaultdict(list)

    for rid, kind, name, payload in con.execute(
            "select id,kind,name,payload from records where city='西安'").fetchall():
        if kind not in SPEC:
            continue
        p = json.loads(payload)
        verdict = grade_record(kind, p)
        p["quality_tier"] = verdict
        con.execute("update records set payload=? where id=?",
                    (json.dumps(p, ensure_ascii=False), rid))
        summary[kind][verdict["grade"]] += 1
        summary[kind]["dynamic:" + str(bool(verdict["dynamic_fetch"]))] += 1
        records[kind].append({"name": name, "grade": verdict["grade"],
                              "exposure": verdict["exposure"]})
    con.commit()
    con.close()

    index = {
        "standard": "docs/data_grading_standard.md",
        "snapshot": str(snap.relative_to(ROOT)).replace("\\", "/"),
        "generated_at": now_iso(),
        "policy": "L1-L3 -> sandbox main path; L4 -> reference_only; L2/L3 open dynamic search on access",
        "kinds": {},
    }
    for kind in SPEC:
        counts = {g: summary[kind][g] for g in ("L1", "L2", "L3", "L4")}
        counts["main"] = counts["L1"] + counts["L2"] + counts["L3"]
        counts["dynamic_fetch"] = summary[kind]["dynamic:True"]
        index["kinds"][kind] = counts

    out = Path(args.out_index) if args.out_index else snap.parent / "GRADE_INDEX.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(index["kinds"], ensure_ascii=False, indent=1))
    print("written", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
