"""P2: build the open-data TAG layer from the P1 matches and run gates T1-T6.

Input : results/p1/poi_mapping.json   (50 POIs matched against OSM + Wikidata)
Output: data/tag_store.sqlite         new snapshot (open-data only)
        results/p2/tag_records.json   every record with its gate verdict
        results/p2/tag_summary.json   counts by evidence class / tag / licence

Verification: excerpts are re-checked against the **cached raw provider payloads**
(the same URLs the P1 run fetched, served from data/open_data_cache), so gate T2 is
a real test and not a self-reference.

Honest limit: no VISITOR_EXPERIENCE record exists because no licensed review corpus
was obtained. `crowding_report`, `queue_report` and `price_satisfaction` stay empty.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import (  # noqa: E402
    NominatimOsmSource,
    WikidataSource,
    match_identity,
    type_to_tags,
)
from shorttrip.dynamic.tagbuild import wikidata_records, osm_records  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.tags import EVIDENCE_CLASSES, gate_tag_v2  # noqa: E402

MAPPING = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "results" / "p1" / "poi_mapping.json")
OUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else ROOT / "results" / "p2"
STORE = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "tag_store.sqlite"


def main() -> int:
    payload = json.loads(MAPPING.read_text(encoding="utf-8"))
    rows = payload["rows"]
    osm = NominatimOsmSource()
    wikidata = WikidataSource()

    # ---- reload the raw provider payloads from cache so T2 is a real check
    # `tags` is re-attached from the live hit: a mapping file produced by the matcher
    # evaluation does not carry the OSM tag payload, only the reference.
    raw_osm: dict[str, dict] = {}
    for row in rows:
        if not (row.get("osm") or {}).get("match"):
            continue
        result = osm.lookup(row["name"], row["city"], anchor_gcj=tuple(row["sandbox_xy"]))
        for hit in result.get("hits") or []:
            if hit.osm_type == row["osm"].get("osm_type") and hit.osm_id == int(row["osm"].get("osm_id") or 0):
                raw_osm[row["local_poi_id"]] = hit.raw
                row.setdefault("osm", {})["tags"] = hit.tags
                row["osm"]["display_name"] = hit.display_name
                row["osm"]["importance"] = hit.importance
                row["osm"]["distance_km"] = hit.distance_km
                break

    accepted_qids = [row["wikidata"]["qid_accepted"] for row in rows
                     if row["wikidata"].get("qid_accepted")]
    raw_wd = wikidata.entities_by_ids(accepted_qids)
    type_qids = []
    for entity in raw_wd.values():
        claims = entity.get("claims") or {}
        for statement in claims.get("P31", []):
            value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                type_qids.append(value["id"])
    type_labels = wikidata.type_labels(type_qids)
    mapped_types = type_to_tags(type_labels)

    print(f"raw payloads: osm={len(raw_osm)} wikidata={len(raw_wd)} | P31 types={len(type_labels)}")

    records = []
    for row in rows:
        poi_id = row["local_poi_id"]
        if poi_id in raw_osm:
            records.extend(osm_records(row, raw_osm[poi_id]))
        qid = row["wikidata"].get("qid_accepted")
        if qid and qid in raw_wd:
            records.extend(wikidata_records(row, raw_wd[qid], type_labels, mapped_types))

    # ---- gates
    identity_index = {
        row["local_poi_id"]: {"match": bool(row["wikidata"].get("qid_accepted") or row["osm"]["match"]),
                              "rule": (row["osm"].get("rule") if row["osm"]["match"] else
                                       row["wikidata"].get("match_rule")),
                              "score": row["wikidata"].get("distance_km") or row["osm"].get("distance_km")}
        for row in rows
    }
    raw_index = {}
    for row in rows:
        poi_id = row["local_poi_id"]
        blob = {}
        if poi_id in raw_osm:
            blob["osm"] = raw_osm[poi_id]
        qid = row["wikidata"].get("qid_accepted")
        if qid and qid in raw_wd:
            blob["wikidata"] = raw_wd[qid]
        if blob:
            raw_index[poi_id] = json.dumps(blob, ensure_ascii=False)

    conflicts: dict = {}
    gated = []
    for record in records:
        verdict = gate_tag_v2(record, raw_text=raw_index.get(record.local_poi_id),
                              identity=identity_index.get(record.local_poi_id),
                              conflicts=conflicts)
        record.status = verdict.decision
        record.confidence = verdict.confidence
        record.gates = {name: gate["passed"] for name, gate in verdict.gates.items()}
        record.evidence_class = record.resolved_evidence_class()
        gated.append((record, verdict))

    store = TagStore(STORE)
    snapshot = store.add_many([record for record, _ in gated],
                              note=f"P2 open-data TAG layer (OSM ODbL + Wikidata CC0) [{Path(MAPPING).stem}]")

    # ---- report
    decisions = Counter(verdict.decision for _, verdict in gated)
    by_class = Counter(record.resolved_evidence_class() for record, verdict in gated
                       if verdict.decision == "accept")
    by_tag = Counter(record.tag_id for record, verdict in gated if verdict.decision == "accept")
    by_licence = Counter(record.licence_status for record, verdict in gated if verdict.decision == "accept")
    by_source = Counter(record.source_name for record, verdict in gated if verdict.decision == "accept")
    pois_with_accept = {record.local_poi_id for record, verdict in gated if verdict.decision == "accept"}
    gate_stats: dict[str, dict] = {}
    for _, verdict in gated:
        for name, gate in verdict.gates.items():
            bucket = gate_stats.setdefault(name, {"pass": 0, "fail": 0, "hard": gate["hard"]})
            bucket["pass" if gate["passed"] else "fail"] += 1

    summary = {
        "generated_at": "2026-10-21",
        "pipeline": "P2 open-data TAG layer",
        "baidu_request_budget": 0,
        "input": {"mapping": str(MAPPING.relative_to(ROOT)), "pois": len(rows)},
        "records": {"total": len(gated), "by_decision": dict(decisions),
                    "accepted_by_evidence_class": dict(by_class),
                    "accepted_by_tag": dict(by_tag),
                    "accepted_by_licence": dict(by_licence),
                    "accepted_by_source": dict(by_source),
                    "distinct_pois_with_accepted": len(pois_with_accept)},
        "gates": gate_stats,
        "evidence_classes_required": list(EVIDENCE_CLASSES),
        "not_executable": {
            "VISITOR_EXPERIENCE": "无可授权评论语料，未取得许可；不使用模型生成评论代替",
            "crowding_report / queue_report / price_satisfaction":
                "依赖游客反馈，当前证据为空；B2 实验组标注为不可执行",
        },
        "snapshot": snapshot,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tag_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    (OUT / "tag_records.json").write_text(
        json.dumps([{"record": record.to_dict(), "verdict": verdict.to_dict()}
                    for record, verdict in gated], ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(json.dumps(summary["records"], ensure_ascii=False, indent=2))
    print("gates:", json.dumps(gate_stats, ensure_ascii=False))
    print(f"snapshot={snapshot} store={store.counts()}")
    print(f"wrote {OUT / 'tag_summary.json'}")
    return 0 if len(pois_with_accept) >= 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
