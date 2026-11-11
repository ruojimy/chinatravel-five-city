"""Evidence -> sandbox record extraction.

Two extractors, merged:

* deterministic (`RegexExtractor`): coordinates from Wikidata/Wikipedia, opening
  hours and prices from the article text with regexes;
* LLM (`DeepSeekExtractor`): fills what the regexes miss, and must return a
  verbatim quote for every field it claims (checked by the gate, so a
  hallucinated value cannot pass).

The merge prefers the deterministic path for numbers and only uses the LLM where
deterministic extraction produced nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .records import CandidateRecord, DataRequest, Evidence, FieldValue
from .sources import regex_hints

SECRETS = Path(__file__).resolve().parents[3] / ".secrets"

TYPE_KEYWORDS = [
    ("博物馆", "博物馆/纪念馆"),
    ("纪念馆", "博物馆/纪念馆"),
    ("美术馆", "美术馆/艺术馆"),
    ("艺术馆", "美术馆/艺术馆"),
    ("图书馆", "其它"),
    ("公园", "公园"),
    ("寺", "历史古迹"),
    ("塔", "人文景观"),
    ("古城", "历史古迹"),
    ("步行街", "商业街区"),
]

EXTRACT_PROMPT = """你是旅行数据录入员。请从给定的外部资料中，抽取“{name}”（{city}，类型：{kind}）的结构化信息。

只输出 JSON，不要解释。字段：
{{
  "name": "与请求一致的名称",
  "type": "场馆类型（若为景点，尽量从这些里选：博物馆/纪念馆、美术馆/艺术馆、公园、历史古迹、人文景观、商业街区、自然风光、其它）",
  "lat": 数字或 null,
  "lon": 数字或 null,
  "opentime": "HH:MM" 或 null,
  "endtime": "HH:MM" 或 null,
  "price": 数字（人民币，免费填 0）或 null,
  "recommendmintime": 建议游览小时数（数字）或 null,
  "quotes": {{"字段名": "资料原文中逐字出现的片段"}},
  "notes": "不确定之处"
}}

硬性要求：
1. 每个填了值的字段都必须在 quotes 里给出一段**原文逐字**片段（不要改写、不要翻译、不要加省略号）；
2. 资料里没有的信息一律填 null，不要推测；
3. 坐标只接受资料里明确写出的数值，不要凭记忆写。

