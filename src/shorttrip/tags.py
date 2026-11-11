"""Visitor-experience TAG layer: taxonomy, extraction and quality gates.

Why this module exists
----------------------
The ChinaTravel sandbox knows a POI's *attributes* (type, hours, price) but nothing
about what visiting it is like. This layer adds evidence-backed tags with
provenance, and it is deliberately strict about three things:

1. **Attribute vs experience.** ``type``/``price``/``shop_hours`` are *attribute
   tags*: a platform states them. ``适合亲子``/``人气旺`` are *experience tags*: a
   platform aggregated what visitors reported. They live in different fields and
   carry different confidence; they are never mixed into one score silently.
2. **Provenance or nothing.** Every record carries the source, the URL, a digest of
   the raw response, the verbatim excerpt the value came from, the retrieval time,
   a licence status and a confidence. Gate T3 re-checks the excerpt against the
   stored raw text, so a fabricated quote cannot enter the store.
3. **Unknown is not zero.** A missing tag is ``None``; it never becomes a low score.
   Coverage and uncertainty are reported separately so a data-poor POI is not
   silently ranked as bad.

Tag dictionary v0.1 follows the task specification, extended with ``cleanliness``
and ``reachability`` (both observed in Baidu's ``content_tag`` vocabulary).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "tag-extractor-v0.1"
FRESH_DAYS = 180

# ---------------------------------------------------------------- taxonomy
# value_type: bool | enum | ordinal | float
# polarity:   benefit (higher = better trip) | burden (higher = worse) | neutral
# direction:  what "higher" means, stated once so a caller cannot flip it silently
TAXONOMY: dict[str, dict] = {
    # ---- 主题与偏好
    "history_culture": dict(group="theme", value_type="bool", polarity="benefit",
                            direction="1=有历史文化属性", description="历史文化主题"),
    "nature": dict(group="theme", value_type="bool", polarity="benefit",
                   direction="1=自然风光为主", description="自然主题"),
    "architecture": dict(group="theme", value_type="bool", polarity="benefit",
                         direction="1=建筑本身可看", description="建筑主题"),
    "photography": dict(group="theme", value_type="bool", polarity="benefit",
                        direction="1=适合拍照", description="摄影友好"),
    "family": dict(group="theme", value_type="bool", polarity="benefit",
                   direction="1=适合家庭出行", description="家庭取向"),
    "romantic": dict(group="theme", value_type="bool", polarity="benefit",
                     direction="1=适合情侣", description="浪漫取向"),
    "indoor": dict(group="theme", value_type="bool", polarity="neutral",
                   direction="1=室内为主", description="室内/室外"),
    # ---- 行动负担
    "walking_intensity": dict(group="burden", value_type="ordinal", polarity="burden",
                              values=["low", "medium", "high"],
                              direction="越大越费体力", description="步行强度"),
    "stairs": dict(group="burden", value_type="bool", polarity="burden",
                   direction="1=台阶多", description="台阶"),
    "slope": dict(group="burden", value_type="ordinal", polarity="burden",
                  values=["low", "medium", "high"], direction="越大坡度越陡", description="坡度"),
    "queue_time": dict(group="burden", value_type="ordinal", polarity="burden",
                       values=["low", "medium", "high"], direction="越大排队越久",
                       description="排队时长", context_required=True),
    "standing_load": dict(group="burden", value_type="ordinal", polarity="burden",
                          values=["low", "medium", "high"], direction="越大站立越久",
                          description="站立负荷"),
    # ---- 舒适与环境
    "crowding": dict(group="comfort", value_type="ordinal", polarity="burden",
                     values=["low", "medium", "high"], direction="越大越拥挤",
                     description="拥挤度", context_required=True),
    "noise": dict(group="comfort", value_type="ordinal", polarity="burden",
                  values=["low", "medium", "high"], direction="越大越吵", description="噪声"),
    "shade": dict(group="comfort", value_type="bool", polarity="benefit",
                  direction="1=有遮阴", description="遮阴"),
    "rest_facilities": dict(group="comfort", value_type="bool", polarity="benefit",
                            direction="1=有休息设施", description="休息设施"),
    "accessibility": dict(group="comfort", value_type="ordinal", polarity="benefit",
                          values=["unknown", "poor", "ok", "good"], direction="越高越无障碍",
                          description="无障碍"),
    "cleanliness": dict(group="comfort", value_type="ordinal", polarity="benefit",
                        values=["low", "medium", "high"], direction="越高越干净", description="卫生"),
    "reachability": dict(group="comfort", value_type="ordinal", polarity="benefit",
                         values=["low", "medium", "high"], direction="越高越好到达",
                         description="交通便利"),
    # ---- 时间与天气
    "best_visit_period": dict(group="timing", value_type="enum", polarity="neutral",
                              values=["morning", "afternoon", "evening", "any"],
                              direction="建议时段", description="最佳时段"),
    "sun_exposure": dict(group="timing", value_type="ordinal", polarity="burden",
                         values=["low", "medium", "high"], direction="越大越晒",
                         description="暴晒程度"),
    "rain_sensitivity": dict(group="timing", value_type="ordinal", polarity="burden",
                             values=["low", "medium", "high"], direction="越大越怕下雨",
                             description="雨天敏感度"),
    "night_view": dict(group="timing", value_type="bool", polarity="benefit",
                       direction="1=夜景值得看", description="夜景"),
    "seasonal_peak": dict(group="timing", value_type="enum", polarity="neutral",
                          values=["spring", "summer", "autumn", "winter", "none"],
                          direction="旺季季节", description="季节峰值"),
    # ---- 预算及收益
    "entry_price": dict(group="budget", value_type="float", polarity="neutral",
                        direction="人民币元，实际报价", description="门票价"),
    "value_for_money": dict(group="budget", value_type="ordinal", polarity="benefit",
                            values=["poor", "ok", "good"], direction="越高越划算",
                            description="性价比（主观）"),
    "paid_extras": dict(group="budget", value_type="bool", polarity="neutral",
                        direction="1=有额外收费项目", description="额外收费"),
    "time_worthiness": dict(group="budget", value_type="ordinal", polarity="benefit",
                            values=["low", "medium", "high"], direction="越高越值得花时间",
                            description="时间性价比"),
    # ---- 人群适配
    "elder_friendly": dict(group="audience", value_type="bool", polarity="benefit",
                           direction="1=适老", description="适老"),
    "child_friendly": dict(group="audience", value_type="bool", polarity="benefit",
                           direction="1=适幼", description="适合亲子"),
    "mobility_friendly": dict(group="audience", value_type="bool", polarity="benefit",
                              direction="1=行动不便者友好", description="行动便利"),
    "couple_friendly": dict(group="audience", value_type="bool", polarity="benefit",
                            direction="1=情侣友好", description="情侣友好"),
}

# ---------------------------------------------------------------- schema v0.2
# The open-data route (OSM/Wikidata) needs a tag vocabulary that names the
# *evidence class* explicitly, because the same string can come from an objective
# facility attribute, an editorial label, or an actual visitor report. These ids
# follow the instruction document's §P2 list; v0.1 ids above stay for the Baidu
# path and the historical store, and ALIASES lets the scorer read both.
TAXONOMY.update({
    "category_history": dict(group="theme", value_type="bool", polarity="benefit",
                             direction="1=历史文化类景点（类别证据）", description="历史文化类别"),
    "category_nature": dict(group="theme", value_type="bool", polarity="benefit",
                            direction="1=自然/园林类景点（类别证据）", description="自然类别"),
    "photo_scenic": dict(group="theme", value_type="bool", polarity="benefit",
                         direction="1=指定观景点/摄影价值有据", description="摄影价值"),
    "night_suitable": dict(group="timing", value_type="bool", polarity="benefit",
                           direction="1=适合夜间游览（需有据）", description="夜游适宜"),
    "family_friendly": dict(group="audience", value_type="bool", polarity="benefit",
                            direction="1=亲子友好（需有据）", description="亲子友好"),
    "low_walking": dict(group="burden", value_type="bool", polarity="benefit",
                        direction="1=步行负担低（需有据）", description="低步行负担"),
    "wheelchair_access": dict(group="comfort", value_type="ordinal", polarity="benefit",
                              values=["no", "limited", "yes"],
                              direction="越高越无障碍", description="无障碍通行"),
    "crowding_report": dict(group="comfort", value_type="ordinal", polarity="burden",
                            values=["low", "medium", "high"], direction="越大越拥挤",
                            description="拥挤反馈", context_required=True),
    "queue_report": dict(group="burden", value_type="ordinal", polarity="burden",
                         values=["low", "medium", "high"], direction="越大排队越久",
                         description="排队反馈", context_required=True),
    "price_satisfaction": dict(group="budget", value_type="ordinal", polarity="benefit",
                               values=["poor", "ok", "good"], direction="越高越觉得值",
                               description="价格满意度（游客反馈）"),
    "weather_sensitive": dict(group="timing", value_type="ordinal", polarity="burden",
                              values=["low", "medium", "high"], direction="越大越受天气影响",
                              description="天气敏感度"),
    # static attribute tags that the open-data route can actually support
    "osm_category": dict(group="attribute", value_type="string", polarity="neutral",
                         direction="OSM tourism/historic/leisure 类别",
                         description="OSM 类别"),
    "wikidata_type": dict(group="attribute", value_type="string", polarity="neutral",
                          direction="Wikidata P31 类型", description="Wikidata 类型"),
    "heritage_designation": dict(group="attribute", value_type="string", polarity="neutral",
                                 direction="文物保护单位等级", description="保护身份"),
    "fee_required": dict(group="budget", value_type="bool", polarity="neutral",
                         direction="1=需付费", description="是否收费"),
    "opening_hours": dict(group="attribute", value_type="string", polarity="neutral",
                          direction="OSM opening_hours 原串", description="开放时间"),
    "recommended_duration": dict(group="attribute", value_type="float", polarity="neutral",
                                 direction="小时", description="建议游玩时长"),
    "poi_category": dict(group="attribute", value_type="string", polarity="neutral",
                         direction="沙盒自带类别", description="沙盒类别"),
    "scenic_grade": dict(group="attribute", value_type="string", polarity="neutral",
                         direction="A 级景区", description="景区等级"),
    "platform_rating": dict(group="attribute", value_type="float", polarity="neutral",
                            direction="平台评分", description="平台评分"),
    "price_quote": dict(group="attribute", value_type="float", polarity="neutral",
                        direction="平台标价", description="平台标价"),
    "review_volume_bucket": dict(group="attribute", value_type="string", polarity="neutral",
                                 direction="评论量分桶", description="评论量分桶"),
})

# The five evidence classes required by the instruction. Mixing them into one
# undifferentiated "TAG" field is the failure mode this project must avoid.
EVIDENCE_CLASSES = (
    "POI_STATIC_ATTRIBUTE",   # objective attribute: category, fee, hours, wheelchair
    "EDITORIAL_TAG",          # platform/editor label, not a visitor report
    "VISITOR_EXPERIENCE",     # supported by actual visitor feedback
    "CONTEXT_PRIOR",          # type x context prior, an inference with a stated rule
    "LIVE_CONDITION",         # weather / opening / traffic fact at query time
)

EVIDENCE_CLASS_BY_KIND = {
    "attribute_api": "POI_STATIC_ATTRIBUTE",
    "crowd_tagged": "POI_STATIC_ATTRIBUTE",   # OSM community-contributed facility tags
    "platform_tag": "EDITORIAL_TAG",
    "documentary_claim": "EDITORIAL_TAG",
    "context_prior": "CONTEXT_PRIOR",
    "visitor_feedback": "VISITOR_EXPERIENCE",
    "manual_annotation": "EDITORIAL_TAG",
}

# Old id -> new canonical id, so the scorer can read both vocabularies.
ALIASES = {
    "history_culture": "category_history",
    "nature": "category_nature",
    "photography": "photo_scenic",
    "night_view": "night_suitable",
    "child_friendly": "family_friendly",
    "accessibility": "wheelchair_access",
    "crowding": "crowding_report",
    "queue_time": "queue_report",
    "value_for_money": "price_satisfaction",
}


def canonical_tag_id(tag_id: str) -> str:
    return ALIASES.get(tag_id, tag_id)


# Which evidence kinds may legitimately support each tag. A platform taxonomy may
# not manufacture a crowding estimate, and a single editorial sentence may not
# manufacture a queue-time ordinal.
EVIDENCE_KINDS = ("attribute_api", "platform_tag", "documentary_claim", "crowd_tagged",
                  "manual_annotation", "visitor_feedback", "context_prior")
BASE_CONFIDENCE = {
    "attribute_api": 0.92,
    "platform_tag": 0.55,      # platform-curated experience label, aggregation unknown
    "documentary_claim": 0.65,  # encyclopaedic text, quote-anchored
    "crowd_tagged": 0.75,       # explicit OSM facility tag (ODbL), e.g. wheelchair=yes
    "manual_annotation": 0.60,
    "visitor_feedback": 0.80,   # licensed review corpus — none available yet (see STATE.md)
    "context_prior": 0.35,      # type x context inference; never a visitor report
}
LICENCE_STATUS = ("api_terms_ok", "cc_by", "cc_by_sa", "cc0", "odbl", "internal_annotation", "unknown")

# ------------------------------------------------------- phrase -> tag rules
# Every rule is (regex, tag_id, value, strength). Only phrases actually observed in
# Baidu's content_tag vocabulary are listed; anything else is reported as unmapped
# so the mapping's coverage is measurable instead of aspirational.
PHRASE_RULES: list[tuple[str, str, object, float]] = [
    (r"适合亲子|亲子游|遛娃", "child_friendly", True, 1.0),
    (r"适合老人|适老|长辈", "elder_friendly", True, 1.0),
    (r"情侣约会|浪漫|适合约会", "couple_friendly", True, 1.0),
    (r"情侣约会|浪漫", "romantic", True, 0.8),
    (r"适合拍照|拍照圣地|出片", "photography", True, 1.0),
    (r"提供无障碍设施|无障碍", "accessibility", "good", 1.0),
    (r"提供无障碍设施|无障碍", "mobility_friendly", True, 0.9),
    (r"人气旺|网红|热门", "crowding", "high", 0.6),
    (r"排队|需排队", "queue_time", "high", 0.6),
    (r"取票方便|免排队|预约便捷", "queue_time", "low", 0.6),
    (r"适合跑步|适合散步|开阔", "walking_intensity", "high", 0.5),
    (r"登山|爬山|台阶", "walking_intensity", "high", 0.8),
    (r"登山|爬山", "slope", "high", 0.7),
    (r"古色古香|历史厚重|重点文物保护单位|世界遗产|国家一级博物馆|红色旅游|"
     r"文化氛围浓|涨知识圣地|展品丰富|历史悠久|古镇游玩", "history_culture", True, 1.0),
    (r"建筑风格独特|皇家园林风格|宏伟大气|古建筑", "architecture", True, 0.9),
    (r"自然风光|山水|风景优美|湖光山色|园林", "nature", True, 0.8),
    (r"夜景|适合夜游|灯光秀", "night_view", True, 1.0),
    (r"收费合理|性价比高|物超所值", "value_for_money", "good", 0.9),
    (r"场馆大|室内|恒温", "indoor", True, 0.7),
    (r"卫生干净|环境整洁", "cleanliness", "high", 0.8),
    (r"停车方便|交通便利|位置优越|地铁直达", "reachability", "high", 0.8),
    (r"环境清幽|安静|人少", "noise", "low", 0.6),
    (r"树荫|遮阴|纳凉", "shade", True, 0.8),
    (r"休息区|座椅|休息设施", "rest_facilities", True, 0.8),
    (r"一日游|值得一去|必去", "time_worthiness", "high", 0.6),
    (r"休闲好去处|休闲", "family", True, 0.4),
]
_COMPILED = [(re.compile(pattern), tag_id, value, strength)
             for pattern, tag_id, value, strength in PHRASE_RULES]

# attribute tag ids derived from Baidu taxonomy fields
ATTRIBUTE_TAXONOMY = {
    "poi_category": "平台原生类别（tag/classified_poi_tag）",
    "scenic_grade": "A 级景区等级（scope_grade）",
    "platform_rating": "平台综合评分（overall_rating，非评论）",
    "price_quote": "平台标价（price）",
    "opening_hours": "营业时间（regular_open_hour/shop_hours）",
    "review_volume_bucket": "评论量分桶（comment_num 已封顶，不作精确计数）",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def ordinal_numeric(value) -> float | None:
    """Map a tag value onto [0,1] for scoring. ``None`` stays ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    table = {
        "low": 0.25, "medium": 0.5, "high": 0.8,
        "poor": 0.2, "ok": 0.6, "good": 0.9, "unknown": None,
        "any": 0.5, "morning": 0.5, "afternoon": 0.5, "evening": 0.5,
        "spring": 0.5, "summer": 0.5, "autumn": 0.5, "winter": 0.5, "none": 0.5,
    }
    return table.get(str(value).lower())


