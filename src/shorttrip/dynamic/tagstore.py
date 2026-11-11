"""Versioned TAG store (SQLite), separate from the sandbox overlay.

Same discipline as ``dynamic/overlay.py``: the ChinaTravel sandbox CSVs are never
touched, tags live in their own versioned table, and a plan records the
``tag_snapshot_id`` it was ranked against so a run can be replayed.

Primary key is ``tag_uid = sha1(local_poi_id|tag_id|source|evidence_id|context|schema)``
so a re-fetch of the same evidence updates in place instead of duplicating, while a
genuinely different observation (new context, new source) is a new row.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..tags import TagEvidence

SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    tag_uid TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    local_poi_id TEXT NOT NULL,
    city TEXT,
    poi_name TEXT,
    tag_id TEXT NOT NULL,
    tag_group TEXT,
    value TEXT,
    value_type TEXT,
    polarity TEXT,
    evidence_kind TEXT,
    status TEXT,
    confidence REAL,
    context TEXT,
    source_name TEXT,
    source_url TEXT,
    evidence_id TEXT,
    excerpt TEXT,
    raw_digest TEXT,
    licence_status TEXT,
    observed_at TEXT,
    retrieved_at TEXT,
    valid_until TEXT,
    gates TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tags_poi ON tags(local_poi_id);
CREATE INDEX IF NOT EXISTS idx_tags_snapshot ON tags(snapshot_id);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    note TEXT,
    n_records INTEGER NOT NULL,
    n_accept INTEGER NOT NULL,
    n_quarantine INTEGER NOT NULL,
    n_reject INTEGER NOT NULL,
    extractor_version TEXT,
    schema_version INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TagStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ write
    def add_many(self, records: list[TagEvidence], *, note: str = "",
                 snapshot_id: str | None = None) -> str:
        snapshot = snapshot_id or f"tag-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        # Second-resolution ids collide when two collectors run back to back (observed:
        # the P2 and P5 runs landed in the same second and silently shared a snapshot).
        if self.conn.execute("SELECT 1 FROM snapshots WHERE snapshot_id=?", (snapshot,)).fetchone():
            suffix = 1
            while self.conn.execute("SELECT 1 FROM snapshots WHERE snapshot_id=?",
                                    (f"{snapshot}-{suffix}",)).fetchone():
                suffix += 1
            snapshot = f"{snapshot}-{suffix}"
        counts = {"accept": 0, "quarantine": 0, "reject": 0}
        for record in records:
            payload = record.to_dict()
            counts[record.status] = counts.get(record.status, 0) + 1
            self.conn.execute(
                """INSERT OR REPLACE INTO tags VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.tag_uid, snapshot, record.local_poi_id, record.city, record.poi_name,
                    record.tag_id, record.group, json.dumps(record.value, ensure_ascii=False),
                    record.value_type, record.polarity, record.evidence_kind, record.status,
                    float(record.confidence), json.dumps(record.context, ensure_ascii=False),
                    record.source_name, record.source_url, record.evidence_id, record.excerpt,
                    record.raw_digest, record.licence_status, record.observed_at,
                    record.retrieved_at, record.valid_until,
                    json.dumps({k: bool(v) for k, v in (record.gates or {}).items()}, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False), _now(),
                ),
            )
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)",
            (snapshot, _now(), note, len(records), counts["accept"], counts["quarantine"],
             counts["reject"], records[0].model_version if records else "", records[0].schema_version if records else 0),
        )
        self.conn.commit()
        return snapshot

    # ------------------------------------------------------------------- read
    def latest_snapshot(self) -> str | None:
        row = self.conn.execute(
            "SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def payloads(self, snapshot_id: str | None = None, status: str | None = "accept") -> list[dict]:
        query = "SELECT payload FROM tags"
        clauses, params = [], []
        if snapshot_id:
            clauses.append("snapshot_id=?")
            params.append(snapshot_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return [json.loads(row[0]) for row in self.conn.execute(query, params).fetchall()]

    def by_poi(self, snapshot_id: str | None = None, status: str = "accept") -> dict[str, dict]:
        """``{local_poi_id: {tag_id: payload}}``, best-confidence row per tag wins."""
        out: dict[str, dict] = {}
        for payload in self.payloads(snapshot_id, status):
            poi = payload["local_poi_id"]
            tag = payload["tag_id"]
            bucket = out.setdefault(poi, {})
            current = bucket.get(tag)
            if current is None or float(payload.get("confidence") or 0) > float(current.get("confidence") or 0):
                bucket[tag] = payload
        return out

    def counts(self) -> dict:
        rows = self.conn.execute("SELECT status, COUNT(*) FROM tags GROUP BY status").fetchall()
        return {row[0]: row[1] for row in rows} | {
            "pois": self.conn.execute("SELECT COUNT(DISTINCT local_poi_id) FROM tags").fetchone()[0],
            "snapshots": self.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        }

    def snapshot_info(self, snapshot_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        return {"snapshot_id": row[0], "created_at": row[1], "note": row[2], "n_records": row[3],
                "n_accept": row[4], "n_quarantine": row[5], "n_reject": row[6],
                "extractor_version": row[7], "schema_version": row[8]}

    def conflicts(self, snapshot_id: str | None = None) -> list[dict]:
        """POI+tag pairs where accepted evidence disagrees — reported, not averaged."""
        out: list[dict] = []
        grouped: dict[tuple[str, str], list[dict]] = {}
        for payload in self.payloads(snapshot_id, status=None):
            if payload.get("status") == "reject":
                continue
            grouped.setdefault((payload["local_poi_id"], payload["tag_id"]), []).append(payload)
        for (poi, tag), rows in grouped.items():
            values = {json.dumps(row.get("value"), ensure_ascii=False) for row in rows}
            if len(values) > 1:
                out.append({
                    "local_poi_id": poi, "tag_id": tag,
                    "values": sorted(values),
                    "sources": sorted({row.get("source_name") for row in rows}),
                    "evidence_kinds": sorted({row.get("evidence_kind") for row in rows}),
                })
        return out

    def summary(self) -> dict:
        return {"path": str(self.path), "counts": self.counts()}
