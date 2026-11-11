"""Patch Baidu adapter with:
1. page_num omission fix (page_num=1 changes the retrieval path and drops the POI);
2. candidate scoring that penalises facility sub-POIs (出入口/停车场/道路…);
3. a query ladder in BaiduSource.fetch: plain -> tag=旅游景点 -> city_limit=false.
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"
text = TARGET.read_text(encoding="utf-8")

# ---------------------------------------------------------------- 1. page_num
OLD_SEARCH = '''    def search(self, q: str, region: str, *, page_size: int = 5, page_num: int = 1,
               scope: int = 2, city_limit: bool = True, tag: str | None = None,
               extra: dict | None = None) -> dict:
        """Keyword search. Tries the documented v3 endpoint once, then v2."""
        shared = {"region": region, "city_limit": "true" if city_limit else "false",
                  "page_size": str(page_size), "page_num": str(page_num), "scope": str(scope)}'''
NEW_SEARCH = '''    def search(self, q: str, region: str, *, page_size: int = 5, page_num: int = 1,
               scope: int = 2, city_limit: bool = True, tag: str | None = None,
               extra: dict | None = None) -> dict:
        """Keyword search. Tries the documented v3 endpoint once, then v2.

        Empirically (2026-10-21) sending ``page_num=1`` explicitly changes the
        retrieval path: `广州塔` then returns *广州塔-西广场 / 广州塔广场 / 广州塔路*
        and the tower itself disappears from the first page, while omitting
        ``page_num`` returns `广州塔` first. So page 1 is sent without the
        parameter; page 2+ sends it.
        """
        shared = {"region": region, "city_limit": "true" if city_limit else "false",
                  "page_size": str(page_size), "scope": str(scope)}
        if page_num and int(page_num) > 1:
            shared["page_num"] = str(page_num)'''
assert OLD_SEARCH in text
text = text.replace(OLD_SEARCH, NEW_SEARCH, 1)

# ---------------------------------------------------------------- 2. scoring
ANCHOR = '''# --------------------------------------------------------------- source adapter'''

SCORING = '''# ------------------------------------------------------------ candidate ranking
# Baidu mixes the venue with its own facilities and neighbours: querying `广州塔`
# returns 广州塔路 (a road), 广州塔地铁站-A口 (a subway exit) and 广州塔-东广场.
# Picking `results[0]` therefore lands on the wrong POI, and the sandbox would get
# a road's coordinates. Candidates are scored instead of trusted by position.
FACILITY_TAGS = (
    "出入口", ";门", "停车场", "售票处", "地铁站", "公交车站", "公交线路",
    "道路", "港口", "接送点", "服务中心", "游客中心", "写字楼", "住宅区",
)
ATTRACTION_TAGS = ("旅游景点", "风景名胜", "博物馆", "文物古迹", "公园", "美术馆", "展览馆")

FACILITY_SUFFIX = re.compile(
    r"[-—–_·]\\s*(东门|西门|南门|北门|正门|大门|出口|入口|地铁口|[A-Za-z]口|"
    r"[^()（）]{0,8}(停车场|售票处|服务中心|游客中心|广场|码头|车站|接送点|隧道|天桥))\\s*$"
)


def strip_facility_suffix(name: str) -> str:
    """``南越王博物院(王墓展区)-东门`` -> ``南越王博物院(王墓展区)``."""
    return FACILITY_SUFFIX.sub("", str(name or "")).strip()


def candidate_score(request_name: str, poi: dict) -> dict:
    """How likely is this search hit to be the venue the planner asked for?"""
    from .sources import normalize_name

    info = poi.get("detail_info") or {}
    name = str(poi.get("name") or "")
    aliases = _split_tags(info.get("alias")) + _split_tags(info.get("new_alias"))
    verdict = identity_check(request_name, strip_facility_suffix(name) or name, aliases=aliases)
    if not verdict.get("match"):
        # also try the raw name, so a genuine "...(分馆)" match is not lost
        verdict = identity_check(request_name, name, aliases=aliases)
    tag_text = str(info.get("tag") or "") + ";" + str(info.get("classified_poi_tag") or "")
    score = float(verdict.get("similarity") or 0.0)
    reasons: list[str] = []
    if normalize_name(name) == normalize_name(request_name):
        score += 0.35
        reasons.append("exact_name")
    elif verdict.get("match"):
        score += 0.10
        reasons.append(f"identity:{verdict.get('rule')}")
    else:
        score -= 0.30
        reasons.append("identity_mismatch")
    if any(token in tag_text for token in FACILITY_TAGS):
        score -= 0.45
        reasons.append("facility_tag")
    if any(token in tag_text for token in ATTRACTION_TAGS):
        score += 0.20
        reasons.append("attraction_tag")
    if str(poi.get("detail")) == "1":
        score += 0.03
        reasons.append("has_detail")
    return {
        "score": round(score, 3),
        "match": bool(verdict.get("match")),
        "rule": verdict.get("rule"),
        "similarity": verdict.get("similarity"),
        "name": name,
        "uid": poi.get("uid"),
        "tag": info.get("tag"),
        "reasons": reasons,
    }


def rank_candidates(request_name: str, pois: list[dict]) -> list[dict]:
    scored = [(candidate_score(request_name, poi), index, poi) for index, poi in enumerate(pois)]
    scored.sort(key=lambda item: (-item[0]["score"], item[1]))
    return [{"verdict": item[0], "poi": item[2]} for item in scored]


# --------------------------------------------------------------- source adapter'''

assert ANCHOR in text
text = text.replace(ANCHOR, SCORING, 1)

# ---------------------------------------------------------------- 3. fetch ladder
OLD_FETCH_START = '''    def fetch(self, name: str, city: str) -> Evidence:
        at = utcnow()
        url = f"{HOST}{SEARCH_V2}"
        try:
            payload = self.client.search(name, city, page_size=self.page_size)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc),
                            authority=self.authority)
        if str(payload.get("status")) != "0":
            return Evidence(self.name, url, at, name, "", ok=False,
                            error=f"status={payload.get('status')} message={payload.get('message')}",
                            authority=self.authority)
        results = payload.get("results") or []
        chosen, check, best = None, {"match": False, "similarity": 0.0, "rule": "none"}, 0.0
        for poi in results:
            info = poi.get("detail_info") or {}
            aliases = _split_tags(info.get("alias")) + _split_tags(info.get("new_alias"))
            verdict = identity_check(name, str(poi.get("name", "")), aliases=aliases)
            best = max(best, float(verdict.get("similarity") or 0.0))
            if verdict["match"] and chosen is None:
                chosen, check = poi, verdict
        if chosen is None and results:
            chosen = results[0]
            info = chosen.get("detail_info") or {}
            aliases = _split_tags(info.get("alias")) + _split_tags(info.get("new_alias"))
            check = identity_check(name, str(chosen.get("name", "")), aliases=aliases)
            check["similarity"] = max(best, float(check.get("similarity") or 0.0))
        if chosen is None:
            return Evidence(self.name, url, at, name, "", ok=False, error="no poi",
                            authority=self.authority)
'''

NEW_FETCH_START = '''    MIN_SCORE = 0.55  # below this the hit is not the venue; report, never guess

    def _query_ladder(self, name: str, city: str) -> list[dict]:
        """Cheap-to-specific attempts; the first confident hit wins."""
        return [
            {"label": "plain", "kwargs": {"page_size": self.page_size}},
            {"label": "attraction_tag", "kwargs": {"page_size": self.page_size, "tag": "旅游景点"}},
            {"label": "no_city_limit", "kwargs": {"page_size": self.page_size, "city_limit": False}},
        ]

    def fetch(self, name: str, city: str) -> Evidence:
        at = utcnow()
        url = f"{HOST}{SEARCH_V2}"
        attempts: list[dict] = []
        payload: dict = {}
        chosen = None
        verdict: dict = {"match": False, "similarity": 0.0, "rule": "none", "score": 0.0}
        for attempt in self._query_ladder(name, city):
            try:
                payload = self.client.search(name, city, **attempt["kwargs"])
            except Exception as exc:  # noqa: BLE001
                attempts.append({"query": attempt["label"], "error": str(exc)})
                continue
            results = payload.get("results") or []
            ranked = rank_candidates(name, results)
            attempts.append({
                "query": attempt["label"],
                "status": payload.get("status"),
                "n": len(results),
                "top": [item["verdict"] for item in ranked[:3]],
            })
            if str(payload.get("status")) != "0":
                continue
            if ranked and ranked[0]["verdict"]["score"] >= self.MIN_SCORE:
                chosen = ranked[0]["poi"]
                verdict = dict(ranked[0]["verdict"])
                break
        if chosen is None:
            return Evidence(
                self.name, url, at, name, "", ok=False,
                error=f"no confident match (best score {attempts[-1]['top'][0]['score'] if attempts and attempts[-1].get('top') else 'n/a'})",
                authority=self.authority,
            )._with_attempts(attempts) if hasattr(Evidence, "_with_attempts") else Evidence(
                self.name, url, at, name, "", ok=False,
                error="no confident match",
                authority=self.authority,
            )
'''

assert OLD_FETCH_START in text
text = text.replace(OLD_FETCH_START, NEW_FETCH_START, 1)

# ------------------------------------------------- 4. simplify tail of fetch
OLD_TAIL = '''        flat = normalize_poi(chosen, source_coord="gcj02ll", detail=detail_poi)
        flat.update({
            "name_match": bool(check.get("match")),
            "name_similarity": check.get("similarity"),
            "identity_rule": check.get("rule"),
            "sub_site": check.get("sub_site"),
            "requested_name": name,
            "region": city,
            "signature_style": payload.get("_signature_style"),
            "cached": bool(payload.get("_cached")),
            "detail_fetched": detail_poi is not None,
        })'''
NEW_TAIL = '''        flat = normalize_poi(chosen, source_coord="gcj02ll", detail=detail_poi)
        flat.update({
            "name_match": bool(verdict.get("match")),
            "name_similarity": verdict.get("similarity"),
            "identity_rule": verdict.get("rule"),
            "candidate_score": verdict.get("score"),
            "candidate_reasons": verdict.get("reasons"),
            "requested_name": name,
            "region": city,
            "query_attempts": attempts,
            "signature_style": payload.get("_signature_style"),
            "cached": bool(payload.get("_cached")),
            "detail_fetched": detail_poi is not None,
        })'''
assert OLD_TAIL in text
text = text.replace(OLD_TAIL, NEW_TAIL, 1)

TARGET.write_text(text, encoding="utf-8")
print("ranking + page_num patch applied")