def utility(tag_id: str, value) -> float | None:
    """Turn a tag value into a 'higher is better for the traveller' number.

    Burden tags are inverted here, once, so no caller has to remember which
    direction a tag points in.
    """
    numeric = ordinal_numeric(value)
    if numeric is None:
        return None
    spec = TAXONOMY.get(tag_id) or {}
    if spec.get("polarity") == "burden":
        return round(1.0 - numeric, 4)
    if spec.get("polarity") == "benefit":
        return round(numeric, 4)
    return None  # neutral tags are shown as context, not scored


# ------------------------------------------------------------------ records
@dataclass
class TagEvidence:
    local_poi_id: str
    tag_id: str
    value: object
    value_type: str
    evidence_kind: str
    city: str = ""
    poi_name: str = ""
    external_refs: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    source_name: str = ""
    source_url: str | None = None
    evidence_id: str = ""
    excerpt: str = ""
    raw_digest: str = ""
    licence_status: str = "unknown"
    observed_at: str | None = None
    retrieved_at: str = ""
    valid_until: str | None = None
    confidence: float = 0.0
    sample_size: int | None = None
    status: str = "candidate"
    gates: dict = field(default_factory=dict)
    model_version: str = EXTRACTOR_VERSION
    schema_version: int = SCHEMA_VERSION
    notes: str = ""
    # --- schema v0.2 fields required by the open-data route (instruction §P2)
    evidence_class: str = ""            # one of EVIDENCE_CLASSES; derived when empty
    source_record_id: str = ""          # e.g. "osm:way/584204634", "wikidata:Q168400"
    valid_for: str = "P180D"            # ISO-8601 duration the claim is expected to hold
    data_version: str = "tagdata-2026-10-21"

    @property
    def tag_type(self) -> str:
        """Vocabulary group (theme/burden/comfort/timing/budget/audience/attribute)."""
        return self.group

    def resolved_evidence_class(self) -> str:
        return self.evidence_class or EVIDENCE_CLASS_BY_KIND.get(self.evidence_kind, "EDITORIAL_TAG")

    @property
    def polarity(self) -> str:
        return (TAXONOMY.get(self.tag_id) or {}).get("polarity", "neutral")

    @property
    def group(self) -> str:
        return (TAXONOMY.get(self.tag_id) or {}).get("group", "other")

    @property
    def tag_uid(self) -> str:
        context_key = json.dumps(self.context or {}, ensure_ascii=False, sort_keys=True)
        raw = "|".join([self.local_poi_id, self.tag_id, self.source_name,
                        self.evidence_id, context_key, str(self.schema_version)])
        return _sha1(raw)

    def to_dict(self) -> dict:
        return {
            "tag_uid": self.tag_uid,
            "local_poi_id": self.local_poi_id,
            "city": self.city,
            "poi_name": self.poi_name,
            "external_refs": self.external_refs,
            "tag_id": self.tag_id,
            "tag_type": self.tag_type,
            "tag_group": self.group,
            "value": self.value,
            "value_type": self.value_type,
            "polarity": self.polarity,
            "evidence_kind": self.evidence_kind,
            "evidence_class": self.resolved_evidence_class(),
            "source_record_id": self.source_record_id,
            "context": self.context,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "evidence_id": self.evidence_id,
            "excerpt": self.excerpt,
            "raw_digest": self.raw_digest,
            "licence_status": self.licence_status,
            "observed_at": self.observed_at,
            "retrieved_at": self.retrieved_at,
            "valid_for": self.valid_for,
            "valid_until": self.valid_until,
            "confidence": round(self.confidence, 3),
            "sample_size": self.sample_size,
            "decision": self.status,
            "status": self.status,
            "gates": self.gates,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
            "data_version": self.data_version,
            "notes": self.notes,
        }


