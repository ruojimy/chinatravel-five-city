"""Can Amap / Baidu return a hotel price *range*?

Probes three Xi'an hotels with known observed prices against:
  - Amap v5 place/text (show_fields=business -> business.cost / rating)
  - Amap v3 place/text (extensions=all -> biz_ext.cost / rating)
  - Baidu Place v2 search + detail (detail_info.price / overall_rating)

Writes results/api_hotel_price_probe_20261111.json (keys never logged).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BAIDU_REQUEST_BUDGET", "8")
os.environ.setdefault("BAIDU_OFFLINE", "0")
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials  # noqa: E402

HOTELS = [
    ("西安威斯汀大酒店", 776),
    ("金鑫宾馆(西安钟楼店)", 84),
    ("秋林酒店(西安建筑科技大学李家村地铁站店)", 154),
]
OUT = ROOT / "results/api_hotel_price_probe_20261111.json"
UA = "ShortTripAssistant/1.0 (price-range probe)"


def amap_key() -> str:
    path = ROOT / ".secrets/amap.key"
    return path.read_text(encoding="ascii").strip()


def http_json(url: str, params: dict, timeout: int = 20) -> dict:
    query = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(query, headers={"User-Agent": UA})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return {"_http": resp.status, "_seconds": round(time.monotonic() - started, 2),
            "body": json.loads(raw)}


def price_like(value) -> dict:
    text = "" if value is None else str(value).strip()
    is_range = bool(re.search(r"\d+\s*[-~—至]\s*\d+", text))
    return {"raw": text, "is_range": is_range,
            "is_positive_number": bool(re.fullmatch(r"\d+(\.\d+)?", text)) and float(text) > 0}


def probe_amap(name: str) -> dict:
    key = amap_key()
    out = {}
    for label, url, params in (
        ("v5_text", "https://restapi.amap.com/v5/place/text",
         {"key": key, "keywords": name, "region": "西安", "city_limit": "true",
          "show_fields": "business", "page_size": "5", "page": "1"}),
        ("v3_text", "https://restapi.amap.com/v3/place/text",
         {"key": key, "keywords": name, "city": "西安", "citylimit": "true",
          "extensions": "all", "offset": "5", "page": "1"}),
    ):
        try:
            got = http_json(url, params)
            body = got["body"]
            pois = body.get("pois") or []
            best = next((p for p in pois if p.get("name") == name), pois[0] if pois else None)
            business = (best or {}).get("business") or {}
            biz_ext = (best or {}).get("biz_ext") or {}
            cost = business.get("cost") if label.startswith("v5") else biz_ext.get("cost")
            rating = business.get("rating") if label.startswith("v5") else biz_ext.get("rating")
            out[label] = {
                "http": got["_http"], "seconds": got["_seconds"],
                "status": body.get("status"), "info": body.get("info"),
                "count": body.get("count"), "returned": len(pois),
                "matched_name": (best or {}).get("name"),
                "poi_type": (best or {}).get("type"),
                "cost": price_like(cost), "rating": rating,
                "tag": business.get("tag") or (best or {}).get("tag"),
            }
        except Exception as exc:  # noqa: BLE001
            out[label] = {"error": f"{type(exc).__name__}: {exc}"}
        time.sleep(0.4)
    return out


def probe_baidu(name: str, client: BaiduPlaceClient) -> dict:
    out = {}
    try:
        found = client.search(name, "西安", page_size=5)
        results = found.get("results") or []
        best = next((r for r in results if r.get("name") == name), results[0] if results else None)
        info = (best or {}).get("detail_info") or {}
        out["search"] = {
            "status": found.get("status"), "message": found.get("message"),
            "returned": len(results), "matched_name": (best or {}).get("name"),
            "uid": (best or {}).get("uid"), "type": (best or {}).get("type"),
            "price": price_like(info.get("price")),
            "overall_rating": info.get("overall_rating") or info.get("price"),
            "comment_num": info.get("comment_num"),
        }
        uid = (best or {}).get("uid")
        if uid:
            detail = client.detail(uid)
            d_info = ((detail.get("result") or {}).get("detail_info") or {})
            out["detail"] = {
                "status": detail.get("status"), "message": detail.get("message"),
                "price": price_like(d_info.get("price")),
                "overall_rating": d_info.get("overall_rating"),
                "comment_num": d_info.get("comment_num"),
                "shop_hours": d_info.get("shop_hours"),
                "tag": d_info.get("tag"),
            }
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> int:
    creds = load_credentials()
    client = BaiduPlaceClient(credentials=creds, cache=False, max_calls=8, timeout=20)
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "credentials": {"baidu": creds.redacted()},
              "hotels": []}
    for name, observed in HOTELS:
        entry = {"hotel": name, "observed_price": observed,
                 "amap": probe_amap(name), "baidu": probe_baidu(name, client)}
        report["hotels"].append(entry)
        print(json.dumps(entry, ensure_ascii=False, indent=1), flush=True)
    report["baidu_calls"] = client.spent
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}  baidu_network_calls={client.spent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
