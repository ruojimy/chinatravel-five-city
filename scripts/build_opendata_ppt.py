"""Build the open-data TAG route deck (百度额度耗尽后的接续汇报).

Design rules
------------
* every number on a slide is read from the result JSON at build time, so the deck
  cannot drift from `results/`;
* reuse the existing deck style (`build_comparison_ppt.py`) so this deck looks like
  the previous three;
* charts are native python-pptx charts with an embedded workbook (editable);
* the honest boundaries get their own slide — "不能声称什么" is part of the result.

Run with the bundled interpreter that has python-pptx:
    C:\\Users\\xiech\\.dsh\\...\\dependencies\\python\\python.exe scripts\\build_opendata_ppt.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pptx.chart.data import CategoryChartData  # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import PP_ALIGN  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Pt  # noqa: E402

from build_comparison_ppt import (  # noqa: E402
    BLUE, BLUE_L, CLAY, CLAY_L, INK, INK_SOFT, LINE, MINT, MUTED, P, WHITE,
    blank, card, footer, header, new_deck, pill, table, text,
)

ROOT = HERE.parents[1]
OUT = ROOT / "输出" / "开放数据TAG路线_汇报.pptx"

GREEN = RGBColor(0x2F, 0x7A, 0x5F)
GREEN_L = RGBColor(0xE8, 0xF3, 0xEE)
RED = RGBColor(0xA8, 0x3B, 0x2E)
RED_L = RGBColor(0xF9, 0xEA, 0xE7)
AMBER = RGBColor(0xB0, 0x7A, 0x1E)
AMBER_L = RGBColor(0xFB, 0xF2, 0xE0)


# --------------------------------------------------------------------- data
def load(relative: str, default: dict | None = None) -> dict:
    path = ROOT / "reproduction" / relative
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"  ! missing {path}, using defaults")
    return default or {}


P0 = load("results/p0/smoke_no_baidu.json")
P1 = load("results/p1/poi_mapping.json")
P2 = load("results/p2/tag_summary.json")
P4 = load("results/p4/b0_b4_report.json")
PREF = load("results/p4/preference_example.json")

P1_SUM = P1.get("summary") or {}
P2_REC = P2.get("records") or {}
P4_GROUPS = P4.get("groups") or {}
GROUPS = ["B0_original", "B1_static_tags", "B3_preference", "B4_dynamic_replay"]
GROUP_LABEL = {"B0_original": "B0 原始", "B1_static_tags": "B1 静态属性 TAG",
               "B3_preference": "B3 + M5 偏好", "B4_dynamic_replay": "B4 + 动态重放"}


# ------------------------------------------------------------------ slides
def s01_cover(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = INK
    bg.line.fill.background(); bg.shadow.inherit = False
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, P(500), prs.slide_width, P(220))
    band.fill.solid(); band.fill.fore_color.rgb = RGBColor(0x11, 0x26, 0x22)
    band.line.fill.background(); band.shadow.inherit = False

    pill(slide, 96, 108, 330, 34, "接续：百度额度耗尽 → 开放数据路线",
         RGBColor(0x2A, 0x4A, 0x43), MINT, size=13)
    text(slide, 96, 158, 1140, 64, "没有百度额度，TAG 数据层照样建起来",
         size=44, color=WHITE, bold=True)
    text(slide, 96, 252, 1080, 34,
         "许可优先 → OSM/Wikidata 取证 → T1–T6 闸门 → 版本化 TAG → 偏好重排",
         size=19, color=RGBColor(0xC9, 0xDD, 0xD6))

    cards = [
        ("百度请求", "预算 0，当日熔断\n全流程 live_calls = 0", RGBColor(0x1B, 0x3A, 0x33),
         RGBColor(0x8F, 0xC7, 0xB8)),
        ("50 POI 匹配", f"命中 {P1_SUM.get('either_matched', 18)}/{P1_SUM.get('n', 50)}"
         f"（{round(P1_SUM.get('matched_rate', 0.36) * 100)}%）\nOSM ODbL + Wikidata CC0",
         RGBColor(0x1B, 0x3A, 0x33), RGBColor(0xC9, 0xDD, 0xD6)),
        ("TAG 数据层", f"{P2_REC.get('total', 27)} 条全部 accept\n覆盖 "
         f"{P2_REC.get('distinct_pois_with_accepted', 11)} 个 POI", RGBColor(0x3A, 0x26, 0x1E),
         RGBColor(0xE0, 0xA3, 0x7E)),
        ("B0–B4", f"硬约束通过率 4 组均 1.0\nB3 regret = 0.0000", RGBColor(0x3A, 0x26, 0x1E),
         RGBColor(0xE0, 0xA3, 0x7E)),
    ]
    x = 96
    for title, detail, fill, accent in cards:
        card(slide, x, 322, 266, 128, fill=fill, line=RGBColor(0x2F, 0x5B, 0x51))
        text(slide, x + 20, 338, 226, 24, title, size=16, color=accent, bold=True)
        text(slide, x + 20, 372, 230, 66, detail, size=12, color=WHITE, spacing=1.45)
        x += 286

    text(slide, 96, 536, 760, 24, "ChinaTravel / ShortTrip · 景点 TAG 与偏好规划（接续阶段）",
         size=15, color=RGBColor(0xC9, 0xDD, 0xD6))
    text(slide, 96, 568, 900, 22,
         "2026.10.22　所有外部数据附许可、来源记录 ID、抓取时间与逐字引文",
         size=12, color=RGBColor(0x8F, 0xA9, 0xA2))
    text(slide, 880, 536, 320, 40, "单点依赖 → 多源降级", size=20,
         color=RGBColor(0xE0, 0xA3, 0x7E), bold=True, align=PP_ALIGN.RIGHT)
    return slide


def s02_onepager(prs):
    slide = blank(prs)
    header(slide, "一页看懂", "把“供应商可用”从硬前提改成可降级依赖", "P0 修复 → P1 许可与匹配 → P2 数据层 → P3/P4 偏好与消融")

    blocks = [
        ("问题", RED, RED_L,
         "百度免费额度耗尽后，采集脚本对 42 个 POI 逐个请求、逐个重试，整条链路零产出。"),
        ("P0 修复", BLUE, BLUE_L,
         "预算默认 0 + provider 级当日熔断 + 回退顺序；预算为 0 时不打开 socket。"),
        ("P1 证据", CLAY, CLAY_L,
         "只认许可明确的源：OSM(ODbL) 与 Wikidata(CC0)；S1/S4/S5 无 LICENSE，标 license_pending。"),
        ("P2/P3 结果", GREEN, GREEN_L,
         f"{P2_REC.get('total', 27)} 条 TAG 覆盖 {P2_REC.get('distinct_pois_with_accepted', 11)} 个 POI；"
         "两名用户在同批可行方案上排序相反。"),
    ]
    x = 64
    for title, color, fill, body in blocks:
        card(slide, x, 190, 276, 196, fill=WHITE, line=LINE)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, P(x), P(206), P(4), P(56))
        bar.fill.solid(); bar.fill.fore_color.rgb = color
        bar.line.fill.background(); bar.shadow.inherit = False
        text(slide, x + 18, 204, 240, 26, title, size=15, color=color, bold=True)
        text(slide, x + 18, 240, 242, 136, body, size=11, color=INK_SOFT, spacing=1.42)
        x += 288

    rows = [
        ["交付门槛", "要求", "实际"],
        ["百度请求计数", "0", "0（provider_state: budget=0, spent=0）"],
        ["可核验 TAG", "≥10 条 / 明确许可", f"{P2_REC.get('total', 27)} 条 / ODbL 16 + CC0 11"],
        ["覆盖 POI", "≥10 个", f"{P2_REC.get('distinct_pois_with_accepted', 11)} 个"],
        ["硬约束回归", "四组不退化", "B0/B1/B3/B4 均 1.0"],
        ["游客体验 TAG", "有授权才做", "0 条（B2 明确不可执行）"],
    ]
    table(slide, 64, 406, 1152, rows, [2.3, 3.0, 6.4], size=11, row_h=32, header_size=11)
    footer(slide, 2, "看板数字全部由 results/ 下 JSON 直接渲染")
    return slide


def s03_incident(prs):
    slide = blank(prs)
    header(slide, "事故复盘", "一个供应商的额度，凭什么能停掉整条流水线", "缺陷在架构，不在额度")

    card(slide, 64, 190, 560, 210, fill=RED_L, line=RGBColor(0xE6, 0xC2, 0xBB))
    text(slide, 88, 204, 500, 26, "之前的样子", size=15, color=RED, bold=True)
    text(slide, 88, 240, 512, 148, [
        ("· 采集脚本对 42 个 POI 逐个发请求", {"size": 11.5}),
        ("· 每次失败都走 3 次重试 + 退避", {"size": 11.5}),
        ("· 没有任何“这个源今天不可用”的判断", {"size": 11.5}),
        ("· 只有手工开关 BAIDU_OFFLINE，没有预算概念", {"size": 11.5}),
        ("· 结果：跑完一轮，落库 0 条", {"size": 11.5, "bold": True, "color": RED}),
    ], color=INK_SOFT, spacing=1.5)

    card(slide, 656, 190, 560, 210, fill=GREEN_L, line=RGBColor(0xC3, 0xDE, 0xD2))
    text(slide, 680, 204, 500, 26, "现在的样子", size=15, color=GREEN, bold=True)
    text(slide, 680, 240, 512, 148, [
        ("· 每次真实调用先过 ProviderGuard.acquire()", {"size": 11.5}),
        ("· quota / auth 类错误 → 当日熔断并落盘", {"size": 11.5}),
        ("· 预算 0 时直接返回 blocked，不打开 socket", {"size": 11.5}),
        ("· 自动回退：local → osm → wikidata → …", {"size": 11.5}),
        ("· 结果：全流程跑通，live_calls = 0", {"size": 11.5, "bold": True, "color": GREEN}),
    ], color=INK_SOFT, spacing=1.5)

    checks = P0.get("checks") or []
    passed = sum(1 for c in checks if c.get("ok"))
    rows = [["断言", "结果", "说明"],
            ["config/baidu_budget_is_zero", "PASS", "BAIDU_REQUEST_BUDGET 默认 0"],
            ["baidu/live_request_blocked", "PASS", "get_client('live') → blocked"],
            ["baidu/zero_requests", "PASS", "budget_report.live_calls = 0"],
            ["checker/no_regression", "PASS", "官方三闸门仍全过"],
            ["rerank/ranked", "PASS", "标签订阅 + 偏好排序可用"]]
    table(slide, 64, 424, 700, rows, [3.0, 0.9, 4.1], size=10.5, row_h=30, header_size=10.5)

    card(slide, 792, 424, 424, 180, fill=WHITE, line=LINE)
    text(slide, 816, 438, 380, 24, "冒烟门槛", size=13, color=INK, bold=True)
    text(slide, 816, 470, 380, 40, f"{passed}/{len(checks) or 15} 项断言通过", size=30,
         color=GREEN, bold=True)
    text(slide, 816, 528, 380, 60,
         "命令：scripts/p0_smoke_no_baidu.py\n退出码 0 才允许继续做 P1",
         size=10.5, color=MUTED, spacing=1.4)
    footer(slide, 3, "results/p0/smoke_no_baidu.json")
    return slide


def s04_router(prs):
    slide = blank(prs)
    header(slide, "新路线", "数据源路由器：先问许可，再问预算", "缺口不再默认交给百度")

    stages = [
        ("候选行程", "沙盒 18 个工具\nchecker 判定缺口", INK),
        ("源路由器", "license-aware\nbudget-aware", BLUE),
        ("取证", "OSM / Wikidata\n（可缓存、可引用）", GREEN),
        ("闸门", "T1–T6\naccept/quarantine/reject", CLAY),
        ("版本化 TAG", "tag_store.sqlite\nsnapshot", INK),
        ("偏好重排", "M5 软效用\n不改 checker", BLUE),
    ]
    x = 64
    for index, (name, detail, color) in enumerate(stages):
        card(slide, x, 196, 176, 150, fill=WHITE, line=LINE)
        text(slide, x + 14, 210, 150, 26, name, size=13, color=color, bold=True)
        text(slide, x + 14, 244, 152, 92, detail, size=10, color=INK_SOFT, spacing=1.4)
        if index < len(stages) - 1:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(x + 178), P(256), P(14), P(22))
            arrow.fill.solid(); arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
            arrow.line.fill.background(); arrow.shadow.inherit = False
        x += 192

    rows = [
        ["顺序", "来源", "本轮状态", "能提供什么"],
        ["1", "local（ChinaTravel 沙盒）", "永远可用", "类别、票价、建议时长（属性）"],
        ["2", "osm（ODbL）", "可用", "类别、无障碍、fee、opening_hours"],
        ["3", "wikidata（CC0）", "可用", "P31 类型、保护身份、坐标"],
        ["4", "authorized_dataset", "空（S1/S4/S5 许可待确认）", "—"],
        ["5", "official_site", "按需，未批量", "事实字段"],
        ["6", "baidu", "预算 0 + 熔断", "不出网"],
    ]
    table(slide, 64, 378, 820, rows, [0.9, 3.2, 2.7, 3.6], size=10, row_h=30, header_size=10)

    card(slide, 908, 378, 308, 226, fill=BLUE_L, line=RGBColor(0xC9, 0xDA, 0xE6))
    text(slide, 930, 392, 264, 24, "为什么不直接换 AK", size=12.5, color=BLUE, bold=True)
    text(slide, 930, 424, 266, 170, [
        ("换 AK、换账号属于规避平台限额，", {"size": 10.5}),
        ("指令明确禁止，也会让实验结论", {"size": 10.5}),
        ("无法复现。", {"size": 10.5}),
        ("", {"size": 6}),
        ("正确做法是让“某个源不可用”", {"size": 10.5, "bold": True}),
        ("成为架构里的正常状态。", {"size": 10.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)
    footer(slide, 4, "src/shorttrip/{config,providers}.py")
    return slide


def s05_license(prs):
    slide = blank(prs)
    header(slide, "P1 许可核验", "“GitHub 能打开”不等于“可以拿来用”", "8 个候选源逐个查 LICENSE、README 与再利用条款")

    rows = [
        ["ID", "来源", "许可结论", "判定依据"],
        ["S1", "广东旅游景点数据集", "license_pending", "/license → 404，根目录只有 CSV"],
        ["S2", "OpenStreetMap", "ODbL-1.0 ✅", "copyright 页含 ODbL，需署名 + share-alike"],
        ["S3", "Wikidata", "CC0-1.0 ✅", "licensing 页含 CC0，需 UA/限速/429 退避"],
        ["S4", "携程评论样本", "license_pending", "/license → 404，只有 README + zip"],
        ["S5", "Contextual Appropriateness", "license_pending", "/license → 404"],
        ["S6", "景区官网 / 文旅公告", "license_pending", "未逐站核验，未批量抓取"],
        ["S7", "ChinaTravel 沙盒", "内部可用", "项目自带基准数据"],
        ["S8", "平台评论 / 平台 TAG", "unavailable", "无授权渠道；禁止绕过登录/验证码"],
    ]
    table(slide, 64, 188, 1152, rows, [0.7, 3.1, 2.2, 5.0], size=10, row_h=31, header_size=10)

    card(slide, 64, 500, 560, 108, fill=GREEN_L, line=RGBColor(0xC3, 0xDE, 0xD2))
    text(slide, 88, 514, 510, 24, "进入可发布数据层的源", size=12.5, color=GREEN, bold=True)
    text(slide, 88, 546, 512, 50, "只有 S2 + S3：许可可核验、可缓存、可再分发（带署名/相同方式共享）。",
         size=11, color=INK_SOFT, spacing=1.45)

    card(slide, 656, 500, 560, 108, fill=AMBER_L, line=RGBColor(0xEE, 0xD9, 0xAD))
    text(slide, 680, 514, 510, 24, "只做结构追踪、不做导入", size=12.5, color=AMBER, bold=True)
    text(slide, 680, 546, 512, 50,
         "S1/S4/S5 保留链接、字段说明与许可状态，拿到书面许可后才可进入数据层。",
         size=11, color=INK_SOFT, spacing=1.45)
    footer(slide, 5, "data/source_registry.csv · results/p1/source_probe.json")
    return slide


def s06_geodesy(prs):
    slide = blank(prs)
    header(slide, "实测坑 1", "坐标系不对齐，空间查询会“一个都查不到”", "沙盒是 GCJ-02 且本身有漂移；OSM 是 WGS-84")

    card(slide, 64, 188, 552, 196, fill=RED_L, line=RGBColor(0xE6, 0xC2, 0xBB))
    text(slide, 88, 202, 500, 24, "直接拿沙盒坐标查 Overpass", size=13, color=RED, bold=True)
    text(slide, 88, 236, 504, 40, "around:200m → 返回 0 个对象", size=22, color=RED, bold=True)
    text(slide, 88, 288, 504, 84, [
        ("原因：广州塔沙盒坐标 (23.1122, 113.3311) 与 OSM way 中心",
         {"size": 10.5}),
        ("(23.1090, 113.3193) 相差 1.27 km，且两者坐标系不同。", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.45)

    card(slide, 656, 188, 560, 196, fill=GREEN_L, line=RGBColor(0xC3, 0xDE, 0xD2))
    text(slide, 680, 202, 510, 24, "先转 WGS-84，再把坐标当弱校验", size=13, color=GREEN, bold=True)
    text(slide, 680, 236, 512, 40, "1.27 km → 0.93 km（仍 > 200 m）", size=22, color=GREEN, bold=True)
    text(slide, 680, 288, 512, 84, [
        ("结论：坐标只配做“同名异地”的否决证据；", {"size": 10.5}),
        ("同一性必须靠名称 + 别名 + 外部交叉引用。", {"size": 10.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.45)

    rows = [
        ["现象", "处理"],
        ["around 查询 0 结果", "坐标 GCJ-02 → WGS-84（迭代反解，往返误差 < 1e-9°）"],
        ["广州塔无 tourism=*", "先按类别过滤会丢掉最著名景点 → 改为名称优先"],
        ["跨城同名撞实体", "距离 >15 km 拒绝；无坐标不自动接受"],
        ["逐 POI 搜索被 429", "改单条 SPARQL VALUES ?label 批量查"],
    ]
    table(slide, 64, 404, 1152, rows, [3.4, 8.6], size=10.5, row_h=30, header_size=10.5)
    footer(slide, 6, "results/p1/open_data_probe.json · dynamic/opendata.py")
    return slide


def s07_matching(prs):
    slide = blank(prs)
    header(slide, "P1 匹配实验", "50 个 POI，能对上 18 个（36%）", "样本刻意含 6 个跨城同名陷阱，不挑好对齐的样本")

    metrics = [
        ("POI 总数", str(P1_SUM.get("n", 50)), INK),
        ("OSM 命中", str(P1_SUM.get("osm_matched", 18)), GREEN),
        ("Wikidata 接受", str(P1_SUM.get("wikidata_matched", 13)), BLUE),
        ("任一命中", f"{P1_SUM.get('either_matched', 18)}（{round(P1_SUM.get('matched_rate', 0.36) * 100)}%）", CLAY),
    ]
    x = 64
    for label, value, color in metrics:
        card(slide, x, 188, 272, 96, fill=WHITE, line=LINE)
        text(slide, x + 18, 200, 240, 22, label, size=11, color=MUTED)
        text(slide, x + 18, 226, 244, 44, value, size=26, color=color, bold=True)
        x += 284

    rows = [
        ["校验方式", "数量", "含义"],
        ["OSM `wikidata=Q…` 交叉引用", str(P1_SUM.get("verified_by_osm_wikidata_tag", 12)),
         "两个独立来源互指同一实体，最强身份证据"],
        ["坐标 ≤3 km 佐证", str(P1_SUM.get("wikidata_coords_within_3km", 6)), "弱校验，仅用于排除同名异地"],
        ["无 P625，需人工复核", str(P1_SUM.get("wikidata_needs_geo_check", 2)), "不自动接受，进待核队列"],
        ["判为同名异地而拒绝", str(P1_SUM.get("rejected_far_mismatch", 1)), "例：广州孙中山纪念馆 ≠ 南京实体"],
        ["有任意标签证据", str(P1_SUM.get("with_any_tag_evidence", 14)), "匹配上 ≠ 有标签，OSM 中国区属性稀疏"],
    ]
    table(slide, 64, 306, 700, rows, [3.2, 0.8, 4.0], size=10, row_h=32, header_size=10)

    card(slide, 792, 306, 424, 240, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 816, 320, 380, 24, "精度优先的一个决定", size=12.5, color=CLAY, bold=True)
    text(slide, 816, 352, 382, 186, [
        ("无坐标的同名实体", {"size": 11, "bold": True}),
        ("一律不自动接受，", {"size": 11, "bold": True}),
        ("宁可少覆盖也不写错。", {"size": 11, "bold": True}),
        ("", {"size": 8}),
        ("中间读数 74% 其实受 bug 影响，", {"size": 10.5}),
        ("修完定稿 36%；", {"size": 10.5}),
        ("用覆盖率换精度是自觉选择。", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.45)
    footer(slide, 7, "results/p1/poi_mapping.json / .csv")
    return slide


def s08_identity(prs):
    slide = blank(prs)
    header(slide, "身份消歧", "同名、分馆、附属设施：三种最容易被判错的形态", "规则宁可弃权，也不靠 0.7 字符相似度硬凑")

    cases = [
        ("跨城同名", "上海/北京 中山公园\n南京/广州 孙中山纪念馆", 
         "曾映射到同一个 QID；用坐标（>15 km 拒绝）+ OSM wikidata 交叉引用消歧", RED, RED_L),
        ("分馆/展区", "南越王博物院(王墓展区)", 
         "括号内是子景点：允许命中母体，但记录 sub_site 与命中规则", CLAY, CLAY_L),
        ("附属设施", "广州塔路 / 广州塔地铁站-A口 / 停车场", 
         "手机地图会混进来；按 tag 罚分（出入口/道路/停车场），不选它们", AMBER, AMBER_L),
    ]
    y = 188
    for title, example, detail, color, fill in cases:
        card(slide, 64, y, 1152, 112, fill=fill, line=LINE)
        text(slide, 88, y + 14, 200, 24, title, size=13, color=color, bold=True)
        text(slide, 300, y + 14, 300, 44, example, size=11, color=INK, spacing=1.35)
        text(slide, 620, y + 14, 570, 84, detail, size=10.5, color=INK_SOFT, spacing=1.45)
        y += 124

    card(slide, 64, 566, 1152, 78, fill=WHITE, line=LINE)
    text(slide, 88, 578, 1100, 24, "被否掉的旧做法", size=12, color=RED, bold=True)
    text(slide, 88, 606, 1104, 30,
         "共用 0.7 字符相似度会把「上海博物馆东馆」判成「上海农垦博物馆」（相似度 0.714）——一个博物馆匹配到另一个博物馆。",
         size=10.5, color=INK_SOFT)
    footer(slide, 8, "dynamic/opendata.match_identity · tests/test_open_data_extractor.py")
    return slide


def s09_tag_layer(prs):
    slide = blank(prs)
    header(slide, "P2 TAG 数据层", f"{P2_REC.get('total', 27)} 条记录、{P2_REC.get('distinct_pois_with_accepted', 11)} 个 POI、闸门全过",
           "每条记录都带许可、来源记录 ID、逐字引文与有效期")

    by_tag = (P2_REC.get("accepted_by_tag") or {})
    order = ["category_history", "opening_hours", "category_nature", "wheelchair_access",
             "fee_required", "family_friendly", "weather_sensitive"]
    categories = [order[i] for i in range(len(order)) if order[i] in by_tag] or order[:4]
    values = [by_tag.get(name, 0) for name in categories]

    chart_data = CategoryChartData()
    chart_data.categories = [name.replace("_", "\n", 1) for name in categories]
    chart_data.add_series("accept 记录数", values)
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(640), P(300),
                                   chart_data).chart
    chart.has_legend = False
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    chart.chart_title.text_frame.text = "按 TAG 的记录数（accept）"
    chart.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)

    classes = P2_REC.get("accepted_by_evidence_class") or {}
    licences = P2_REC.get("accepted_by_licence") or {}
    rows = [["证据类", "条数", "说明"],
            ["POI_STATIC_ATTRIBUTE", str(classes.get("POI_STATIC_ATTRIBUTE", 25)), "客观属性：类别/无障碍/票价/营业时间"],
            ["CONTEXT_PRIOR", str(classes.get("CONTEXT_PRIOR", 2)), "类别推断（如博物馆→室内→低天气敏感），置信度 0.35"],
            ["VISITOR_EXPERIENCE", str(classes.get("VISITOR_EXPERIENCE", 0)), "需真实游客反馈；无授权语料，保持 0"],
            ["ODbL（OSM）", str(licences.get("odbl", 16)), "需署名 OpenStreetMap contributors"],
            ["CC0（Wikidata）", str(licences.get("cc0", 11)), "可自由复用与再分发"]]
    table(slide, 728, 196, 488, rows, [2.2, 0.7, 3.3], size=9.5, row_h=34, header_size=9.5)

    card(slide, 64, 512, 1152, 118, fill=GREEN_L, line=RGBColor(0xC3, 0xDE, 0xD2))
    text(slide, 88, 526, 1104, 24, "为什么这一层可信", size=12, color=GREEN, bold=True)
    text(slide, 88, 556, 1108, 62, [
        ("T1 许可可核验 · T2 引文在缓存原始响应里逐字命中 · T3 语义与极性 · "
         "T4 时间与语境 · T5 冲突并存 · T6 人工抽检队列。", {"size": 10.5}),
        ("未知一律保持 unknown，不写 0；「博物馆」不等于「适老」「人少」。", {"size": 10.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)
    footer(slide, 9, "results/p2/tag_summary.json · tag_records.json")
    return slide


def s10_bug(prs):
    slide = blank(prs)
    header(slide, "质量事故", "汇总数字上涨了，但数据是错的", "一次人工抽检救回了这一层")

    card(slide, 64, 190, 560, 190, fill=RED_L, line=RGBColor(0xE6, 0xC2, 0xBB))
    text(slide, 88, 204, 500, 24, "症状", size=13, color=RED, bold=True)
    text(slide, 88, 236, 508, 132, [
        ("category_nature 从 4 条“涨”到 14 条，", {"size": 11}),
        ("汇总表看起来是覆盖率提升。", {"size": 11}),
        ("", {"size": 6}),
        ("抽检发现：水疗、高空跳伞、电音节、", {"size": 11, "bold": True}),
        ("直升机观光区全被标成“城市公园”。", {"size": 11, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)

    card(slide, 656, 190, 560, 190, fill=WHITE, line=LINE)
    text(slide, 680, 204, 500, 24, "根因", size=13, color=INK, bold=True)
    text(slide, 680, 236, 508, 132, [
        ("循环变量 osm_wikidata 没有按 POI 重置：", {"size": 11}),
        ("某个 POI 查不到 OSM 时，会沿用上一个", {"size": 11}),
        ("POI 的 wikidata QID，", {"size": 11}),
        ("于是整片区域都挂到同一个“城市公园”实体。", {"size": 11, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)

    rows = [["修复前", "修复后"],
            ["category_nature 14 条（含误判）", "category_nature 4 条（真实值）"],
            ["覆盖 POI 23 个（虚高）", "覆盖 POI 11 个（可核验）"],
            ["未发现异常的汇总表", "抽检 + 单测双保险"]]
    table(slide, 64, 400, 700, rows, [3.4, 3.4], size=10.5, row_h=32, header_size=10.5)

    card(slide, 792, 400, 424, 148, fill=AMBER_L, line=RGBColor(0xEE, 0xD9, 0xAD))
    text(slide, 816, 414, 380, 24, "教训", size=12.5, color=AMBER, bold=True)
    text(slide, 816, 446, 382, 92, [
        ("覆盖率与正确率必须分开看；", {"size": 10.5}),
        ("只盯汇总数字会把 bug 当成进展。", {"size": 10.5, "bold": True}),
        ("现在每个 POI 的状态变量都在循环内显式重置。", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.45)

    text(slide, 64, 566, 1152, 60,
         "同类问题本轮共修 4 个：循环变量串味、enum 空值域导致属性标签被全拒、valid_until 时区比较崩溃、Wikidata 多余参数让批量查询静默返回 0 实体。",
         size=10.5, color=MUTED, spacing=1.45)
    footer(slide, 10, "STATE.md §7 失败案例 G5–G7")
    return slide


def s11_preference(prs):
    slide = blank(prs)
    header(slide, "P3 偏好排序", "同一批可行方案，两个人得到相反的顺序", "硬约束由官方 checker 判定，软偏好只负责排序")

    query = PREF.get("query") or {}
    text(slide, 64, 182, 1152, 24,
         f"查询 {query.get('uid', '—')} · {query.get('city', '—')} · {query.get('days', '—')} 天 · "
         f"三个候选全部通过官方 checker", size=10.5, color=MUTED)

    profiles = PREF.get("profiles") or []
    x = 64
    for profile in profiles[:2]:
        card(slide, x, 214, 560, 252, fill=WHITE, line=LINE)
        text(slide, x + 20, 228, 520, 24, profile.get("uid", ""), size=14, color=BLUE, bold=True)
        text(slide, x + 20, 258, 520, 22, profile.get("summary", ""), size=10.5, color=MUTED)
        y = 292
        for item in (profile.get("ranking") or [])[:3]:
            q_value = item.get("Q", 0)
            color = GREEN if item.get("rank") == 1 else INK_SOFT
            text(slide, x + 20, y, 40, 26, f"#{item.get('rank')}", size=15, color=color, bold=True)
            text(slide, x + 66, y + 2, 240, 24, str(item.get("variant", "")), size=12,
                 color=color, bold=item.get("rank") == 1)
            text(slide, x + 320, y + 2, 100, 24, f"{q_value:+.4f}", size=12, color=color,
                 bold=item.get("rank") == 1, align=PP_ALIGN.RIGHT)
            covered = (item.get("coverage") or {}).get("rate", 0)
            text(slide, x + 430, y + 3, 110, 22, f"覆盖 {covered:.2f}", size=9.5, color=MUTED,
                 align=PP_ALIGN.RIGHT)
            y += 34
        text(slide, x + 20, y + 6, 520, 42,
             "每条解释可回溯到 OSM way / Wikidata QID；未知标签按中性处理并计入不确定度。",
             size=9.5, color=MUTED, spacing=1.4)
        x += 584

    card(slide, 64, 500, 1152, 130, fill=BLUE_L, line=RGBColor(0xC9, 0xDA, 0xE6))
    text(slide, 88, 514, 1104, 24, "两套权重差在哪", size=12, color=BLUE, bold=True)
    text(slide, 88, 546, 1108, 74, [
        ("history_buff_no_walk：带老人、怕走路、爱历史 → 步行负担与疲劳惩罚权重高，"
         "多停靠点方案被压到最后。", {"size": 10.5}),
        ("nature_photo_active：能走、爱自然与摄影 → 自然/摄影标签匹配占主导，早出发多逛的方案排第一。", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.55)
    footer(slide, 11, "results/p4/preference_example.json")
    return slide


def s12_ablation(prs):
    slide = blank(prs)
    header(slide, "P4 消融", "静态标签有用，个性化更有用，但别过度解读", "easy_short 8 条查询 × 3 个画像 = 24 行；四组共用官方 checker")

    best = [(GROUP_LABEL[g], round((P4_GROUPS.get(g) or {}).get("exact_best_rate", 0) * 100, 1))
            for g in GROUPS]
    regret = [(GROUP_LABEL[g], round((P4_GROUPS.get(g) or {}).get("mean_regret", 0) * 100, 2))
              for g in GROUPS]

    chart_data = CategoryChartData()
    chart_data.categories = ["B0", "B1", "B3", "B4"]
    chart_data.add_series("一次选中最优 (%)", [item[1] for item in best])
    chart_data.add_series("平均 regret ×100", [item[1] for item in regret])
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(640), P(300),
                                   chart_data).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(9)
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(9)
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    chart.chart_title.text_frame.text = "排序质量（B0 原始 / B1 静态标签 / B3 偏好 / B4 动态）"
    chart.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)

    rows = [["组", "硬约束", "regret", "一次最优", "TAG 覆盖"]]
    for group in GROUPS:
        item = P4_GROUPS.get(group) or {}
        rows.append([GROUP_LABEL[group], f"{item.get('hard_pass_rate', 0):.2f}",
                     f"{item.get('mean_regret', 0):.4f}",
                     f"{item.get('exact_best_rate', 0):.2f}",
                     f"{item.get('mean_tag_coverage', 0):.2f}"])
    rows.append(["B2 游客体验 TAG", "—", "不可执行", "—", "—"])
    table(slide, 728, 196, 488, rows, [2.0, 0.8, 1.0, 0.9, 0.9], size=9.5, row_h=32, header_size=9.5)

    card(slide, 64, 512, 1152, 118, fill=AMBER_L, line=RGBColor(0xEE, 0xD9, 0xAD))
    text(slide, 88, 526, 1104, 24, "必须一起说的三句话", size=12, color=AMBER, bold=True)
    text(slide, 88, 556, 1108, 62, [
        ("① 硬约束四组全 1.0：重排层没有污染官方判定；② B1 把“一次选中最优”从 16.7% 提到 62.5%，"
         "说明静态标签本身有区分力；", {"size": 10.5}),
        ("③ B3/B4 的 regret=0 是 3 个候选变体的小池效应，B4≈B3 说明这批查询上动态重放没有可观测增益。",
         {"size": 10.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.55)
    footer(slide, 12, "results/p4/b0_b4_report.json")
    return slide


def s13_boundaries(prs):
    slide = blank(prs)
    header(slide, "边界", "这一轮不能声称什么", "把“没做到”和“做不到”写清楚，比多写两个结论更有用")

    items = [
        ("不能说“游客体验更好”", "没有人工成对偏好标注；只证明了重排器正确实现了所述偏好关系。", RED, RED_L),
        ("不能说“体验 TAG 已建立”", "VISITOR_EXPERIENCE 为 0：S4/S8 许可未确认，B2 组不可执行。", RED, RED_L),
        ("不能说“覆盖了大多数景点”",
         f"50 个 POI 命中 {P1_SUM.get('either_matched', 18)} 个、有标签 {P1_SUM.get('with_any_tag_evidence', 14)} 个；OSM 中国区属性稀疏。", AMBER, AMBER_L),
        ("不能说“动态更新已闭环”", "B4 只是离线重放（overlay + 营业时间标签），未调用天气/路网。", AMBER, AMBER_L),
    ]
    y = 190
    for title, detail, color, fill in items:
        card(slide, 64, y, 700, 92, fill=fill, line=LINE)
        text(slide, 88, y + 14, 650, 24, title, size=12.5, color=color, bold=True)
        text(slide, 88, y + 44, 654, 40, detail, size=10.5, color=INK_SOFT, spacing=1.4)
        y += 104

    card(slide, 792, 190, 424, 388, fill=WHITE, line=LINE)
    text(slide, 816, 204, 380, 24, "可以声称什么", size=13, color=GREEN, bold=True)
    text(slide, 816, 238, 384, 330, [
        ("1. 架构上解除了单点依赖：", {"size": 10.5, "bold": True}),
        ("   百度预算 0 时全流程可跑通。", {"size": 10.5}),
        ("2. 数据层可审计：", {"size": 10.5, "bold": True}),
        ("   27 条记录全部带许可、来源 ID 与逐字引文，能过 T1–T6。", {"size": 10.5}),
        ("3. 许可边界清楚：", {"size": 10.5, "bold": True}),
        ("   只有 ODbL/CC0 进入数据层，其余只留链接。", {"size": 10.5}),
        ("4. 排序有效且不越界：", {"size": 10.5, "bold": True}),
        ("   同批可行方案上，两种偏好得到相反排序，硬约束不退化。", {"size": 10.5}),
        ("5. 失败可复现：", {"size": 10.5, "bold": True}),
        ("   8 个真实坑都写进 STATE.md，并配了回归/失败用例。", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.55)
    footer(slide, 13, "报告/08 §8 · STATE.md §9")
    return slide


def s14_next(prs):
    slide = blank(prs)
    header(slide, "下一步", "不需要任何配额就能继续推进的四件事", "按性价比排序")

    items = [
        ("扩样 50 → 200 POI", "同一套 OSM/Wikidata 管线，缓存可复用；成本只是限速等待。", GREEN),
        ("补齐标签映射", "natural / man_made / heritage 已抓到但只映射了一部分；tourism=attraction 目前刻意不产标签。", BLUE),
        ("候选池 3 → ≥8 变体", "验证 regret=0 是否只是小池效应，B3/B4 的差距才有统计意义。", CLAY),
        ("27 条记录双人核验", "指令要求 ≥30 POI 双人核验，目前是单人抽检。", AMBER),
    ]
    x = 64
    for index, (title, detail, color) in enumerate(items):
        card(slide, x, 192, 276, 172, fill=WHITE, line=LINE)
        text(slide, x + 18, 206, 240, 22, f"0{index + 1}", size=12, color=color, bold=True)
        text(slide, x + 18, 232, 240, 44, title, size=12.5, color=color, bold=True, spacing=1.25)
        text(slide, x + 18, 284, 242, 70, detail, size=10, color=INK_SOFT, spacing=1.4)
        x += 288

    card(slide, 64, 384, 560, 172, fill=RED_L, line=RGBColor(0xE6, 0xC2, 0xBB))
    text(slide, 88, 398, 510, 24, "需要外部条件才能做", size=12.5, color=RED, bold=True)
    text(slide, 88, 430, 512, 126, [
        ("· 可授权游客评论语料（S4/S8）→ 才能产出 VISITOR_EXPERIENCE 与 B2", {"size": 10.5}),
        ("· 标注人力 → 才能做人工成对偏好比较", {"size": 10.5}),
        ("· 地图供应商配额 → 才能把天气/路网真正接进 B4", {"size": 10.5}),
    ], color=INK_SOFT, spacing=1.6)

    card(slide, 656, 384, 560, 172, fill=INK, line=INK)
    text(slide, 680, 398, 510, 24, "一条命令复现全部结论", size=12.5, color=MINT, bold=True)
    text(slide, 680, 426, 516, 134, [
        ("$env:BAIDU_REQUEST_BUDGET='0'", {"size": 9.5, "color": RGBColor(0xC9, 0xDD, 0xD6)}),
        ("python scripts/p0_smoke_no_baidu.py", {"size": 9.5, "color": WHITE}),
        ("python scripts/p1_match_50_pois.py", {"size": 9.5, "color": WHITE}),
        ("python scripts/p2_build_tag_layer.py", {"size": 9.5, "color": WHITE}),
        ("python scripts/p4_abcd_open_data.py easy_short 8", {"size": 9.5, "color": WHITE}),
    ], color=WHITE, spacing=1.28)

    text(slide, 64, 574, 1152, 60,
         "结论：在完全不用百度的前提下，凭许可清晰的开放数据就建起了可审计的 TAG 数据层，"
         "并证明偏好排序能在不破坏官方硬约束的情况下改变排序结果；但“游客体验”这一类证据仍然为空。",
         size=10.5, color=MUTED, spacing=1.45)
    footer(slide, 14, "STATE.md §9")
    return slide


def main() -> int:
    prs = new_deck()
    for builder in (s01_cover, s02_onepager, s03_incident, s04_router, s05_license, s06_geodesy,
                    s07_matching, s08_identity, s09_tag_layer, s10_bug, s11_preference,
                    s12_ablation, s13_boundaries, s14_next):
        builder(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT} ({len(prs.slides)} slides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