# --------------------------------------------------------------- extraction
def _expiry(days: int = FRESH_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _anchor(raw_text: str, *candidates: str) -> str:
    """Return the first candidate that really occurs in the raw response.

    Gate T3 is only meaningful if extraction refuses to invent excerpts, so this
    helper is the single place where an excerpt is chosen. An empty string means
    "could not anchor", and the gate will reject the record.
    """
    for candidate in candidates:
        if candidate and candidate in (raw_text or ""):
            return candidate
    return ""


def extract_attribute_tags(flat: dict, *, city: str, poi_name: str, raw_text: str,
                           source_name: str = "baidu", source_url: str | None = None,
                           retrieved_at: str | None = None) -> list[TagEvidence]:
    """Attribute tags: the platform *states* these, so confidence is high."""
    at = retrieved_at or _now()
    digest = _sha1(raw_text or "")
    poi_id = f"sandbox:{city}:{poi_name}"
    refs = {"baidu_uid": flat.get("uid")}
    out: list[TagEvidence] = []

    def add(tag_id: str, value, excerpt: str, *, kind: str = "attribute_api",
            confidence: float | None = None, notes: str = "") -> None:
        if value in (None, "", []):
            return
        out.append(TagEvidence(
            local_poi_id=poi_id, tag_id=tag_id, value=value,
            value_type=(TAXONOMY.get(tag_id) or {}).get("value_type", "string"),
            evidence_kind=kind, city=city, poi_name=poi_name, external_refs=refs,
            source_name=source_name, source_url=source_url, evidence_id=_sha1(f"{tag_id}:{excerpt}"),
            excerpt=excerpt, raw_digest=digest, licence_status="api_terms_ok",
            retrieved_at=at, valid_until=_expiry(),
            confidence=confidence if confidence is not None else BASE_CONFIDENCE[kind],
            notes=notes,
        ))

    taxonomy = ", ".join((flat.get("tag_path") or []) + (flat.get("classified_tag_path") or [])
                         + (flat.get("label_path") or []))
    category_raw = ";".join(flat.get("classified_tag_path") or []) or \
        ";".join(flat.get("tag_path") or []) or str(flat.get("scope_type") or "")
    add("poi_category", taxonomy, _anchor(raw_text, category_raw, str(flat.get("scope_type") or "")))
    if flat.get("scope_grade"):
        add("scenic_grade", flat["scope_grade"], _anchor(raw_text, str(flat["scope_grade"])))
    if flat.get("overall_rating") is not None:
        rating = flat["overall_rating"]
        add("platform_rating", rating,
            _anchor(raw_text, f'"overall_rating": "{rating}"', f'"overall_rating":{rating}', str(rating)),
            notes="平台综合评分，不是评论文本统计")
    if flat.get("price") is not None:
        price_text = str(flat.get("price_text") or flat["price"])
        quote = _anchor(raw_text, f'"price": "{price_text}"', f'"price":"{price_text}"', price_text)
        add("price_quote", flat["price"], quote)
        add("entry_price", float(flat["price"]), quote)
    if flat.get("open_time") and flat.get("close_time"):
        window = f"{flat['open_time']}-{flat['close_time']}"
        add("opening_hours", window,
            _anchor(raw_text, f'"shop_hours": "{window}"', window,
                    f'"shop_hours":"{window}"'))
    if flat.get("comment_bucket"):
        raw_comment = str(flat.get("comment_num"))
        add("review_volume_bucket", flat["comment_bucket"],
            _anchor(raw_text, f'"comment_num": "{raw_comment}"', f'"comment_num":"{raw_comment}"',
                    raw_comment),
            notes="comment_num 在 200 处封顶，只作序数分桶")
    return out


def extract_experience_tags(flat: dict, *, city: str, poi_name: str, raw_text: str,
                            source_name: str = "baidu", source_url: str | None = None,
                            retrieved_at: str | None = None,
                            context: dict | None = None) -> tuple[list[TagEvidence], dict]:
    """Experience tags from the platform's UGC-derived ``content_tag`` vocabulary.

    Returns the records plus a coverage report: which phrases were mapped, which
    were dropped, and why. Unmapped phrases are kept so the mapping can be
    improved with evidence instead of guesswork.
    """
    at = retrieved_at or _now()
    digest = _sha1(raw_text or "")
    poi_id = f"sandbox:{city}:{poi_name}"
    refs = {"baidu_uid": flat.get("uid")}
    phrases = [str(item) for item in (flat.get("content_tags") or [])]
    out: list[TagEvidence] = []
    mapped: dict[str, list[str]] = {}
    unmapped: list[str] = []

    for phrase in phrases:
        hit = False
        for pattern, tag_id, value, strength in _COMPILED:
            if not pattern.search(phrase):
                continue
            hit = True
            spec = TAXONOMY[tag_id]
            confidence = BASE_CONFIDENCE["platform_tag"] * float(strength)
            if spec.get("context_required") and not (context or {}):
                confidence *= 0.7  # no weekday/time context -> weaker claim
            out.append(TagEvidence(
                local_poi_id=poi_id, tag_id=tag_id, value=value,
                value_type=spec.get("value_type", "bool"),
                evidence_kind="platform_tag", city=city, poi_name=poi_name,
                external_refs=refs, context=context or {},
                source_name=source_name, source_url=source_url,
                evidence_id=_sha1(f"{phrase}:{tag_id}"),
                excerpt=phrase, raw_digest=digest, licence_status="api_terms_ok",
                retrieved_at=at, valid_until=_expiry(),
                confidence=min(0.85, confidence), sample_size=None,
                notes=f"平台标签短语「{phrase}」映射；无单条评论与投票数",
            ))
            mapped.setdefault(tag_id, []).append(phrase)
        if not hit:
            unmapped.append(phrase)

    report = {
        "phrases": len(phrases),
        "mapped_tags": len({item.tag_id for item in out}),
        "mapped_phrases": sorted(mapped),
        "unmapped_phrases": unmapped,
        "coverage": round(len(phrases) - len(unmapped), 3) if phrases else 0.0,
        "coverage_rate": round((len(phrases) - len(unmapped)) / len(phrases), 3) if phrases else 0.0,
    }
    return out, report


def extract_documentary_tags(text: str, *, city: str, poi_name: str, source_name: str,
                             source_url: str, quote_rules: Iterable[tuple[str, str, object, float]] | None = None,
                             retrieved_at: str | None = None) -> list[TagEvidence]:
    """Tags from encyclopaedic text, only when the *quote* really occurs in it."""
    at = retrieved_at or _now()
    digest = _sha1(text or "")
    poi_id = f"sandbox:{city}:{poi_name}"
    out: list[TagEvidence] = []
    for pattern, tag_id, value, strength in (quote_rules or []):
        match = re.search(pattern, text or "")
        if not match:
            continue
        spec = TAXONOMY.get(tag_id) or {}
        out.append(TagEvidence(
            local_poi_id=poi_id, tag_id=tag_id, value=value,
            value_type=spec.get("value_type", "bool"),
            evidence_kind="documentary_claim", city=city, poi_name=poi_name,
            source_name=source_name, source_url=source_url,
            evidence_id=_sha1(match.group(0)), excerpt=match.group(0),
            raw_digest=digest, licence_status="cc_by_sa",
            retrieved_at=at, valid_until=_expiry(),
            confidence=BASE_CONFIDENCE["documentary_claim"] * float(strength),
            notes="百科文本逐字引用，属于描述性陈述而非游客反馈",
        ))
    return out


# -------------------------------------------------------------------- gates
@dataclass
class TagVerdict:
    decision: str  # accept | quarantine | reject
    gates: dict
    reasons: list[str]
    confidence: float

    def to_dict(self) -> dict:
        return {"decision": self.decision, "confidence": round(self.confidence, 3),
                "gates": self.gates, "reasons": self.reasons}


def gate_tag(record: TagEvidence, *, raw_text: str | None = None,
             identity: dict | None = None, seen: dict | None = None) -> TagVerdict:
    """T1-T8. Hard failures reject; soft failures quarantine; else accept.

    * T1 licence     : the source must be usable (API terms / CC BY-SA / ODbL / own annotation)
    * T2 identity    : the POI must be the one we asked for, and not a facility sub-POI
    * T3 traceability: the excerpt must occur verbatim in the stored raw text
    * T4 semantics   : tag known, value inside its declared domain, polarity applied
    * T5 context     : tags that need a context (crowding/queue) must say when they apply
    * T6 duplicate   : same value twice from the same source is dropped
    * T7 uncertainty : missing/ambiguous stays unknown, never 0
    * T8 spot-check  : a sample is flagged for human review
    """
    gates: dict[str, dict] = {}
    reasons: list[str] = []
    hard_failed = False
    soft_failed = False

    def put(name: str, passed: bool, detail: str, *, hard: bool = True) -> None:
        nonlocal hard_failed, soft_failed
        gates[name] = {"passed": passed, "hard": hard, "detail": detail}
        if passed:
            return
        reasons.append(f"{name}: {detail}")
        if hard:
            hard_failed = True
        else:
            soft_failed = True

    licence_ok = record.licence_status in LICENCE_STATUS and record.licence_status != "unknown"
    put("T1_licence", licence_ok,
        f"licence={record.licence_status}" + ("" if licence_ok else "（未确认授权，不得落库使用）"))

    if identity is None:
        put("T2_identity", True, "未提供同一性判定，按软条件处理", hard=False)
    else:
        allowed = bool(identity.get("match"))
        rule = identity.get("rule", "?")
        put("T2_identity", allowed, f"identity rule={rule} score={identity.get('score')}")

    if raw_text is None:
        put("T3_traceability", False, "没有原始响应可供逐字核对", hard=True)
    else:
        anchored = bool(record.excerpt) and record.excerpt in raw_text
        put("T3_traceability", anchored,
            f"引文能否在原文逐字命中：{anchored}（excerpt={record.excerpt[:40]!r}）")

    spec = TAXONOMY.get(record.tag_id)
    if spec is None and record.tag_id in ATTRIBUTE_TAXONOMY:
        # Attribute tags are declarative platform facts; they only need a value.
        put("T4_semantics", record.value not in (None, "", []),
            f"属性标签 {record.tag_id}={record.value!r}")
        spec = {"value_type": "attribute", "polarity": "neutral"}
    elif spec is None:
        put("T4_semantics", False, f"未知 tag_id={record.tag_id}")
    else:
        value_ok = True
        detail = f"{record.tag_id}={record.value!r}"
        if spec.get("value_type") == "bool" and not isinstance(record.value, bool):
            value_ok = False
            detail += "（bool 标签必须给布尔值）"
        domain = spec.get("values") or []
        if spec.get("value_type") == "ordinal" and domain and record.value not in domain:
            value_ok = False
            detail += f"（取值不在 {domain}）"
        if spec.get("value_type") == "enum" and domain and record.value not in domain:
            value_ok = False
            detail += f"（取值不在 {domain}）"
        put("T4_semantics", value_ok, detail)

    if spec and spec.get("context_required"):
        has_context = bool(record.context)
        put("T5_context", has_context,
            "带语境标签缺少 weekday/time_window 语境" if not has_context else f"context={record.context}",
            hard=False)
    else:
        put("T5_context", True, "该标签不要求语境", hard=False)

    if seen is not None:
        key = (record.local_poi_id, record.tag_id, record.source_name)
        previous = seen.get(key)
        if previous is None:
            seen[key] = {json.dumps(record.value, ensure_ascii=False)}
            put("T6_duplicate", True, "首次出现", hard=False)
        elif json.dumps(record.value, ensure_ascii=False) in previous:
            # Two vocabulary phrases asserting the same value is corroboration.
            record.notes = (record.notes + "；同源多短语印证").strip("；")
            put("T6_duplicate", True, "同一来源多个短语给出一致取值（算印证，不算重复）", hard=False)
        else:
            previous.add(json.dumps(record.value, ensure_ascii=False))
            put("T6_duplicate", False,
                f"同一来源给出互相冲突的取值：{sorted(previous)}", hard=False)
    else:
        put("T6_duplicate", True, "未提供去重集合", hard=False)

    known = record.value not in (None, "")
    put("T7_uncertainty", known, "未知值不得写成 0/False" if not known else f"取值={record.value!r}")

    needs_review = record.evidence_kind in ("platform_tag", "documentary_claim")
    put("T8_spot_check", True,
        "进入人工抽检队列" if needs_review else "结构化字段，免抽检", hard=False)

    confidence = float(record.confidence)
    if soft_failed:
        confidence = max(0.0, confidence - 0.10 * sum(
            1 for item in gates.values() if not item["passed"] and not item["hard"]))
    if hard_failed:
        decision = "reject"
    elif soft_failed:
        decision = "quarantine"
    else:
        decision = "accept"
    return TagVerdict(decision=decision, gates=gates, reasons=reasons, confidence=confidence)


def gate_all(records: list[TagEvidence], *, raw_index: dict[str, str],
             identity_index: dict[str, dict]) -> list[tuple[TagEvidence, TagVerdict]]:
    """Run T1-T8 over a batch, resolving raw text and identity per POI."""
    seen: dict = {}
    out: list[tuple[TagEvidence, TagVerdict]] = []
    for record in records:
        raw = raw_index.get(record.local_poi_id)
        identity = identity_index.get(record.local_poi_id)
        verdict = gate_tag(record, raw_text=raw, identity=identity, seen=seen)
        record.status = verdict.decision
        record.confidence = verdict.confidence
        record.gates = {name: item["passed"] for name, item in verdict.gates.items()}
        out.append((record, verdict))
    return out


# ------------------------------------------------------------------ queries
def describe() -> dict:
    """Machine-readable dictionary, so docs/report never drift from the code."""
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "n_tags": len(TAXONOMY),
        "groups": sorted({spec["group"] for spec in TAXONOMY.values()}),
        "tags": {key: {k: v for k, v in spec.items() if k != "values"} | {"values": spec.get("values")}
                 for key, spec in TAXONOMY.items()},
        "attribute_tags": ATTRIBUTE_TAXONOMY,
        "phrase_rules": len(PHRASE_RULES),
        "evidence_kinds": list(EVIDENCE_KINDS),
        "base_confidence": BASE_CONFIDENCE,
    }


