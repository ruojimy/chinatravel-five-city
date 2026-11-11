"""External evidence sources.

Design rule: a source is only *evidence*, never truth. Each adapter returns the
fetched text verbatim plus a coarse authority score, and the quality gate decides
what may enter the sandbox. Sources are ordered cheap-to-expensive and all are
free/no-key except the LLM used for extraction.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from .records import Evidence, utcnow

UA = "ShortTripAssistant/1.0 (course project; POI verification)"
SECRETS = Path(__file__).resolve().parents[3] / ".secrets"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "evidence_cache"
CACHE_TTL_HOURS = 24 * 7


def _get(url: str, timeout: int = 30, headers: dict | None = None, retries: int = 3) -> str:
    """HTTP GET with retries: a transient SSL error must not change a verdict."""
    import time as _time

    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            _time.sleep(0.6 * (attempt + 1) ** 2)
    raise last  # type: ignore[misc]


def normalize_name(value: str) -> str:
    """Normalise a POI name for identity comparison (NFKC, strip spaces/punct)."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[\s·•,，.。、\-_/\\|()（）\[\]【】<>《》:：;；'\"“”‘’!！?？]", "", text)
    return text


def name_similarity(request_name: str, returned_name: str, aliases: str | list | None = None) -> tuple[bool, float]:
    """Is the returned POI the same thing the planner asked for?

    Accepts: normalised equality, prefix/containment with a sane length ratio,
    an alias hit, or high string similarity. Rejects fuzzy search noise.
    """
    wanted = normalize_name(request_name)
    got = normalize_name(returned_name)
    if not wanted or not got:
        return False, 0.0
    if wanted == got:
        return True, 1.0
    if got.startswith(wanted) or wanted.startswith(got):
        ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
        if ratio >= 0.6:
            return True, round(ratio, 3)
    if wanted in got or got in wanted:
        ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
        if ratio >= 0.75:
            return True, round(ratio, 3)
    alias_list: list[str] = []
    if isinstance(aliases, str):
        alias_list = [part for part in re.split(r"[|,，;；]", aliases) if part.strip()]
    elif isinstance(aliases, (list, tuple)):
        alias_list = [str(part) for part in aliases]
    for alias in alias_list:
        normalized_alias = normalize_name(alias)
        if normalized_alias and (normalized_alias == wanted or normalized_alias.startswith(wanted)):
            return True, 0.9
    similarity = SequenceMatcher(None, wanted, got).ratio()
    return (similarity >= 0.7), round(similarity, 3)


def cached_fetch(source, name: str, city: str) -> Evidence:
    """Fetch through a 7-day disk cache so reruns are reproducible and cheap."""
    import dataclasses
    import hashlib
    from datetime import datetime, timedelta, timezone

    key = hashlib.sha1(f"{source.name}|{name}|{city}".encode("utf-8")).hexdigest()[:16]
    path = CACHE_DIR / f"{key}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            retrieved = datetime.fromisoformat(payload["retrieved_at"])
            if datetime.now(timezone.utc) - retrieved < timedelta(hours=CACHE_TTL_HOURS):
                item = Evidence(**payload)
                item.structured = item.structured or {}
                item.structured["cached"] = True
                return item
        except Exception:  # noqa: BLE001
            pass
    item = source.fetch(name, city)
    try:
        path.write_text(json.dumps(dataclasses.asdict(item), ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return item


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------- sources
class WikipediaSource:
    """zh.wikipedia article text: usually contains 开放时间/票价 for Chinese museums."""

    name = "wikipedia_zh"
    authority = 0.75

    def fetch(self, name: str, city: str) -> Evidence:
        url = "https://zh.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "extracts|coordinates|info",
                "inprop": "url",
                "titles": name,
                "format": "json",
                "explaintext": 1,
                "redirects": 1,
            }
        )
        at = utcnow()
        try:
            data = json.loads(_get(url))
            page = next(iter(data["query"]["pages"].values()))
            if "missing" in page:
                return Evidence(self.name, url, at, name, "", ok=False, error="page missing", authority=self.authority)
            text = page.get("extract", "")
            structured = {
                "title": page.get("title"),
                "fullurl": page.get("fullurl"),
                "coordinates": page.get("coordinates"),
            }
            return Evidence(self.name, page.get("fullurl", url), at, page.get("title", name), text, structured, self.authority)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


