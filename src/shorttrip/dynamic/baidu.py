"""Baidu LBS Web Service adapter (Place API) with SN signature auth.

Everything in this module is pinned to a **real request**, made 2026-10-21 with
the project's own AK/SK. The probe transcripts live in
``reproduction/results/baidu_path_probe.json`` and ``results/baidu_raw/``:

* SN signature: works. Verified offline against Baidu's published test vector
  (``self_test()``) and live against ``/geocoder/v2/``, which answered
  ``status=240 APP 服务被禁用`` — i.e. the signature passed and only the *service
  entitlement* was missing. A bad signature would have been ``211``.
* ``/place/v3/search`` → **HTTP 404** (endpoint not deployed for this account).
  ``/place/v2/search`` → ``status=0``. The documented "Place API 3.0" page maps to
  the v2 Web Service endpoint in practice; the adapter therefore uses v2 and
  records the 404 as a capability-matrix fact instead of pretending otherwise.
* ``/place/v2/detail`` additionally returns ``price``, ``alias``, ``scope_grade``
  and — importantly — ``content_tag``.

What Baidu can and cannot tell us
---------------------------------
| channel | example value | what it is |
| --- | --- | --- |
| ``tag`` / ``classified_poi_tag`` | ``旅游景点;4A景区`` | platform taxonomy = **attribute** |
| ``label`` / ``scope_type`` / ``scope_grade`` | ``AAAA景区,城市风光`` | platform classification = attribute |
| ``shop_hours`` / ``regular_open_hour`` | ``09:30-22:30`` + per-weekday periods | attribute |
| ``price`` | ``230.0`` | attribute (ticket price) |
| ``overall_rating`` | ``4.6`` | platform aggregate score, **not** a review |
| ``comment_num`` | ``200`` for 广州塔 *and* 故宫 | a **capped bucket**, not a count |
| ``content_tag`` | ``适合亲子;适合拍照;情侣约会;人气旺`` | UGC-derived experience labels, aggregation undisclosed |
| recommended duration | — | **not provided**, stays ``None`` |

So ``content_tag`` is the only visitor-experience channel here, and it is a
*platform-curated* label set: no vote counts, no timestamps, no per-review text.
It is classified as ``platform_tag`` evidence and never presented as a review
statistic (``comment_num`` is explicitly down-graded to an ordinal bucket because
several famous venues all report exactly 200).

Credentials come from ``BAIDU_AK`` / ``BAIDU_SK`` env vars, else
``reproduction/.secrets/baidu.key``. They are never logged.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .records import Evidence, utcnow

ROOT = Path(__file__).resolve().parents[3]
SECRETS = ROOT / ".secrets"
CACHE_DIR = ROOT / "data" / "evidence_cache"
FIXTURE_DIR = ROOT / "data" / "baidu_fixtures"
CACHE_SCHEMA = 2  # bump when the cached payload shape changes

# Quota protection. The account's free quota was exhausted on 2026-10-21, so Baidu
# is now an *optional* provider: the default live budget is 0 (see config.py), a
# provider-level circuit breaker records `quota_exhausted` for the UTC day, and
# replay from data/baidu_fixtures/ keeps the historical evidence reproducible.
OFFLINE_ENV = "BAIDU_OFFLINE"


def offline_forced() -> bool:
    from ..config import settings

    return settings().baidu_offline or os.environ.get(OFFLINE_ENV, "").strip().lower() in (
        "1", "true", "yes", "on")


def live_budget() -> int:
    """0 by default: the P0 fix for 'quota exhausted stops the project'."""
    from ..config import settings

    return settings().provider_budget("baidu")


HOST = "https://api.map.baidu.com"
UA = "ShortTripAssistant/1.0 (course project; POI verification)"

SEARCH_V2 = "/place/v2/search"
DETAIL_V2 = "/place/v2/detail"
SEARCH_V3 = "/place/v3/search"  # documented "Place API 3.0"; 404 as of 2026-10-21
DETAIL_V3 = "/place/v3/detail"

ENDPOINT_NOTES = {
    SEARCH_V3: "HTTP 404 on 2026-10-21（未部署）；文档中的 Place API 3.0 实际走 v2",
    DETAIL_V3: "status=2 Parameter Invalid（路径存在但参数/权限不匹配）",
    SEARCH_V2: "status=0，实际可用（query/region/scope=2/ret_coordtype=gcj02ll）",
    DETAIL_V2: "status=0，实际可用，额外给出 price/alias/content_tag/scope_grade",
}

# Baidu status codes worth distinguishing (LBS 状态码文档).
QUOTA_CODES = {4, 302, 401, 402}
AUTH_CODES = {5, 101, 102, 200, 203, 240}  # account/entitlement: retrying is pointless
SN_FAIL_CODES = {2, 211, 212}  # signature string wrong -> try the next spelling

# ``comment_num``/``image_num`` come back as round numbers; 广州塔 and 故宫 both
# report exactly 200, so anything at or above this is treated as "capped".
COMMENT_NUM_CAP = 200


# --------------------------------------------------------------------- secrets
@dataclass
class Credentials:
    ak: str
    sk: str | None
    source: str  # "env" | "file"
    path: str | None = None

    @property
    def has_sk(self) -> bool:
        return bool(self.sk)

    def redacted(self) -> dict:
        def mask(value: str | None) -> str | None:
            if not value:
                return None
            return value[:4] + "*" * max(0, len(value) - 8) + value[-4:]

        return {"ak": mask(self.ak), "sk_present": self.has_sk, "source": self.source, "path": self.path}

    def __repr__(self) -> str:  # never leak through a traceback or log line
        return f"Credentials(ak={self.redacted()['ak']!r}, sk_present={self.has_sk}, source={self.source!r})"


class BaiduCredentialsError(RuntimeError):
    pass


def load_credentials(path: str | Path | None = None, *, allow_env: bool = True) -> Credentials:
    """Env vars win over the local key file; a missing key raises, never fakes."""
    if allow_env:
        ak = os.environ.get("BAIDU_AK", "").strip()
        sk = os.environ.get("BAIDU_SK", "").strip()
        if ak:
            return Credentials(ak=ak, sk=sk or None, source="env")
    target = Path(path) if path else (SECRETS / "baidu.key")
    if target.exists():
        text = target.read_text(encoding="utf-8").strip()
        if text.startswith("{"):
            payload = json.loads(text)
        else:  # two-line "ak\nsk" form
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            payload = {"ak": lines[0] if lines else "", "sk": lines[1] if len(lines) > 1 else ""}
        ak = str(payload.get("ak", "")).strip()
        sk = str(payload.get("sk", "")).strip()
        if ak:
            return Credentials(ak=ak, sk=sk or None, source="file", path=str(target))
    raise BaiduCredentialsError(
        "缺少百度 AK：请设置环境变量 BAIDU_AK/BAIDU_SK，或写入 reproduction/.secrets/baidu.key"
    )


# ------------------------------------------------------------------- signature
# Baidu's official sample (Java) does this, and it is *not* obvious:
#
#   1. build the query: key=URLEncoder.encode(value), in **URL order** (not sorted);
#   2. whole = uri + "?" + query + sk                  (no separator before sk)
#   3. signed = URLEncoder.encode(whole)               (encode the WHOLE string)
#   4. sn = md5(signed)                                (32 lowercase hex)
#
# Step 3 is what most re-implementations miss; without it every request answers
# 211 "APP SN校验失败". ``self_test()`` pins this against Baidu's published vector
# (/geocoder/v2/?address=百度大厦&output=json&ak=yourak, sk=yoursk ->
# 7de5a22212ffaa9e326444c75a58f9a0) so a refactor cannot silently break it.
SIGN_ALGORITHMS = ("md5_urlenc", "md5_raw", "md5_query_only")
SN_TEST_VECTOR = {
    "uri": "/geocoder/v2/",
    "params": {"address": "百度大厦", "output": "json", "ak": "yourak"},
    "sk": "yoursk",
    "expect": "7de5a22212ffaa9e326444c75a58f9a0",
}


def java_urlencode(text: str) -> str:
    """java.net.URLEncoder semantics: space -> '+', keep ``* - . _``, else %XX."""
    return urllib.parse.quote_plus(text, safe="*-._")


def _quote_value(value, mode: str) -> str:
    text = str(value)
    if mode == "java":
        return java_urlencode(text)
    if mode == "pct":  # RFC3986: space -> %20
        return urllib.parse.quote(text, safe="")
    if mode == "plus":
        return urllib.parse.quote_plus(text, safe="")
    if mode == "raw":
        return text
    if mode == "double":
        return urllib.parse.quote(urllib.parse.quote(text, safe=""), safe="")
    if mode == "pct_lower":
        quoted = urllib.parse.quote(text, safe="")
        return re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quoted)
    raise ValueError(f"unknown encoding mode: {mode}")


def canonical_query(params: dict, mode: str = "java", *, sort: bool = False) -> str:
    """``a=1&b=2`` — byte-for-byte what the request URL carries.

    ``sort=False`` (default) preserves insertion order because Baidu signs the
    parameters *in URL order*. Whatever order is used here must be the order sent;
    the client guarantees that by building the string once (see ``sign_query``).
    """
    items = [(str(k), v) for k, v in params.items() if k != "sn"]
    if sort:
        items.sort(key=lambda kv: kv[0])
    return "&".join(f"{key}={_quote_value(value, mode)}" for key, value in items)


def sign_query(uri_path: str, query: str, sk: str) -> str:
    """Sign an *already assembled* query string — the only safe way to do this."""
    return hashlib.md5(java_urlencode(f"{uri_path}?{query}{sk}").encode("utf-8")).hexdigest()


def sign(uri_path: str, params: dict, sk: str, *, algorithm: str = "md5_urlenc",
         mode: str = "java", with_host: bool = False, sort: bool = False) -> str:
    """Return Baidu's ``sn`` for one request. Default algorithm is the official one."""
    prefix = HOST if with_host else ""
    query = canonical_query(params, mode, sort=sort)
    if algorithm == "md5_urlenc":
        return sign_query(f"{prefix}{uri_path}", query, sk)
    if algorithm == "md5_query_only":
        whole = f"{prefix}{uri_path}?{java_urlencode(query)}{sk}"
        return hashlib.md5(whole.encode("utf-8")).hexdigest()
    if algorithm == "md5_raw":
        return hashlib.md5(f"{prefix}{uri_path}?{query}{sk}".encode("utf-8")).hexdigest()
    raise ValueError(f"unknown signing algorithm: {algorithm}")


