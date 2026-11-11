"""P2 step 1: build a candidate-evidence table for manual POI adjudication.

The point is to break the circularity that P0 flagged: the matcher must not be
judged by its own score. So this script prints, for each of the 50 sample POIs, the
*evidence* a person would use — the POI's own name/city, the current match and its
distance, the Wikidata entity label/description, and the OSM display name — with an
empty `gold` column for adjudication.

It deliberately does **not** print the matcher's score, so the adjudication cannot be
anchored on it.

Outputs
  datasets/poi_matching_gold/candidates.csv
  results/p6_matching/candidate_table.txt   (compact, for reading)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import NominatimOsmSource, WikidataSource  # noqa: E402

MAPPING = ROOT / "results" / "p1" / "poi_mapping.json"
OUT_CSV = ROOT / "datasets" / "poi_matching_gold" / "candidates.csv"
OUT_TXT = ROOT / "results" / "p6_matching" / "candidate_table.txt"


def main() -> int:
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    rows = mapping.get("rows") or []
    osm = NominatimOsmSource()
    wikidata = WikidataSource()

    accepted = [row["wikidata"]["qid_accepted"] for row in rows
                if (row.get("wikidata") or {}).get("qid_accepted")]
    entities = wikidata.entities_by_ids(accepted)
    labels = {}
    type_qids = []
    for entity in entities.values():
        for statement in (entity.get("claims") or {}).get("P31", []):
            value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                type_qids.append(value["id"])
    labels = wikidata.type_labels(type_qids)

    table: list[dict] = []
    for row in rows:
        wd = row.get("wikidata") or {}
        osm_info = row.get("osm") or {}
        entity = entities.get(wd.get("qid_accepted") or "") or {}
        wd_label = ((entity.get("labels") or {}).get("zh") or {}).get("value")
        wd_label_en = ((entity.get("labels") or {}).get("en") or {}).get("value")
        wd_desc = ((entity.get("descriptions") or {}).get("zh") or {}).get("value")
        p31 = []
        for statement in (entity.get("claims") or {}).get("P31", [])[:3]:
            value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            qid = value.get("id") if isinstance(value, dict) else None
            if qid:
                p31.append((labels.get(qid) or {}).get("zh") or qid)

        # candidate alternatives for the same POI (so the reviewer can say "the right
        # one is candidate 2, not candidate 1")
        result = osm.lookup(row["name"], row["city"], anchor_gcj=tuple(row["sandbox_xy"]))
        candidates = []
        for hit in (result.get("hits") or [])[:3]:
            candidates.append({
                "display_name": hit.display_name[:70],
                "distance_km": hit.distance_km,
                "tags": {k: v for k, v in (hit.tags or {}).items()
                         if k in ("tourism", "historic", "leisure", "amenity", "wikidata")},
            })

        table.append({
            "poi_id": row["local_poi_id"],
            "name": row["name"],
            "city": row["city"],
            "sandbox_type": row["type"],
            "wd_qid": wd.get("qid_accepted") or "",
            "wd_label": wd_label or "",
            "wd_label_en": wd_label_en or "",
            "wd_desc": (wd_desc or "")[:40],
            "wd_p31": " / ".join(p31),
            "osm_matched": "Y" if osm_info.get("match") else "N",
            "osm_name": (osm_info.get("display_name") or "")[:60],
            "osm_distance_km": osm_info.get("distance_km"),
            "osm_candidates": " || ".join(
                f'{c["display_name"]}@{c["distance_km"]}km'
                for c in candidates),
            "gold": "",
            "reviewer": "",
            "reason": "",
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0].keys()))
        writer.writeheader()
        writer.writerows(table)

    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# POI 候选证据表（用于人工裁决；不含匹配分数）", ""]
    for index, item in enumerate(table, start=1):
        lines.append(f'{index:2d}. [{item["city"]}] {item["name"]}  ({item["sandbox_type"]})')
        lines.append(f'     Wikidata: {item["wd_qid"]} {item["wd_label"]} / {item["wd_label_en"]}'
                     f' | {item["wd_desc"]} | P31={item["wd_p31"]}')
        lines.append(f'     OSM: matched={item["osm_matched"]} {item["osm_name"]}'
                     f' @{item["osm_distance_km"]}km')
        if item["osm_candidates"]:
            lines.append(f'     候选: {item["osm_candidates"]}')
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {OUT_CSV} ({len(table)} rows) and {OUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