def freshness_days(retrieved_at: str) -> float | None:
    try:
        moment = datetime.fromisoformat(retrieved_at)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - moment).total_seconds() / 86400.0, 1)


def decayed_confidence(record: TagEvidence) -> float:
    """Long-lived attributes decay slowly; crowding-type claims decay fast."""
    age = freshness_days(record.retrieved_at)
    if age is None:
        return record.confidence
    half_life = 30.0 if record.tag_id in ("crowding", "queue_time") else 365.0
    factor = math.pow(0.5, max(0.0, age) / half_life)
    return round(record.confidence * factor, 3)


# ------------------------------------------------------- gate v0.2 (T1-T6)
# The open-data route uses the instruction document's six checks, which are a
# coarser, evidence-class-aware subset of the T1-T8 set above. They are kept as a
# separate function so the Baidu-path tests and results stay reproducible.
GATE_V2_ACCEPT_LICENCES = {"odbl", "cc0", "cc_by", "cc_by_sa", "api_terms_ok", "internal_annotation"}


@dataclass
class GateV2Result:
    decision: str          # accept | quarantine | reject
    gates: dict
    reasons: list[str]
    confidence: float
    needs_review: bool = False

    def to_dict(self) -> dict:
        return {"decision": self.decision, "confidence": round(self.confidence, 3),
                "needs_review": self.needs_review, "gates": self.gates, "reasons": self.reasons}


