"""Probe which Amap (高德) Web Service APIs this key can use, and what fields
they return for a POI that the ChinaTravel sandbox does not contain.

Writes results/amap_probe.json (UTF-8) so the console encoding does not matter.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _keys import amap_key  # noqa: E402

KEY = amap_key()
OUT = Path(__file__).resolve().parents[1] / "results" / "amap_probe.json"
UA = "ShortTripAssistant/1.0"


def call(path: str, params: dict) -> dict:
    url = "https://restapi.amap.com" + path + "?" + urllib.parse.urlencode({**params, "key": KEY})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def main() -> int:
    report: dict = {}

    # 1) POI 关键字搜索 v5
    v5 = call(
        "/v5/place/text",
        {"keywords": "南越王博物院", "region": "广州", "city_limit": "true", "page_size": 3, "show_fields": "business"},
    )
    report["v5_place_text"] = {
        "status": v5.get("status"),
        "info": v5.get("info"),
        "infocode": v5.get("infocode"),
        "count": v5.get("count"),
        "first": (v5.get("pois") or [{}])[0],
    }

    # 2) v3 POI 搜索（老接口，含 biz_ext）
    v3 = call("/v3/place/text", {"keywords": "南越王博物院", "city": "广州", "offset": 3, "extensions": "all"})
    report["v3_place_text"] = {
        "status": v3.get("status"),
        "info": v3.get("info"),
        "count": v3.get("count"),
        "first": (v3.get("pois") or [{}])[0],
    }

    # 3) POI 详情（拿 biz_ext / opentime / cost）
    poi_id = None
    for bucket in ("v5_place_text", "v3_place_text"):
        first = report[bucket].get("first") or {}
        poi_id = first.get("id") or poi_id
    if poi_id:
        detail = call("/v3/place/detail", {"id": poi_id, "extensions": "all"})
        report["v3_place_detail"] = {
            "status": detail.get("status"),
            "info": detail.get("info"),
            "pois": detail.get("pois"),
        }

    # 4) 地理编码
    geo = call("/v3/geocode/geo", {"address": "南越王博物院", "city": "广州"})
    report["geocode"] = {"status": geo.get("status"), "info": geo.get("info"), "geocodes": geo.get("geocodes")}

    # 5) 步行/驾车/公交路径（用真实路网校验沙盒 goto）
    for mode, path in (("walking", "/v3/direction/walking"), ("driving", "/v3/direction/driving"), ("transit", "/v3/direction/transit/integrated")):
        params = {"origin": "113.2644,23.1291", "destination": "113.2556,23.1403"}
        if mode == "transit":
            params.update({"city": "广州", "cityd": "广州"})
        route = call(path, params)
        route.pop("key", None)
        report[f"route_{mode}"] = {
            "status": route.get("status"),
            "info": route.get("info"),
            "route_keys": list((route.get("route") or {}).keys()),
        }

    # 6) 天气（未来可用于"下雨改室内"的扰动）
    weather = call("/v3/weather/weatherInfo", {"city": "440100", "extensions": "base"})
    report["weather"] = {"status": weather.get("status"), "info": weather.get("info"), "lives": (weather.get("lives") or [{}])[0]}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("statuses:", {k: (v.get("status"), v.get("info")) for k, v in report.items()})
    print("poi_id:", poi_id, "-> wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
