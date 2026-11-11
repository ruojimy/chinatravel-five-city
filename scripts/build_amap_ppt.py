"""Build the Amap-driven dynamic-update deck (main storyline: 高德接入 + 动态更新)."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Pt
from pptx.dml.color import RGBColor

from build_comparison_ppt import (  # noqa: E402
    BLUE, BLUE_L, CLAY, CLAY_L, INK, INK_SOFT, LINE, MINT, MUTED, P, WHITE,
    blank, card, footer, header, new_deck, pill, table, text,
)

OUT = HERE.parents[1] / "输出" / "高德动态沙盒更新_主线汇报.pptx"


def s1_cover(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = INK
    bg.line.fill.background(); bg.shadow.inherit = False
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, P(500), prs.slide_width, P(220))
    band.fill.solid(); band.fill.fore_color.rgb = RGBColor(0x11, 0x26, 0x22)
    band.line.fill.background(); band.shadow.inherit = False

    pill(slide, 96, 112, 250, 34, "主线：高德接入 + 动态更新", RGBColor(0x2A, 0x4A, 0x43), MINT, size=13)
    text(slide, 96, 172, 1120, 64, "缺数据时，让沙盒自己长出来", size=44, color=WHITE, bold=True)
    text(slide, 96, 248, 1040, 34, "缺口检测 → 高德取证 → 八道质量闸门 → 版本化注入 → 重新求解", size=19, color=RGBColor(0xC9, 0xDD, 0xD6))

    cards = [
        ("数据源", "高德 Web 服务 5 类接口\n3 把 key 额度轮换", RGBColor(0x1B, 0x3A, 0x33), RGBColor(0x8F, 0xC7, 0xB8)),
        ("质量", "8 道闸门 + 引文锚定\naccept / quarantine / reject", RGBColor(0x1B, 0x3A, 0x33), RGBColor(0xC9, 0xDD, 0xD6)),
        ("注入", "10 个活着的工具实例\n派生缓存同步失效", RGBColor(0x3A, 0x26, 0x1E), RGBColor(0xE0, 0xA3, 0x7E)),
        ("证据", "南越王 2/3 → 3/3\n省博检出 3 处冲突", RGBColor(0x3A, 0x26, 0x1E), RGBColor(0xE0, 0xA3, 0x7E)),
    ]
    x = 96
    for title, detail, fill, accent in cards:
        card(slide, x, 322, 266, 122, fill=fill, line=RGBColor(0x2F, 0x5B, 0x51))
        text(slide, x + 20, 338, 226, 24, title, size=16, color=accent, bold=True)
        text(slide, x + 20, 370, 228, 58, detail, size=12, color=WHITE, spacing=1.45)
        x += 286

    text(slide, 96, 536, 760, 24, "Lingwei Cao  ·  Yuhang Ji  ·  Churui Xie", size=15, color=RGBColor(0xC9, 0xDD, 0xD6))
    text(slide, 96, 568, 900, 22, "2026.10.17   所有外部数据均附 URL、抓取时间与原文引文", size=12, color=RGBColor(0x8F, 0xA9, 0xA2))
    text(slide, 880, 536, 320, 40, "静态 → 可更新", size=20, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True, align=PP_ALIGN.RIGHT)
    return slide


def s2_problem(prs):
    slide = blank(prs)
    header(slide, "为什么需要它", "沙盒是一次性快照，而城市每天都在变", "三种缺口最常见，且都直接让“可行方案”变“无解”")

    items = [
        ("新开场馆", "上海博物馆东馆（2024 开馆）\n北京大运河博物馆（2023）", "沙盒 3 张表 + POI 表全无记录", CLAY),
        ("改名/迁移", "南越王博物院（2021 年合并更名）\n原名也已不在表内", "模型记得它，判分器却接不了地", RGBColor(0x8A, 0x4A, 0x2A)),
        ("信息陈旧", "某馆“全天开放”\n高德实测 09:00–21:00", "未知值被当成已知，方案秒变乐观", RGBColor(0x6E, 0x4A, 0x8A)),
    ]
    x = 64
    for title, detail, impact, color in items:
        card(slide, x, 190, 372, 208, fill=WHITE, line=LINE)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, P(x), P(206), P(4), P(60))
        bar.fill.solid(); bar.fill.fore_color.rgb = color
        bar.line.fill.background(); bar.shadow.inherit = False
        text(slide, x + 20, 204, 330, 26, title, size=16, color=color, bold=True)
        text(slide, x + 20, 240, 334, 56, detail, size=11.5, color=INK_SOFT, spacing=1.35)
        text(slide, x + 20, 306, 334, 24, "后果", size=11, color=MUTED, bold=True)
        text(slide, x + 20, 330, 334, 56, impact, size=11.5, color=INK, spacing=1.35)
        x += 396

    card(slide, 64, 424, 1152, 112, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 88, 438, 1100, 26, "于是问题变成：能不能让模型在“找不到数据”时，主动出去找，并且保证找回来的东西可信？", size=13.5, color=CLAY, bold=True)
    text(
        slide,
        88,
        470,
        1100,
        56,
        [
            ("三个约束条件：① 不能破坏沙盒（基准要可比）；② 数据要能过官方 checker（不能只过我们自己的检查）；③ 用户要看得到来源。", {"size": 11.5}),
            ("这三条决定了后面的“overlay + 闸门 + 引文”设计。", {"size": 11.5, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )

    text(slide, 64, 560, 1150, 24, "这三类缺口不是我们编的：前两个是真实场馆，第三个是在广东省博物馆上实测出来的。", size=12, color=MUTED)
    footer(slide, 2, "报告/06 §1–2")
    return slide


def s3_pipeline(prs):
    slide = blank(prs)
    header(slide, "主线", "七阶段流水线：从“缺口”到“能用的新沙盒”", "每一阶段都留下可复核的产物（请求、证据、判定、版本）")

    steps = [
        ("① 检测缺口", "checker 报 missing_key_data\n或 POI 不在表里\n→ DataRequest"),
        ("② 高德取证", "v5 place/text + business\n每条带 URL/时间/摘要"),
        ("③ 结构化抽取", "确定性抽取（不靠 LLM）\n坐标/类型/营业时间"),
        ("④ 质量闸门", "8 道硬/软关\naccept/quarantine/reject"),
        ("⑤ 版本落库", "SQLite overlay\n沙盒 CSV 一字不改"),
        ("⑥ 在线注入", "广播到 10 个工具实例\n失效派生缓存"),
        ("⑦ 重新求解", "同一 query 重规划\n仍无解才说“冲突”"),
    ]
    x = 64
    for index, (name, detail) in enumerate(steps):
        card(slide, x, 192, 152, 176, fill=WHITE, line=LINE)
        text(slide, x + 12, 206, 130, 44, name, size=11.5, color=CLAY, bold=True, spacing=1.15)
        text(slide, x + 12, 256, 130, 104, detail, size=9.5, color=INK_SOFT, spacing=1.4)
        if index < 6:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(x + 154), P(270), P(14), P(22))
            arrow.fill.solid(); arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
            arrow.line.fill.background(); arrow.shadow.inherit = False
        x += 166

    rows = [
        ["阶段", "产物", "落在哪"],
        ["② 取证", "Evidence（正文 + URL + 时间 + sha256）", "data/evidence_cache/"],
        ["③④ 抽取与闸门", "CandidateRecord + 8 条 GateResult", "results/dynamic_evidence/"],
        ["⑤ 版本", "sandbox_version（如 sb-20261017T065102）", "data/sandbox_overlay.sqlite"],
        ["⑦ 重规划", "修复前后 hard 通过数对比", "results/dynamic_update/"],
    ]
    table(slide, 64, 396, 700, rows, [1.4, 3.6, 2.4], size=10.5, row_h=34, header_size=11)

    card(slide, 792, 396, 424, 170, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 816, 410, 380, 24, "一句话概括", size=13, color=INK, bold=True)
    text(
        slide,
        816,
        440,
        380,
        116,
        [
            ("沙盒不再是一次性快照，", {"size": 12}),
            ("而是一个“可被证据修订、", {"size": 12}),
            ("且每次修订都留版本”的活数据层。", {"size": 12, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.5,
    )
    footer(slide, 3, "src/shorttrip/dynamic/（7 个模块）")
    return slide


def s4_why_amap(prs):
    slide = blank(prs)
    header(slide, "数据源", "为什么是高德：一个接口拿到坐标、类型、营业时间", "中文场景的事实标准，且字段是结构化的")

    rows = [
        ["候选源", "能拿到", "权威度", "结论"],
        ["高德 Web 服务", "名称/类型/经纬度/营业时间/电话/官网", "0.92", "主力"],
        ["Wikipedia (zh)", "正文（常含开放时间/票价）", "0.75", "补充正文与票价"],
        ["Wikidata", "坐标、官网、实体 ID", "0.85", "坐标交叉校验"],
        ["OSM / Nominatim", "名称、坐标、POI 类别", "0.60", "低成本存在性验证"],
        ["LLM（V4.1）", "无引文的“记忆”", "0.30", "只做抽取，不能单独采信"],
    ]
    table(slide, 64, 190, 720, rows, [1.9, 3.2, 0.9, 1.6], size=11, row_h=38, header_size=11.5)

    card(slide, 812, 190, 404, 148, fill=WHITE, line=LINE)
    text(slide, 836, 204, 360, 24, "高德返回的真实字段", size=12.5, color=INK, bold=True)
    text(
        slide,
        836,
        234,
        360,
        96,
        [
            ("name: 南越王博物院(王墓展区)", {"size": 10, "font": "Consolas"}),
            ("type: 科教文化服务;博物馆;博物馆", {"size": 10, "font": "Consolas"}),
            ("location: 113.269853,23.126878", {"size": 10, "font": "Consolas"}),
            ("opentime_week: 周二至周日 09:00-17:30…", {"size": 10, "font": "Consolas"}),
        ],
        color=INK_SOFT,
        spacing=1.5,
    )

    card(slide, 812, 352, 404, 152, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 836, 366, 360, 24, "为什么权威度给 0.92", size=12.5, color=CLAY, bold=True)
    text(
        slide,
        836,
        396,
        360,
        100,
        [
            ("· 结构化字段，不依赖 LLM 解析", {"size": 11.5}),
            ("· 与用户手机上的地图同源", {"size": 11.5}),
            ("· 有 tel/website 可二次核验", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.5,
    )

    text(slide, 64, 452, 720, 120, "补充说明：DeepSeek 这个账号没有 web-search 接口（/search 与 web_search tool 均不存在），所以“联网取证”落在地图与百科上；LLM 只负责把非结构化正文抽成字段，且每个字段必须附原文引文。", size=11.5, color=INK_SOFT, spacing=1.4)
    footer(slide, 4, "results/amap_probe.json · report 06 §8")
    return slide


def s5_api(prs):
    slide = blank(prs)
    header(slide, "接口", "五类接口，各有分工", "全部已实测可用（infocode 10000）")

    rows = [
        ["接口", "关键返回", "我们用它做什么"],
        ["v5/place/text（show_fields=business）", "name / type / location / opentime_week / tel", "主力：坐标 + 类型 + 营业时间"],
        ["v3/place/detail", "biz_ext.opentime2 / website / alias", "官网与别名（辅助同一性判定）"],
        ["v3/geocode/geo", "formatted_address / location / adcode", "名称歧义时二次定位"],
        ["v3/direction/walking、transit/integrated", "距离 / 时长 / 票价", "校验沙盒合成路网（G8）"],
        ["v3/weather/weatherInfo", "weather / temperature / reporttime", "降雨 → 改室内扰动"],
    ]
    table(slide, 64, 190, 1152, rows, [3.4, 3.4, 3.0], size=11, row_h=40, header_size=11.5)

    card(slide, 64, 424, 556, 128, fill=WHITE, line=LINE)
    text(slide, 88, 438, 500, 24, "额度：3 把 key 轮换", size=13, color=INK, bold=True)
    text(slide, 88, 468, 500, 76, "遇到 10003/10004/10021/10044（日额度/并发/权限）自动切下一把重试；网络异常也 fallthrough。批量抓取不会因单 key 打满中断。", size=11.5, color=INK_SOFT, spacing=1.4)

    card(slide, 660, 424, 556, 128, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 438, 500, 24, "一个必须记住的坑", size=13, color=CLAY, bold=True)
    text(slide, 684, 468, 500, 76, "高德 location 是 lon,lat，沙盒是 lat,lon。第一版没交换，导致 POI 落到城市外 → G4 几何关直接 reject。现在显式交换并写进字段名注释。", size=11.5, color=INK_SOFT, spacing=1.4)

    text(slide, 64, 568, 1150, 24, "接口能力已经覆盖“新开/改名/陈旧”三类缺口所需的全部字段。", size=12, color=MUTED)
    footer(slide, 5, "scripts/probe_amap.py · report 06 §8.1")
    return slide


def s6_extract(prs):
    slide = blank(prs)
    header(slide, "抽取", "把高德的自由文本变成沙盒字段", "三条确定性规则，替代“让 LLM 猜”")

    rules = [
        ("① 营业时间取众数", "opentime_week 会枚举节假日例外：\n“周二至周日 09:00-17:30…7/27-8/31 09:00-18:00”\n→ 取出现次数最多的时段作为常规时间", "09:00 / 17:30"),
        ("② 类型映射到标签", "type_path 是“大类;中类;小类”：\n“科教文化服务;博物馆;博物馆”\n→ 按关键词表映射到沙盒标签", "博物馆/纪念馆"),
        ("③ 坐标显式换序", "location 字符串是 lon,lat，\n沙盒 DataFrame 是 lat,lon\n→ 解析后交换，并保留原串作为引文", "23.1269 / 113.2699"),
    ]
    x = 64
    for title, detail, result in rules:
        card(slide, x, 190, 372, 208, fill=WHITE, line=LINE)
        text(slide, x + 20, 206, 334, 26, title, size=14, color=INK, bold=True)
        text(slide, x + 20, 242, 334, 96, detail, size=11, color=INK_SOFT, spacing=1.4)
        text(slide, x + 20, 348, 334, 24, "→ " + result, size=12.5, color=CLAY, bold=True)
        x += 396

    card(slide, 64, 424, 1152, 96, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 438, 1100, 24, "为什么强调“确定性”：高德给的是结构化 JSON，用正则/规则就够", size=13, color=INK, bold=True)
    text(slide, 88, 468, 1100, 40, "LLM 只在 regex 抽不到时补位（例如维基正文里的票价），且每个字段必须带原文引文，闸门逐字校验——幻觉字段会被直接丢掉。", size=11.5, color=INK_SOFT, spacing=1.35)

    text(slide, 64, 542, 1150, 40, "结果：南越王博物院的营业时间、坐标、类型全部来自高德确定性抽取，只有票价来自维基正文（10 元）。", size=12, color=MUTED, spacing=1.35)
    footer(slide, 6, "src/shorttrip/dynamic/extract.py · report 06 §2")
    return slide


def s7_gates(prs):
    slide = blank(prs)
    header(slide, "质量", "八道闸门：先证明“这条数据可信”，才允许进沙盒", "硬关 fail = reject；软关 fail = 降置信度或隔离")

    rows = [
        ["类别", "闸门", "查什么", "类型"],
        ["来源", "G1 权威性", "至少一个高权威源真返回了内容", "硬"],
        ["同一性", "G2 名称/坐标", "名称相似度（含 alias）+ 坐标落在城市范围", "硬"],
        ["可信性", "G3 引文锚定", "每个字段的引文必须在原文逐字出现", "硬"],
        ["几何", "G4 / G4b", "城市外接框内；多源坐标偏差 ≤ 3 km", "硬 / 软"],
        ["合理性", "G5 取值格式", "开馆 05:00–24:00、票价 0–1000、时长 0.5–8 h", "硬"],
        ["完整性", "G6 必需字段", "该类型必需字段齐全", "软→隔离"],
        ["出处", "S1 / S2", "营业时间有权威出处 / 有官网", "软"],
        ["可执行", "G7 / G8", "与沙盒现有记录冲突 / 真实路网一致性", "软"],
    ]
    table(slide, 64, 190, 800, rows, [1.1, 1.9, 4.0, 1.2], size=10.5, row_h=36, header_size=11)

    card(slide, 892, 190, 324, 176, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 914, 204, 290, 24, "G3 引文锚定（核心）", size=12.5, color=CLAY, bold=True)
    text(slide, 914, 234, 290, 124, [
        ("LLM 说 opentime = 09:00", {"size": 10.5}),
        ("必须给出原文片段：", {"size": 10.5}),
        ("“周二至周日 09:00-17:30”", {"size": 10, "font": "Consolas"}),
        ("闸门回原文做子串校验，", {"size": 10.5}),
        ("对不上 → 丢弃该字段。", {"size": 10.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.45)

    card(slide, 892, 382, 324, 150, fill=WHITE, line=LINE)
    text(slide, 914, 396, 290, 24, "为什么这条最重要", size=12.5, color=INK, bold=True)
    text(slide, 914, 426, 290, 96, "编造一个营业时间，会让 checker 判“可执行”，最后把“数据缺失”伪装成“方案可行”——这是最危险的失败模式。", size=11, color=INK_SOFT, spacing=1.4)

    text(slide, 64, 552, 800, 48, "8 道关里 4 道是硬关。设计取舍：宁可隔离，也不猜；宁可少录一条，也不录错一条。", size=12, color=MUTED, spacing=1.35)
    footer(slide, 7, "src/shorttrip/dynamic/quality.py · report 06 §2")
    return slide


def s8_three_states(prs):
    slide = blank(prs)
    header(slide, "判定", "三态：接受、隔离、拒绝", "四案例实测，全靠真实网络数据")

    rows = [
        ["案例", "判定", "置信度", "关键依据"],
        ["南越王博物院（沙盒缺失）", "accept", "0.95", "高德坐标 + 09:00-17:30；维基补票价 10 元"],
        ["上海博物馆东馆（2024 新开）", "quarantine", "0.66", "只有坐标类型，无营业时间/票价 → 不猜"],
        ["广东省博物馆（沙盒已有）", "quarantine", "0.71", "检出 3 处冲突 + 路网乐观 ×1.34/×1.71"],
        ["凭空编造的场馆", "reject", "0.55", "高德返回别的 POI（相似度 0.23）→ 挡掉"],
    ]
    table(slide, 64, 190, 1152, rows, [3.4, 1.3, 1.0, 4.2], size=11, row_h=42, header_size=11.5)

    states = [
        ("accept", "落库 + 注入，可直接用于规划", RGBColor(0x2A, 0x7A, 0x6A)),
        ("quarantine", "落库但不注入，向用户提示“无法完成核查”", CLAY),
        ("reject", "不落库、不参与任何推断", RGBColor(0x8A, 0x4A, 0x2A)),
    ]
    x = 64
    for name, detail, color in states:
        card(slide, x, 400, 372, 96, fill=WHITE, line=LINE)
        text(slide, x + 20, 412, 200, 24, name, size=13, color=color, bold=True)
        text(slide, x + 20, 442, 334, 44, detail, size=11, color=INK_SOFT, spacing=1.3)
        x += 396

    card(slide, 64, 512, 1152, 84, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(
        slide,
        88,
        526,
        1104,
        56,
        {"inline": [
            ("为什么 0.55 是下限：", {"size": 11.5, "bold": True, "color": INK}),
            ("只要高德路网能连通这个点，就证明“POI 真实存在且可达”，这是独立证据；但字段不全仍不足以 accept。", {"size": 11.5}),
        ]},
        color=INK_SOFT,
    )
    footer(slide, 8, "results/dynamic_update/report_cold.json")
    return slide


def s9_conflict(prs):
    slide = blank(prs)
    header(slide, "证据 ①", "冲突检测：省博在沙盒里是“全天开放”", "这是“缺失值被默认成已知”的现场证据")

    rows = [
        ["字段", "沙盒快照", "高德实测", "处理"],
        ["opentime", "00:00", "09:00", "冲突"],
        ["endtime", "24:00", "21:00", "冲突"],
        ["坐标", "23.1205, 113.3330", "23.1148, 113.3264", "漂移 1.4 km"],
    ]
    table(slide, 64, 210, 620, rows, [1.2, 2.4, 2.2, 1.4], size=11, row_h=40, header_size=11.5)

    card(slide, 712, 190, 504, 200, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 736, 204, 460, 24, "系统怎么处理", size=13, color=CLAY, bold=True)
    text(slide, 736, 236, 460, 144, [
        ("· 不覆盖：新值落 overlay，状态 quarantine", {"size": 11.5}),
        ("· 置信度 0.71（有置信但有冲突）", {"size": 11.5}),
        ("· 等用户/官方页确认后才切换", {"size": 11.5}),
        ("→ 保护了“已确认行程”不被悄悄改掉", {"size": 11.5, "bold": True}),
    ], color=INK_SOFT, spacing=1.55)

    card(slide, 64, 430, 1152, 112, fill=WHITE, line=LINE)
    text(slide, 88, 444, 1100, 26, "为什么这件事值得单独一页", size=13, color=INK, bold=True)
    text(slide, 88, 476, 1100, 56, [
        ("00:00–24:00 是“未知”被编码成“已知”的典型：checker 会认为这个馆任何时候都能进，于是排出“21:30 参观”这种现实中不可能的行程。", {"size": 11.5}),
        ("我们的冲突检测把这个隐性 bug 显性化了，并且给出可核对的证据（高德原文 + 抓取时间）。", {"size": 11.5}),
    ], color=INK_SOFT, spacing=1.4)

    text(slide, 64, 560, 1150, 24, "同类问题可以用同一条闸门批量普查：把沙盒里 00:00–24:00 的记录挑出来重新核验。", size=12, color=MUTED)
    footer(slide, 9, "report 06 §8.3 · report 05 风险表")
    return slide


def s10_inject(prs):
    slide = blank(prs)
    header(slide, "注入", "为什么“改文件”不生效：三个模块各存了一份缓存", "这是整套方案里最容易被低估的工程量")

    layers = [
        ("commonsense_constraint.py", "模块加载时 new 了 Attractions/Restaurants/Accommodations/Poi", RGBColor(0x8A, 0x4A, 0x2A)),
        ("concept_func.py", "_TOOLS_BY_LANG 里又一份", RGBColor(0x8A, 0x4A, 0x2A)),
        ("hard_constraint.py", "_TOOLS_BY_LANG 里第三份", RGBColor(0x8A, 0x4A, 0x2A)),
        ("transportation/apis.py", "_nearest_station_cache（派生）", CLAY),
        ("shorttrip/env.py", "_leg_cache / _place_cache（派生）", CLAY),
    ]
    y = 190
    for name, detail, color in layers:
        card(slide, 64, y, 660, 72, fill=WHITE, line=LINE)
        text(slide, 88, y + 12, 300, 24, name, size=12, color=color, bold=True)
        text(slide, 88, y + 38, 610, 24, detail, size=11, color=INK_SOFT)
        y += 84

    card(slide, 764, 190, 452, 168, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 788, 204, 400, 24, "SandboxBus 做两件事", size=13, color=INK, bold=True)
    text(slide, 788, 234, 400, 116, [
        ("① 广播写入：表类 concat 一行，Poi 类写 dict", {"size": 11.5}),
        ("② 失效派生缓存：地铁最近站、腿部路线", {"size": 11.5}),
        ("实测一次接受会 patch 10 个实例", {"size": 11.5, "bold": True, "color": CLAY}),
    ], color=INK_SOFT, spacing=1.55)

    card(slide, 764, 372, 452, 160, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 788, 386, 400, 24, "两个真实踩坑", size=13, color=CLAY, bold=True)
    text(slide, 788, 416, 400, 108, [
        ("· 漏 patch 一处 → planner 看得到、checker 看不到", {"size": 11}),
        ("· 不失效派生缓存 → goto 永远返回首次的 None", {"size": 11}),
        ("→ 所以“更新沙盒”本质是一次广播 + 一次失效", {"size": 11, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)

    text(slide, 64, 596, 1150, 24, "另外：overlay 是持久层，新进程启动时 rehydrate 会把 active 记录重放一遍（实测恢复 10 个实例）。", size=12, color=MUTED)
    footer(slide, 10, "src/shorttrip/dynamic/bus.py、pipeline.py")
    return slide


def s11_before_after(prs):
    slide = blank(prs)
    header(slide, "效果", "注入前后：从“判不了”到“能规划”", "南越王博物院，冷启动与热启动都验证过")

    rows = [
        ["观察点", "更新前", "更新后"],
        ["attractions_select 查询", "查不到", "查得到"],
        ["goto 到该点的路线", "报错 / 无解", "3 段 metro 可用"],
        ["Is_attractions_correct", "No information found", "通过"],
        ["含该 POI 的查询（硬约束）", "2 / 3，all_ok=false", "3 / 3，all_ok=true"],
    ]
    table(slide, 64, 190, 660, rows, [2.6, 2.2, 2.2], size=11, row_h=40, header_size=11.5)

    card(slide, 752, 190, 464, 168, fill=WHITE, line=LINE)
    text(slide, 776, 204, 410, 24, "冷启动 / 热启动", size=13, color=INK, bold=True)
    text(slide, 776, 234, 410, 116, [
        ("冷启动：rehydrate 0 → 抓取 → accept → patch 10", {"size": 11}),
        ("热启动：rehydrate 10 → 表已可见、schema 已恢复", {"size": 11}),
        ("→ overlay 真的能跨进程恢复", {"size": 11, "bold": True}),
    ], color=INK_SOFT, spacing=1.55)

    card(slide, 752, 372, 464, 150, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 776, 386, 410, 24, "新数据的来源链", size=13, color=CLAY, bold=True)
    text(slide, 776, 416, 410, 96, [
        ("wikipedia_zh（13,394 字正文）→ 票价 10 元", {"size": 10.5, "font": "Consolas"}),
        ("wikidata Q124682045 → 坐标 + 官网", {"size": 10.5, "font": "Consolas"}),
        ("amap B00140USZS → 名称/类型/营业时间", {"size": 10.5, "font": "Consolas"}),
    ], color=INK_SOFT, spacing=1.5)

    text(slide, 64, 552, 1150, 48, "这一页是整个方案的核心证明：外部抓来的数据，最终要能被官方 checker 接受，而不是只被我们自己的脚本接受。", size=12.5, color=INK_SOFT, spacing=1.35)
    footer(slide, 11, "results/dynamic_update/report_cold.json、report_warm.json")
    return slide


def s12_route(prs):
    slide = blank(prs)
    header(slide, "证据 ②", "G8：沙盒路网时间系统性乐观 1.3–1.7 倍", "用高德真实路线量化，而不是靠感觉")

    data = CategoryChartData()
    data.categories = ["南越王 步行", "南越王 公交", "省博 步行", "省博 公交"]
    data.add_series("沙盒 goto", (185.3, 39.7, 193.7, 36.6))
    data.add_series("高德实测", (291.9, 54.2, 271.8, 62.4))
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(660), P(320), data).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(10)
    chart.legend.font.color.rgb = INK_SOFT
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(8.5)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for series, color in zip(plot.series, (BLUE, CLAY)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    chart.value_axis.maximum_scale = 320
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    chart.value_axis.tick_labels.font.size = Pt(9)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.category_axis.tick_labels.font.size = Pt(9)
    chart.category_axis.tick_labels.font.color.rgb = INK

    card(slide, 748, 196, 468, 150, fill=WHITE, line=LINE)
    text(slide, 772, 210, 410, 24, "倍数（高德 / 沙盒）", size=12.5, color=INK, bold=True)
    text(slide, 772, 240, 410, 96, [
        ("南越王：步行 ×1.58  ·  公交 ×1.37", {"size": 12}),
        ("省　　博：步行 ×1.40  ·  公交 ×1.71", {"size": 12}),
        ("→ 合成地铁图没有候车、换乘、绕路", {"size": 11, "color": CLAY, "bold": True}),
    ], color=INK_SOFT, spacing=1.55)

    card(slide, 748, 364, 468, 152, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 772, 378, 410, 24, "于是有了两条校准", size=12.5, color=CLAY, bold=True)
    text(slide, 772, 408, 410, 100, [
        ("① G8 闸门：ratio > 1.25 → route_optimism 并扣分", {"size": 11}),
        ("② 规划：route_slack_factor = 1.3，折成时间余量", {"size": 11}),
        ("→ 只许更严格，不许更乐观", {"size": 11, "bold": True}),
    ], color=INK_SOFT, spacing=1.5)

    text(slide, 64, 540, 660, 56, "意义：一个“沙盒可行”的紧衔接行程，现实中可能赶不上——这是基准可信度问题，必须显式建模。", size=11.5, color=MUTED, spacing=1.35)
    footer(slide, 12, "results/dynamic_update/route_check.json · report 06 §9")
    return slide


def s13_weather(prs):
    slide = blank(prs)
    header(slide, "扩展", "天气与接驳：都已实测可调用", "一个负责“扰动”，一个负责“校准”")

    rows = [
        ["函数", "作用", "实测结果"],
        ["amap_weather(city)", "当前天气 + 是否降水", "广州：多云 30℃，不触发"],
        ["weather_constraint(city)", "降雨时生成“至少一个室内场馆”的 DSL 约束", "不降雨 → 返回 None"],
        ["amap_transit(o, d, city)", "真实公交时长/里程/票价", "省博方向：95.4 min / 22.1 km / 5 元"],
        ["calibrate_sandbox_minutes(s, a)", "用真实时长替换沙盒值，只许更严格", "36.6 → 62.7"],
    ]
    table(slide, 64, 190, 1152, rows, [2.4, 3.6, 3.2], size=11, row_h=42, header_size=11.5)

    card(slide, 64, 404, 556, 132, fill=WHITE, line=LINE)
    text(slide, 88, 418, 500, 24, "为什么把天气做成“约束”而不是“打分”", size=12.5, color=INK, bold=True)
    text(slide, 88, 448, 500, 80, "做成 DSL 约束，就能直接喂给现有 checker：降雨 → 必须至少一个室内场馆。不用改判分器，也不用发明新指标。", size=11, color=INK_SOFT, spacing=1.4)

    card(slide, 660, 404, 556, 132, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 418, 500, 24, "接驳校准的边界", size=12.5, color=CLAY, bold=True)
    text(slide, 684, 448, 500, 80, "只在“校准版本”上替换城际接驳耗时，原沙盒不动；这样既能贴近现实，又保持基准分数可比。", size=11, color=INK_SOFT, spacing=1.4)

    text(slide, 64, 556, 1150, 40, "这两个能力目前是“可调用、已验证”，接进 planner 各约 5 行——放在下一步。", size=12, color=MUTED)
    footer(slide, 13, "src/shorttrip/dynamic/sources.py · report 06 §11")
    return slide


def s14_papers(prs):
    slide = blank(prs)
    header(slide, "方法依据", "这条流水线的每个环节，都有论文撑着", "不是拍脑袋设计，而是把六篇的结构拼起来")

    rows = [
        ["论文", "借来的结构", "落在哪一步"],
        ["ChinaTravel（ICLR'26）", "可执行约束 + 只读沙箱 + 四闸门", "新数据必须过同一套 checker"],
        ["LLM-Modulo / 形式化验证", "生成与验证分离，验证不过就回炉", "LLM 只抽取，闸门裁决；引文即证明义务"],
        ["Personal Travel Solver", "偏好可复用、确认后生效", "新数据带 type/cuisine 供排序"],
        ["TripTide", "扰动感知、最小改动", "数据更新=外部扰动，走同一套修订"],
        ["TravelPlanner", "受控沙箱、可复现", "overlay + 版本 + 证据缓存"],
        ["Revisiting…", "评测陷阱意识（陈旧/缺失被误判）", "三态判定，不把缺数据当不可行"],
    ]
    table(slide, 64, 190, 1152, rows, [2.8, 3.4, 3.4], size=10.5, row_h=38, header_size=11)

    card(slide, 64, 470, 1152, 100, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 484, 1100, 26, "一句话：ChinaTravel 给“可执行判分”，LLM-Modulo 给“生成-验证分离”，", size=12.5, color=INK, bold=True)
    text(slide, 88, 514, 1100, 44, "TravelPlanner/TripTide 给“可复现与最小改动”，PTS 给“画像可复用”，Revisiting 给“能力边界的自觉”。", size=12.5, color=INK_SOFT)
    footer(slide, 14, "report 06 §3")
    return slide


def s15_pitfalls(prs):
    slide = blank(prs)
    header(slide, "复盘", "动态更新路上踩的五个坑", "每一个都留下了日志或修复记录")

    rows = [
        ["坑", "现象", "解法"],
        ["高德 location 是 lon,lat", "POI 落到城市外，G4 直接 reject", "显式换序 + 字段注释"],
        ["高德模糊召回", "编造名称命中近似场馆", "名称相似度 + alias + 阈值 0.7 → reject"],
        ["证据缓存没有版本", "旧结构缓存缺字段，闸门静默跳过", "key 加版本前缀（待做）"],
        ["PowerShell 改中文源码", "UTF-8 被当 ANSI，方法被吞", "改用 .py 补丁脚本"],
        ["NO_PROXY 含 [::1]", "httpx2 报 Invalid port ':1]'", "清空代理变量"],
    ]
    table(slide, 64, 190, 1152, rows, [2.4, 3.6, 3.6], size=11, row_h=42, header_size=11.5)

    card(slide, 64, 434, 556, 132, fill=WHITE, line=LINE)
    text(slide, 88, 448, 500, 24, "最值得记住的一条", size=12.5, color=INK, bold=True)
    text(slide, 88, 478, 500, 80, "“改文件不生效”——三个模块各有一份工具缓存。做动态数据的人必须先看清缓存边界，否则会一直以为数据没抓到。", size=11, color=INK_SOFT, spacing=1.4)

    card(slide, 660, 434, 556, 132, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 448, 500, 24, "过程教训", size=12.5, color=CLAY, bold=True)
    text(slide, 684, 478, 500, 80, "同一轮里两次用 PowerShell 做多行替换把源码写坏。之后统一“写补丁脚本 → 执行 → 校验”，再没翻车。", size=11, color=INK_SOFT, spacing=1.4)

    text(slide, 64, 586, 1150, 24, "这些坑都写进了 README 的“已知限制”，下次接手的人不用再踩一遍。", size=12, color=MUTED)
    footer(slide, 15, "report 06 §8.3 · README 已知限制")
    return slide


def s16_next(prs):
    slide = blank(prs)
    header(slide, "边界与下一步", "四件事，按性价比排序", "不藏问题")

    items = [
        ("别名表收口 G2", "高德模糊召回仍可能命中近似 POI（当前落 quarantine）", "编辑距离 + business.alias + 新名字要第二个独立来源"),
        ("天气/接驳接线", "amap_weather / amap_transit 已验证，未进 planner", "降雨生成室内约束；transit 替换城际接驳（校准版）"),
        ("普查 00:00–24:00", "沙盒里未知值被编码成全天开放", "批量挑出这类记录重核，产出冲突清单"),
        ("离线基准固化", "证据有 7 天缓存，版本随方案落盘", "把某次更新的快照固化成可发布的 split"),
    ]
    y = 190
    for title, why, fix in items:
        card(slide, 64, y, 1152, 104, fill=WHITE, line=LINE)
        text(slide, 88, y + 14, 400, 24, title, size=13, color=CLAY, bold=True)
        text(slide, 88, y + 44, 470, 50, why, size=11, color=INK_SOFT, spacing=1.3)
        arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(576), P(y + 46), P(24), P(22))
        arrow.fill.solid(); arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
        arrow.line.fill.background(); arrow.shadow.inherit = False
        text(slide, 620, y + 14, 570, 24, "下一步", size=11, color=MUTED, bold=True)
        text(slide, 620, y + 44, 570, 50, fix, size=11, color=INK, spacing=1.3)
        y += 120
    footer(slide, 16, "report 06 §11 · README")
    return slide


def s17_conclusion(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = INK
    bg.line.fill.background(); bg.shadow.inherit = False
    pill(slide, 96, 84, 132, 32, "结论", RGBColor(0x2A, 0x4A, 0x43), MINT, size=12)
    text(slide, 96, 136, 1080, 46, "三句话带走", size=32, color=WHITE, bold=True)

    rows = [
        ("沙盒可以变成活数据层", "缺口 → 高德取证 → 八道闸门 → 版本化注入 → 重规划；沙盒 CSV 一字不改，原 split 分数不受影响。"),
        ("质量靠机制而不是模型", "引文锚定 + 多源交叉 + 冲突拦截，让 LLM 只能当抽取器；编造的场馆会被 reject 并给出理由。"),
        ("顺手发现了基准的真问题", "沙盒把未知营业时间写成 00:00–24:00；合成路网时间乐观 1.3–1.7 倍——两者都会让“可行”变乐观。"),
    ]
    y = 208
    for index, (title, detail) in enumerate(rows):
        text(slide, 96, y, 60, 40, f"0{index + 1}", size=24, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True)
        text(slide, 168, y - 2, 420, 32, title, size=20, color=WHITE, bold=True)
        text(slide, 168, y + 34, 1000, 52, detail, size=13, color=RGBColor(0xC9, 0xDD, 0xD6), spacing=1.4)
        y += 142
    text(slide, 96, 648, 1000, 24, "下一步：别名收口 · 天气接驳接线 · 00:00–24:00 普查 · 快照固化", size=12.5, color=RGBColor(0x8F, 0xA9, 0xA2))
    return slide


def main() -> int:
    prs = new_deck()
    s1_cover(prs)
    s2_problem(prs)
    s3_pipeline(prs)
    s4_why_amap(prs)
    s5_api(prs)
    s6_extract(prs)
    s7_gates(prs)
    s8_three_states(prs)
    s9_conflict(prs)
    s10_inject(prs)
    s11_before_after(prs)
    s12_route(prs)
    s13_weather(prs)
    s14_papers(prs)
    s15_pitfalls(prs)
    s16_next(prs)
    s17_conclusion(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT} slides={len(prs.slides)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
