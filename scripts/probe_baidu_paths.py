"""Which Baidu Web Service paths exist for this AK? Signature is already proven,
so HTTP 404 == "no such endpoint" and 211 == "signature rejected".

`/geocoder/v2/` is the control: Baidu's own SN documentation signs it, so it must
answer (200 or a permission code), never 404.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.dynamic.baidu import (  # noqa: E402
    HOST,
    UA,
    canonical_query,
    load_credentials,
    sign_query,
)

CASES = [
    # (label, path, params)
    ("control_geocoder_v2", "/geocoder/v2/", {"address": "百度大厦", "output": "json"}),
    ("place_v2_search", "/place/v2/search", {"query": "广州塔", "region": "广州", "output": "json"}),
    ("place_v3_search_q", "/place/v3/search", {"q": "广州塔", "region": "广州", "output": "json"}),
    ("place_v3_search_query", "/place/v3/search", {"query": "广州塔", "region": "广州", "output": "json"}),
    ("place_abroad_v1", "/place_abroad/v1/search", {"query": "广州塔", "region": "广州", "output": "json"}),
    ("place_search_v3", "/place/search/v3", {"q": "广州塔", "region": "广州", "output": "json"}),
    ("api_place_v3_search", "/api/place/v3/search", {"q": "广州塔", "region": "广州", "output": "json"}),
    ("place_v2_detail", "/place/v2/detail", {"uid": "dummy", "output": "json"}),
    ("place_v3_detail", "/place/v3/detail", {"uid": "dummy", "output": "json"}),
    ("place_v2_suggestion", "/place/v2/suggestion", {"query": "广州塔", "region": "广州", "output": "json"}),
    ("direction_v2_walking", "/direction/v2/walking", {"origin": "23.1,113.2", "destination": "23.2,113.3"}),
]


def call(path: str, params: dict, ak: str, sk: str) -> dict:
    full = dict(params)
    full["ak"] = ak
    qs = canonical_query(full, "java")
    sn = sign_query(path, qs, sk)
    url = f"{HOST}{path}?{qs}&sn={sn}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return {"http": resp.status, "json": json.loads(body)}
            except json.JSONDecodeError:
                return {"http": resp.status, "raw": body[:300]}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return {"http": exc.code, "raw": body[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "error": str(exc)}


def main() -> int:
    creds = load_credentials()
    rows = []
    for label, path, params in CASES:
        result = call(path, params, creds.ak, creds.sk or "")
        payload = result.get("json") or {}
        rows.append(
            {
                "label": label,
                "path": path,
                "http": result.get("http"),
                "status": payload.get("status"),
                "message": payload.get("message") or payload.get("msg"),
                "raw": result.get("raw"),
            }
        )
        print(f"{label:26s} http={result.get('http')} status={payload.get('status')} msg={payload.get('message') or payload.get('msg')}")
    out = ROOT / "results" / "baidu_path_probe.json"
    out.write_text(json.dumps({"credentials": creds.redacted(), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
