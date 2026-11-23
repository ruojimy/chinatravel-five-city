"""Build an immutable opt-in planning overlay from the V20 catalog in openGauss."""

from collections import Counter
import csv
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from shutil import copytree, ignore_patterns
from statistics import median
from tempfile import TemporaryDirectory

from .snapshots import import_snapshot

CITIES = ("西安", "厦门")
BASE = "6de12f4"
PROFILE = "xiamen12_historical_v20_completion"
ESTIMATES = f"sandbox_profiles/{PROFILE}/database/accommodations/xian/"


def positive(value):
    try:
        amount = float(value)
    except (ValueError, TypeError):
        return None
    return amount if isfinite(amount) and amount > 0 else None


def approved_estimates(db, base):
    """Join only unique, explicitly approved high-confidence observations."""
    result = {}
    for filename in ("price_estimates_supplement.csv", "price_provenance.csv"):
        relative = ESTIMATES + filename
        path = base / relative
        digest = sha256(path.read_bytes()).hexdigest()
        if db.one("SELECT sha256 FROM st_snapshot_file WHERE snapshot_id=%s AND path=%s",
                  (BASE, relative)) != (digest,):
            raise ValueError(f"酒店估价来源校验失败: {relative}")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        names = Counter(row["name"] for row in rows)
        for index, row in enumerate(rows):
            direct = filename == "price_provenance.csv"
            confidence = row["confidence"] if direct else row["confidence_by_n"]
            if names[row["name"]] != 1 or confidence != "high":
                continue
            if not direct and row["recommended"] != "adopt_as_estimated":
                continue
            value = positive(row.get("price_mid", row.get("mid")))
            lower = positive(row.get("price_low", row.get("interval60_low")))
            upper = positive(row.get("price_high", row.get("interval60_high")))
            donors = row.get("n_comparables", "")
            if not (value and lower and upper and lower <= value <= upper and donors.isdecimal() and int(donors) >= 8):
                continue
            result[row["name"]] = {
                "price": value, "basis": "high_confidence_estimate", "unit": "CNY/room/night",
                "interval": [lower, upper], "comparables": int(donors),
                "source": {"file": relative, "sha256": digest, "row_index_0based": index},
            }
    return result


def hotel_price(payload):
    info = payload.get("hotel_reference", {})
    offers = []
    for value in info.get("room_or_offer_observations", ()):
        obs = value["observation"]
        if positive(obs.get("price_cny_per_room_stay")) and positive(obs.get("nights")):
            amount = positive(obs["price_cny_per_room_stay"]) / positive(obs["nights"])
        elif obs.get("unit") == "元/间/查询1晚" and positive(obs.get("price_cny")):
            amount = positive(obs["price_cny"])
        else:
            continue
        offers.append(amount)
    if offers:
        return {"price": median(offers), "basis": "historical_nightly_room_observation",
                "unit": "CNY/room/night", "observations": len(offers)}
    display = info.get("display_price_observation") or {}
    amount = positive(display.get("amount_cny"))
    if amount:
        return {"price": amount, "basis": "historical_display_price_proxy",
                "unit": "CNY/room/night", "original_unit_scope": display.get("unit_scope"),
                "observed_at": display.get("observed_at"), "evidence_id": display.get("evidence_id")}
    return None


def entry(payload, scope, estimate):
    src = payload.get("source_record_id")
    access, data = payload["access"], payload["data"]
    if not src:
        return None
    result = {"name": payload["name"], "source": payload["source_locator"], "fields": {},
              "basis": "catalog_reference", "planning_eligible": False}
    # Discovery is broader than routeability. Keep records with no position searchable by name.
    routable = (access.get("planning_position_available") and access.get("poi_name_match")
                and positive(data.get("lat")) and positive(data.get("lon")))
    if payload["kind"] == "accommodation" and routable and access.get("grade") != "L4":
        price = hotel_price(payload) if payload["city"] == "厦门" else estimate
        if price:
            result.update(basis=price["basis"], price_evidence=price, planning_eligible=True)
            result["fields"]["price"] = round(price["price"], 2)
            if payload["city"] == "厦门":
                # The legacy solver interprets numbed as guest capacity per room.
                result["fields"]["numbed"] = 2
                result["room_assumption"] = {"physical_beds": 1, "guest_capacity": 2,
                                             "basis": "user_approved_double_room_trial"}
            elif positive(data.get("numbed")):
                result["fields"]["numbed"] = data["numbed"]
            else:
                return result | {"fields": {}, "planning_eligible": False}
    if scope == "reference" and payload["kind"] == "attraction":
        admission = payload.get("admission_evidence")
        if admission:
            result["basis"] = admission["basis"]
            result["fields"]["price"] = 0
            if routable and access.get("time_complete") and access.get("grade") != "L4":
                result["planning_eligible"] = True
                low, high = positive(data.get("recommendmintime")), positive(data.get("recommendmaxtime"))
                if not low or not high or high < low:
                    result["fields"].update(recommendmintime=0.5, recommendmaxtime=1.0)
                    result["visit_duration_basis"] = "30_to_60_minute_trial_default"
    return result


