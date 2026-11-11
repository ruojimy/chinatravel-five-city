import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = [
    "data/catalog_v1_1_20261022/catalog.sqlite3",
    "data/tag_store_v2.sqlite",
    "results/weekly20_20261103/batch06/snapshot_v4/catalog.sqlite3",
    "results/xian_claude_20261106_012334/snapshot_v3/catalog.sqlite3",
]
for rel in PATHS:
    p = ROOT / rel
    print("=" * 24, rel, "exists", p.exists(), p.stat().st_size if p.exists() else "")
    if not p.exists():
        continue
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
    print("tables", tables)
    for t in tables:
        try:
            n = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        except Exception as exc:
            n = str(exc)
        print("  ", t, n)
    # city distribution if a city column exists
    for t in tables:
        cols = [r[1] for r in cur.execute(f'pragma table_info("{t}")')]
        if "city" in cols:
            try:
                rows = cur.execute(f'select city, count(*) from "{t}" group by city order by 2 desc').fetchall()
                print("  cities", t, rows[:15])
            except Exception as exc:
                print("  city fail", t, exc)
    con.close()
