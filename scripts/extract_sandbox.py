"""Extract the official ChinaTravel sandbox archives into the layout the code expects.

The published zips were produced on a Chinese Windows machine, so entry names are
mojibake when read naively (the byte string is GBK but zipfile decodes CP437).
We repair the names, then write `chinatravel/environment/database/` (zh) and
`chinatravel/environment/database_en/` (en).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "sandbox"
TARGET = ROOT / "ChinaTravel" / "chinatravel" / "environment"


def repair_name(info: zipfile.ZipInfo) -> str:
    raw = info.orig_filename
    if info.flag_bits & 0x800:  # already UTF-8 flagged
        return raw
    for encoding in ("cp437", "gbk"):
        try:
            candidate = raw.encode(encoding) if encoding == "cp437" else raw
            return candidate.decode("gbk") if encoding == "cp437" else candidate
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return raw


def decode_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def extract(zip_path: Path, dest: Path) -> int:
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = decode_name(info).replace("\\", "/")
            out = dest / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(info))
            count += 1
    return count


def main() -> int:
    jobs = [
        (RAW / "ChinaTravel_sandbox_zh.zip", TARGET),
        (RAW / "ChinaTravel_sandbox_en.zip", TARGET),
    ]
    for zip_path, dest in jobs:
        if not zip_path.exists():
            print(f"missing {zip_path}")
            return 1
        n = extract(zip_path, dest)
        print(f"{zip_path.name}: {n} files -> {dest}")
    for name in ("database", "database_en"):
        root = TARGET / name
        if root.exists():
            cities = sorted(p.name for p in root.iterdir() if p.is_dir())
            tables = sorted(p.name for p in (root / cities[0]).iterdir()) if cities else []
            print(f"  {name}: {len(cities)} city dirs, first={cities[0] if cities else None}, tables={tables}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
