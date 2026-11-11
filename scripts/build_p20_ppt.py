"""Build the P20 DeepSeek dynamic-sandbox report deck (editable PowerPoint)."""
from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
OUT = PROJECT / 'output/ppt/P20_DeepSeek动态沙盒实测_20261023.pptx'
COVER = PROJECT / '.ppt-report-dynamic-20261022/cover.png'

NAVY = RGBColor(0x14, 0x2B, 0x3C)
TEAL = RGBColor(0x20, 0x7E, 0x80)
TEAL_DARK = RGBColor(0x18, 0x5F, 0x61)
TEAL_LIGHT = RGBColor(0xE7, 0xF2, 0xF1)
MUTED = RGBColor(0x53, 0x65, 0x71)
LINE = RGBColor(0xD9, 0xE1, 0xE3)
BG = RGBColor(0xFC, 0xFB, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xE8, 0xEE, 0xEB)
AMBER = RGBColor(0xC9, 0x8A, 0x3C)
AMBER_LIGHT = RGBColor(0xFB, 0xF2, 0xE6)
RED = RGBColor(0xA9, 0x4B, 0x42)
RED_LIGHT = RGBColor(0xF8, 0xEB, 0xE9)
GREEN = RGBColor(0x2E, 0x7D, 0x5B)
GREEN_LIGHT = RGBColor(0xEA, 0xF3, 0xEE)
FONT = 'Microsoft YaHei'


def add_text(slide, text, x, y, w, h, size=14, color=NAVY, bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.0,
             space_after=0, font=FONT):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    p.space_after = Pt(space_after)
    run = p.add_run()
    run.text = str(text)
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return shape


def add_list(slide, items, x, y, w, h, size=13, color=MUTED, bullet='·', gap=5, line_spacing=1.12):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = line_spacing
        p.space_after = Pt(gap)
        r = p.add_run()
        r.text = f'{bullet} {item}'
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.color.rgb = color
    return shape


def add_card(slide, x, y, w, h, fill=WHITE, line=LINE, radius=0.06, line_width=0.8):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(line_width)
    return shape


def add_chip(slide, text, x, y, w, h, fill=TEAL_LIGHT, color=TEAL_DARK, size=10.5, bold=True):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = 0.25
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    tf = shape.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color


def add_kpi(slide, x, y, w, h, number, label, note='', color=TEAL):
    add_card(slide, x, y, w, h, fill=WHITE, line=LINE)
    add_text(slide, number, x + 0.22, y + 0.18, w - 0.44, 0.66, size=30, color=color, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)
    add_text(slide, label, x + 0.22, y + 0.88, w - 0.44, 0.3, size=12, color=NAVY, bold=True)
    if note:
        add_text(slide, note, x + 0.22, y + 1.16, w - 0.44, 0.3, size=10, color=MUTED)


def add_table(slide, data, x, y, w, h, col_widths=None, font_size=11.5, header_size=11.5,
              row_height=None, aligns=None):
    rows, cols = len(data), len(data[0])
    shape = slide.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(h))
    table = shape.table
    table.first_row = True
    table.horz_banding = False
    if col_widths:
        for i, cw in enumerate(col_widths):
            table.columns[i].width = Inches(cw)
    body_h = (h - (row_height or 0.42)) / max(1, rows - 1)
    for r, row in enumerate(data):
        table.rows[r].height = Inches(row_height if r == 0 and row_height else body_h)
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r == 0 else (WHITE if r % 2 == 1 else LIGHT)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = (aligns[c] if aligns else (PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER))
            run = p.add_run()
            run.text = str(value)
            run.font.name = FONT
            run.font.size = Pt(header_size if r == 0 else font_size)
            run.font.bold = r == 0
            run.font.color.rgb = WHITE if r == 0 else NAVY
    return table


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width = Inches(13.333)
        self.prs.slide_height = Inches(7.5)
        self.n = 0
        self.total = 14

    def new(self, bg=BG):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = bg
        self.n += 1
        return slide

    def header(self, slide, title, subtitle):
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.67), Inches(0.46), Inches(0.08), Inches(0.62))
        bar.fill.solid(); bar.fill.fore_color.rgb = TEAL; bar.line.fill.background()
        add_text(slide, title, 0.9, 0.38, 11.55, 0.62, size=27, color=NAVY, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(slide, subtitle, 0.9, 1.05, 11.7, 0.38, size=14.5, color=MUTED)
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.67), Inches(1.55), Inches(12.0), Inches(0.012))
        line.fill.solid(); line.fill.fore_color.rgb = LINE; line.line.fill.background()
        add_text(slide, 'P20 · DeepSeek × 扩展动态沙盒', 0.67, 7.08, 5.0, 0.22, size=9.5, color=MUTED)
        add_text(slide, f'{self.n:02d} / {self.total}', 11.85, 7.08, 0.8, 0.22, size=9.5,
                 color=MUTED, align=PP_ALIGN.RIGHT)

    def notes(self, slide, text):
        slide.notes_slide.notes_text_frame.text = text

    def save(self):
        OUT.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(OUT)


