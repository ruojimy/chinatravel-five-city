"""End-to-end orchestration: gap -> fetch -> extract -> gate -> version -> patch."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import bus
from .extract import HybridExtractor
from .overlay import OverlayStore
from .quality import QualityGate
from .records import DataRequest, UpdateResult, GateResult
from .sources import amap_route, cached_fetch, default_sources

ROOT = Path(__file__).resolve().parents[3]


def rehydrate(store: OverlayStore, env, extra_roots: list | None = None,*,now=None,
              allow_synthetic=False) -> int:
    """Re-apply every active overlay record to the live tools in this process.

    The overlay is the durable store; a fresh process (a new planner run, an
    evaluation job) must replay it before planning, otherwise it silently plans
    against the stale sandbox.
    """
    patched = 0
    for record in store.active(now=now,allow_synthetic=allow_synthetic):
        outcome = bus.apply(record,extra_roots=(extra_roots or [])+[env],now=now,
                            allow_synthetic=allow_synthetic)
        patched += outcome.patched
    invalidate = getattr(env, "invalidate", None)
    if callable(invalidate):
        invalidate()
    return patched


class UpdatePipeline:
    def __init__(
        self,
        env,
        store: OverlayStore,
        *,
        sources=None,
        extractor: HybridExtractor | None = None,
        gate: QualityGate | None = None,
        use_llm: bool = True,
        record_dir: Path | None = None,
    ):
        self.env = env
        self.store = store
        self.sources = sources if sources is not None else default_sources(include_llm=use_llm)
        self.extractor = extractor or HybridExtractor(use_llm=use_llm)
        self.gate = gate or QualityGate(env)
        self.record_dir = record_dir or (ROOT / "results" / "dynamic_evidence")
        self.record_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- flow
    def fetch(self, request: DataRequest) -> list:
        evidence = []
        for source in self.sources:
            started = time.time()
            item = cached_fetch(source, request.name, request.city)
            item.structured = item.structured or {}
            item.structured["latency_s"] = round(time.time() - started, 2)
            evidence.append(item)
            time.sleep(0.4)  # be polite to free endpoints (Nominatim asks for <=1 rps)
        return evidence

    # -------------------------------------------------------------- conflicts
    def detect_conflicts(self, request: DataRequest, record: dict) -> list[dict]:
        """Compare a fresh record against what the sandbox already believes.

        This is the "data conflict" field from M6: a newer, authoritative source
        that disagrees with the snapshot must not be silently overwritten.
        """
        table_of = {
            "attraction": self.env.attraction_table,
            "restaurant": self.env.restaurant_table,
            "accommodation": self.env.accommodation_table,
        }[request.kind]
        table = table_of(request.city)
        if table is None or table.empty:
            return []
        names = table["name"].astype(str)
        match = table[names == record["name"]]
        if match.empty:
            return []
        row = match.iloc[0].to_dict()
        conflicts: list[dict] = []
        for field, column in (("opentime", "opentime"), ("endtime", "endtime")):
            fresh = str(record.get(field) or "")
            old = str(row.get(column) or "")
            if fresh and old and fresh[:5] != old[:5]:
                conflicts.append({"field": field, "sandbox": old, "external": fresh})
        if record.get("price") is not None and row.get("price") is not None:
            try:
                if abs(float(record["price"]) - float(row["price"])) > 0.5:
                    conflicts.append(
                        {"field": "price", "sandbox": float(row["price"]), "external": float(record["price"])}
                    )
            except (TypeError, ValueError):
                pass
        try:
            from math import cos, radians, sqrt

            dlat = (float(record["lat"]) - float(row["lat"])) * 111.0
            dlon = (float(record["lon"]) - float(row["lon"])) * 111.0 * cos(radians(float(row["lat"])))
            if sqrt(dlat * dlat + dlon * dlon) > 0.8:
                conflicts.append(
                    {
                        "field": "location",
                        "sandbox": [float(row["lat"]), float(row["lon"])],
                        "external": [float(record["lat"]), float(record["lon"])],
                    }
                )
        except (KeyError, TypeError, ValueError):
            pass
        return conflicts

    def route_check(self, request: DataRequest, candidate, anchor: str | None) -> dict | None:
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

    def run(self,request:DataRequest,anchor:str|None=None,*,expansion_envelope:dict|None=None) -> UpdateResult:
        evidence = self.fetch(request)
        candidate = self.extractor.extract(request, evidence)
        route = self.route_check(request, candidate, anchor)
        quality = self.gate.evaluate(candidate, route)
        conflicts = self.detect_conflicts(request, candidate.plain()) if candidate.fields else []
        if conflicts and quality.decision == "accept":
            quality.decision = "quarantine"
            quality.needs_user_confirm = True
            quality.reasons.append(
                f"与沙箱现有记录冲突 {len(conflicts)} 处 -> 不覆盖，等待确认："
                + ", ".join(item["field"] for item in conflicts)
            )
        version = None
        patched = 0
        if quality.decision == "accept":
            payload = {
                "request": request.to_dict(),
                "record": {**candidate.plain(), "kind": request.kind, "city": request.city},
                "quality": quality.to_dict(),
                "evidence": [item.to_dict() for item in evidence],
                "route": route,
            }
            if expansion_envelope is not None:payload['expansion_envelope']=expansion_envelope
            version = self.store.add(payload)
            load_gate=self.store.last_gate or {'planning_ready':False,'effective_status':'quarantine',
                                             'errors':['missing_overlay_load_verdict']}
            payload['load_gate']=load_gate
            if not load_gate.get('planning_ready') or load_gate.get('effective_status')!='active':
                quality.decision='quarantine'
                quality.needs_user_confirm=True
                quality.reasons.append('needs_contract: 完整来源/时间/字段合约未通过，已隔离，未注入。')
                quality.gates.append(GateResult('expansion_load_contract',False,
                                                json.dumps(load_gate,ensure_ascii=False)))
                payload['quality']=quality.to_dict()
                payload['patch']={'patched':0,'details':['blocked by final load gate']}
                (self.record_dir/f'{request.kind}_{request.city}_{request.name}.json').write_text(
                    json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
                return UpdateResult(request,candidate,quality,version,0,conflicts,route)
            outcome = bus.apply(payload['expansion_envelope'],extra_roots=[self.env])
            patched = outcome.patched
            if outcome.status!='applied' or patched==0:
                self.store.quarantine_version(version,outcome.status)
                quality.decision='quarantine';quality.needs_user_confirm=True
                quality.reasons.append('live_patch_blocked: '+outcome.status)
                quality.gates.append(GateResult('live_patch',False,json.dumps(outcome.details,ensure_ascii=False)))
                payload['quality']=quality.to_dict();payload['load_gate']=self.store.last_gate
            invalidate = getattr(self.env, "invalidate", None)
            if callable(invalidate):
                invalidate()
            payload["patch"] = {"patched":patched,"details":outcome.details,'status':outcome.status,'load_gate':outcome.gate}
            (self.record_dir / f"{request.kind}_{request.city}_{request.name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return UpdateResult(request, candidate, quality, version, patched, conflicts, route)
        if quality.decision == "quarantine":
            payload = {
                "request": request.to_dict(),
                "record": {**candidate.plain(), "kind": request.kind, "city": request.city},
                "quality": quality.to_dict(),
                "evidence": [item.to_dict() for item in evidence],
            }
            self.store.add(payload, status="quarantine")
        (self.record_dir / f"{request.kind}_{request.city}_{request.name}.json").write_text(
            json.dumps(
                {
                    "request": request.to_dict(),
                    "record": {**candidate.plain(), "kind": request.kind, "city": request.city},
                    "quality": quality.to_dict(),
                    "evidence": [item.to_dict() for item in evidence],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return UpdateResult(request, candidate, quality, version, 0, conflicts, route)