def prepare(db, base):
    estimates = approved_estimates(db, base)
    strict = db.all("SELECT name FROM st_catalog_record WHERE snapshot_id=%s AND city=%s AND kind='accommodation'",
                    (BASE, "西安"))
    excluded = {name for name, in strict}
    records = db.all(
        "SELECT payload FROM st_catalog_reference WHERE snapshot_id=%s ORDER BY id", (BASE,))
    if not records or not db.one("SELECT 1 FROM st_meta WHERE key='city_catalog_v20_references'"):
        raise ValueError("请先完成 V20 目录和参考批次导入")
    pending_hotels = db.all(
        "SELECT payload FROM st_catalog_pending WHERE snapshot_id=%s AND city=%s AND kind='accommodation' ORDER BY id",
        (BASE, "西安"))
    hotels = [json.loads(raw) for raw, in pending_hotels]
    counts = Counter(hotel["name"] for hotel in hotels)
    data = {}
    for raw, in records:
        payload = json.loads(raw)
        value = entry(payload, "reference", None)
        if value:
            data[payload["source_record_id"]] = value
    for hotel in hotels:
        name = hotel["name"]
        if name in excluded or counts[name] != 1 or name not in estimates:
            continue
        value = entry(hotel, "estimate", estimates[name])
        if value and value["planning_eligible"]:
            data[hotel["source_record_id"]] = value
    timetable = []
    rail_rows = db.all(
        "SELECT payload FROM st_catalog_record WHERE snapshot_id=%s AND kind='train' ORDER BY id", (BASE,))
    for raw_row, in rail_rows:
        record = json.loads(raw_row)
        row = record["data"]
        fare = row.get("fare", {})
        if fare.get("scope") != "historical_fare_reference" or not positive(fare.get("value_cny")):
            continue
        timetable.append({"origin": row["origin"], "destination": row["destination"],
                          "service": [row[field] for field in ("TrainID", "From", "To", "BeginTime", "EndTime")],
                          "fare": fare})
    policy = {"schema": 1, "base": BASE, "cities": CITIES, "records": data, "rail": timetable}
    raw = (json.dumps(policy, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    identifier = "trial-" + sha256(raw).hexdigest()[:24]
    with TemporaryDirectory(prefix="st-trial-") as folder:
        root = Path(folder)
        (root / "reference-preview.json").write_bytes(raw)
        import_snapshot(db, root, identifier, BASE, "ShortTrip 2.2 reference trial", catalog=False)
    totals = Counter((key.split(":", 1)[0], value["basis"], value["planning_eligible"]) for key, value in data.items())
    print(f"参考试排快照 {identifier}，{len(data)} 条地点，{len(timetable)} 条历史铁路票价")
    for (kind, basis, eligible), count in sorted(totals.items()):
        print(f"  {kind} {basis} {'试排' if eligible else '查询'} {count}")
    return identifier


def prepare_engine(base, destination):
    """Use the same trial evidence in the constructor and the independent verifier."""
    original = base / "sandbox_profiles" / PROFILE / "engine"
    copytree(original, destination, dirs_exist_ok=True, ignore=ignore_patterns("__pycache__", "*.pyc"))
    path = destination / "chinatravel/environment/planning_access.py"
    text = path.read_text(encoding="utf-8")
    before = "    return Sandbox('G3')"
    if text.count(before) != 1:
        raise ValueError("Unexpected V20 verifier source")
    path.write_text(text.replace(
        before,
        "    if _PROFILE == 'expanded12':\n"
        "        from shorttrip_planner_preview import sandbox_for\n"
        "        return sandbox_for(Sandbox)\n"
        + before,
    ), encoding="utf-8")
    return destination