def gate_tag_v2(record: TagEvidence, *, raw_text: str | None = None,
                identity: dict | None = None, conflicts: dict | None = None) -> GateV2Result:
    """T1 licence, T2 excerpt, T3 semantics/polarity, T4 time+context, T5 conflict, T6 review.

    Only ``accept`` may be scored. Conflicts are *preserved* (both rows kept, both
    quarantined) rather than averaged into a false certainty.
    """
    gates: dict[str, dict] = {}
    reasons: list[str] = []
    hard_failed = False
    soft_failed = False

    def put(name: str, passed: bool, detail: str, *, hard: bool = True) -> None:
        nonlocal hard_failed, soft_failed
        gates[name] = {"passed": passed, "hard": hard, "detail": detail}
        if passed:
            return
        reasons.append(f"{name}: {detail}")
        if hard:
            hard_failed = True
        else:
            soft_failed = True

    # T1 licence
    licence_ok = record.licence_status in GATE_V2_ACCEPT_LICENCES
    put("T1_licence", licence_ok, f"licence={record.licence_status}")

    # T2 excerpt must exist verbatim in the raw provider payload
    if raw_text is None:
        put("T2_excerpt", False, "没有原始响应可比对")
    else:
        anchored = bool(record.excerpt) and record.excerpt in raw_text
        put("T2_excerpt", anchored, f"excerpt={record.excerpt[:60]!r} in raw={anchored}")

    # T3 semantics + polarity
    spec = TAXONOMY.get(record.tag_id)
    if spec is None:
        put("T3_semantics", False, f"未知 tag_id={record.tag_id}")
    else:
        ok = True
        detail = f"{record.tag_id}={record.value!r}"
        if spec.get("value_type") == "bool" and not isinstance(record.value, bool):
            ok, detail = False, detail + "（bool 标签需布尔值）"
        elif spec.get("value_type") == "ordinal" and spec.get("values") \
                and record.value not in spec["values"]:
            ok, detail = False, detail + f"（取值须在 {spec['values']}）"
        elif spec.get("value_type") == "enum" and spec.get("values") \
                and record.value not in spec["values"]:
            ok, detail = False, detail + f"（取值须在 {spec['values']}）"
        put("T3_semantics", ok, detail)

    # T4 time + audience applicability
    problems = []
    if record.valid_until:
        try:
            expiry = datetime.fromisoformat(record.valid_until)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < datetime.now(timezone.utc):
                problems.append("valid_until 已过期")
        except ValueError:
            problems.append("valid_until 无法解析")
    else:
        problems.append("缺少 valid_until")
    if spec and spec.get("context_required") and not record.context:
        problems.append("该类标签必须带语境（工作日/时段/季节）")
    if record.evidence_kind == "context_prior" and not record.notes:
        problems.append("CONTEXT_PRIOR 必须写明推断规则")
    put("T4_time_context", not problems, "；".join(problems) or "时间与语境齐备", hard=False)

    # T5 conflict / duplicate
    key = (record.local_poi_id, record.tag_id)
    if conflicts is not None:
        previous = conflicts.get(key)
        if previous is None:
            conflicts[key] = {json.dumps(record.value, ensure_ascii=False)}
            put("T5_conflict", True, "首次出现", hard=False)
        elif json.dumps(record.value, ensure_ascii=False) in previous:
            record.notes = (record.notes + "；多源一致，置信度上调").strip("；")
            record.confidence = min(0.99, record.confidence + 0.05)
            put("T5_conflict", True, "不同来源给出一致取值（印证）", hard=False)
        else:
            previous.add(json.dumps(record.value, ensure_ascii=False))
            put("T5_conflict", False, f"同一标签出现冲突取值 {sorted(previous)}", hard=False)
    else:
        put("T5_conflict", True, "未提供冲突集合", hard=False)

    # T6 human spot-check (non-blocking, but recorded)
    needs_review = record.evidence_kind in ("context_prior", "platform_tag", "documentary_claim")
    put("T6_review", True, "进入人工抽检队列" if needs_review else "结构化字段，免抽检", hard=False)

    confidence = float(record.confidence)
    if soft_failed:
        confidence = max(0.0, confidence - 0.10 * sum(
            1 for gate in gates.values() if not gate["passed"] and not gate["hard"]))
    if hard_failed:
        decision = "reject"
    elif soft_failed:
        decision = "quarantine"
    else:
        decision = "accept"
    return GateV2Result(decision=decision, gates=gates, reasons=reasons,
                        confidence=confidence, needs_review=needs_review)
