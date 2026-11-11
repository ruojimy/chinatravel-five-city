"""Download the two CC BY 4.0 review datasets and inspect their real structure.

Licence: both are CC BY 4.0 (machine-readable via DataCite / Zenodo metadata, see
results/p1/new_sources.json), so downloading and deriving statistics is permitted
with attribution. Files are small (1.6 MB xlsx + a 4TU xlsx).

Run with the bundled interpreter (needs openpyxl):
  python.exe reproduction/scripts/p1_fetch_licensed_reviews.py
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "visitor_reviews_raw"
OUT = ROOT / "results" / "p1" / "licensed_reviews_structure.json"
UA = "ShortTripAssistant/1.0 (course project; CC BY 4.0 dataset use)"

ZENODO_CONTENT = ("https://zenodo.org/api/records/21633654/files/"
                  "Zhangjiajie_UGC_LDA_DEMATEL_Data-20260227(1).xlsx/content")
FOURTU_LANDING = "https://data.4tu.nl/articles/_/22122224/1"


def download(url: str, target: Path, *, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {"ok": True, "bytes": len(raw), "path": str(target)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}", "url": url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "url": url}


def inspect_xlsx(path: Path) -> dict:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheets = {}
    for name in workbook.sheetnames:
        sheet = workbook[name]
        rows = []
        for index, row in enumerate(sheet.iter_rows(values_only=True)):
            if index >= 4:
                break
            rows.append(["" if cell is None else str(cell)[:120] for cell in row][:14])
        sheets[name] = {"n_cols": sheet.max_column, "n_rows": sheet.max_row, "head": rows}
    workbook.close()
    return sheets


def main() -> int:
    report: dict = {"generated_at": "2026-10-22", "licence": "CC BY 4.0", "datasets": {}}

    # ---- Zenodo (Zhangjiajie UGC reviews)
    target = RAW / "zhangjiajie_ugc.xlsx"
    result = download(ZENODO_CONTENT, target)
    entry = {"source": "zenodo:10.5281/zenodo.21633654", "download": result}
    if result.get("ok"):
        entry["sheets"] = inspect_xlsx(target)
    report["datasets"]["zenodo_zhangjiajie"] = entry
    print("zenodo:", "ok" if result.get("ok") else result.get("error"),
          "| sheets:", list(entry.get("sheets", {})))

    # ---- 4TU (TripAdvisor reviews of 10 Chinese attractions)
    landing = download(FOURTU_LANDING, RAW / "4tu_landing.html")
    links: list[str] = []
    if landing.get("ok"):
        html = (RAW / "4tu_landing.html").read_text(encoding="utf-8", errors="replace")
        links = sorted(set(re.findall(r'https?://[^"\'<>\s]+\.xlsx[^"\'<>\s]*', html)))
        entry4 = {"source": "4tu:10.4121/22122224.v1", "landing": landing,
                  "xlsx_links": links[:6], "datasets": {}}
        for url in links[:2]:
            name = re.sub(r"[^0-9A-Za-z._-]+", "_", url.rsplit("/", 1)[-1])[:80] or "file.xlsx"
            got = download(url, RAW / f"4tu_{name}")
            if got.get("ok"):
                try:
                    entry4["datasets"][name] = {"download": got, "sheets": inspect_xlsx(RAW / f"4tu_{name}")}
                except Exception as exc:  # noqa: BLE001
                    entry4["datasets"][name] = {"download": got, "error": f"{type(exc).__name__}: {exc}"}
        report["datasets"]["4tu"] = entry4
        print("4tu links:", links[:3], "| inspected:", list(entry4["datasets"]))
    else:
        report["datasets"]["4tu"] = {"source": "4tu:10.4121/22122224.v1", "landing": landing}
        print("4tu landing failed:", landing.get("error"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)

    for key, entry in report["datasets"].items():
        print(f"\n=== {key}")
        for name, sheet in (entry.get("sheets") or {}).items():
            print(f"  sheet {name}: {sheet['n_rows']} rows x {sheet['n_cols']} cols")
            for row in sheet["head"][:3]:
                print("    ", row)
        for name, item in (entry.get("datasets") or {}).items():
            print(f"  file {name}: {list(item.get('sheets', {}))}")
            for sheet_name, sheet in (item.get("sheets") or {}).items():
                print(f"    sheet {sheet_name}: {sheet['n_rows']}x{sheet['n_cols']}")
                for row in sheet["head"][:3]:
                    print("      ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
