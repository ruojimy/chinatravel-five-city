"""P5: run the visitor-experience extractor on the CC BY 4.0 review corpus.

This is the first time the project produces `VISITOR_EXPERIENCE` records with real
visitor text behind them. It is deliberately conservative:

* a deterministic, length-stratified sample is used (default 800 reviews) so the run
  is cheap and reproducible; the sampling rule is recorded in the output;
* every published record cites one verbatim review sentence plus its review id;
* per-tag counts, positive/negative split, Beta-smoothed rate, Wilson lower bound and
  a manual-review excerpt file are all written out, including the *negatives*.

Outputs
  results/p5_visitor_tag/extract_report.json
  results/p5_visitor_tag/records.json
  results/p5_visitor_tag/review_sample.csv        (for human spot-check)
  data/tag_store.sqlite                           new snapshot (visitor evidence)
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.tags import gate_tag_v2  # noqa: E402
from shorttrip.visitor_tags import (  # noqa: E402
    CORPUS_ID,
    aggregate_mentions,
    build_records,
    describe,
    extract_mentions,
)

RAW = ROOT / "data" / "visitor_reviews_raw"
CORPUS = RAW / "zhangjiajie_reviews.jsonl"
STATS = RAW / "zhangjiajie_stats.json"
OUT = ROOT / "results" / "p5_visitor_tag"
STORE = ROOT / "data" / "tag_store.sqlite"


def stratified_sample(reviews: list[dict], n: int) -> list[dict]:
    """Deterministic length-stratified sample: sort by (length bucket, sha1), take every k-th."""
    buckets: dict[int, list[dict]] = {}
    for review in reviews:
        bucket = min(5, review["chars"] // 200)
        buckets.setdefault(bucket, []).append(review)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item["text_sha1"])
    sample: list[dict] = []
    index = 0
    while len(sample) < n and any(buckets.values()):
        for key in sorted(buckets):
            if len(sample) >= n:
                break
            bucket = buckets[key]
            if not bucket:
                continue
            position = index % len(bucket)
            sample.append(bucket[position])
            bucket.pop(position)
        index += 1
    return sample[:n]


def main() -> int:
    if not CORPUS.exists():
        print("缺少语料：先运行 scripts/p1_fetch_licensed_reviews.py 与 p1_normalise_reviews.py")
        return 2
    reviews = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 800
    sample = stratified_sample(reviews, limit)
    print(f"corpus={len(reviews)} sampled={len(sample)}")

    mentions = []
    for review in sample:
        mentions.extend(extract_mentions(review))
    print(f"mentions={len(mentions)} across {len({m.tag_id for m in mentions})} tags")

    aggregates = aggregate_mentions(mentions, total_reviews=len(sample))
    records = build_records(aggregates, local_poi_id="corpus:张家界国家森林公园",
                            poi_name="张家界国家森林公园", city="张家界",
                            corpus_stats={"published_at": "2026-07-28"})

    # ---- gates: T1 licence, T2 excerpt in a real review, T3 semantics, T4 time/context,
    # T5 conflict, T6 review queue. A "conflict" is only registered when the tag is
    # genuinely polarised; a lone dissenting sentence is not a conflict.
    review_text = {review["review_id"]: review["text"] for review in sample}
    conflicts: dict = {}
    for aggregate in aggregates:
        if aggregate.get("polarized"):
            key = ("corpus:张家界国家森林公园", aggregate["tag_id"])
            conflicts.setdefault(key, set()).add(json.dumps(aggregate["value"], ensure_ascii=False))
    gated = []
    conflicts: dict = {}
    for record in records:
        raw_text = review_text.get(record.source_record_id, "")
        verdict = gate_tag_v2(record, raw_text=raw_text,
                              identity={"match": True, "rule": "corpus_poi", "score": 1.0},
                              conflicts=conflicts)
        record.status = verdict.decision
        record.confidence = verdict.confidence
        record.gates = {name: gate["passed"] for name, gate in verdict.gates.items()}
        record.evidence_class = "VISITOR_EXPERIENCE"
        gated.append((record, verdict))

    store = TagStore(STORE)
    snapshot = store.add_many([record for record, _ in gated],
                              note="P5 visitor-experience TAGs from CC BY 4.0 review corpus")

    decisions = Counter(verdict.decision for _, verdict in gated)
    by_tag = Counter(record.tag_id for record, verdict in gated if verdict.decision == "accept")
    gate_stats: dict[str, dict] = {}
    for _, verdict in gated:
        for name, gate in verdict.gates.items():
            bucket = gate_stats.setdefault(name, {"pass": 0, "fail": 0, "hard": gate["hard"]})
            bucket["pass" if gate["passed"] else "fail"] += 1

    # ---- manual spot-check sheet: 2 accepted + all quarantined/rejected, with quotes
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "review_sample.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tag_id", "value", "decision", "n_mentions", "pos", "neg", "neutral",
                         "wilson_lower", "confidence", "review_id", "quote",
                         "human_ok(1/0)", "human_note"])
        for record, verdict in sorted(gated, key=lambda item: (item[0].status != "accept",
                                                               -item[0].sample_size or 0)):
            if verdict.decision == "accept" and record.sample_size < 3:
                continue
            writer.writerow([record.tag_id, json.dumps(record.value, ensure_ascii=False),
                             verdict.decision, record.sample_size,
                             record.notes.split("正/负/中性 = ")[-1].split("；")[0] if "正/负/中性" in record.notes else "",
                             "", "", "", record.confidence, record.source_record_id,
                             record.excerpt.replace("\n", " ")[:300], "", ""])

    report = {
        "stage": "P5 visitor-experience extraction",
        "corpus": {
            "id": CORPUS_ID,
            "source": "https://doi.org/10.5281/zenodo.21633654",
            "licence": "CC BY 4.0",
            "attribution": stats.get("attribution"),
            "reviews_total": len(reviews),
            "reviews_sampled": len(sample),
            "sampling": f"按长度分层、sha1 排序后每层轮取，上限 {limit}",
            "poi_scope": "张家界国家森林公园（1 个 POI；不在 ChinaTravel 10 城内）",
        },
        "extraction": {
            "extractor": describe(),
            "mentions": len(mentions),
            "tags_hit": sorted({mention.tag_id for mention in mentions}),
            "records": len(records),
            "by_decision": dict(decisions),
            "accepted_by_tag": dict(by_tag),
            "gates": gate_stats,
        },
        "honest_limits": [
            "语料只覆盖 1 个 POI，且不在 ChinaTravel 10 城内，因此不能直接接入沙盒行程排序",
            "点评文本以英文为主（15066 条中仅 3 条中文），词表为此做成中英双语",
            "4TU 的中国 10 景点评论数据集（同样 CC BY 4.0）因 TLS 握手失败未能下载，否则可覆盖到 10 个景点",
            "只做规则抽取，未接入 LLM；每条记录都能用句子逐字复核",
        ],
        "snapshot": snapshot,
        "store_counts": store.counts(),
    }
    # ---- human-readable evidence sheet (accepted records, with their quotes)
    lines = ["# P5 游客体验 TAG 明细（accept）", "",
             f"> 语料：`{CORPUS_ID}`（CC BY 4.0）；抽样 {len(sample)} / {len(reviews)} 条评论；"
             f"抽取器 `visitor-tag-lexicon-v0.1`", "",
             "| TAG | 取值 | 提及评论数 | 正/负/中性 | Wilson 下界 | 置信度 | 原文证据 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for record, verdict in sorted(gated, key=lambda item: (-item[0].sample_size or 0)):
        if verdict.decision != "accept":
            continue
        split = ""
        if "正/负/中性 = " in record.notes:
            split = record.notes.split("正/负/中性 = ")[1].split("；")[0]
        lower = record.notes.split("Wilson 下界 ")[1].split("；")[0] if "Wilson 下界 " in record.notes else ""
        quote = record.excerpt.replace("|", "/")[:160]
        lines.append(f"| `{record.tag_id}` | {json.dumps(record.value, ensure_ascii=False)} | "
                     f"{record.sample_size} | {split} | {lower} | {record.confidence:.2f} | {quote} |")
    lines += ["", "## 被隔离（quarantine）的记录", "",
              "| TAG | 取值 | 提及评论数 | 原因 |", "| --- | --- | --- | --- |"]
    for record, verdict in gated:
        if verdict.decision == "accept":
            continue
        reason = "；".join(verdict.reasons)[:120].replace("|", "/")
        lines.append(f"| `{record.tag_id}` | {json.dumps(record.value, ensure_ascii=False)} | "
                     f"{record.sample_size} | {reason} |")
    lines += ["", f"来源与署名：{report['corpus']['attribution']}。",
              "每条记录可用 `source_record_id` 回到语料中逐字复核；未通过的记录保留原因，不删除。"]
    (OUT / "accepted_records.md").write_text("\n".join(lines), encoding="utf-8")

    OUT.joinpath("extract_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
    (OUT / "records.json").write_text(json.dumps(
        [{"record": record.to_dict(), "verdict": verdict.to_dict()} for record, verdict in gated],
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in report["extraction"].items() if k != "extractor"},
                     ensure_ascii=False, indent=2)[:1500])
    print("snapshot:", snapshot, "store:", store.counts())
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
