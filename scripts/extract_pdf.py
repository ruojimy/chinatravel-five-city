"""Extract text from a PDF into a UTF-8 text file (one section per page)."""
import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    reader = PdfReader(str(src))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - report and keep going
            text = f"<extract failed: {exc}>"
        parts.append(f"\n\n===== Page {i} =====\n\n{text}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("".join(parts), encoding="utf-8")
    print(f"pages={len(reader.pages)} chars={sum(len(p) for p in parts)} -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
