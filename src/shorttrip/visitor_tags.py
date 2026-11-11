"""Visitor-experience TAG extraction from **licensed** review text.

This is the module the whole P1 task was blocked on: until now
``VISITOR_EXPERIENCE`` was empty because no licensable corpus existed. With the
CC BY 4.0 Zhangjiajie corpus (Zenodo 10.5281/zenodo.21633654) there is real visitor
text to work from.

Design choices, all made so a reviewer can check the work by hand:

* **Rule-based, bilingual lexicon.** Every tag comes from an explicit phrase list.
  No model guesses a tag that no phrase supports, and the same input always yields
  the same output. An LLM pass can be layered on later, but it would still have to
  cite a verbatim quote.
* **Sentence-level quotes.** The `excerpt` of every record is a verbatim sentence
  from a specific review, and `source_record_id` is that review's id, so T2/T3 can
  re-check it against the corpus.
* **Polarity is two things.** `polarity` is the tag's inherent direction (a burden
  tag is bad when high); `sentiment` is what the visitor said (+1/-1/0). Lumping them
  together is how "很多人排队" gets mis-filed as a *feature*.
* **Aggregation, not a single review.** Per (POI, tag) we publish the count, the
  smoothed rate with a Beta prior, and the Wilson lower bound as confidence. One
  angry review cannot define a POI.
* **Unknown stays unknown.** A tag with no supporting sentence is simply absent; it
  is never written as 0/False.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .tags import BASE_CONFIDENCE, TagEvidence, _sha1, _now

EXTRACTOR_VERSION = "visitor-tag-lexicon-v0.2"
CORPUS_ID = "zenodo21633654"
CORPUS_LICENCE = "cc_by"
CORPUS_ATTRIBUTION = ("Huang Bao-Hui (2026), Dataset for: Research on the Emotional "
                      "Experience of Online Tourists in Zhangjiajie, Zenodo, CC BY 4.0")
# Beta prior: a neutral starting point that a handful of reviews cannot overwhelm.
PRIOR_ALPHA, PRIOR_BETA = 2.0, 2.0

SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\u4e00-\u9fff])|\n+")

# (regex, tag_id, value, sentiment, strength)
# `value` is the tag value when the phrase fires; `sentiment` is +1/-1/0 for what the
# visitor felt, kept separate from the tag's own polarity.
RULES: list[tuple[str, str, object, int, float]] = [
    # ---- crowding
    (r"\bcrowded\b|\bpacked\b|\bbusy\b|人太多|拥挤|人山人海|排队的人", "crowding_report", "high", -1, 1.0),
    (r"not (?:very )?crowded|\buncrowded\b|人不多|不拥挤|清静", "crowding_report", "low", 1, 0.9),
    # ---- queueing
    (r"\bqueue\b|\bqueues\b|\blong line\b|wait(?:ed|ing)? (?:for )?(?:a long|hours)|\b排队\b|等很久", "queue_report", "high", -1, 1.0),
    (r"no (?:need to )?queue|skip the line|不用排队|无需排队", "queue_report", "low", 1, 0.8),
    # ---- walking burden
    (r"lots of walking|\blong walk\b|much walking|\bwalk a lot\b|\bhik(?:e|ing)\b|\bclimb\b|"
     r"\bstairs\b|\bsteep\b|走很多|爬山|台阶|很累|体力", "walking_intensity", "high", -1, 1.0),
    (r"\beasy walk\b|\bflat\b|not much walking|不用走|不累|平坦", "walking_intensity", "low", 1, 0.8),
    # ---- weather sensitivity
    (r"\brain(?:y|ing)?\b|\braincoat\b|\bslippery\b|\bfog(?:gy)?\b|下雨|雨衣|湿滑|雾", "weather_sensitive", "high", -1, 1.0),
    (r"\bhot\b|\bheat\b|\bhumid\b|很热|闷热", "weather_sensitive", "high", -1, 0.7),
    (r"\bsunny\b|\bclear (?:day|sky)\b|晴天|天气很好", "weather_sensitive", "medium", 1, 0.6),
    # ---- scenic / photography value
    (r"\bphoto(?:s|graph)?\b|\bview(?:s)?\b|\bscenery\b|\bscenic\b|\blandscape\b|拍照|风景|景色|绝美", "photo_scenic", True, 0, 1.0),
    # ---- night
    (r"\bnight view\b|\bat night\b|\bnight scene\b|\bsunset\b|\bevening\b|夜景|日落|晚上去", "night_suitable", True, 0, 0.8),
    # ---- family
    (r"\bkids?\b|\bchildren\b|\bfamily\b|\bchild\b|小孩|孩子|亲子", "family_friendly", True, 0, 0.9),
    # ---- accessibility (only when explicitly mentioned)
    (r"\bwheelchair\b|\baccessible\b|\bdisabled\b|无障碍|轮椅", "wheelchair_access", "yes", 1, 0.9),
    # ---- rest facilities / toilets (complaints and praise both matter)
    (r"\btoilet(?:s)?\b|\brestroom(?:s)?\b|\brest area\b|\bbench(?:es)?\b|卫生间|厕所|休息区", "rest_facilities", True, 0, 0.7),
    (r"\bdirty\b|\bsmelly\b|很脏|脏乱", "cleanliness", "low", -1, 0.8),
    # ---- noise
    (r"\bnoisy\b|\bloud\b|很吵|嘈杂", "noise", "high", -1, 0.8),
    (r"\bquiet\b|\bpeaceful\b|安静|清幽", "noise", "low", 1, 0.8),
    # ---- value for money (evaluative: sentiment carries the meaning)
    (r"\bworth (?:it|the)\b|\bworth the trip\b|\bvalue for money\b|值得|性价比高", "price_satisfaction", "good", 1, 1.0),
    (r"\bexpensive\b|\boverpriced\b|\brip[- ]off\b|太贵|坑人|不值", "price_satisfaction", "poor", -1, 1.0),
    # ---- ticket / fee mentions (attribute-ish but visitor-stated)
    (r"\bticket(?:s)?\b|\bentrance fee\b|\badmission\b|门票", "fee_required", True, 0, 0.6),
    # A service merely being mentioned is not good reachability. Route-scoped
    # service/waiting evidence is handled separately by candidate_matching.
    (r"easy to (?:reach|get to)|交通便利|交通方便|到达方便", "reachability", "high", 1, 0.6),
    (r"hard to (?:reach|get to)|交通不便|难以到达", "reachability", "low", -1, 0.6),
]

COMPILED = [(re.compile(pattern, re.IGNORECASE), tag_id, value, sentiment, strength)
            for pattern, tag_id, value, sentiment, strength in RULES]

NEGATION = re.compile(r"\b(not|no|never|hardly|barely|without)\b|不|没|无", re.IGNORECASE)


@dataclass
class Mention:
    review_id: str
    poi_hint: str
    sentence: str
    tag_id: str
    value: object
    sentiment: int
    strength: float
    chars: int = 0
    negated: bool = False

    def to_dict(self) -> dict:
        return {"review_id": self.review_id, "poi_hint": self.poi_hint,
                "tag_id": self.tag_id, "value": self.value, "sentiment": self.sentiment,
                "strength": self.strength, "negated": self.negated,
                "sentence": self.sentence[:200]}


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(text or "") if part.strip()]


def extract_mentions(review: dict) -> list[Mention]:
    """Every rule hit becomes a mention; the sentence is the evidence.

    Per sentence and per tag, only the **longest matching phrase** is kept. Without
    this, "No queue at all." fired both the `queue_report=high` (\bqueue\b) and the
    `queue_report=low` (no queue) rules, so a review praising the absence of queues
    was counted as evidence of queueing. Longest-match is a cheap, deterministic
    stand-in for "the more specific phrase wins".
    """
    out: list[Mention] = []
    for sentence in sentences(review.get("text", "")):
        if len(sentence) < 6:
            continue
        best_per_tag: dict[str, tuple[int, Mention]] = {}
        for pattern, tag_id, value, sentiment, strength in COMPILED:
            match = pattern.search(sentence)
            if not match:
                continue
            span = match.end() - match.start()
            mention = Mention(
                review_id=review["review_id"], poi_hint=review.get("poi_hint", ""),
                sentence=sentence, tag_id=tag_id, value=value, sentiment=sentiment,
                strength=strength, chars=len(sentence),
                negated=bool(NEGATION.search(sentence)),
            )
            current = best_per_tag.get(tag_id)
            if current is None or span > current[0]:
                best_per_tag[tag_id] = (span, mention)
        out.extend(mention for _, mention in best_per_tag.values())
    return out


def wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = successes / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def aggregate_mentions(mentions: list[Mention], *, total_reviews: int) -> list[dict]:
    """Group per (poi, tag, value) and attach count / smoothed rate / confidence."""
    groups: dict[tuple[str, str, str], list[Mention]] = {}
    for mention in mentions:
        groups.setdefault((mention.poi_hint, mention.tag_id, json.dumps(mention.value)),
                          []).append(mention)

    aggregates: list[dict] = []
    used_quotes: set[str] = set()
    for (poi, tag_id, value_key), items in groups.items():
        n = len(items)
        # The statistical unit is the *review*, not the sentence: one review that says
        # "crowded" twice is still one visitor reporting crowding. Counting sentences
        # made successes exceed total_reviews and produced a negative sqrt in Wilson.
        distinct_reviews = len({item.review_id for item in items})
        positive = sum(1 for item in items if item.sentiment > 0)
        negative = sum(1 for item in items if item.sentiment < 0)
        neutral = n - positive - negative
        # dirichlet/beta-smoothed share of the reviews that mention this value
        smoothed = (distinct_reviews + PRIOR_ALPHA) / (total_reviews + PRIOR_ALPHA + PRIOR_BETA)
        lower = wilson_lower(min(distinct_reviews, total_reviews), total_reviews)
        # Focused evidence: prefer the *shortest* sentence that matched (a long pasted
        # "guide" paragraph would otherwise be quoted for several different tags), and
        # never reuse a sentence already used by another record in this run.
        ranked = sorted(items, key=lambda item: (-item.strength, item.chars))
        best = next((item for item in ranked if item.sentence[:120] not in used_quotes), ranked[0])
        used_quotes.add(best.sentence[:120])
        aggregates.append({
            "poi_hint": poi, "tag_id": tag_id, "value": json.loads(value_key),
            "n_mentions": n, "n_reviews": distinct_reviews, "reviews": total_reviews,
            "positive": positive, "negative": negative, "neutral": neutral,
            "smoothed_rate": round(smoothed, 5),
            "wilson_lower": round(lower, 5),
            "confidence": round(min(0.95, BASE_CONFIDENCE["visitor_feedback"] *
                                    (0.5 + 0.5 * lower)), 4),
            "best_quote": best.sentence[:300],
            "quote_review_id": best.review_id,
        })
    aggregates.sort(key=lambda item: -item["n_mentions"])

    # Polarisation: when two values of the same tag each have a real share of the
    # reviews (e.g. some visitors say crowded, others say quiet), that disagreement is
    # information, not a data error. Such records must go to human review instead of
    # being averaged into a false consensus.
    by_tag: dict[tuple[str, str], list[dict]] = {}
    for aggregate in aggregates:
        by_tag.setdefault((aggregate["poi_hint"], aggregate["tag_id"]), []).append(aggregate)
    for (poi, tag_id), items in by_tag.items():
        total = sum(item["n_reviews"] for item in items)
        if total <= 0 or len(items) < 2:
            continue
        shares = [(item, item["n_reviews"] / total) for item in items]
        if sum(1 for _, share in shares if share >= 0.3) >= 2:
            for item, share in shares:
                item["polarized"] = share >= 0.3
                item["share_of_tag"] = round(share, 3)
    return aggregates


def build_records(aggregates: list[dict], *, local_poi_id: str, poi_name: str,
                  city: str, corpus_stats: dict, valid_days: int = 365) -> list[TagEvidence]:
    """One evidence-backed TAG record per aggregate."""
    at = _now()
    expiry = (datetime.now(timezone.utc) + timedelta(days=valid_days)).date().isoformat()
    out: list[TagEvidence] = []
    for item in aggregates:
        confidence = min(0.95, BASE_CONFIDENCE["visitor_feedback"] *
                         (0.55 + 0.45 * min(1.0, item["n_mentions"] / 20.0)))
        out.append(TagEvidence(
            local_poi_id=local_poi_id, tag_id=item["tag_id"], value=item["value"],
            value_type="bool" if isinstance(item["value"], bool) else "ordinal",
            evidence_kind="visitor_feedback", city=city, poi_name=poi_name,
            external_refs={"corpus": CORPUS_ID,
                           "review_ids": [item["quote_review_id"]]},
            context={"corpus_scope": "张家界国家森林公园", "sampled_reviews": item["reviews"]},
            source_name="zenodo_zhangjiajie_reviews",
            source_url="https://doi.org/10.5281/zenodo.21633654",
            evidence_id=_sha1(f'{CORPUS_ID}:{item["quote_review_id"]}:{item["tag_id"]}'),
            excerpt=item["best_quote"],
            raw_digest=hashlib.sha1(item["best_quote"].encode("utf-8")).hexdigest()[:16],
            licence_status=CORPUS_LICENCE, observed_at=corpus_stats.get("published_at"),
            retrieved_at=at, valid_until=expiry, confidence=confidence,
            sample_size=item["n_mentions"], status="candidate",
            model_version=EXTRACTOR_VERSION, data_version=CORPUS_ID,
            source_record_id=item["quote_review_id"],
            notes=(f'来自 CC BY 4.0 语料的 {item["n_mentions"]} 条提及；'
                   f'正/负/中性 = {item["positive"]}/{item["negative"]}/{item["neutral"]}；'
                   f'Wilson 下界 {item["wilson_lower"]}；{CORPUS_ATTRIBUTION}'),
        ))
    return out


def describe() -> dict:
    tag_ids = sorted({tag_id for _, tag_id, _, _, _ in RULES})
    return {"extractor_version": EXTRACTOR_VERSION, "rules": len(RULES),
            "tags": tag_ids, "prior": {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA},
            "corpus": {"id": CORPUS_ID, "licence": "CC BY 4.0",
                       "attribution": CORPUS_ATTRIBUTION}}
