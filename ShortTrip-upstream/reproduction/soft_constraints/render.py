"""Table-format soft-mode report, including every candidate and penalty detail."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('baseline_table_renderer', ROOT / 'reproduction/render.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
e = base.e
CATEGORY_NAMES = {'transport': '交通合理性', 'rhythm': '每日节奏', 'distribution': '跨日分布', 'efficiency': '路线效率'}
RULE_NAMES = {'long_commute': '单次通勤过长', 'long_walk': '单段步行过久', 'station_wait': '候车过久',
              'airport_wait': '候机过久', 'crowded_day': '日间安排过紧', 'long_day_span': '游览跨度过长',
              'idle_gap': '连续空闲过长', 'too_little_sightseeing': '游览内容过少', 'missing_lunch': '遗漏午餐',
              'missing_dinner': '遗漏晚餐', 'no_attractions': '可游玩日无景点',
              'daily_transit_time': '日交通总耗时过长', 'daily_transit_distance': '日交通总距离过长',
              'meal_detour_time': '餐饮绕路时间', 'meal_detour_distance': '餐饮绕路距离'}


def display(value, digits=None):
    return '未知' if value is None else e(f'{value:.{digits}f}' if digits is not None else value)


def plan_tables(plan, selected=False):
    parts = []
    for day in plan['itinerary']:
        attributes = f'data-day="{day["day"]}" data-day-cost="{base.day_cost(day)}"' if selected else ''
        parts.append(f'<section class="day" {attributes}><h3>第 {day["day"]} 天</h3><div class="scroll"><table class="schedule"><thead><tr><th>时段</th><th>活动类型</th><th>活动／地点</th><th>到达交通：方式与耗时</th></tr></thead><tbody>')
        for a in day['activities']:
            marker = 'data-activity="1"' if selected else ''
            transports = base.transport_cell(a.get('transports', []))
            if not selected:
                transports = transports.replace('data-transport=', 'data-candidate-transport=')
            parts.append(f'<tr {marker}><td>{e(a["start_time"])}–{e(a["end_time"])}</td><td>{e(base.TYPES.get(a["type"],a["type"]))}</td><td>{base.activity_cell(a)}</td><td>{transports}</td></tr>')
        parts.append(f'</tbody></table></div><div class="total">当日费用：¥{base.day_cost(day):,.2f}</div></section>')
    return ''.join(parts)


def score_details(score):
    rows = ''.join('<tr><td>' + e(d['day']) + '</td><td>' + e(CATEGORY_NAMES[d['category']]) + '</td><td>' +
                   e(RULE_NAMES.get(d['rule'],d['rule'])) + '</td><td>' + e(d['actual']) + '</td><td>' +
                   e(d['threshold']) + '</td><td>' + f'{d["penalty"]:.3f}' + '</td></tr>' for d in score['details'])
    return ('<div class="scroll"><table class="score-table"><thead><tr><th>日期</th><th>分类</th><th>惩罚项</th><th>实际值</th><th>阈值</th><th>原始惩罚</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
            '<p class="uid">分钟与公里按对应规则计量；原始惩罚乘分类权重后汇总。未知项为 null，不伪造为已知零。</p>'
            '<details><summary>完整指标、覆盖率和配置</summary><pre>' + e(json.dumps(score,ensure_ascii=False,indent=2)) + '</pre></details>')


def main():
    bundle = json.loads((OUT / 'all_results.json').read_text(encoding='utf-8'))
    cases = []
    for number, item in enumerate(bundle['cases'], 1):
        split, query, chosen, score, selection = (item[k] for k in ('split','query','selected_plan','selected_score','selection'))
        total = sum(base.day_cost(d) for d in chosen['itinerary'])
        parts = [f'<section class="case" id="{split}" data-total-cost="{total}"><h2>{number}. {e(split)} · {e(query["start_city"])} → {e(query["target_city"])} · {query["days"]} 天</h2><p class="uid">{e(item["uid"])}</p>',
                 f'<div class="score-box">最低软惩罚：<b>{score["total_penalty"]:.3f}</b> · 已保留 {selection["candidate_count"]}/20 个唯一可行候选 · 选中采集编号 #{selection["selected_ordinal"]}</div>',
                 '<p>' + ' · '.join(e(CATEGORY_NAMES[k]) + f'：{v:.3f}' for k,v in score['categories'].items()) + '</p>',
                 f'<p class="total">市内交通合计：{display(score["metrics"]["total_city_transit_minutes"])} 分钟 / {display(score["metrics"]["total_city_transit_km"],2)} 公里；餐饮绕路可计算 {score["coverage"]["meal_routes_known"]}/{score["coverage"]["meal_routes_total"]} 组；等待时间可计算 {score["coverage"]["waits_known"]}/{score["coverage"]["waits_total"]} 次。</p>',
                 f'<p class="uid">停止原因：{e(selection["stop_reason"])}；活动实体序列共有 {selection["structural_variants"]} 种。总分越低越好，只保证本次前 20 个候选池内最优。</p>',
                 f'<p class="uid">旧版原始行程参考分：{item["baseline_score"]["total_penalty"]:.3f}（使用同一评分器，仅用于比较，不进入本次候选池）。本次结果可能优于或劣于旧结果；未用旧结果替换新候选。</p>',
                 plan_tables(chosen, True), f'<div class="total">行程总费用：¥{total:,.2f} · {chosen["people_number"]} 人</div>',
                 '<details class="panel"><summary>选中行程的软惩罚明细</summary>' + score_details(score) + '</details>',
                 '<details class="panel" open><summary>20 个候选排名（点击编号查看完整候选）</summary><div class="scroll"><table class="score-table"><thead><tr><th>排名</th><th>采集编号</th>' + ''.join(f'<th>{v}</th>' for v in CATEGORY_NAMES.values()) + '<th>总惩罚</th></tr></thead><tbody>']
        ranking = sorted(item['candidates'], key=lambda c:(c['score']['total_penalty'],c['ordinal']))
        for rank,c in enumerate(ranking,1):
            target=f'{split}-candidate-{c["ordinal"]}'
            parts.append(f'<tr class="{"winner" if rank==1 else ""}"><td>{rank}</td><td><a href="#{target}" onclick="document.getElementById(\'{target}\').open=true">#{c["ordinal"]}</a></td>' +
                         ''.join(f'<td>{c["score"]["categories"][k]:.3f}</td>' for k in CATEGORY_NAMES) + f'<td>{c["score"]["total_penalty"]:.3f}</td></tr>')
        parts.append('</tbody></table></div></details>')
        for c in item['candidates']:
            target=f'{split}-candidate-{c["ordinal"]}'
            parts.append(f'<details class="panel" id="{target}"><summary>候选 #{c["ordinal"]} · 惩罚 {c["score"]["total_penalty"]:.3f}</summary>' +
                         plan_tables(c['plan']) + score_details(c['score']) + '<details><summary>候选原始 JSON 与独立检查</summary><pre>' + e(json.dumps({'plan':c['plan'],'audit':c['audit'],'fingerprint':c['fingerprint']},ensure_ascii=False,indent=2)) + '</pre></details></details>')
        parts += [f'<details class="panel"><summary>原始旅行需求</summary><p>{e(query["nature_language"])}</p></details>',
                  f'<details class="panel"><summary>选中行程完整 JSON</summary><pre id="json-{split}">{e(json.dumps(chosen,ensure_ascii=False,indent=2))}</pre></details>',
                  f'<details class="panel"><summary>原版独立评估结果</summary>{base.evaluation_tables(split,item["status"]["method"])}</details></section>']
        cases.append(''.join(parts))
    css = base.CSS + '.score-box{background:#edf2f8;border:1px solid #dbe1e9;border-radius:6px;padding:16px}.score-box b{font-size:24px}.score-table{table-layout:auto!important}.score-table th,.score-table td{width:auto!important;min-width:80px}.winner{background:#e6f4ea}a{color:#285d91}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ChinaTravel · 软约束选优三例行程</title><style>'+css+'</style></head><body><main><h1>ChinaTravel 原架构 + 软约束 · 三例行程</h1><p class="uid">同一原版 DFS 收集前 20 个去重可行候选，按交通合理性、每日节奏、跨日分布、路线效率评分，选取总惩罚最低者。模型为 DeepSeek Flash，非思考模式。全部候选和评分已保存。</p>'+''.join(cases)+'</main></body></html>'
    (OUT/'itineraries.html').write_text(page,encoding='utf-8')
    print('Rendered selected plans, 60 candidate plans, rankings and penalty details.')


if __name__=='__main__':
    main()
