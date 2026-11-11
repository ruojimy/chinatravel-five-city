"""Open-data adapters: OpenStreetMap (ODbL) and Wikidata (CC0).

Both are licence-clear and need no key, which is why they replace Baidu as the
primary TAG source after the quota was exhausted.

Measured facts that shaped this module (2026-10-21, `results/p1/open_data_probe.json`)

* ``around`` queries at ChinaTravel sandbox coordinates return **0** OSM objects:
  the sandbox stores GCJ-02 while OSM is WGS-84, and the sandbox itself drifts up
  to ~1.4 km from the real venue. So identity is established by **name**, and
  coordinates are only a *soft* verification with a generous radius.
* 广州塔 exists in OSM as a tower (``man_made=tower``) **without** ``tourism=*``,
  so filtering by category before matching loses the most famous venue in the sample.
* Wikidata's ``wbgetentities&sites=zhwiki&titles=A|B|...`` accepts up to 50 titles
  per call, which makes a 50-POI batch cost ~3 requests instead of 150.
  Extra parameters (``sitefilter``/``normalize``) silently returned 0 entities.

Politeness: one shared client per provider, ≥1.1 s between calls, explicit
``User-Agent``, bounded retries with exponential backoff, on-disk cache with TTL,
and every call passes the provider guard from ``providers.py``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings
from ..providers import guard
from ..tags import EXTRACTOR_VERSION, SCHEMA_VERSION, TagEvidence, _sha1, _now

ROOT = Path(__file__).resolve().parents[3]  # .../reproduction; parents[2] was src/ (P0 bug: cache in source tree)
CACHE_DIR = ROOT / "data" / "open_data_cache"
CACHE_SCHEMA = 1
UA = os.environ.get(
    "TAG_HTTP_UA",
    "ShortTripAssistant/1.0 (course project; POI attribute matching; non-commercial)",
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OSM_API = "https://api.openstreetmap.org/api/0.6"

# --------------------------------------------------------------------- geodesy
A = 6378245.0
EE = 0.00669342162296594323


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - EE * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float, iterations: int = 4) -> tuple[float, float]:
    """Numeric inversion of :func:`wgs84_to_gcj02` (no closed form)."""
    guess_lon, guess_lat = lon, lat
    for _ in range(iterations):
        f_lon, f_lat = wgs84_to_gcj02(guess_lon, guess_lat)
        guess_lon += lon - f_lon
        guess_lat += lat - f_lat
    return guess_lon, guess_lat


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


# ---------------------------------------------------------------------- names
_PUNCT = re.compile(r"[\s·•,，.。、\-_/\\|()（）\[\]【】<>《》:：;；'\"“”‘’!！?？]")


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _PUNCT.sub("", text)


# ---------------------------------------------------------------- http client
@dataclass
class CallLog:
    provider: str
    url: str
    status: int | None
    ok: bool
    cached: bool = False
    latency_s: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return {"provider": self.provider, "url": self.url.split("?")[0], "status": self.status,
                "ok": self.ok, "cached": self.cached, "latency_s": round(self.latency_s, 2),
                "note": self.note}


class OpenDataClient:
    """Polite JSON client: guard → cache → throttle → retry/backoff → record."""

    def __init__(self, provider: str, *, cache: bool = True, timeout: int | None = None,
                 min_interval: float | None = None, cache_dir: Path | None = None):
        config = settings()
        self.provider = provider
        self.cache = cache
        self.timeout = timeout or config.http_timeout
        self.min_interval = max(1.0, min_interval or config.http_min_interval) if provider == "osm" \
            else (min_interval or config.http_min_interval)
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_hours = config.evidence_ttl_hours
        self.calls: list[CallLog] = []
        self._last = 0.0

    def _throttle(self) -> None:
        delta = time.time() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.time()

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha1(f"{CACHE_SCHEMA}|{url}".encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{self.provider}_{key}.json"

    def get_json(self, url: str, *, use_cache: bool = True) -> dict:
        path = self._cache_path(url)
        if self.cache and use_cache and path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                retrieved = datetime.fromisoformat(payload["_retrieved_at"])
                if datetime.now(timezone.utc) - retrieved < timedelta(hours=self.ttl_hours):
                    self.calls.append(CallLog(self.provider, url, 200, True, True))
                    return payload["body"]
            except Exception:  # noqa: BLE001
                pass
        allowed, reason = guard().acquire(self.provider)
        if not allowed:
            self.calls.append(CallLog(self.provider, url, None, False, False, 0.0, reason))
            return {"_error": reason, "_blocked": True}
        last_error = ""
        for attempt in range(3):
            try:
                self._throttle()
                guard().spend(self.provider)
                started = time.time()
                request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8", "replace"))
                    latency = time.time() - started
                    guard().record(self.provider, ok=True, status_code=response.status, message="ok")
                    self.calls.append(CallLog(self.provider, url, response.status, True, False, latency))
                    if self.cache:
                        try:
                            path.write_text(json.dumps({"_retrieved_at": _now(), "url": url, "body": body},
                                                       ensure_ascii=False), encoding="utf-8")
                        except Exception:  # noqa: BLE001
                            pass
                    return body
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                guard().record(self.provider, ok=False, status_code=exc.code, message=last_error)
                self.calls.append(CallLog(self.provider, url, exc.code, False, False, 0.0, last_error))
                if exc.code in (429, 500, 502, 503, 504):
                    # Honour Retry-After when the service states it; otherwise back off hard.
                    retry_after = 0.0
                    try:
                        retry_after = float(exc.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                    wait = max(retry_after, 4.0 * (attempt + 1) ** 2)
                    time.sleep(min(wait, 30.0))
                    continue
                return {"_error": last_error, "_status": exc.code}
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                guard().record(self.provider, ok=False, status_code=None, message=last_error,
                               kind="timeout" if "timed out" in last_error.lower() else "network_error")
                self.calls.append(CallLog(self.provider, url, None, False, False, 0.0, last_error))
                time.sleep(1.0 * (attempt + 1))
        return {"_error": last_error or "failed"}

    def report(self) -> dict:
        return {"provider": self.provider, "calls": len(self.calls),
                "live": sum(1 for call in self.calls if not call.cached),
                "cached": sum(1 for call in self.calls if call.cached),
                "failed": sum(1 for call in self.calls if not call.ok),
                "log": [call.to_dict() for call in self.calls]}


# --------------------------------------------------------------- OSM source
OSM_TAG_KEYS = ("tourism", "historic", "leisure", "amenity", "wheelchair", "fee",
                "opening_hours", "wikidata", "wikipedia", "heritage", "natural", "man_made")


@dataclass
class OsmHit:
    name: str
    display_name: str
    osm_type: str
    osm_id: int
    lat: float
    lon: float
    category: str | None
    type: str | None
    importance: float | None
    distance_km: float | None
    tags: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "display_name": self.display_name, "osm_type": self.osm_type,
                "osm_id": self.osm_id, "lat": self.lat, "lon": self.lon,
                "category": self.category, "type": self.type, "importance": self.importance,
                "distance_km": self.distance_km, "tags": self.tags}


class NominatimOsmSource:
    """Name-first OSM lookup (ODbL). Returns candidates, never a silent single guess."""

    provider = "osm"
    licence = "ODbL-1.0"
    attribution = "© OpenStreetMap contributors"

    def __init__(self, client: OpenDataClient | None = None, *, limit: int = 5):
        self.client = client or OpenDataClient("osm")
        self.limit = limit

    def lookup(self, name: str, city: str, *, anchor_gcj: tuple[float, float] | None = None,
               require_city: bool = True) -> dict:
        params = {
            "q": f"{name} {city}",
            "format": "jsonv2",
            "limit": str(self.limit),
            "extratags": "1",
            "addressdetails": "1",
            "accept-language": "zh",
        }
        if os.environ.get("TAG_CONTACT_EMAIL"):
            params["email"] = os.environ["TAG_CONTACT_EMAIL"]
        body = self.client.get_json(f"{NOMINATIM}?{urllib.parse.urlencode(params)}")
        if isinstance(body, dict) and body.get("_error"):
            return {"ok": False, "error": body["_error"], "blocked": bool(body.get("_blocked")), "hits": []}
        hits: list[OsmHit] = []
        for row in body if isinstance(body, list) else []:
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            extratags = {key: (row.get("extratags") or {}).get(key) for key in OSM_TAG_KEYS
                         if (row.get("extratags") or {}).get(key) is not None}
            for extra_key, extra_value in (row.get("extratags") or {}).items():
                if extra_key in ("wikidata", "wikipedia", "wheelchair", "fee", "opening_hours",
                                 "heritage", "website", "tourism", "historic", "leisure", "amenity"):
                    extratags[extra_key] = extra_value
            distance = None
            if anchor_gcj:
                wlon, wlat = gcj02_to_wgs84(anchor_gcj[1], anchor_gcj[0])
                distance = km_between((wlat, wlon), (lat, lon))
            hits.append(OsmHit(
                name=str(row.get("name") or str(row.get("display_name", "")).split(",")[0]).strip(),
                display_name=str(row.get("display_name") or ""),
                osm_type=str(row.get("osm_type") or ""),
                osm_id=int(row.get("osm_id") or 0),
                lat=lat, lon=lon,
                category=row.get("category") or row.get("class"),
                type=row.get("type"),
                importance=row.get("importance"),
                distance_km=None if distance is None else round(distance, 2),
                tags=extratags,
                raw=row,
            ))
        rejected_by_city: list[str] = []
        if require_city and city and hits:
            # A 1000-km-away hit with the same name is noise: measured on 重庆际华园滑雪馆,
            # Nominatim returned 合肥 results. Distance alone already filtered them, but the
            # administrative check is cheaper and catches the case when coordinates are missing.
            kept = []
            for hit in hits:
                if city in hit.display_name:
                    kept.append(hit)
                else:
                    rejected_by_city.append(hit.display_name[:60])
            if kept:
                hits = kept
        return {"ok": True, "hits": hits, "query": params["q"],
                "rejected_by_city": rejected_by_city}


# ----------------------------------------------------------- Wikidata source
TYPE_KEYWORDS = [
    ("博物馆", "category_history"), ("museum", "category_history"),
    ("纪念馆", "category_history"), ("memorial", "category_history"),
    ("古迹", "category_history"), ("遗址", "category_history"), ("archaeological", "category_history"),
    ("寺", "category_history"), ("庙", "category_history"), ("temple", "category_history"),
    ("祠堂", "category_history"), ("故居", "category_history"), ("palace", "category_history"),
    ("宫殿", "category_history"), ("城墙", "category_history"), ("要塞", "category_history"),
    ("公园", "category_nature"), ("park", "category_nature"),
    ("花园", "category_nature"), ("garden", "category_nature"),
    ("山", "category_nature"), ("mountain", "category_nature"), ("湖", "category_nature"),
    ("自然保护区", "category_nature"), ("nature reserve", "category_nature"),
    ("植物园", "category_nature"), ("botanical", "category_nature"),
    ("观景", "photo_scenic"), ("viewpoint", "photo_scenic"),
    ("塔", "photo_scenic"), ("tower", "photo_scenic"),
    ("游乐园", "family_friendly"), ("amusement", "family_friendly"),
    ("动物园", "family_friendly"), ("zoo", "family_friendly"),
    ("主题公园", "family_friendly"), ("theme park", "family_friendly"),
]

WIKIDATA_PROPS = {
    "P31": "instance_of",
    "P625": "coordinates",
    "P1435": "heritage_designation",
    "P18": "image",
    "P856": "official_website",
    "P571": "inception",
    "P1619": "date_opened",
}


class WikidataSource:
    """Batch entity + type-label lookup. CC0, so derived records may be redistributed."""

    provider = "wikidata"
    licence = "CC0-1.0"
    attribution = "Wikidata (CC0)"

    def __init__(self, client: OpenDataClient | None = None):
        self.client = client or OpenDataClient("wikidata")

    # ------------------------------------------------------------------ entities
    def entities_by_titles(self, titles: list[str], *, sites: str = "zhwiki") -> dict:
        """Up to 50 zhwiki article titles per call -> entities. Verified shape."""
        out: dict = {}
        if not titles:
            return out
        for start in range(0, len(titles), 50):
            chunk = [title for title in titles[start:start + 50] if title]
            if not chunk:
                continue
            params = {
                "action": "wbgetentities",
                "sites": sites,
                "titles": "|".join(chunk),
                "props": "claims|labels|aliases|sitelinks|descriptions",
                "languages": "zh|en",
                "format": "json",
            }
            body = self.client.get_json(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}")
            if body.get("_error"):
                out["_error"] = body["_error"]
                continue
            for qid, entity in (body.get("entities") or {}).items():
                if qid.startswith("-") or entity.get("missing") is not None:
                    out.setdefault("_missing", []).append(entity)
                    continue
                out[qid] = entity
        return out

    def search_entities(self, name: str, *, language: str = "zh", limit: int = 5) -> list[dict]:
        params = {"action": "wbsearchentities", "search": name, "language": language,
                  "uselang": language, "limit": str(limit), "format": "json"}
        body = self.client.get_json(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}")
        if body.get("_error"):
            return []
        return body.get("search") or []

    def items_by_labels(self, labels: list[str], *, language: str = "zh") -> dict[str, str]:
        """Batch label -> QID via one SPARQL query.

        ``wbsearchentities`` is one request per POI, which trips the 429 limiter
        (measured: 8 of 43 calls rejected). A single ``VALUES ?label`` query does
        the same work in one request, which is the polite way to use the Query
        Service.
        """
        wanted = sorted({label for label in labels if label and '"' not in label})
        if not wanted:
            return {}
        values = " ".join(f'"{label}"@{language}' for label in wanted)
        query = ("SELECT ?item ?label WHERE { VALUES ?label { " + values + " } "
                 "?item rdfs:label ?label . } LIMIT 500")
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": query, "format": "json"})
        body = self.client.get_json(url)
        if body.get("_error"):
            return {}
        out: dict[str, str] = {}
        for binding in ((body.get("results") or {}).get("bindings") or []):
            try:
                qid = binding["item"]["value"].rsplit("/", 1)[-1]
                label = binding["label"]["value"]
            except (KeyError, TypeError):
                continue
            out.setdefault(label, qid)
        return out


    def entities_by_ids(self, qids: list[str]) -> dict:
        """Batch ``wbgetentities&ids=`` — used to reload raw claims for gate T2."""
        out: dict = {}
        qids = [qid for qid in qids if qid]
        if not qids:
            return out
        for start in range(0, len(qids), 45):
            chunk = qids[start:start + 45]
            params = {"action": "wbgetentities", "ids": "|".join(chunk),
                      "props": "claims|labels|aliases|sitelinks|descriptions",
                      "languages": "zh|en", "format": "json"}
            body = self.client.get_json(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}")
            if body.get("_error"):
                continue
            for qid, entity in (body.get("entities") or {}).items():
                if not qid.startswith("-") and entity.get("missing") is None:
                    out[qid] = entity
        return out

    def type_labels(self, qids: list[str]) -> dict[str, dict]:
        labels: dict[str, dict] = {}
        qids = sorted({qid for qid in qids if qid})
        if not qids:
            return labels
        for start in range(0, len(qids), 45):
            chunk = qids[start:start + 45]
            params = {"action": "wbgetentities", "ids": "|".join(chunk),
                      "props": "labels|descriptions", "languages": "zh|en", "format": "json"}
            body = self.client.get_json(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}")
            if body.get("_error"):
                continue
            for qid, entity in (body.get("entities") or {}).items():
                labels[qid] = {
                    "zh": ((entity.get("labels") or {}).get("zh") or {}).get("value"),
                    "en": ((entity.get("labels") or {}).get("en") or {}).get("value"),
                    "desc_zh": ((entity.get("descriptions") or {}).get("zh") or {}).get("value"),
                }
        return labels

    # ------------------------------------------------------------------- extract
    @staticmethod
    def summarize(entity: dict) -> dict:
        claims = entity.get("claims") or {}
        out: dict = {
            "qid": entity.get("id"),
            "label_zh": ((entity.get("labels") or {}).get("zh") or {}).get("value"),
            "label_en": ((entity.get("labels") or {}).get("en") or {}).get("value"),
            "aliases_zh": [item.get("value") for item in ((entity.get("aliases") or {}).get("zh") or [])],
            "description_zh": ((entity.get("descriptions") or {}).get("zh") or {}).get("value"),
            "sitelinks": sorted((entity.get("sitelinks") or {}).keys())[:8],
            "instance_of": [],
            "coordinates": None,
            "heritage": [],
            "has_image": False,
            "official_website": None,
            "claim_count": len(claims),
        }
        for item in claims.get("P31", []):
            value = item.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                out["instance_of"].append(value["id"])
        if claims.get("P625"):
            value = claims["P625"][0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if value:
                out["coordinates"] = {"lat": value.get("latitude"), "lon": value.get("longitude")}
        for item in claims.get("P1435", []):
            value = item.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                out["heritage"].append(value["id"])
        out["has_image"] = bool(claims.get("P18"))
        if claims.get("P856"):
            out["official_website"] = (claims["P856"][0].get("mainsnak", {})
                                       .get("datavalue", {}).get("value"))
        return out


def type_to_tags(labels: dict[str, dict]) -> dict[str, list[str]]:
    """Map P31 type labels to the v0.2 tag ids. Only explicit keyword evidence."""
    mapping: dict[str, list[str]] = {}
    for qid, label in labels.items():
        text = " ".join(filter(None, [label.get("zh"), label.get("en"), label.get("desc_zh")])).lower()
        for keyword, tag_id in TYPE_KEYWORDS:
            if keyword.lower() in text:
                mapping.setdefault(qid, []).append(tag_id)
    return mapping


# ------------------------------------------------------------------ identity
# Ungated locators: words that name a *position* within a place, not a different place.
LOCATOR_WORDS = ("景区", "旅游区", "园区", "风景区", "公园", "广场", "东门", "西门", "南门",
                 "北门", "正门", "入口", "出口", "游客中心", "服务中心", "售票处", "博物馆",
                 "纪念馆", "美术馆", "古镇", "老街")

# v2: venue-type suffixes that name a *part of* or a *kind of* the same place. These are
# only accepted when the coordinates also agree (<= 3 km), because "XX剧场" vs "XX" is
# the same venue, while "XX博物馆" vs "XX" in another district is often not.
SUFFIX_WORDS = ("剧场", "剧院", "乐园", "馆区", "馆", "中心", "基地", "码头", "游船",
                "大舞台", "度假区", "景区", "园区", "校区", "博物院", "博物馆", "纪念馆")
SINGLE_CHAR_SUFFIXES = ("区", "馆", "园", "厅", "场", "楼", "城")
MAX_SUFFIX_KM = 3.0

# Wikidata entities that are not places at all.
DISAMBIGUATION_MARKERS = ("消歧義", "消歧义", "disambiguation", "維基媒體消歧義頁",
                          "维基媒体消歧义页")

SUB_SITE_PATTERN = re.compile(r"^\s*(?P<parent>[^()（）\[\]【】]+?)\s*[(\[（【]\s*(?P<child>[^)\]）】]+)\s*[)\]）】]\s*$")


def is_disambiguation(entity: dict) -> bool:
    """True when the entity is a disambiguation page rather than a POI.

    Measured: 上海人民公园 was accepted against Q7165653 whose P31 is
    「維基媒體消歧義頁」 — a page listing several parks, not a park.
    """
    labels = [((entity.get("labels") or {}).get(lang) or {}).get("value") or ""
              for lang in ("zh", "en")]
    description = ((entity.get("descriptions") or {}).get("zh") or {}).get("value") or ""
    for statement in (entity.get("claims") or {}).get("P31", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id") in ("Q4167410", "Q22808320"):
            return True  # Wikimedia disambiguation page / Wikimedia category
    blob = " ".join(labels + [description]).lower()
    return any(marker.lower() in blob for marker in DISAMBIGUATION_MARKERS)


def match_identity(request_name: str, candidate_name: str,
                   aliases: list[str] | None = None,
                   distance_km: float | None = None) -> dict:
    """Strict, rule-labelled name matching for open-data candidates.

    Deliberately not a 0.7 character-similarity threshold: measured earlier, that
    maps 上海博物馆东馆 onto 上海农垦博物馆. Abstention is preferred.

    ``distance_km`` enables the v2 suffix rule: a venue-type suffix (剧场/馆区/…) is
    accepted only when the coordinates also agree within 3 km.
    """
    from difflib import SequenceMatcher

    wanted = normalize_name(request_name)
    if not wanted:
        return {"match": False, "rule": "empty", "similarity": 0.0}
    texts = [(candidate_name or "", "name")] + [(alias or "", "alias") for alias in (aliases or [])]
    loose = SequenceMatcher(None, wanted, normalize_name(candidate_name)).ratio()
    for raw, kind in texts:
        got = normalize_name(raw)
        if not got:
            continue
        if got == wanted:
            return {"match": True, "rule": f"{kind}_exact", "similarity": 1.0, "matched": raw}
    # a bracketed sub-site of an exactly-named parent, e.g. 南越王博物院(王墓展区)
    sub = SUB_SITE_PATTERN.match(str(candidate_name or ""))
    if sub and normalize_name(sub.group("parent")) == wanted:
        return {"match": True, "rule": "sub_site_of_exact_parent", "similarity": 1.0,
                "parent": sub.group("parent"), "sub_site": sub.group("child")}
    near = distance_km is not None and distance_km <= MAX_SUFFIX_KM
    for raw, kind in texts:
        got = normalize_name(raw)
        if not got or len(wanted) < 3:
            continue
        if got.startswith(wanted) or wanted.startswith(got):
            ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
            extra = got[len(wanted):] if got.startswith(wanted) else wanted[len(got):]
            if ratio >= 0.6 and any(word in extra for word in LOCATOR_WORDS):
                return {"match": True, "rule": f"{kind}_prefix_locator", "similarity": round(ratio, 3),
                        "extra": extra, "matched": raw}
            if near and ratio >= 0.6 and any(word in extra for word in SUFFIX_WORDS):
                return {"match": True, "rule": f"{kind}_venue_suffix_near", "similarity": round(ratio, 3),
                        "extra": extra, "matched": raw, "distance_km": distance_km}
            if near and ratio >= 0.85 and extra in SINGLE_CHAR_SUFFIXES:
                return {"match": True, "rule": f"{kind}_char_suffix_near", "similarity": round(ratio, 3),
                        "extra": extra, "matched": raw, "distance_km": distance_km}
    return {"match": False, "rule": "abstain", "similarity": round(loose, 3)}

