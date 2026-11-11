"""Patch 3: harden G2 identity with normalisation + alias + similarity."""
from pathlib import Path

DYN = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic"


def patch(path: Path, pairs):
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"pattern missing in {path.name}: {old[:70]!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("patched", path.name)


patch(
    DYN / "sources.py",
    [
        (
            "import json\nimport re\nimport urllib.parse\nimport urllib.request\nfrom pathlib import Path",
            "import json\nimport re\nimport unicodedata\nimport urllib.parse\nimport urllib.request\nfrom difflib import SequenceMatcher\nfrom pathlib import Path",
        ),
        (
            "def cached_fetch(source, name: str, city: str) -> Evidence:",
            '''def normalize_name(value: str) -> str:
    """Normalise a POI name for identity comparison (NFKC, strip spaces/punct)."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[\\s·•,，.。、\\-_/\\\\|()（）\\[\\]【】<>《》:：;；'\\\"“”‘’!！?？]", "", text)
    return text


def name_similarity(request_name: str, returned_name: str, aliases: str | list | None = None) -> tuple[bool, float]:
    """Is the returned POI the same thing the planner asked for?

    Accepts: normalised equality, prefix/containment with a sane length ratio,
    an alias hit, or high string similarity. Rejects fuzzy search noise.
    """
    wanted = normalize_name(request_name)
    got = normalize_name(returned_name)
    if not wanted or not got:
        return False, 0.0
    if wanted == got:
        return True, 1.0
    if got.startswith(wanted) or wanted.startswith(got):
        ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
        if ratio >= 0.6:
            return True, round(ratio, 3)
    if wanted in got or got in wanted:
        ratio = min(len(wanted), len(got)) / max(len(wanted), len(got))
        if ratio >= 0.75:
            return True, round(ratio, 3)
    alias_list: list[str] = []
    if isinstance(aliases, str):
        alias_list = [part for part in re.split(r"[|,，;；]", aliases) if part.strip()]
    elif isinstance(aliases, (list, tuple)):
        alias_list = [str(part) for part in aliases]
    for alias in alias_list:
        normalized_alias = normalize_name(alias)
        if normalized_alias and (normalized_alias == wanted or normalized_alias.startswith(wanted)):
            return True, 0.9
    similarity = SequenceMatcher(None, wanted, got).ratio()
    return (similarity >= 0.7), round(similarity, 3)


def cached_fetch(source, name: str, city: str) -> Evidence:''',
        ),
        (
            '''            pois = data.get("pois") or []
            chosen = None
            name_match = False
            for poi in pois:
                poi_name = str(poi.get("name", ""))
                if poi_name == name or poi_name.startswith(name):
                    chosen = poi
                    name_match = True
                    break
            chosen = chosen or (pois[0] if pois else None)''',
            '''            pois = data.get("pois") or []
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
            if not name_match and chosen is not None:
                _, best_similarity = name_similarity(
                    name, str(chosen.get("name", "")), (chosen.get("business") or {}).get("alias")
                )''',
        ),
        (
            '                "name_match": name_match,',
            '                "name_match": name_match,\n                "name_similarity": best_similarity,',
        ),
    ],
)

patch(
    DYN / "quality.py",
    [
        (
            '            returned = amap_evidence.structured.get("name")\n            identity_ok = False\n            gate("G2_identity", False, f"高德返回的是另一个 POI：{returned!r}，与请求 {request.name!r} 不符")',
            '            returned = amap_evidence.structured.get("name")\n'
            '            similarity = amap_evidence.structured.get("name_similarity")\n'
            '            identity_ok = False\n'
            '            gate(\n'
            '                "G2_identity",\n'
            '                False,\n'
            '                f"高德返回的是另一个 POI：{returned!r}（相似度 {similarity}），与请求 {request.name!r} 不符",\n'
            '            )',
        ),
    ],
)
print("done")
