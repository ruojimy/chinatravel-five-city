"""Preference-aware re-ranker: order feasible plans, never judge feasibility.

Hard constraints stay with the official ChinaTravel checker. This module only
answers "of two plans that both pass, which one suits *this* traveller better, and
why", and it reports its own uncertainty separately:

    Q(P | u, t) =      Match(P, u)
                 - λ1 * TravelBurden(P, u)
                 - λ2 * FatigueAdjacency(P, u)
                 - λ3 * QueueAndCrowdRisk(P, t)
                 - λ4 * ThemeRepetition(P, u)
                 - λ5 * EditCost(P, P_previous)
                 - λ6 * PriceDiscomfort(P, u)
                 (+ coverage / uncertainty reported separately)

Each term is bounded in [0, 1] and each λ is documented, so a reviewer can see why
plan A beat plan B and can re-weight without touching the checker. Missing tag
evidence contributes the *neutral* value 0.5 and is counted in ``coverage`` — a
data-poor POI is never silently punished.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .preference import INTEREST_KEYS, UserProfile
from .tags import TAXONOMY, utility

NEUTRAL = 0.5

# interest key -> (tag ids that can support it, weight). Both the v0.1 vocabulary
# (Baidu path) and the v0.2 vocabulary (open-data path) are listed, so one scorer
# reads either store without the caller translating ids.
INTEREST_TAGS: dict[str, list[tuple[str, float]]] = {
    "history_culture": [("history_culture", 1.0), ("category_history", 1.0)],
    "nature": [("nature", 1.0), ("category_nature", 1.0)],
    "architecture": [("architecture", 1.0)],
    "photography": [("photography", 1.0), ("photo_scenic", 1.0)],
    "family": [("family", 1.0), ("child_friendly", 0.6), ("family_friendly", 1.0)],
    "romantic": [("romantic", 1.0), ("couple_friendly", 0.6)],
    "night_view": [("night_view", 1.0), ("night_suitable", 1.0)],
}

AUDIENCE_TAGS_ELDER = [("elder_friendly", 1.0), ("mobility_friendly", 0.8),
                       ("accessibility", 0.6), ("wheelchair_access", 0.7)]
AUDIENCE_TAGS_CHILD = [("child_friendly", 1.0), ("family", 0.4), ("family_friendly", 0.8)]
BURDEN_TAGS_WALK = [("walking_intensity", 1.0), ("stairs", 0.6), ("slope", 0.6),
                    ("standing_load", 0.4), ("low_walking", 1.0)]
BURDEN_TAGS_QUEUE = [("queue_time", 1.0), ("crowding", 1.0), ("queue_report", 1.0),
                     ("crowding_report", 1.0)]
THEME_TAG_IDS = ("history_culture", "nature", "architecture", "photography",
                 "category_history", "category_nature", "photo_scenic")


@dataclass
class RerankOptions:
    lambda_travel: float = 0.20
    lambda_fatigue: float = 0.15
    lambda_queue: float = 0.12
    lambda_theme: float = 0.08
    lambda_edit: float = 0.25
    lambda_price: float = 0.10
    holiday: bool = False

    def to_dict(self) -> dict:
        return {key: getattr(self, key) for key in
                ("lambda_travel", "lambda_fatigue", "lambda_queue", "lambda_theme",
                 "lambda_edit", "lambda_price", "holiday")}


def _minutes(hhmm: str) -> int:
    try:
        hour, minute = str(hhmm).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return 0


def _poi_id(city: str, name: str) -> str:
    return f"sandbox:{city}:{name}"


def plan_activities(plan: dict) -> list[dict]:
    return [activity for day in plan.get("itinerary", []) for activity in day.get("activities", [])]


def _tag_value(tags: dict[str, dict], poi_id: str, tag_id: str):
    payload = (tags.get(poi_id) or {}).get(tag_id)
    return None if payload is None else payload.get("value")


def _tag_confidence(tags: dict[str, dict], poi_id: str, tag_id: str) -> float:
    payload = (tags.get(poi_id) or {}).get(tag_id)
    return 0.0 if payload is None else float(payload.get("confidence") or 0.0)


def _tagged_utility(tags: dict[str, dict], poi_id: str, tag_id: str) -> float | None:
    value = _tag_value(tags, poi_id, tag_id)
    if value is None:
        return None
    return utility(tag_id, value)


def _weighted_utility(tags: dict[str, dict], poi_id: str, pairs: list[tuple[str, float]]) -> tuple[float | None, float]:
    """Confidence-weighted mean utility; returns (value|None, weight_covered)."""
    total_w = 0.0
    acc = 0.0
    for tag_id, weight in pairs:
        value = _tagged_utility(tags, poi_id, tag_id)
        if value is None:
            continue
        confidence = _tag_confidence(tags, poi_id, tag_id)
        effective = weight * max(confidence, 0.1)
        acc += value * effective
        total_w += effective
    if total_w <= 0:
        return None, 0.0
    return acc / total_w, total_w


def score_plan(
    plan: dict,
    profile: UserProfile,
    tags: dict[str, dict],
    *,
    city: str | None = None,
    previous: dict | None = None,
    options: RerankOptions | None = None,
) -> dict:
    """Score one feasible plan. Returns components, coverage and explanations."""
    options = options or RerankOptions()
    weights = profile.weights()
    interests = profile.interest_vector()
    city = city or plan.get("target_city", "")
    activities = plan_activities(plan)
    attractions = [a for a in activities if a.get("type") == "attraction"]
    explanations: list[dict] = []
    unknown: list[str] = []
    tagged: list[str] = []

    # ---------------------------------------------------------------- Match
    match_terms: list[float] = []
    for activity in attractions:
        name = str(activity.get("position") or "")
        poi = _poi_id(city, name)
        pairs: list[tuple[str, float]] = []
        for interest, weight in interests.items():
            if weight <= 0:
                continue
            for tag_id, tag_weight in INTEREST_TAGS.get(interest, []):
                pairs.append((tag_id, weight * tag_weight))
        if profile.with_elders:
            pairs += [(tag_id, 0.4 * weight) for tag_id, weight in AUDIENCE_TAGS_ELDER]
        if profile.with_children:
            pairs += [(tag_id, 0.4 * weight) for tag_id, weight in AUDIENCE_TAGS_CHILD]
        if profile.indoor_preference:
            pairs.append(("indoor", 0.3))
        if profile.night_preference:
            pairs.append(("night_view", 0.2))
        value, covered = _weighted_utility(tags, poi, pairs)
        if value is None:
            match_terms.append(NEUTRAL)
            unknown.append(name)
            explanations.append({"poi": name, "match": NEUTRAL, "why": "无可用标签，按中性处理"})
        else:
            match_terms.append(value)
            tagged.append(name)
            explanations.append({"poi": name, "match": round(value, 3),
                                 "why": f"由 {covered:.2f} 权重的标签证据支持"})
    match = sum(match_terms) / len(match_terms) if match_terms else NEUTRAL

    # -------------------------------------------------------- TravelBurden
    transport_minutes = 0.0
    for activity in activities:
        for leg in activity.get("transports") or []:
            transport_minutes += max(0, _minutes(leg.get("end_time")) - _minutes(leg.get("start_time")))
    activity_minutes = sum(max(0, _minutes(a.get("end_time")) - _minutes(a.get("start_time")))
                           for a in activities if a.get("end_time") and a.get("start_time"))
    total_minutes = transport_minutes + activity_minutes
    travel_ratio = transport_minutes / total_minutes if total_minutes else 0.0
    walking_burden = None
    for name in [str(a.get("position") or "") for a in attractions]:
        value, _covered = _weighted_utility(tags, _poi_id(city, name), BURDEN_TAGS_WALK)
        if value is not None:
            walking_burden = value if walking_burden is None else min(walking_burden, value)
    walking_term = 0.0 if walking_burden is None else (1.0 - walking_burden)  # utility->burden
    travel_burden = min(1.0, 0.7 * travel_ratio + 0.3 * walking_term)

    # ----------------------------------------------------- FatigueAdjacency
    fatigue_pairs = 0
    for first, second in zip(attractions, attractions[1:]):
        def intense(activity) -> bool:
            value = _tagged_utility(tags, _poi_id(city, str(activity.get("position") or "")),
                                    "walking_intensity")
            return value is not None and value <= 0.3   # high intensity -> low utility
        if intense(first) and intense(second):
            fatigue_pairs += 1
    fatigue = min(1.0, fatigue_pairs / max(1, len(attractions) - 1))

    # ------------------------------------------------- QueueAndCrowdRisk
    queue_terms = []
    for activity in attractions:
        poi = _poi_id(city, str(activity.get("position") or ""))
        value, _covered = _weighted_utility(tags, poi, BURDEN_TAGS_QUEUE)
        if value is None:
            continue
        risk = 1.0 - value
        if options.holiday:
            risk = min(1.0, risk * 1.25)
        queue_terms.append(risk)
    queue_risk = sum(queue_terms) / len(queue_terms) if queue_terms else 0.0

    # -------------------------------------------------- ThemeRepetition
    theme_counts: dict[str, int] = {}
    for activity in attractions:
        poi = _poi_id(city, str(activity.get("position") or ""))
        for tag_id in THEME_TAG_IDS:
            if _tagged_utility(tags, poi, tag_id) in (1.0,):
                theme_counts[tag_id] = theme_counts.get(tag_id, 0) + 1
    excess = sum(max(0, count - 2) for count in theme_counts.values())
    theme_repetition = min(1.0, excess / 3.0)

    # ------------------------------------------------------- PriceDiscomfort
    prices = [float(a.get("price") or 0.0) for a in attractions]
    mean_price = sum(prices) / len(prices) if prices else 0.0
    price_term = min(1.0, mean_price / 200.0)

    # ------------------------------------------------------------ EditCost
    edit_cost = 0.0
    changed: list[dict] = []
    if previous is not None:
        before = [str(a.get("position") or "") for a in plan_activities(previous)
                  if a.get("type") == "attraction"]
        after = [str(a.get("position") or "") for a in attractions]
        removed = [name for name in before if name not in after]
        added = [name for name in after if name not in before]
        kept = [name for name in after if name in before]
        denominator = max(1, len(before) + len(added))
        edit_cost = min(1.0, (len(removed) + len(added)) / denominator)
        changed = [{"removed": name} for name in removed] + [{"added": name} for name in added]
        if kept:
            locked_missing = [name for name in profile.locked if name in before and name not in after]
            if locked_missing:
                edit_cost = 1.0
                changed.append({"locked_violated": locked_missing})

    components = {
        "match": round(match, 4),
        "travel_burden": round(travel_burden, 4),
        "fatigue_adjacency": round(fatigue, 4),
        "queue_crowd_risk": round(queue_risk, 4),
        "theme_repetition": round(theme_repetition, 4),
        "edit_cost": round(edit_cost, 4),
        "price_discomfort": round(price_term, 4),
    }
    penalties = {
        "travel_burden": options.lambda_travel * weights["walking_burden"] * components["travel_burden"],
        "fatigue_adjacency": options.lambda_fatigue * weights["fatigue_adjacency"] * components["fatigue_adjacency"],
        "queue_crowd_risk": options.lambda_queue * weights["queue_risk"] * components["queue_crowd_risk"],
        "theme_repetition": options.lambda_theme * weights["theme_repetition"] * components["theme_repetition"],
        "edit_cost": options.lambda_edit * weights["edit_cost"] * components["edit_cost"],
        "price_discomfort": options.lambda_price * weights["price"] * components["price_discomfort"],
    }
    q = components["match"] * weights["interest"] - sum(penalties.values())

    n_attr = len(attractions)
    coverage_rate = (len(set(tagged)) / n_attr) if n_attr else 0.0
    uncertainty = round(1.0 - coverage_rate, 3)
    return {
        "Q": round(q, 4),
        "components": components,
        "penalties": {key: round(value, 4) for key, value in penalties.items()},
        "weights": {key: round(value, 3) for key, value in weights.items()},
        "coverage": {
            "attractions": n_attr,
            "with_evidence": len(set(tagged)),
            "unknown": sorted(set(unknown)),
            "rate": round(coverage_rate, 3),
        },
        "uncertainty": uncertainty,
        "explanations": explanations,
        "itinerary_change": changed,
        "sandbox_version": plan.get("sandbox_version"),
        "tag_snapshot_id": plan.get("tag_snapshot_id"),
        "ranking_model_version": "rerank-v0.1",
        "preference_version": profile.version,
        "options": options.to_dict(),
        "note": "软评分，与官方 checker 分数无关；不得当作可行性或正确性结论",
    }


def rank_plans(
    candidates: list[dict],
    profile: UserProfile,
    tags: dict[str, dict],
    *,
    city: str | None = None,
    previous: dict | None = None,
    options: RerankOptions | None = None,
) -> list[dict]:
    """Order plans by Q without dropping any; each row keeps its full explanation."""
    rows = []
    for index, plan in enumerate(candidates):
        scored = score_plan(plan, profile, tags, city=city, previous=previous, options=options)
        rows.append({"candidate": index, "plan": plan, **scored})
    rows.sort(key=lambda row: (-row["Q"], row["candidate"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def describe_tag_support(tags: dict[str, dict]) -> dict:
    """Coverage of the tag table itself, so a report can show how thin the evidence is."""
    tag_counts: dict[str, int] = {}
    for per_poi in tags.values():
        for tag_id in per_poi:
            tag_counts[tag_id] = tag_counts.get(tag_id, 0) + 1
    return {
        "pois_with_any_tag": len(tags),
        "tags_present": sorted(tag_counts),
        "per_tag": dict(sorted(tag_counts.items(), key=lambda kv: -kv[1])),
        "taxonomy_size": len(TAXONOMY),
        "taxonomy_coverage": round(len(tag_counts) / len(TAXONOMY), 3),
        "interest_tags_covered": sorted(set(INTEREST_KEYS) & set(tag_counts)),
    }
