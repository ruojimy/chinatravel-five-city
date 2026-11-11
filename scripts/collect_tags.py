"""Collect visitor-experience TAGs for the sample POIs and run the T1-T8 gates.

Default is ``replay``: it uses the Baidu responses captured on 2026-10-21 and
spends no quota. ``--live`` is the only way to hit the network, and it refuses to
run when ``BAIDU_OFFLINE=1``.

Outputs:
  data/tag_store.sqlite                     versioned TAG store (accept/quarantine/reject)
  results/tags/collect_report.json          per-POI outcome, gate pass rates, phrase coverage
  results/tags/tag_records_audit.json       every record with its gates, for manual review
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.baidu import BaiduSource, get_client, self_test  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.tags import (  # noqa: E402
    describe,
    extract_attribute_tags,
    extract_experience_tags,
    gate_all,
)

SAMPLE = ROOT / "datasets" / "tag_sample" / "pois.json"
STORE = ROOT / "data" / "tag_store.sqlite"
OUT = ROOT / "results" / "tags"


def main() -> int:
    mode = "live" if "--live" in sys.argv else "replay"
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    pois = sample["pois"]
    client = get_client(mode)
    source = BaiduSource(client)
    print(f"mode={mode} pois={len(pois)} signature_self_test={self_test()['ok']}")

    records = []
    raw_index: dict[str, str] = {}
    identity_index: dict[str, dict] = {}
    per_poi: list[dict] = []
    phrase_reports: dict[str, dict] = {}

    for poi in pois:
        evidence = source.fetch(poi["name"], poi["city"], anchor=(poi["lat"], poi["lon"]))
        data = evidence.structured or {}
        entry = {
            "local_poi_id": poi["local_poi_id"],
            "city": poi["city"],
            "name": poi["name"],
            "ok": evidence.ok,
            "error": evidence.error,
            "evidence_chars": len(evidence.text or ""),
        }
        if not evidence.ok:
            per_poi.append(entry)
            continue
        entry.update({
            "chosen_name": data.get("name"),
            "identity_rule": data.get("identity_rule"),
            "candidate_score": data.get("candidate_score"),
            "n_content_tags": len(data.get("content_tags") or []),
            "replayed": bool(data.get("cached")),
        })
        raw_index[poi["local_poi_id"]] = evidence.text or ""
        identity_index[poi["local_poi_id"]] = {
            "match": bool(data.get("name_match")),
            "rule": data.get("identity_rule"),
            "score": data.get("candidate_score"),
        }
        attributes = extract_attribute_tags(
            data, city=poi["city"], poi_name=poi["name"], raw_text=evidence.text or "",
            source_url=evidence.url, retrieved_at=evidence.retrieved_at,
        )
        experiences, coverage = extract_experience_tags(
            data, city=poi["city"], poi_name=poi["name"], raw_text=evidence.text or "",
            source_url=evidence.url, retrieved_at=evidence.retrieved_at,
        )
        phrase_reports[poi["local_poi_id"]] = coverage
        records.extend(attributes)
        records.extend(experiences)
        entry.update({"n_attribute_tags": len(attributes), "n_experience_tags": len(experiences),
                      "phrase_coverage": coverage["coverage_rate"],
                      "unmapped_phrases": coverage["unmapped_phrases"]})
        per_poi.append(entry)
        print(f"  {poi['city']:3s} {poi['name'][:18]:20s} ok attrs={len(attributes):2d} "
              f"exp={len(experiences):2d} cov={coverage['coverage_rate']}")

    gated = gate_all(records, raw_index=raw_index, identity_index=identity_index)

    store = TagStore(STORE)
    snapshot = store.add_many([record for record, _ in gated],
                              note=f"collect_tags mode={mode} pois={len(pois)}")

    decision_counts = Counter(verdict.decision for _, verdict in gated)
    gate_pass: dict[str, dict] = {}
    for _, verdict in gated:
        for name, item in verdict.gates.items():
            bucket = gate_pass.setdefault(name, {"pass": 0, "fail": 0, "hard": item["hard"]})
            bucket["pass" if item["passed"] else "fail"] += 1

    by_tag = Counter(record.tag_id for record, verdict in gated if verdict.decision == "accept")
    by_kind = Counter(record.evidence_kind for record, verdict in gated if verdict.decision == "accept")
    unmapped_all = [phrase for report in phrase_reports.values() for phrase in report["unmapped_phrases"]]

    report = {
        "mode": mode,
        "generated_at": "2026-10-21",
        "signature_self_test": self_test()["ok"],
        "quota_policy": "replay 优先；live 需显式 --live 且 BAIDU_OFFLINE!=1",
        "sample": {"n": len(pois), "cities": sample["cities"], "source": str(SAMPLE.relative_to(ROOT))},
        "evidence": {
            "pois_attempted": len(pois),
            "pois_with_evidence": sum(1 for entry in per_poi if entry["ok"]),
            "pois_without_evidence": sum(1 for entry in per_poi if not entry["ok"]),
            "pois_with_experience_tags": sum(1 for entry in per_poi if entry.get("n_experience_tags")),
            "coverage_of_sample": round(sum(1 for e in per_poi if e.get("n_experience_tags")) / len(pois), 3),
        },
        "records": {
            "total": len(gated),
            "by_decision": dict(decision_counts),
            "by_evidence_kind": dict(by_kind),
            "accepted_by_tag": dict(by_tag),
        },
        "gates": gate_pass,
        "phrase_mapping": {
            "unmapped_phrases": sorted(set(unmapped_all)),
            "n_unmapped": len(set(unmapped_all)),
            "per_poi": phrase_reports,
        },
        "tag_dictionary": describe(),
        "per_poi": per_poi,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "collect_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "tag_records_audit.json").write_text(
        json.dumps([{"record": record.to_dict(), "verdict": verdict.to_dict()} for record, verdict in gated],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"snapshot": snapshot, "decisions": dict(decision_counts),
                      "evidence": report["evidence"], "store": store.counts()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
