"""Build the room_types and hotel_price_observations tables in a catalog snapshot.

The main accommodation record keeps ONE room type (ChinaTravel alignment).
All room types live in `room_types`, queried only after a hotel is shortlisted.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "xian_gapfill_20261109"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    args = ap.parse_args()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap

    room_files = [RUN / "staging/roomtypes_existing/room_types.jsonl"]
    room_files += sorted((RUN / "staging").glob("hotel_batch_*/room_types.jsonl"))
    rows, seen = [], set()
    for f in room_files:
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["hotel"], r["room_id"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)

    price_items = []
    for f in ([RUN / "staging/hotel/items.jsonl", RUN / "staging/hotel2/items.jsonl"]
              + sorted((RUN / "staging").glob("hotel_batch_*/items.jsonl"))):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            it = json.loads(line)
            if "price" in (it.get("data") or {}):
                price_items.append(it)

    con = sqlite3.connect(str(snap))
    con.execute("drop table if exists room_types")
    con.execute("""create table room_types (
        hotel_name text not null, room_id text not null, room_name text,
        bed_text text, bed_count integer, area text, window text,
        is_primary integer default 0, source_url text, raw_path text,
        observed_at text, hotel_id text,
        primary key (hotel_name, room_id))""")
    con.executemany("""insert or replace into room_types
        (hotel_name, room_id, room_name, bed_text, bed_count, area, window,
         is_primary, source_url, raw_path, observed_at, hotel_id)
        values (?,?,?,?,?,?,?,?,?,?,?,?)""", [
        (r["hotel"], r["room_id"], r.get("room_name"), r.get("bed_text"), r.get("bed_count"),
         r.get("area"), r.get("window"), r.get("is_primary", 0), r.get("source_url"),
         r.get("raw_path"), r.get("observed_at"), str(r.get("hotel_id") or ""))
        for r in rows])

    con.execute("drop table if exists hotel_price_observations")
    con.execute("""create table hotel_price_observations (
        hotel_name text, price real, observed_at text, source_url text,
        raw_path text, basis text)""")
    con.executemany("""insert into hotel_price_observations
        (hotel_name, price, observed_at, source_url, raw_path, basis)
        values (?,?,?,?,?,?)""", [
        (it["name"], float(it["data"]["price"]), it["source"].get("observed_at"),
         it["source"].get("url"), it["evidence"].get("raw_path"),
         (it.get("notes") or "").split(";")[0].replace("price_basis=", ""))
        for it in price_items])
    con.execute("create index if not exists idx_roomtypes_hotel on room_types(hotel_name)")
    con.execute("create index if not exists idx_priceobs_hotel on hotel_price_observations(hotel_name)")
    con.commit()

    hotels = con.execute("select count(distinct hotel_name) from room_types").fetchone()[0]
    rooms = con.execute("select count(*) from room_types").fetchone()[0]
    multi = con.execute("""select count(*) from (select hotel_name, count(distinct bed_count)
                           from room_types where bed_count is not null group by hotel_name
                           having count(distinct bed_count) > 1)""").fetchone()[0]
    obs = con.execute("select count(distinct hotel_name) from hotel_price_observations").fetchone()[0]
    con.close()
    print(json.dumps({"hotels_with_rooms": hotels, "rooms": rooms,
                      "hotels_multi_bed_config": multi,
                      "hotels_with_price_obs": obs,
                      "room_files": [str(f.relative_to(ROOT)) for f in room_files if f.exists()]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