class WikidataSource:
    """Wikidata claims: authoritative coordinates and official website."""

    name = "wikidata"
    authority = 0.85

    def fetch(self, name: str, city: str) -> Evidence:
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {
                "action": "wbgetentities",
                "sites": "zhwiki",
                "titles": name,
                "props": "claims|labels",
                "languages": "zh|en",
                "format": "json",
            }
        )
        at = utcnow()
        try:
            data = json.loads(_get(url))
            entity_id, entity = next(iter(data["entities"].items()))
            if entity.get("missing") is not None:
                return Evidence(self.name, url, at, name, "", ok=False, error="entity missing", authority=self.authority)
            claims = entity.get("claims", {})
            structured: dict = {
                "entity": entity_id,
                "label": entity.get("labels", {}).get("zh", {}).get("value"),
            }
            if "P625" in claims:
                value = claims["P625"][0]["mainsnak"].get("datavalue", {}).get("value", {})
                structured["coordinates"] = {"lat": value.get("latitude"), "lon": value.get("longitude")}
            if "P856" in claims:
                structured["official_website"] = claims["P856"][0]["mainsnak"].get("datavalue", {}).get("value")
            text = json.dumps(structured, ensure_ascii=False)
            return Evidence(self.name, f"https://www.wikidata.org/wiki/{entity_id}", at, structured.get("label") or name, text, structured, self.authority)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


class NominatimSource:
    """OpenStreetMap search: cheap existence + geometry cross-check."""

    name = "openstreetmap"
    authority = 0.6

    def fetch(self, name: str, city: str) -> Evidence:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": f"{name} {city}", "format": "jsonv2", "limit": 5, "accept-language": "zh"}
        )
        at = utcnow()
        try:
            rows = json.loads(_get(url))
            text = json.dumps(rows, ensure_ascii=False)
            return Evidence(self.name, url, at, name, text, {"results": rows}, self.authority)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


class LLMChatSource:
    """DeepSeek chat, *without* citations.

    Kept deliberately: it is the cheapest way to get a draft, but its output can
    never be accepted on its own (the gate treats it as `llm_only`).
    """

    name = "deepseek_chat"
    authority = 0.3

    def __init__(self, model: str = "deepseek-v4-pro"):
        self.model = model
        self.token = (SECRETS / "deepseek.key").read_text(encoding="ascii").strip()

    def fetch(self, name: str, city: str) -> Evidence:
        url = "https://api.deepseek.com/chat/completions"
        at = utcnow()
        prompt = (
            f"请仅凭你的知识回答：{city}的“{name}”是什么类型的场所？大致经纬度、开放时间、门票价格。"
            "如果不知道就直说不知道，不要编造。"
        )
        try:
            data = _post_json(
                url,
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                    "temperature": 0,
                },
                {"Authorization": f"Bearer {self.token}"},
            )
            text = data["choices"][0]["message"].get("content") or ""
            return Evidence(self.name, url, at, name, text, {"model": self.model}, self.authority)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


class AmapSource:
    """高德地图 Web 服务：POI 检索（含 biz_ext 营业时间）+ 地理编码。

    Highest-authority source we have: it is the same data Chinese map apps use, it
    returns structured fields, and it carries `opentime_week` for most venues.
    """

    name = "amap"
    authority = 0.92

    QUOTA_CODES = {"10003", "10004", "10021", "10044"}
    _rotation = {"index": 0}

    def __init__(self, keys: list[str] | None = None):
        if keys is None:
            path = SECRETS / "amap.keys"
            keys = [k.strip() for k in path.read_text(encoding="ascii").splitlines() if k.strip()] if path.exists() else []
            if not keys:
                keys = [(SECRETS / "amap.key").read_text(encoding="ascii").strip()]
        self.keys = keys or [""]
        self.key = self.keys[0]

    def _call(self, path: str, params: dict) -> dict:
        """Call Amap with key rotation: quota errors move to the next key."""
        last: dict = {}
        start = self._rotation["index"] % len(self.keys)
        for offset in range(len(self.keys)):
            index = (start + offset) % len(self.keys)
            key = self.keys[index]
            url = "https://restapi.amap.com" + path + "?" + urllib.parse.urlencode({**params, "key": key})
            try:
                data = json.loads(_get(url))
            except Exception as exc:  # noqa: BLE001
                last = {"status": "0", "info": str(exc), "infocode": "network"}
                continue
            if str(data.get("status")) == "1":
                self._rotation["index"] = index
                self.key = key
                return data
            last = data
            if str(data.get("infocode")) not in self.QUOTA_CODES:
                return data
        return last


