"""Rebuild Xi'an's position index from the entity tables.

Why: `poi/xian/poi.json` had 1,394 entries while the planning tables hold
591 attractions + 706 hotels + 486 restaurants. `Poi.search()` is an exact-name
dict lookup, so 523/591 attractions, 691/706 hotels and 463/486 restaurants
could not be located at all.

Strategy
 1. keep every existing POI entry (arbitrary points the agent may still ask for)
 2. add every entity's exact `name`; the entity table coordinate wins on a
    conflict because plans place that exact name at that coordinate
 3. add a Chinese-only alias (English suffix / bracketed branch removed) only
    when it maps to one place; branch names shared by several hotels are
    skipped instead of silently pointing at the wrong one
 4. add metro stations from `transportation/subways.json`
 5. add short station aliases (`西安北` -> `西安北站`) and airport short names

Output is deterministic: sorted by name, backed up first, plus a manifest with
replaced/ambiguous/conflict counts and a 100% coverage check.
"""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "data/xian11_merged_sandbox"
POI_PATH = SANDBOX / "poi/xian/poi.json"
MANIFEST = SANDBOX / "poi/xian/poi_index_manifest.json"
BACKUP = SANDBOX / "poi/xian/poi.json.bak_20261111"

PUNCT = re.compile(r"[\s\u3000·•・\-—–_()（）\[\]【】{}<>《》\"'“”‘’,，.。;；:：!！?？/\\|]+")


def norm(s: str) -> str:
    return PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")).strip().lower())


def core(s: str) -> str:
    """Chinese-only core: drop a trailing latin alias and bracketed branch text."""
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    t = re.sub(r"[（(].*?[)）]", "", t)
    t = re.split(r"\s+[A-Za-z]", t, maxsplit=1)[0]
    return t.strip()


def hav(a, b, c, d):
    R = 6371000
    p1, p2 = math.radians(a), math.radians(c)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    if not POI_PATH.exists():
        raise SystemExit(f"missing {POI_PATH}")
    # idempotent: always rebuild from the untouched original, not from a
    # previous rebuild
    base_path = BACKUP if BACKUP.exists() else POI_PATH
    original = json.loads(base_path.read_text(encoding="utf-8"))
    index: dict[str, tuple[float, float]] = {}
    origin: dict[str, str] = {}
    replaced, conflicts = [], []
    for item in original:
        name = str(item.get("name") or "").strip()
        pos = item.get("position") or []
        if name and len(pos) == 2:
            index[name] = (float(pos[0]), float(pos[1]))
            origin[name] = "existing"

    def put_exact(name: str, lat: float, lon: float, source: str) -> None:
        name = str(name or "").strip()
        if not name:
            return
        if name in index:
            d = hav(index[name][0], index[name][1], lat, lon)
            if d > 50:
                replaced.append({"name": name, "old_m": round(d),
                                 "old_source": origin[name], "new_source": source})
                index[name] = (lat, lon)
                origin[name] = source
            return
        index[name] = (lat, lon)
        origin[name] = source

    added = Counter()
    alias_candidates: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    entity_rows = (("attraction", "attractions", "attractions.csv"),
                   ("accommodation", "accommodations", "accommodations.csv"),
                   ("restaurant", "restaurants", "restaurants_xian.csv"))
    for kind, sub, filename in entity_rows:
        for r in rows(SANDBOX / sub / "xian" / filename):
            lat, lon = float(r["lat"]), float(r["lon"])
            if r["name"] not in index:
                added[kind] += 1
            put_exact(r["name"], lat, lon, kind)
            alias = core(r["name"])
            if alias and alias != r["name"]:
                alias_candidates[alias].append((lat, lon, kind))

    # only add an alias when all its owners point at (roughly) the same place
    ambiguous = []
    for alias, owners in alias_candidates.items():
        if alias in index:
            continue
        spread = max((hav(a[0], a[1], b[0], b[1]) for a in owners for b in owners), default=0)
        if spread > 200:
            ambiguous.append({"alias": alias, "owners": len(owners), "spread_m": round(spread)})
            continue
        index[alias] = (owners[0][0], owners[0][1])
        origin[alias] = "alias"
        added["alias"] += 1

    # metro stations
    subway = json.loads((SANDBOX / "transportation/subways.json").read_text(encoding="utf-8"))
    station_count = 0
    for line in subway.get("xian", []):
        for st in line.get("stations", []):
            lat_s, lon_s = str(st.get("position", "")).split(",")
            name = st.get("name")
            if name and name not in index:
                index[name] = (float(lat_s), float(lon_s))
                origin[name] = "subway"
                station_count += 1

    # short station / airport aliases derived from entries that already exist
    short = 0
    for name in list(index):
        if name.endswith("站") and len(name) > 2 and name[:-1] not in index:
            index[name[:-1]] = index[name]
            origin[name[:-1]] = "station:short"
            short += 1
    if "西安咸阳国际机场" in index:
        for alias in ("咸阳机场", "西安咸阳机场"):
            if alias not in index:
                index[alias] = index["西安咸阳国际机场"]
                origin[alias] = "airport:alias"
                short += 1

    payload = [{"name": name, "position": [round(index[name][0], 8), round(index[name][1], 8)]}
               for name in sorted(index)]
    if not BACKUP.exists():
        shutil.copy2(POI_PATH, BACKUP)
    POI_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")

    coverage = {}
    for kind, sub, filename in entity_rows:
        names = [r["name"] for r in rows(SANDBOX / sub / "xian" / filename)]
        hit = sum(1 for n in names if n in index)
        coverage[kind] = {"total": len(names), "hit": hit, "missing": len(names) - hit}

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "poi_entries_before": len(original), "poi_entries_after": len(index),
        "added": dict(added), "station_entries_added": station_count,
        "station_short_aliases": short,
        "coordinates_replaced_by_entity": len(replaced),
        "replaced_sample": replaced[:20],
        "ambiguous_aliases_skipped": len(ambiguous),
        "ambiguous_sample": ambiguous[:20],
        "coverage": coverage,
        "sources": ["attractions", "accommodations", "restaurants",
                    "transportation/subways.json", "existing poi.json"],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"before": len(original), "after": len(index), "added": dict(added),
                      "coverage": coverage, "replaced": len(replaced),
                      "ambiguous_skipped": len(ambiguous)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
