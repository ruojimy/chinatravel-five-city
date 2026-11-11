"""Bridge between the three places a tag can come from, kept explicit.

1. **Sandbox attributes** — `type` / `price` / `recommendmintime` / opening hours
   that ChinaTravel already ships. Turning them into tags is a *category
   inference*, not visitor evidence, so confidence is capped at 0.70 and the
   evidence kind says so.
2. **The TAG store** — external, gated, provenance-carrying evidence (Baidu
   `content_tag` today; a licensed review corpus when one is available).
3. **Merged view** — per POI and per tag the highest-confidence record wins, but
   the original payload is kept so a report can show which source produced it.

Keeping these separate is what stops "platform category" from being reported as
"visitors say", which is the failure mode the task specification warns about.
"""
from __future__ import annotations

from .tags import BASE_CONFIDENCE, EXTRACTOR_VERSION, _sha1, _now

# sandbox `type` -> theme tags. This is a *category* inference from the dataset's
# own labels; it says what a place is, never what visiting it is like.
TYPE_THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("博物馆", ("history_culture",)),
    ("纪念馆", ("history_culture",)),
    ("美术馆", ("photography", "architecture")),
    ("艺术馆", ("photography", "architecture")),
    ("历史古迹", ("history_culture", "architecture")),
    ("人文景观", ("architecture",)),
    ("自然风光", ("nature",)),
    ("公园", ("nature",)),
    ("游乐园", ("family",)),
    ("体育娱乐", ("family",)),
    ("商业街区", ("photography",)),
    ("文化旅游区", ("history_culture",)),
]

SANDBOX_CONFIDENCE = 0.70


def _payload(tag_id: str, value, *, city: str, name: str, evidence_kind: str,
             confidence: float, note: str) -> dict:
    return {
        "tag_id": tag_id,
        "value": value,
        "confidence": confidence,
        "evidence_kind": evidence_kind,
        "status": "accept",
        "source_name": "chinaTravel_sandbox",
        "local_poi_id": f"sandbox:{city}:{name}",
        "poi_name": name,
        "city": city,
        "evidence_id": _sha1(f"{city}:{name}:{tag_id}:{value}"),
        "retrieved_at": _now(),
        "model_version": EXTRACTOR_VERSION,
        "note": note,
    }


def sandbox_attribute_tags(env, city: str) -> dict[str, dict]:
    """Build the attribute-tag view for one city from the sandbox tables alone."""
    table = env.attraction_table(city)
    if table is None or table.empty:
        return {}
    out: dict[str, dict] = {}
    for row in table.to_dict("records"):
        name = str(row["name"])
        poi = f"sandbox:{city}:{name}"
        bucket: dict[str, dict] = {}
        type_text = str(row.get("type") or "")
        bucket["poi_category"] = _payload(
            "poi_category", type_text, city=city, name=name, evidence_kind="attribute_api",
            confidence=0.9, note="沙盒自带类别")
        try:
            price = float(row.get("price"))
            bucket["entry_price"] = _payload(
                "entry_price", price, city=city, name=name, evidence_kind="attribute_api",
                confidence=0.9, note="沙盒标价")
        except (TypeError, ValueError):
            pass
        try:
            duration = float(row.get("recommendmintime"))
            bucket["recommended_duration"] = _payload(
                "recommended_duration", duration, city=city, name=name,
                evidence_kind="attribute_api", confidence=0.9, note="沙盒建议时长（小时）")
        except (TypeError, ValueError):
            pass
        for keyword, tags in TYPE_THEME_RULES:
            if keyword in type_text:
                for tag_id in tags:
                    bucket[tag_id] = _payload(
                        tag_id, True, city=city, name=name, evidence_kind="attribute_api",
                        confidence=SANDBOX_CONFIDENCE,
                        note=f"由类别「{type_text}」推断的主题标签（类别推断，非游客证据）")
        out[poi] = bucket
    return out


def tag_view_from_store(store, snapshot: str | None = None) -> dict[str, dict]:
    """Accepted external evidence, best confidence per tag."""
    return store.by_poi(snapshot, status="accept")


def merge_tag_views(*views: dict[str, dict]) -> dict[str, dict]:
    """Merge POI->tag views, later views only fill gaps or win on confidence."""
    merged: dict[str, dict] = {}
    for view in views:
        for poi, tags in (view or {}).items():
            bucket = merged.setdefault(poi, {})
            for tag_id, payload in tags.items():
                current = bucket.get(tag_id)
                if current is None or float(payload.get("confidence") or 0) > float(current.get("confidence") or 0):
                    bucket[tag_id] = payload
    return merged


def provenance_summary(view: dict[str, dict]) -> dict:
    """How much of a tag view is external evidence vs category inference."""
    kinds: dict[str, int] = {}
    for tags in view.values():
        for payload in tags.values():
            kind = payload.get("evidence_kind", "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1
    total = sum(kinds.values())
    return {
        "records": total,
        "by_evidence_kind": kinds,
        "external_share": round(
            sum(count for kind, count in kinds.items() if kind != "attribute_api") / total, 3)
        if total else 0.0,
        "base_confidence": BASE_CONFIDENCE,
    }
