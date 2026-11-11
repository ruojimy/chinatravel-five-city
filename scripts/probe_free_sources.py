"""Probe free, no-key sources for POI facts (OSM/Nominatim, Wikipedia, Wikidata)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

UA = "ShortTripResearch/1.0 (course project; contact: student)"


def get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def main() -> int:
    name = "南越王博物院"
    print("== Nominatim")
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": name, "format": "jsonv2", "limit": 3, "accept-language": "zh", "addressdetails": 1}
    )
    try:
        rows = json.loads(get(url))
        print(len(rows), "hits")
        for row in rows[:3]:
            print("  ", row.get("display_name"), row.get("lat"), row.get("lon"), row.get("class"), row.get("type"))
    except Exception as exc:  # noqa: BLE001
        print("FAIL", exc)

    print("\n== Wikipedia zh extract")
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
    try:
        data = json.loads(get(url))
        pages = data["query"]["pages"]
        for page_id, page in pages.items():
            print("  page:", page.get("title"), "missing" if "missing" in page else "ok")
            print("  coords:", page.get("coordinates"))
            print("  url:", page.get("fullurl"))
            extract = page.get("extract", "")
            print("  extract chars:", len(extract))
            for keyword in ("开放", "门票", "时间", "票价", "免费"):
                idx = extract.find(keyword)
                if idx >= 0:
                    print(f"   ...{keyword}: {extract[max(0, idx-60):idx+120].strip()}")
    except Exception as exc:  # noqa: BLE001
        print("FAIL", exc)

    print("\n== Wikidata claims")
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetentities", "sites": "zhwiki", "titles": name, "props": "claims|labels|sitelinks", "languages": "zh|en", "format": "json"}
    )
    try:
        data = json.loads(get(url))
        for entity_id, entity in data["entities"].items():
            print("  entity:", entity_id, entity.get("labels", {}).get("zh", {}).get("value"))
            claims = entity.get("claims", {})
            print("  claim props:", sorted(claims)[:20])
            for prop in ("P625", "P856", "P571", "P1619", "P610", "P1174"):
                if prop in claims:
                    print(f"   {prop}:", json.dumps(claims[prop][0]["mainsnak"].get("datavalue", {}), ensure_ascii=False)[:200])
    except Exception as exc:  # noqa: BLE001
        print("FAIL", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