def cover(d):
    slide = d.new(WHITE)
    slide.shapes.add_picture(str(COVER), 0, 0, width=d.prs.slide_width, height=d.prs.slide_height)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.76), Inches(1.35), Inches(0.62), Inches(0.055))
    line.fill.solid(); line.fill.fore_color.rgb = TEAL; line.line.fill.background()
    add_text(slide, 'P20 · 研究检查点 2026.10.23', 0.76, 1.02, 6.2, 0.3, size=13, color=TEAL, bold=True)
    add_text(slide, '扩展沙盒里的 DeepSeek\nQuery → Plan 实测', 0.76, 1.55, 6.35, 1.9,
             size=31, color=NAVY, bold=True, line_spacing=1.08)
    add_text(slide, '4 条旅行请求 · 9 份候选日程 · 21 条动态证据', 0.78, 3.58, 6.0, 0.4,
             size=16, color=TEAL_DARK)
    add_text(slide, 'ChinaTravel 结构 × 新沙盒 × 外部 LLM', 0.78, 4.05, 5.8, 0.32,
             size=12.5, color=MUTED)
    add_chip(slide, '9/9 交付   ·   0/9 严格接纳', 0.78, 5.55, 3.55, 0.46,
             fill=NAVY, color=WHITE, size=12)
    add_text(slide, '证据入口：results/p20_deepseek_dynamic_sandbox/', 0.78, 6.55, 6.0, 0.25,
             size=10, color=MUTED)
    d.notes(slide, '封面图沿用项目 2026-10-22 报告封面资产；标题与数字来自 P20 REPORT.md 与 evaluation.json。')


def summary(d):
    slide = d.new()
    d.header(slide, '闭环跑通，但还没有一份计划被证明可执行',
             '4 条 query、4 份动态稿、1 次修订：交付不是问题，硬约束证明才是问题')
    kpis = [
        ('9 / 9', '候选计划交付', '4 static + 4 dynamic + 1 revised', TEAL),
        ('0 / 9', '严格接纳', '无 fail、无 unknown 且原生 schema 通过', RED),
        ('21 → 0', 'claims 升级为硬事实', '全部 unverified；0 hard / 0 estimate', AMBER),
        ('61 / 1.07M', 'API 调用 / tokens', 'temperature 0；1,065,939 tokens', NAVY),
    ]
    for i, (num, label, note, color) in enumerate(kpis):
        add_kpi(slide, 0.67 + i * 3.12, 1.82, 2.92, 1.55, num, label, note, color)
    add_card(slide, 0.67, 3.72, 7.55, 2.35, fill=WHITE, line=LINE)
    add_text(slide, '这一轮实际发生了什么', 0.93, 3.92, 6.8, 0.32, size=14, color=NAVY, bold=True)
    add_list(slide, [
        '49 次 gateway 工具调用：模型真实读取库内候选、实体和会话 claims。',
        'D01 补门票/午餐/天气成本；D03 补钟楼/碑林票价，并在修订中把碑林换成大明宫。',
        '21 条动态 claims 仍全部 unverified：预算、房态、到达时间无法被证明。',
    ], 0.93, 4.33, 6.9, 1.55, size=11.5, color=MUTED, gap=7)
    add_card(slide, 8.48, 3.72, 4.17, 2.35, fill=NAVY, line=None)
    add_text(slide, '一句话', 8.75, 3.96, 3.6, 0.25, size=11, color=RGBColor(0x9F, 0xC9, 0xC7), bold=True)
    add_text(slide, '能力闭环\n已经跑通；\n硬约束闭环\n还没有。', 8.75, 4.3, 3.55, 1.55,
             size=23, color=WHITE, bold=True, line_spacing=1.05)
    add_text(slide, '不是官方 DR/EPR/LPR/FPR；不是现实准确率；unknown 不计通过，也不是无解。',
             0.67, 6.42, 12.0, 0.28, size=10.5, color=MUTED)
    d.notes(slide, 'KPI 来自 evaluation.json metrics 与 summary.json；claims 来自 overlay/v001/manifest.json。')


