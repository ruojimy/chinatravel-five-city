"""Recompute field support and its frozen-corpus ceiling; no new model/API calls."""
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.retrieval_benchmark import assess_evidence, target_key


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    source = ROOT / "results/p24_dynamic_feedback"
    out = ROOT / "results/p26_dataset_diagnosis"
    out.mkdir(exist_ok=True)
    queries = read(source / "private/queries_96.json")
    corpus = read(source / "private/evidence_corpus.json")
    evaluations = {(e["level"], e["uid"]): e for e in read(source / "evaluations/all_96.json")}
    fields = collections.defaultdict(collections.Counter)
    levels = collections.defaultdict(collections.Counter)
    cases = []
    for q in queries:
        evaluation = evaluations[q["level"], q["uid"]]
        upper = used = 0
        unavailable = []
        for r in q["requirements"]:
            f = fields[r["field"]]
            f["required"] += 1
            matching = [e for e in corpus["evidence"] if assess_evidence(e, r, corpus["captured_at"])["usable"]]
            can_support = bool(matching)
            level = evaluation["dynamic"]["resolved_levels"].get(target_key(r["target_id"], r["field"]))
            actually_supported = can_support and any(e["level"] == level for e in matching)
            f["corpus_ceiling"] += can_support
            f["actual_supported"] += actually_supported
            if actually_supported:
                f["supported_as:" + level] += 1
            upper += can_support
            used += actually_supported
            if not can_support:
                unavailable.append(r["field"])
        cases.append({"level": q["level"], "uid": q["uid"], "required": len(q["requirements"]),
                      "corpus_ceiling": upper, "actual_supported": used,
                      "complete_possible_with_corpus": upper == len(q["requirements"]),
                      "unavailable_fields": unavailable})
        l = levels[q["level"]]
        l["cases"] += 1
        l["required"] += len(q["requirements"])
        l["corpus_ceiling"] += upper
        l["actual_supported"] += used
        l["complete_possible_cases"] += upper == len(q["requirements"])
    summary = read(source / "summary.json")
    required = sum(c["required"] for c in cases)
    ceiling = sum(c["corpus_ceiling"] for c in cases)
    actual = sum(c["actual_supported"] for c in cases)
    checks = {
        "unique_level_uid": len(evaluations) == len(cases) == 96,
        "required_matches_original": required == summary["total"]["dynamic"]["metrics"]["required_fields"],
        "support_matches_original": actual == summary["total"]["dynamic"]["metrics"]["resolved_fields"],
        "support_within_ceiling": actual <= ceiling <= required,
    }
    report = {"scope": "P24 captured corpus at original frozen clock; P24 permissive reference/estimate assessment, not P25 strict verified completion or live freshness",
              "required": required, "corpus_ceiling": ceiling, "actual_supported": actual,
              "complete_possible_cases": sum(c["complete_possible_with_corpus"] for c in cases),
              "fields": dict(fields), "levels": dict(levels), "cases": cases, "checks": checks}
    (out / "schema_support_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    rows = [{"field": k, **v} for k,v in sorted(fields.items())]
    with (out / "schema_support_by_field.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, sorted({k for row in rows for k in row}))
        w.writeheader(); w.writerows(rows)
    print(json.dumps({k:v for k,v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    assert all(checks.values()), checks


if __name__ == "__main__":
    main()
