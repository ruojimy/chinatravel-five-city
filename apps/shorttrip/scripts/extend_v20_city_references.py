"""Publish source-backed V20 discovery references while retaining planning isolation."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import json
from pathlib import Path
import re
import sys
import unicodedata

from import_v20_city_catalog import digest, dump, number, present, read


RECEIPT = "city_catalog_v20_references"
PUBLIC_SPACES = Path(__file__).resolve().parent.parent / "references/v20-free-public-spaces.json"
OFFICIAL = "xiamen_evidence/official_room_price_history.csv"
NIKKO = "xiamen_evidence/nikko_manual/manual_room_variants.csv"
OBSERVATIONS = {
    "ctrip_wutong_rooms_observations.csv": "observation_csv_sha256",
    "ctrip_7days_rooms_observations.csv": "seven_csv_sha256",
    "ctrip_huaxin_rooms_observations.csv": "huaxin_csv_sha256",
}


def normalized_name(name):
    return "".join(unicodedata.normalize("NFKC", name).casefold().split())


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def source_rows(path, source_file, id_key, name_key, tier):
    for index, row in enumerate(csv_rows(path)):
        if not present(row.get(id_key)) or not present(row.get(name_key)) or not present(row.get("source_url")):
            raise ValueError(f"Missing evidence identity or URL in {path.name} row {index}")
        evidence = {
            "scope": tier,
            "source_locator": {"file": source_file, "sha256": digest(path), "row_index_0based": index},
            "observation": row,
        }
        yield row[id_key], (row[name_key], evidence)


def room_observations(profile, observations):
    by_id = defaultdict(list)
    for relative, id_key, name_key, tier in (
        (OFFICIAL, "main_record_id", "property", "first_party_historical_room_or_price"),
        (NIKKO, "hotel_main_id", "hotel_main_name", "first_party_historical_room_configuration"),
    ):
        for source_id, evidence in source_rows(profile / relative, relative, id_key, name_key, tier):
            by_id[source_id].append(evidence)
    if observations is None:
        return by_id
    manifest = read(observations / "manifest.json")
    for filename, digest_key in OBSERVATIONS.items():
        file = observations / filename
        if digest(file) != manifest[digest_key]:
            raise ValueError(f"Local historical quote file does not match its manifest: {filename}")
        relative = f"{observations.name}/{filename}"
        for source_id, item in source_rows(file, relative, "hotel_id", "hotel_name", "historical_manually_observed_offer"):
            _, evidence = item
            row = evidence["observation"]
            if (date.fromisoformat(row["checkout"]) <= date.fromisoformat(row["checkin"])
                    or not number(float(row["price_cny"]), 0.01) or row["unit"] != "元/间/查询1晚"
                    or row["is_actual_transaction"] != "no"):
                raise ValueError(f"Invalid historical offer context: {filename}")
            by_id[source_id].append(item)
    return by_id


OUTDOOR_CATEGORIES = {"公园", "城市广场", "海滩", "步行街", "历史文化街区", "商业街区", "城市道路"}
BROAD_CATEGORIES = {"旅游景点", "风景名胜", "公园广场", "自然风光", "休闲场所", "观景点", "人文景观"}
OUTDOOR_NAMES = (
    (re.compile(r"公园(?:[东西南北中]区)?(?:[\(（][^()（）]*路[^()（）]*[\)）])?$"), "public_park_grounds"),
    (re.compile(r"广场$"), "public_square"),
    (re.compile(r"(?:海滩|沙滩|浴场)$"), "public_beach"),
    (re.compile(r"(?:步行街|老街|古街|街道|历史文化街区|文创街区|文化街|商业步行街|水街|猫街)$"), "public_outdoor_streets"),
    (re.compile(r"(?:绿道|步道|木栈道|长堤|共享绿地|观景平台|观景台)(?:[（(]园路[^()（）]*[)）])?$"), "public_path_or_viewpoint"),
)
RESTRICTED_CONTEXT = re.compile(
    r"方特|老院子|观音山梦幻|大明宫|白鹿原影视城|中国唐苑|"
    r"国家森林公园|国家湿地公园|核心保护区|大学|校园|校区|"
    r"购物中心|商场|奥莱|万达|集团|商务营运中心|总部|餐厅|"
    r"泡泡玛特|啤酒|睡眠|研学广场|露营地|团建|管理处|贵宾|建设中|"
    r"游乐|乐园|蹦床|剧场|演艺中心|海洋馆|水族馆|景区[-－·]|度假区|鳌园|琴园|北辰山-|陈嘉庚墓|华夏千古颂|海之梦|[一二三四五六七八九]区广场|住宅小区"
)


def public_outdoor_scope(name, data):
    if not present(name) or RESTRICTED_CONTEXT.search(name):
        return None
    labels = data.get("category_values") or ([data["type"]] if data.get("type") else [])
    if set(labels) - OUTDOOR_CATEGORIES - BROAD_CATEGORIES:
        return None
    if name in {"粉巷", "嘉会坊", "观光旅游大道/环岛东路"}:
        return "public_outdoor_streets"
    return next((scope for pattern, scope in OUTDOOR_NAMES if pattern.search(name)), None)


EXPANDED_OUTDOOR_BASIS = "public_outdoor_type_reference"
OPEN_PARK_PARENTS = (
    "仙岳公园", "忠仑公园", "白鹭洲公园", "五缘湾湿地公园", "狐尾山公园", "厦门香山公园",
    "兴庆宫公园", "唐城墙遗址公园", "曲江池遗址公园",
)
OPEN_PARK_FEATURE = re.compile(r"(?:亭|木桥|亲水平台|观景台|草坪|花溪|樱花谷|雕像|铜像|石狮|湖|园中园|水上广场|唐诗迷宫)$")
OPEN_PARK_SECTION = re.compile(r"公园(?:[0-9一二三四五六七八九十]+期|[1-9一二三四五六七八九]区)$")
PUBLIC_STREETS = re.compile(r"(?:观光大道|健身步道|亲水步道|海滨步道|滨水步道|骑行道|公共绿道)$")
PUBLIC_WALKWAY_NODE = re.compile(r"(?:健康步道|市政绿道)[\u4e00-\u9fff]{0,8}(?:桥|观景台|观景平台)$")
EXTRA_RESTRICTIONS = re.compile(
    r"经停|施工|已关闭|已停业|暂停营业|闭园|小区|度假村|主题乐园|营地|售票|专用|办公|"
    r"出海|帆船|游船|温泉|滑道|展馆|纪念馆|博物馆|影视城|营业部|运动培训|体育场|球场"
)


def expanded_public_scope(name, data):
    """Recognize a public place with a compatible category and a scoped name."""
    name = unicodedata.normalize("NFKC", name).strip()
    if RESTRICTED_CONTEXT.search(name) or EXTRA_RESTRICTIONS.search(name):
        return None
    labels = data.get("category_values") or ([data["type"]] if data.get("type") else [])
    if set(labels) - OUTDOOR_CATEGORIES - BROAD_CATEGORIES:
        return None
    if PUBLIC_STREETS.search(name) or name in {"环岛路", "环岛东路", "中山路步行街"}:
        return "public_outdoor_streets"
    if PUBLIC_WALKWAY_NODE.search(name) or name in {"曾厝垵牌坊", "集美学村牌坊"}:
        return "public_path_or_viewpoint"
    if name in {"湖里街道侨文化园", "街心花园"} or OPEN_PARK_SECTION.search(name):
        return "public_park_grounds"
    if (any(parent in name and name.index(parent) + len(parent) < len(name) for parent in OPEN_PARK_PARENTS)
            and OPEN_PARK_FEATURE.search(name)):
        return "public_park_outdoor_feature"
    if re.fullmatch(r"[^()]+广场\([^()]{1,24}(?:路|街)\)", name):
        return "public_square"
    return None


def positive_price(value):
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


def free_admission(city, name, payload, public_spaces):
    row = payload["raw_record"]
    data = payload["data"]
    access = payload["access"]
    key = city, row["id"]
    published = public_spaces.get(key)
    if published is not None:
        expected_name, evidence = published
        if expected_name != name:
            raise ValueError(f"Public space source identity changed: {key}")
        if data.get("price") in (None, 0):
            return evidence
        return None
    outdoor = public_outdoor_scope(name, data)
    if ((access["planning_position_available"] or outdoor) and str(row.get("price")).strip() in {"0", "0.0"}
            and data.get("price") == 0):
        scope = {
            "鼓浪屿": "outdoor_streets_excludes_ferry_and_ticketed_venues",
            "厦门大学(思明校区)": "basic_admission_subject_to_visitor_access_policy",
        }.get(name, "basic_admission_excludes_paid_services")
        return {"amount_cny": 0, "scope": scope, "basis": "explicit_zero_in_verified_snapshot",
                "source_locator": payload["source_locator"]}
    if outdoor and not any(positive_price(v) for v in (data.get("price"), row.get("price"))):
        return {
            "amount_cny": 0, "scope": outdoor, "basis": "user_approved_public_outdoor_admission",
            "approved_on": "2026-11-23", "price_status": "assumed_for_reference",
            "covers": "basic access to the named outdoor public area",
            "excludes": ["ticketed facilities", "reservations or access restrictions", "ferries", "paid activities"],
            "source_locator": payload["source_locator"],
        }
    expanded = expanded_public_scope(name, data)
    if expanded and not any(positive_price(v) for v in (data.get("price"), row.get("price"))):
        return {
            "amount_cny": 0, "scope": expanded, "basis": EXPANDED_OUTDOOR_BASIS,
            "approved_on": "2026-11-24", "price_status": "assumed_for_reference",
            "covers": "basic access to the named outdoor public area",
            "excludes": ["ticketed facilities", "reservations or access restrictions", "ferries", "paid activities"],
            "source_locator": payload["source_locator"],
        }
    return None


DISCOVERY_LOCATION_GAPS = {"name", "source_id", "verified_position", "valid_position", "poi_name_link", "lat", "lon"}
DISCOVERY_EXCLUDED_TYPES = {"酒吧", "培训机构", "室内展位", "购物相关场所", "餐饮相关场所"}
DISCOVERY_EXCLUDED_NAMES = re.compile(
    r"建设中|暂停营业|永久关闭|核心保护区|贵宾通道|管理处|运营管理中心|"
    r"母婴室|公共厕所|售票处|专用通道|餐厅|酒馆|咖啡专门店|"
    r"AMOY BAGEL MUSEUM|草莓夫妇丨厦门菜|^欣颖水族$|安全理事会",
    re.IGNORECASE,
)
DISCOVERY_FIELDS = ("price", "opentime", "endtime", "recommendmintime", "recommendmaxtime")


def attraction_discovery(name, payload, restrictions):
    """Admit verified locations with incomplete visit information for discovery."""
    if not present(name) or DISCOVERY_EXCLUDED_NAMES.search(name):
        return None
    access, data = payload["access"], payload["data"]
    if (not access["planning_position_available"] or not access["poi_name_match"]
            or DISCOVERY_LOCATION_GAPS.intersection(restrictions)):
        return None
    labels = data.get("category_values") or ([data["type"]] if data.get("type") else [])
    if DISCOVERY_EXCLUDED_TYPES.intersection(labels):
        return None
    gaps = [field for field in DISCOVERY_FIELDS if field in restrictions]
    if not gaps:
        return None
    return {
        "basis": "matched_snapshot_attraction",
        "price_status": "unknown" if data.get("price") is None else "stored_snapshot_reference",
        "missing_visit_fields": gaps,
        "source_locator": payload["source_locator"],
    }


def hotel_evidence(name, payload, observations):
    row = payload["raw_record"]
    historical = None
    price = payload["data"].get("price")
    if (row.get("price_status") == "historical_source_reference_conditional"
            and number(price, 0.01) and present(row.get("historical_price_source_url"))
            and present(row.get("historical_price_evidence_id"))):
        historical = {
            "amount_cny": price, "unit_scope": row.get("historical_price_unit_status"),
            "price_scope": row.get("historical_price_scope"), "observed_at": row.get("historical_price_observed_at") or None,
            "checkin": row.get("historical_price_checkin") or None, "checkout": row.get("historical_price_checkout") or None,
            "source_url": row["historical_price_source_url"], "evidence_id": row["historical_price_evidence_id"],
            "source_locator": payload["source_locator"],
        }
    rooms = []
    for expected_name, evidence in observations.get(row["id"], ()):
        if normalized_name(expected_name) != normalized_name(name):
            raise ValueError(f"Historical room source identity differs for {row['id']}: {expected_name} vs {name}")
        rooms.append(evidence)
    if historical is None and not rooms:
        return None
    return {"display_price_observation": historical, "room_or_offer_observations": rooms}


def build_references(quarantined, profile, local_observations):
    public = read(PUBLIC_SPACES)
    public_spaces = {
        (city, source_id): (name, {
            "amount_cny": 0, "scope": scope, "basis": "named_public_area_sources",
            "observed_on": public["observed_on"], "evidence_manifest_sha256": digest(PUBLIC_SPACES),
            "sources": [public["sources"][source] for source in sources],
        })
        for city, source_id, name, scope, sources in public["places"]
    }
    observations = room_observations(profile, local_observations)
    refs, rows, admissions = {}, [], Counter()
    for row_id, city, kind, name, reasons_raw, payload_raw in quarantined:
        if kind not in ("attraction", "accommodation"):
            continue
        payload = json.loads(payload_raw)
        restrictions = json.loads(reasons_raw)
        admission = free_admission(city, name, payload, public_spaces) if kind == "attraction" else None
        if kind == "attraction":
            info = admission or attraction_discovery(name, payload, restrictions)
        else:
            info = hotel_evidence(name, payload, observations) if city == "厦门" else None
        if info is None:
            continue
        data = payload["data"].copy()
        position_available = payload["access"]["planning_position_available"] and "verified_position" not in restrictions
        if not position_available:
            data["lat"] = None
            data["lon"] = None
        if admission is not None:
            data["price"] = 0
            payload["admission_evidence"] = admission
            if admission["basis"] == EXPANDED_OUTDOOR_BASIS:
                discovery = attraction_discovery(name, payload, restrictions)
                if discovery:
                    payload["discovery_evidence"] = discovery
            admissions[city, admission["basis"]] += 1
        elif kind == "attraction":
            payload["discovery_evidence"] = info
        else:
            # Prices and bed configurations are tied to observations and rooms.
            # The top-level fields cannot represent a compatible price/bed pair.
            data["price"] = None
            data["numbed"] = None
            payload["hotel_reference"] = info
        payload.update(data=data, use_scope="reference_only", budgeting_allowed=False, scheduling_allowed=False,
                       planning_restrictions=restrictions, position_available=position_available)
        refs[row_id] = (row_id, city, kind, name, dump(payload))
        rows.append((city, kind, name, info))
    return refs, rows, admissions


def summary_of(snapshot, existing, quarantine, rows, admissions):
    references = Counter((city, kind) for city, kind, _, _ in rows)
    hotels = [info for _, kind, _, info in rows if kind == "accommodation"]
    rooms = [e for h in hotels for e in h["room_or_offer_observations"]]
    discovered = [(city, info) for city, kind, _, info in rows
                  if kind == "attraction" and info["basis"] == "matched_snapshot_attraction"]
    discovery_counts = Counter((city, info["price_status"]) for city, info in discovered)
    return {
        "snapshot": snapshot,
        "catalog_browse": sum(existing.values()) + len(rows),
        "reference_only": len(rows),
        "pending": sum(quarantine.values()) - len(rows),
        "free_attraction_references_by_source": [
            {"city": city, "basis": basis, "count": count} for (city, basis), count in sorted(admissions.items())
        ],
        "xiamen_historical_hotel_display_prices": sum(bool(h["display_price_observation"]) for h in hotels),
        "xiamen_hotels_with_any_price_evidence": sum(
            h["display_price_observation"] is not None or any(
                e["observation"].get("price_cny_per_room_stay") or e["observation"].get("reference_starting_price")
                or e["observation"].get("price_cny") for e in h["room_or_offer_observations"]
            ) for h in hotels
        ),
        "xiamen_hotel_room_offer_observations": dict(Counter(e["scope"] for e in rooms)),
        "counts": [
            {"city": city, "kind": kind, "catalog": existing[city, kind],
             "reference_only": references[city, kind], "pending": quarantine[city, kind] - references[city, kind]}
            for city, kind in sorted(existing.keys() | quarantine.keys())
        ],
        "attraction_discovery_by_city": [
            {"city": city, "price_status": price_status, "count": count}
            for (city, price_status), count in sorted(discovery_counts.items())
        ],
        "free_attraction_references": [
            {"city": c, "name": name, **info}
            for c, kind, name, info in rows if kind == "attraction" and "amount_cny" in info
        ],
    }


def is_new_outdoor_admission(current, proposed):
    if proposed is None or proposed[:4] != current[:4] or current[2] != "attraction":
        return False
    before, after = json.loads(current[-1]), json.loads(proposed[-1])
    admission = after.pop("admission_evidence", {})
    if (before.get("admission_evidence") or admission.get("basis") != EXPANDED_OUTDOOR_BASIS
            or before["data"].get("price") not in (None, 0) or after["data"].get("price") != 0):
        return False
    after["data"]["price"] = before["data"]["price"]
    return before == after


def import_batch(db, snapshot, profile, local_observations, check):
    from shorttrip_cloud.db import execute_batch

    with db.tx() as cur:
        cur.execute("SELECT id FROM st_snapshot WHERE id=%s FOR UPDATE", (snapshot,))
        if cur.fetchone() is None:
            raise ValueError(f"Missing source snapshot: {snapshot}")
        cur.execute("SELECT value FROM st_meta WHERE key='city_catalog_v20_xian_xiamen'")
        if cur.fetchone() is None:
            raise ValueError("Import the verified V20 catalog before extending its references")
        cur.execute("SELECT id, city, kind, name, reasons, payload FROM st_catalog_quarantine WHERE snapshot_id=%s AND id LIKE %s ORDER BY id",
                    (snapshot, "v20:%"))
        quarantine_rows = cur.fetchall()
        quarantine = Counter((row[1], row[2]) for row in quarantine_rows)
        cur.execute("SELECT city, kind, count(*) FROM st_catalog_record WHERE snapshot_id=%s AND id LIKE %s GROUP BY 1,2",
                    (snapshot, "v20:%"))
        existing = Counter({(c, k): n for c, k, n in cur.fetchall()})
        refs, rows, admissions = build_references(quarantine_rows, profile, local_observations)
        if not refs:
            raise ValueError("No validated references produced")
        summary = summary_of(snapshot, existing, quarantine, rows, admissions)
        if check:
            return summary
        cur.execute("SELECT id, city, kind, name, payload FROM st_catalog_reference WHERE snapshot_id=%s", (snapshot,))
        current = cur.fetchall()
        existing_ids = {row[0] for row in current}
        upgrades = []
        for row in current:
            proposed = refs.get(row[0])
            if proposed == row:
                continue
            if not is_new_outdoor_admission(row, proposed):
                raise ValueError(f"Existing catalog reference would change or disappear: {row[0]}")
            upgrades.append((proposed[-1], snapshot, row[0]))
        if upgrades:
            execute_batch(cur, "UPDATE st_catalog_reference SET payload=%s WHERE snapshot_id=%s AND id=%s", upgrades)
        additions = sorted(refs[row_id] for row_id in refs.keys() - existing_ids)
        if additions:
            execute_batch(cur, "INSERT INTO st_catalog_reference (snapshot_id,id,city,kind,name,payload) VALUES (%s,%s,%s,%s,%s,%s)",
                          [(snapshot, *row) for row in additions])
        if additions or upgrades:
            cur.execute("SELECT id, city, kind, name, payload FROM st_catalog_reference WHERE snapshot_id=%s", (snapshot,))
            current = cur.fetchall()
        if len(current) != len(refs) or set(current) != set(refs.values()):
            raise ValueError("Catalog reference read-back mismatch")
        cur.execute("SELECT value FROM st_meta WHERE key=%s", (RECEIPT,))
        stored = cur.fetchone()
        encoded = dump(summary)
        if stored is None:
            cur.execute("INSERT INTO st_meta (key, value) VALUES (%s,%s)", (RECEIPT, encoded))
        elif stored != (encoded,):
            prior = json.loads(stored[0])
            if not (additions or upgrades) or prior.get("reference_only") != len(existing_ids):
                raise ValueError("Existing catalog reference receipt differs")
            cur.execute("UPDATE st_meta SET value=%s WHERE key=%s", (encoded, RECEIPT))
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--hotel-observations", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    release = args.release.resolve()
    sys.path[:0] = [str(release), str(release / "combined version_personalized")]
    from chinatravel.environment.sandbox.v20 import COMMIT, PROFILE, verify
    from shorttrip_cloud.config import load
    from shorttrip_cloud.db import Database

    snapshot = COMMIT[:7]
    profile = release / "ShortTrip/artifacts/data" / snapshot / "sandbox_profiles" / PROFILE
    verify(profile)
    db = Database(load())
    try:
        if not args.check:
            db.ensure_schema()
        summary = import_batch(db, snapshot, profile, args.hotel_observations, args.check)
    finally:
        db.close()
    report = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