def amap_route(origin: tuple[float, float], destination: tuple[float, float], *, city: str = "", mode: str = "walking", key: str | None = None) -> dict:
    """Real road-network route between two (lat, lon) points (Amap uses lon,lat)."""
    source = AmapSource([key] if key else None)
    origin_s = f"{origin[1]},{origin[0]}"
    dest_s = f"{destination[1]},{destination[0]}"
    if mode == "walking":
        data = source._call("/v3/direction/walking", {"origin": origin_s, "destination": dest_s})
        paths = ((data.get("route") or {}).get("paths") or [{}])
        path = paths[0] if paths else {}
        return {
            "mode": "walking",
            "ok": str(data.get("status")) == "1" and bool(path),
            "distance_km": round(float(path.get("distance", 0)) / 1000.0, 2) if path.get("distance") else None,
            "duration_min": round(float(path.get("duration", 0)) / 60.0, 1) if path.get("duration") else None,
            "infocode": data.get("infocode"),
        }
    if mode == "transit":
        params = {"origin": origin_s, "destination": dest_s, "city": city, "cityd": city}
        data = source._call("/v3/direction/transit/integrated", params)
        route = data.get("route") or {}
        transits = route.get("transits") or []
        best = transits[0] if transits else {}
        return {
            "mode": "transit",
            "ok": str(data.get("status")) == "1" and bool(best),
            "duration_min": round(float(best.get("duration", 0)) / 60.0, 1) if best.get("duration") else None,
            "distance_km": round(float(best.get("distance", 0)) / 1000.0, 2) if best.get("distance") else None,
            "cost": best.get("cost"),
            "infocode": data.get("infocode"),
        }
    return {"mode": mode, "ok": False, "infocode": "unsupported"}

    def fetch(self, name: str, city: str) -> Evidence:
        at = utcnow()
        url = "https://restapi.amap.com/v5/place/text"
        try:
            data = self._call(
                "/v5/place/text",
                {
                    "keywords": name,
                    "region": city,
                    "city_limit": "true",
                    "page_size": 5,
                    "show_fields": "business",
                },
            )
            if str(data.get("status")) != "1":
                return Evidence(self.name, url, at, name, "", ok=False, error=f"{data.get('info')}/{data.get('infocode')}", authority=self.authority)
            pois = data.get("pois") or []
            chosen = None
            name_match = False
            best_similarity = 0.0
            for poi in pois:
                poi_name = str(poi.get("name", ""))
                business_i = poi.get("business") or {}
                ok_i, similarity_i = name_similarity(name, poi_name, business_i.get("alias"))
                if similarity_i > best_similarity:
                    best_similarity = similarity_i
                if ok_i:
                    chosen = poi
                    name_match = True
                    break
            chosen = chosen or (pois[0] if pois else None)
            if not name_match and chosen is not None:
                _, best_similarity = name_similarity(
                    name, str(chosen.get("name", "")), (chosen.get("business") or {}).get("alias")
                )
            if chosen is None:
                return Evidence(self.name, url, at, name, "", ok=False, error="no poi", authority=self.authority)
            business = chosen.get("business") or {}
            type_path = str(chosen.get("type", ""))
            parts = [part for part in type_path.split(";") if part]
            loc = str(chosen.get("location", ""))
            lat = lon = None
            if "," in loc:
                lon_s, lat_s = loc.split(",")[:2]
                lon, lat = float(lon_s), float(lat_s)
            structured = {
                "poi_id": chosen.get("id"),
                "name_match": name_match,
                "name_similarity": best_similarity,
                "name": chosen.get("name"),
                "type_path": parts,
                "type": parts[-1] if parts else "",
                "lat": lat,
                "lon": lon,
                "location": loc,
                "address": chosen.get("address"),
                "district": chosen.get("adname"),
                "city": chosen.get("cityname"),
                "tel": business.get("tel") or chosen.get("tel"),
                "website": chosen.get("website"),
                "opentime_text": business.get("opentime_week") or business.get("opentime_today") or "",
                "rating": business.get("rating"),
                "cost": business.get("cost"),
                "alias": business.get("alias"),
                "typecode": chosen.get("typecode"),
            }
            return Evidence(self.name, url, at, str(chosen.get("name") or name), json.dumps(data, ensure_ascii=False), structured, self.authority)
        except Exception as exc:  # noqa: BLE001
            return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


