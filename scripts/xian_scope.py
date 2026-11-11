"""Scope tiers for Xi'an cross-city transport, with provenance of each tier.

Three reference city sets, all taken from real files in this repository:

* NATIVE10 - ChinaTravel's original 10 cities. Its intercity_transport is a
  fully connected graph: train 10x9=90 files (single-city view, Chengdu =
  18 files / 407 rows); flight 9 cities x 8 directions x 10 = 720 rows
  (Suzhou has no airport; single-city view = 160 rows). Verified against
  ChinaTravel/chinatravel/environment/database/intercity_transport/.
* EXPANSION30 - the earliest expansion dataset, data/expansion_v1_20261022/
  collection_manifest.json -> city_windows (30 windows, created 2026-10-22).
  报告/静态数据库5城市扩张.md and 报告/12_扩容数据完整合约与独立模型验证.md
  both describe "30 个新增城市". This is the user-approved extra city set.
* Everything else - real records captured from aggregator boards / airline
  pages, but outside both reference sets. Kept, and explicitly labelled.

Policy (user instruction 2026-11-08): cross-city records to the expansion
cities may be KEPT, but must be DOCUMENTED. So scope_check never rejects a
record; it returns a tier that the quality report must break out by number,
source and A-grade count.
"""
from __future__ import annotations

import re

# ChinaTravel original 10 cities
NATIVE10 = ("北京", "成都", "重庆", "广州", "杭州", "南京", "上海", "深圳", "苏州", "武汉")
FLIGHT_NATIVE = tuple(c for c in NATIVE10 if c != "苏州")  # no airport in sandbox

# Earliest expansion dataset: data/expansion_v1_20261022/collection_manifest.json
EXPANSION30 = (
    "西安", "天津", "郑州", "长沙", "青岛", "济南", "厦门", "福州", "昆明",
    "贵阳", "南宁", "合肥", "南昌", "沈阳", "大连", "哈尔滨", "长春", "石家庄",
    "太原", "兰州", "乌鲁木齐", "呼和浩特", "海口", "三亚", "无锡", "宁波",
    "温州", "珠海", "佛山", "东莞",
)
EXPANSION_EXTRA = tuple(c for c in EXPANSION30 if c != "西安")

TIER_DOCS = {
    "native10": "西安 <-> ChinaTravel 原生 10 城（沙盒 intercity_transport 全互联口径）",
    "expansion30": "西安 <-> 最早扩展集 data/expansion_v1_20261022 的额外 29 城；用户 2026-11-08 明确允许保留，但必须说明",
    "other_city": "西安 <-> 不在原生 10 城也不在扩展 30 城的城市（聚合看板/航司页真实航线）；保留并单独标注",
    "no_xian": "两端都不含西安（采集时混入的其它城市对）；保留并标注为范围异常",
    "not_cross_city": "非跨城类别，不适用范围分层",
}

IATA = {
    "XIY": "西安", "PEK": "北京", "PKX": "北京", "NAY": "北京",
    "SHA": "上海", "PVG": "上海", "CAN": "广州", "SZX": "深圳",
    "CTU": "成都", "TFU": "成都", "CKG": "重庆", "HGH": "杭州",
    "NKG": "南京", "WUH": "武汉", "SZV": "苏州",
}
ENGLISH = {
    "xianyang": "西安", "xi'an": "西安", "beijing": "北京", "daxing": "北京",
    "capital": "北京", "shanghai": "上海", "hongqiao": "上海", "pudong": "上海",
    "guangzhou": "广州", "baiyun": "广州", "shenzhen": "深圳", "baoan": "深圳",
    "chengdu": "成都", "chongqing": "重庆", "hangzhou": "杭州",
    "xiaoshan": "杭州", "nanjing": "南京", "wuhan": "武汉",
    "jiangbei": "重庆", "tianfu": "成都", "shuangliu": "成都",
    "lukou": "南京", "tianhe": "武汉", "tianjin": "天津", "binhai": "天津",
    "xiamen": "厦门", "jinan": "济南", "kunming": "昆明", "urumqi": "乌鲁木齐",
    "aksu": "阿克苏", "hohhot": "呼和浩特", "harbin": "哈尔滨",
    "qingdao": "青岛", "jiaodong": "青岛", "zhuhai": "珠海", "wuxi": "无锡",
    "ningbo": "宁波", "lishe": "宁波", "changsha": "长沙", "sanya": "三亚",
    "phoenix": "三亚", "guiyang": "贵阳", "longdongbao": "贵阳",
    "yantai": "烟台", "penglai": "烟台", "yulin": "榆林", "hainan": "海南",
}
CHINESE_AIRPORT = {
    "咸阳": "西安", "西安": "西安", "大兴": "北京", "首都": "北京",
    "虹桥": "上海", "浦东": "上海", "白云": "广州", "宝安": "深圳",
    "双流": "成都", "天府": "成都", "江北": "重庆", "萧山": "杭州",
    "禄口": "南京", "天河": "武汉", "胶东": "青岛", "揭阳": "揭阳",
}
STATION = {
    "清河": "北京", "汉口": "武汉", "武昌": "武汉", "成都东": "成都",
    "上海虹桥": "上海", "杭州西": "杭州", "南京南": "南京", "广州南": "广州",
    "深圳北": "深圳", "重庆北": "重庆", "重庆西": "重庆",
    "西安北": "西安", "西安东": "西安", "北京西": "北京", "北京南": "北京",
    "上海南": "上海", "杭州东": "杭州", "苏州北": "苏州",
    "厦门北": "厦门", "长沙南": "长沙", "青岛北": "青岛",
}


def city_of(endpoint) -> str:
    """Map a station/airport string to a canonical city, or OUT."""
    s = str(endpoint or "").strip()
    low = s.lower()
    for city in sorted(set(NATIVE10 + EXPANSION30), key=len, reverse=True):
        if city in s:
            return city
    for key, city in CHINESE_AIRPORT.items():
        if key in s:
            return city
    for key, city in STATION.items():
        if key in s:
            return city
    for code in re.findall(r"\b([A-Z]{3})\b", s):
        if code in IATA:
            return IATA[code]
    for key, city in ENGLISH.items():
        if key in low:
            return city
    return "OUT"


def scope_check(kind: str, data: dict) -> dict:
    """Return a documented scope tier. Never rejects - see module docstring."""
    if kind not in ("train", "flight"):
        return {"tier": "not_cross_city", "from_city": None, "to_city": None,
                "pair": None, "documented": True, "note": TIER_DOCS["not_cross_city"]}
    a = city_of(data.get("From"))
    b = city_of(data.get("To"))
    other = b if a == "西安" else (a if b == "西安" else None)
    native = FLIGHT_NATIVE if kind == "flight" else NATIVE10
    if other is None:
        tier = "no_xian"
    elif other in native:
        tier = "native10"
    elif other in EXPANSION_EXTRA:
        tier = "expansion30"
    else:
        tier = "other_city"
    return {"tier": tier, "from_city": a, "to_city": b, "pair": f"{a}->{b}",
            "documented": True, "note": TIER_DOCS[tier]}
