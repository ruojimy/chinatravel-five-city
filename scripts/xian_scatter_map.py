"""Render a self-contained scatter map of every located Xi'an record.

No tiles, no CDN: the page draws a projected scatter on canvas so it renders
offline in the preview panel. Coordinates are catalog WGS-84; the projection
scales longitude by cos(latitude) so the city keeps its real aspect ratio.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from p31_common import _gcj_offset  # noqa: E402


def gcj_to_wgs(lat: float, lon: float) -> tuple[float, float]:
    """DataV boundaries are GCJ-02; the catalog is WGS-84."""
    wlat, wlon = lat, lon
    for _ in range(6):
        dlat, dlon = _gcj_offset(wlat, wlon)
        wlat, wlon = lat - dlat, lon - dlon
    return round(wlat, 5), round(wlon, 5)


def load_boundary(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    districts = []
    for feat in raw.get("features", []):
        geom = feat.get("geometry") or {}
        name = (feat.get("properties") or {}).get("name") or ""
        polys = geom.get("coordinates") or []
        if geom.get("type") == "Polygon":
            polys = [polys]
        rings = []
        for poly in polys:
            for ring in poly:
                pts = [gcj_to_wgs(lat, lon) for lon, lat in ring]
                if len(pts) >= 4:
                    rings.append([[q[1], q[0]] for q in pts])  # -> [lon, lat]
        if rings:
            districts.append({"name": name, "rings": rings})
    return districts

KINDS = [
    ("poi", "POI", "#7048E8"),
    ("restaurant", "餐厅", "#C92A2A"),
    ("attraction", "景点", "#E8590C"),
    ("accommodation", "住宿", "#2E86DE"),
    ("metro_station", "地铁站", "#0CA678"),
]


def coords(kind: str, data: dict) -> tuple[float, float] | None:
    if kind in ("poi", "metro_station"):
        pos = data.get("position")
        if isinstance(pos, str):
            parts = pos.split(",")
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except (IndexError, ValueError):
                return None
        elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
            # POI stores [lat, lon]; metro stores "lon,lat" as a string
            try:
                lat, lon = float(pos[0]), float(pos[1])
            except (TypeError, ValueError):
                return None
        else:
            return None
        return (lat, lon) if 3 < lat < 55 and 70 < lon < 140 else None
    try:
        return float(data["lat"]), float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def label(kind: str, data: dict, name: str) -> str:
    if kind == "accommodation":
        price = data.get("price")
        return f"{name} · ¥{price}" if price else name
    if kind == "restaurant":
        c = data.get("cuisine")
        return f"{name} · {c}" if c else name
    if kind == "attraction":
        t = data.get("opentime")
        return f"{name} · {t} 开" if t else name
    if kind == "metro_station":
        line = data.get("line")
        return f"{name} · {line}" if line else name
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="results/xian_gapfill_20261109/snapshot_v16/catalog.sqlite3")
    ap.add_argument("--out", default="results/xian_gapfill_20261109/xian_scatter.html")
    ap.add_argument("--boundary", default="data/geo/xian_boundary.json")
    args = ap.parse_args()

    con = sqlite3.connect(str(ROOT / args.snapshot))
    series = []
    counts = Counter()
    for kind, zh, color in KINDS:
        points = []
        for name, payload in con.execute(
                "select name,payload from records where city='西安' and kind=?", (kind,)):
            data = json.loads(payload)["data"]
            c = coords(kind, data)
            if not c:
                continue
            points.append([round(c[0], 5), round(c[1], 5), label(kind, data, name)])
        counts[zh] = len(points)
        series.append({"id": kind, "label": zh, "color": color, "points": points})
    con.close()

    boundary_path = ROOT / args.boundary
    districts = load_boundary(boundary_path) if boundary_path.exists() else []
    boundary_payload = json.dumps(districts, ensure_ascii=False, separators=(",", ":"))

    total = sum(counts.values())
    payload = json.dumps(series, ensure_ascii=False, separators=(",", ":"))
    legend_rows = "".join(
        f'<label class="row"><input type="checkbox" data-id="{s["id"]}" checked>'
        f'<span class="dot" style="background:{s["color"]}"></span>'
        f'<span class="name">{s["label"]}</span>'
        f'<span class="num">{counts[s["label"]]:,}</span></label>'
        for s in series
    )
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>西安数据分布散点图</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         background:#F6F5F2; color:#2C2C2A; }}
  header {{ padding:14px 18px 10px; border-bottom:1px solid #E3E1DA; background:#fff; }}
  h1 {{ margin:0 0 4px; font-size:16px; font-weight:600; }}
  .meta {{ font-size:12px; color:#6B6A64; }}
  .wrap {{ display:flex; gap:14px; padding:14px 18px 18px; align-items:flex-start; }}
  .panel {{ width:190px; flex:0 0 190px; background:#fff; border:1px solid #E3E1DA;
            border-radius:10px; padding:12px; }}
  .panel h2 {{ margin:0 0 8px; font-size:12px; font-weight:600; color:#6B6A64; letter-spacing:.02em; }}
  .row {{ display:flex; align-items:center; gap:8px; padding:5px 0; font-size:13px; cursor:pointer; }}
  .row input {{ margin:0; }}
  .dot {{ width:9px; height:9px; border-radius:50%; flex:0 0 9px; }}
  .name {{ flex:1; }}
  .num {{ color:#6B6A64; font-variant-numeric:tabular-nums; font-size:12px; }}
  .hint {{ margin-top:10px; font-size:11px; line-height:1.5; color:#8A8880; }}
  .canvas-box {{ position:relative; flex:1; background:#fff; border:1px solid #E3E1DA;
                 border-radius:10px; overflow:hidden; }}
  canvas {{ display:block; width:100%; height:640px; }}
  #tip {{ position:absolute; pointer-events:none; transform:translate(-50%,-140%);
          background:#2C2C2A; color:#fff; font-size:12px; padding:4px 8px; border-radius:6px;
          white-space:nowrap; opacity:0; transition:opacity .12s; }}
</style>
</head>
<body>
<header>
  <h1>西安 · 已采集数据位置分布</h1>
  <div class="meta">快照 snapshot_v16 · 共 {total:,} 个有坐标点位 · 生成于 {stamp}</div>
</header>
<div class="wrap">
  <div class="panel">
    <h2>类别</h2>
    {legend_rows}
    <label class="row"><input type="checkbox" id="boundary" checked>
      <span class="dot" style="background:#D9D6CC;border:1px solid #B4B2A9"></span>
      <span class="name">行政轮廓</span><span class="num">{len(districts)} 区县</span></label>
    <div class="hint">勾选切换显隐；鼠标悬停查看名称。轮廓来自 DataV 西安市边界（GCJ-02 已转 WGS-84），与点位同一坐标系。</div>
  </div>
  <div class="canvas-box">
    <canvas id="cv"></canvas>
    <div id="tip"></div>
  </div>
</div>
<script>
const SERIES = {payload};
const DISTRICTS = {boundary_payload};
const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
let visible = new Set(SERIES.map(s => s.id));
let showBoundary = true;
let boxes = [];

function resize() {{
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * dpr);
  cv.height = Math.round(r.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}}

function bounds() {{
  let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
  const grow = (lat, lon) => {{
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }};
  for (const s of SERIES) {{
    if (!visible.has(s.id)) continue;
    for (const p of s.points) grow(p[0], p[1]);
  }}
  if (showBoundary) {{
    for (const d of DISTRICTS) for (const ring of d.rings) for (const q of ring) grow(q[1], q[0]);
  }}
  return {{minLat, maxLat, minLon, maxLon}};
}}

function draw() {{
  const w = cv.clientWidth, h = cv.clientHeight;
  ctx.clearRect(0, 0, w, h);
  const b = bounds();
  if (!isFinite(b.minLat)) return;
  const pad = 34;
  const kx = Math.cos((b.minLat + b.maxLat) / 2 * Math.PI / 180);
  const spanX = Math.max((b.maxLon - b.minLon) * kx, 1e-4);
  const spanY = Math.max(b.maxLat - b.minLat, 1e-4);
  const scale = Math.min((w - pad * 2) / spanX, (h - pad * 2) / spanY);
  const ox = (w - spanX * scale) / 2;
  const oy = (h - spanY * scale) / 2;
  const proj = (lat, lon) => [ox + (lon - b.minLon) * kx * scale,
                              oy + (b.maxLat - lat) * scale];

  ctx.strokeStyle = '#EFEDE7';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = pad + (h - pad * 2) * i / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  }}

  if (showBoundary) {{
    for (const d of DISTRICTS) {{
      ctx.beginPath();
      for (const ring of d.rings) {{
        ring.forEach((q, i) => {{
          const [x, y] = proj(q[1], q[0]);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }});
        ctx.closePath();
      }}
      ctx.fillStyle = '#FBFAF6';
      ctx.fill('evenodd');
      ctx.strokeStyle = '#CFCBBF';
      ctx.lineWidth = 0.9;
      ctx.stroke();
    }}
    ctx.fillStyle = '#B4B2A9';
    ctx.font = '11px -apple-system, "Microsoft YaHei", sans-serif';
    ctx.textAlign = 'center';
    for (const d of DISTRICTS) {{
      if (!d.name || !d.rings.length) continue;
      let best = null, bestArea = 0;
      for (const ring of d.rings) {{
        let a = 0, cx = 0, cy = 0;
        for (let i = 0; i < ring.length - 1; i++) {{
          const x0 = ring[i][0], y0 = ring[i][1], x1 = ring[i + 1][0], y1 = ring[i + 1][1];
          const cross = x0 * y1 - x1 * y0;
          a += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross;
        }}
        const area = Math.abs(a / 2);
        if (area > bestArea) {{ bestArea = area; best = {{cx: cx / (3 * a), cy: cy / (3 * a), ring}}; }}
      }}
      if (!best) continue;
      let minX = 1e9, maxX = -1e9;
      for (const q of best.ring) {{
        const [x] = proj(q[1], q[0]);
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
      }}
      if (maxX - minX < 38) continue;
      const [x, y] = proj(best.cy, best.cx);
      ctx.fillText(d.name, x, y);
    }}
    ctx.textAlign = 'start';
  }}

  boxes = [];
  for (const s of SERIES) {{
    if (!visible.has(s.id)) continue;
    ctx.fillStyle = s.color;
    ctx.globalAlpha = s.id === 'poi' ? 0.45 : 0.8;
    for (const p of s.points) {{
      const [x, y] = proj(p[0], p[1]);
      ctx.beginPath();
      ctx.arc(x, y, s.id === 'poi' ? 1.3 : 1.9, 0, 6.2832);
      ctx.fill();
    }}
    ctx.globalAlpha = 1;
  }}

  ctx.fillStyle = '#8A8880';
  ctx.font = '11px -apple-system, "Microsoft YaHei", sans-serif';
  ctx.fillText(b.maxLat.toFixed(2) + '°N', 8, pad - 8);
  ctx.fillText(b.minLat.toFixed(2) + '°N', 8, h - pad + 14);
  ctx.fillText(b.minLon.toFixed(2) + '°E', pad, h - 8);
  ctx.fillText(b.maxLon.toFixed(2) + '°E', w - pad - 46, h - 8);
  cv.dataset.proj = JSON.stringify([b.minLat, b.maxLat, b.minLon, b.maxLon, kx, scale, ox, oy]);
}}

function pick(mx, my) {{
  const [minLat, maxLat, minLon, , kx, scale, ox, oy] = JSON.parse(cv.dataset.proj || '[]');
  if (minLat === undefined) return null;
  let best = null, bestD = 9;
  for (const s of SERIES) {{
    if (!visible.has(s.id)) continue;
    for (const p of s.points) {{
      const x = ox + (p[1] - minLon) * kx * scale;
      const y = oy + (maxLat - p[0]) * scale;
      const d = (x - mx) * (x - mx) + (y - my) * (y - my);
      if (d < bestD) {{ bestD = d; best = {{p, s, x, y}}; }}
    }}
  }}
  return best;
}}

cv.addEventListener('mousemove', (e) => {{
  const r = cv.getBoundingClientRect();
  const hit = pick(e.clientX - r.left, e.clientY - r.top);
  if (!hit) {{ tip.style.opacity = 0; return; }}
  tip.textContent = hit.p[2] + '（' + hit.s.label + '）';
  tip.style.left = hit.x + 'px';
  tip.style.top = hit.y + 'px';
  tip.style.opacity = 1;
}});
cv.addEventListener('mouseleave', () => {{ tip.style.opacity = 0; }});

document.getElementById('boundary').addEventListener('change', (e) => {{
  showBoundary = e.target.checked;
  draw();
}});
document.querySelectorAll('input[type=checkbox]').forEach(cb => {{
  cb.addEventListener('change', () => {{
    if (cb.checked) visible.add(cb.dataset.id); else visible.delete(cb.dataset.id);
    draw();
  }});
}});

window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>
"""
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(json.dumps({"out": str(out), "counts": counts, "total": total,
                      "size_kb": round(out.stat().st_size / 1024)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