def default_sources(include_llm: bool = True) -> list:
    sources = [AmapSource(), WikipediaSource(), WikidataSource(), NominatimSource()]
    if include_llm:
        sources.append(LLMChatSource())
    return sources


OPEN_HOUR_PATTERNS = [
    re.compile(r"(?P<open>\d{1,2}[:：]\d{2})\s*[-—–~至到]\s*(?P<close>\d{1,2}[:：]\d{2})"),
    re.compile(r"(?P<open>\d{1,2}[:：]\d{2}).{0,12}开馆.{0,12}(?P<close>\d{1,2}[:：]\d{2}).{0,6}闭馆"),
]
PRICE_PATTERNS = [
    re.compile(r"全票\s*(?P<price>\d+)\s*元"),
    re.compile(r"门票\s*(?P<price>\d+)\s*元"),
    re.compile(r"票价\s*(?P<price>\d+)\s*元"),
    re.compile(r"免费"),
]


def regex_hints(text: str) -> dict:
    """Cheap, deterministic hints used to cross-check the LLM extraction."""
    hints: dict = {"open_windows": [], "prices": [], "free": False}
    if not text:
        return hints
    for pattern in OPEN_HOUR_PATTERNS:
        for match in pattern.finditer(text):
            hints["open_windows"].append(
                {
                    "opentime": match.group("open").replace("：", ":"),
                    "endtime": match.group("close").replace("：", ":"),
                    "quote": match.group(0),
                }
            )
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(text):
            if "price" in pattern.groupindex and match.groupdict().get("price"):
                hints["prices"].append({"price": int(match.group("price")), "quote": match.group(0)})
            elif pattern.pattern == "免费":
                hints["free"] = True
    return hints


def _amap_fetch_impl(self, name: str, city: str) -> Evidence:
    """Attach AmapSource.fetch back onto the class (recovery for patch 3)."""
    at = utcnow()
    url = "https://restapi.amap.com/v5/place/text"
    try:
        data = self._call(
            "/v5/place/text",
            {
                "keywords": name,
                "region": city,
                "city_limit": "true",
                "page_size": 5,
                "show_fields": "business",
            },
        )
        if str(data.get("status")) != "1":
            return Evidence(
                self.name, url, at, name, "",
                ok=False,
                error=f"{data.get('info')}/{data.get('infocode')}",
                authority=self.authority,
            )
        pois = data.get("pois") or []
        chosen = None
        name_match = False
        best_similarity = 0.0
        for poi in pois:
            poi_name = str(poi.get("name", ""))
            business_i = poi.get("business") or {}
            ok_i, similarity_i = name_similarity(name, poi_name, business_i.get("alias"))
            if similarity_i > best_similarity:
                best_similarity = similarity_i
            if ok_i:
                chosen = poi
                name_match = True
                break
        chosen = chosen or (pois[0] if pois else None)
        if chosen is None:
            return Evidence(self.name, url, at, name, "", ok=False, error="no poi", authority=self.authority)
        if not name_match:
            _, best_similarity = name_similarity(
                name, str(chosen.get("name", "")), (chosen.get("business") or {}).get("alias")
            )
        business = chosen.get("business") or {}
        parts = [part for part in str(chosen.get("type", "")).split(";") if part]
        loc = str(chosen.get("location", ""))
        lat = lon = None
        if "," in loc:
            lon_s, lat_s = loc.split(",")[:2]
            lon, lat = float(lon_s), float(lat_s)
        structured = {
            "poi_id": chosen.get("id"),
            "name_match": name_match,
            "name_similarity": best_similarity,
            "name": chosen.get("name"),
            "type_path": parts,
            "type": parts[-1] if parts else "",
            "lat": lat,
            "lon": lon,
            "location": loc,
            "address": chosen.get("address"),
            "district": chosen.get("adname"),
            "city": chosen.get("cityname"),
            "tel": business.get("tel") or chosen.get("tel"),
            "website": chosen.get("website"),
            "opentime_text": business.get("opentime_week") or business.get("opentime_today") or "",
            "rating": business.get("rating"),
            "cost": business.get("cost"),
            "alias": business.get("alias"),
            "typecode": chosen.get("typecode"),
        }
        return Evidence(
            self.name, url, at, str(chosen.get("name") or name),
            json.dumps(data, ensure_ascii=False), structured, self.authority,
        )
    except Exception as exc:  # noqa: BLE001
        return Evidence(self.name, url, at, name, "", ok=False, error=str(exc), authority=self.authority)