--- 外部资料开始 ---
{evidence}
--- 外部资料结束 ---
"""


def _norm_time(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*(\d{1,2})[:：](\d{2})\s*$", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return f"{hour:02d}:{minute:02d}"


class RegexExtractor:
    """Deterministic extraction used as the primary path for numeric fields."""

    name = "regex+api"

    def extract(self, request: DataRequest, evidence: list[Evidence]) -> CandidateRecord:
        fields: dict[str, FieldValue] = {}

        # identity fields come from the request; the gate re-verifies them
        fields["name"] = FieldValue(request.name, request.name, "planner")
        fields["city"] = FieldValue(request.city, request.city, "planner")

        # coordinates: Wikidata wins, then Wikipedia geosearch, then OSM
        for item in evidence:
            if item.source == "wikidata" and item.structured.get("coordinates"):
                coords = item.structured["coordinates"]
                fields["lat"] = FieldValue(coords.get("lat"), item.text[:80], item.source)
                fields["lon"] = FieldValue(coords.get("lon"), item.text[:80], item.source)
                break
        if "lat" not in fields:
            for item in evidence:
                if item.source == "wikipedia_zh" and item.structured.get("coordinates"):
                    coords = item.structured["coordinates"][0]
                    fields["lat"] = FieldValue(coords.get("lat"), json.dumps(item.structured, ensure_ascii=False)[:80], item.source)
                    fields["lon"] = FieldValue(coords.get("lon"), json.dumps(item.structured, ensure_ascii=False)[:80], item.source)
                    break

        # type: keyword over the article title/lead
        article = next((item for item in evidence if item.source == "wikipedia_zh" and item.ok), None)
        if article is not None:
            head = article.text[:400] + article.title
            for keyword, label in TYPE_KEYWORDS:
                if keyword in head:
                    fields["type"] = FieldValue(label, keyword, article.source)
                    break

        # opening hours / price: regex over the article
        hints = regex_hints(article.text if article else "")
        if hints["open_windows"]:
            window = hints["open_windows"][0]
            fields["opentime"] = FieldValue(_norm_time(window["opentime"]), window["quote"], article.source if article else "")
            fields["endtime"] = FieldValue(_norm_time(window["endtime"]), window["quote"], article.source if article else "")
        if hints["prices"]:
            fields["price"] = FieldValue(float(hints["prices"][0]["price"]), hints["prices"][0]["quote"], article.source if article else "")
        elif hints["free"]:
            fields["price"] = FieldValue(0.0, "免费", article.source if article else "")

        return CandidateRecord(request=request, fields=fields, extractor=self.name, evidence=evidence)


class DeepSeekExtractor:
    name = "deepseek"

    def __init__(self, model: str = "deepseek-v4-pro", timeout: int = 120):
        self.model = model
        self.timeout = timeout
        self.token = (SECRETS / "deepseek.key").read_text(encoding="ascii").strip()

    def _call(self, prompt: str) -> dict:
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 2500,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        content = data["choices"][0]["message"].get("content") or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.S)
            return json.loads(match.group(0)) if match else {}

    def extract(self, request: DataRequest, evidence: list[Evidence]) -> CandidateRecord:
        blocks = []
        for item in evidence:
            if not item.ok or not item.text:
                continue
            kind = "结构化记录" if item.source == "wikidata" else "网页正文"
            blocks.append(f"[{item.source} | {item.url} | {kind}]\n{item.text[:6000]}")
        prompt = EXTRACT_PROMPT.format(
            name=request.name,
            city=request.city,
            kind=request.kind,
            evidence="\n\n".join(blocks)[:14000] or "（无可用资料）",
        )
        try:
            raw = self._call(prompt)
        except Exception as exc:  # noqa: BLE001
            return CandidateRecord(request=request, fields={}, extractor=self.name, evidence=evidence)
        quotes = raw.get("quotes") or {}
        by_source = {item.source: item for item in evidence if item.ok}
        priority = ["wikipedia_zh", "deepseek_chat", "wikidata", "openstreetmap"]
        fields: dict[str, FieldValue] = {}
        for key in ("name", "type", "lat", "lon", "opentime", "endtime", "price", "recommendmintime"):
            value = raw.get(key)
            if value is None or value == "":
                continue
            if key in ("opentime", "endtime"):
                value = _norm_time(str(value))
                if value is None:
                    continue
            if key in ("lat", "lon", "price", "recommendmintime"):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            quote = str(quotes.get(key, ""))
            source = ""
            for candidate in priority:
                item = by_source.get(candidate)
                if item is not None and quote and quote in item.text:
                    source = candidate
                    break
            fields[key] = FieldValue(value, quote, source or "deepseek_chat")
        return CandidateRecord(request=request, fields=fields, extractor=self.name, evidence=evidence)


AMAP_TYPE_MAP = [
    ("博物馆", "博物馆/纪念馆"),
    ("展览馆", "博物馆/纪念馆"),
    ("纪念馆", "博物馆/纪念馆"),
    ("美术馆", "美术馆/艺术馆"),
    ("科技馆", "博物馆/纪念馆"),
    ("公园", "公园"),
    ("植物园", "公园"),
    ("寺庙", "历史古迹"),
    ("教堂", "历史古迹"),
    ("古迹", "历史古迹"),
    ("风景名胜", "人文景观"),
    ("旅游景点", "人文景观"),
    ("特色街区", "商业街区"),
    ("步行街", "商业街区"),
]


def parse_opening(text: str) -> tuple[str | None, str | None, str]:
    """Pick the dominant HH:MM-HH:MM pair out of a free-form opening-hours blob.

    Amap's `opentime_week` enumerates holiday exceptions, e.g. "周二至周日
    09:00-17:30（16:00停止售票）…7月27日-8月31日 09:00-18:00". The modal pair is the
    regular schedule, so we take the most frequent one and keep its quote.
    """
    if not text:
        return None, None, ""
    pattern = r"(\d{1,2})[:：](\d{2})\s*[-—–~至到]\s*(\d{1,2})[:：](\d{2})"
    pairs = re.findall(pattern, text)
    if not pairs:
        return None, None, ""
    counts: dict[tuple[str, str], int] = {}
    for h1, m1, h2, m2 in pairs:
        key = (f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}")
        counts[key] = counts.get(key, 0) + 1
    (open_t, close_t), _ = max(counts.items(), key=lambda item: item[1])
    quote = ""
    for match in re.finditer(pattern, text):
        if open_t in match.group(0).replace("：", ":"):
            quote = match.group(0)
            break
    return open_t, close_t, quote or f"{open_t}-{close_t}"


class AmapExtractor:
    """Deterministic extraction from the Amap record (no LLM involved)."""

    name = "amap"

    def extract(self, request: DataRequest, evidence: list[Evidence]) -> CandidateRecord:
        item = next((e for e in evidence if e.source == "amap" and e.ok and e.structured.get("lat")), None)
        fields: dict[str, FieldValue] = {}
        if item is not None:
            data = item.structured
            fields["name"] = FieldValue(request.name, request.name, "planner")
            fields["city"] = FieldValue(request.city, request.city, "planner")
            fields["lat"] = FieldValue(float(data["lat"]), data["location"], item.source)
            fields["lon"] = FieldValue(float(data["lon"]), data["location"], item.source)
            type_path = data.get("type_path") or []
            for keyword, label in AMAP_TYPE_MAP:
                if any(keyword in part for part in type_path):
                    fields["type"] = FieldValue(label, keyword, item.source)
                    break
            open_t, close_t, quote = parse_opening(data.get("opentime_text") or "")
            if open_t and close_t:
                fields["opentime"] = FieldValue(open_t, quote, item.source)
                fields["endtime"] = FieldValue(close_t, quote, item.source)
            cost = data.get("cost")
            if isinstance(cost, (int, float)) or (isinstance(cost, str) and cost.replace(".", "", 1).isdigit()):
                fields["price"] = FieldValue(float(cost), str(cost), item.source)
        return CandidateRecord(request=request, fields=fields, extractor=self.name, evidence=evidence)


class HybridExtractor:
    """Amap first, then Wikidata/Wikipedia regex, then the LLM as a gap filler."""

    name = "hybrid"

    def __init__(self, llm: DeepSeekExtractor | None = None, use_llm: bool = True):
        self.amap = AmapExtractor()
        self.regex = RegexExtractor()
        self.llm = llm if llm is not None else (DeepSeekExtractor() if use_llm else None)

    def extract(self, request: DataRequest, evidence: list[Evidence]) -> CandidateRecord:
        merged: dict[str, FieldValue] = {}
        used: list[str] = []
        for extractor in (self.amap, self.regex):
            record = extractor.extract(request, evidence)
            if record.fields:
                used.append(extractor.name)
            for key, value in record.fields.items():
                if key not in merged and value.value is not None:
                    merged[key] = value
        if self.llm is not None:
            llm_record = self.llm.extract(request, evidence)
            if llm_record.fields:
                used.append("llm")
            for key, value in llm_record.fields.items():
                if key not in merged and value.value is not None:
                    merged[key] = value
        return CandidateRecord(
            request=request,
            fields=merged,
            extractor="+".join(used) or "none",
            evidence=evidence,
        )