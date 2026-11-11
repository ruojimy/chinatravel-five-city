import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# five-city v4
for p in [
    ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3",
    ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite",
]:
    print("v4", p, p.exists(), p.stat().st_size if p.exists() else "")
    if p.exists():
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        cur = con.cursor()
        print(" tables", [r[0] for r in cur.execute("select name from sqlite_master where type='table'")])
        for t in [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]:
            print("  ", t, cur.execute(f'select count(*) from "{t}"').fetchone()[0])
        con.close()

# weekly20 tree
w = ROOT / "results/weekly20_20261103"
print("\nweekly20 dirs")
for d in sorted(w.iterdir()):
    print(" ", d.name, d.is_dir())
for batch in sorted(w.glob("batch*")):
    snaps = sorted(batch.glob("snapshot*"))
    print(batch.name, [s.name for s in snaps])

# metadata of weekly20 snapshot_v4
for p in [ROOT / "results/weekly20_20261103/batch06/snapshot_v4/catalog.sqlite3",
          ROOT / "results/xian_claude_20261106_012334/snapshot_v3/catalog.sqlite3"]:
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    print("\nmetadata", p.name)
    for row in cur.execute("select * from metadata"):
        print(" ", str(row)[:600])
    con.close()

# tag store metadata
p = ROOT / "data/tag_store_v2.sqlite"
con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
cur = con.cursor()
print("\ntag_store_v2 snapshots")
for row in cur.execute("select * from snapshots"):
    print(" ", str(row)[:600])
print("tags sample")
for row in cur.execute("select * from tags limit 5"):
    print(" ", str(row)[:400])
con.close()
