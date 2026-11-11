"""M5: user preference profile.

Design rules taken from the task specification:

* A preference is a relation ``user x time x POI x trip context`` — not a global
  "attraction score". The same museum is good for a family and bad for someone who
  cannot walk far.
* ``必须 / 不能 / 最多 / 至少`` become *hard constraint candidates* and are handed to
  the rule layer (the official DSL checker), never to the soft scorer.
* ``尽量 / 更喜欢 / 不太想`` become soft weights, and the user may change them.
* Every item records where it came from (explicit statement, dialogue inference, or
  a documented neutral prior) and how confident we are. A user correction outranks
  an older inference.
* Anything the user did not say stays ``None``. A neutral prior is labelled as such
  so the report can say "this ranking leans on an unconfirmed assumption".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

PROVENANCE = ("user_explicit", "dialogue_inferred", "default_prior")
PROVENANCE_WEIGHT = {"user_explicit": 1.0, "dialogue_inferred": 0.75, "default_prior": 0.5}

INTEREST_KEYS = ("history_culture", "nature", "architecture", "photography",
                 "family", "romantic", "night_view")

# Chinese cues for the light deterministic parser. Each hit is recorded as
# `dialogue_inferred` and can be overridden by an explicit spec.
CUE_RULES: list[tuple[str, str, object]] = [
    (r"老人|父母|长辈|带爸|带妈|爷爷|奶奶", "with_elders", True),
    (r"小孩|孩子|儿童|宝宝|亲子|带娃", "with_children", True),
    (r"历史|文化|博物馆|古迹|博物", "interest.history_culture", True),
    (r"自然|山水|风景|爬山|湖|森林", "interest.nature", True),
    (r"建筑|古建|设计|地标", "interest.architecture", True),
    (r"拍照|摄影|出片|打卡", "interest.photography", True),
    (r"情侣|约会|浪漫|二人", "interest.romantic", True),
    (r"夜景|夜游|晚上", "interest.night_view", True),
    (r"预算|省钱|便宜|穷游|学生", "price_sensitivity", 0.8),
    (r"不差钱|预算充足|高端", "price_sensitivity", 0.2),
    (r"腿脚|不能走|少走路|无障碍|轮椅", "walking_tolerance", 0.25),
    (r"能走|暴走|徒步|多走", "walking_tolerance", 0.85),
    (r"(?:可以|愿意|能接受|不介意)排队", "max_queue", 1.0),
    (r"不想排队|不要排队|少排队|怕排队|不要挤|人少|避开人多", "max_queue", 0.3),
    (r"室内|怕晒|怕热|下雨", "indoor_preference", True),
]
_CUES = [(re.compile(pattern), key, value) for pattern, key, value in CUE_RULES]

HARD_CUES = [
    (re.compile(r"必须|一定要|务必|必去"), "must_visit"),
    (re.compile(r"不去|不要去|排除|不想去"), "avoid"),
]


@dataclass
class PreferenceItem:
    key: str
    value: object
    source: str = "default_prior"
    confidence: float = 0.5
    note: str = ""

    def __post_init__(self) -> None:
        if self.source not in PROVENANCE:
            raise ValueError(f"unknown provenance: {self.source}")
        self.confidence = float(self.confidence)

    @property
    def effective_weight(self) -> float:
        return round(PROVENANCE_WEIGHT[self.source] * self.confidence, 4)

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "source": self.source,
                "confidence": round(self.confidence, 3),
                "effective_weight": self.effective_weight, "note": self.note}


@dataclass
class UserProfile:
    """Everything the planner is allowed to assume about the traveller."""

    uid: str = "anonymous"
    people: int = 1
    with_elders: bool | None = None
    with_children: bool | None = None
    walking_tolerance: float | None = None      # 0 = cannot walk far, 1 = fine with 20k steps
    max_queue: float | None = None              # 0 = hates queues, 1 = indifferent
    price_sensitivity: float | None = None      # 0 = price-blind, 1 = very price sensitive
    indoor_preference: bool | None = None
    night_preference: bool | None = None
    interests: dict[str, float] = field(default_factory=dict)
    must_visit: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)   # confirmed by the user
    items: list[PreferenceItem] = field(default_factory=list)
    neutral_priors: list[str] = field(default_factory=list)
    version: str = "pref-v0.1"

    # ------------------------------------------------------------------ build
    @classmethod
    def from_spec(cls, spec: dict) -> "UserProfile":
        """Build from an explicit structured spec (highest trust)."""
        profile = cls(uid=str(spec.get("uid", "anonymous")))
        profile.people = int(spec.get("people", 1))
        mapping = {
            "with_elders": "with_elders", "with_children": "with_children",
            "walking_tolerance": "walking_tolerance", "max_queue": "max_queue",
            "price_sensitivity": "price_sensitivity", "indoor_preference": "indoor_preference",
            "night_preference": "night_preference",
        }
        for key, attr in mapping.items():
            if key in spec and spec[key] is not None:
                setattr(profile, attr, spec[key])
                profile.items.append(PreferenceItem(
                    key=attr, value=spec[key], source="user_explicit", confidence=1.0,
                    note="结构化偏好显式给出"))
        for key, weight in (spec.get("interests") or {}).items():
            if key not in INTEREST_KEYS:
                continue
            profile.interests[key] = float(weight)
            profile.items.append(PreferenceItem(
                key=f"interest.{key}", value=float(weight), source="user_explicit",
                confidence=1.0))
        for name, attr in (("must_visit", "must_visit"), ("avoid", "avoid"), ("locked", "locked")):
            values = list(spec.get(name) or [])
            setattr(profile, attr, values)
            for value in values:
                profile.items.append(PreferenceItem(
                    key=attr, value=value, source="user_explicit", confidence=1.0,
                    note="硬约束候选，交由官方 DSL checker 判定"))
        return profile

    @classmethod
    def from_query(cls, query: dict, spec: dict | None = None) -> "UserProfile":
        """Parse the ChinaTravel query's Chinese ``nature_language``, then overlay spec."""
        profile = cls.from_spec({**(spec or {}), "people": query.get("people_number", 1),
                                 "uid": str(query.get("uid", "anonymous"))})
        text = str(query.get("nature_language") or "")
        profile._parse_cues(text)
        profile._fill_neutral_priors()
        return profile

    def _parse_cues(self, text: str) -> None:
        if not text:
            return
        for pattern, key, value in _CUES:
            matches = list(pattern.finditer(text))
            if not matches:
                continue
            if key.startswith("interest."):
                # A bare theme word inside a negated request is not a positive
                # interest. Candidate matching handles the specific avoided
                # activity; don't turn dislike of hiking into dislike of nature.
                def positive(match):
                    prefix = re.split(r"[，。；！？,;]|但是|但|不过", text[:match.start()])[-1]
                    return not re.search(r"(?:不喜欢|不想|不爱|不要|讨厌|排除|避开)[^，。；！？]{0,6}$", prefix)
                if not any(positive(match) for match in matches):
                    continue
                interest = key.split(".", 1)[1]
                if interest in self.interests:
                    continue
                self.interests[interest] = 1.0
                self.items.append(PreferenceItem(
                    key=key, value=1.0, source="dialogue_inferred", confidence=0.75,
                    note=f"从文本「{pattern.pattern}」推断"))
            else:
                current = getattr(self, key, None)
                if current is not None:
                    continue
                setattr(self, key, value)
                self.items.append(PreferenceItem(
                    key=key, value=value, source="dialogue_inferred", confidence=0.65,
                    note=f"从文本「{pattern.pattern}」推断"))
        for pattern, attr in HARD_CUES:
            for match in pattern.finditer(text):
                tail = text[match.end():match.end() + 12]
                target = re.split(r"[，。；、\s]", tail)[0]
                if len(target) < 2:
                    continue
                bucket = getattr(self, attr)
                if target not in bucket:
                    bucket.append(target)
                    self.items.append(PreferenceItem(
                        key=attr, value=target, source="dialogue_inferred", confidence=0.6,
                        note="疑似硬约束，需用户确认后才交给 checker"))

    def _fill_neutral_priors(self) -> None:
        """Unknown stays unknown for scoring, but record that a neutral prior was used."""
        for attr in ("walking_tolerance", "max_queue", "price_sensitivity",
                     "indoor_preference", "night_preference"):
            if getattr(self, attr) is None:
                self.neutral_priors.append(attr)
                self.items.append(PreferenceItem(
                    key=attr, value=None, source="default_prior", confidence=0.3,
                    note="用户未提及，排序时按中性先验处理，不当作确定偏好"))
        for interest in INTEREST_KEYS:
            if interest not in self.interests:
                self.neutral_priors.append(f"interest.{interest}")

    # ------------------------------------------------------------------ edits
    def correct(self, key: str, value, *, note: str = "") -> None:
        """A user correction outranks every inference (spec §8)."""
        if key.startswith("interest."):
            self.interests[key.split(".", 1)[1]] = float(value)
        elif key in ("must_visit", "avoid", "locked"):
            bucket = getattr(self, key)
            if value not in bucket:
                bucket.append(value)
        else:
            setattr(self, key, value)
        for existing in self.items:
            if existing.key == key:
                existing.source = "default_prior"
                existing.confidence = min(existing.confidence, 0.2)
        self.items.append(PreferenceItem(key=key, value=value, source="user_explicit",
                                         confidence=1.0, note=note or "用户更正"))

    # ------------------------------------------------------------------ query
    def weights(self) -> dict[str, float]:
        """Turn the profile into bounded scoring weights (0..1)."""
        def num(value, default=0.5):
            return default if value is None else float(value)

        elder = 1.0 if self.with_elders else 0.0
        child = 1.0 if self.with_children else 0.0
        return {
            "interest": 1.0,
            "walking_burden": 0.6 * (1.0 - num(self.walking_tolerance, 0.6)) + 0.25 * elder + 0.15 * child,
            "queue_risk": 0.5 + 0.5 * (1.0 - num(self.max_queue, 0.5)),
            "fatigue_adjacency": 0.5 + 0.5 * elder + 0.3 * child,
            "theme_repetition": 0.4,
            "price": 0.6 * num(self.price_sensitivity, 0.3),
            "indoor": 0.8 if self.indoor_preference else 0.0,
            "edit_cost": 0.7,
        }

    def interest_vector(self) -> dict[str, float]:
        """Interest weights normalised to 1.0 in total; unmentioned interests = 0."""
        raw = {key: float(self.interests.get(key, 0.0)) for key in INTEREST_KEYS}
        total = sum(raw.values())
        if total <= 0:
            return {key: 0.0 for key in raw}
        return {key: round(value / total, 4) for key, value in raw.items()}

    def high_gain_questions(self, limit: int = 3) -> list[dict]:
        """At most ``limit`` questions, only about unknowns that move the ranking."""
        pool = [
            ("walking_tolerance", "同行有没有走不了太久的人（老人/小孩/腿脚不便）？",
             "直接决定体力惩罚的权重，影响最大"),
            ("max_queue", "能接受排队多久？",
             "决定节假日热门景点的惩罚强度"),
            ("interests", "这次更想看历史/自然/建筑/拍照中的哪几类？",
             "决定匹配项，是排序的主项"),
            ("price_sensitivity", "门票价格敏感吗？",
             "决定是否优先免费或低价景点"),
        ]
        out = []
        for key, question, why in pool:
            if key == "interests":
                unknown = not self.interests
            else:
                unknown = getattr(self, key, None) is None
            if unknown:
                out.append({"key": key, "question": question, "why": why})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ dumps
    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "version": self.version, "people": self.people,
            "with_elders": self.with_elders, "with_children": self.with_children,
            "walking_tolerance": self.walking_tolerance, "max_queue": self.max_queue,
            "price_sensitivity": self.price_sensitivity,
            "indoor_preference": self.indoor_preference,
            "night_preference": self.night_preference,
            "interests": self.interests, "must_visit": self.must_visit,
            "avoid": self.avoid, "locked": self.locked,
            "weights": self.weights(), "interest_vector": self.interest_vector(),
            "items": [item.to_dict() for item in self.items],
            "neutral_priors": self.neutral_priors,
            "open_questions": self.high_gain_questions(),
        }

    def summary(self) -> str:
        parts = [f"people={self.people}"]
        if self.with_elders:
            parts.append("with_elders")
        if self.with_children:
            parts.append("with_children")
        if self.interests:
            parts.append("interests=" + ",".join(sorted(self.interests)))
        if self.must_visit:
            parts.append("must=" + ",".join(self.must_visit))
        return " ".join(parts)