def design(d):
    slide = d.new()
    d.header(slide, '实验设计：用 ChinaTravel 的结构，跑我们自己的沙盒',
             'query → 工具 → static_first → 动态检索/门禁 → dynamic_first → 独立检查')
    stages = [
        ('01', 'Query', '4 条自然语言请求'),
        ('02', '沙盒工具', 'TAG / 名称 / evidence'),
        ('03', 'static_first', '先封存首稿'),
        ('04', '动态检索', '16 搜索 / 24 打开'),
        ('05', 'dynamic / 修订', '读证据再改稿'),
    ]
    for i, (num, title, note) in enumerate(stages):
        x = 0.67 + i * 2.45
        add_card(slide, x, 1.82, 2.05, 1.02, fill=WHITE, line=LINE)
        add_text(slide, num, x + 0.15, 1.92, 0.4, 0.24, size=10, color=TEAL, bold=True)
        add_text(slide, title, x + 0.15, 2.14, 1.75, 0.28, size=12.5, color=NAVY, bold=True)
        add_text(slide, note, x + 0.15, 2.44, 1.8, 0.26, size=9.5, color=MUTED)
        if i < len(stages) - 1:
            add_text(slide, '→', x + 2.08, 2.18, 0.3, 0.3, size=14, color=TEAL, align=PP_ALIGN.CENTER)
    add_text(slide, '四个案例', 0.67, 3.12, 4.0, 0.3, size=14, color=NAVY, bold=True)
    cases = [
        ('D01', '长沙 · 1 天', '历史文化 · 午餐不辣', '预算 ¥500 · 地铁优先'),
        ('D02', '厦门 · 2 天', '自然风光 · 双床房', '预算 ¥1500 · 闽南菜'),
        ('D03', '西安 · 2 天', '历史文化 · 1 间房', '预算 ¥1200 · 地铁优先'),
        ('D04', '昆明 · 2 天', '自然风光 · 1 间房', '预算 ¥1000 · 云南特色'),
    ]
    for i, (cid, city, theme, note) in enumerate(cases):
        x = 0.67 + (i % 2) * 3.15
        y = 3.48 + (i // 2) * 1.42
        add_card(slide, x, y, 2.95, 1.22, fill=WHITE, line=LINE)
        add_text(slide, cid, x + 0.16, y + 0.12, 0.5, 0.25, size=10, color=TEAL, bold=True)
        add_text(slide, city, x + 0.16, y + 0.36, 2.5, 0.3, size=14, color=NAVY, bold=True)
        add_text(slide, theme, x + 0.16, y + 0.68, 2.55, 0.24, size=10.5, color=MUTED)
        add_text(slide, note, x + 0.16, y + 0.93, 2.55, 0.22, size=9.5, color=MUTED)
    add_card(slide, 7.35, 3.12, 5.3, 3.0, fill=TEAL_LIGHT, line=None)
    add_text(slide, '协议与边界', 7.65, 3.32, 4.6, 0.3, size=14, color=TEAL_DARK, bold=True)
    add_list(slide, [
        'D01/D02 复用 P19 同 query，D03/D04 为新城市泛化。',
        '隐藏机器约束、participant prompt、evaluator 初始冻结；首稿后仅有实现修复。',
        '不是官方 split，没有已知可行解见证。',
        '高德暂停、浏览器关闭、无本地模型；模型只能通过 gateway 行动。',
    ], 7.65, 3.7, 4.7, 2.15, size=10.5, color=NAVY, gap=6)
    add_text(slide, '出行日期统一为 2026-10-24 / 25；D01 1 天，其余 2 天。',
             0.67, 6.72, 12.0, 0.28, size=10, color=MUTED)
    d.notes(slide, '流程对应 p20_agent.py 的 static/dynamic/revised 三阶段；四个 query 在 public/queries.json。')


def architecture(d):
    slide = d.new()
    d.header(slide, '被测系统：隔离 gateway + 可追溯证据层',
             '模型不读文件、不联网；所有库内事实和动态证据都必须经过 gateway')
    boxes = [
        (0.67, 1.85, 3.15, 1.15, 'DeepSeek v4-pro', '只输出 JSON action\ntemperature 0', WHITE),
        (4.25, 1.85, 4.35, 1.15, 'Gateway 工具', 'lookup / find_name / evidence\nrequest_live / submit', WHITE),
        (9.0, 1.85, 3.65, 1.15, '扩展沙盒（只读）', '30 城 · 14,057 实体\nSHA-256 固定', WHITE),
    ]
    for x, y, w, h, title, body, fill in boxes:
        add_card(slide, x, y, w, h, fill=fill, line=LINE)
        add_text(slide, title, x + 0.18, y + 0.14, w - 0.36, 0.3, size=14, color=NAVY, bold=True)
        add_text(slide, body, x + 0.18, y + 0.52, w - 0.36, 0.55, size=10, color=MUTED)
    for x in (3.9, 8.68):
        add_text(slide, '→', x, 2.22, 0.28, 0.28, size=15, color=TEAL, align=PP_ALIGN.CENTER)
    add_text(slide, '↓ evidence / request_live', 5.75, 3.06, 1.9, 0.24, size=9, color=MUTED, align=PP_ALIGN.CENTER)
    add_card(slide, 4.25, 3.42, 4.35, 1.15, fill=WHITE, line=LINE)
    add_text(slide, '正常实时检索', 4.43, 3.55, 3.7, 0.28, size=13, color=NAVY, bold=True)
    add_text(slide, '16 搜索 query · 24 次来源打开\n22 页保存 / 2 失败 / 4 挑战页', 4.43, 3.9, 3.95, 0.55,
             size=10, color=MUTED)
    add_card(slide, 9.0, 3.42, 3.65, 1.15, fill=TEAL_LIGHT, line=None)
    add_text(slide, '逐字引文 + 哈希 + 门禁', 9.18, 3.55, 3.3, 0.28, size=13, color=TEAL_DARK, bold=True)
    add_text(slide, 'overlay v001 · 21 claims\n21 unverified / 0 hard', 9.18, 3.9, 3.2, 0.55,
             size=10, color=NAVY)
    add_text(slide, '↓', 10.72, 4.67, 0.3, 0.28, size=15, color=TEAL, align=PP_ALIGN.CENTER)
    add_card(slide, 9.0, 5.18, 3.65, 1.12, fill=AMBER_LIGHT, line=None)
    add_text(slide, '独立 evaluator', 9.18, 5.31, 3.25, 0.28, size=13, color=AMBER, bold=True)
    add_text(slide, '官方 schema + DSL 子集\n项目三值检查', 9.18, 5.64, 3.25, 0.52, size=10, color=NAVY)
    add_card(slide, 0.67, 5.18, 8.05, 1.12, fill=WHITE, line=LINE)
    add_text(slide, '边界', 0.85, 5.31, 1.0, 0.28, size=12, color=NAVY, bold=True)
    add_text(slide, 'Amap 0 调用 · 浏览器 / CUA 0 次 · 本地模型 0 个；失败来源写入暂停账本，同域不重试。',
             0.85, 5.64, 7.55, 0.4, size=10.5, color=MUTED)
    add_text(slide, '正式库 SHA-256：bd8e6e97…b9210（14,057 实体；planning_ready = 0）',
             0.67, 6.55, 12.0, 0.25, size=9.5, color=MUTED)
    d.notes(slide, '架构对应 p20_agent.py Gateway 与 p20_live_fetch.py；数字来自 summary.json 与 live/ 目录。')


def baseline(d):
    slide = d.new()
    d.header(slide, '沙盒基线：记录很多，可规划字段很少',
             '14,057 条实体里，原生价格、营业时间和床位数都只是稀疏存在')
    data = [
        ['类型', '记录数', '原生价格', '原生营业时间', '明确床数'],
        ['景点', '3,376', '11', '54', '—'],
        ['餐厅', '4,601', '277', '115', '—'],
        ['住宿', '6,080', '2', '0', '167'],
        ['合计', '14,057', '290', '169', '167'],
    ]
    add_table(slide, data, 0.67, 1.9, 7.45, 2.55, col_widths=[1.7, 1.3, 1.25, 1.55, 1.25],
              font_size=11.5, header_size=11.5, row_height=0.44)
    kpis = [
        ('30', '城市', TEAL),
        ('8,548', '范围断言', TEAL),
        ('0', 'planning_ready', AMBER),
        ('10', '存储房型报价', AMBER),
    ]
    for i, (num, label, color) in enumerate(kpis):
        x = 8.55 + (i % 2) * 2.0
        y = 1.9 + (i // 2) * 1.18
        add_card(slide, x, y, 1.86, 1.08, fill=WHITE, line=LINE)
        add_text(slide, num, x + 0.16, y + 0.12, 1.55, 0.5, size=25, color=color, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(slide, label, x + 0.16, y + 0.7, 1.55, 0.26, size=10.5, color=NAVY, bold=True)
    add_text(slide, '30 城覆盖 · 8,548 条范围断言 / 590 个来源 URL\nplanning_ready = 0 · 10 条存储报价均过期',
             8.55, 4.22, 3.9, 0.55, size=9, color=MUTED, line_spacing=1.1)
    add_card(slide, 0.67, 4.75, 12.0, 1.45, fill=AMBER_LIGHT, line=None)
    add_text(slide, '覆盖率决定了“动态检索是必需项”', 0.92, 4.93, 6.5, 0.3, size=13, color=AMBER, bold=True)
    add_text(slide, '原生价格覆盖率：景点 0.3%（11/3,376）、餐厅 6.0%（277/4,601）、住宿 0.03%（2/6,080）。'
                    '原生价格、营业时间和床位数不能支撑日期级预算/库存；动态检索必须介入。',
             0.92, 5.3, 11.4, 0.65, size=11.5, color=NAVY)
    add_text(slide, '数据源：results/p17_continuous/current_status.json；基线 SHA-256 未变。',
             0.67, 6.55, 12.0, 0.25, size=9.5, color=MUTED)
    d.notes(slide, '记录数、原生字段计数与 planning_ready 来自 p17_continuous/current_status.json coverage。')


def cases(d):
    slide = d.new()
    d.header(slide, '四条请求，九份计划', 'pass · fail · unknown；D01/D02 与 P19 同 query，D03/D04 新城市泛化')
    data = [
        ['Case', '城市 / 天数', '主题 / 预算', 'static', 'dynamic', '修订'],
        ['D01', '长沙 · 1 天', '历史 / ¥500', '17 · 1 · 6', '17 · 2 · 5', '—'],
        ['D02', '厦门 · 2 天', '自然 + 双床 / ¥1500', '15 · 2 · 8', '16 · 2 · 7', '—'],
        ['D03', '西安 · 2 天', '历史 / ¥1200', '16 · 2 · 7', '17 · 2 · 6', '19 · 2 · 6'],
        ['D04', '昆明 · 2 天', '自然 / ¥1000', '15 · 2 · 8', '16 · 2 · 7', '—'],
    ]
    add_table(slide, data, 0.67, 1.9, 8.4, 3.25, col_widths=[0.8, 1.35, 2.1, 1.3, 1.3, 1.3],
              font_size=12, header_size=11.5, row_height=0.48)
    add_card(slide, 9.35, 1.9, 3.3, 3.25, fill=TEAL_LIGHT, line=None)
    add_text(slide, 'D03 修订', 9.6, 2.1, 2.8, 0.3, size=14, color=TEAL_DARK, bold=True)
    add_list(slide, [
        '排除碑林博物馆',
        '换入大明宫国家遗址公园',
        '保留钟楼 / 酒店 / 两顿午餐 / 起终点',
        '4/4 锁定项保留；19 pass，为全轮最高',
    ], 9.6, 2.5, 2.75, 2.15, size=10.5, color=NAVY, gap=5)
    add_text(slide, '9/9 交付；0/9 strict；所有计划都保留 unknown，没有把缺口隐藏成完成。',
             0.67, 5.55, 12.0, 0.4, size=13, color=NAVY, bold=True)
    add_text(slide, '注：表格中的三个数字依次为 pass / fail / unknown。',
             0.67, 6.55, 12.0, 0.25, size=9.5, color=MUTED)
    d.notes(slide, '逐阶段数字来自 evaluation.json；D03 修订检查见 evaluation.json 与 revision.json。')


def results(d):
    slide = d.new()
    d.header(slide, '结果：结构性检查全过，严格接纳仍是 0',
             '148 pass / 17 fail / 60 unknown；unknown 没有被算作通过')
    chart_data = CategoryChartData()
    chart_data.categories = ['static（4 份）', 'dynamic（4 份）', 'revised（1 份）']
    chart_data.add_series('pass', (63, 66, 19))
    chart_data.add_series('fail', (7, 8, 2))
    chart_data.add_series('unknown', (29, 25, 6))
    gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(0.67), Inches(1.85),
                                Inches(6.35), Inches(4.25), chart_data)
    chart = gf.chart
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.font.name = FONT
    chart.font.size = Pt(10)
    chart.font.color.rgb = MUTED
    plot = chart.plots[0]
    plot.gap_width = 55
    plot.overlap = 100
    plot.has_data_labels = True
    plot.data_labels.font.name = FONT
    plot.data_labels.font.size = Pt(9)
    plot.data_labels.font.bold = True
    for series, color, label_color in zip(chart.series, (GREEN, RED, AMBER), (WHITE, WHITE, NAVY)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
        series.data_labels.font.color.rgb = label_color
    chart.value_axis.maximum_scale = 100
    chart.value_axis.minimum_scale = 0
    chart.value_axis.has_major_gridlines = False
    chart.value_axis.tick_labels.font.size = Pt(9)
    chart.value_axis.tick_labels.font.color.rgb = MUTED
    chart.category_axis.tick_labels.font.size = Pt(9)
    chart.category_axis.tick_labels.font.color.rgb = NAVY
    add_card(slide, 7.3, 1.85, 5.35, 1.35, fill=GREEN_LIGHT, line=None)
    add_text(slide, '148 pass', 7.52, 1.98, 2.2, 0.45, size=20, color=GREEN, bold=True)
    add_text(slide, '10 项结构检查 × 9 份计划：天数、人数、景点、主题、午餐、时序、起终点全部通过。',
             7.52, 2.45, 4.9, 0.6, size=10, color=NAVY)
    add_card(slide, 7.3, 3.35, 5.35, 1.35, fill=RED_LIGHT, line=None)
    add_text(slide, '17 fail', 7.52, 3.48, 2.2, 0.45, size=20, color=RED, bold=True)
    add_text(slide, '9 原生 schema + 7 hotel_room_count + 1 zero_cost；没有其他硬约束违反。',
             7.52, 3.95, 4.9, 0.6, size=10, color=NAVY)
    add_card(slide, 7.3, 4.85, 5.35, 1.55, fill=AMBER_LIGHT, line=None)
    add_text(slide, '60 unknown', 7.52, 4.98, 2.5, 0.45, size=20, color=AMBER, bold=True)
    add_text(slide, '预算 9 · 开放/门票 9 · 高德路线 9 · 天气 9\n不辣 7 · 日期房态 7 · 动态证据消费 4 · 地铁 4 · 双床 2',
             7.52, 5.42, 4.95, 0.8, size=9.5, color=NAVY)
    add_text(slide, 'static 63 / 7 / 29   ·   dynamic 66 / 8 / 25   ·   revised 19 / 2 / 6',
             0.67, 6.22, 6.35, 0.25, size=9, color=MUTED)
    add_text(slide, 'strict = 无 fail + 无 unknown + 原生 schema 通过；当前 0/9。',
             0.67, 6.55, 12.0, 0.28, size=10, color=MUTED)
    d.notes(slide, '图表数据来自 evaluation.json 的 9 份计划；unknown 分项由 adapted_evidence_aware_checks 聚合。')


def why_zero(d):
    slide = d.new()
    d.header(slide, '为什么 0 严格接纳：三类硬缺口',
             '不是评分口径把 unknown 当 fail，而是 schema、字段和证据都没有闭合')
    cards = [
        ('01', '接口', '原生 schema 0/9', RED_LIGHT, RED, [
            '计划使用 start / end 扩展锚点，官方 schema 不认。',
            '未知 cost / price / transport 保留 null，schema 要求 number。',
            '填 0 能过 schema，但会伪造未知价格，不能做。',
        ], '影响：官方评分无法直接运行'),
        ('02', '字段', '住宿 0/4', AMBER_LIGHT, AMBER, [
            '4 个住宿 case 都没有写 rooms。',
            'D04 还重复放了 2 个 accommodation 活动。',
            'prompt 模板未列 rooms / room_type / single_beds，属于接口缺陷。',
        ], '影响：房型硬约束无法证明'),
        ('03', '证据', '21 claims 全 unverified', TEAL_LIGHT, TEAL_DARK, [
            '0 条 usable_as_hard_fact，0 条 labelled estimate。',
            '实体未验证、使用权未知、来源时钟未知/过期。',
            'D01 用未核实“免费”声明写 0，被 zero-cost 检查判 fail。',
        ], '影响：预算 / 到达只能保持 unknown'),
    ]
    for i, (num, tag, title, fill, color, items, impact) in enumerate(cards):
        x = 0.67 + i * 4.08
        add_card(slide, x, 1.85, 3.86, 3.75, fill=fill, line=None)
        add_text(slide, num, x + 0.24, 2.02, 0.5, 0.3, size=11, color=color, bold=True)
        add_text(slide, tag, x + 0.24, 2.3, 1.2, 0.28, size=11, color=color, bold=True)
        add_text(slide, title, x + 0.24, 2.62, 3.4, 0.42, size=17, color=color, bold=True)
        add_list(slide, items, x + 0.24, 3.18, 3.35, 1.7, size=10.3, color=NAVY, gap=7)
        add_text(slide, impact, x + 0.24, 5.02, 3.35, 0.3, size=10, color=color, bold=True)
    add_card(slide, 0.67, 5.85, 12.0, 0.72, fill=NAVY, line=None)
    add_text(slide, 'strict = schema ok + fail 0 + unknown 0', 0.92, 5.97, 5.4, 0.4,
             size=14, color=WHITE, bold=True)
    add_text(slide, '当前：schema 0 + fail 17 + unknown 60  →  0/9', 6.3, 5.97, 6.1, 0.4,
             size=13, color=RGBColor(0x9F, 0xC9, 0xC7), align=PP_ALIGN.RIGHT)
    d.notes(slide, '失败构成来自 evaluation.json：official_output_schema_ok 9 次、hotel_room_count 7 次、zero_cost 1 次。')


def dynamic(d):
    slide = d.new()
    d.header(slide, '动态检索：能拿到范围，拿不到硬事实',
             '16 条搜索、24 次打开、21 条逐字引文；门禁把它们全部留在 unverified')
    bars = [
        ('16', '搜索 query', 5.0, TEAL),
        ('24', '来源打开尝试', 4.5, TEAL),
        ('22', '页面保存（含 4 挑战页）', 4.0, TEAL),
        ('21', '逐字引文 claims', 3.5, TEAL_DARK),
        ('0', 'hard fact / labelled estimate', 2.8, AMBER),
    ]
    for i, (num, label, width, color) in enumerate(bars):
        y = 1.88 + i * 0.7
        add_card(slide, 0.67, y, width, 0.56, fill=color, line=None)
        add_text(slide, num, 0.88, y + 0.1, 0.75, 0.35, size=17, color=WHITE, bold=True)
        add_text(slide, label, 1.68, y + 0.14, width - 1.15, 0.28, size=10.5,
                 color=WHITE if color != AMBER else NAVY, bold=True)
    add_text(slide, '2 个失败包：百度百科 403、Trip.com 432；4 个保存页是验证码/验证/挑战页。',
             0.67, 5.55, 5.8, 0.65, size=9.5, color=MUTED)
    chart_data = CategoryChartData()
    chart_data.categories = ['expired · 4', 'unknown source clock · 17',
                             'usage rights unknown · 21', 'entity unverified · 21']
    chart_data.add_series('claims', (4, 17, 21, 21))
    gf = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(6.55), Inches(1.85),
                                Inches(6.05), Inches(3.5), chart_data)
    chart = gf.chart
    chart.has_title = False
    chart.has_legend = False
    chart.font.name = FONT
    chart.font.size = Pt(9)
    chart.font.color.rgb = MUTED
    plot = chart.plots[0]
    plot.gap_width = 55
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.font.bold = True
    plot.data_labels.font.color.rgb = WHITE
    series = chart.series[0]
    series.format.fill.solid()
    series.format.fill.fore_color.rgb = TEAL
    chart.value_axis.maximum_scale = 25
    chart.value_axis.has_major_gridlines = False
    chart.value_axis.visible = False
    chart.category_axis.tick_labels.font.size = Pt(9.5)
    chart.category_axis.tick_labels.font.color.rgb = NAVY
    add_text(slide, '门禁未通过原因（可多选）', 6.55, 5.45, 5.5, 0.28, size=11, color=NAVY, bold=True)
    add_text(slide, '21 条 claims 全部 unverified：0 hard / 0 labelled estimate。',
             6.55, 5.8, 5.7, 0.28, size=11, color=AMBER, bold=True)
    add_text(slide, '来源受阻：微信验证码 · 携程验证 · Trip 432 · 百度 403 · Booking 202；失败即暂停，同域不重试。',
             0.67, 6.55, 12.0, 0.25, size=9.5, color=MUTED)
    d.notes(slide, '16/24/22/2 来自 live/search_*.json 与 open_*.json；门禁原因为 overlay/v001/claims.json 的 checks。')


def consumption(d):
    slide = d.new()
    d.header(slide, '证据被读取 ≠ 被消费', 'D02 / D04 有可用 claims，但没有进入计划或断言')
    data = [
        ['Case', 'evidence 读取', '可用 claims', '引用 claim', '动态变化'],
        ['D01', '3', '9', '7', '门票 0 / 36 / 80；补天气；未用 2020 历史公告'],
        ['D02', '1', '5', '1', '只读酒店；植物园开放/票价、两日天气未消费'],
        ['D03', '3', '4', '4', '钟楼 15/30、碑林 85/170；修订换碑林'],
        ['D04', '3', '3', '2', '只写天气；翠湖开放时间未消费'],
    ]
    add_table(slide, data, 0.67, 1.9, 8.35, 3.55, col_widths=[0.75, 1.25, 1.15, 1.15, 4.05],
              font_size=10.5, header_size=10.5, row_height=0.48)
    add_card(slide, 9.3, 1.9, 3.35, 1.65, fill=TEAL_LIGHT, line=None)
    add_text(slide, 'D03 修订', 9.55, 2.05, 2.8, 0.3, size=13, color=TEAL_DARK, bold=True)
    add_list(slide, ['碑林 → 大明宫', '4/4 锁定保留', '19 pass，全轮最高'], 9.55, 2.4, 2.8, 1.0,
             size=10, color=NAVY, gap=4)
    add_card(slide, 9.3, 3.75, 3.35, 1.7, fill=AMBER_LIGHT, line=None)
    add_text(slide, '未消费', 9.55, 3.9, 2.8, 0.3, size=13, color=AMBER, bold=True)
    add_list(slide, ['D02：植物园 + 天气', 'D04：翠湖开放时间', '检索了，但没写进 plan'],
             9.55, 4.25, 2.8, 1.0, size=10, color=NAVY, gap=4)
    add_text(slide, '下一步不是“多搜”，而是让模型消费、正确引用，并把可用参考接入预算/时段。',
             0.67, 5.75, 12.0, 0.4, size=12.5, color=NAVY, bold=True)
    add_text(slide, 'evidence 读取来自 events/；可用 claims 为选中实体的 overlay claims；引用 claim 为 fact_claims 中的 p20:*。',
             0.67, 6.55, 12.0, 0.25, size=9.5, color=MUTED)
    d.notes(slide, '读取次数来自 events/*_evidence.json；可用/引用数为脚本从 plans 与 overlay 计算。')


def quality(d):
    slide = d.new()
    d.header(slide, '沙盒质量：三类问题会污染规划', '这些是数据治理问题，不是模型幻觉；在 gateway 前修更可靠')
    cards = [
        ('01', '重复实体', '同一物业，两条记录', [
            '萬達朗豪酒店 vs Langham Place Xiamen',
            '坐标相距约 20 m，疑为同一物业',
            '模型选了带房型 operator assertion 的重复项',
        ], TEAL_LIGHT, TEAL_DARK, '影响：同一物业可能被算成两个候选'),
        ('02', '候选噪声', '名字与城市不一致', [
            'Grand Park Kunmimg（拼写/城市异常）',
            '重复的 Fanta Wild Dream Land',
            'Bairuopu (köpinghuvudort i Kina...)',
        ], AMBER_LIGHT, AMBER, '影响：模型可能选到非目标城市的点'),
        ('03', 'TAG 边界', 'history/nature 可用，餐厅/酒店不足', [
            'history/nature：TAG 召回有效',
            '餐厅/酒店：缺值/否定/硬软约束编译',
            '模型用 12 次 find_name 补名称检索',
        ], RED_LIGHT, RED, '影响：菜系 / 店名不能证明不辣或双床'),
    ]
    for i, (num, title, sub, items, fill, color, impact) in enumerate(cards):
        x = 0.67 + i * 4.08
        add_card(slide, x, 1.85, 3.86, 3.9, fill=fill, line=None)
        add_text(slide, num, x + 0.24, 2.02, 0.5, 0.3, size=11, color=color, bold=True)
        add_text(slide, title, x + 0.24, 2.32, 3.4, 0.38, size=18, color=color, bold=True)
        add_text(slide, sub, x + 0.24, 2.76, 3.4, 0.28, size=10, color=NAVY, bold=True)
        add_list(slide, items, x + 0.24, 3.2, 3.35, 1.6, size=10, color=NAVY, gap=7)
        add_text(slide, impact, x + 0.24, 5.08, 3.35, 0.4, size=9.5, color=color, bold=True)
    add_text(slide, '重复实体、噪声和 TAG 边界会直接污染“不同景点 / 库存 / 预算”的判断；'
                    '这些应该在入库和 gateway 层治理，而不是靠 prompt 让模型猜。',
             0.67, 6.12, 12.0, 0.42, size=11.5, color=NAVY, bold=True)
    d.notes(slide, '例子来自 events/D02 与 D04；重复酒店坐标来自 catalog 记录。')


def proven(d):
    slide = d.new()
    d.header(slide, '能力判断：什么被证明，什么仍未知', '0 strict 不是“模型不会规划”，而是环境/接口/证据没有闭合')
    add_card(slide, 0.67, 1.85, 5.95, 3.8, fill=GREEN_LIGHT, line=None)
    add_text(slide, '已证明', 0.95, 2.02, 3.0, 0.36, size=20, color=GREEN, bold=True)
    add_list(slide, [
        '外部模型能在隔离 gateway 下完成多轮工具调用。',
        '动态证据会被读取，并改变计划（D01/D03）。',
        '门禁能阻止未核实断言升级为硬事实。',
        '修订锁定/排除可执行：D03 4/4 锁定保留。',
        '失败来源会暂停，同域不重试。',
    ], 0.95, 2.55, 5.3, 2.7, size=11.5, color=NAVY, gap=10)
    add_text(slide, '证据：49 条 gateway 事件；D03 修订 4/4 锁定保留。',
             0.95, 4.95, 5.3, 0.3, size=9.5, color=GREEN)
    add_card(slide, 6.7, 1.85, 5.95, 3.8, fill=AMBER_LIGHT, line=None)
    add_text(slide, '未证明', 6.98, 2.02, 3.0, 0.36, size=20, color=AMBER, bold=True)
    add_list(slide, [
        '任何计划在现实中可行。',
        '官方 DR / EPR / LPR / FPR 或模型排名。',
        '预算已满足、17:00/18:00 返回可达。',
        '日期房价/双床库存可用。',
        '存在已知可行解见证。',
    ], 6.98, 2.55, 5.3, 2.7, size=11.5, color=NAVY, gap=10)
    add_text(slide, '证据：strict 0/9；60 unknown；无已知可行解见证。',
             6.98, 4.95, 5.3, 0.3, size=9.5, color=AMBER)
    add_card(slide, 0.67, 5.9, 12.0, 0.72, fill=NAVY, line=None)
    add_text(slide, '“0 严格接纳”只说明当前证据和接口不足以证明硬约束，不说明模型没有规划能力。',
             0.95, 6.03, 11.4, 0.4, size=13, color=WHITE, bold=True)
    d.notes(slide, '“已证明”对应实际事件与计划变化；“未证明”对应 evaluator 的 unknown 与没有见证。')


def next_steps(d):
    slide = d.new()
    d.header(slide, '下一步：先修接口，再扩样本', '按影响排序；不要用更多 query 掩盖接口缺口')
    rows = [
        ('P0', '原生 plan 转换器 + 未知值表达', '把 start/end 锚点和 null 费用转成可投影结构', '1–2 天'),
        ('P0', '住宿 rooms / room_type / single_beds', 'answer 模板 + gateway 校验；修 D04 重复 accommodation', '1 天'),
        ('P1', 'qualified labelled estimate 接入', '让“有出处的范围”进入预算/时段，而不是永远 unknown', '2–3 天'),
        ('P1', '实体去重 + TAG 值/否定编译', '处理 20 m 内重复物业、跨城噪声和“不辣”约束', '3–5 天'),
        ('P2', 'Amap 恢复 + 日期库存 + 可行解对照', '路线、房价、已知 witness；再做通过率', '下一批'),
    ]
    for i, (p, title, note, eta) in enumerate(rows):
        y = 1.85 + i * 0.83
        add_text(slide, p, 0.67, y + 0.12, 0.55, 0.28, size=11, color=TEAL, bold=True)
        add_text(slide, title, 1.35, y + 0.07, 5.35, 0.3, size=12.5, color=NAVY, bold=True)
        add_text(slide, note, 1.35, y + 0.4, 6.35, 0.25, size=9.5, color=MUTED)
        add_text(slide, eta, 7.9, y + 0.12, 1.25, 0.28, size=10, color=MUTED, align=PP_ALIGN.RIGHT)
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.67), Inches(y + 0.72), Inches(8.55), Inches(0.008))
        line.fill.solid(); line.fill.fore_color.rgb = LINE; line.line.fill.background()
    add_card(slide, 9.55, 1.85, 3.1, 3.55, fill=TEAL_LIGHT, line=None)
    add_text(slide, '下一轮验收', 9.8, 2.02, 2.6, 0.3, size=14, color=TEAL_DARK, bold=True)
    add_list(slide, [
        '原生 schema 可投影',
        '住宿字段 100% 写入',
        '至少 1 个 known feasible witness',
        '预算/到达有 qualified estimate',
        '官方指标单独报告',
    ], 9.8, 2.42, 2.55, 2.6, size=10, color=NAVY, gap=7)
    add_text(slide, '先把 unknown 变成可解释的估计，再把估计变成可核验事实。',
             0.67, 6.35, 12.0, 0.35, size=13, color=TEAL_DARK, bold=True)
    d.notes(slide, '优先级来自 REPORT.md 的瓶颈排序；验收标准是本轮之后的最小下一批。')


