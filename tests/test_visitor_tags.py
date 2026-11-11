"""Tests for the visitor-experience TAG extractor (P5).

Every test corresponds to a defect found while building it on the real CC BY 4.0
corpus, so a regression is caught rather than re-discovered:

1. "No queue at all." must not count as evidence of queueing (longest-match rule).
2. Sentence splitting must not cut "bus No. 5".
3. Non-evaluative tags must not report unanimous positive sentiment.
4. One review mentioning a tag twice counts once (the review is the unit).
5. Polarised values (good vs poor) must be flagged, a lone dissent must not be.
6. Unknown stays unknown: no sentence, no record.
7. Wilson lower bound is below the raw rate and monotone in n.
8. Every record cites a review id that exists in the corpus.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.visitor_tags import (  # noqa: E402
    aggregate_mentions,
    build_records,
    extract_mentions,
    sentences,
    wilson_lower,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name if condition else (name, detail))


def review(text: str, rid: str = "r1") -> dict:
    return {"review_id": rid, "poi_hint": "测试景点", "text": text}


def main() -> int:
    # 1. negation must win over the bare keyword
    mentions = extract_mentions(review("No queue at all."))
    check("1/no_queue_not_counted_as_queue",
          all(m.tag_id != "queue_report" or m.value == "low" for m in mentions),
          str([(m.tag_id, m.value) for m in mentions]))

    # 2. sentence split must keep "No. 5" together
    parts = sentences("I took bus No. 5 to the gate. It was fine.")
    check("2/sentence_split_keeps_no5", any("No. 5" in part for part in parts), str(parts))

    # 3. non-evaluative tags are neutral, not unanimous praise
    mentions = extract_mentions(review("The view is amazing and great for photos."))
    photo = [m for m in mentions if m.tag_id == "photo_scenic"]
    check("3/photo_not_scored_positive", bool(photo) and all(m.sentiment == 0 for m in photo),
          str([(m.tag_id, m.sentiment) for m in mentions]))

    # 4. review is the statistical unit
    mentions = extract_mentions(review("Very crowded. Also crowded near the lift."))
    crowding = [m for m in mentions if m.tag_id == "crowding_report"]
    aggregates = aggregate_mentions(crowding, total_reviews=10)
    target = next((a for a in aggregates if a["tag_id"] == "crowding_report"), None)
    check("4/review_is_unit_of_count",
          target is not None and target["n_mentions"] == 2 and target["n_reviews"] == 1,
          str(target))

    # 5. polarisation flagged only when both sides have real share
    texts = ["Very crowded." for _ in range(6)] + ["Not crowded at all." for _ in range(5)]
    mentions = []
    for index, text in enumerate(texts):
        mentions.extend(extract_mentions(review(text, rid=f"r{index}")))
    aggregates = aggregate_mentions(mentions, total_reviews=20)
    polarized = {a["value"]: a.get("polarized", False) for a in aggregates
                 if a["tag_id"] == "crowding_report"}
    check("5/polarised_both_values_flagged", all(polarized.values()) and len(polarized) == 2,
          str(polarized))

    lone = ["Very crowded." for _ in range(18)] + ["Not crowded." for _ in range(2)]
    mentions = []
    for index, text in enumerate(lone):
        mentions.extend(extract_mentions(review(text, rid=f"x{index}")))
    aggregates = aggregate_mentions(mentions, total_reviews=20)
    minority = [a for a in aggregates if a["tag_id"] == "crowding_report" and a["value"] == "low"]
    check("5b/lone_dissent_not_polarised", bool(minority) and not minority[0].get("polarized", False),
          str(minority))

    # 6. no evidence -> no record
    bare = extract_mentions(review("I went there on Tuesday."))
    check("6/no_phrase_no_mention", bare == [], str(bare))

    # 7. Wilson bound behaves
    check("7/wilson_below_rate", wilson_lower(10, 20) < 0.5, str(wilson_lower(10, 20)))
    check("7b/wilson_grows_with_n", wilson_lower(50, 100) > wilson_lower(5, 10),
          f"{wilson_lower(50, 100)} vs {wilson_lower(5, 10)}")

    # 8. records point back to a real review and carry the corpus licence
    mentions = extract_mentions(review("Very crowded and quite dirty."))
    aggregates = aggregate_mentions(mentions, total_reviews=4)
    records = build_records(aggregates, local_poi_id="corpus:测试景点", poi_name="测试景点",
                            city="张家界", corpus_stats={"published_at": "2026-07-28"})
    check("8/record_cites_review",
          bool(records) and all(record.source_record_id == "r1" for record in records),
          str([(r.tag_id, r.source_record_id) for r in records]))
    check("8b/record_licence_cc_by", all(record.licence_status == "cc_by" for record in records),
          str({record.licence_status for record in records}))
    check("8c/record_has_quote", all(record.excerpt for record in records))

    print(f"PASS {len(PASSED)}  FAIL {len(FAILED)}")
    for name in PASSED:
        print(f"  ok   {name}")
    for name, detail in FAILED:
        print(f"  FAIL {name}: {detail}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
