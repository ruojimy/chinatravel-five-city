import csv, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BAIDU_REQUEST_BUDGET", "20")
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials

CSV_PATH = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")
rows = [r for r in csv.DictReader(open(CSV_PATH, encoding="utf-8-sig"))
        if r["price_status"] == "unknown"
        and (any(k in r["name"] for k in HOSTEL) or str(r["numbed"]).strip() == "2")]
key = (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()
UA = "probe"


def get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def amap_detail(poi_id):
    return get("https://restapi.amap.com/v5/place/detail",
               {"key": key, "id": poi_id, "show_fields": "business"})


def amap_around(lat, lon):
    return get("https://restapi.amap.com/v5/place/around",
               {"key": key, "location": f"{lon},{lat}", "radius": "300",
                "types": "100000", "show_fields": "business", "page_size": "10",
                "page": "1"})


client = BaiduPlaceClient(credentials=load_credentials(), cache=False, max_calls=20)
out = []
for r in rows:
    name = r["name"]
    rec = {"name": name, "numbed": r["numbed"], "lat": r["lat"], "lon": r["lon"]}
    # 1) Amap text -> id -> detail
    try:
        body = get("https://restapi.amap.com/v5/place/text",
                   {"key": key, "keywords": name, "region": "西安", "city_limit": "true",
                    "show_fields": "business", "page_size": "3", "page": "1"})
        pois = body.get("pois") or []
        best = next((p for p in pois if p.get("name") == name), None)
        rec["amap_id"] = (best or {}).get("id")
        rec["amap_text_cost"] = ((best or {}).get("business") or {}).get("cost")
        if rec["amap_id"]:
            d = amap_detail(rec["amap_id"])
            pois2 = d.get("pois") or []
            rec["amap_detail_cost"] = (((pois2[0] if pois2 else {}).get("business")) or {}).get("cost")
    except Exception as exc:  # noqa: BLE001
        rec["amap_error"] = f"{type(exc).__name__}: {exc}"
    time.sleep(0.4)
    # 2) Amap around
    try:
        around = amap_around(r["lat"], r["lon"])
        hits = [p for p in (around.get("pois") or []) if p.get("name") == name]
        rec["amap_around_cost"] = ((hits[0].get("business") if hits else {}) or {}).get("cost")
    except Exception as exc:  # noqa: BLE001
        rec["amap_around_error"] = f"{type(exc).__name__}: {exc}"
    time.sleep(0.4)
    # 3) Baidu search -> uid -> detail
    try:
        found = client.search(name, "西安", page_size=3)
        results = found.get("results") or []
        best = next((x for x in results if x.get("name") == name), None)
        rec["baidu_uid"] = (best or {}).get("uid")
        rec["baidu_search_price"] = ((best or {}).get("detail_info") or {}).get("price")
        if rec["baidu_uid"]:
            detail = client.detail(rec["baidu_uid"])
            di = ((detail.get("result") or {}).get("detail_info") or {})
            rec["baidu_detail_price"] = di.get("price")
            rec["baidu_detail_type"] = di.get("type") or (detail.get("result") or {}).get("type")
    except Exception as exc:  # noqa: BLE001
        rec["baidu_error"] = f"{type(exc).__name__}: {exc}"
    out.append(rec)
    time.sleep(0.5)
print(json.dumps(out, ensure_ascii=False, indent=1))
print("baidu calls", client.spent)
(ROOT / "results/per_capita_target_extra_probe_20261111.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
