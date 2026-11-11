"""Build the detailed work-summary deck (本次工作详细总结).

Reuses the visual language of the earlier comparison deck (same palette, 1280x720
grid, shared helpers) so the two decks sit side by side.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt
from pptx.dml.color import RGBColor

from build_comparison_ppt import (  # noqa: E402
    BLUE,
    BLUE_L,
    CLAY,
    CLAY_L,
    INK,
    INK_SOFT,
    LINE,
    MINT,
    MUTED,
    P,
    PAPER,
    WHITE,
    blank,
    card,
    footer,
    header,
    new_deck,
    pill,
    table,
    text,
)

OUT = HERE.parents[1] / "输出" / "本次工作详细总结_复现与动态沙盒.pptx"
GREY = RGBColor(0xEC, 0xF1, 0xEF)


# --------------------------------------------------------------------------- 01
def s_cover(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = INK
    bg.line.fill.background()
    bg.shadow.inherit = False

    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, P(506), prs.slide_width, P(214))
    band.fill.solid()
    band.fill.fore_color.rgb = RGBColor(0x11, 0x26, 0x22)
    band.line.fill.background()
    band.shadow.inherit = False

    pill(slide, 96, 118, 236, 34, "课程项目 · 工作详细总结", RGBColor(0x2A, 0x4A, 0x43), MINT, size=13)
    text(slide, 96, 180, 1120, 64, "从复现 ChinaTravel 到动态沙盒", size=44, color=WHITE, bold=True)
    text(
        slide,
        96,
        256,
        1040,
        34,
        "六篇报告 · 12 个模块 · 58 条自建用例 · 一套可验证的数据更新流水线",
        size=19,
        color=RGBColor(0xC9, 0xDD, 0xD6),
    )

    cards = [
        ("复现", "官方数据 / 沙箱 / 评测器 / 规则 agent\nAll pass 87.5%", RGBColor(0x1B, 0x3A, 0x33), RGBColor(0x8F, 0xC7, 0xB8)),
        ("架构", "ShortTrip 六组件 × ChinaTravel 四闸门\n逐层映射与差距", RGBColor(0x1B, 0x3A, 0x33), RGBColor(0xC9, 0xDD, 0xD6)),
        ("数据", "V1 修订 40 条 · V2 无解 18 条\n修复 70% / 锁定 28/28", RGBColor(0x3A, 0x26, 0x1E), RGBColor(0xE0, 0xA3, 0x7E)),
        ("动态更新", "缺口→取证→质闸→注入\n10 个工具实例即时可见", RGBColor(0x3A, 0x26, 0x1E), RGBColor(0xE0, 0xA3, 0x7E)),
    ]
    x = 96
    for title, detail, fill, accent in cards:
        card(slide, x, 330, 266, 128, fill=fill, line=RGBColor(0x2F, 0x5B, 0x51))
        text(slide, x + 20, 348, 226, 24, title, size=16, color=accent, bold=True)
        text(slide, x + 20, 380, 228, 62, detail, size=12, color=WHITE, spacing=1.45)
        x += 286

    text(slide, 96, 546, 760, 24, "Lingwei Cao  ·  Yuhang Ji  ·  Churui Xie", size=15, color=RGBColor(0xC9, 0xDD, 0xD6))
    text(slide, 96, 578, 900, 22, "2026.10.17   所有分数由官方 checker 判出，所有外部数据均附来源与引文", size=12, color=RGBColor(0x8F, 0xA9, 0xA2))
    text(slide, 900, 546, 300, 40, "6 周 · 5 阶段", size=20, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True, align=PP_ALIGN.RIGHT)
    return slide


# --------------------------------------------------------------------------- 02
def s_overview(prs):
    slide = blank(prs)
    header(slide, "总览", "五阶段：从复现到可自我纠错的沙盒", "主线是把「能判分」变成「能修订、能解释、能更新」")

    stages = [
        ("① 复现", "官方仓库 + 双语沙箱 + 评测器\n规则 agent 无 LLM 跑通", BLUE),
        ("② 剖析", "三层架构 / 四闸门 / 87 个约束族\n33,806 行沙箱画像", RGBColor(0x4C, 0x7F, 0x9B)),
        ("③ 架构", "ShortTrip 六组件\n逐层映射与差距清单", RGBColor(0x2A, 0x7A, 0x6A)),
        ("④ 数据", "V1 修订 40 条 / V2 无解 18 条\nM1–M6 改动清单", CLAY),
        ("⑤ 动态更新", "高德 + 维基 + Wikidata\n8 道闸门 + 版本化注入", RGBColor(0x8A, 0x4A, 0x2A)),
    ]
    x = 64
    for title, detail, color in stages:
        card(slide, x, 196, 214, 150, fill=WHITE, line=LINE)
        text(slide, x + 18, 212, 180, 30, title, size=17, color=color, bold=True)
        text(slide, x + 18, 250, 182, 84, detail, size=11.5, color=INK_SOFT, spacing=1.4)
        if x < 1000:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(x + 220), P(258), P(18), P(24))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
            arrow.line.fill.background()
            arrow.shadow.inherit = False
        x += 240

    stats = [
        ("2,404", "条查询已物化"),
        ("33,806", "行沙箱记录"),
        ("58", "条自建用例"),
        ("18/18", "无解分类正确"),
        ("10", "个工具实例热更新"),
    ]
    x = 64
    for big, label in stats:
        card(slide, x, 384, 220, 96, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
        text(slide, x + 18, 398, 190, 40, big, size=26, color=CLAY, bold=True)
        text(slide, x + 18, 444, 190, 22, label, size=12, color=INK_SOFT)
        x += 236

    card(slide, 64, 500, 1152, 112, fill=WHITE, line=LINE)
    text(slide, 88, 514, 1100, 26, "三个阶段各自回答一个问题", size=14, color=INK, bold=True)
    text(
        slide,
        88,
        546,
        1100,
        52,
        "复现回答「它到底怎么跑、分数多少」；架构回答「我们能复用什么、必须建什么」；"
        "数据与动态更新回答「怎么把一次性的基准，变成能持续修订、能自我纠错的系统」。",
        size=12,
        color=INK_SOFT,
        spacing=1.3,
    )
    footer(slide, 2, "报告 01–06 · results/ 下逐项可复核")
    return slide


# --------------------------------------------------------------------------- 03
def s_phase1(prs):
    slide = blank(prs)
    header(slide, "阶段 ①", "复现 ChinaTravel：能离线跑的部分全部跑通", "只剩 LLM 求解一环需要外部模型额度")

    card(slide, 64, 190, 556, 386, fill=BLUE_L, line=RGBColor(0xC3, 0xD6, 0xE4))
    text(slide, 88, 206, 500, 28, "做到了什么", size=16, color=BLUE, bold=True)
    text(
        slide,
        88,
        246,
        500,
        310,
        [
            ("· 完整 clone 官方仓库（193 文件）+ 双语沙箱", {"size": 12.5}),
            ("· 查询集 6 类物化为 2,404 条 per-uid JSON", {"size": 12.5}),
            ("· WorldEnv 全部 18 个工具命令可用", {"size": 12.5}),
            ("· RuleNeSy + oracle DSL 无 LLM 跑通", {"size": 12.5}),
            ("· 官方 eval_exp.py 端到端出分", {"size": 12.5}),
            ("", {"size": 6}),
            ("关键：评测器与 agent 解耦，", {"size": 12.5, "bold": True}),
            ("所以“复现评测”不需要 API key。", {"size": 12.5, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.55,
    )

    card(slide, 644, 190, 572, 386, fill=WHITE, line=LINE)
    text(slide, 668, 206, 520, 28, "六个真实的坑（都写进报告/01 §6）", size=16, color=INK, bold=True)
    rows = [
        ["坑", "后果 / 解法"],
        ["沙箱 zip 文件名 GBK 当 CP437 解码", "路径全乱 → cp437→gbk 修复"],
        ["hard_logic_py 是 Python repr 非 JSON", "json.loads 直接崩 → ast.literal_eval"],
        ["easy 与 preference_base50 有 50 个 uid 重叠", "loader 报 ambiguous → 别名 split"],
        ["numpy 1.26.4 无 cp313 轮子", "降级失败 → numpy 2.2.6"],
        ["GBK 终端写日志崩（UnicodeEncodeError）", "PYTHONUTF8=1"],
        ["合成器 constraints.py:795 引用未定义变量", "from-plans 跑不通 → 不复用它"],
    ]
    table(slide, 668, 244, 524, rows, [2.4, 2.6], size=10.5, row_h=40, header_size=11)

    text(slide, 64, 592, 1150, 24, "→ 复现的意义不是“能跑”，而是确认了：沙箱只读、约束可执行、判分独立——这三条决定了后续所有设计。", size=12.5, color=INK_SOFT)
    footer(slide, 3, "报告/01 · scripts/download_data.py、extract_sandbox.py、materialise_queries.py")
    return slide


# --------------------------------------------------------------------------- 04
def s_phase1_result(prs):
    slide = blank(prs)
    header(slide, "阶段 ① 结果", "官方基线的分数，与它真正的代价", "同一批 8 条 1 天查询，同一套官方脚本")

    data = CategoryChartData()
    data.categories = ["Schema", "Commonsense", "Hard DSL", "All pass"]
    data.add_series("官方 RuleNeSy + oracle", (100.0, 99.54, 97.5, 87.5))
    data.add_series("ShortTrip（无 LLM）", (100.0, 100.0, 100.0, 100.0))
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(680), P(330), data).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(11)
    chart.legend.font.color.rgb = INK_SOFT
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.number_format = "0.0"
    plot.data_labels.number_format_is_linked = False
    for series, color in zip(plot.series, (BLUE, CLAY)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    chart.value_axis.maximum_scale = 110
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    chart.value_axis.tick_labels.font.size = Pt(10)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.category_axis.tick_labels.font.size = Pt(11)
    chart.category_axis.tick_labels.font.color.rgb = INK

    card(slide, 772, 196, 444, 156, fill=WHITE, line=LINE)
    text(slide, 796, 210, 400, 24, "读法：这是管线自检", size=13, color=MUTED, bold=True)
    text(slide, 796, 238, 400, 100, "8 条查询不是大样本；它的价值是证明我们的方案格式与官方 checker 完全兼容，且在 commonsense 上拿到满分。", size=12, color=INK_SOFT, spacing=1.4)

    card(slide, 772, 368, 444, 158, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 796, 382, 400, 24, "官方基线的代价（一条 3 天查询）", size=12.5, color=CLAY, bold=True)
    text(
        slide,
        796,
        410,
        400,
        108,
        [
            ("197,618 搜索节点 / 9,577 次校验 / 300 s", {"size": 12, "bold": True}),
            ("DSL 全过 9577/9577，commonsense 通过 0 次", {"size": 12, "bold": True, "color": CLAY}),
            ("→ 约束理解对，也换不来能落地的行程", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.45,
    )

    card(slide, 64, 546, 1152, 92, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 560, 1100, 26, "这组数据直接决定了后面两个设计选择", size=13.5, color=INK, bold=True)
    text(
        slide,
        88,
        590,
        1100,
        36,
        "① 常识校验必须进搜索循环，不能最后跑一次；② 必须有“无解/超时”分类，而不是 least plan 兜底。",
        size=12.5,
        color=INK_SOFT,
    )
    footer(slide, 4, "results/e0_official_eval_rulenes_y.txt、e0_official_eval_shorttrip.txt")
    return slide


# --------------------------------------------------------------------------- 05
def s_phase2(prs):
    slide = blank(prs)
    header(slide, "阶段 ②", "剖析：三层架构、四道闸门、一份数据画像", "看懂“它为什么可信”，才知道“我们能复用什么”")

    layers = [
        ("环境层", "10 城 × 7 表 / 33,806 行 / 18 个工具命令", "goto 全程确定性算价算时", BLUE),
        ("智能体层", "5 类求解器：纯神经 / NeSy / 规则 / LLM-Modulo / 冠军方案", "共同点：循环里调用同一个 checker", RGBColor(0x4C, 0x7F, 0x9B)),
        ("评测层", "schema → commonsense(8 检查/27 列) → hard DSL → preference", "异常即 False；条件于②统计 LPR", RGBColor(0x6E, 0x99, 0xB1)),
    ]
    y = 190
    for name, left, right, color in layers:
        card(slide, 64, y, 700, 96, fill=WHITE, line=LINE)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, P(64), P(y + 16), P(5), P(64))
        bar.fill.solid()
        bar.fill.fore_color.rgb = color
        bar.line.fill.background()
        bar.shadow.inherit = False
        text(slide, 90, y + 14, 200, 26, name, size=15, color=color, bold=True)
        text(slide, 210, y + 16, 540, 24, left, size=12, color=INK_SOFT)
        text(slide, 210, y + 44, 540, 24, right, size=11.5, color=MUTED)
        y += 110

    card(slide, 788, 190, 428, 192, fill=WHITE, line=LINE)
    text(slide, 812, 204, 380, 24, "数据画像（实测）", size=14, color=INK, bold=True)
    text(
        slide,
        812,
        234,
        380,
        140,
        [
            ("· 查询：easy 300 / medium 150 / human 154", {"size": 11.5}),
            ("  human1000 1000 / 偏好 6×50 / phase2 100", {"size": 11.5}),
            ("· 约束：5.3 条（easy）→ 13.8 条（phase2）", {"size": 11.5}),
            ("· 约束族：按概念函数签名分 87 个家族", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.6,
    )

    card(slide, 788, 396, 428, 148, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 812, 410, 380, 24, "两条必须记住的语义陷阱", size=13, color=CLAY, bold=True)
    text(
        slide,
        812,
        440,
        380,
        96,
        [
            ("· schema 里 1=通过，commonsense 里 1=违规", {"size": 11.5}),
            ("· 沙盒把“未知营业时间”编码成 00:00–24:00", {"size": 11.5, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.55,
    )

    text(slide, 64, 560, 1150, 24, "“未知=全天开放”这条后来在广东省博物馆上被高德数据当场抓了出来（见第 16 页），是整份工作最实的一个发现。", size=12.5, color=INK_SOFT)
    footer(slide, 5, "报告/02 · notes/constraint_families.md、dataset_profile.json")
    return slide


# --------------------------------------------------------------------------- 06
def s_our_arch(prs):
    slide = blank(prs)
    header(slide, "阶段 ③", "我们的架构：六个组件，落成 12 个模块", "绿色=已跑通；其余=已设计未实现")

    items = [
        ("① 约束抽取 + 用户确认", "问卷抽硬/软约束；LLM 只澄清；确认后才搜索", MUTED, False),
        ("② 候选排序", "软偏好在这里生效，不参与通过与否", MUTED, False),
        ("③ 有界搜索 + 校验循环", "候选/节点/时间三预算；checker 在循环里当反馈", INK, True),
        ("④ 改动代价 + 最小改动修订", "锁定不可动；替换/新增/删除/平移都计入代价", INK, True),
        ("⑤ 无解三分类 + 解释", "确认冲突 / 可行未搜到 / 数据缺失，各带证据", INK, True),
        ("⑥ 版本与差异", "SQLite 版本表 + 新旧对比（overlay 已实现）", MUTED, False),
    ]
    pos = [(64, 190), (484, 190), (904, 190), (64, 356), (484, 356), (904, 356)]
    for (x, y), (name, detail, color, done) in zip(pos, items):
        card(slide, x, y, 312, 146, fill=WHITE, line=RGBColor(0xD8, 0xEA, 0xE3) if done else RGBColor(0xE7, 0xEC, 0xEA))
        text(slide, x + 18, y + 14, 276, 44, name, size=13, color=CLAY if not done else INK, bold=True, spacing=1.1)
        text(slide, x + 18, y + 62, 276, 74, detail, size=11, color=INK_SOFT, spacing=1.35)
        if done:
            text(slide, x + 252, y + 16, 44, 20, "✓", size=15, color=RGBColor(0x2A, 0x7A, 0x6A), bold=True)

    rows = [
        ["组件", "对应模块", "状态"],
        ["③ 有界搜索 + 校验", "planner.py / scheduler.py / checker.py", "跑通（E2 48 条）"],
        ["④ 改动代价 + 修订", "repair.py / dataset.py", "跑通（E3 40 条）"],
        ["⑤ 无解三分类", "infeasibility.py", "跑通（E4 18 条）"],
        ["⑥ 版本与差异", "dynamic/overlay.py + bus.py", "跑通（动态更新）"],
        ["①② 问卷与画像排序", "—（设计完成）", "未实现"],
    ]
    table(slide, 64, 522, 700, rows, [2.2, 3.0, 1.8], size=10.5, row_h=26, header_size=10.5)

    card(slide, 792, 522, 424, 116, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 816, 534, 380, 22, "一句话定位", size=12.5, color=INK, bold=True)
    text(slide, 816, 560, 380, 68, "ChinaTravel 提供“可执行约束 + 确定性沙箱 + 四闸门”；我们不重造，只补“确认—修订—解释—版本”这半边。", size=11.5, color=INK_SOFT, spacing=1.4)
    footer(slide, 6, "报告/03 · src/shorttrip/")
    return slide


# --------------------------------------------------------------------------- 07
def s_mapping(prs):
    slide = blank(prs)
    header(slide, "阶段 ③ 对比", "逐层映射：哪些直接继承、哪些必须新建", "这张表决定了后面每一步的工作量")

    rows = [
        ["能力", "ChinaTravel 里有什么", "我们的用法", "需要新建"],
        ["数据沙箱", "10 城 7 表，确定性算价算时", "直接复用（SandboxEnv）", "来源/有效期/版本"],
        ["约束语言", "hard_logic_py + 35 个概念函数", "当作内部 IR 复用", "锁定原语、改动代价"],
        ["约束抽取", "NL → DSL（两次 LLM 调用）", "复用接口", "问卷 + 确认 + 可解释"],
        ["候选排序", "按 DSL 通过数重排", "复用思想", "软偏好打分（画像）"],
        ["搜索", "回溯 DFS + 300 s 墙钟", "复用 checker-in-the-loop", "三预算 + 降级策略"],
        ["校验", "schema / 常识 / DSL / 偏好", "完全复用，零改造", "修订后全行程复审"],
        ["无解", "只有 error_info / least plan", "—", "三分类 + 证据 + 不放宽"],
        ["版本交互", "无（只输出 JSON）", "—", "版本表、差异视图、地图"],
    ]
    table(slide, 64, 190, 1152, rows, [1.3, 3.1, 3.0, 2.6], size=11.5, row_h=44, header_size=12.5)

    card(slide, 64, 580, 1152, 58, fill=WHITE, line=LINE)
    text(
        slide,
        88,
        598,
        1100,
        30,
        {"inline": [
            ("结论：", {"size": 12.5, "bold": True, "color": INK}),
            ("复用的 4 项让我们省掉了整个“判分”工程量；需要新建的 4 项，正好是我们项目的全部价值。", {"size": 12.5}),
        ]},
        color=INK_SOFT,
    )
    footer(slide, 7, "报告/03 §2")
    return slide


# --------------------------------------------------------------------------- 08
def s_experiments(prs):
    slide = blank(prs)
    header(slide, "阶段 ④", "四个实验，全部由官方 checker 判分", "E1 先证明裁判可信，E2/E3/E4 才可信")

    rows = [
        ["实验", "数据", "核心结果", "结论"],
        ["E1 checker 变异检测", "1 个有效方案 × 9 类变异", "9 / 9 检出，触发列符合预期", "裁判可信"],
        ["E2 构造 + 有界修复", "easy/medium/human/偏好 各 12 条", "构造 48/48，常识 47/48，hard 226→246 / 267", "无 LLM 也能落地"],
        ["E3 扰动修订", "11 个基础方案 → 40 条", "修复 28/40（70%），锁定 28/28", "最小改动可行"],
        ["E4 无解三分类", "3 类 × 6 条 = 18 条", "18/18，误判“不可行” 0 次", "不把找不到当不可能"],
    ]
    table(slide, 64, 190, 1152, rows, [2.0, 2.6, 3.6, 1.8], size=11.5, row_h=46, header_size=12.5)

    cards = [
        ("58", "条自建用例", "V1 40 + V2 18"),
        ("47/48", "常识可执行", "唯一失败是长跨城当日酒店不可达"),
        ("70%", "扰动修复率", "关门 91% / 提前离场 75% / 晚点 20%"),
        ("0", "误判“不可行”", "有见证就不说不可行"),
    ]
    x = 64
    for big, label, detail in cards:
        card(slide, x, 404, 268, 126, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
        text(slide, x + 20, 418, 228, 40, big, size=26, color=CLAY, bold=True)
        text(slide, x + 20, 462, 228, 22, label, size=12, color=INK, bold=True)
        text(slide, x + 20, 486, 230, 36, detail, size=10.5, color=MUTED, spacing=1.3)
        x += 288

    text(slide, 64, 552, 1150, 24, "E1 是这次自己加的：先证明“判分器对 9 类典型错误都不漏”，后面的修复率才有意义。", size=12.5, color=INK_SOFT)
    footer(slide, 8, "报告/05 · results/e1–e4_*.json、experiment_tables.md")
    return slide


# --------------------------------------------------------------------------- 09
def s_e3(prs):
    slide = blank(prs)
    header(slide, "阶段 ④ E3", "扰动修复：三种扰动，三种难度", "最有价值的不是 70%，而是“去程晚点只有 20%”")

    data = CategoryChartData()
    data.categories = ["景点/餐厅关门", "必须 15:30 到站", "去程晚点"]
    data.add_series("修复成功率 %", (90.9, 75.0, 20.0))
    chart = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, P(64), P(206), P(600), P(300), data).chart
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(11)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.number_format = '0.0"%"'
    plot.data_labels.number_format_is_linked = False
    plot.series[0].format.fill.solid()
    plot.series[0].format.fill.fore_color.rgb = CLAY
    chart.value_axis.maximum_scale = 100
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    chart.value_axis.tick_labels.font.size = Pt(10)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.category_axis.tick_labels.font.size = Pt(11)
    chart.category_axis.tick_labels.font.color.rgb = INK

    card(slide, 692, 206, 524, 150, fill=WHITE, line=LINE)
    text(slide, 716, 220, 470, 24, "整体", size=12, color=MUTED, bold=True)
    text(slide, 716, 246, 470, 40, "28 / 40 = 70%", size=26, color=CLAY, bold=True)
    text(slide, 716, 288, 470, 24, "锁定项保持 28/28  ·  平均改动代价 3.28 处", size=12, color=INK_SOFT)

    card(slide, 692, 372, 524, 134, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 716, 386, 470, 24, "为什么“去程晚点”只有 2/10", size=13, color=CLAY, bold=True)
    text(
        slide,
        716,
        416,
        470,
        82,
        [
            ("到达时刻是全局量 → 整段右移 → 只能放弃当天内容", {"size": 11.5}),
            ("一放弃就破坏“景点数量”计数约束", {"size": 11.5}),
            ("→ 真正需要的是“内容重排 + 计数守恒”", {"size": 11.5, "bold": True}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )

    card(slide, 64, 528, 1152, 96, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 542, 1100, 24, "这条失败直接变成了后续路线图的第一优先级", size=13, color=INK, bold=True)
    text(slide, 88, 572, 1100, 40, "于是有了后面两条工作：用高德真实路网量化“沙盒乐观”，以及给规划加 1.3× 时间余量。", size=12, color=INK_SOFT)
    footer(slide, 9, "报告/05 §E3 · results/e3_repair.json")
    return slide


# --------------------------------------------------------------------------- 10
def s_datasets(prs):
    slide = blank(prs)
    header(slide, "阶段 ④ 数据", "数据集改动：只动“约束 + 元数据 + 标签”三层", "四条准入标准：可判分 / 不动沙箱 / 有真值 / 有增量")

    rows = [
        ["编号", "改动", "加在哪", "解决什么", "状态"],
        ["M1", "锁定项 locked", "记录元数据", "「晚饭已订不能动」", "已实现"],
        ["M2", "扰动 disruption", "追加 DSL 约束", "关门 / 晚点 / 提前离场", "已实现"],
        ["M3", "改动代价 witness_cost", "记录真值", "「尽量少改」有度量", "已实现"],
        ["M4", "无解标签 + 证据", "记录标签", "「哪个要求在冲突」", "已实现"],
        ["M5", "偏好画像 profile", "记录元数据", "问卷偏好可复用、可排序", "设计完成"],
        ["M6", "数据时效字段", "POI 级元数据", "过时/缺失时拒绝下结论", "部分实现"],
    ]
    table(slide, 64, 190, 1152, rows, [0.7, 2.4, 1.9, 3.3, 1.2], size=11.5, row_h=40, header_size=12.5)

    card(slide, 64, 496, 556, 116, fill=WHITE, line=LINE)
    text(slide, 88, 510, 500, 24, "V1 shorttrip_repair（40 条）", size=13, color=INK, bold=True)
    text(slide, 88, 540, 500, 60, "扰动 = 往 query 末尾追加一条 DSL 约束，所以原查询仍有效、判分器零改造。", size=11.5, color=INK_SOFT, spacing=1.35)

    card(slide, 660, 496, 556, 116, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 510, 500, 24, "V2 shorttrip_infeasible（18 条）", size=13, color=CLAY, bold=True)
    text(slide, 684, 540, 500, 60, "三类各带可机器验证的证据：下界不等式 / 见证方案 / 沙箱缺失。", size=11.5, color=INK_SOFT, spacing=1.35)
    footer(slide, 10, "报告/04 · datasets/shorttrip_repair、shorttrip_infeasible")
    return slide


# --------------------------------------------------------------------------- 11
def s_dynamic_pipeline(prs):
    slide = blank(prs)
    header(slide, "阶段 ⑤", "动态沙盒更新：缺数据时，模型可以自己出去找", "七阶段流水线 + 8 道质量闸门 + 版本化注入")

    steps = [
        ("① 检测缺口", "checker 报 missing_key_data\n或 POI 不在表里"),
        ("② 外部取证", "高德 / 维基 / Wikidata / OSM\n每条带 URL+时间+摘要"),
        ("③ 结构化抽取", "regex+API 优先，LLM 补缺\n每字段必须有原文引文"),
        ("④ 质量闸门", "8 道硬/软关\naccept / quarantine / reject"),
        ("⑤ 版本落库", "SQLite overlay\n沙盒 CSV 一字不改"),
        ("⑥ 在线注入", "广播到 10 个活着的工具实例\n并失效派生缓存"),
        ("⑦ 重新求解", "同一 query 重规划\n仍无解才允许说“冲突”"),
    ]
    x = 64
    for index, (name, detail) in enumerate(steps):
        card(slide, x, 196, 152, 168, fill=WHITE, line=LINE)
        text(slide, x + 12, 210, 128, 40, name, size=11.5, color=CLAY, bold=True, spacing=1.15)
        text(slide, x + 12, 258, 128, 96, detail, size=9.5, color=INK_SOFT, spacing=1.4)
        if index < 6:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(x + 154), P(268), P(14), P(22))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
            arrow.line.fill.background()
            arrow.shadow.inherit = False
        x += 166

    gates = [
        ("真实性", "G1 权威来源 · G2 名称/坐标同一性 · G3 引文锚定"),
        ("合理性", "G4 城市范围 · G4b 多源坐标一致 · G5 取值格式"),
        ("完整性", "G6 必需字段 · S1 营业时间出处 · S2 官网"),
        ("可执行性", "G7 冲突检测 · G8 真实路网一致性"),
    ]
    y = 392
    for name, detail in gates:
        text(slide, 64, y, 120, 24, name, size=12, color=CLAY, bold=True)
        text(slide, 190, y, 1020, 24, detail, size=12, color=INK_SOFT)
        y += 40

    card(slide, 64, 566, 1152, 62, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(
        slide,
        88,
        582,
        1104,
        34,
        {"inline": [
            ("三态判定：", {"size": 12, "bold": True, "color": INK}),
            ("accept（落库注入） / quarantine（落库不注入，等确认） / reject（不落库）。核心原则：宁可隔离，也不猜。", {"size": 12}),
        ]},
        color=INK_SOFT,
    )
    footer(slide, 11, "报告/06 · src/shorttrip/dynamic/（7 个模块）")
    return slide


# --------------------------------------------------------------------------- 12
def s_dynamic_cases(prs):
    slide = blank(prs)
    header(slide, "阶段 ⑤ 实测", "四个案例：接受、隔离、隔离、拒绝", "冷启动，全部走真实网络数据")

    rows = [
        ["案例", "判定", "置信度", "关键依据"],
        ["南越王博物院（沙盒缺失）", "accept", "0.95", "高德坐标+09:00-17:30，维基补票价 10 元"],
        ["上海博物馆东馆（2024 新开）", "quarantine", "0.66", "只有坐标类型，无营业时间/票价 → 不猜"],
        ["广东省博物馆（沙盒已有）", "quarantine", "0.71", "检出 3 处冲突 + 路网乐观 ×1.34/×1.71"],
        ["凭空编造的场馆", "reject", "0.55", "高德返回别的 POI（相似度 0.23）→ 挡掉"],
    ]
    table(slide, 64, 190, 700, rows, [2.6, 1.2, 1.0, 3.4], size=11, row_h=42, header_size=11.5)

    card(slide, 788, 190, 428, 200, fill=WHITE, line=LINE)
    text(slide, 812, 204, 380, 24, "注入前后的硬指标（南越王）", size=13, color=INK, bold=True)
    text(
        slide,
        812,
        234,
        380,
        148,
        [
            ("表可见      ✗ → ✓", {"size": 12}),
            ("goto 可路由  ✗ → ✓（metro）", {"size": 12}),
            ("checker 接受 ✗ → ✓", {"size": 12}),
            ("方案硬约束  2/3 → 3/3 全过", {"size": 12, "bold": True, "color": CLAY}),
        ],
        color=INK_SOFT,
        spacing=1.65,
    )

    card(slide, 64, 396, 1152, 128, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 88, 410, 1100, 26, "两个真实发现（比数字更重要）", size=13, color=CLAY, bold=True)
    text(
        slide,
        88,
        442,
        1100,
        70,
        [
            ("① 沙盒把“未知营业时间”编码成 00:00–24:00：省博在沙盒里是全天开放，高德是 09:00–21:00，还有 1.4 km 坐标漂移 → 冲突检测拒绝自动覆盖。", {"size": 11.5}),
            ("② 高德对不存在的名字会模糊召回：加了名称相似度闸门后，编造场馆从“隔离”升级为“拒绝”，并给出锚定理由。", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.45,
    )

    text(slide, 64, 546, 1150, 24, "冷启动 / 热启动都验证过：新进程 rehydrate 一次性恢复 10 个工具实例的更新状态。", size=12, color=INK_SOFT)
    footer(slide, 12, "results/dynamic_update/report_cold.json、report_warm.json")
    return slide


# --------------------------------------------------------------------------- 13
def s_amap(prs):
    slide = blank(prs)
    header(slide, "阶段 ⑤ 数据源", "高德接入：一个接口拿到坐标、类型、营业时间", "3 把 key 额度轮换，避免单 key 打满")

    rows = [
        ["接口", "关键字段", "用途"],
        ["v5/place/text（show_fields=business）", "name / type / location / opentime_week", "主力：坐标+类型+营业时间"],
        ["v3/place/detail", "biz_ext.opentime2 / website / alias", "官网、别名"],
        ["v3/geocode/geo", "formatted_address / location", "名称歧义时二次定位"],
        ["v3/direction/{walking,transit}", "真实距离 / 时长 / 票价", "校验沙盒合成路网"],
        ["v3/weather/weatherInfo", "weather / temperature", "降雨 → 改室内扰动"],
    ]
    table(slide, 64, 190, 720, rows, [2.8, 2.6, 2.2], size=10.5, row_h=38, header_size=11)

    card(slide, 808, 190, 408, 168, fill=WHITE, line=LINE)
    text(slide, 832, 204, 360, 24, "接入后带来的三个确定性", size=13, color=INK, bold=True)
    text(
        slide,
        832,
        234,
        360,
        116,
        [
            ("· 营业时间来自结构化字段，不再靠 LLM 猜", {"size": 11.5}),
            ("· 坐标顺序坑已处理（高德 lon,lat）", {"size": 11.5}),
            ("· 抽取可完全不用 LLM，置信度反而更高", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.55,
    )

    card(slide, 808, 372, 408, 152, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 832, 386, 360, 24, "额度策略", size=13, color=CLAY, bold=True)
    text(
        slide,
        832,
        414,
        360,
        100,
        [
            ("3 把 key 轮询：遇到 10003/10004/10021/10044", {"size": 11.5}),
            ("（日额度/并发/权限）自动切下一把并重试；", {"size": 11.5}),
            ("网络异常也 fallthrough。", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.5,
    )

    card(slide, 64, 486, 1152, 110, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 500, 1100, 26, "顺带确认的两件事", size=13, color=INK, bold=True)
    text(
        slide,
        88,
        530,
        1100,
        54,
        [
            ("· DeepSeek 没有 web-search 接口（/search 与 web_search tool 都不存在）→ 联网取证落在地图/百科，LLM 只做抽取。", {"size": 11.5}),
            ("· 天气接口可用：广州实测「多云 30℃」不触发约束；降雨时才生成“至少一个室内场馆”的 DSL 约束。", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.45,
    )
    footer(slide, 13, "report 06 §8 · results/amap_probe.json · scripts/probe_amap.py")
    return slide


# --------------------------------------------------------------------------- 14
def s_route(prs):
    slide = blank(prs)
    header(slide, "阶段 ⑤ 发现", "沙盒的路网是“合成”的：时间系统性乐观 1.3–1.7 倍", "这直接动摇“沙盒判定可行 = 现实可行”的前提")

    data = CategoryChartData()
    data.categories = ["南越王博物院", "广东省博物馆"]
    data.add_series("沙盒 goto（分钟）", (39.7, 36.6))
    data.add_series("高德公交（分钟）", (54.2, 62.4))
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, P(64), P(196), P(620), P(300), data).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(11)
    chart.legend.font.color.rgb = INK_SOFT
    plot = chart.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(11)
    plot.data_labels.font.color.rgb = INK
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for series, color in zip(plot.series, (BLUE, CLAY)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    chart.value_axis.maximum_scale = 80
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xEA, 0xE7)
    chart.value_axis.tick_labels.font.size = Pt(10)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.category_axis.tick_labels.font.size = Pt(11)
    chart.category_axis.tick_labels.font.color.rgb = INK

    rows = [
        ["POI（广州南站出发）", "沙盒", "高德", "倍数"],
        ["南越王博物院 walk", "185.3", "291.9", "×1.58"],
        ["南越王博物院 transit", "39.7", "54.2", "×1.37"],
        ["广东省博物馆 walk", "193.7", "271.8", "×1.40"],
        ["广东省博物馆 transit", "36.6", "62.4", "×1.71"],
    ]
    table(slide, 712, 196, 504, rows, [2.6, 1.0, 1.0, 0.9], size=10.5, row_h=34, header_size=10.5)

    card(slide, 712, 386, 504, 140, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 736, 400, 460, 24, "于是有了 G8 与 1.3× 校准", size=13, color=CLAY, bold=True)
    text(
        slide,
        736,
        430,
        460,
        88,
        [
            ("G8：ratio = 高德 / 沙盒 > 1.25 → 标记 route_optimism 并扣置信度", {"size": 11}),
            ("规划：PlannerOptions.route_slack_factor = 1.3，把偏差折成时间余量", {"size": 11}),
        ],
        color=INK_SOFT,
        spacing=1.45,
    )

    text(slide, 64, 522, 620, 60, "为什么重要：一个“沙盒可行”的紧衔接行程，现实中可能赶不上——这是基准本身的可信度问题，不是我们方法的瑕疵。", size=12, color=INK_SOFT, spacing=1.35)
    footer(slide, 14, "results/dynamic_update/route_check.json · report 06 §9")
    return slide


# --------------------------------------------------------------------------- 15
def s_pitfalls(prs):
    slide = blank(prs)
    header(slide, "复盘", "七个坑：五个来自上游/环境，两个来自我自己", "每一个都留了复现命令或日志")

    rows = [
        ["坑", "现象", "定位 / 解法", "来源"],
        ["沙箱 zip GBK 名", "路径全乱码", "cp437→gbk 解码", "上游"],
        ["hard_logic_py 是 repr", "json.loads 崩", "ast.literal_eval 兜底", "上游"],
        ["easy 与 preference 重叠 50 uid", "loader 报 ambiguous", "别名 split 目录", "上游"],
        ["constraints.py:795 未定义变量", "from-plans 无法跑", "不复用该生成器", "上游 bug"],
        ["GBK 终端写日志", "UnicodeEncodeError 假崩", "PYTHONUTF8=1", "环境"],
        ["NO_PROXY 含 [::1]", "httpx2 Invalid port ':1]'", "清空代理变量", "环境"],
        ["PowerShell 改中文文件", "UTF-8 被当 ANSI 写坏", "改用 .py 补丁脚本", "我自己"],
    ]
    table(slide, 64, 190, 1152, rows, [2.8, 2.6, 2.8, 1.2], size=10.5, row_h=38, header_size=11)

    card(slide, 64, 492, 556, 150, fill=WHITE, line=LINE)
    text(slide, 88, 506, 500, 24, "最后那个坑值得单说", size=13, color=INK, bold=True)
    text(
        slide,
        88,
        536,
        500,
        96,
        [
            ("同一轮里我两次用 PowerShell 做多行替换，", {"size": 11.5}),
            ("把 sources.py 的 AmapSource.fetch 直接吞掉，", {"size": 11.5}),
            ("演示当场 AttributeError。", {"size": 11.5, "bold": True}),
            ("→ 之后统一改成「写 .py 补丁脚本 → 执行 → 校验」。", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )

    card(slide, 660, 492, 556, 150, fill=CLAY_L, line=RGBColor(0xE6, 0xC8, 0xB6))
    text(slide, 684, 506, 500, 24, "LLM 基线为什么还没跑", size=13, color=CLAY, bold=True)
    text(
        slide,
        684,
        536,
        500,
        96,
        [
            ("不是模型问题：v4-pro / v4.1-flash 都报同一句", {"size": 11.5}),
            ("ValueError: invalid literal for int() ... ':1]'", {"size": 11, "font": "Consolas"}),
            ("根因是 httpx2 解析 NO_PROXY 里的 [::1]。", {"size": 11.5, "bold": True}),
            ("→ 清代理变量 + --llm deepseek-flash（不带斜杠）", {"size": 11.5}),
        ],
        color=INK_SOFT,
        spacing=1.4,
    )
    footer(slide, 15, "报告/01 §6 · results/e0_llm_act_flash2.log（完整 traceback）")
    return slide


# --------------------------------------------------------------------------- 16
def s_deliverables(prs):
    slide = blank(prs)
    header(slide, "交付物", "六份报告、12 个模块、12 个脚本、2 个数据集", "全部可重跑，结果 JSON 逐项可复核")

    groups = [
        (
            "报告（6 篇 · 约 84 KB）",
            [
                "01 复现与环境搭建",
                "02 架构与数据集剖析",
                "03 我们的架构与映射",
                "04 数据集改动方案",
                "05 实验与结论",
                "06 缺数据时的动态更新",
            ],
            BLUE,
        ),
        (
            "代码（12 模块 · 约 5.4k 行）",
            [
                "env / plan / checker",
                "planner / scheduler / repair",
                "dataset / infeasibility",
                "dynamic：records/sources",
                "extract / quality / overlay",
                "bus / pipeline",
            ],
            CLAY,
        ),
        (
            "数据与结果",
            [
                "V1 修订 40 条（含见证）",
                "V2 无解 18 条（含证据）",
                "overlay：版本化沙盒",
                "evidence_cache：7 天可复核",
                "e1–e4 结果 JSON",
                "高德探测 + 路网对比",
            ],
            RGBColor(0x2A, 0x7A, 0x6A),
        ),
    ]
    x = 64
    for title, items, color in groups:
        card(slide, x, 190, 372, 330, fill=WHITE, line=LINE)
        text(slide, x + 20, 204, 330, 26, title, size=13.5, color=color, bold=True)
        y = 242
        for item in items:
            text(slide, x + 20, y, 330, 24, "· " + item, size=11.5, color=INK_SOFT)
            y += 34
        x += 396

    card(slide, 64, 546, 1152, 92, fill=RGBColor(0xEE, 0xF4, 0xF1), line=LINE)
    text(slide, 88, 560, 1100, 26, "重跑只需要三条命令", size=13, color=INK, bold=True)
    text(
        slide,
        88,
        590,
        1100,
        36,
        "python scripts/build_shorttrip_datasets.py  ·  python -m shorttrip.experiments  ·  python scripts/demo_dynamic_sandbox.py --fresh",
        size=11.5,
        color=INK_SOFT,
        font="Consolas",
    )
    footer(slide, 16, "reproduction/README.md · 报告/")
    return slide


# --------------------------------------------------------------------------- 17
def s_limits(prs):
    slide = blank(prs)
    header(slide, "边界与下一步", "四个限制，四条下一步", "按性价比排序，不藏问题")

    items = [
        ("LLM 基线未跑通", "根因已定位（httpx2 + NO_PROXY），修复路径明确但未验证", "清代理变量 + --llm deepseek-flash，补 Act/ReAct 三档"),
        ("高德模糊召回", "编造名称可能命中近似 POI，目前落到 quarantine", "编辑距离 + alias 别名表，把新名字要求第二个独立来源"),
        ("天气/接驳未接线", "amap_weather / amap_transit 已可用，未进 planner", "降雨生成室内约束；transit 时间替换城际接驳"),
        ("V1/V2 规模小", "40 / 18 条，来自 11 个基础方案", "扩到 100+ 条；补“多解与替代集”"),
    ]
    y = 190
    for title, why, fix in items:
        card(slide, 64, y, 1152, 104, fill=WHITE, line=LINE)
        text(slide, 88, y + 14, 380, 24, title, size=13, color=CLAY, bold=True)
        text(slide, 88, y + 44, 470, 50, why, size=11, color=INK_SOFT, spacing=1.3)
        arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, P(576), P(y + 46), P(24), P(22))
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = RGBColor(0xC9, 0xD5, 0xD0)
        arrow.line.fill.background()
        arrow.shadow.inherit = False
        text(slide, 620, y + 14, 570, 24, "下一步", size=11, color=MUTED, bold=True)
        text(slide, 620, y + 44, 570, 50, fix, size=11, color=INK, spacing=1.3)
        y += 120
    footer(slide, 17, "报告/06 §11 · README 已知限制")
    return slide


# --------------------------------------------------------------------------- 18
def s_conclusion(prs):
    slide = blank(prs, paper=False)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = INK
    bg.line.fill.background()
    bg.shadow.inherit = False

    pill(slide, 96, 84, 132, 32, "结论", RGBColor(0x2A, 0x4A, 0x43), MINT, size=12)
    text(slide, 96, 136, 1080, 46, "四句话带走", size=32, color=WHITE, bold=True)

    rows = [
        ("复现是地基", "官方数据、沙箱、四闸门在本机跑通；85% 的判分工程量因此省掉，只剩 LLM 求解需要额度。"),
        ("架构是增量", "锁定、改动代价、无解三分类、版本差异——都在官方 checker 上判分：修复 70%、锁定 28/28、分类 18/18。"),
        ("数据改动很小", "只动约束与元数据，不动沙箱；原 split 分数不受影响，新 split 才承载新能力。"),
        ("动态更新是闭环", "缺数据 → 取证 → 八道闸门 → 版本化注入 → 重规划；并顺手证明了沙盒路网乐观 1.3–1.7 倍。"),
    ]
    y = 200
    for index, (title, detail) in enumerate(rows):
        text(slide, 96, y, 60, 40, f"0{index + 1}", size=24, color=RGBColor(0xE0, 0xA3, 0x7E), bold=True)
        text(slide, 168, y - 2, 340, 32, title, size=20, color=WHITE, bold=True)
        text(slide, 168, y + 32, 1000, 50, detail, size=13.5, color=RGBColor(0xC9, 0xDD, 0xD6), spacing=1.4)
        y += 118

    text(slide, 96, 660, 1000, 24, "下一步：LLM 基线 → 别名收口 → 天气/接驳接线 → 规模扩到 100+", size=12.5, color=RGBColor(0x8F, 0xA9, 0xA2))
    return slide


def main() -> int:
    prs = new_deck()
    s_cover(prs)
    s_overview(prs)
    s_phase1(prs)
    s_phase1_result(prs)
    s_phase2(prs)
    s_our_arch(prs)
    s_mapping(prs)
    s_experiments(prs)
    s_e3(prs)
    s_datasets(prs)
    s_dynamic_pipeline(prs)
    s_dynamic_cases(prs)
    s_amap(prs)
    s_route(prs)
    s_pitfalls(prs)
    s_deliverables(prs)
    s_limits(prs)
    s_conclusion(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT} slides={len(prs.slides)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