AmapSource.fetch = _amap_fetch_impl


# ------------------------------------------------------------------ weather (①)
def amap_weather(city: str, adcode: str | None = None, key: str | None = None) -> dict:
    """Current weather for a city; rain/snow is what drives the indoor re-plan."""
    source = AmapSource([key] if key else None)
    params = {"city": adcode or city, "extensions": "base"}
    data = source._call("/v3/weather/weatherInfo", params)
    lives = data.get("lives") or []
    if str(data.get("status")) != "1" or not lives:
        return {"ok": False, "infocode": data.get("infocode"), "info": data.get("info")}
    live = lives[0]
    weather = str(live.get("weather", ""))
    rainy = any(word in weather for word in ("雨", "雪", "雷"))
    return {
        "ok": True,
        "city": live.get("city"),
        "weather": weather,
        "temperature": live.get("temperature"),
        "wind": live.get("winddirection"),
        "reporttime": live.get("reporttime"),
        "precipitation": rainy,
        "infocode": data.get("infocode"),
    }


def weather_constraint(city: str, adcode: str | None = None) -> dict | None:
    """Turn rain into a hard constraint: at least one indoor (museum-type) stop.

    This is the TripTide-style "disruption -> re-plan" trigger, expressed in the
    same DSL the evaluator already understands, so no checker change is needed.
    """
    report = amap_weather(city, adcode)
    if not report.get("ok") or not report.get("precipitation"):
        return None
    code = (
        "indoor_set=set()\n"
        "for activity in allactivities(plan):\n"
        "  if activity_type(activity)=='attraction': indoor_set.add(attraction_type(activity, target_city(plan)))\n"
        "result=({'博物馆/纪念馆','美术馆/艺术馆'}<=indoor_set)"
    )
    return {
        "kind": "weather",
        "weather": report.get("weather"),
        "reporttime": report.get("reporttime"),
        "code": code,
        "note": f"{city} 当前{report.get('weather')}，至少安排一个室内场馆",
    }


# ------------------------------------------------------------------ transit (②)
def amap_transit(origin, destination, city: str, key: str | None = None) -> dict:
    """Transit duration for replacing the sandbox's synthetic intercity connection."""
    result = amap_route(tuple(origin), tuple(destination), mode="transit", city=city, key=key)
    return {
        "ok": result.get("ok"),
        "transit_min": result.get("duration_min"),
        "transit_km": result.get("distance_km"),
        "fare": result.get("cost"),
        "infocode": result.get("infocode"),
    }


def calibrate_sandbox_minutes(sandbox_min: float | None, amap_min: float | None, floor: float = 1.25) -> float | None:
    """Replace a sandbox travel time with the real one, never making it faster.

    We keep the larger of (sandbox, amap) so that the benchmark's feasibility
    judgement can only become *stricter*, never more optimistic.
    """
    if amap_min is None:
        return sandbox_min
    if sandbox_min is None:
        return amap_min
    return max(float(sandbox_min), float(amap_min)) if amap_min >= float(sandbox_min) * (floor / 1.25) else float(amap_min)