def closing(d):
    slide = d.new(NAVY)
    # decorative circles / lines
    c1 = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.2), Inches(-1.2), Inches(4.4), Inches(4.4))
    c1.fill.background(); c1.line.color.rgb = RGBColor(0x2A, 0x5A, 0x66); c1.line.width = Pt(1)
    c2 = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(11.5), Inches(3.6), Inches(3.2), Inches(3.2))
    c2.fill.background(); c2.line.color.rgb = RGBColor(0x2A, 0x5A, 0x66); c2.line.width = Pt(1)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.78), Inches(1.45), Inches(0.62), Inches(0.055))
    line.fill.solid(); line.fill.fore_color.rgb = TEAL; line.line.fill.background()
    add_text(slide, 'P20 · 结论', 0.78, 1.12, 3.0, 0.3, size=12, color=RGBColor(0x9F, 0xC9, 0xC7), bold=True)
    add_text(slide, '闭环已跑通；\n下一关是把“可解释的未知”\n变成“可核验的事实”。', 0.78, 1.85, 8.2, 2.3,
             size=30, color=WHITE, bold=True, line_spacing=1.15)
    add_text(slide, '9/9 交付 · 0/9 严格接纳 · 21 claims 全 unverified · 0 高德调用',
             0.78, 4.55, 7.5, 0.35, size=13, color=RGBColor(0x9F, 0xC9, 0xC7))
    evidence = [
        ('REPORT.md', '完整报告与逐案日程'),
        ('evaluation.json', '9 份计划逐项检查'),
        ('decision_trace.md', '61 次调用轨迹'),
        ('overlay/v001/', '21 条 claims + 收据'),
    ]
    for i, (name, note) in enumerate(evidence):
        x = 0.78 + i * 3.05
        add_card(slide, x, 5.45, 2.85, 0.95, fill=RGBColor(0x1B, 0x38, 0x49), line=RGBColor(0x2A, 0x5A, 0x66))
        add_text(slide, name, x + 0.16, 5.57, 2.55, 0.3, size=10.5, color=WHITE, bold=True)
        add_text(slide, note, x + 0.16, 5.9, 2.55, 0.25, size=8.5, color=RGBColor(0x9F, 0xC9, 0xC7))
    add_text(slide, 'results/p20_deepseek_dynamic_sandbox/  ·  2026.10.23', 0.78, 6.9, 9.0, 0.25,
             size=9, color=RGBColor(0x7F, 0xA9, 0xAE))
    d.notes(slide, '收尾；证据文件均在 results/p20_deepseek_dynamic_sandbox/。')


def main():
    d = Deck()
    cover(d)
    summary(d)
    design(d)
    architecture(d)
    baseline(d)
    cases(d)
    results(d)
    why_zero(d)
    dynamic(d)
    consumption(d)
    quality(d)
    proven(d)
    next_steps(d)
    closing(d)
    d.save()
    print(json.dumps({'saved': str(OUT), 'slides': len(d.prs.slides)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
