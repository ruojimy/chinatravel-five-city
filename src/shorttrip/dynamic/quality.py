"""Quality gate: the only place allowed to decide that external data may enter
the sandbox.

Every rule is either *hard* (failure = reject) or *soft* (affects confidence and
may force a user confirmation). The gate never trusts the extractor: for each
claimed field it re-checks the quote against the fetched text, and for geometry
it re-checks the point against the city's existing footprint.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .records import (
    REQUIRED_FIELDS,
    CandidateRecord,
    DataRequest,
    GateResult,
    QualityReport,
)

FRESH_DAYS = 90
MAX_COORD_DRIFT_KM = 3.0
CITY_MARGIN_DEG = 0.6


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


class QualityGate:
    def __init__(self, env, city_boxes: dict | None = None):
        self.env = env
        self._boxes = city_boxes or {}

    # ------------------------------------------------------------------ util
    def city_box(self, city: str) -> tuple[float, float, float, float] | None:
        if city in self._boxes:
            return self._boxes[city]
        lats, lons = [], []
        for table in (
            self.env.attraction_table(city),
            self.env.restaurant_table(city),
            self.env.accommodation_table(city),
        ):
            if table is None or table.empty:
                continue
            lats += list(table["lat"].astype(float))
            lons += list(table["lon"].astype(float))
        if not lats:
            return None
        box = (min(lats), max(lats), min(lons), max(lons))
        self._boxes[city] = box
        return box

    def existing_names(self, city: str, kind: str) -> set[str]:
        table = {
            "attraction": self.env.attraction_table,
            "restaurant": self.env.restaurant_table,
            "accommodation": self.env.accommodation_table,
        }[kind](city)
        if table is None or table.empty:
            return set()
        return set(table["name"].astype(str))

    # ------------------------------------------------------------------ gates
    def evaluate(self, candidate: CandidateRecord, route: dict | None = None) -> QualityReport:
        request = candidate.request
        fields = candidate.fields
        gates: list[GateResult] = []
        reasons: list[str] = []

        def gate(name: str, passed: bool, detail: str, hard: bool = True) -> None:
            gates.append(GateResult(name, passed, detail, hard))
            if not passed:
                reasons.append(f"{name}: {detail}")

        ok_evidence = [item for item in candidate.evidence if item.ok]
        # G1 authority: at least one high-authority source said something
        authoritative = [item for item in ok_evidence if item.authority >= 0.7 and item.text]
        gate(
            "G1_authority",
            bool(authoritative),
            f"{len(authoritative)} 个高权威来源（wikipedia/wikidata）可用" if authoritative else "没有高权威来源",
        )

        # G2 identity: name matches and the article is about that name
        name_value = str(fields.get("name").value) if fields.get("name") else ""
        identity_ok = name_value and (name_value == request.name or request.name in name_value or name_value in request.name)
        amap_evidence = next((item for item in ok_evidence if item.source == "amap"), None)
        amap_mismatch = bool(amap_evidence and amap_evidence.structured.get("name_match") is False)
        if amap_mismatch:
            returned = amap_evidence.structured.get("name")
            similarity = amap_evidence.structured.get("name_similarity")
            identity_ok = False
            gate(
                "G2_identity",
                False,
                f"高德返回的是另一个 POI：{returned!r}（相似度 {similarity}），与请求 {request.name!r} 不符",
            )
        else:
            gate("G2_identity", bool(identity_ok), f"名称一致性：{name_value!r} vs {request.name!r}")

        # G3 quote anchoring: every claimed value must cite text that really exists
        bad_quotes = []
        for key, value in fields.items():
            if key in ("name", "city"):
                value.quote_ok = True
                continue
            if value.source == "planner":
                value.quote_ok = True
                continue
            if value.value is None:
                continue
            haystack = next((item.text for item in ok_evidence if item.source == value.source), "")
            if not value.quote:
                value.quote_ok = False
                bad_quotes.append(key)
                continue
            value.quote_ok = bool(haystack) and (value.quote in haystack)
            if not value.quote_ok:
                bad_quotes.append(key)
        for key in bad_quotes:
            fields.pop(key, None)
        gate(
            "G3_quote_anchor",
            not bad_quotes,
            "所有字段都能在原文中逐字对上" if not bad_quotes else f"以下字段引文对不上，已丢弃：{sorted(bad_quotes)}",
        )

        # G4 geometry
        lat = fields.get("lat").value if fields.get("lat") else None
        lon = fields.get("lon").value if fields.get("lon") else None
        box = self.city_box(request.city)
        if lat is None or lon is None:
            gate("G4_geometry", False, "缺少坐标")
        elif box is None:
            gate("G4_geometry", False, "无法计算城市范围")
        else:
            min_lat, max_lat, min_lon, max_lon = box
            inside = (
                min_lat - CITY_MARGIN_DEG <= lat <= max_lat + CITY_MARGIN_DEG
                and min_lon - CITY_MARGIN_DEG <= lon <= max_lon + CITY_MARGIN_DEG
            )
            gate("G4_geometry", inside, f"坐标 ({lat:.4f},{lon:.4f}) 是否落在 {request.city} 范围内：{inside}")

        # G4b two-source coordinate agreement
        coords = []
        for item in ok_evidence:
            if item.source == "wikidata" and item.structured.get("coordinates"):
                point = item.structured["coordinates"]
                coords.append((item.source, point.get("lat"), point.get("lon")))
            if item.source == "wikipedia_zh" and item.structured.get("coordinates"):
                point = item.structured["coordinates"][0]
                coords.append((item.source, point.get("lat"), point.get("lon")))
            if item.source == "openstreetmap":
                for row in item.structured.get("results", [])[:3]:
                    try:
                        coords.append((item.source, float(row["lat"]), float(row["lon"])))
                    except (KeyError, TypeError, ValueError):
                        continue
        if len(coords) >= 2 and lat is not None:
            drift = min(_km(lat, lon, item[1], item[2]) for item in coords if item[1] is not None)
            gate("G4b_coord_agreement", drift <= MAX_COORD_DRIFT_KM, f"多源坐标最小偏差 {drift:.2f} km")
        else:
            gate("G4b_coord_agreement", True, "只有一个坐标来源，按软条件处理（降低置信度）", hard=False)

        # G5 field sanity
        problems = []
        opentime, endtime = fields.get("opentime"), fields.get("endtime")
        if opentime and endtime and opentime.value and endtime.value:
            open_min = int(str(opentime.value).split(":")[0]) * 60 + int(str(opentime.value).split(":")[1])
            close_min = int(str(endtime.value).split(":")[0]) * 60 + int(str(endtime.value).split(":")[1])
            if not (5 * 60 <= open_min < close_min <= 24 * 60):
                problems.append(f"开放时间不合常理 {opentime.value}-{endtime.value}")
        price = fields.get("price")
        if price and price.value is not None and not (0 <= float(price.value) <= 1000):
            problems.append(f"价格异常 {price.value}")
        recommend = fields.get("recommendmintime")
        if recommend and recommend.value is not None and not (0.5 <= float(recommend.value) <= 8):
            problems.append(f"建议时长异常 {recommend.value}")
        gate("G5_field_sanity", not problems, "；".join(problems) or "字段取值合理")

        # G6 completeness: identity is known but the record may still be unusable
        required = REQUIRED_FIELDS.get(request.kind, ())
        missing = [key for key in required if key not in fields or fields[key].value in (None, "")]
        gate(
            "G6_completeness",
            not missing,
            f"缺失字段：{missing}" if missing else "必需字段齐全",
            hard=False,
        )

        # G7 duplicate detection
        names = self.existing_names(request.city, request.kind)
        duplicate = request.name in names
        gate(
            "G7_no_conflict",
            True,
            "沙箱中已存在同名记录（将作为更新处理）" if duplicate else "沙箱中无同名记录",
            hard=False,
        )

        # soft: where do the opening hours come from?
        hour_sources = {fields[key].source for key in ("opentime", "endtime") if key in fields}
        hour_authoritative = any(
            next((item.authority for item in ok_evidence if item.source == source), 0.0) >= 0.7
            for source in hour_sources
        )
        gate(
            "S1_hours_provenance",
            bool(hour_sources) and hour_authoritative,
            f"开放时间来源：{sorted(hour_sources) or '无'}（权威来源：{hour_authoritative}）",
            hard=False,
        )

        # soft: official website / fresh
        has_site = any(item.structured.get("official_website") for item in ok_evidence)
        gate("S2_official_site", has_site, "有官网链接" if has_site else "未取到官网", hard=False)

        # G8 real road network: the sandbox `goto` is a synthetic subway graph and is
        # systematically optimistic, so compare against Amap before trusting a plan.
        if route:
            ratios = []
            for key, label in (("walk", "步行"), ("transit", "公交/地铁")):
                sandbox_min = route.get(f"sandbox_{key}_min")
                amap_min = route.get(f"amap_{key}_min")
                if sandbox_min and amap_min:
                    ratios.append((label, round(float(amap_min) / float(sandbox_min), 2)))
            worst = max(ratios, key=lambda item: item[1]) if ratios else None
            if worst is None:
                # brand-new POI: nothing to compare against, so do not penalise;
                # the Amap baseline is stored for calibration instead.
                passed = True
                detail = "新增 POI，无沙盒基线；已记录高德基线供校准"
            else:
                passed = worst[1] <= 1.25
                detail = "[" + ", ".join(f"{label} x{ratio}" for label, ratio in ratios) + "]"
                if not passed:
                    detail += " -> 沙盒时间乐观"
            gate("G8_real_route", passed, detail, hard=False)

        hard_failed = [item for item in gates if item.hard and not item.passed]
        soft_failed = [item for item in gates if not item.hard and not item.passed]
        soft_names = {item.name for item in soft_failed}

        confidence = 0.5 + 0.1 * len(authoritative) + (0.1 if hour_authoritative else 0.0) + (0.05 if has_site else 0.0)
        confidence = min(0.99, confidence)
        if soft_failed:
            confidence -= 0.12 * len(soft_failed)
        if route and (route.get('amap_walk_min') or route.get('amap_transit_min')):
            confidence = max(confidence, 0.55)

        if hard_failed:
            decision = "reject"
            needs_confirm = False
        elif "G6_completeness" in soft_names or "S1_hours_provenance" in soft_names:
            # identity holds, but the record cannot be used safely yet
            decision = "quarantine"
            needs_confirm = True
            reasons.append("关键字段缺失或开放时间无权威出处 -> 隔离，等待用户/官方渠道确认")
        elif soft_names:
            decision = "accept"
            needs_confirm = True
            reasons.append("存在软失败项，标注需用户确认")
        else:
            decision = "accept"
            needs_confirm = False

        return QualityReport(
            decision=decision,
            gates=gates,
            reasons=reasons,
            confidence=max(0.0, confidence),
            needs_user_confirm=needs_confirm,
        )


def valid_until(days: int = FRESH_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
