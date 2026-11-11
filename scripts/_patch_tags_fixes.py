"""Fix three real defects the gates exposed on the first real run:

1. T4 rejected every *attribute* tag ("unknown tag_id") because attribute tags live
   in ATTRIBUTE_TAXONOMY, not TAXONOMY.
2. T3 rejected 4 records whose `excerpt` was synthesised (a Python list repr, a
   `regular_open_hour ...` label) instead of being a verbatim slice of the raw
   response. Excerpts are now anchored against the raw text at extraction time.
3. T6 treated the same tag/value reported by two different platform phrases as a
   duplicate and quarantined it. Two phrases agreeing is *corroboration*; only a
   genuinely different value is a conflict.
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "tags.py"
text = TARGET.read_text(encoding="utf-8")

# ---------------------------------------------------------------- (1) T4
OLD_T4 = '''    spec = TAXONOMY.get(record.tag_id)
    if spec is None:
        put("T4_semantics", False, f"未知 tag_id={record.tag_id}")
    else:'''
NEW_T4 = '''    spec = TAXONOMY.get(record.tag_id)
    if spec is None and record.tag_id in ATTRIBUTE_TAXONOMY:
        # Attribute tags are declarative platform facts; they only need a value.
        put("T4_semantics", record.value not in (None, "", []),
            f"属性标签 {record.tag_id}={record.value!r}")
        spec = {"value_type": "attribute", "polarity": "neutral"}
    elif spec is None:
        put("T4_semantics", False, f"未知 tag_id={record.tag_id}")
    else:'''
assert OLD_T4 in text
text = text.replace(OLD_T4, NEW_T4, 1)

# ---------------------------------------------------------------- (2) T6
OLD_T6 = '''    if seen is not None:
        key = (record.local_poi_id, record.tag_id, str(record.value), record.source_name)
        duplicate = key in seen
        put("T6_duplicate", not duplicate, "同源重复值" if duplicate else "首次出现", hard=False)
        if not duplicate:
            seen[key] = record.confidence
    else:
        put("T6_duplicate", True, "未提供去重集合", hard=False)'''
NEW_T6 = '''    if seen is not None:
        key = (record.local_poi_id, record.tag_id, record.source_name)
        previous = seen.get(key)
        if previous is None:
            seen[key] = {json.dumps(record.value, ensure_ascii=False)}
            put("T6_duplicate", True, "首次出现", hard=False)
        elif json.dumps(record.value, ensure_ascii=False) in previous:
            # Two vocabulary phrases asserting the same value is corroboration.
            record.notes = (record.notes + "；同源多短语印证").strip("；")
            put("T6_duplicate", True, "同一来源多个短语给出一致取值（算印证，不算重复）", hard=False)
        else:
            previous.add(json.dumps(record.value, ensure_ascii=False))
            put("T6_duplicate", False,
                f"同一来源给出互相冲突的取值：{sorted(previous)}", hard=False)
    else:
        put("T6_duplicate", True, "未提供去重集合", hard=False)'''
assert OLD_T6 in text
text = text.replace(OLD_T6, NEW_T6, 1)

# ---------------------------------------------------------------- (3) excerpts
OLD_ATTR = '''def extract_attribute_tags(flat: dict, *, city: str, poi_name: str, raw_text: str,
                           source_name: str = "baidu", source_url: str | None = None,
                           retrieved_at: str | None = None) -> list[TagEvidence]:
    """Attribute tags: the platform *states* these, so confidence is high."""
    at = retrieved_at or _now()
    digest = _sha1(raw_text or "")
    poi_id = f"sandbox:{city}:{poi_name}"
    refs = {"baidu_uid": flat.get("uid")}
    out: list[TagEvidence] = []
'''
NEW_ATTR = '''def _anchor(raw_text: str, *candidates: str) -> str:
    """Return the first candidate that really occurs in the raw response.

    Gate T3 is only meaningful if extraction refuses to invent excerpts, so this
    helper is the single place where an excerpt is chosen. An empty string means
    "could not anchor", and the gate will reject the record.
    """
    for candidate in candidates:
        if candidate and candidate in (raw_text or ""):
            return candidate
    return ""


def extract_attribute_tags(flat: dict, *, city: str, poi_name: str, raw_text: str,
                           source_name: str = "baidu", source_url: str | None = None,
                           retrieved_at: str | None = None) -> list[TagEvidence]:
    """Attribute tags: the platform *states* these, so confidence is high."""
    at = retrieved_at or _now()
    digest = _sha1(raw_text or "")
    poi_id = f"sandbox:{city}:{poi_name}"
    refs = {"baidu_uid": flat.get("uid")}
    out: list[TagEvidence] = []
'''
assert OLD_ATTR in text
text = text.replace(OLD_ATTR, NEW_ATTR, 1)

OLD_BODY = '''    taxonomy = ", ".join((flat.get("tag_path") or []) + (flat.get("classified_tag_path") or [])
                         + (flat.get("label_path") or []))
    add("poi_category", taxonomy, str(flat.get("classified_tag_path") or flat.get("tag_path") or ""))
    if flat.get("scope_grade"):
        add("scenic_grade", flat["scope_grade"], str(flat["scope_grade"]))
    if flat.get("overall_rating") is not None:
        add("platform_rating", flat["overall_rating"],
            f'"overall_rating": "{flat["overall_rating"]}"',
            notes="平台综合评分，不是评论文本统计")
    if flat.get("price") is not None:
        add("price_quote", flat["price"], f'"price": "{flat.get("price_text") or flat["price"]}"')
        add("entry_price", float(flat["price"]), f'"price": "{flat.get("price_text") or flat["price"]}"')
    if flat.get("open_time") and flat.get("close_time"):
        add("opening_hours", f"{flat['open_time']}-{flat['close_time']}", str(flat.get("open_quote") or ""))
    if flat.get("comment_bucket"):
        add("review_volume_bucket", flat["comment_bucket"], f'"comment_num": "{flat.get("comment_num")}"',
            notes="comment_num 在 200 处封顶，只作序数分桶")
    return out'''

NEW_BODY = '''    taxonomy = ", ".join((flat.get("tag_path") or []) + (flat.get("classified_tag_path") or [])
                         + (flat.get("label_path") or []))
    category_raw = str(flat.get("classified_tag_path") or flat.get("tag_path") or "")
    add("poi_category", taxonomy, _anchor(raw_text, category_raw, str(flat.get("scope_type") or "")))
    if flat.get("scope_grade"):
        add("scenic_grade", flat["scope_grade"], _anchor(raw_text, str(flat["scope_grade"])))
    if flat.get("overall_rating") is not None:
        rating = flat["overall_rating"]
        add("platform_rating", rating,
            _anchor(raw_text, f'"overall_rating": "{rating}"', f'"overall_rating":{rating}', str(rating)),
            notes="平台综合评分，不是评论文本统计")
    if flat.get("price") is not None:
        price_text = str(flat.get("price_text") or flat["price"])
        quote = _anchor(raw_text, f'"price": "{price_text}"', f'"price":"{price_text}"', price_text)
        add("price_quote", flat["price"], quote)
        add("entry_price", float(flat["price"]), quote)
    if flat.get("open_time") and flat.get("close_time"):
        window = f"{flat['open_time']}-{flat['close_time']}"
        add("opening_hours", window,
            _anchor(raw_text, f'"shop_hours": "{window}"', window,
                    f'"shop_hours":"{window}"'))
    if flat.get("comment_bucket"):
        raw_comment = str(flat.get("comment_num"))
        add("review_volume_bucket", flat["comment_bucket"],
            _anchor(raw_text, f'"comment_num": "{raw_comment}"', f'"comment_num":"{raw_comment}"',
                    raw_comment),
            notes="comment_num 在 200 处封顶，只作序数分桶")
    return out'''
assert OLD_BODY in text
text = text.replace(OLD_BODY, NEW_BODY, 1)

TARGET.write_text(text, encoding="utf-8")
print("tags.py defects fixed: T4 attribute domain, T6 corroboration, T3 anchored excerpts")
