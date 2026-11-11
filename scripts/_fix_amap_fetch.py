"""Recovery: re-attach AmapSource.fetch (lost during patch 3) by appending a
module-level implementation and monkey-patching the class."""
from pathlib import Path

DYN = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic"
path = DYN / "sources.py"
text = path.read_text(encoding="utf-8")

if "_amap_fetch_impl" in text:
    print("already patched")
    raise SystemExit(0)

block = '''

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
'''

path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
print("re-attached AmapSource.fetch")
