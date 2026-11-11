"""Probe connectivity + real payload shape for Overpass, Nominatim and Wikidata.

Cheap: 1 Overpass query, 1 Nominatim query, 2 Wikidata calls. Records exactly what
came back so the adapters are written against reality, not assumptions.
"""
import json
import sys
import urllib.parse
import urllib.request

UA = "ShortTripAssistant/1.0 (course project; POI attribute check)"
OUT = "reproduction/results/p1/open_data_probe.json"


def get(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def post(url, body, timeout=60):
    req = urllib.request.Request(url, data=body.encode("utf-8"),
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


report = {}

# 1) Overpass: small around query at 广州塔
ql = """[out:json][timeout:25];
(
  nwr(around:200,23.10628,113.32453)["tourism"];
  nwr(around:200,23.10628,113.32453)["historic"];
  nwr(around:200,23.10628,113.32453)["leisure"];
);
out tags center 12;"""
try:
    status, text = post("https://overpass-api.de/api/interpreter", "data=" + urllib.parse.quote(ql))
    data = json.loads(text)
    elements = data.get("elements") or []
    report["overpass"] = {
        "status": status, "n": len(elements),
        "elements": [
            {"type": e.get("type"), "id": e.get("id"), "lat": e.get("lat"), "lon": e.get("lon"),
             "center": e.get("center"), "tags": e.get("tags")}
            for e in elements[:8]
        ],
    }
    print("overpass ok n=", len(elements))
except Exception as exc:  # noqa: BLE001
    report["overpass"] = {"error": str(exc)}
    print("overpass ERR", exc)

# 2) Nominatim with extratags
try:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": "广州塔 广州", "format": "jsonv2", "limit": 2, "extratags": 1,
         "addressdetails": 0, "accept-language": "zh"})
    status, text = get(url)
    rows = json.loads(text)
    report["nominatim"] = {"status": status, "n": len(rows),
                           "first": {k: rows[0].get(k) for k in ("display_name", "lat", "lon", "osm_type",
                                                                  "osm_id", "class", "type", "extratags")} if rows else None}
    print("nominatim ok n=", len(rows))
except Exception as exc:  # noqa: BLE001
    report["nominatim"] = {"error": str(exc)}
    print("nominatim ERR", exc)

# 3) Wikidata: zhwiki titles -> entities (batch capable)
titles = ["广州塔", "故宫博物院", "南越王博物院", "陈家祠", "上海博物馆"]
try:
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetentities", "sites": "zhwiki", "titles": "|".join(titles),
         "props": "claims|labels|aliases|sitelinks", "languages": "zh|en",
         "sitefilter": "zhwiki", "format": "json", "normalize": 1})
    status, text = get(url)
    data = json.loads(text)
    entities = data.get("entities") or {}
    summary = {}
    for qid, ent in entities.items():
        if qid.startswith("-"):
            summary[qid] = {"missing": True, "input": ent}
            continue
        claims = ent.get("claims") or {}
        summary[qid] = {
            "label_zh": ((ent.get("labels") or {}).get("zh") or {}).get("value"),
            "n_claims": len(claims),
            "P31": [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                    for c in claims.get("P31", []) if c.get("mainsnak", {}).get("datavalue")],
            "P625": [c["mainsnak"].get("datavalue", {}).get("value")
                     for c in claims.get("P625", []) if c.get("mainsnak", {}).get("datavalue")],
            "P1435": [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                      for c in claims.get("P1435", []) if c.get("mainsnak", {}).get("datavalue")],
            "sitelinks": list((ent.get("sitelinks") or {}).keys())[:5],
            "claims_keys": sorted(claims.keys())[:40],
        }
    report["wikidata_titles"] = {"status": status, "n": len(entities), "entities": summary}
    print("wikidata titles ok n=", len(entities))
except Exception as exc:  # noqa: BLE001
    report["wikidata_titles"] = {"error": str(exc)}
    print("wikidata ERR", exc)

# 4) Wikidata P31 label expansion
try:
    ids = set()
    for ent in (report.get("wikidata_titles", {}).get("entities") or {}).values():
        ids.update(ent.get("P31") or [])
    ids = sorted(ids)[:40]
    if ids:
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|descriptions",
             "languages": "zh|en", "format": "json"})
        status, text = get(url)
        data = json.loads(text)
        labels = {}
        for qid, ent in (data.get("entities") or {}).items():
            labels[qid] = {
                "zh": ((ent.get("labels") or {}).get("zh") or {}).get("value"),
                "en": ((ent.get("labels") or {}).get("en") or {}).get("value"),
                "desc_zh": ((ent.get("descriptions") or {}).get("zh") or {}).get("value"),
            }
        report["wikidata_types"] = {"status": status, "labels": labels}
        print("wikidata types ok n=", len(labels))
    else:
        report["wikidata_types"] = {"note": "no P31 collected"}
except Exception as exc:  # noqa: BLE001
    report["wikidata_types"] = {"error": str(exc)}
    print("wikidata types ERR", exc)

with open(OUT, "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print("wrote", OUT)
