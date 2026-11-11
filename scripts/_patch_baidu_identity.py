"""Replace loose fuzzy identity with a strict, rule-labelled check.

Measured failure: `上海博物馆东馆` (East Pavilion) was accepted as `上海农垦博物馆`
because SequenceMatcher scored 0.714 >= the shared 0.7 threshold. Character
similarity is unsafe for short Chinese venue names, so the Baidu path now accepts
only: exact, alias-exact, sub-site of an exact parent, prefix/containment where the
extra part is a *facility/locator* word, or a geometric confirmation when an anchor
coordinate exists. Everything else abstains.
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"
text = TARGET.read_text(encoding="utf-8")

OLD_ID = '''def identity_check(request_name: str, returned_name: str, *, aliases: list[str] | None = None) -> dict:
    """Same POI, a sub-site of it, or noise?

    Baidu returns ``南越王博物院(王墓展区)`` for ``南越王博物院`` — the same museum
    complex, one gallery of it — while bad names return unrelated venues such as
    ``So Sorry``. The existing G2 gate only knows exact/prefix matching, so this
    adds the *sub-site* case and reports which rule fired.
    """
    from .sources import name_similarity

    ok, similarity = name_similarity(request_name, returned_name, aliases)
    if ok:
        return {"match": True, "similarity": similarity, "rule": "name_or_alias"}
    match = SUB_SITE_PATTERN.match(str(returned_name or ""))
    if match:
        parent_ok, parent_similarity = name_similarity(request_name, match.group("parent"), aliases)
        if parent_ok:
            return {
                "match": True,
                "similarity": round(max(similarity, parent_similarity), 3),
                "rule": "sub_site_of_requested_complex",
                "parent": match.group("parent"),
                "sub_site": match.group("child"),
            }
    return {"match": False, "similarity": similarity, "rule": "no_match"}'''

NEW_ID = '''# Words that can legitimately trail a venue name without naming a different venue:
# "广州塔景区", "南越王博物院(王墓展区)-东门", "广州塔-东广场".
LOCATOR_WORDS = (
    "景区", "旅游区", "园区", "风景区", "广场", "东门", "西门", "南门", "北门",
    "正门", "大门", "入口", "出口", "地铁口", "游客中心", "服务中心", "售票处",
)
MAX_IDENTITY_KM = 2.0


def identity_check(
    request_name: str,
    returned_name: str,
    *,
    aliases: list[str] | None = None,
    anchor: tuple[float, float] | None = None,
    poi_xy: tuple[float, float] | None = None,
) -> dict:
    """Same POI, a sub-site of it, or noise? Returns the rule that fired.

    Deliberately *not* using ``sources.name_similarity``'s 0.7 fuzzy threshold:
    measured on 2026-10-21, that threshold maps ``上海博物馆东馆`` to
    ``上海农垦博物馆`` (ratio 0.714), i.e. one museum onto a different museum.
    Abstaining is the correct behaviour when nothing better is available.
    """
    from difflib import SequenceMatcher

    from .sources import normalize_name

    wanted = normalize_name(request_name)
    loose = 0.0
    if wanted:
        loose = SequenceMatcher(None, wanted, normalize_name(returned_name)).ratio()
    if not wanted:
        return {"match": False, "similarity": 0.0, "rule": "empty_request"}

    texts: list[tuple[str, str]] = [(str(returned_name or ""), "name")]
    for alias in aliases or []:
        texts.append((str(alias), "alias"))

    # 1) exact (after dropping a trailing facility segment)
    for raw, kind in texts:
        got = normalize_name(strip_facility_suffix(raw) or raw)
        if got and got == wanted:
            return {"match": True, "similarity": 1.0, "rule": f"{kind}_exact", "matched": raw}

    # 2) sub-site of an exactly-named complex, e.g. 南越王博物院(王墓展区)
    match = SUB_SITE_PATTERN.match(strip_facility_suffix(str(returned_name or "")))
    if match and normalize_name(match.group("parent")) == wanted:
        return {
            "match": True,
            "similarity": 1.0,
            "rule": "sub_site_of_exact_parent",
            "parent": match.group("parent"),
            "sub_site": match.group("child"),
        }

    # 3) prefix / containment whose extra part is only a locator word
    for raw, kind in texts:
        got = normalize_name(strip_facility_suffix(raw) or raw)
        if not got or len(wanted) < 3:
            continue
        if got.startswith(wanted) or wanted.startswith(got):
            ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
            extra = got[len(wanted):] if got.startswith(wanted) else wanted[len(got):]
            if ratio >= 0.6 and any(word in extra for word in LOCATOR_WORDS):
                return {
                    "match": True,
                    "similarity": round(ratio, 3),
                    "rule": f"{kind}_prefix_locator",
                    "extra": extra,
                    "matched": raw,
                }

    # 4) geometric confirmation: a nearby point plus a loose name agreement
    if anchor and poi_xy and None not in anchor and None not in poi_xy:
        distance = km_between(anchor, poi_xy)
        if distance <= MAX_IDENTITY_KM and loose >= 0.5:
            return {
                "match": True,
                "similarity": round(loose, 3),
                "rule": "geo_near",
                "distance_km": round(distance, 2),
            }

    return {"match": False, "similarity": round(loose, 3), "rule": "abstain",
            "reason": "名称不足以确认同一景点，且无坐标佐证" if not anchor else "名称与坐标均不足"}


def identity_check_legacy(request_name: str, returned_name: str, *, aliases: list[str] | None = None) -> dict:
    """Old behaviour, kept for diffing the two rules on the same fixture set."""
    from .sources import name_similarity

    ok, similarity = name_similarity(request_name, returned_name, aliases)
    if ok:
        return {"match": True, "similarity": similarity, "rule": "name_or_alias(legacy)"}
    return {"match": False, "similarity": similarity, "rule": "no_match(legacy)"}'''

assert OLD_ID in text
text = text.replace(OLD_ID, NEW_ID, 1)

# candidate_score: use the strict check, accept an anchor, tighten the score maths
OLD_SCORE = '''def candidate_score(request_name: str, poi: dict) -> dict:
    """How likely is this search hit to be the venue the planner asked for?"""
    from .sources import normalize_name

    info = poi.get("detail_info") or {}
    name = str(poi.get("name") or "")
    aliases = _split_tags(info.get("alias")) + _split_tags(info.get("new_alias"))
    verdict = identity_check(request_name, strip_facility_suffix(name) or name, aliases=aliases)
    if not verdict.get("match"):
        # also try the raw name, so a genuine "...(分馆)" match is not lost
        verdict = identity_check(request_name, name, aliases=aliases)'''

NEW_SCORE = '''def candidate_score(
    request_name: str, poi: dict, *, anchor: tuple[float, float] | None = None
) -> dict:
    """How likely is this search hit to be the venue the planner asked for?"""
    from .sources import normalize_name

    info = poi.get("detail_info") or {}
    name = str(poi.get("name") or "")
    aliases = _split_tags(info.get("alias")) + _split_tags(info.get("new_alias"))
    location = poi.get("location") or {}
    poi_xy = None
    try:
        poi_xy = (float(location["lat"]), float(location["lng"]))
    except (KeyError, TypeError, ValueError):
        poi_xy = None
    verdict = identity_check(request_name, name, aliases=aliases, anchor=anchor, poi_xy=poi_xy)'''

assert OLD_SCORE in text
text = text.replace(OLD_SCORE, NEW_SCORE, 1)

OLD_RANK = '''def rank_candidates(request_name: str, pois: list[dict]) -> list[dict]:
    scored = [(candidate_score(request_name, poi), index, poi) for index, poi in enumerate(pois)]'''
NEW_RANK = '''def rank_candidates(
    request_name: str, pois: list[dict], *, anchor: tuple[float, float] | None = None
) -> list[dict]:
    scored = [(candidate_score(request_name, poi, anchor=anchor), index, poi) for index, poi in enumerate(pois)]'''
assert OLD_RANK in text
text = text.replace(OLD_RANK, NEW_RANK, 1)

# source adapter: thread an optional anchor through
OLD_SIG = '''    def fetch(self, name: str, city: str) -> Evidence:
        at = utcnow()
        url = f"{HOST}{SEARCH_V2}"
        attempts: list[dict] = []'''
NEW_SIG = '''    def fetch(self, name: str, city: str, anchor: tuple[float, float] | None = None) -> Evidence:
        at = utcnow()
        url = f"{HOST}{SEARCH_V2}"
        attempts: list[dict] = []'''
assert OLD_SIG in text
text = text.replace(OLD_SIG, NEW_SIG, 1)

text = text.replace("ranked = rank_candidates(name, results)", "ranked = rank_candidates(name, results, anchor=anchor)", 1)
text = text.replace('"cached": bool(payload.get("_cached")),', '"cached": bool(payload.get("_cached")),\n            "anchor": list(anchor) if anchor else None,', 1)

TARGET.write_text(text, encoding="utf-8")
print("strict identity patch applied")
