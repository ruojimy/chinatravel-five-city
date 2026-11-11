"""Render existing experiment data in the user's reference table layout.

Reads saved JSON/CSV only. Does not call a model or rewrite itinerary data.
"""
import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reproduction'
TYPES = {'airplane': '飞机', 'train': '火车', 'attraction': '景点', 'lunch': '午餐',
         'dinner': '晚餐', 'breakfast': '早餐', 'accommodation': '酒店',
         'walk': '步行', 'metro': '地铁', 'taxi': '出租车'}


def e(value):
    return html.escape(str(value), quote=True)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def minutes(start, end):
    if not start or not end:
        return None
    begin = sum(int(x) * factor for x, factor in zip(start.split(':'), (60, 1)))
    finish = sum(int(x) * factor for x, factor in zip(end.split(':'), (60, 1)))
    return finish - begin if finish >= begin else finish + 1440 - begin


def minute_text(value):
    return f'{value} 分钟' if value is not None else '未记录耗时'


def day_cost(day):
    return sum(float(a.get('cost', 0)) + sum(float(t.get('cost', 0)) for t in a.get('transports', []))
               for a in day.get('activities', []))


def transport_cell(transports):
    if not transports:
        return '未记录接驳交通'
    parts = []
    durations = []
    for leg in transports:
        duration = minutes(leg.get('start_time'), leg.get('end_time'))
        durations.append(duration)
        parts.append('<div class="leg" data-transport="1">' +
                     f'{e(TYPES.get(leg.get("mode"), leg.get("mode", "交通")))}：'
                     f'{e(leg.get("start", ""))} → {e(leg.get("end", ""))}<br>'
                     f'{e(leg.get("start_time", ""))}–{e(leg.get("end_time", ""))} · '
                     f'<b>{minute_text(duration)}</b></div>')
    if len(parts) > 1 and all(value is not None for value in durations):
        parts.append(f'<div class="total">各段行进合计：{sum(durations)} 分钟</div>')
    return ''.join(parts)


def activity_cell(activity):
    kind = activity.get('type')
    if kind in ('airplane', 'train'):
        identifier = activity.get('FlightID' if kind == 'airplane' else 'TrainID', '')
        duration = minutes(activity.get('start_time'), activity.get('end_time'))
        return (f'{e(TYPES[kind])} {e(identifier)}：{e(activity.get("start", ""))} → '
                f'{e(activity.get("end", ""))}；{minute_text(duration)}')
    return e(activity.get('position', ''))


def evaluation_tables(split, method):
    directory = ROOT / 'eval_res' / f'splits_repro_{split}' / method
    sections = []
    for name, title in [('schema', 'JSON 结构验证'), ('commonsense', '常识与沙盒一致性'), ('logical_py', '原始硬约束验证')]:
        path = directory / f'{name}.csv'
        if not path.exists():
            continue
        with path.open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.reader(file))
        if not rows:
            continue
        sections.append(f'<h3>{title}</h3><div class="scroll"><table><thead><tr>' +
                        ''.join(f'<th>{e(cell)}</th>' for cell in rows[0]) + '</tr></thead><tbody>' +
                        ''.join('<tr>' + ''.join(f'<td>{e(cell)}</td>' for cell in row) + '</tr>' for row in rows[1:]) +
                        '</tbody></table></div>')
    return ('<p class="uid">结构与硬约束：1 表示通过。常识表：0 表示没有违规。</p>' + ''.join(sections)) if sections else '<p>无评估记录。</p>'


CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#192638;font:15px/1.6 "Microsoft YaHei",sans-serif}
main{max-width:1440px;padding:28px;margin:auto}h1{font-size:27px}h2{font-size:20px;margin:0}h3{font-size:17px;margin:24px 0 10px}
.case{background:white;border:1px solid #dbe1e9;border-radius:10px;padding:24px;margin:22px 0}.uid{font-size:12px;color:#667085;margin:4px 0 16px}
table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{padding:11px;border:1px solid #dbe1e9;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:#edf2f8}th:nth-child(1){width:11%}th:nth-child(2){width:8%}th:nth-child(3){width:27%}
.leg+.leg{margin-top:10px;padding-top:8px;border-top:1px dashed #dbe1e9}.total{margin-top:10px;color:#465c77}
.scroll{overflow-x:auto}.panel{margin-top:16px;border-top:1px solid #dbe1e9;padding-top:12px}.panel summary{cursor:pointer;color:#465c77}
.panel table{table-layout:auto;width:max-content;min-width:100%;font-size:12px}.panel th,.panel td{width:auto;min-width:75px;max-width:240px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f9;border:1px solid #dbe1e9;border-radius:6px;padding:16px;max-height:520px;overflow:auto;font-size:12px}
.download{margin-top:12px;padding:7px 14px;background:#edf2f8;border:1px solid #dbe1e9;border-radius:5px;color:#192638;cursor:pointer}
@media(max-width:700px){main{padding:14px}.case{padding:14px}.schedule{min-width:760px}h1{font-size:23px}}
@media print{body{background:white}.case{break-before:page}tr{break-inside:avoid}.panel{display:none}.scroll{overflow:visible}}
'''


def main():
    manifest = read(OUT / 'manifest.json')
    status = read(OUT / 'run_status.json')
    evaluations = read(OUT / 'evaluation_summary.json')
    cases = []
    for number, sample in enumerate(manifest['samples'], 1):
        split, uid = sample['split'], sample['uid']
        query = read(ROOT / sample['query_path'])
        plan = read(ROOT / 'results' / status['method'] / f'{uid}.json')
        itinerary = plan.get('itinerary', [])
        total = sum(day_cost(day) for day in itinerary)
        parts = [f'<section class="case" id="{e(split)}" data-uid="{e(uid)}" data-total-cost="{total}">',
                 f'<h2>{number}. {e(split)} · {e(query["start_city"])} → {e(query["target_city"])} · {e(query["days"])} 天</h2>',
                 f'<p class="uid">{e(uid)}</p>']
        for day in itinerary:
            parts.append(f'<section class="day" data-day="{e(day["day"])}" data-day-cost="{day_cost(day)}"><h3>第 {e(day["day"])} 天</h3>'
                         '<div class="scroll"><table class="schedule"><thead><tr><th>时段</th><th>活动类型</th><th>活动／地点</th><th>到达交通：方式与耗时</th></tr></thead><tbody>')
            for activity in day.get('activities', []):
                parts.append('<tr data-activity="1">' +
                             f'<td>{e(activity.get("start_time", ""))}–{e(activity.get("end_time", ""))}</td>'
                             f'<td>{e(TYPES.get(activity.get("type"), activity.get("type", "")))}</td>'
                             f'<td>{activity_cell(activity)}</td><td>{transport_cell(activity.get("transports", []))}</td></tr>')
            parts.append(f'</tbody></table></div><div class="total">当日费用：¥{day_cost(day):,.2f}</div></section>')
        parts.append(f'<div class="total">行程总费用：¥{total:,.2f} · {e(plan.get("people_number", query["people_number"]))} 人</div>')
        evaluation = evaluations.get(split, {})
        if 'all_pass' in evaluation:
            text = ' · '.join(f'{title} {evaluation[key]["passed"]}/{evaluation[key]["total"]}'
                              for key, title in [('schema', '结构'), ('commonsense', '常识检查'), ('logical_py', '硬约束')])
            parts.append(f'<p class="uid">官方评估：{e(text)}</p>')
        parts.append(f'<details class="panel"><summary>原始旅行需求</summary><p>{e(query["nature_language"])}</p></details>')
        parts.append(f'<details class="panel"><summary>完整原始 JSON 与费用明细</summary><button class="download" data-target="json-{split}" data-name="{e(uid)}.json">下载 JSON</button><pre id="json-{split}">{e(json.dumps(plan, ensure_ascii=False, indent=2))}</pre></details>')
        parts.append(f'<details class="panel"><summary>原版评估结果</summary>{evaluation_tables(split, status["method"])}</details></section>')
        cases.append(''.join(parts))
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>ChinaTravel 原架构 · 三例行程</title><style>' + CSS + '</style></head><body><main><h1>ChinaTravel 原架构 · 三例行程</h1>' +
            ''.join(cases) + '</main><script>document.querySelectorAll(".download").forEach(b=>b.addEventListener("click",()=>{const blob=new Blob([document.getElementById(b.dataset.target).textContent],{type:"application/json;charset=utf-8"});const u=URL.createObjectURL(blob);const a=document.createElement("a");a.href=u;a.download=b.dataset.name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}));</script></body></html>')
    (OUT / 'itineraries.html').write_text(page, encoding='utf-8')
    print('Rendered existing three-case results in reference table format; itinerary JSON unchanged.')


if __name__ == '__main__':
    main()
