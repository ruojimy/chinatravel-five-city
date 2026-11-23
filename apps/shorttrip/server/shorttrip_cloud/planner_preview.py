"""Release-local policy for ShortTrip's opt-in evidence-backed trial plans."""

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path

OVERLAY = "SHORTTRIP_REFERENCE_PREVIEW"


@lru_cache(maxsize=1)
def policy():
    path = os.environ.get(OVERLAY)
    if not path:
        return {"cities": [], "records": {}, "id": None}
    path = Path(path)
    raw = path.read_bytes()
    expected = "trial-" + hashlib.sha256(raw).hexdigest()[:24]
    data = json.loads(raw)
    if path.parent.name != expected or data["schema"] != 1 or data["base"] != "6de12f4":
        raise ValueError("参考试排数据校验失败")
    return {**data, "id": expected}


def sandbox_for(Sandbox):
    selected = policy()["records"]
    if not selected:
        return Sandbox("G3")

    class TrialSandbox(Sandbox):
        def _record(self, kind, city, row_index):
            item = super()._record(kind, city, row_index)
            extra = selected.get(item["record_id"])
            if extra is None or extra["name"] != item["name"]:
                return item
            payload = item["payload"]
            access = payload["access"]
            access["shorttrip_trial_context"] = extra
            access["catalog_discoverable"] = True
            if extra["basis"] == "price_quarantined":
                payload["data"]["price"] = None
                access["main_path"] = False
                access["price_usable_for_static_budget"] = False
            if extra["planning_eligible"] and access["planning_position_available"] and access["poi_name_match"]:
                payload["data"].update(extra["fields"])
                access["main_path"] = True
                access["price_usable_for_static_budget"] = "price" in extra["fields"]
                access["planning_required_missing"] = [
                    name for name in access["planning_required_missing"] if name not in extra["fields"]
                ]
                access["qualification_boundary"] = "允许试排。历史或估计价格、房型和建议时长以实际为准。"
            elif access["planning_required_missing"]:
                access["main_path"] = False
            return item

        @lru_cache(maxsize=None)
        def _discoverable(self, kind, city):
            base = dict(super()._discoverable(kind, city))
            if city in policy()["cities"] and kind in ("attraction", "accommodation"):
                _, _, rows, _, _, aliases, _ = self._catalog(kind, city)
                for index in range(len(rows)):
                    if index in base or index in aliases:
                        continue
                    rid = f"{kind}:{self.cities[city]}:{rows[index].get('id', '')}"
                    if rid in selected:
                        base[index] = self._record(kind, city, index)
            return tuple(sorted(base.items()))

        def intercity_search(self, origin, destination, mode="any", travel_date=None, seat_code=None):
            result = super().intercity_search(origin, destination, mode, travel_date, seat_code)
            if travel_date and not seat_code and any(city in policy()["cities"] for city in (origin, destination)) and mode != "airplane":
                # The pinned engine exposes these fares only in undated mode. Date-matched
                # services from the first call take priority over the historical schedule.
                fallback = super().intercity_search(origin, destination, "train")
                existing = {rail_key(item["record"]["payload"]["data"], origin, destination)
                            for item in result["records"] if item["mode"] == "train"}
                for item in fallback["records"]:
                    payload = item["record"]["payload"]
                    data = payload["data"]
                    if rail_key(data, origin, destination) not in existing and historical_trial(data, origin, destination):
                        result["records"].append(item)
            for item in result["records"]:
                payload = item["record"]["payload"]
                data = payload["data"]
                if item["mode"] == "train" and historical_trial(data, origin, destination):
                    payload["static_budget_eligible"] = True
                    data["CostSource"] = "shorttrip_historical_trial"
            result["returned"] = len(result["records"])
            return result

    # The upstream edit/runtime cache locates the concrete adapter module by this name.
    TrialSandbox.__module__ = Sandbox.__module__
    return TrialSandbox("G3")


@lru_cache(maxsize=1)
def rail_fares():
    result = {}
    for row in policy().get("rail", ()):
        key = (row["origin"], row["destination"], *row["service"])
        # Conflicting observations need independent review.
        amount = row["fare"]["value_cny"]
        result[key] = amount if key not in result or result[key] == amount else None
    return result


RAIL_FIELDS = ("TrainID", "From", "To", "BeginTime", "EndTime")


def rail_key(data, origin, destination):
    return (origin, destination, *(data.get(field) for field in RAIL_FIELDS))


def historical_trial(data, origin, destination):
    return (data.get("CostSource") in ("12306_historical_benchmark_reference", "shorttrip_historical_trial")
            and rail_fares().get(rail_key(data, origin, destination)) == data.get("Cost"))


def apply_rail_fares(frame, origin, destination, lang):
    fares = rail_fares()
    if lang != "zh" or not fares or frame.empty or "Cost" not in frame:
        return frame
    for index, row in frame[frame["Cost"].isna()].iterrows():
        key = rail_key(row, origin, destination)
        fare = fares.get(key)
        if fare is not None:
            frame.at[index, "Cost"] = fare
            frame.at[index, "CostSource"] = "shorttrip_historical_trial"
    return frame


def trial_price(data, access, unit):
    extra = access.get("shorttrip_trial_context")
    if not extra or not extra["planning_eligible"] or "price" not in extra["fields"]:
        return None
    return {"value": data["price"], "currency": "CNY", "unit": unit, "status": "trial_reference",
            "unit_basis": "shorttrip_trial", "source_status": extra["basis"], "source_context": extra,
            "usable_for_snapshot_budget": True, "verified_for_date": False, "inventory": "unknown"}
