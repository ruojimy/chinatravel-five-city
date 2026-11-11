"""P1: match 50 ChinaTravel POIs against OSM (ODbL) and Wikidata (CC0).

This is the first real deliverable of the open-data route and it answers one
question with evidence: *how much of the benchmark can be covered without Baidu?*

Sample design (stratified, not hand-picked to look good)
-------------------------------------------------------
* 9 sandbox cities, several sandbox ``type`` values, three price bands;
* deliberately includes **cross-city same-name** cases (a classic identity trap);
* includes both famous and obscure venues so precision is not flattered.

Matching rules (measured against real data, see results/p1/open_data_probe.json)
-------------------------------------------------------------------------------
* Identity is **name-first**. OSM `around` queries at sandbox coordinates return 0
  objects because the sandbox is GCJ-02 with ~1.4 km drift; 广州塔 also has no
  ``tourism=*`` tag in OSM. So a category filter before matching loses data.
* Exact normalised name or alias => match. Prefix/containment only when the extra
  part is a locator word (景区/公园/博物馆…). Otherwise **abstain**.
* Coordinates are converted GCJ-02 -> WGS-84 and used only as a *soft* signal; a
  match with > 3 km distance is reported but marked low confidence.

Outputs
  results/p1/poi_mapping.json / .csv       per-POI outcome with the rule that fired
  datasets/p1/poi_sample_50.json           the frozen sample for reproducibility
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import (  # noqa: E402
    NominatimOsmSource,
    WikidataSource,
    gcj02_to_wgs84,
    km_between,
    match_identity,
    type_to_tags,
)
from shorttrip.env import get_env  # noqa: E402

CITIES = ["广州", "上海", "北京", "杭州", "成都", "南京", "重庆", "武汉", "苏州"]
OUT_JSON = ROOT / "results" / "p1" / "poi_mapping.json"
OUT_CSV = ROOT / "results" / "p1" / "poi_mapping.csv"
SAMPLE = ROOT / "datasets" / "p1" / "poi_sample_50.json"
TARGET_N = 50
MAX_KM_SOFT = 3.0      # beyond this the coordinate only corroborates weakly
MAX_KM_REJECT_WD = 15.0  # beyond this a same-named Wikidata entity is a different place
MAX_KM_REJECT_OSM = 10.0


def build_sample(env) -> list[dict]:
    """Stratified 50 POIs: per city — famous (priciest), free, museum-ish, long-name."""
    random.seed(20261021)
    per_city: dict[str, list[dict]] = {}
    duplicates: dict[str, list[str]] = {}
    for city in CITIES:
        table = env.attraction_table(city)
        if table is None or table.empty:
            continue
        frame = table.copy()
        frame["price"] = frame["price"].astype(float)
        picks: list[dict] = []

        def add(row, reason: str) -> None:
            if any(item["local_poi_id"] == f"sandbox:{city}:{row['name']}" for item in picks):
                return
            picks.append({
                "local_poi_id": f"sandbox:{city}:{row['name']}",
                "city": city, "name": str(row["name"]), "type": str(row["type"]),
                "lat": float(row["lat"]), "lon": float(row["lon"]),
                "price": float(row["price"]), "opentime": str(row["opentime"]),
                "endtime": str(row["endtime"]), "recommendmintime": float(row["recommendmintime"]),
                "sample_reason": reason,
            })

        priciest = frame.sort_values("price", ascending=False).head(3)
        for _, row in priciest.iterrows():
            add(row, "priciest")
        free = frame[frame["price"] <= 0]
        if not free.empty:
            add(free.iloc[len(free) // 2], "free")
        museums = frame[frame["type"].astype(str).str.contains("博物馆|纪念馆")]
        if not museums.empty:
            add(museums.iloc[0], "museum_typed")
        long_names = frame.assign(n=frame["name"].astype(str).str.len()).sort_values("n", ascending=False)
        if not long_names.empty:
            add(long_names.iloc[0], "long_name")
        rest = frame.sample(min(3, len(frame)), random_state=20261021)
        for _, row in rest.iterrows():
            add(row, "random")
        per_city[city] = picks
        for name in frame["name"].astype(str):
            duplicates.setdefault(name, []).append(city)

    # cross-city same-name stratum: a name that exists in >=2 cities is an identity trap
    same_name_cases = []
    for name, cities in duplicates.items():
        if len({city for city in cities}) >= 2:
            for city in sorted({city for city in cities})[:2]:
                table = env.attraction_table(city)
                match = table[table["name"].astype(str) == name]
                if match.empty:
                    continue
                row = match.iloc[0]
                same_name_cases.append({
                    "local_poi_id": f"sandbox:{city}:{name}", "city": city, "name": name,
                    "type": str(row["type"]), "lat": float(row["lat"]), "lon": float(row["lon"]),
                    "price": float(row["price"]), "opentime": str(row["opentime"]),
                    "endtime": str(row["endtime"]), "recommendmintime": float(row["recommendmintime"]),
                    "sample_reason": f"cross_city_same_name({len(cities)} cities)",
                })

    ordered = same_name_cases[:6]
    cursor = {city: 0 for city in per_city}
    while len(ordered) < TARGET_N:
        progressed = False
        for city, picks in per_city.items():
            if len(ordered) >= TARGET_N:
                break
            index = cursor[city]
            if index < len(picks):
                ordered.append(picks[index])
                cursor[city] = index + 1
                progressed = True
        if not progressed:
            break
    return ordered[:TARGET_N]


def main() -> int:
    env = get_env("zh")
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    if SAMPLE.exists() and "--rebuild" not in sys.argv:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))["pois"]
        print(f"loaded frozen sample n={len(sample)} from {SAMPLE}")
    else:
        sample = build_sample(env)
        SAMPLE.write_text(json.dumps({"generated_at": "2026-10-21", "n": len(sample),
                                      "cities": sorted({row['city'] for row in sample}),
                                      "pois": sample}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"built sample n={len(sample)} -> {SAMPLE}")

    wikidata = WikidataSource()
    osm = NominatimOsmSource()

    # ---- Wikidata: one batched title lookup, then one SPARQL label lookup for misses
    titles = [row["name"] for row in sample]
    entities = wikidata.entities_by_titles(titles)
    by_title: dict[str, str] = {}
    for qid, entity in entities.items():
        if qid.startswith("_"):
            continue
        zhwiki = (entity.get("sitelinks") or {}).get("zhwiki") or {}
        title = zhwiki.get("title")
        if title:
            by_title[title] = qid
    missing_titles = [name for name in titles if name not in by_title]
    label_hits = wikidata.items_by_labels(missing_titles) if missing_titles else {}
    label_entities = wikidata.entities_by_titles(list(label_hits.keys())) if label_hits else {}
    print(f"wikidata batch: {len(by_title)} title->QID, "
          f"{len(label_hits)} label->QID via SPARQL, of {len(titles)} POIs")

    summaries: dict[str, dict] = {}
    all_entities = {**{k: v for k, v in entities.items() if not k.startswith("_")},
                    **{k: v for k, v in label_entities.items() if not k.startswith("_")}}
    for qid, entity in all_entities.items():
        if not isinstance(entity, dict) or "claims" not in entity:
            continue
        summaries[qid] = wikidata.summarize(entity)
    type_qids = [qid for summary in summaries.values() for qid in (summary.get("instance_of") or [])]
    labels = wikidata.type_labels(type_qids)
    tag_map = type_to_tags(labels)
    print(f"wikidata types: {len(labels)} P31 labels, {len(tag_map)} mapped to tags")

    rows = []
    # ---- pass 1: OSM lookup first, so an explicit `wikidata=Q…` OSM tag can pull in
    # the entity even when the zhwiki-title lookup missed it (this is the strongest
    # cross-source identity evidence available, and it raised tag coverage).
    osm_results: dict[str, dict] = {}
    for poi in sample:
        osm_results[poi["local_poi_id"]] = osm.lookup(
            poi["name"], poi["city"], anchor_gcj=(poi["lat"], poi["lon"]))
    bridged_qids = set()
    for poi in sample:
        result = osm_results[poi["local_poi_id"]]
        for hit in result.get("hits") or []:
            if match_identity(poi["name"], hit.display_name.split(",")[0], [hit.name])["match"]:
                qid = (hit.tags or {}).get("wikidata")
                if qid:
                    bridged_qids.add(qid)
                break
    bridged_entities = wikidata.entities_by_ids(sorted(bridged_qids)) if bridged_qids else {}
    for qid, entity in bridged_entities.items():
        if "claims" in entity:
            summaries[qid] = wikidata.summarize(entity)
    extra_types = [qid for summary in summaries.values()
                   for qid in (summary.get("instance_of") or []) if qid not in labels]
    if extra_types:
        labels.update(wikidata.type_labels(extra_types))
        tag_map = type_to_tags(labels)
    print(f"osm wikidata bridge: {len(bridged_qids)} QIDs, {len(bridged_entities)} fetched")

    for index, poi in enumerate(sample, start=1):
        # NOTE: these must be reset per POI. A leaked value here silently attached
        # the previous POI's entity to the next one (a spa and a skydiving site were
        # briefly tagged as "urban park"). Caught by manual spot-check of 39 records.
        osm_wikidata = None
        entry = {
            "local_poi_id": poi["local_poi_id"], "city": poi["city"], "name": poi["name"],
            "type": poi["type"], "price": poi["price"], "sample_reason": poi["sample_reason"],
            "sandbox_xy": [poi["lat"], poi["lon"]],
        }
        # --- Wikidata identity
        qid = by_title.get(poi["name"])
        wd_rule = "zhwiki_title_exact" if qid else "none"
        if qid is None and poi["name"] in label_hits:
            qid = label_hits[poi["name"]]
            wd_rule = "sparql_label_exact"
        entry["wikidata"] = {"qid": qid, "match_rule": wd_rule, "qid_accepted": None}
        if qid and qid in summaries:
            summary = summaries[qid]
            coords = summary.get("coordinates") or {}
            distance = None
            if coords.get("lat") is not None and coords.get("lon") is not None:
                wlon, wlat = gcj02_to_wgs84(poi["lon"], poi["lat"])
                distance = round(km_between((wlat, wlon), (coords["lat"], coords["lon"])), 2)
            # Two independent sources agreeing on the QID is the strongest identity
            # signal available here (OSM tags frequently carry `wikidata=Q…`), so it
            # overrides the distance test. Absence of P625 is *not* evidence of a
            # different place: it only means "needs geo check".
            osm_wikidata = None
            entry["wikidata"].update({
                "label_zh": summary.get("label_zh"),
                "description_zh": summary.get("description_zh"),
                "instance_of": summary.get("instance_of") or [],
                "type_labels": [labels.get(item, {}) for item in (summary.get("instance_of") or [])][:4],
                "heritage": summary.get("heritage") or [],
                "has_image": summary.get("has_image"),
                "distance_km": distance,
            })
            entry["_wd_summary"] = summary  # resolved after the OSM lookup below
        # --- OSM identity (already fetched in pass 1)
        result = osm_results[poi["local_poi_id"]]
        best = None
        if result.get("ok"):
            for hit in result["hits"]:
                verdict = match_identity(poi["name"], hit.display_name.split(",")[0], [hit.name])
                if verdict["match"]:
                    best = (hit, verdict)
                    break
        entry["osm"] = {
            "ok": bool(result.get("ok")),
            "n_hits": len(result.get("hits") or []),
            "error": result.get("error"),
            "match": False,
            "rule": "abstain",
            "distance_km": None,
        }
        if best:
            hit, verdict = best
            far = hit.distance_km is not None and hit.distance_km > MAX_KM_REJECT_OSM
            entry["osm"].update({
                "match": not far,
                "rule": "rejected_far" if far else verdict["rule"],
                "display_name": hit.display_name, "osm_type": hit.osm_type, "osm_id": hit.osm_id,
                "tags": hit.tags, "importance": hit.importance, "distance_km": hit.distance_km,
                "confidence_note": ("坐标差 %.1f km > %.0f km，判为同名异地" % (hit.distance_km, MAX_KM_REJECT_OSM))
                if far else (("坐标差 > %.0f km，仅按名称匹配" % MAX_KM_SOFT)
                             if (hit.distance_km or 0) > MAX_KM_SOFT else ""),
            })
            osm_wikidata = (hit.tags or {}).get("wikidata")

        # --- resolve the Wikidata acceptance now that OSM may corroborate the QID
        if qid and "_wd_summary" in entry:
            summary = entry.pop("_wd_summary")
            distance = entry["wikidata"].get("distance_km")
            if osm_wikidata and osm_wikidata == qid:
                accepted, reason = True, "osm_wikidata_bridge"
            elif distance is None:
                # No P625 is not evidence of the same place either. Measured trap:
                # 广州孙中山纪念馆 mapped to the 南京 entity via a zhwiki title with
                # no coordinates. Abstain and report instead of guessing.
                accepted, reason = False, "实体无坐标，无法消歧，需人工或第二来源"
                entry["wikidata"]["needs_geo_check"] = True
            elif distance <= MAX_KM_REJECT_WD:
                accepted, reason = True, ""
            else:
                accepted, reason = False, f"实体在 {distance} km 外，判为同名异地"
            entry["wikidata"].update({
                "accepted": accepted,
                "reject_reason": reason if not accepted else "",
                "verification": "osm_wikidata_tag" if (osm_wikidata and osm_wikidata == qid) else (
                    "coordinate_within_15km" if distance is not None else "name_only_needs_geo_check"),
                "tags": sorted({tag for item in (summary.get("instance_of") or [])
                                for tag in tag_map.get(item, [])}) if accepted else [],
            })
            if accepted:
                entry["wikidata"]["qid_accepted"] = qid
            else:
                entry["wikidata"]["match_rule"] = "title_match_but_far"
        elif qid:
            entry["wikidata"]["accepted"] = False
            entry["wikidata"]["reject_reason"] = "实体摘要缺失"

        # --- if the title lookup missed but OSM carries an explicit wikidata=Q…,
        # use it: an explicit cross-reference from a second source is identity evidence.
        if not entry["wikidata"].get("qid_accepted") and osm_wikidata and osm_wikidata in summaries:
            summary = summaries[osm_wikidata]
            entry["wikidata"].update({
                "qid": osm_wikidata, "qid_accepted": osm_wikidata,
                "match_rule": "from_osm_wikidata_tag", "accepted": True,
                "verification": "osm_wikidata_tag",
                "label_zh": summary.get("label_zh"),
                "description_zh": summary.get("description_zh"),
                "instance_of": summary.get("instance_of") or [],
                "distance_km": None,
                "tags": sorted({tag for item in (summary.get("instance_of") or [])
                                for tag in tag_map.get(item, [])}),
            })
        rows.append(entry)
        status = []
        if entry["wikidata"]["qid"]:
            status.append(f"wd={entry['wikidata']['qid']}")
        if entry["osm"]["match"]:
            status.append(f"osm={entry['osm']['osm_type']}/{entry['osm']['osm_id']}")
        print(f"  {index:2d}. {poi['city']:2s} {poi['name'][:20]:22s} " + (", ".join(status) or "no match"))

    # ------------------------------------------------------------- aggregate
    total = len(rows)
    wd_hits = sum(1 for row in rows if row["wikidata"].get("qid_accepted"))
    osm_hits = sum(1 for row in rows if row["osm"]["match"])
    either = sum(1 for row in rows if row["wikidata"].get("qid_accepted") or row["osm"]["match"])
    with_tags = sum(1 for row in rows
                    if row["wikidata"].get("tags") or (row["osm"].get("tags") or {}))
    near = sum(1 for row in rows
               if row["wikidata"].get("distance_km") is not None and row["wikidata"]["distance_km"] <= MAX_KM_SOFT)
    bridged = sum(1 for row in rows
                  if row["wikidata"].get("verification") == "osm_wikidata_tag")
    needs_geo = sum(1 for row in rows if row["wikidata"].get("needs_geo_check"))
    rejected = sum(1 for row in rows
                   if row["wikidata"].get("match_rule") == "title_match_but_far"
                   or row["osm"].get("rule") == "rejected_far")
    summary = {
        "n": total,
        "wikidata_matched": wd_hits,
        "osm_matched": osm_hits,
        "either_matched": either,
        "matched_rate": round(either / total, 3) if total else 0.0,
        "wikidata_coords_within_3km": near,
        "verified_by_osm_wikidata_tag": bridged,
        "wikidata_needs_geo_check": needs_geo,
        "rejected_far_mismatch": rejected,
        "with_any_tag_evidence": with_tags,
        "by_city": {},
        "by_reason": {},
    }
    for row in rows:
        city = row["city"]
        bucket = summary["by_city"].setdefault(city, {"n": 0, "matched": 0})
        bucket["n"] += 1
        bucket["matched"] += 1 if (row["wikidata"].get("qid_accepted") or row["osm"]["match"]) else 0
    for row in rows:
        reason = str(row["sample_reason"]).split("(")[0]
        bucket = summary["by_reason"].setdefault(reason, {"n": 0, "matched": 0})
        bucket["n"] += 1
        bucket["matched"] += 1 if (row["wikidata"].get("qid_accepted") or row["osm"]["match"]) else 0

    payload = {
        "generated_at": "2026-10-21",
        "sources": {"osm": {"licence": "ODbL-1.0", "provider": "nominatim"},
                    "wikidata": {"licence": "CC0-1.0", "api": "wbgetentities"}},
        "baidu_request_budget": 0,
        "summary": summary,
        "provider_calls": {"osm": osm.client.report(), "wikidata": wikidata.client.report()},
        "rows": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_poi_id", "city", "name", "type", "price", "wikidata_qid",
                         "wd_match_rule", "wd_distance_km", "wd_tags", "osm_matched", "osm_rule",
                         "osm_ref", "osm_distance_km", "osm_tags"])
        for row in rows:
            writer.writerow([
                row["local_poi_id"], row["city"], row["name"], row["type"], row["price"],
                row["wikidata"]["qid"] or "", row["wikidata"]["match_rule"],
                row["wikidata"].get("distance_km", ""), ",".join(row["wikidata"].get("tags") or []),
                row["osm"]["match"], row["osm"]["rule"],
                f'{row["osm"].get("osm_type")}/{row["osm"].get("osm_id")}' if row["osm"]["match"] else "",
                row["osm"].get("distance_km", ""),
                ",".join(f"{k}={v}" for k, v in (row["osm"].get("tags") or {}).items()),
            ])

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {OUT_JSON} and {OUT_CSV}")
    print("provider calls:", json.dumps({k: {"live": v["live"], "cached": v["cached"],
                                             "failed": v["failed"]}
                                         for k, v in payload["provider_calls"].items()},
                                        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
