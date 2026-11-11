"""Build the ChinaTravel × ShortTrip comparison deck.

Design language follows the team's earlier course deck (1280x720 grid, dark-green
ink, muted footers) and adds a two-accent system so the comparison reads at a
glance: blue = ChinaTravel, terracotta = ShortTrip Assistant.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).resolve().parents[2] / "输出" / "ChinaTravel与ShortTrip架构对比.pptx"

W, H = 1280, 720
FONT = "Microsoft YaHei"

INK = RGBColor(0x16, 0x30, 0x2B)
INK_SOFT = RGBColor(0x3C, 0x55, 0x4F)
MUTED = RGBColor(0x6B, 0x82, 0x7C)
LINE = RGBColor(0xD7, 0xE3, 0xDE)
PAPER = RGBColor(0xF6, 0xFA, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLUE = RGBColor(0x2F, 0x66, 0x8C)
BLUE_L = RGBColor(0xE7, 0xEF, 0xF5)
CLAY = RGBColor(0xB5, 0x5E, 0x35)
CLAY_L = RGBColor(0xF8, 0xEC, 0xE4)
MINT = RGBColor(0xDE, 0xEC, 0xE6)


def P(px: float) -> Emu:
    return Inches(px / W * 13.3333)


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(13.3333)
    prs.slide_height = Inches(7.5)
    return prs


def blank(prs: Presentation, paper: bool = True):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    if paper:
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = PAPER
        bg.line.fill.background()
        bg.shadow.inherit = False
    return slide


def text(
    slide,
    x: float,
    y: float,
    w: float,
    h: float | None = None,
    content=None,
    *,
    size: float = 18,
    color: RGBColor = INK,
    bold: bool = False,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing: float = 1.18,
    space_after: float = 0,
    font: str = FONT,
):
    if content is None:
        content, h = h, 220
    if h is None:
        h = 220
    box = slide.shapes.add_textbox(P(x), P(y), P(w), P(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    items = content if isinstance(content, (list, tuple)) else [content]
    if isinstance(content, dict) and "inline" in content:
        items = [content]
    for index, item in enumerate(items):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.alignment = align
        para.line_spacing = spacing
        para.space_after = Pt(space_after)
        if isinstance(item, dict) and "inline" in item:
            for body, opts in item["inline"]:
                run = para.add_run()
                run.text = body
                run.font.size = Pt(opts.get("size", size))
                run.font.bold = opts.get("bold", bold)
                run.font.color.rgb = opts.get("color", color)
                run.font.name = opts.get("font", font)
            continue
        if isinstance(item, tuple):
            body, opts = item
        else:
            body, opts = item, {}
        run = para.add_run()
        run.text = body
        run.font.size = Pt(opts.get("size", size))
        run.font.bold = opts.get("bold", bold)
        run.font.color.rgb = opts.get("color", color)
        run.font.name = opts.get("font", font)
    return box


def card(slide, x, y, w, h, fill=WHITE, line=LINE, radius=0.06, line_w=1.0):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, P(x), P(y), P(w), P(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(line_w)
    shape.shadow.inherit = False
    shape.adjustments[0] = radius
    shape.text_frame.word_wrap = True
    return shape


def pill(slide, x, y, w, h, label, fill, color=WHITE, size=12, bold=True):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, P(x), P(y), P(w), P(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    shape.adjustments[0] = 0.5
    frame = shape.text_frame
    frame.word_wrap = False
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = frame.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    run = para.add_run()
    run.text = label
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    return shape


def header(slide, kicker: str, title: str, sub: str | None = None, accent=INK, title_size: float = 30):
    text(slide, 64, 56, 620, 26, kicker, size=13, color=accent, bold=True)
    text(slide, 64, 86, 1120, 46, title, size=title_size, color=INK, bold=True)
    if sub:
        text(slide, 64, 140, 1120, 26, sub, size=15, color=MUTED)


def footer(slide, number: int, note: str = "ChinaTravel × ShortTrip Assistant"):
    line = slide.shapes.add_connector(1, P(64), P(664), P(1216), P(664))
    line.line.color.rgb = LINE
    line.line.width = Pt(0.75)
    text(slide, 64, 676, 900, 20, note, size=11, color=MUTED)
    text(slide, 1160, 672, 56, 22, f"{number:02d}", size=13, color=MUTED, bold=True, align=PP_ALIGN.RIGHT)


def table(slide, x, y, w, rows, col_widths, *, header_fill=INK, zebra=WHITE, size=13, row_h=34, header_size=13):
    height = row_h * len(rows)
    shape = slide.shapes.add_table(len(rows), len(rows[0]), P(x), P(y), P(w), P(height))
    tbl = shape.table
    total = sum(col_widths)
    for index, ratio in enumerate(col_widths):
        tbl.columns[index].width = P(w * ratio / total)
    for r, row in enumerate(rows):
        tbl.rows[r].height = P(row_h)
        for c, cell_text in enumerate(row):
            cell = tbl.cell(r, c)
            cell.margin_left = P(10)
            cell.margin_right = P(8)
            cell.margin_top = P(4)
            cell.margin_bottom = P(4)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if r == 0:
                cell.fill.fore_color.rgb = header_fill
            else:
                cell.fill.fore_color.rgb = zebra if r % 2 else RGBColor(0xEF, 0xF5, 0xF2)
            frame = cell.text_frame
            frame.word_wrap = True
            para = frame.paragraphs[0]
            para.alignment = PP_ALIGN.LEFT
            run = para.add_run()
            run.text = str(cell_text)
            run.font.size = Pt(header_size if r == 0 else size)
            run.font.bold = r == 0
            run.font.color.rgb = WHITE if r == 0 else INK_SOFT
            run.font.name = FONT
    return tbl


# --------------------------------------------------------------------------- 01
def slide_cover(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = INK
    bg.line.fill.background()
    bg.shadow.inherit = False

    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, P(520), prs.slide_width, P(200))
    band.fill.solid()
    band.fill.fore_color.rgb = RGBColor(0x11, 0x26, 0x22)
    band.line.fill.background()
    band.shadow.inherit = False

    pill(slide, 96, 120, 208, 34, "课程项目 · 复现与对比", RGBColor(0x2A, 0x4A, 0x43), MINT, size=13)
    text(slide, 96, 182, 1120, 70, "ChinaTravel  ×  ShortTrip Assistant", size=40, color=WHITE, bold=True)
    text(
        slide,
        96,
        264,
        1000,
        34,
        "一次真实复现、一份架构对比、两个可验证的数据集改动",
        size=20,
        color=RGBColor(0xC9, 0xDD, 0xD6),
    )

    card(slide, 96, 340, 500, 116, fill=RGBColor(0x1B, 0x3A, 0x33), line=RGBColor(0x2F, 0x5B, 0x51))
    text(slide, 120, 358, 440, 24, "ChinaTravel（ICLR'26）", size=15, color=RGBColor(0x8F, 0xC7, 0xB8), bold=True)
    text(slide, 120, 388, 450, 56, "开集旅行规划基准：约束可执行、沙箱确定、四道闸门", size=14, color=WHITE)

    card(slide, 620, 340, 500, 116, fill=RGBColor(0x3A, 0x26, 0x1E), line=RGBColor(0x63, 0x3F, 0x2E))
    text(slide, 644, 358, 440, 24, "ShortTrip Assistant（我们）", size=15, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True)
    text(slide, 644, 388, 450, 56, "确认后的修订：锁定项、改动代价、无解解释、版本", size=14, color=WHITE)

    text(slide, 96, 560, 700, 24, "Lingwei Cao  ·  Yuhang Ji  ·  Churui Xie", size=15, color=RGBColor(0xC9, 0xDD, 0xD6))
    text(slide, 96, 592, 700, 22, "2026.10.17   全部数字由官方 checker 判出", size=12, color=RGBColor(0x8F, 0xA9, 0xA2))
    text(slide, 900, 560, 300, 40, "地基  →  增量", size=22, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True, align=PP_ALIGN.RIGHT)
    return slide


# --------------------------------------------------------------------------- 02
def slide_onepager(prs):
    slide = blank(prs)
    header(slide, "一页看懂", "两者解决的不是同一个问题", "所以它们不是竞品，而是「地基」与「增量」")

    card(slide, 64, 196, 556, 328, fill=BLUE_L, line=RGBColor(0xC3, 0xD6, 0xE4))
    pill(slide, 92, 220, 132, 30, "ChinaTravel", BLUE, WHITE, size=12)
    text(slide, 92, 262, 500, 34, "从零规划一次，然后判分", size=23, color=BLUE, bold=True)
    text(
        slide,
        92,
        312,
        500,
        210,
        [
            ("输入：城市、天数、人数 + 一组可执行约束", {"size": 14.5}),
            ("输出：一份 itinerary JSON", {"size": 14.5}),
            ("判分：schema → 常识 → 约束 → 偏好", {"size": 14.5}),
            ("", {"size": 8}),
            ("回答的问题：", {"size": 13.5, "bold": True, "color": BLUE}),
            ("「给定需求，能造出既合规又能执行的行程吗？」", {"size": 15, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )

    card(slide, 660, 196, 556, 328, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    pill(slide, 688, 220, 168, 30, "ShortTrip", CLAY, WHITE, size=12)
    text(slide, 688, 262, 500, 34, "行程确认之后，再谈修改", size=23, color=CLAY, bold=True)
    text(
        slide,
        688,
        312,
        500,
        210,
        [
            ("输入：已确认行程 + 扰动 + 锁定项", {"size": 14.5}),
            ("输出：改动最小的新行程 + 差异 + 理由", {"size": 14.5}),
            ("判分：同一个官方 checker 复审全行程", {"size": 14.5}),
            ("", {"size": 8}),
            ("回答的问题：", {"size": 13.5, "bold": True, "color": CLAY}),
            ("「事情变了，怎么改、改了多少、改不了怎么办？」", {"size": 15, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )

    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(624), P(340), P(32), P(44))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
    arrow.line.fill.background()
    arrow.shadow.inherit = False

    card(slide, 64, 548, 1152, 62, fill=WHITE, line=LINE)
    text(
        slide,
        88,
        568,
        1104,
        32,
        {
            "inline": [
                ("→ 我们复用了左栏的全部判分能力", {"size": 13.5, "bold": True, "color": INK}),
                ("，只在右栏加了「修订」这一层：锁定、改动代价、无解解释、版本。", {"size": 13.5}),
            ]
        },
        color=INK_SOFT,
    )
    footer(slide, 2, "两栏对比：左边是基准、右边是我们的项目")
    return slide


# --------------------------------------------------------------------------- 03
def slide_ct_arch(prs):
    slide = blank(prs)
    header(slide, "ChinaTravel ①", "三层架构：环境只读、约束可执行、判分独立", "复现时最重要的认知：三者互不依赖")

    layers = [
        ("环境层  environment/", "10 城 × 7 张表，33,806 行记录\n18 个工具命令，`goto` 全程确定性算价算时", BLUE),
        ("智能体层  agent/", "5 类求解器：纯神经 / NeSy / 规则 / LLM-Modulo / 比赛冠军\n共同点：都在循环里调用同一个 checker", RGBColor(0x4C, 0x7F, 0x9B)),
        ("评测层  evaluation/ + symbol_verification/", "4 道闸门 + DSL 解释器（AST 白名单，异常即 False）", RGBColor(0x6E, 0x99, 0xB1)),
    ]
    y = 196
    for name, detail, color in layers:
        card(slide, 64, y, 700, 108, fill=WHITE, line=RGBColor(0xCF, 0xDD, 0xE6))
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, P(64), P(y + 18), P(5), P(72))
        bar.fill.solid()
        bar.fill.fore_color.rgb = color
        bar.line.fill.background()
        bar.shadow.inherit = False
        text(slide, 92, y + 18, 640, 24, name, size=16, color=color, bold=True)
        text(slide, 92, y + 48, 640, 46, detail, size=13, color=INK_SOFT, spacing=1.3)
        y += 122

    card(slide, 800, 196, 416, 336, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 824, 216, 380, 26, "复现时的三个「原来如此」", size=15, color=INK, bold=True)
    text(
        slide,
        824,
        252,
        372,
        200,
        [
            ("① 沙箱是只读事实，不是数据库：没有写入、没有网络、没有随机。", {"size": 12.5}),
            ("② 约束是「可执行代码」而不是打分函数：能跑出 True/False，能归因。", {"size": 12.5}),
            ("③ checker 与 agent 解耦：agent 用它当反馈，评测用它当裁判。", {"size": 12.5}),
        ],
        color=INK_SOFT,
        spacing=1.35,
        space_after=8,
    )
    text(slide, 824, 474, 372, 44, "→ 这三条正是我们能直接复用它的原因", size=12.5, color=CLAY, bold=True)

    text(slide, 64, 566, 1150, 24, "沙箱规模：景点 3,413 · 酒店 3,866 · 餐厅 4,655 · POI 12,172 · 车次 5,345 · 航班 720 · 地铁站 3,635", size=13, color=MUTED)
    footer(slide, 3, "数据来自本机复现：chinatravel/environment/database{,_en}")
    return slide


# --------------------------------------------------------------------------- 04
def slide_pipeline(prs):
    slide = blank(prs)
    header(slide, "ChinaTravel ②", "一个请求如何变成四个分数", "四个闸门串行；前一个不过，后一个的分数会失真")

    gates = [
        ("① Schema", "结构合法性", "类型、必填字段、城际/市内字段互斥", "1 = 通过（注意极性与后面相反）"),
        ("② Commonsense", "现实可执行性", "8 个检查函数 / 27 个违规列", "1 = 违规；异常会额外加一列"),
        ("③ Hard DSL", "用户约束", "hard_logic_py 逐条执行", "异常 = False；条件于②统计 LPR"),
        ("④ Preference", "偏好排序", "只在「①②③全过」的样本上平均", "无效行程偏好记 0，不能绕过有效性"),
    ]
    x = 64
    for index, (name, sub, what, note) in enumerate(gates):
        card(slide, x, 200, 268, 220, fill=WHITE, line=RGBColor(0xCF, 0xDD, 0xE6))
        text(slide, x + 20, 218, 230, 26, name, size=17, color=BLUE, bold=True)
        text(slide, x + 20, 248, 230, 22, sub, size=13, color=INK, bold=True)
        text(slide, x + 20, 278, 228, 60, what, size=13, color=INK_SOFT, spacing=1.3)
        text(slide, x + 20, 348, 228, 60, note, size=12, color=MUTED, spacing=1.3)
        if index < 3:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(x + 272), P(292), P(24), P(30))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
            arrow.line.fill.background()
            arrow.shadow.inherit = False
        x += 300

    card(slide, 64, 452, 700, 158, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 468, 650, 26, "我们在复现里量到的一个尖锐事实", size=15, color=INK, bold=True)
    text(
        slide,
        88,
        498,
        650,
        62,
        [
            ("官方 RuleNeSy + oracle 约束，跑一条 3 天查询：", {"size": 12.5}),
            ("搜索 197,618 节点 · 9,577 次约束校验 · 打满 300 s", {"size": 12.5, "bold": True}),
            ("DSL 全过 9577/9577，但 commonsense 通过 0 次。", {"size": 12.5, "bold": True, "color": CLAY}),
        ],
        color=INK_SOFT,
        spacing=1.35,
    )
    text(slide, 88, 566, 650, 24, "→ 「约束理解对」换不来「能落地」，这正是常识层必须独立的理由。", size=12.5, color=INK_SOFT)

    card(slide, 788, 452, 428, 158, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 812, 468, 380, 26, "对我们架构的直接含义", size=15, color=CLAY, bold=True)
    text(
        slide,
        812,
        502,
        380,
        62,
        [
            ("① 常识校验必须进搜索循环，而不是最后跑一次", {"size": 12.5}),
            ("② 必须有「无解/超时」分类，而不是 least plan", {"size": 12.5}),
        ],
        color=INK_SOFT,
        spacing=1.4,
        space_after=6,
    )
    footer(slide, 4, "官方 eval_exp.py 的四个闸门；实测数据见 报告/01 §5.2")
    return slide


# --------------------------------------------------------------------------- 05
def slide_dataset(prs):
    slide = blank(prs)
    header(slide, "ChinaTravel ③", "数据集画像：7 张表、7 个 split、一条 DSL", "约束数从 5.3 条（easy）到 13.8 条（phase2）")

    stats = [
        ("10", "个城市", "北京/上海/南京/苏州/杭州\n深圳/成都/武汉/广州/重庆"),
        ("33,806", "行沙箱记录", "7 张表：景点/酒店/餐厅\nPOI/车次/航班/地铁站"),
        ("7", "个 split", "easy/medium/human/偏好 6 档\n+ human1000 + phase2"),
        ("2,404", "条已物化查询", "全部转成 per-uid JSON\n可直接喂给官方 loader"),
    ]
    x = 64
    for number, label, detail in stats:
        card(slide, x, 196, 268, 152, fill=WHITE, line=LINE)
        text(slide, x + 20, 208, 232, 42, number, size=29, color=INK, bold=True)
        text(slide, x + 20, 252, 232, 22, label, size=13.5, color=BLUE, bold=True)
        text(slide, x + 20, 278, 232, 56, detail, size=10.5, color=MUTED, spacing=1.35)
        x += 300

    rows = [
        ["split", "条数", "约束/条", "它的真实用途"],
        ["easy", "300", "5.3", "票数=人数、打车车辆数这类「固定套路」"],
        ["medium", "150", "8.4", "加入房型/预算/指定景点，最像真实需求"],
        ["human", "154", "4.4", "1–6 天、含出发/返程时刻窗"],
        ["phase2", "100", "13.8", "英文、大量「或」组合、正式评测"],
        ["preference*", "6×50", "5.2", "6 档偏好，用于偏好排序评测"],
    ]
    table(slide, 64, 370, 700, rows, [1.1, 0.7, 0.8, 3.6], size=12, row_h=32, header_size=12)

    card(slide, 800, 370, 416, 212, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 824, 386, 380, 24, "一条约束长什么样", size=14, color=INK, bold=True)
    text(
        slide,
        824,
        414,
        384,
        116,
        [
            ("total_cost=0", {"size": 9.5, "font": "Consolas"}),
            ("for activity in allactivities(plan):", {"size": 9.5, "font": "Consolas"}),
            ("  total_cost += activity_cost(activity)", {"size": 9.5, "font": "Consolas"}),
            ("  total_cost += innercity_transport_cost(", {"size": 9.5, "font": "Consolas"}),
            ("      activity_transports(activity))", {"size": 9.5, "font": "Consolas"}),
            ("result=(total_cost<=6000)", {"size": 9.5, "font": "Consolas"}),
        ],
        color=INK_SOFT,
        spacing=1.28,
    )
    text(slide, 824, 544, 380, 34, "→ 可执行、可归因、可被 checker 逐条判 True/False", size=11, color=CLAY, bold=True)
    footer(slide, 5, "统计脚本：scripts/profile_datasets.py、scripts/catalogue_constraints.py")
    return slide


# --------------------------------------------------------------------------- 06
def slide_our_arch(prs):
    slide = blank(prs)
    header(slide, "ShortTrip ①", "我们的架构：六个必须存在的组件", "来自流程图，但落到代码里就是这六件事")

    items = [
        ("① 约束抽取 + 用户确认", "问卷抽硬/软约束；LLM 只做澄清；确认后才进搜索", CLAY),
        ("② 候选排序", "软偏好在这里生效：按画像给候选打分，不参与通过与否", CLAY),
        ("③ 有界搜索 + 校验循环", "候选/节点/时间三预算；checker 在循环里当反馈", INK),
        ("④ 改动代价 + 最小改动修订", "锁定项不可动；替换/新增/删除/时间平移都计入代价", INK),
        ("⑤ 无解三分类 + 解释", "确认冲突 / 可行但超预算 / 关键数据缺失，各自带证据", RGBColor(0x8A, 0x4A, 0x2A)),
        ("⑥ 版本与差异", "SQLite 存行程版本；新旧对比 + 地图可视化", RGBColor(0x8A, 0x4A, 0x2A)),
    ]
    positions = [(64, 196), (484, 196), (904, 196), (64, 386), (484, 386), (904, 386)]
    for (x, y), (name, detail, color) in zip(positions, items):
        card(slide, x, y, 312, 158, fill=WHITE, line=RGBColor(0xE6, 0xD3, 0xC6))
        text(slide, x + 18, y + 16, 276, 44, name, size=14, color=color, bold=True, spacing=1.1)
        text(slide, x + 18, y + 66, 276, 80, detail, size=11.5, color=INK_SOFT, spacing=1.3)

    text(slide, 64, 566, 1150, 24, "已跑通：③ 有界搜索+校验 · ④ 改动代价+修订 · ⑤ 无解三分类（离线部分）", size=13, color=INK_SOFT)
    text(slide, 64, 596, 1150, 24, "待实现：① 问卷与确认 · ② 画像驱动的候选排序 · ⑥ Web 接口 / SQLite 版本表", size=13, color=MUTED)
    footer(slide, 6, "组件划分见 报告/03 §1.3；代码见 reproduction/src/shorttrip/")
    return slide


# --------------------------------------------------------------------------- 07
def slide_layer_compare(prs):
    slide = blank(prs)
    header(slide, "对比 ①", "逐层对照：哪些直接继承、哪些必须新建", "一句话：ChinaTravel 提供地基，我们补「确认—修订—解释—版本」")

    rows = [
        ["能力", "ChinaTravel 里有什么", "我们的用法", "需要新建"],
        ["数据沙箱", "10 城 7 表，确定性算价算时", "直接复用（SandboxEnv 包装）", "来源/有效期/版本"],
        ["约束语言", "hard_logic_py + 35 个概念函数", "当作内部 IR 复用", "锁定原语、改动代价目标"],
        ["约束抽取", "NL → DSL（LLM，两次调用）", "复用接口", "问卷 + 确认 + 可解释"],
        ["候选排序", "按 DSL 通过数重排", "复用思想", "软偏好打分（画像）"],
        ["搜索", "回溯 DFS + 300 s 墙钟", "复用「checker in the loop」", "三预算 + 降级策略"],
        ["校验", "schema/常识/DSL/偏好 四关", "完全复用，零改造", "修订后全行程复审"],
        ["无解", "只有 error_info / least plan", "—", "三分类 + 证据 + 不放宽约束"],
        ["版本交互", "无（只输出 JSON）", "—", "版本表、差异视图、地图"],
    ]
    table(slide, 64, 196, 1152, rows, [1.3, 3.1, 3.0, 2.6], size=12, row_h=44, header_size=13)
    footer(slide, 7, "对应 报告/03 §2 的映射表")
    return slide


# --------------------------------------------------------------------------- 08
def slide_scene_chen(prs):
    slide = blank(prs)
    header(slide, "对比 ②", "场景：下午景点突然关门，但 18:00 的晚餐已订", "先看「一边有什么、一边缺什么」，再看我们怎么补")

    card(slide, 64, 196, 556, 300, fill=BLUE_L, line=RGBColor(0xC3, 0xD6, 0xE4))
    pill(slide, 88, 214, 132, 28, "ChinaTravel", BLUE, WHITE, size=11)
    text(slide, 88, 254, 500, 30, "能判分，但没有「修订」这件事", size=18, color=BLUE, bold=True)
    text(
        slide,
        88,
        296,
        500,
        [
            ("· 7 个 split 全是「从零规划一次」", {"size": 13}),
            ("· DSL 只能表达「必须有 X」，不能表达「X 不许动」", {"size": 13}),
            ("· 没有「改了几处」的度量，也没有新旧对比", {"size": 13}),
            ("· 扰动只能靠重新采样，不能挂在已确认行程上", {"size": 13}),
        ],
        color=INK_SOFT,
        spacing=1.5,
    )
    text(slide, 88, 452, 500, 30, "→ 陈先生的需求，在基准里无处落脚", size=13, color=CLAY, bold=True)

    card(slide, 660, 196, 556, 300, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    pill(slide, 684, 214, 120, 28, "ShortTrip", CLAY, WHITE, size=11)
    text(slide, 684, 254, 500, 30, "四步：锁 → 改 → 算 → 复审", size=18, color=CLAY, bold=True)
    steps = [
        ("① 锁定", "晚餐 = (位置, 开始时间) 不可变"),
        ("② 定向修复", "只替换关门的景点，其余不动"),
        ("③ 算代价", "替换/新增/删除/大幅平移 各计一次"),
        ("④ 复审", "同一 checker 重跑三闸门"),
    ]
    y = 296
    for name, detail in steps:
        text(slide, 684, y, 132, 24, name, size=13, color=CLAY, bold=True)
        text(slide, 818, y, 386, 24, detail, size=13, color=INK_SOFT)
        y += 40
    text(slide, 684, 452, 500, 30, "→ 实测：锁定项 28/28 保持，平均改动 3.28 处", size=13, color=CLAY, bold=True)

    card(slide, 64, 516, 1152, 92, fill=WHITE, line=LINE)
    text(slide, 88, 530, 1100, 24, "数据是怎么造的：不碰沙箱，只往 query 末尾追加一条约束", size=13, color=INK, bold=True)
    text(
        slide,
        88,
        562,
        1100,
        30,
        {
            "inline": [
                ("景点关门 →  ", {"size": 12, "color": MUTED}),
                ('result=not({"拙政园"}&attraction_name_set)', {"size": 12, "font": "Consolas"}),
            ]
        },
        color=INK_SOFT,
    )
    footer(slide, 8, "对应 报告/04 §3；用例文件 reproduction/datasets/shorttrip_repair/")
    return slide


# --------------------------------------------------------------------------- 09
def slide_scene_zhou(prs):
    slide = blank(prs)
    header(
        slide,
        "对比 ③",
        "场景：14:00 进馆、15:30 到站，谁在冲突？",
        "关键是「不要把自己的无能为力说成客观不可能」",
        title_size=28,
    )

    card(slide, 64, 196, 470, 300, fill=BLUE_L, line=RGBColor(0xC3, 0xD6, 0xE4))
    text(slide, 88, 214, 420, 30, "ChinaTravel 的回答方式", size=17, color=BLUE, bold=True)
    text(
        slide,
        88,
        258,
        420,
        220,
        [
            ("搜索超时 → 抛 TimeOutError", {"size": 13}),
            ("搜不到 → 返回 least plan（可能常识全挂）", {"size": 13}),
            ("两者在下游数据里没有区别", {"size": 13}),
            ("", {"size": 6}),
            ("后果：用户看到的是「规划失败」，", {"size": 13, "bold": True}),
            ("既不知道是数据缺、还是真冲突、还是没搜够。", {"size": 13, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.45,
    )

    card(slide, 566, 178, 650, 318, fill=WHITE, line=LINE)
    text(slide, 590, 194, 600, 26, "我们的三分类（每类必须带证据）", size=16, color=INK, bold=True)

    kinds = [
        ("确认冲突", "预算上限 < 可证明下界", "最便宜城际往返×人数 + 最便宜酒店×夜数", CLAY),
        ("可行但未搜到", "有见证方案，只是搜索预算耗尽", "只报「未证明不可行」，绝不报「不可行」", RGBColor(0x8A, 0x75, 0x2A)),
        ("关键数据缺失", "必去 POI 在沙箱里不存在", "报数据缺失，要求用户确认或换目标", BLUE),
    ]
    y = 232
    for name, cond, action, color in kinds:
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, P(590), P(y + 6), P(4), P(58))
        bar.fill.solid()
        bar.fill.fore_color.rgb = color
        bar.line.fill.background()
        bar.shadow.inherit = False
        text(slide, 610, y, 210, 24, name, size=14, color=color, bold=True)
        text(slide, 610, y + 24, 580, 20, cond, size=12, color=INK_SOFT)
        text(slide, 610, y + 44, 580, 20, action, size=12, color=MUTED)
        y += 86

    card(slide, 64, 512, 1152, 96, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 526, 1100, 24, "实测：18 条三类用例，分类 18/18 正确；把「可行」误判成「不可行」0 次", size=14, color=INK, bold=True)
    text(slide, 88, 558, 1100, 30, "注意：这个 100% 是「构造上就让每类可判定」的结果，属于设计正确，不是模型聪明。", size=12, color=MUTED)
    footer(slide, 9, "对应 报告/04 §4；分类器 reproduction/src/shorttrip/infeasibility.py")
    return slide


# --------------------------------------------------------------------------- 10
def slide_repro_chart(prs):
    slide = blank(prs)
    header(slide, "证据 ①", "同一批 8 条查询、同一个官方评测脚本", "官方基线（纯规则 + oracle 约束）vs 我们的确定性构造 + 有界修复")

    data = CategoryChartData()
    data.categories = ["Schema", "Commonsense", "Hard DSL", "All pass"]
    data.add_series("官方 RuleNeSy", (100.0, 99.54, 97.5, 87.5))
    data.add_series("ShortTrip（无 LLM）", (100.0, 100.0, 100.0, 100.0))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(720), P(360), data
    ).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(12)
    chart.legend.font.color.rgb = INK_SOFT
    chart.legend.font.name = FONT
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(11)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.font.name = FONT
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.number_format = "0.0"
    plot.data_labels.number_format_is_linked = False
    for series, color in zip(plot.series, (BLUE, CLAY)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    value_axis = chart.value_axis
    value_axis.maximum_scale = 110
    value_axis.minimum_scale = 0
    value_axis.has_major_gridlines = True
    value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    value_axis.tick_labels.font.size = Pt(11)
    value_axis.tick_labels.font.color.rgb = MUTED
    value_axis.tick_labels.font.name = FONT
    chart.category_axis.tick_labels.font.size = Pt(12)
    chart.category_axis.tick_labels.font.color.rgb = INK
    chart.category_axis.tick_labels.font.name = FONT

    card(slide, 812, 196, 404, 168, fill=WHITE, line=LINE)
    text(slide, 836, 212, 360, 24, "怎么读这张图", size=14, color=INK, bold=True)
    text(
        slide,
        836,
        244,
        360,
        [
            ("· 8 条「1 天、1–2 人」查询，不是大样本", {"size": 12}),
            ("· 同一 checker、同一脚本、同一沙箱", {"size": 12}),
            ("· 结论只到「管线兼容 + 常识满分」，不代表超过 SOTA", {"size": 12}),
        ],
        color=INK_SOFT,
        spacing=1.35,
    )

    card(slide, 812, 384, 404, 172, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 836, 400, 360, 24, "为什么我们能满分", size=14, color=CLAY, bold=True)
    text(
        slide,
        836,
        432,
        360,
        [
            ("① 候选先按地理距离预筛（≤9–12 km）", {"size": 12}),
            ("② 时间链整条重排，交通段逐字复刻 goto", {"size": 12}),
            ("③ 每次编辑都过一遍官方三闸门", {"size": 12}),
        ],
        color=INK_SOFT,
        spacing=1.35,
    )
    footer(slide, 10, "原始输出：results/e0_official_eval_shorttrip.txt、…_rulenes_y.txt")
    return slide


# --------------------------------------------------------------------------- 11
def slide_e12(prs):
    slide = blank(prs)
    header(slide, "证据 ②", "先证明判分器可信，再谈修复率", "E1 = checker 变异检测；E2 = 48 条真实查询上的零 LLM 构造")

    card(slide, 64, 196, 520, 380, fill=WHITE, line=LINE)
    text(slide, 88, 212, 470, 26, "E1 · 9 类「像人会犯的错」", size=15, color=INK, bold=True)
    text(slide, 88, 240, 470, 38, "9 / 9 全部检出", size=28, color=CLAY, bold=True)
    rows = [
        ["变异", "被哪一列抓到"],
        ["景点名不存在", "Unavailable attractions（整组 5 列）"],
        ["午餐挪到 14:00", "Inappropriate Meal Times"],
        ["地铁票价 +1 元", "Incorrect price… / cost…"],
        ["删掉地铁 tickets", "Incorrect cost information…"],
        ["活动时间重叠", "Does not follow Chronological Order"],
        ["酒店房型不符", "…Accommodation on price or room type"],
        ["城际车次不存在", "Invalid Trains or Airplanes…"],
    ]
    table(slide, 88, 306, 470, rows, [1.5, 3.2], size=11, row_h=28, header_size=11)

    card(slide, 612, 196, 604, 380, fill=WHITE, line=LINE)
    text(slide, 636, 212, 560, 26, "E2 · 48 条真实查询（四个 split 各 12 条）", size=14, color=INK, bold=True)
    metrics = [
        ("48 / 48", "构造成功", "全部拿到一份可执行的方案"),
        ("47 / 48", "Commonsense 通过", "唯一失败是长跨城当日酒店不可达"),
        ("226 → 246", "Hard DSL 通过 / 267", "加上有界修复后 +20 条约束"),
        ("29 → 31", "三闸门全过 / 48", "medium 从 0/12 提到 2/12"),
    ]
    y = 272
    for big, label, detail in metrics:
        text(slide, 636, y, 200, 34, big, size=21, color=CLAY, bold=True)
        text(slide, 842, y + 2, 340, 22, label, size=13, color=INK, bold=True)
        text(slide, 842, y + 22, 350, 20, detail, size=11, color=MUTED)
        y += 68

    text(slide, 64, 596, 1150, 24, "→ 两个实验合起来说明：这份 checker 可以当「独立裁判」，我们的构造器在真实城市规模下站得住。", size=13, color=INK_SOFT)
    footer(slide, 11, "原始结果：results/e1_mutations.json、results/e2_baseline.json")
    return slide


# --------------------------------------------------------------------------- 12
def slide_e3(prs):
    slide = blank(prs)
    header(slide, "证据 ③", "E3：40 条「已确认行程 + 扰动」，修好 28 条", "关门几乎必成，改动到达时刻则明显变难——这是最有信息量的地方")

    data = CategoryChartData()
    data.categories = ["景点/餐厅关门", "必须 15:30 前到站", "去程晚点"]
    data.add_series("修复成功率 %", (90.9, 75.0, 20.0))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED, P(64), P(210), P(620), P(300), data
    ).chart
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(12)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.font.name = FONT
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.number_format = '0.0"%"'
    plot.data_labels.number_format_is_linked = False
    series = plot.series[0]
    series.format.fill.solid()
    series.format.fill.fore_color.rgb = CLAY
    chart.value_axis.maximum_scale = 100
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    chart.value_axis.tick_labels.font.size = Pt(11)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.value_axis.tick_labels.font.name = FONT
    chart.category_axis.tick_labels.font.size = Pt(12)
    chart.category_axis.tick_labels.font.color.rgb = INK
    chart.category_axis.tick_labels.font.name = FONT

    card(slide, 712, 196, 504, 150, fill=WHITE, line=LINE)
    text(slide, 736, 212, 460, 22, "整体指标", size=12.5, color=MUTED, bold=True)
    text(slide, 736, 236, 460, 40, "28 / 40 = 70%", size=27, color=CLAY, bold=True)
    text(slide, 736, 280, 460, 22, "修复成功（三闸门全过且锁定项未动）", size=12, color=INK_SOFT)
    text(slide, 736, 306, 460, 24, "锁定项保持 28/28  ·  平均改动代价 3.28 处", size=12, color=INK_SOFT)

    card(slide, 712, 362, 504, 194, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 736, 376, 460, 24, "为什么「去程晚点」只有 2/10", size=14, color=CLAY, bold=True)
    text(
        slide,
        736,
        406,
        460,
        96,
        [
            ("① 到达时刻是全局量，整段右移", {"size": 12}),
            ("② 局部替换救不了 → 只能放弃当天部分内容", {"size": 12}),
            ("③ 一放弃就破坏「景点数量」这类计数约束", {"size": 12}),
            ("④ 真正需要的是「内容重排 + 计数守恒」", {"size": 12, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.32,
    )
    text(slide, 736, 508, 460, 36, "→ 这条失败直接变成了下一步的第一优先级", size=11.5, color=CLAY, bold=True)

    text(slide, 64, 548, 620, 24, "closure 20/22 · early_departure 6/8 · go_delay 2/10", size=12, color=MUTED)
    footer(slide, 12, "原始结果：results/e3_repair.json；用例：datasets/shorttrip_repair/")
    return slide


# --------------------------------------------------------------------------- 13
def slide_e4(prs):
    slide = blank(prs)
    header(slide, "证据 ④", "E4：18 条无解用例，三类全部分对", "而且没有一次把「其实可行」说成「不可行」")

    cards = [
        ("确认冲突", "6 / 6", "预算 623 < 可证明下界 624", CLAY),
        ("可行但未搜到", "6 / 6", "有见证方案 → 只报「未证明」", RGBColor(0x8A, 0x75, 0x2A)),
        ("关键数据缺失", "6 / 6", "POI 不在沙箱 4 张表内", BLUE),
    ]
    x = 64
    for name, score, detail, color in cards:
        card(slide, x, 196, 372, 168, fill=WHITE, line=RGBColor(0xE6, 0xD3, 0xC6))
        text(slide, x + 22, 214, 330, 26, name, size=15, color=color, bold=True)
        text(slide, x + 22, 248, 330, 44, score, size=30, color=color, bold=True)
        text(slide, x + 22, 300, 330, 46, detail, size=12, color=INK_SOFT, spacing=1.3)
        x += 396

    rows = [
        ["真实类别", "预测类别", "误判为「不可行」"],
        ["确认冲突（6）", "确认冲突 6", "—"],
        ["可行但未搜到（6）", "可行但未搜到 6", "0"],
        ["关键数据缺失（6）", "关键数据缺失 6", "—"],
        ["合计", "18 / 18 = 100%", "0 次"],
    ]
    table(slide, 64, 392, 700, rows, [2.4, 2.0, 1.8], size=12, row_h=34, header_size=12)

    card(slide, 800, 392, 416, 172, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 824, 408, 380, 24, "这个 100% 的边界", size=14, color=INK, bold=True)
    text(
        slide,
        824,
        440,
        380,
        [
            ("它是「构造使然」：每类都带一个可判定特征。", {"size": 12}),
            ("真正难的是下界不够紧时怎么判 —— 那需要更紧的不可行证明。", {"size": 12}),
        ],
        color=INK_SOFT,
        spacing=1.35,
    )
    text(slide, 64, 588, 1150, 24, "规则：没有证据就不许说「不可行」。这条规则本身就是从 ChinaTravel 的 least plan 兜底里学到的。", size=13, color=INK_SOFT)
    footer(slide, 13, "原始结果：results/e4_infeasible.json；用例：datasets/shorttrip_infeasible/")
    return slide


# --------------------------------------------------------------------------- 14
def slide_dataset_changes(prs):
    slide = blank(prs)
    header(slide, "数据集改动", "改的不是沙箱，而是「约束 + 元数据 + 标签」三层", "四条准入标准：可判分 / 不动沙箱 / 有真值 / 有增量")

    rows = [
        ["编号", "改动", "加在哪", "解决什么", "状态"],
        ["M1", "锁定项 locked", "记录元数据", "「晚饭已订不能动」", "已实现"],
        ["M2", "扰动 disruption", "追加 DSL 约束", "关门 / 晚点 / 提前离场", "已实现"],
        ["M3", "改动代价 witness_cost", "记录真值", "「尽量少改」有度量", "已实现"],
        ["M4", "无解标签 + 证据", "记录标签", "「哪个要求在冲突」", "已实现"],
        ["M5", "偏好画像 profile", "记录元数据", "问卷偏好可复用、可排序", "设计完成"],
        ["M6", "数据时效字段", "POI 级元数据", "数据过时/缺失时拒绝下结论", "设计完成"],
    ]
    table(slide, 64, 196, 1152, rows, [0.7, 2.4, 1.9, 3.3, 1.2], size=12, row_h=42, header_size=13)

    card(slide, 64, 512, 556, 96, fill=WHITE, line=LINE)
    text(slide, 88, 528, 500, 24, "兼容性：为什么没破坏可比性", size=13, color=INK, bold=True)
    text(slide, 88, 558, 500, 42, "V1 的 query 就是标准 query，eval_exp.py 可直接判；原 7 个 split 的分数不受影响。", size=12, color=INK_SOFT, spacing=1.3)

    card(slide, 660, 512, 556, 96, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 528, 500, 24, "为什么不复用官方合成器", size=13, color=CLAY, bold=True)
    text(slide, 684, 558, 500, 42, "它三重校验要求种子方案必须满足约束 → 天生造不出「不可行」；且 2026.08 版 day_time 家族有 NameError。", size=12, color=INK_SOFT, spacing=1.3)
    footer(slide, 14, "详见 报告/04；生成脚本 scripts/build_shorttrip_datasets.py")
    return slide


# --------------------------------------------------------------------------- 15
def slide_limits(prs):
    slide = blank(prs)
    header(slide, "诚实的部分", "三个负面结果，和它们指向的下一步", "这些不是「没做完」，是「做了以后发现的真问题」")

    items = [
        (
            "去程晚点只修好 2/10",
            "到达时刻是全局量：局部替换无效，放弃当天内容又会破坏计数约束。",
            "把「内容重排 + 计数守恒」做进修复循环（而不是分阶段贪心）。",
        ),
        (
            "human 的 hard 通过没提升（41/51）",
            "失败集中在出发/返程时刻窗与景点类型，分阶段编辑会互相踩。",
            "让候选排序与搜索耦合：类型约束直接进候选生成，而不是事后补。",
        ),
        (
            "没有跑 LLM Agent",
            "本机无 API key，且不应擅自消耗额度；管线命令已就绪。",
            "补 Act/ReAct/LLMNeSy 三档对照，才能做 PDF 里的「完整 vs 无反馈」消融。",
        ),
    ]
    y = 196
    for title, why, fix in items:
        card(slide, 64, y, 1152, 116, fill=WHITE, line=LINE)
        text(slide, 88, y + 16, 470, 24, title, size=13.5, color=CLAY, bold=True)
        text(slide, 88, y + 46, 480, 56, why, size=12, color=INK_SOFT, spacing=1.3)
        arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(596), P(y + 46), P(28), P(26))
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
        arrow.line.fill.background()
        arrow.shadow.inherit = False
        text(slide, 648, y + 16, 540, 24, "下一步", size=12, color=MUTED, bold=True)
        text(slide, 648, y + 46, 544, 56, fix, size=12, color=INK, spacing=1.3)
        y += 132
    footer(slide, 15, "详见 报告/05 §6 与 报告/03 §4")
    return slide


# --------------------------------------------------------------------------- 16
def slide_conclusion(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = INK
    bg.line.fill.background()
    bg.shadow.inherit = False

    pill(slide, 96, 88, 132, 32, "结论", RGBColor(0x2A, 0x4A, 0x43), MINT, size=12)
    text(slide, 96, 140, 1080, 46, "三句话带走", size=32, color=WHITE, bold=True)

    rows = [
        ("地基不是竞品", "ChinaTravel 的约束 IR、确定性沙箱、四道闸门都被我们直接复用，并在本机跑通、按官方口径量了分。"),
        ("增量是可验证的", "锁定 + 改动代价 + 无解三分类，都在官方 checker 上判分：修复 70%、锁定 28/28、分类 18/18。"),
        ("数据改动很小", "只动约束与元数据，不动沙箱；原 split 的分数不受影响，新 split 才承载新能力。"),
    ]
    y = 208
    for index, (title, detail) in enumerate(rows):
        text(slide, 96, y, 60, 40, f"0{index + 1}", size=24, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True)
        text(slide, 168, y - 2, 340, 32, title, size=20, color=WHITE, bold=True)
        text(slide, 168, y + 34, 980, 52, detail, size=14, color=RGBColor(0xC9, 0xDD, 0xD6), spacing=1.4)
        y += 136

    text(slide, 96, 636, 1000, 24, "下一步：内容重排 + 计数守恒 · 问卷画像排序 · 数据时效闸门", size=13, color=RGBColor(0x8F, 0xA9, 0xA2))
    return slide


def main() -> int:
    prs = new_deck()
    slide_cover(prs)
    slide_onepager(prs)
    slide_ct_arch(prs)
    slide_pipeline(prs)
    slide_dataset(prs)
    slide_our_arch(prs)
    slide_layer_compare(prs)
    slide_scene_chen(prs)
    slide_scene_zhou(prs)
    slide_repro_chart(prs)
    slide_e12(prs)
    slide_e3(prs)
    slide_e4(prs)
    slide_dataset_changes(prs)
    slide_limits(prs)
    slide_conclusion(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT} slides={len(prs.slides)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