def sign_variants(uri_path: str, params: dict, sk: str) -> dict[str, str]:
    """Every candidate, so a probe failure stays diagnosable instead of mysterious."""
    out = {algorithm: sign(uri_path, params, sk, algorithm=algorithm) for algorithm in SIGN_ALGORITHMS}
    out["md5_urlenc_sorted"] = sign(uri_path, params, sk, algorithm="md5_urlenc", sort=True)
    return out


def self_test() -> dict:
    """Offline proof that the signer still matches Baidu's published vector."""
    vector = SN_TEST_VECTOR
    got = sign(vector["uri"], vector["params"], vector["sk"], algorithm="md5_urlenc")
    signed_string = java_urlencode(
        f'{vector["uri"]}?{canonical_query(vector["params"], "java")}{vector["sk"]}'
    )
    return {
        "ok": got == vector["expect"],
        "expected": vector["expect"],
        "got": got,
        "algorithm": "md5_urlenc",
        "signed_string": signed_string,
        "note": "参数按 URL 出现顺序参与签名（官方样例即如此），不是字母序；整串再 URL 编码后取 MD5",
    }


# --------------------------------------------------------------- coordinates
X_PI = math.pi * 3000.0 / 180.0


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    """BD-09 (Baidu native) -> GCJ-02 (Amap). Never mix the two in a distance test."""
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def gcj02_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    middle = (math.sin(dlat / 2) ** 2
              + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(middle)))


