"""Ingest verified Xi'an items into a new immutable catalog snapshot.

Every item must carry a locally saved raw page and a verbatim quote. The gate
here refuses anything it cannot re-derive: missing raw file, quote not present
in the raw bytes or the tag-stripped text, or a record that fails
`expansion_contract.validate_record`. Rejected items go to quarantine.jsonl and
are never counted.

Usage:
  python scripts/xian_ingest.py --parent results/<run>/snapshot_vN/catalog.sqlite3 \
      --out results/<run>/snapshot_vM --items results/<run>/staging/b01/items.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.expansion_contract import (  # noqa: E402
    FIELDS, OPTIONAL_VALUES, VERSION, field_policy, parse_time, validate_record,
)

CITY = "西安"
CLASSES = ("attraction", "restaurant", "accommodation")
INGEST_KINDS = tuple(FIELDS.keys())
TRANSPORT = ("poi", "metro_station", "train", "flight")
ID_FIELDS = {"train": "TrainID", "flight": "FlightID"}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def strip_tags(text: str) -> str:
    return html.unescape(TAG_RE.sub(" ", text))


def normalize(text: str) -> str:
    return WS_RE.sub("", text)


def norm_name(name: str) -> str:
    name = (name or "").replace("（", "(").replace("）", ")").replace("－", "-").replace("—", "-")
    return normalize(name).lower()


def clock_or_none(value):
    """Date-only strings are not clocks; they must stay as original text."""
    return value if value and parse_time(value) else None


def coordinate_order(kind: str) -> str:
    return {
        "poi": "latitude,longitude",
        "metro_station": "longitude,latitude",
        "train": "not_applicable",
        "flight": "not_applicable",
    }.get(kind, "named_lat_lon_columns")


def template_record(kind: str) -> dict:
    return {
        "schema_version": VERSION,
        "record_id": None,
        "language": "zh",
        "kind": kind,
        "city": CITY,
        "name": None,
        "source_id": None,
        "source_url": None,
        "source_locator": {},
        "source_published_at": None,
        "source_updated_at": None,
        "observed_at": None,
        "retrieved_at": None,
        "catalogued_at": None,
        "valid_from": None,
        "valid_until": None,
        "field_policies": {},
        "field_provenance": {},
        "authority": "government_published_list",
        "licence_status": "public_official_notice",
        "coordinate_system": "unknown",
        "coordinate_order": coordinate_order(kind),
        "trust_status": "official_listing",
        "entity_verified": False,
        "needs_live_verification": True,
        "uncertainty_flags": [],
        "synthetic": False,
        "tags": [],
        "data": {},
        "proxy_id_policy": "derived_stable_key",
        "scope": {"city": CITY},
        "research_notes": None,
        "field_freshness_notes": "Static page capture; opening hours and prices keep their TTL and are not renewed by this snapshot.",
    }


METRO_SUFFIX = re.compile(r"([（(]地铁站[)）]|[-—－]?地铁站)$")


def canonical_name(kind: str, name: str) -> str:
    if kind == "metro_station":
        return METRO_SUFFIX.sub("", name.strip())
    return name.strip()


def identity(kind: str, name: str, data: dict) -> str:
    key = ID_FIELDS.get(kind)
    value = (data or {}).get(key) if key else None
    return norm_name(str(value or canonical_name(kind, name)))


def existing_keys(conn: sqlite3.Connection, kind: str) -> set[str]:
    keys = set()
    for name, payload in conn.execute(
            f"select name, payload from records where city='{CITY}' and kind=?", (kind,)):
        data = (json.loads(payload).get("data") or {})
        keys.add(identity(kind, name, data))
    return keys


def verify_evidence(item: dict) -> tuple[dict | None, str | None]:
    ev = item.get("evidence") or {}
    raw_path = ev.get("raw_path")
    quote = (ev.get("quote") or "").strip()
    if not raw_path:
        return None, "missing_raw_path"
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / raw_path
    if not path.exists():
        return None, f"raw_not_found:{raw_path}"
    min_len = 2 if quote == item.get("name", "").strip() else 3
    if len(quote) < min_len:
        return None, "quote_too_short"
    raw = path.read_bytes()
    text = decode(raw)
    stripped = strip_tags(text)
    quote_norm = normalize(quote)
    match = None
    if quote_norm and quote_norm in normalize(text):
        match = "raw"
    elif quote_norm and quote_norm in normalize(stripped):
        match = "text_only"
    if match is None:
        return None, "quote_not_verbatim_in_raw"
    return {
        "raw_path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "raw_sha256": sha256_bytes(raw),
        "raw_bytes": len(raw),
        "text_sha256": sha256_bytes(stripped.encode("utf-8")),
        "quote": quote,
        "quote_match": match,
        "locator": ev.get("locator"),
        "_text_norm": normalize(text) + "\n" + normalize(stripped),
    }, None


def build_record(item: dict, evidence: dict, stamp: str) -> dict:
    kind = item["kind"]
    name = item["name"].strip()
    source = item.get("source") or {}
    url = source.get("url") or ""
    record = template_record(kind)
    record_id = "xian:" + hashlib.sha256(
        f"{kind}|{name}|{url}".encode("utf-8")).hexdigest()[:24]
    source_id = "xian-src:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    evidence_id = "xian-evidence:" + hashlib.sha256(
        f"{url}|{evidence['quote']}|{evidence['raw_sha256']}".encode("utf-8")).hexdigest()[:40]

    record.update({
        "record_id": record_id,
        "name": name,
        "source_id": source_id,
        "source_url": url or None,
        "source_locator": {
            "raw_path": evidence["raw_path"],
            "locator": evidence["locator"],
            "quote": evidence["quote"],
            "date_text": source.get("published_at") if not clock_or_none(source.get("published_at")) else None,
        },
        "source_published_at": clock_or_none(source.get("published_at")),
        "source_updated_at": source.get("updated_at"),
        "observed_at": source.get("observed_at"),
        "retrieved_at": stamp,
        "catalogued_at": stamp,
        "authority": source.get("authority") or "government_published_list",
        "licence_status": source.get("licence_status") or "public_official_notice",
        "trust_status": source.get("trust_status") or "official_listing",
        "uncertainty_flags": list(item.get("uncertainty_flags") or []),
        "research_notes": item.get("notes"),
        "coordinate_system": item.get("coordinate_system") or "unknown",
    })

    data = item.get("data") or {}
    required = FIELDS[kind]
    record_data = {}
    policies = {}
    provenance = {}
    for key in required:
        value = data.get(key)
        if key == "name" and not value:
            value = name
        policies[key] = field_policy(key, kind)
        provenance[key] = {
            "source_id": None, "source_url": None, "observed_at": None,
            "status": "unknown", "evidence_id": None, "quote": None, "valid_until": None,
        }
        record_data[key] = None
        if value is not None and value != "":
            record_data[key] = value
            provenance[key] = {
                "source_id": source_id,
                "source_url": url or None,
                "observed_at": source.get("observed_at"),
                "status": "source_value",
                "evidence_id": evidence_id,
                "quote": evidence["quote"],
                "valid_until": None,
            }
    record["data"] = record_data
    record["field_policies"] = policies
    record["field_provenance"] = provenance
    return {"record": record, "evidence_id": evidence_id, "evidence": evidence,
            "source_id": source_id}


def evidence_payload(evidence_id: str, item: dict, evidence: dict, stamp: str) -> dict:
    source = item.get("source") or {}
    return {
        "evidence_id": evidence_id,
        "source_url": source.get("url"),
        "publisher": source.get("publisher"),
        "authority": source.get("authority") or "government_published_list",
        "licence_status": source.get("licence_status") or "public_official_notice",
        "raw_path": evidence["raw_path"],
        "raw_sha256": evidence["raw_sha256"],
        "raw_bytes": evidence["raw_bytes"],
        "text_sha256": evidence["text_sha256"],
        "quote": evidence["quote"],
        "quote_match": evidence["quote_match"],
        "locator": evidence["locator"],
        "captured_at": stamp,
        "source_published_at": clock_or_none(source.get("published_at")),
        "source_published_text": source.get("published_at") if not clock_or_none(source.get("published_at")) else None,
        "observed_at": source.get("observed_at"),
        "identity_basis": (item.get("evidence") or {}).get("identity_basis") or "name",
        "identity_distance_m": (item.get("evidence") or {}).get("identity_distance_m"),
        "matched_name": (item.get("evidence") or {}).get("matched_name"),
        "truth_certified": False,
        "entity_verified": False,
    }


def apply_enrichment(conn: sqlite3.Connection, rows: list[dict], stamp: str) -> dict:
    """Fill only null fields on existing records; never overwrite a known value."""
    applied, skipped = [], []
    for row in rows:
        kind = row.get("kind")
        name = (row.get("name") or "").strip()
        if kind not in INGEST_KINDS or not name:
            skipped.append({"name": name, "reason": "bad_key"})
            continue
        hit = conn.execute(
            f"select id, payload from records where city='{CITY}' and kind=? and name=?",
            (kind, name)).fetchone()
        if hit is None:
            skipped.append({"name": name, "reason": "not_found"})
            continue
        record_id, payload_raw = hit
        payload = json.loads(payload_raw)
        evidence, reason = verify_evidence(row)
        if evidence is None:
            skipped.append({"name": name, "reason": reason})
            continue
        evidence.pop("_text_norm", None)
        data = row.get("data") or {}
        source = row.get("source") or {}
        url = source.get("url") or ""
        source_id = "xian-src:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        evidence_id = "xian-evidence:" + hashlib.sha256(
            f"{url}|{evidence['quote']}|{evidence['raw_sha256']}".encode("utf-8")).hexdigest()[:40]
        changed = []
        for key, value in data.items():
            if key not in FIELDS[kind] or value in (None, ""):
                continue
            current = (payload.setdefault("data", {})).get(key)
            if current not in (None, ""):
                skipped.append({"name": name, "field": key, "reason": "already_known"})
                continue
            payload["data"][key] = value
            payload.setdefault("field_policies", {})[key] = field_policy(key, kind)
            payload.setdefault("field_provenance", {})[key] = {
                "source_id": source_id,
                "source_url": url or None,
                "observed_at": source.get("observed_at"),
                "status": "source_value",
                "evidence_id": evidence_id,
                "quote": evidence["quote"],
                "valid_until": None,
            }
            changed.append(key)
        if not changed:
            continue
        gate = validate_record(payload, now=stamp)
        conn.execute(
            "update records set payload=?, gate=?, planning_ready=? where id=?",
            (json.dumps(payload, ensure_ascii=False), json.dumps(gate, ensure_ascii=False),
             1 if gate["planning_ready"] else 0, record_id))
        conn.execute("insert or replace into evidence (id, payload) values (?,?)", (
            evidence_id, json.dumps(evidence_payload(evidence_id, row, evidence, stamp),
                                    ensure_ascii=False)))
        applied.append({"name": name, "record_id": record_id, "fields": changed})
    return {"applied": applied, "skipped": skipped}


def transport_counts(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute(
        f"select kind, count(*) from records where city='{CITY}' and kind in "
        f"({','.join('?' * len(TRANSPORT))}) group by kind", TRANSPORT).fetchall())


def counts(conn: sqlite3.Connection) -> dict:
    out = {}
    for kind in CLASSES:
        rows = [json.loads(p) for p, in conn.execute(
            f"select payload from records where city='{CITY}' and kind=?", (kind,))]
        gaps = [json.loads(g) for g, in conn.execute(
            f"select gate from records where city='{CITY}' and kind=?", (kind,))]
        out[kind] = {
            "n": len(rows),
            "discovery_ok": sum(1 for gap in gaps if gap.get("discovery_ok")),
            "planning_ready": sum(1 for gap in gaps if gap.get("planning_ready")),
            "native_complete": sum(
                1 for payload in rows
                if all((payload.get("data") or {}).get(key) not in (None, "")
                       for key in FIELDS.get(payload.get("kind"), ())
                       if key not in OPTIONAL_VALUES)
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--items", required=True)
    parser.add_argument("--enrich", default=None,
                        help="jsonl of field upgrades for existing records (null fields only)")
    parser.add_argument("--label", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    parent = Path(args.parent)
    if not parent.is_absolute():
        parent = ROOT / parent
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    items_path = Path(args.items)
    if not items_path.is_absolute():
        items_path = ROOT / items_path
    if out_dir.exists() and not args.dry_run:
        raise SystemExit(f"refusing to overwrite existing snapshot: {out_dir}")

    stamp = now_iso()
    parent_hash = sha256_bytes(parent.read_bytes())
    conn = sqlite3.connect(parent.resolve().as_uri() + "?mode=ro", uri=True)
    known = {kind: existing_keys(conn, kind) for kind in INGEST_KINDS}
    conn.close()

    accepted, rejected = [], []
    for line_no, line in enumerate(items_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            rejected.append({"line": line_no, "reason": f"bad_json:{exc}"})
            continue
        kind = item.get("kind")
        name = (item.get("name") or "").strip()
        if kind not in INGEST_KINDS:
            rejected.append({"line": line_no, "name": name, "reason": "kind_not_ingestible"})
            continue
        if not name:
            rejected.append({"line": line_no, "reason": "missing_name"})
            continue
        aliases = [norm_name(a) for a in (item.get("aliases") or []) if a]
        key = identity(kind, name, item.get("data") or {})
        if key in known[kind] or any(a in known[kind] for a in aliases):
            rejected.append({"line": line_no, "name": name, "reason": "duplicate_name"})
            continue
        evidence, reason = verify_evidence(item)
        if evidence is None:
            rejected.append({"line": line_no, "name": name, "reason": reason})
            continue
        if norm_name(name) not in evidence.pop("_text_norm").lower():
            rejected.append({"line": line_no, "name": name, "reason": "name_not_in_raw"})
            continue
        built = build_record(item, evidence, stamp)
        gate = validate_record(built["record"], now=stamp)
        if not gate["discovery_ok"]:
            rejected.append({"line": line_no, "name": name,
                             "reason": "validate_record", "errors": gate["errors"][:6]})
            continue
        known[kind].add(key)
        for alias in aliases:
            known[kind].add(alias)
        accepted.append({**built, "gate": gate, "item": item})

    summary = {
        "parent": str(parent.relative_to(ROOT)).replace("\\", "/"),
        "parent_sha256": parent_hash,
        "items": str(items_path.relative_to(ROOT)).replace("\\", "/"),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "by_kind": {kind: sum(1 for a in accepted if a["record"]["kind"] == kind)
                    for kind in INGEST_KINDS},
        "dry_run": args.dry_run,
        "ingested_at": stamp,
    }
    if args.dry_run:
        print(json.dumps({**summary, "rejected_detail": rejected[:20]},
                         ensure_ascii=False, indent=1))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    target_db = out_dir / "catalog.sqlite3"
    shutil.copy2(parent, target_db)

    conn = sqlite3.connect(target_db)
    for entry in accepted:
        record = entry["record"]
        conn.execute(
            "insert into records (id, kind, city, name, provider_city_match, planning_ready, payload, gate)"
            " values (?,?,?,?,?,?,?,?)",
            (
                record["record_id"], record["kind"], CITY, record["name"],
                1 if (entry["item"].get("data") or {}).get("district") else 0,
                1 if entry["gate"]["planning_ready"] else 0,
                json.dumps(record, ensure_ascii=False),
                json.dumps(entry["gate"], ensure_ascii=False),
            ),
        )
        conn.execute("insert into evidence (id, payload) values (?,?)", (
            entry["evidence_id"],
            json.dumps(evidence_payload(entry["evidence_id"], entry["item"],
                                        entry["evidence"], stamp), ensure_ascii=False),
        ))
    conn.commit()
    enrichment = {"applied": [], "skipped": []}
    if args.enrich:
        enrich_path = Path(args.enrich)
        if not enrich_path.is_absolute():
            enrich_path = ROOT / args.enrich
        rows = [json.loads(line) for line in
                enrich_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        enrichment = apply_enrichment(conn, rows, stamp)
        conn.commit()
    integrity = conn.execute("pragma integrity_check").fetchone()[0]
    post = counts(conn)
    transport = transport_counts(conn)
    total = conn.execute("select count(*) from records").fetchone()[0]
    conn.close()

    manifest = {
        "snapshot": out_dir.name,
        "derived_from": f"{Path(summary['parent']).parent.name} (immutable, unchanged)",
        "parent": summary["parent"],
        "parent_sha256": parent_hash,
        "catalog_sha256": sha256_bytes(target_db.read_bytes()),
        "sqlite_integrity_check": integrity,
        "record_count": total,
        "xian_by_kind": post,
        "transport_by_kind": transport,
        "ingested": {
            "items": summary["items"],
            "accepted": len(accepted),
            "by_kind": summary["by_kind"],
            "label": args.label,
        },
        "enrichment": {
            "applied": len(enrichment["applied"]),
            "fields": sum(len(a["fields"]) for a in enrichment["applied"]),
            "skipped": len(enrichment["skipped"]),
        },
        "categories": {
            "new_facts_or_entities": f"{len(accepted)} rows with raw page + verbatim quote re-checked at ingest",
            "engineering_envelope_repair": "none in this snapshot",
            "quarantined": f"{len(rejected)} items rejected, see quarantine.jsonl",
        },
        "ingested_at": stamp,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with open(out_dir / "quarantine.jsonl", "w", encoding="utf-8") as handle:
        for row in rejected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "ingest_report.json").write_text(json.dumps(
        {**summary, "rejected_detail": rejected, "xian_by_kind": post,
         "enrichment": enrichment},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if integrity != "ok":
        raise SystemExit(f"integrity check failed: {integrity}")
    print(json.dumps({**summary, "xian_by_kind": post,
                      "enrichment": {"applied": len(enrichment["applied"]),
                                     "fields": sum(len(a["fields"]) for a in enrichment["applied"]),
                                     "skipped": len(enrichment["skipped"])},
                      "catalog_sha256": manifest["catalog_sha256"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
