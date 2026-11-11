"""P2: turn OSM/Wikidata matches into TAG records with verifiable evidence.

Separating evidence classes is the whole point of this module:

| what we observed | tag | evidence class | why |
| --- | --- | --- | --- |
| OSM `tourism=museum` | `category_history` | POI_STATIC_ATTRIBUTE | an objective mapped category |
| OSM `wheelchair=yes` | `wheelchair_access` | POI_STATIC_ATTRIBUTE | an explicit facility attribute |
| OSM `fee=no` | `fee_required` | POI_STATIC_ATTRIBUTE | an explicit fact |
| OSM `leisure=park` | `category_nature` | POI_STATIC_ATTRIBUTE | mapped category |
| Wikidata P31 type label | `category_*` | POI_STATIC_ATTRIBUTE | structured CC0 claim |
| Wikidata P1435 heritage | `heritage_designation` | POI_STATIC_ATTRIBUTE | structured CC0 claim |
| type is museum -> indoor -> low weather risk | `weather_sensitive` | CONTEXT_PRIOR | an *inference*, never a visitor report |
| type is zoo/theme park -> suits families | `family_friendly` | CONTEXT_PRIOR | same; confidence capped low |

There is deliberately **no** VISITOR_EXPERIENCE record: no licensed review corpus was
obtained, and the instruction forbids substituting model guesses for visitor
feedback. `crowding_report`, `queue_report` and `price_satisfaction` therefore stay
empty, and the B2 experiment group is marked not-executable.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..tags import (
    BASE_CONFIDENCE,
    EVIDENCE_CLASS_BY_KIND,
    TagEvidence,
    _sha1,
    _now,
)

OSM_LICENCE = "odbl"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
WIKIDATA_LICENCE = "cc0"
DATA_VERSION = "tagdata-2026-10-21"

# category inference from OSM tags -> (tag_id, value, note)
OSM_CATEGORY_RULES = [
    (("tourism", "museum"), "category_history", True, "OSM tourism=museum"),
    (("tourism", "gallery"), "category_history", True, "OSM tourism=gallery"),
    (("tourism", "attraction"), "category_history", None, "OSM tourism=attraction（仅提示，需配合 historic/类别）"),
    (("historic", None), "category_history", True, "OSM historic=*"),
    (("leisure", "park"), "category_nature", True, "OSM leisure=park"),
    (("leisure", "garden"), "category_nature", True, "OSM leisure=garden"),
    (("natural", None), "category_nature", True, "OSM natural=*"),
    (("tourism", "viewpoint"), "photo_scenic", True, "OSM tourism=viewpoint"),
    (("man_made", "tower"), "photo_scenic", True, "OSM man_made=tower（观景塔）"),
]

CONTEXT_PRIOR_RULES = [
    (("tourism", "museum"), "weather_sensitive", "low", "室内场馆，天气敏感度低（类别推断）"),
    (("amenity", "museum"), "weather_sensitive", "low", "室内场馆，天气敏感度低（类别推断）"),
    (("tourism", "zoo"), "family_friendly", True, "动物园类，亲子适配（类别推断）"),
    (("tourism", "theme_park"), "family_friendly", True, "主题乐园类，亲子适配（类别推断）"),
    (("leisure", "park"), "family_friendly", True, "公园类，亲子适配（类别推断）"),
]


def _expiry(days: int = 180) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _record(*, poi: dict, tag_id: str, value, evidence_kind: str, source_name: str,
            source_url: str, source_record_id: str, excerpt: str, raw_text: str,
            licence: str, confidence: float, notes: str = "",
            value_type: str = "bool", context: dict | None = None) -> TagEvidence:
    return TagEvidence(
        local_poi_id=poi["local_poi_id"], tag_id=tag_id, value=value, value_type=value_type,
        evidence_kind=evidence_kind, city=poi["city"], poi_name=poi["name"],
        external_refs={"osm": source_record_id if source_name == "osm" else None,
                       "wikidata": source_record_id if source_name == "wikidata" else None},
        context=context or {}, source_name=source_name, source_url=source_url,
        evidence_id=_sha1(f"{tag_id}:{excerpt}:{source_record_id}"), excerpt=excerpt,
        raw_digest=_sha1(raw_text), licence_status=licence, retrieved_at=_now(),
        valid_until=_expiry(), confidence=confidence, status="candidate",
        source_record_id=source_record_id, data_version=DATA_VERSION, notes=notes,
    )


# ------------------------------------------------------------------ OSM -> TAG
def osm_records(row: dict, raw_row: dict) -> list[TagEvidence]:
    """Convert one matched OSM POI into TAG records. ``raw_row`` is the verbatim
    Nominatim hit, so every ``excerpt`` can be re-checked against real bytes."""
    osm = row.get("osm") or {}
    if not osm.get("match"):
        return []
    tags = osm.get("tags") or {}
    ref = f'osm:{osm.get("osm_type")}/{osm.get("osm_id")}'
    url = f'https://www.openstreetmap.org/{osm.get("osm_type")}/{osm.get("osm_id")}'
    raw_text = json.dumps(raw_row, ensure_ascii=False)
    out: list[TagEvidence] = []

    def excerpt(key: str) -> str:
        return f'"{key}": "{tags.get(key)}"'

    for (key, value), tag_id, tag_value, note in OSM_CATEGORY_RULES:
        if key not in tags:
            continue
        if value is not None and str(tags.get(key)) != value:
            continue
        if tag_value is None:
            # tourism=attraction is too weak on its own; only keep it when nothing
            # stronger (museum/historic) already explains the category.
            if "category_history" in {item.tag_id for item in out}:
                continue
            if tags.get("historic") or tags.get("tourism") in ("museum", "gallery"):
                continue
            continue
        if tag_id in {item.tag_id for item in out}:
            continue
        out.append(_record(
            poi=row, tag_id=tag_id, value=tag_value, evidence_kind="crowd_tagged",
            source_name="osm", source_url=url, source_record_id=ref,
            excerpt=excerpt(key), raw_text=raw_text, licence=OSM_LICENCE,
            confidence=BASE_CONFIDENCE["crowd_tagged"], notes=f"{note}；{OSM_ATTRIBUTION}",
        ))

    if "wheelchair" in tags and str(tags["wheelchair"]) in ("yes", "limited", "no"):
        out.append(_record(
            poi=row, tag_id="wheelchair_access", value=str(tags["wheelchair"]),
            evidence_kind="crowd_tagged", source_name="osm", source_url=url,
            source_record_id=ref, excerpt=excerpt("wheelchair"), raw_text=raw_text,
            licence=OSM_LICENCE, confidence=BASE_CONFIDENCE["crowd_tagged"],
            notes=f"OSM wheelchair 明确标注；{OSM_ATTRIBUTION}", value_type="ordinal",
        ))
    if "fee" in tags and str(tags["fee"]) in ("yes", "no"):
        out.append(_record(
            poi=row, tag_id="fee_required", value=str(tags["fee"]) == "yes",
            evidence_kind="crowd_tagged", source_name="osm", source_url=url,
            source_record_id=ref, excerpt=excerpt("fee"), raw_text=raw_text,
            licence=OSM_LICENCE, confidence=BASE_CONFIDENCE["crowd_tagged"],
            notes=f"OSM fee 标注；{OSM_ATTRIBUTION}",
        ))
    if "opening_hours" in tags:
        out.append(_record(
            poi=row, tag_id="opening_hours", value=str(tags["opening_hours"]),
            evidence_kind="crowd_tagged", source_name="osm", source_url=url,
            source_record_id=ref, excerpt=excerpt("opening_hours"), raw_text=raw_text,
            licence=OSM_LICENCE, confidence=BASE_CONFIDENCE["crowd_tagged"] * 0.9,
            notes=f"OSM opening_hours 原串，未做日历语义解析；{OSM_ATTRIBUTION}",
            value_type="string",
        ))
    if "heritage" in tags:
        out.append(_record(
            poi=row, tag_id="heritage_designation", value=str(tags["heritage"]),
            evidence_kind="crowd_tagged", source_name="osm", source_url=url,
            source_record_id=ref, excerpt=excerpt("heritage"), raw_text=raw_text,
            licence=OSM_LICENCE, confidence=BASE_CONFIDENCE["crowd_tagged"],
            notes=f"OSM heritage 标注；{OSM_ATTRIBUTION}", value_type="string",
        ))
    # context priors: explicitly labelled, lower confidence, never visitor evidence
    for (key, value), tag_id, tag_value, note in CONTEXT_PRIOR_RULES:
        if key not in tags:
            continue
        if value is not None and str(tags.get(key)) != value:
            continue
        if tag_id in {item.tag_id for item in out}:
            continue
        out.append(_record(
            poi=row, tag_id=tag_id, value=tag_value, evidence_kind="context_prior",
            source_name="osm", source_url=url, source_record_id=ref,
            excerpt=excerpt(key), raw_text=raw_text, licence=OSM_LICENCE,
            confidence=BASE_CONFIDENCE["context_prior"], notes=note, value_type="ordinal",
        ))
    return out


# ------------------------------------------------------------- Wikidata -> TAG
def wikidata_records(row: dict, entity: dict, type_labels: dict[str, dict],
                     mapped_types: dict[str, list[str]]) -> list[TagEvidence]:
    """Convert one accepted Wikidata entity into TAG records (CC0)."""
    wd = row.get("wikidata") or {}
    qid = wd.get("qid_accepted")
    if not qid or not entity:
        return []
    ref = f"wikidata:{qid}"
    url = f"https://www.wikidata.org/wiki/{qid}"
    raw_text = json.dumps(entity, ensure_ascii=False)
    claims = entity.get("claims") or {}
    out: list[TagEvidence] = []

    # P31 instance-of -> category tags, with the P31 statement as the excerpt
    seen: set[str] = set()
    for statement in claims.get("P31", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        target = value.get("id") if isinstance(value, dict) else None
        if not target:
            continue
        for tag_id in mapped_types.get(target, []):
            if tag_id in seen:
                continue
            seen.add(tag_id)
            label = type_labels.get(target, {})
            excerpt = f'"id": "{target}"'
            out.append(_record(
                poi=row, tag_id=tag_id, value=True, evidence_kind="attribute_api",
                source_name="wikidata", source_url=url, source_record_id=ref,
                excerpt=excerpt, raw_text=raw_text, licence=WIKIDATA_LICENCE,
                confidence=BASE_CONFIDENCE["attribute_api"] * 0.95,
                notes=(f"Wikidata P31={target}（{label.get('zh') or label.get('en') or ''}）"
                       "；类别推断为标签，非游客评价；Wikidata CC0"),
            ))
    if claims.get("P1435"):
        value = claims["P1435"][0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
        target = value.get("id") if isinstance(value, dict) else None
        if target:
            out.append(_record(
                poi=row, tag_id="heritage_designation", value=target,
                evidence_kind="attribute_api", source_name="wikidata", source_url=url,
                source_record_id=ref, excerpt=f'"id": "{target}"', raw_text=raw_text,
                licence=WIKIDATA_LICENCE, confidence=BASE_CONFIDENCE["attribute_api"] * 0.9,
                notes=f"Wikidata P1435={target} 保护身份；Wikidata CC0", value_type="string",
            ))
    return out