# -------------------------------------------------------------------- client
@dataclass
class CallRecord:
    path: str
    params: dict
    status: int | None
    message: str
    latency_s: float
    cached: bool = False
    signature_style: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "params": {k: v for k, v in self.params.items() if k not in ("ak", "sn")},
            "status": self.status,
            "message": self.message,
            "latency_s": round(self.latency_s, 2),
            "cached": self.cached,
            "signature_style": self.signature_style,
        }


class BaiduPlaceClient:
    """Rate-limited, redacted, budget-capped client for the Place API.

    * one process-wide call budget, so a runaway loop cannot burn the daily quota;
    * exponential backoff on transient network errors (no key rotation: one key);
    * disk cache keyed by a schema-versioned hash, so an offline rerun reproduces
      the same numbers and the evidence digest stays stable;
    * ``prefer_v3`` exists only to *record* that the documented 3.0 endpoint is
      unavailable; it is switched off automatically after the first failure.
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        cache: bool = True,
        max_calls: int = 60,
        timeout: int = 20,
        min_interval_s: float = 0.25,
        coordtype: str = "gcj02ll",
        prefer_v3: bool = False,
        verbose: bool = False,
    ):
        self.credentials = credentials or load_credentials()
        self.cache = cache
        self.max_calls = max_calls
        self.timeout = timeout
        self.min_interval_s = min_interval_s
        self.coordtype = coordtype
        self.prefer_v3 = prefer_v3
        self.verbose = verbose
        self.calls: list[CallRecord] = []
        self._last_call_at = 0.0
        self._signature_style: str | None = os.environ.get("BAIDU_SIGN_STYLE") or None
        self._v3_dead = not prefer_v3
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def spent(self) -> int:
        """Calls that actually reached the network. Blocked attempts are free."""
        return len([call for call in self.calls
                    if not call.cached and call.signature_style != "blocked"])

    # --------------------------------------------------------------- internals
    def _throttle(self) -> None:
        delta = time.time() - self._last_call_at
        if delta < self.min_interval_s:
            time.sleep(self.min_interval_s - delta)
        self._last_call_at = time.time()

    def _cache_path(self, path: str, params: dict) -> Path:
        key = json.dumps({"v": CACHE_SCHEMA, "path": path, "params": params},
                         ensure_ascii=False, sort_keys=True)
        return CACHE_DIR / f"baidu_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.json"

    def _base_params(self, params: dict) -> dict:
        merged = {"output": "json", **params}
        if self.coordtype and "ret_coordtype" not in merged:
            merged["ret_coordtype"] = self.coordtype
        merged["ak"] = self.credentials.ak
        return merged

    def _send(self, path: str, params: dict, style: str) -> tuple[dict, float]:
        """One GET. ``style == 'no_sn'`` deliberately sends AK only (diagnostic)."""
        started = time.time()
        sort = style.endswith("_sorted")
        query = canonical_query(params, "java", sort=sort)
        if style == "no_sn":
            url = f"{HOST}{path}?{query}"
        elif style in ("md5_urlenc", "md5_urlenc_sorted"):
            url = f"{HOST}{path}?{query}&sn={sign_query(path, query, self.credentials.sk or '')}"
        else:
            sn = sign(path, params, self.credentials.sk or "", algorithm=style, sort=sort)
            url = f"{HOST}{path}?{query}&sn={sn}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return payload, time.time() - started

    def _attempt(self, path: str, params: dict, style: str) -> tuple[dict, float]:
        last: Exception | None = None
        for attempt in range(3):
            try:
                self._throttle()
                return self._send(path, params, style)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (403, 429, 500, 502, 503, 504):
                    time.sleep(0.8 * (attempt + 1) ** 2)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001 — transient SSL/DNS hiccup
                last = exc
                time.sleep(0.6 * (attempt + 1) ** 2)
        raise last  # type: ignore[misc]

    # ------------------------------------------------------------------- API
    def discover_signature_style(self, path: str = SEARCH_V2, probe_params: dict | None = None) -> dict:
        """Prove which SN spelling this AK/SK accepts (one call per candidate)."""
        if not self.credentials.has_sk:
            return {"ok": False, "reason": "没有 SK，无法做 SN 签名（ak+sk 校验要求 sk）",
                    "ak_only": self.credentials.redacted()}
        base = self._base_params(
            probe_params or {"query": "广州塔", "region": "广州", "scope": "2", "page_size": "1"}
        )
        order = ["md5_urlenc", "no_sn", "md5_raw", "md5_query_only", "md5_urlenc_sorted"]
        if self._signature_style:
            order = [self._signature_style] + [s for s in order if s != self._signature_style]
        trials: list[dict] = []
        winner = None
        for style in order:
            if self.spent >= self.max_calls:
                trials.append({"style": style, "status": None, "message": "budget exhausted"})
                break
            try:
                payload, latency = self._attempt(path, base, style)
            except Exception as exc:  # noqa: BLE001
                trials.append({"style": style, "status": None, "message": f"transport: {exc}"})
                self.calls.append(CallRecord(path, base, None, f"transport: {exc}", 0.0, False, style))
                continue
            status = payload.get("status")
            message = str(payload.get("message"))
            self.calls.append(CallRecord(path, base, status, message, latency, False, style))
            trials.append({"style": style, "status": status, "message": message})
            if str(status) == "0":
                winner = style
                self._signature_style = style
                break
            if status in AUTH_CODES or status in QUOTA_CODES:
                break
        result = {
            "ok": winner is not None,
            "style": winner,
            "sn_required": winner not in (None, "no_sn"),
            "trials": trials,
            "path": path,
            "ak_only": self.credentials.redacted(),
        }
        if winner:
            os.environ["BAIDU_SIGN_STYLE"] = winner
        return result

    def request(self, path: str, params: dict, *, use_cache: bool = True) -> dict:
        """Signed GET. Returns Baidu's JSON verbatim, plus ``_endpoint``/``_cached``.

        Every live call must pass the provider guard first. With the default
        ``BAIDU_REQUEST_BUDGET=0`` this returns immediately and **no socket is
        opened** — that is the P0 contract: a spent quota degrades to open data
        instead of stopping the pipeline.
        """
        from ..providers import guard

        params = {k: v for k, v in params.items() if v is not None}
        cache_path = self._cache_path(path, params)
        # A cache hit is local evidence, not a request, so it is allowed at budget 0.
        if self.cache and use_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("_schema") == CACHE_SCHEMA:
                    cached["_cached"] = True
                    self.calls.append(CallRecord(path, params, cached.get("status"),
                                                 str(cached.get("message")), 0.0, True, None))
                    return cached
            except Exception:  # noqa: BLE001
                pass
        allowed, reason = guard().acquire("baidu")
        if not allowed:
            self.calls.append(CallRecord(path, params, None, reason, 0.0, False, "blocked"))
            return {"status": -2, "message": reason, "result": None, "_cached": False,
                    "_endpoint": path, "_blocked": True, "_blocked_reason": reason}
        if self.spent >= self.max_calls:
            return {"status": -1, "message": f"local call budget exhausted ({self.max_calls})",
                    "result": None, "_cached": False, "_endpoint": path}
        if not self.credentials.has_sk:
            return {"status": -1, "message": "no sk configured; cannot sign",
                    "result": None, "_cached": False, "_endpoint": path}
        full = self._base_params(params)
        style = self._signature_style or os.environ.get("BAIDU_SIGN_STYLE") or "md5_urlenc"
        attempts = [style] + [s for s in ("md5_urlenc", "no_sn", "md5_raw", "md5_query_only") if s != style]
        for candidate in attempts:
            try:
                guard().spend("baidu")
                payload, latency = self._attempt(path, full, candidate)
            except Exception as exc:  # noqa: BLE001
                self.calls.append(CallRecord(path, full, None, f"transport: {exc}", 0.0, False, candidate))
                kind = "timeout" if "timed out" in str(exc).lower() else "network_error"
                guard().record("baidu", ok=False, status_code=None, message=str(exc), kind=kind)
                return {"status": -1, "message": f"transport error: {exc}", "result": None,
                        "_cached": False, "_endpoint": path}
            status = payload.get("status")
            self.calls.append(CallRecord(path, full, status, str(payload.get("message")),
                                         latency, False, candidate))
            if str(status) == "0":
                self._signature_style = candidate
                os.environ["BAIDU_SIGN_STYLE"] = candidate
                guard().record("baidu", ok=True, status_code=0, message="ok")
                payload.update({"_schema": CACHE_SCHEMA, "_retrieved_at": utcnow(),
                                "_signature_style": candidate, "_cached": False, "_endpoint": path})
                if self.cache:
                    try:
                        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                return payload
            guard().record("baidu", ok=False,
                           status_code=int(status) if str(status).lstrip("-").isdigit() else None,
                           message=str(payload.get("message")))
            if status in AUTH_CODES or status in QUOTA_CODES:
                # Breaker is now open for the day: return, never retry with another key.
                payload.update({"_cached": False, "_endpoint": path})
                return payload
        return {"status": -1, "message": "all signature variants rejected", "result": None,
                "_cached": False, "_endpoint": path}

    # --------------------------------------------------------------- wrappers
    def search(self, q: str, region: str, *, page_size: int = 5, page_num: int = 1,
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
            shared["page_num"] = str(page_num)
        if tag:
            shared["tag"] = tag
        if extra:
            shared.update(extra)
        if not self._v3_dead:
            payload = self.request(SEARCH_V3, {"q": q, **shared})
            if str(payload.get("status")) == "0":
                return payload
            self._v3_dead = True  # 404/parameter error: remember, never retry per call
        return self.request(SEARCH_V2, {"query": q, **shared})

    def detail(self, uid: str, *, scope: int = 2) -> dict:
        return self.request(DETAIL_V2, {"uid": uid, "scope": str(scope)})

    def budget_report(self) -> dict:
        statuses: dict[str, int] = {}
        for call in self.calls:
            key = "cached" if call.cached else str(call.status)
            statuses[key] = statuses.get(key, 0) + 1
        return {
            "calls": len(self.calls),
            "live_calls": self.spent,
            "by_status": statuses,
            "max_calls": self.max_calls,
            "signature_style": self._signature_style,
            "v3_search_available": not self._v3_dead,
            "credentials": self.credentials.redacted(),
        }


# ------------------------------------------------------------------- POI shape
def _as_float(value):
    try:
        if value in (None, "", []):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        if value in (None, "", []):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _split_tags(value) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[;,、，|]", str(value))
    return [part.strip() for part in parts if part.strip() and part.strip() != "全部"]


DAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def opening_window(detail: dict) -> dict:
    """Dominant open/close pair + closed weekdays from a Baidu POI.

    Prefers the structured ``regular_open_hour.periods`` (per weekday, with
    minutes) over the human-readable ``shop_hours`` string, and always reports the
    quote a reviewer can re-check.
    """
    periods = ((detail.get("regular_open_hour") or {}).get("periods") or []) \
        if isinstance(detail, dict) else []
    windows: dict[tuple[str, str], int] = {}
    closed_days: list[str] = []
    for period in periods:
        try:
            open_h, open_m = int(period["open"]["hour"]), int(period["open"]["minute"])
            close_h, close_m = int(period["close"]["hour"]), int(period["close"]["minute"])
            day = int(period["open"].get("day", -1))
        except (KeyError, TypeError, ValueError):
            continue
        if (open_h, open_m) == (0, 0) and (close_h, close_m) in ((0, 0), (24, 0)):
            closed_days.append(DAY_NAMES[day] if 0 <= day <= 6 else str(day))
            continue
        key = (f"{open_h:02d}:{open_m:02d}", f"{close_h:02d}:{close_m:02d}")
        windows[key] = windows.get(key, 0) + 1
    shop_hours = str((detail or {}).get("shop_hours") or "")
    if windows:
        (open_t, close_t), _ = max(windows.items(), key=lambda item: item[1])
        return {"open": open_t, "end": close_t, "quote": f"regular_open_hour {open_t}-{close_t}",
                "closed_days": closed_days, "source": "regular_open_hour", "raw": shop_hours}
    match = re.search(r"(\d{1,2})[:：](\d{2})\s*-\s*(\d{1,2})[:：](\d{2})", shop_hours)
    if match:
        return {"open": f"{int(match.group(1)):02d}:{match.group(2)}",
                "end": f"{int(match.group(3)):02d}:{match.group(4)}",
                "quote": match.group(0), "closed_days": [], "source": "shop_hours", "raw": shop_hours}
    return {"open": None, "end": None, "quote": "", "closed_days": [], "source": "none", "raw": shop_hours}


def comment_bucket(comment_num: int | None) -> str | None:
    """``comment_num`` is capped, so publish a bucket and never a fake count."""
    if comment_num is None:
        return None
    if comment_num >= COMMENT_NUM_CAP:
        return f">={COMMENT_NUM_CAP}(capped)"
    if comment_num >= 50:
        return "50-199"
    if comment_num >= 10:
        return "10-49"
    if comment_num > 0:
        return "1-9"
    return "0"


def normalize_poi(poi: dict, *, source_coord: str = "gcj02ll", detail: dict | None = None) -> dict:
    """Flatten one Baidu POI (search result, optionally enriched with detail).

    ``None`` always means "Baidu did not return this field" — a real, reportable
    outcome, never a value to impute.
    """
    location = poi.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    lng_use, lat_use = lon, lat
    coord_note = source_coord
    if source_coord == "bd09ll" and lon is not None and lat is not None:
        lng_use, lat_use = bd09_to_gcj02(float(lon), float(lat))
        coord_note = "bd09ll->gcj02ll"

    info = dict(poi.get("detail_info") or {})
    if detail:
        info.update(detail.get("detail_info") or {})
    window = opening_window(info)
    comment_num = _as_int(info.get("comment_num"))

    return {
        "uid": poi.get("uid") or (detail or {}).get("uid"),
        "name": poi.get("name") or (detail or {}).get("name"),
        "lat": lat_use,
        "lon": lng_use,
        "coord_type": coord_note,
        "raw_location": location,
        "navi_location": info.get("navi_location"),
        "address": poi.get("address") or (detail or {}).get("address"),
        "province": poi.get("province"),
        "city": poi.get("city"),
        "area": poi.get("area"),
        "telephone": poi.get("telephone") or (detail or {}).get("telephone"),
        "detail": poi.get("detail"),
        # ---- attribute channels (platform taxonomy)
        "type_path": [part for part in str(poi.get("type") or info.get("type") or "").split(";") if part],
        "tag_path": _split_tags(info.get("tag")),
        "classified_tag_path": _split_tags(info.get("classified_poi_tag")),
        "label_path": _split_tags(info.get("label")),
        "scope_type": info.get("scope_type"),
        "scope_grade": info.get("scope_grade"),
        # ---- attribute values
        "shop_hours": info.get("shop_hours"),
        "open_time": window["open"],
        "close_time": window["end"],
        "open_quote": window["quote"],
        "open_source": window["source"],
        "closed_weekdays": window["closed_days"],
        "price_text": info.get("price"),
        "price": _as_float(info.get("price")),
        "overall_rating": _as_float(info.get("overall_rating")),
        "comment_num": comment_num,
        "comment_bucket": comment_bucket(comment_num),
        "image_num": _as_int(info.get("image_num")),
        # ---- visitor-experience channel (platform-curated, UGC-derived)
        "content_tags": _split_tags(info.get("content_tag")),
        "content_tag_raw": info.get("content_tag"),
        # ---- identity helpers
        "alias": _split_tags(info.get("alias")),
        "new_alias": _split_tags(info.get("new_alias")),
        "children": [
            {"uid": child.get("uid"), "name": child.get("name"), "tag": child.get("tag"),
             "location": child.get("location")}
            for child in (info.get("children") or [])
        ],
        "parent_id": info.get("parent_id"),
        "detail_url": info.get("detail_url"),
        "detail_info_keys": sorted(info.keys()),
    }


SUB_SITE_PATTERN = re.compile(
    r"^\s*(?P<parent>[^()（）\[\]【】]+?)\s*[(\[（【]\s*(?P<child>[^)\]）】]+)\s*[)\]）】]\s*$"
)


# Words that can legitimately trail a venue name without naming a different venue:
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
    return {"match": False, "similarity": similarity, "rule": "no_match(legacy)"}


# ------------------------------------------------------------ candidate ranking
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
    r"[-—–_·]\s*(东门|西门|南门|北门|正门|大门|出口|入口|地铁口|[A-Za-z]口|"
    r"[^()（）]{0,8}(停车场|售票处|服务中心|游客中心|广场|码头|车站|接送点|隧道|天桥))\s*$"
)


def strip_facility_suffix(name: str) -> str:
    """``南越王博物院(王墓展区)-东门`` -> ``南越王博物院(王墓展区)``."""
    return FACILITY_SUFFIX.sub("", str(name or "")).strip()


def candidate_score(
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
    verdict = identity_check(request_name, name, aliases=aliases, anchor=anchor, poi_xy=poi_xy)
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


def rank_candidates(
    request_name: str, pois: list[dict], *, anchor: tuple[float, float] | None = None
) -> list[dict]:
    scored = [(candidate_score(request_name, poi, anchor=anchor), index, poi) for index, poi in enumerate(pois)]
    scored.sort(key=lambda item: (-item[0]["score"], item[1]))
    return [{"verdict": item[0], "poi": item[2]} for item in scored]


# --------------------------------------------------------------- source adapter
class BaiduSource:
    """Evidence adapter compatible with ``sources.cached_fetch``.

    Mirrors :class:`AmapSource`: one lookup = one ``Evidence`` whose ``structured``
    payload carries the normalised POI and whose ``text`` is the verbatim JSON, so
    the G3 quote-anchor gate can re-check every claimed value.
    """

    name = "baidu"
    authority = 0.90  # map-platform data: authoritative on identity/hours, not on taste

    def __init__(self, client: BaiduPlaceClient | None = None, *, fetch_detail: bool = True,
                 page_size: int = 5):
        self.client = client or get_client()
        self.fetch_detail = fetch_detail
        self.page_size = page_size

    MIN_SCORE = 0.55  # below this the hit is not the venue; report, never guess

    def _query_ladder(self, name: str, city: str) -> list[dict]:
        """Cheap-to-specific attempts; the first confident hit wins."""
        return [
            {"label": "plain", "kwargs": {"page_size": self.page_size}},
            {"label": "attraction_tag", "kwargs": {"page_size": self.page_size, "tag": "旅游景点"}},
            {"label": "no_city_limit", "kwargs": {"page_size": self.page_size, "city_limit": False}},
        ]

    def fetch(self, name: str, city: str, anchor: tuple[float, float] | None = None) -> Evidence:
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
            ranked = rank_candidates(name, results, anchor=anchor)
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
            best = 0.0
            for attempt in attempts:
                for verdict_row in attempt.get("top") or []:
                    best = max(best, float(verdict_row.get("score") or 0.0))
            return Evidence(
                self.name, url, at, name, "", ok=False,
                structured={
                    "requested_name": name,
                    "region": city,
                    "name_match": False,
                    "candidate_score": round(best, 3),
                    "query_attempts": attempts,
                },
                error=f"no confident match (best candidate score {best:.3f} < {self.MIN_SCORE})",
                authority=self.authority,
            )

        detail_payload = None
        if self.fetch_detail and chosen.get("uid"):
            try:
                detail_payload = self.client.detail(chosen["uid"])
            except Exception:  # noqa: BLE001
                detail_payload = None
        detail_poi = None
        if detail_payload and str(detail_payload.get("status")) == "0":
            detail_poi = detail_payload.get("result")
        flat = normalize_poi(chosen, source_coord="gcj02ll", detail=detail_poi)
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
            "anchor": list(anchor) if anchor else None,
            "detail_fetched": detail_poi is not None,
        })
        text = json.dumps({"search": payload.get("results"),
                           "detail": (detail_payload or {}).get("result")}, ensure_ascii=False)
        return Evidence(self.name, url, at, str(chosen.get("name") or name), text, flat,
                        self.authority)


def default_baidu_source(**kwargs) -> BaiduSource:
    return BaiduSource(**kwargs)


# ------------------------------------------------------------- replay client
class BaiduFixtureClient:
    """Serves responses captured on 2026-10-21. No network, no quota spent.

    Everything returned here is *replayed evidence*: reports must label it as such
    and must not describe it as a fresh API test. The fixture index maps
    ``city|name`` (search) and ``uid`` (detail) to the exact bytes Baidu sent.
    """

    mode = "replay"

    def __init__(self, fixture_dir: str | Path | None = None):
        self.dir = Path(fixture_dir or FIXTURE_DIR)
        index_path = self.dir / "index.json"
        self.index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {
            "searches": {}, "details": {}, "captured_at": None
        }
        self.calls: list[CallRecord] = []
        self._signature_style = "replay"

    @property
    def spent(self) -> int:
        return 0

    @property
    def credentials(self):
        return Credentials(ak="(replay)", sk=None, source="fixture", path=str(self.dir))

    def _load(self, bucket: str, key: str) -> dict | None:
        rel = (self.index.get(bucket) or {}).get(key)
        if not rel:
            return None
        path = self.dir / rel
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def search(self, q: str, region: str, **kwargs) -> dict:
        key = f"{region}|{q}"
        record = self._load("searches", key)
        self.calls.append(CallRecord(SEARCH_V2, {"query": q, "region": region},
                                     None if record is None else 0,
                                     "fixture" if record else "no fixture", 0.0, True, "replay"))
        if record is None:
            return {"status": -3, "message": f"no captured response for {key!r}",
                    "results": [], "_cached": True, "_replayed": True,
                    "_endpoint": "fixture", "_signature_style": "n/a"}
        payload = dict(record["raw"])
        payload.update({"_cached": True, "_replayed": True, "_endpoint": "fixture",
                        "_signature_style": "n/a", "_captured_at": record.get("captured_at"),
                        "_ignored_kwargs": sorted(kwargs)})
        return payload

    def detail(self, uid: str, **kwargs) -> dict:
        record = self._load("details", uid)
        self.calls.append(CallRecord(DETAIL_V2, {"uid": uid}, None if record is None else 0,
                                     "fixture" if record else "no fixture", 0.0, True, "replay"))
        if record is None:
            return {"status": -3, "message": f"no captured detail for {uid}",
                    "result": None, "_replayed": True, "_endpoint": "fixture"}
        payload = dict(record["raw"])
        payload.update({"_cached": True, "_replayed": True, "_endpoint": "fixture",
                        "_captured_at": record.get("captured_at")})
        return payload

    def discover_signature_style(self, *args, **kwargs) -> dict:
        return {"ok": False, "style": "replay", "reason": "回放模式：签名已在 2026-10-21 实测通过，此处不重测",
                "trials": [], "sn_required": True}

    def budget_report(self) -> dict:
        return {"mode": "replay", "calls": len(self.calls), "live_calls": 0,
                "available_searches": sorted(self.index.get("searches") or {}),
                "available_details": sorted(self.index.get("details") or {}),
                "captured_at": self.index.get("captured_at")}


class BaiduBlockedClient:
    """Returned when a caller asks for ``live`` while the budget is 0.

    It answers every call with an explicit ``blocked`` payload instead of raising,
    so a pipeline that still asks Baidu degrades gracefully instead of crashing.
    """

    mode = "blocked"

    def __init__(self, reason: str):
        self.reason = reason
        self.calls: list[CallRecord] = []

    @property
    def spent(self) -> int:
        return 0

    @property
    def credentials(self):
        return Credentials(ak="(blocked)", sk=None, source="budget_zero")

    def _payload(self, path: str) -> dict:
        self.calls.append(CallRecord(path, {}, None, self.reason, 0.0, True, "blocked"))
        return {"status": -2, "message": self.reason, "result": None, "results": [],
                "_cached": False, "_blocked": True, "_blocked_reason": self.reason,
                "_endpoint": path}

    def search(self, q: str, region: str, **kwargs) -> dict:
        return self._payload(SEARCH_V2)

    def detail(self, uid: str, **kwargs) -> dict:
        return self._payload(DETAIL_V2)

    def discover_signature_style(self, *args, **kwargs) -> dict:
        return {"ok": False, "style": None, "reason": self.reason, "trials": [],
                "sn_required": True}

    def budget_report(self) -> dict:
        return {"mode": "blocked", "reason": self.reason, "calls": len(self.calls),
                "live_calls": 0, "max_calls": 0}


def get_client(mode: str = "auto", **kwargs):
    """Resolve a Baidu client honouring the P0 budget rule.

    * ``auto``  — replay fixtures when present (default), never live;
    * ``replay``— fixtures only;
    * ``live``  — only if the configured budget is > 0, otherwise a client that
      returns an explicit ``budget_zero`` error for every call and opens no socket.
    """
    if mode == "live":
        budget = live_budget()
        if budget <= 0 or offline_forced():
            return BaiduBlockedClient(
                f"百度请求预算为 0（BAIDU_REQUEST_BUDGET={budget}），已阻断；改用开放数据源")
        return BaiduPlaceClient(max_calls=budget, **kwargs)
    if mode == "replay":
        return BaiduFixtureClient(kwargs.pop("fixture_dir", None))
    if offline_forced() or live_budget() <= 0 or (FIXTURE_DIR / "index.json").exists():
        if (FIXTURE_DIR / "index.json").exists():
            return BaiduFixtureClient(kwargs.pop("fixture_dir", None))
        return BaiduBlockedClient("百度预算为 0 且无本地夹具，已阻断")
    return BaiduPlaceClient(**kwargs)


def probe_place_api(client: BaiduPlaceClient, *, q: str = "广州塔", region: str = "广州") -> dict:
    """Record exactly which Place API fields this account can obtain today."""
    out: dict = {"signature": client.discover_signature_style()}
    if not out["signature"].get("ok"):
        out["ok"] = False
        return out
    search = client.search(q, region, page_size=3)
    out["search"] = {"status": search.get("status"), "message": search.get("message"),
                     "endpoint": search.get("_endpoint"),
                     "n_pois": len(search.get("results") or [])}
    results = search.get("results") or []
    if not results:
        out["ok"] = False
        return out
    flat = normalize_poi(results[0], source_coord="gcj02ll")
    out["poi"] = flat
    out["field_availability"] = {
        key: flat.get(key) not in (None, "", [])
        for key in ("uid", "address", "type_path", "tag_path", "label_path", "shop_hours", "open_time",
                    "price", "overall_rating", "comment_num", "content_tags", "telephone", "detail_url")
    }
    if flat.get("uid"):
        detail = client.detail(flat["uid"])
        out["detail"] = {"status": detail.get("status"), "message": detail.get("message"),
                         "endpoint": detail.get("_endpoint"),
                         "keys": sorted(((detail.get("result") or {}).get("detail_info") or {}).keys())}
        if detail.get("result"):
            out["detail_poi"] = normalize_poi(detail["result"], source_coord="gcj02ll")
    out["ok"] = True
    out["budget"] = client.budget_report()
    out["endpoint_notes"] = ENDPOINT_NOTES
    return out