def profiles_from_specs(specs: Iterable[dict]) -> list[UserProfile]:
    return [UserProfile.from_spec(spec) for spec in specs]


DEFAULT_SPECS = [
    {"uid": "family_kids", "people": 3, "with_children": True, "walking_tolerance": 0.4,
     "max_queue": 0.35, "price_sensitivity": 0.65,
     "interests": {"history_culture": 0.8, "family": 1.0, "photography": 0.4}},
    {"uid": "senior_slow", "people": 2, "with_elders": True, "walking_tolerance": 0.15,
     "max_queue": 0.2, "indoor_preference": True,
     "interests": {"history_culture": 1.0, "nature": 0.3}},
    {"uid": "photo_young", "people": 2, "walking_tolerance": 0.85, "max_queue": 0.7,
     "price_sensitivity": 0.3, "night_preference": True,
     "interests": {"photography": 1.0, "architecture": 0.8, "night_view": 0.7}},
    {"uid": "budget_student", "people": 1, "walking_tolerance": 0.8, "max_queue": 0.4,
     "price_sensitivity": 1.0,
     "interests": {"history_culture": 0.6, "nature": 0.6}},
    {"uid": "culture_buff", "people": 2, "walking_tolerance": 0.6, "max_queue": 0.5,
     "interests": {"history_culture": 1.0, "architecture": 0.7}},
]
