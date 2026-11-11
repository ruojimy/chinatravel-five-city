"""Parse Trip.com hotel list SSR payload into (hotelId, name, price, lat, lon) rows.

Input: raw HTML saved from https://hk.trip.com/hotels/list?city=10...
Prints JSON lines with the fields plus the raw offsets of name and price in the HTML,
so callers can judge whether a single continuous quote is possible.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def unescape_blob(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    out = []
    for c in chunks:
        try:
            out.append(json.loads(c))
        except json.JSONDecodeError:
            continue
    return "".join(out)


def balanced(text: str, start: int) -> str | None:
    """text[start] must be '{' or '['; return the balanced slice."""
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def find_key(text: str, key: str):
    """Yield values of every '"key":<value>' occurrence, parsed as JSON."""
    pat = re.compile(r'"%s":' % re.escape(key))
    for m in pat.finditer(text):
        pos = m.end()
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            continue
        ch = text[pos]
        if ch in "{[":
            raw = balanced(text, pos)
        else:
            end = pos
            while end < len(text) and text[end] not in ",}]":
                end += 1
            raw = text[pos:end]
        if raw is None:
            continue
        try:
            yield m.start(), json.loads(raw)
        except json.JSONDecodeError:
            continue


def main() -> int:
    path = Path(sys.argv[1])
    html = path.read_bytes().decode("utf-8", errors="replace")
    blob = unescape_blob(html)
    hotels = []
    for _, val in find_key(blob, "hotelList"):
        if not isinstance(val, list):
            continue
        for card in val:
            info = card.get("hotelInfo") or {}
            name = ((info.get("nameInfo") or {}).get("name") or "").strip()
            hid = ((info.get("summary") or {}).get("hotelId") or "").strip()
            pos = info.get("positionInfo") or {}
            coord = (pos.get("mapCoordinate") or [{}])[0]
            addr = pos.get("address") or ""
            price = None
            room_name = ""
            bed = ""
            for room in card.get("roomInfo") or []:
                pi = room.get("priceInfo") or {}
                if pi.get("price"):
                    price = pi.get("price")
                    room_name = ((room.get("summary") or {}).get("saleRoomName") or "")
                    bed = "；".join(((room.get("bedInfo") or {}).get("contentList") or []))
                    break
            hotels.append({
                "hotel_id": hid,
                "name": name,
                "price": price,
                "room": room_name,
                "bed": bed,
                "lat": coord.get("latitude"),
                "lon": coord.get("longitude"),
                "addr": addr,
            })
        break
    for h in hotels:
        print(json.dumps(h, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
