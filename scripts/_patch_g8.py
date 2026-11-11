"""Patch: wire the real-road-network check (G8) into the quality gate."""
from pathlib import Path

DYN = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic"


def patch(name: str, pairs: list[tuple[str, str]]) -> None:
    path = DYN / name
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"pattern missing in {name}: {old[:60]!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("patched", name)


patch(
    "records.py",
    [
        (
            "    patched_instances: int = 0\n    conflicts: list = field(default_factory=list)",
            "    patched_instances: int = 0\n    conflicts: list = field(default_factory=list)\n    route: dict | None = None",
        ),
        (
            '            "conflicts": self.conflicts,',
            '            "conflicts": self.conflicts,\n            "route": self.route,',
        ),
    ],
)

patch(
    "quality.py",
    [
        (
            "    def evaluate(self, candidate: CandidateRecord) -> QualityReport:",
            "    def evaluate(self, candidate: CandidateRecord, route: dict | None = None) -> QualityReport:",
        ),
        (
            '        gate("S2_official_site", has_site, "有官网链接" if has_site else "未取到官网", hard=False)',
            '''        gate("S2_official_site", has_site, "有官网链接" if has_site else "未取到官网", hard=False)

        # G8 real road network: the sandbox `goto` is a synthetic subway graph and is
        # systematically optimistic, so compare against Amap before trusting a plan.
        if route:
            ratios = []
            for key, label in (("walk", "步行"), ("transit", "公交/地铁")):
                sandbox_min = route.get(f"sandbox_{key}_min")
                amap_min = route.get(f"amap_{key}_min")
                if sandbox_min and amap_min:
                    ratios.append((label, round(float(amap_min) / float(sandbox_min), 2)))
            worst = max(ratios, key=lambda item: item[1]) if ratios else None
            passed = bool(worst) and worst[1] <= 1.25
            detail = (
                f"{[f'{label} x{ratio}' for label, ratio in ratios]}"
                if ratios
                else "缺少可对比的路由数据"
            )
            gate("G8_real_route", passed, detail + (" -> 沙盒时间乐观" if not passed else ""), hard=False)''',
        ),
    ],
)

patch(
    "pipeline.py",
    [
        (
            "from .sources import cached_fetch, default_sources",
            "from .sources import amap_route, cached_fetch, default_sources",
        ),
        (
            "    def run(self, request: DataRequest) -> UpdateResult:\n        evidence = self.fetch(request)\n        candidate = self.extractor.extract(request, evidence)\n        quality = self.gate.evaluate(candidate)",
            '''    def route_check(self, request: DataRequest, candidate, anchor: str | None) -> dict | None:
        """Sandbox synthetic route vs Amap real road network, for one anchor."""
        if not anchor or not candidate.fields:
            return None
        lat = candidate.fields.get("lat")
        lon = candidate.fields.get("lon")
        if not lat or not lon or lat.value is None or lon.value is None:
            return None
        poi_table = self.env.transport.poi_search.data.get(request.city, {})
        anchor_coords = poi_table.get(anchor)
        if anchor_coords is None:
            return None
        facts: dict = {"anchor": anchor, "city": request.city}
        for mode, key in (("walking", "walk"), ("transit", "transit")):
            try:
                result = amap_route(
                    (float(anchor_coords[0]), float(anchor_coords[1])),
                    (float(lat.value), float(lon.value)),
                    mode=mode,
                    city=request.city,
                )
            except Exception as exc:  # noqa: BLE001
                result = {"mode": mode, "ok": False, "error": str(exc)}
            facts[f"amap_{key}_min"] = result.get("duration_min")
            facts[f"amap_{key}_km"] = result.get("distance_km")
            facts[f"amap_{key}_ok"] = result.get("ok")
        for mode, key in (("walk", "walk"), ("metro", "transit")):
            seconds = self.env.trip_seconds(request.city, anchor, candidate.fields["name"].value, mode)
            facts[f"sandbox_{key}_min"] = round(seconds * 60, 1) if seconds else None
        return facts

    def run(self, request: DataRequest, anchor: str | None = None) -> UpdateResult:
        evidence = self.fetch(request)
        candidate = self.extractor.extract(request, evidence)
        route = self.route_check(request, candidate, anchor)
        quality = self.gate.evaluate(candidate, route)''',
        ),
        (
            '            "evidence": [item.to_dict() for item in evidence],\n            }\n            version = self.store.add(payload)',
            '            "evidence": [item.to_dict() for item in evidence],\n                "route": route,\n            }\n            version = self.store.add(payload)',
        ),
        (
            "            return UpdateResult(request, candidate, quality, version, patched, conflicts)",
            "            return UpdateResult(request, candidate, quality, version, patched, conflicts, route)",
        ),
        (
            "        return UpdateResult(request, candidate, quality, version, 0, conflicts)",
            "        return UpdateResult(request, candidate, quality, version, 0, conflicts, route)",
        ),
    ],
)
print("done")
