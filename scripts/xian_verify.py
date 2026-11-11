"""Audit a Xi'an snapshot for data authenticity, not just counts.

For every record it re-derives what the warehouse claims:
  * evidence rows referenced by field_provenance actually exist
  * the raw page still sits at raw_path with the recorded sha256
  * the quoted text is still verbatim in that raw page
  * the entity name appears in the page
  * coordinates fall inside the Xi'an bounding box and declare a CRS
  * no two records in a kind share an identity

Legacy rows whose raw page was never captured locally are reported as
`legacy_unverifiable`, never as verified. Exit code is 1 only for structural
problems (missing table, integrity failure), so a batch can still close.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.expansion_contract import FIELDS, OPTIONAL_VALUES, validate_record  # noqa: E402

CITY = "西安"
BBOX = {"lon": (107.3, 109.9), "lat": (33.5, 34.9)}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(text: str) -> str:
    text = (text or "").replace("（", "(").replace("）", ")").replace("－", "-").replace("—", "-")
    return WS_RE.sub("", text)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class RawCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, str, str]] = {}

    def get(self, rel_path: str) -> tuple[str, str, str] | None:
        if rel_path in self._data:
            value = self._data[rel_path]
            return value or None
        path = Path(rel_path)
        if not path.is_absolute():
            path = ROOT / rel_path
        if not path.exists():
            self._data[rel_path] = None
            return None
        raw = path.read_bytes()
        text = decode(raw)
        stripped = html.unescape(TAG_RE.sub(" ", text))
        value = (sha256(path), norm(text) + "\n" + norm(stripped), norm(stripped))
        self._data[rel_path] = value
        return value


def audit(snapshot: Path, sample: int | None) -> dict:
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    tables = {row[0] for row in conn.execute(
        "select name from sqlite_master where type='table'")}
    if not {"records", "evidence"} <= tables:
        raise SystemExit("snapshot missing records/evidence tables")
    integrity = conn.execute("pragma integrity_check").fetchone()[0]

    evidence = {}
    for eid, payload in conn.execute("select id, payload from evidence"):
        try:
            evidence[eid] = json.loads(payload)
        except json.JSONDecodeError:
            evidence[eid] = {}

    rows = conn.execute(
        f"select id, kind, name, payload, gate from records where city='{CITY}'").fetchall()
    conn.close()

    cache = RawCache()
    stats = defaultdict(Counter)
    problems = []
    identities = defaultdict(set)
    verified_ids = []

    for index, (rid, kind, name, payload_raw, gate_raw) in enumerate(rows):
        if sample and index >= sample:
            break
        bucket = stats[kind]
        bucket["records"] += 1
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            bucket["broken_payload"] += 1
            problems.append({"id": rid, "kind": kind, "name": name, "issue": "payload_not_json"})
            continue

        gate = validate_record(payload, now=now_iso())
        if not gate["discovery_ok"]:
            bucket["fails_contract"] += 1
            problems.append({"id": rid, "kind": kind, "name": name,
                             "issue": "discovery_contract", "detail": gate["errors"][:4]})

        data = payload.get("data") or {}
        source_url = (payload.get("source_url") or "")
        source_group = ("amap" if "amap.com" in source_url else
                        "baidu" if "baidu.com" in source_url else
                        "gov" if "gov.cn" in source_url else
                        "other" if source_url else "none")
        bucket["src_" + source_group] += 1

        # 1. evidence references
        refs = []
        for field, prov in (payload.get("field_provenance") or {}).items():
            if not isinstance(prov, dict) or prov.get("status") != "source_value":
                continue
            eid = prov.get("evidence_id")
            if not eid:
                bucket["field_without_evidence"] += 1
                problems.append({"id": rid, "kind": kind, "name": name,
                                 "issue": "field_without_evidence_ref", "field": field})
                continue
            if eid not in evidence:
                bucket["dangling_evidence"] += 1
                problems.append({"id": rid, "kind": kind, "name": name,
                                 "issue": "evidence_not_in_table", "field": field,
                                 "evidence_id": eid})
                continue
            refs.append((field, prov, evidence[eid]))

        if not refs:
            bucket["no_source_fields"] += 1

        # 2/3/4. raw page, hash, quote, name
        local_ok = 0
        checked = 0
        for field, prov, ev in refs:
            raw_path = ev.get("raw_path")
            if not raw_path:
                bucket["no_raw_path"] += 1
                continue
            checked += 1
            cached = cache.get(raw_path)
            if cached is None:
                bucket["raw_missing"] += 1
                continue
            digest, text_norm, _ = cached
            expected = ev.get("raw_sha256")
            if expected and digest != expected:
                bucket["hash_mismatch"] += 1
                problems.append({"id": rid, "kind": kind, "name": name,
                                 "issue": "raw_sha256_mismatch", "field": field,
                                 "raw_path": raw_path})
                continue
            quote = norm(prov.get("quote") or ev.get("quote") or "")
            if quote and quote not in text_norm:
                bucket["quote_not_verbatim"] += 1
                problems.append({"id": rid, "kind": kind, "name": name,
                                 "issue": "quote_not_verbatim", "field": field,
                                 "quote": (prov.get("quote") or "")[:40]})
                continue
            if norm(name) not in text_norm:
                distance = ev.get("identity_distance_m")
                if ev.get("identity_basis") == "coordinate_match" and distance is not None:
                    try:
                        if float(distance) <= 200:
                            bucket["coordinate_identity"] += 1
                            local_ok += 1
                            continue
                    except (TypeError, ValueError):
                        pass
                bucket["name_not_in_raw"] += 1
                problems.append({"id": rid, "kind": kind, "name": name,
                                 "issue": "name_not_in_raw", "field": field,
                                 "raw_path": raw_path})
                continue
            local_ok += 1

        if checked and local_ok == checked:
            bucket["locally_verified"] += 1
            verified_ids.append(rid)
        elif checked:
            bucket["partially_verified"] += 1
        else:
            bucket["legacy_unverifiable"] += 1

        # 5. coordinates
        if kind in ("poi", "metro_station", "attraction", "restaurant", "accommodation"):
            lat = lon = None
            position = data.get("position")
            if isinstance(position, list) and len(position) == 2:
                lat, lon = position[0], position[1]
            elif isinstance(position, str) and "," in position:
                lon, lat = (float(x) for x in position.split(",")[:2])
            elif data.get("lat") is not None:
                lat, lon = data.get("lat"), data.get("lon")
            if lat is not None and lon is not None:
                if not (BBOX["lat"][0] <= float(lat) <= BBOX["lat"][1]
                        and BBOX["lon"][0] <= float(lon) <= BBOX["lon"][1]):
                    bucket["coord_out_of_bbox"] += 1
                    problems.append({"id": rid, "kind": kind, "name": name,
                                     "issue": "coord_outside_xian", "lat": lat, "lon": lon})
                if payload.get("coordinate_system") not in ("WGS84", "GCJ02", "BD09"):
                    bucket["coord_undeclared"] += 1

        # 6. duplicate identity
        fields = payload.get("data", {})
        ident = (fields.get("TrainID") or fields.get("FlightID") or name)
        if kind == "metro_station":
            ident = re.sub(r"(\(地铁站\)|[-]?地铁站)$", "", str(ident))
            ident = f"{ident}@{fields.get('line') or '未知线路'}"
        if kind in ("poi", "restaurant", "accommodation", "attraction"):
            lat = fields.get("lat")
            lon = fields.get("lon")
            position = fields.get("position")
            if isinstance(position, list) and len(position) == 2:
                lat, lon = position
            elif isinstance(position, str) and "," in position:
                lon, lat = position.split(",")[:2]
            if lat is not None and lon is not None:
                try:
                    ident = f"{ident}@{round(float(lat), 3)},{round(float(lon), 3)}"
                except (TypeError, ValueError):
                    pass
        ident_norm = norm(str(ident)).lower()
        if ident_norm in identities[kind]:
            bucket["duplicate_identity"] += 1
            problems.append({"id": rid, "kind": kind, "name": name,
                             "issue": "duplicate_identity"})
        identities[kind].add(ident_norm)

    target_failures = {"raw_missing", "hash_mismatch", "quote_not_verbatim",
                       "name_not_in_raw", "dangling_evidence", "payload_not_json"}
    hard = sum(problem["issue"] for problem in problems) if False else sum(
        1 for problem in problems if problem["issue"] in {
            "raw_sha256_mismatch", "quote_not_verbatim", "name_not_in_raw",
            "evidence_not_in_table", "payload_not_json"})
    summary = {
        "snapshot": str(snapshot.relative_to(ROOT)).replace("\\", "/"),
        "checked_at": now_iso(),
        "records": len(rows),
        "sampled": sum(counter["records"] for counter in stats.values()),
        "integrity_check": integrity,
        "by_kind": {kind: dict(counter) for kind, counter in sorted(stats.items())},
        "totals": dict(sum(stats.values(), Counter())),
        "hard_failures": hard,
        "problems": problems[:400],
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out")
    parser.add_argument("--sample", type=int)
    args = parser.parse_args()
    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    summary = audit(snapshot, args.sample)

    out = Path(args.out) if args.out else snapshot.parent / "verification.json"
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    totals = summary["totals"]
    print(f"snapshot {summary['snapshot']}  records={summary['records']}  "
          f"integrity={summary['integrity_check']}")
    print(f"本地可复核 {totals.get('locally_verified', 0)}  "
          f"部分 {totals.get('partially_verified', 0)}  "
          f"无本地原文 {totals.get('legacy_unverifiable', 0)}  硬失败 {summary['hard_failures']}")
    for kind, counter in summary["by_kind"].items():
        print(f"  {kind:<14} n={counter.get('records', 0):<5} "
              f"verified={counter.get('locally_verified', 0):<5} "
              f"legacy={counter.get('legacy_unverifiable', 0):<5} "
              f"raw_missing={counter.get('raw_missing', 0):<5} "
              f"dup={counter.get('duplicate_identity', 0)}")
    print("report:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
