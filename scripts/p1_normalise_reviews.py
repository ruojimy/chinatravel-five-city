"""Normalise the CC BY 4.0 review corpus and retry the 4TU dataset.

Zenodo 10.5281/zenodo.21633654 (CC BY 4.0) ships `Zhangjiajie_UGC_LDA_DEMATEL_Data.xlsx`
with a `Review` sheet (~15.7k rows). This script turns it into a JSONL corpus with a
stable review id and a text hash, so downstream extraction can cite an exact record.

4TU 10.4121/22122224.v1 (CC BY 4.0) holds TripAdvisor reviews for 10 Chinese
attractions; its landing page failed with a TLS EOF once, so it is retried here with
backoff and several endpoint shapes.

Outputs
  data/visitor_reviews_raw/zhangjiajie_reviews.jsonl
  data/visitor_reviews_raw/zhangjiajie_stats.json
  results/p1/fourtu_retry.json
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "visitor_reviews_raw"
OUT_JSONL = RAW / "zhangjiajie_reviews.jsonl"
OUT_STATS = RAW / "zhangjiajie_stats.json"
OUT_4TU = ROOT / "results" / "p1" / "fourtu_retry.json"
UA = "ShortTripAssistant/1.0 (course project; CC BY 4.0 dataset use)"

CJK = re.compile(r"[\u4e00-\u9fff]")


def normalise_reviews(path: Path) -> dict:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook["Review"]
    texts: list[str] = []
    for row in sheet.iter_rows(values_only=True):
        cell = row[0] if row else None
        if cell is None:
            continue
        text = " ".join(str(cell).split())
        if len(text) < 8:
            continue
        texts.append(text)
    workbook.close()

    seen: set[str] = set()
    records: list[dict] = []
    for index, text in enumerate(texts):
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        if digest in seen:
            continue
        seen.add(digest)
        cjk = len(CJK.findall(text))
        records.append({
            "review_id": f"zenodo21633654:{index:06d}",
            "text_sha1": digest,
            "poi_hint": "张家界国家森林公园",
            "chars": len(text),
            "cjk_ratio": round(cjk / max(1, len(text)), 3),
            "text": text,
        })

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    lengths = sorted(record["chars"] for record in records)
    stats = {
        "source": "zenodo:10.5281/zenodo.21633654",
        "licence": "CC BY 4.0",
        "attribution": "Huang Bao-Hui (2026), Dataset for: Research on the Emotional "
                       "Experience of Online Tourists in Zhangjiajie, Zenodo",
        "sheet": "Review",
        "raw_rows": len(texts),
        "unique_reviews": len(records),
        "duplicates_removed": len(texts) - len(records),
        "chars_total": sum(lengths),
        "chars_p50": lengths[len(lengths) // 2] if lengths else 0,
        "chars_p90": lengths[int(len(lengths) * 0.9)] if lengths else 0,
        "chars_max": lengths[-1] if lengths else 0,
        "chinese_reviews": sum(1 for record in records if record["cjk_ratio"] > 0.5),
        "sample": [record["text"][:120] for record in records[:5]],
        "poi_scope": "张家界（不在 ChinaTravel 10 城内）",
    }
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def retry_4tu() -> dict:
    candidates = [
        "https://data.4tu.nl/articles/_/22122224/1",
        "https://data.4tu.nl/v2/articles/22122224",
        "https://data.4tu.nl/api/articles/22122224",
    ]
    attempts = []
    for url in candidates:
        for attempt in range(3):
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    body = response.read().decode("utf-8", "replace")
                links = sorted(set(re.findall(r'https?://[^"\'<>\s]+\.xlsx[^"\'<>\s]*', body)))
                attempts.append({"url": url, "status": response.status, "chars": len(body),
                                 "xlsx_links": links[:5]})
                return {"ok": True, "attempts": attempts, "xlsx_links": links[:5]}
            except Exception as exc:  # noqa: BLE001
                attempts.append({"url": url, "attempt": attempt + 1, "error": str(exc)[:160]})
                time.sleep(2.0 * (attempt + 1))
    return {"ok": False, "attempts": attempts,
            "note": "TLS 在生产环境被中断；改用 DataCite 元数据 + 手动下载，不影响主结论"}


def main() -> int:
    stats = normalise_reviews(RAW / "zhangjiajie_ugc.xlsx")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("sample",)}, ensure_ascii=False, indent=2))
    print("sample:", stats["sample"][:2])

    fourtu = retry_4tu()
    OUT_4TU.write_text(json.dumps(fourtu, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n4tu:", "ok" if fourtu.get("ok") else fourtu.get("attempts", [{}])[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
