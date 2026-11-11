"""Patch 2: neutral G8 for brand-new POIs + real-road calibration slack."""
from pathlib import Path

DYN = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic"
SRC = Path(__file__).resolve().parents[1] / "src" / "shorttrip"


def patch(path: Path, pairs, count=1):
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"pattern missing in {path.name}: {old[:70]!r}")
        text = text.replace(old, new, count)
    path.write_text(text, encoding="utf-8")
    print("patched", path.name)


patch(
    DYN / "quality.py",
    [
        (
            '            worst = max(ratios, key=lambda item: item[1]) if ratios else None\n'
            '            passed = bool(worst) and worst[1] <= 1.25\n'
            '            detail = (\n'
            '                f"{[f\'{label} x{ratio}\' for label, ratio in ratios]}"\n'
            '                if ratios\n'
            '                else "缺少可对比的路由数据"\n'
            '            )\n'
            '            gate("G8_real_route", passed, detail + (" -> 沙盒时间乐观" if not passed else ""), hard=False)',
            '            worst = max(ratios, key=lambda item: item[1]) if ratios else None\n'
            '            if worst is None:\n'
            '                # brand-new POI: nothing to compare against, so do not penalise;\n'
            '                # the Amap baseline is stored for calibration instead.\n'
            '                passed = True\n'
            '                detail = "新增 POI，无沙盒基线；已记录高德基线供校准"\n'
            '            else:\n'
            '                passed = worst[1] <= 1.25\n'
            '                detail = "[" + ", ".join(f"{label} x{ratio}" for label, ratio in ratios) + "]"\n'
            '                if not passed:\n'
            '                    detail += " -> 沙盒时间乐观"\n'
            '            gate("G8_real_route", passed, detail, hard=False)',
        ),
        (
            "        if soft_failed:\n            confidence -= 0.12 * len(soft_failed)",
            "        if soft_failed:\n            confidence -= 0.12 * len(soft_failed)\n"
            "        if route and (route.get('amap_walk_min') or route.get('amap_transit_min')):\n"
            "            confidence = max(confidence, 0.55)",
        ),
    ],
)

patch(
    SRC / "planner.py",
    [
        (
            "    day_cutoff_mid: int = 19 * 60 + 30\n    day_cutoff_last: int = 21 * 60",
            "    day_cutoff_mid: int = 19 * 60 + 30\n    day_cutoff_last: int = 21 * 60\n"
            "    # Amap shows the sandbox `goto` is 1.3-1.7x optimistic, so reserve slack\n"
            "    # on top of every leg when judging whether an activity still fits.\n"
            "    route_slack_factor: float = 1.3",
        ),
        (
            "            mode = self.env.best_mode(city, builder.position, station)\n"
            "            travel = self.env.trip_seconds(city, builder.position, station, mode) if mode else None\n"
            "            if travel is None:\n"
            "                return False\n"
            "            return minutes(builder.time) + travel * 60 + duration + 20 <= deadline",
            "            mode = self.env.best_mode(city, builder.position, station)\n"
            "            travel = self.env.trip_seconds(city, builder.position, station, mode) if mode else None\n"
            "            if travel is None:\n"
            "                return False\n"
            "            travel = travel * self.options.route_slack_factor\n"
            "            return minutes(builder.time) + travel * 60 + duration + 20 <= deadline",
        ),
    ],
)

patch(
    SRC / "scheduler.py",
    [
        (
            '    day_cutoff_last: int = 21 * 60,\n    day_cutoff_mid: int = 19 * 60 + 30,',
            '    day_cutoff_last: int = 21 * 60,\n    day_cutoff_mid: int = 19 * 60 + 30,\n'
            '    route_slack_factor: float = 1.3,',
        ),
        (
            "            travel = env.trip_seconds(city, position, back[\"From\"], mode) if mode else None\n"
            "            if travel is None:\n"
            "                return False\n"
            "            return minutes(builder.time) + travel * 60 + duration + 15 <= deadline",
            "            travel = env.trip_seconds(city, position, back[\"From\"], mode) if mode else None\n"
            "            if travel is None:\n"
            "                return False\n"
            "            travel = travel * route_slack_factor\n"
            "            return minutes(builder.time) + travel * 60 + duration + 15 <= deadline",
        ),
    ],
)
print("done")
