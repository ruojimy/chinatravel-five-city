"""Render the P20 report, summary, current checkpoint and manifest from sealed artifacts."""
from __future__ import annotations

import collections
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p20_deepseek_dynamic_sandbox'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def acts(plan):
    return [a for d in plan.get('itinerary', []) for a in d.get('activities', [])]


def money(x):
    return '待核验' if x is None else str(x)


def pct(n, d):
    return f'{n / d:.1%}' if d else 'n/a'


def main():
    evaluation = load(OUT / 'evaluation.json')
    protocol = load(OUT / 'public/protocol.json')
    queries = load(OUT / 'public/queries.json')
    constraints = load(OUT / 'private/constraints.json')
    overlay = load(OUT / 'overlay/v001/claims.json')
    claims = overlay['claims']
    claims_manifest = load(OUT / 'overlay/v001/manifest.json')
    pauses = load(OUT / 'live/source_pauses.json')
    states = {p.stem: load(p) for p in sorted((OUT / 'agent_state').glob('*.json'))}
    events = [load(p) for p in sorted((OUT / 'events').glob('*/*.json'))]
    searches = [load(p) for p in sorted((OUT / 'live').glob('search_*.json'))]
    opens = sorted((OUT / 'live').glob('open_*.json'))
    failed_opens = sorted((OUT / 'live').glob('open_*.failed.json'))
    op_counts = collections.Counter(e['request'].get('action') for e in events)
    candidates = sum(len(e.get('result', {}).get('candidates', [])) for e in events
                     if isinstance(e.get('result'), dict) and isinstance(e.get('result', {}).get('candidates'), list))
    stages = {(x['case_id'], x['stage']): x for x in evaluation['evaluations']}
    total_calls = sum(s['usage'].get('calls', 0) for s in states.values())
    total_tokens = sum(s['usage'].get('total_tokens', 0) for s in states.values())
    prompt_tokens = sum(s['usage'].get('prompt_tokens', 0) for s in states.values())
    completion_tokens = sum(s['usage'].get('completion_tokens', 0) for s in states.values())
    search_queries = sum(len(s.get('queries', [])) for s in searches)
    claim_reasons = collections.Counter()
    for c in claims:
        for chk in c['ingest_verdict'].get('checks', []):
            if chk.get('claim_id') == c['claim_id']:
                claim_reasons.update(chk.get('reasons', []))
    dynamic_claims = {}
    plan_changes = {}
    numeric_costs = {}
    evidence_reads = collections.Counter((e['case_id'], e['stage']) for e in events
                                         if e['request'].get('action') == 'evidence')
    claims_by_entity = collections.defaultdict(list)
    for c in claims:
        claims_by_entity[c['entity_id']].append(c)
    for (cid, stage), x in stages.items():
        plan = load(OUT / 'plans' / cid / f'{stage}.json')
        refs = {r for c in plan.get('fact_claims', []) for r in c.get('evidence_refs', []) if isinstance(r, str) and r.startswith('p20:')}
        crefs = {r for c in plan.get('plan_changes', []) for r in c.get('evidence_refs', []) if isinstance(r, str) and r.startswith('p20:')}
        dynamic_claims[(cid, stage)] = (len(refs), len(crefs))
        plan_changes[(cid, stage)] = plan.get('plan_changes', [])
        numeric_costs[(cid, stage)] = sum(isinstance(a.get('cost'), (int, float)) for a in acts(plan['proposed_plan']))

    def stage_table():
        lines = ['| Case / 阶段 | pass | fail | unknown | 原生schema | 严格接纳 |', '|---|---:|---:|---:|---|---|']
        for x in evaluation['evaluations']:
            c = x['check_counts']
            lines.append(f"| {x['case_id']} / {x['stage']} | {c.get('pass', 0)} | {c.get('fail', 0)} | "
                         f"{c.get('unknown', 0)} | {'通过' if x['official_output_schema_ok'] else '未通过'} | "
                         f"{'是' if x['strict_accepted_plan'] else '否'} |")
        return '\n'.join(lines)

    def plan_table(proposed):
        lines = ['| 天 | 时段 | 类型 | 地点 | 费用 |', '|---|---|---|---|---|']
        for d in proposed['itinerary']:
            for a in d['activities']:
                lines.append(f"| {d['day']} | {a.get('start_time')}–{a.get('end_time')} | {a.get('type')} | "
                             f"{a.get('position')} | {money(a.get('cost'))} |")
        return '\n'.join(lines)

    lines = ['# 扩展沙盒中的 DeepSeek Query → Plan 动态检索实测（P20）', '',
             '时间：' + datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M +08:00'), '',
             f'本轮让 DeepSeek `{protocol["participant"]["model"]}` 作为被测规划模型，在我们 30 城的扩展沙盒里完成 4 条旅行请求、'
             '4 份动态稿和 1 次显式修订。模型只能通过本地 gateway 调用真实 TAG/名称/证据工具；根代理在模型提出缺口后执行有限实时检索，'
             '把逐字引文经门禁写入会话 overlay，再由模型读取并改稿。', '',
             f'**结果：9/9 份候选日程已交付，0 份通过严格接纳（无 fail、无 unknown 且原生 schema 通过）。** '
             '所有价格/路线/天气/库存类新增断言仍为未核实；模型没有用 0 或静态速度补齐路线费用，但出现了 1 次“未核实免费断言被写成 0”的边界违规。', '',
             '## 与 ChinaTravel 实验的关系', '',
             '保留“自然语言 query → 沙盒工具调用 → plan → 独立约束验证”的结构，并额外加入“缺口检索 → 证据版本 → 再规划 → 修订”。'
             '官方输出 schema 与 DSL 只用于可计算子集；新增城市、证据时效、来源绑定和动态交通由项目三值门判定。'
             '本轮不是官方 split，没有已知可行解见证，也没有把新增城市记录塞进官方环境检查器，因此不报告官方 DR/EPR/LPR/FPR 或模型排名。', '',
             'D01、D02 复用 P19 的同一 participant query，便于对照“子代理 vs 外部 API”的行为；D03 西安、D04 昆明为新城市泛化。'
             'P19 的答案未被模型读取。', '',
             '## 方法与运行事实', '',
             f'- 冻结输入：{len(queries)} 条 query、隐藏机器约束、participant prompt、独立 evaluator。初始 freeze 在任何有效 participant 输出前建立；'
             '此后为修复 usage 计数、断点续跑和大文件哈希做过运行器/评分器实现修复，freeze 文件重建。query/约束/prompt 哈希未变；'
             'evaluator 的检查逻辑未变，但文件哈希在 D01 首稿后因流式哈希修复变更，因此不能称完全预注册。详见 `logs/attempt_001_infra_failure.md` 与 `private/freeze.json`。',
             f'- 模型调用 {total_calls} 次，共 {total_tokens:,} tokens（prompt {prompt_tokens:,} / completion {completion_tokens:,}），temperature 0。',
             f'- gateway 事件 {len(events)} 条：' + '、'.join(f'{k} {v}' for k, v in sorted(op_counts.items())) + '。',
             f'- 工具返回候选记录累计 {candidates} 条（同一记录在多次 lookup/find_name 中可能重复）。',
             f'- 动态检索：{search_queries} 条搜索 query、{len(opens) + len(failed_opens)} 次来源打开尝试（{len(opens)} 个页面保存，{len(failed_opens)} 个失败；'
             '其中 4 个保存页实为验证码/验证/挑战页，不能当正文）。',
             f'- 新增 claims {len(claims)} 条，全部 `unverified`；0 条 `usable_as_hard_fact`，0 条 `usable_as_labelled_estimate`。',
             f'- 高德调用 0 次，浏览器/CUA 0 次，本地模型 0 次；静态正式库 SHA-256 `{protocol["baseline"]["sha256"]}` 未变。', '',
             '## 总体判定', '',
             f'- 交付率：{pct(evaluation["metrics"]["delivered"], evaluation["metrics"]["plans"])}（{evaluation["metrics"]["delivered"]}/{evaluation["metrics"]["plans"]}）。',
             f'- 严格接纳：{evaluation["metrics"]["strict_accepted"]}/{evaluation["metrics"]["plans"]}。',
             f'- 检查状态总计：pass {evaluation["metrics"]["check_status_counts"].get("pass", 0)}、'
             f'fail {evaluation["metrics"]["check_status_counts"].get("fail", 0)}、'
             f'unknown {evaluation["metrics"]["check_status_counts"].get("unknown", 0)}。',
             '- 明确 fail 的构成：9 份原生 schema 均失败（扩展 `start/end` 类型 + 未知数值/交通字段为 null）；D02/D03/D04 的静态、动态和 D03 修订稿均有 `hotel_room_count` 失败（模型没有写 `rooms`；D04 还重复放了 2 个 accommodation 活动）；D01 动态稿有 1 个 `zero_cost_has_source_or_hard_evidence` 失败。',
             '- 结构性项目检查（天数、人数、不同景点、主题 TAG、午餐数、逐日午餐、时序、起终点）大多通过；这不是现实准确率。', '',
             '## 各阶段评分', '', stage_table(), '',
             '> 通过项包含人数、天数、不同景点、TAG 召回和计划时序等，不等于环境可行。unknown 表示缺少可核验事实，不是“违反”，也不是“无解”。', '',
             '## 动态证据门禁', '',
             f'overlay v001 共 {len(claims)} 条 claims，来自 {claims_manifest.get("new_claims", len(claims))} 条新增断言、10 个来源登记。'
             f'`reconcile` 结果：{dict(collections.Counter(c["ingest_verdict"]["status"] for c in claims))}。'
             '未通过原因（可多选）：' + '、'.join(f'`{k}` {v}' for k, v in claim_reasons.most_common()) + '。', '',
             '这意味着：动态检索能提供有 URL、逐字引文和抓取时间的“范围参考”，但当前正式库记录普遍 `entity_unverified`/`usage_rights_unknown`，'
             '加上来源页面多数没有可规范化发布时钟，门禁不会把这些参考升级为硬事实。天气还受 `adcode` 与发布时间时区未规范化影响；'
             '酒店日期库存完全缺失。', '',
             '## 证据消费', '']
    evidence_rows = []
    notes = {
        'D01': '读取岳麓、简牍、夏记；使用价格/开放/天气/分支参考，未把 2020 历史公告当当前规则。',
        'D02': '只读取酒店；植物园开放/票价与两日天气 claims 已入库但未被消费。',
        'D03': '读取钟楼、碑林、酒店；使用两景点价格参考，酒店无 claim。',
        'D04': '读取翠湖、酒店、植物园；只把天气写进 plan，翠湖开放时间 claim 未被消费。',
    }
    evidence_rows.append('| Case | 动态 evidence 读取 | 选中实体的可用 claims | 动态稿引用 claim | 观察 |')
    evidence_rows.append('|---|---:|---:|---:|---|')
    for cid in ('D01', 'D02', 'D03', 'D04'):
        plan = load(OUT / 'plans' / cid / 'dynamic_first.json')
        selected = {a.get('entity_id') for a in acts(plan['proposed_plan']) if a.get('entity_id')}
        available = sum(len(claims_by_entity[e]) for e in selected)
        evidence_rows.append(f'| {cid} | {evidence_reads.get((cid, "dynamic_first"), 0)} | {available} | '
                             f'{dynamic_claims[(cid, "dynamic_first")][0]} | {notes[cid]} |')
    lines += evidence_rows + ['']
    lines += ['## 动态检索实际发生了什么', '']

    source_rows = [
        ('D01', '岳麓书院官网', 'opening_hours, price', '40 元/人、季节开放时间', 'unverified'),
        ('D01', '长沙简牍博物馆官网', 'price, opening_hours', '2007 免费声明、9:00–17:00、周二闭馆', 'unverified'),
        ('D01', '简牍馆 2020 恢复开放公告', 'opening_hours', '2020 疫情期 10:00–16:00（历史，过期）', 'unverified'),
        ('D01', '中国天气网湖南页', 'weather_forecast', '10/24 晴 24/16', 'unverified'),
        ('D01', '腾讯地图（夏记粉店）', 'identity, price, theme', '黄兴路步行街店、人均 18 元、6 点营业', 'unverified'),
        ('D02', '厦门朗豪酒店官网', 'room_configuration', '高级客房：特大床或两张单人床（OR）', 'unverified'),
        ('D02', '厦门园林植物园官网', 'opening_hours, price', '10/8–4/30 6:30–17:30；30 元/人', 'unverified'),
        ('D02', '中国天气网福建页', 'weather_forecast', '10/24 多云 32/24；10/25 多云 30/24', 'unverified'),
        ('D03', '西安碑林博物馆官网', 'opening_hours, price', '9:00–18:30、17:00 停止检票；85/42 元', 'unverified（已过期）'),
        ('D03', '永安旅游（钟楼）', 'opening_hours, price', '10/11 起 8:30–18:00；施工期单楼 15 元', 'unverified'),
        ('D04', '昆明信息港（翠湖公告）', 'opening_hours', '夏季 4/1–11/30 6:00–24:00', 'unverified（已过期）'),
        ('D04', '中国天气网云南页', 'weather_forecast', '10/24 晴 26/16；10/25 晴 27/15', 'unverified'),
    ]
    lines += ['| Case | 来源 | 字段 | 实际读到的范围 | 门禁 |', '|---|---|---|---|---|']
    for row in source_rows:
        lines.append('| ' + ' | '.join(row) + ' |')
    lines += ['',
              f'失败/受阻：百度百科 403（D02 午餐）、微信公众平台验证码（碑林/翠湖原文）、携程验证页（钟楼）、Trip.com 432（昆明植物园分部）、'
              f'Booking.com 202 挑战页（朗豪日期房价）。均已按“失败即暂停、同域不重试”处理，见 `live/source_pauses.json`；没有换域名绕行。', '',
              '## 各 Query 与计划', '']

    for q in queries:
        cid = q['case_id']
        static = load(OUT / 'plans' / cid / 'static_first.json')
        dynamic = load(OUT / 'plans' / cid / 'dynamic_first.json')
        lines += [f'### {cid} {q["city"]}（{q["days"]} 天，{q["date"]}）', '', '> ' + q['query'], '',
                  '**static_first**', '', plan_table(static['proposed_plan']), '',
                  '**dynamic_first**', '', plan_table(dynamic['proposed_plan']), '']
        changes = dynamic.get('plan_changes', [])
        if changes:
            lines.append('动态改动：')
            for c in changes:
                lines.append('- ' + c.get('change', '') + '（refs: ' + ', '.join(c.get('evidence_refs', [])) + '）')
            lines.append('')
        lines += ['仍未决：'] + ['- ' + x for x in dynamic.get('unresolved', [])] + ['']
        lines += [f'动态稿引用新 claim {dynamic_claims[(cid, "dynamic_first")][0]} 个；数字费用活动 {numeric_costs[(cid, "dynamic_first")]} 个。', '']

    revision = load(OUT / 'plans/D03/revised.json')
    lines += ['## 修订与锁定项', '',
              'D03 修订要求：排除西安碑林博物馆，保留钟楼、Bestay Hotel Express、两顿午餐和起终点，换入另一处历史文化景点。', '',
              '| 检查 | 结果 |', '|---|---|',
              '| 禁止实体已移除 | ' + ('是' if constraints['D03']['min_attractions'] and 'overture:f197eafc-d025-4fde-806c-15ae2d29ee82' not in {a.get('entity_id') for a in acts(revision['proposed_plan'])} else '否') + ' |',
              '| 锁定实体保留 | 4/4 |',
              '| 替代景点 | 大明宫国家遗址公园（overture:83c26c4e-13f9-4f1f-adbc-e23288ed000d） |',
              '| 修订后数字费用活动 | ' + str(numeric_costs[('D03', 'revised')]) + ' |', '',
              '修订稿仍没有 `rooms`，`hotel_room_count` 继续失败；这说明多轮锁定/排除逻辑可用，但住宿输出接口缺陷没有被修订自动修复。', '',
              '## 沙盒与检索能力的实测结论', '',
              '1. **Query→工具→计划→证据→改稿的闭环可跑通**：DeepSeek 在 4 个 case 上都实际调用了 lookup/find_name/evidence，没有直接编造库外实体；动态稿引用了新 claim，D03 修订正确移除碑林并保留 4 个锁定实体。',
              '2. **原生 ChinaTravel schema 仍是硬接口缺口**：计划使用 `start/end` 扩展锚点，价格/交通未知时保留 null；官方 schema 要求数值和官方活动枚举，9/9 失败。拒绝填 0 是正确边界，但这也意味着当前输出不能直接进入官方评分。',
              '3. **住宿字段是提示词/接口缺陷**：participant prompt 的 answer 模板没有显式列出 `rooms/room_type/single_beds`，模型在 4 个住宿 case 中都没有写 `rooms`，D04 还重复放了 accommodation。不能把这一项全部归因于模型规划能力；下一版必须补字段并在 gateway 校验。',
              '4. **动态检索能改善“范围参考”，不能自动升级硬事实**：21 条 claims 全部 unverified；原因集中在实体未验证、使用权未知、来源时钟未知/过期。D01 的 0 元门票、D03 的 15/85 元门票都来自这类参考；模型把它们标成 `scoped_reference_unverified_current` 是诚实的，但预算仍无法被证明。',
              '5. **交通仍是阻塞项**：高德暂停，0 次调用；23 段计划交通全部保留 null 耗时/费用，模型没有用网页或静态速度替代。这是正确行为，也意味着“17:00/18:00 返回”仍只是决策目标。',
              '6. **来源访问限制真实存在**：微信验证码、携程验证页、Trip.com 432、百度百科 403、Booking 202；按暂停账本停止，没有绕行。动态检索的“能力”不仅是搜索，还包括在受阻时保留缺口。',
              '7. **沙盒身份/重复实体需要治理**：`萬達朗豪酒店` 与 `Langham Place Xiamen` 坐标约 20 m，疑为同一物业的重复记录；模型选了带房型 operator assertion 的重复记录。`夏记粉店` 与腾讯地图“黄兴路步行街店”也只是候选关联。此类重复会污染“不同实体/库存/预算”的判断。',
              '8. **候选噪声仍高**：厦门 lookup 返回 `Grand Park Kunmimg`（拼写/城市异常）、重复的 `Fanta Wild Dream Land`，长沙返回 `Bairuopu (köpinghuvudort i Kina...)` 等 OSM 噪声；TAG 召回对 history/nature 有效，但餐厅/酒店缺少值/否定/硬软约束编译，模型主要靠 `find_name` 补。', '',
              '## 这轮能证明与不能证明什么', '',
              '- 能证明：外部 DeepSeek 模型可以在隔离 gateway 下完成多轮工具调用；动态证据会被读取并影响计划；证据门禁能阻止未核实断言升级；修订锁定/排除可执行；失败来源会被暂停。',
              '- 不能证明：任何计划在现实中可行；模型排名；官方 DR/EPR/LPR/FPR；预算已满足；到达时间可达；或“0 严格接纳”说明模型没有规划能力。',
              '- 主要瓶颈按优先级：原生 plan 转换/字段接口 → 住宿 rooms/room_type 显式字段 → 可用动态证据到预算/时段的受控接入 → 实体去重与 TAG 值/否定编译 → 高德恢复与日期库存 → 有已知可行解的对照集。', '',
              '## 复现', '',
              '```powershell',
              'cd reproduction',
              '$env:PYTHONUTF8="1"',
              '# 冻结文件已存在；不要重跑 --freeze 覆盖',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_agent.py --case D01 --stage static',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_agent.py --case D01 --stage dynamic',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_agent.py --case D03 --stage revised --revision results\\p20_deepseek_dynamic_sandbox\\public\\revision.json',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_extract_live.py',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_ingest_overlay.py results\\p20_deepseek_dynamic_sandbox\\live\\ingest_request_001.json',
              '.\\.venv\\Scripts\\python.exe scripts\\p20_evaluate.py',
              '```', '',
              '实时检索由根代理按 `live/request_D0*.json` 执行，页面原文在 `live/open_*.json`，claims 规格在 `live/claim_specs.json`；'
              '所有失败/暂停在 `live/source_pauses.json`。', '',
              '## 证据入口', '',
              '- `public/queries.json`、`public/protocol.json`、`public/participant_prompt.txt`、`public/revision.json`：输入与协议。',
              '- `private/constraints.json`、`private/freeze.json`：隐藏机器约束与冻结哈希。',
              '- `events/`、`logs/`、`decision_trace.md`：49 条 gateway 事件、61 次模型调用和逐步决策轨迹。',
              '- `plans/`：4 份 static_first、4 份 dynamic_first、1 份 revised。',
              '- `live/`：5 个搜索包、22 个保存页面、2 个失败包、暂停账本、21 条 claim 规格。',
              '- `overlay/v001/`：21 条 claims、SQLite 会话证据、门禁收据与哈希。',
              '- `evaluation.json`、`summary.json`、`manifest.json`：评分细项、摘要与全量哈希清单。', '']
    report = '\n'.join(lines)
    report_path = OUT / 'REPORT.md'
    if report_path.exists():
        raise SystemExit('REPORT.md exists; preserve first report')
    report_path.write_text(report, encoding='utf-8')

    # summary
    summary = {
        'at': datetime.now(timezone.utc).isoformat(),
        'status': 'finite_external_model_dynamic_pilot_complete_not_full_benchmark',
        'participant': {'provider': 'deepseek', 'model': protocol['participant']['model'],
                        'api_calls': total_calls, 'total_tokens': total_tokens,
                        'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens},
        'queries': len(queries), 'revision_queries': 1, 'plans': len(evaluation['evaluations']),
        'static_first_proposals': 4, 'dynamic_first_proposals': 4, 'revised_proposals': 1,
        'strict_accepted_plans': evaluation['metrics']['strict_accepted'],
        'delivery_rate': evaluation['metrics']['delivery_rate'],
        'check_status_counts': evaluation['metrics']['check_status_counts'],
        'tool_events': dict(op_counts), 'candidates_returned': candidates,
        'live_search_queries': search_queries, 'source_open_attempts': len(opens) + len(failed_opens),
        'saved_pages': len(opens), 'failed_open_packets': len(failed_opens),
        'challenge_or_captcha_pages': 4,
        'new_scoped_claims': len(claims), 'new_hard_claims': 0,
        'new_labelled_estimate_claims': 0,
        'amap_calls': 0, 'browser_calls': 0, 'local_models': 0,
        'catalogue_base_unchanged': True,
        'official_benchmark_scores': None, 'real_world_accuracy': None,
        'limits': evaluation['limitations'] + [
            'Participant prompt did not explicitly list rooms/room_type/single_beds, so hotel room-count failures are partly an interface defect.',
            'Dynamic claims are all unverified; budget and arrival-time cannot be certified.',
            'One zero-cost assertion used an unverified free-admission claim and was failed by the evaluator.',
            'Entity duplication (Wanda Langham / Langham Place Xiamen) and catalog noise remain unresolved.',
        ],
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'current_evaluation.json').write_text(json.dumps({
        'at': summary['at'], 'phase': 'p20_deepseek_dynamic_sandbox',
        'status': summary['status'], 'report': 'results/p20_deepseek_dynamic_sandbox/REPORT.md',
        'summary': 'results/p20_deepseek_dynamic_sandbox/summary.json',
        'evaluation': 'results/p20_deepseek_dynamic_sandbox/evaluation.json',
        'manifest': 'results/p20_deepseek_dynamic_sandbox/manifest.json',
        'baseline_sha256': protocol['baseline']['sha256'], 'broad_static_collection_paused': True,
        'queries': len(queries), 'revision_queries': 1, 'plans': len(evaluation['evaluations']),
        'strict_accepted_plans': evaluation['metrics']['strict_accepted'],
        'full_catalog_completion': False, 'real_world_accuracy': None,
        'official_benchmark_scores': None, 'measured_network_savings': None,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    scripts = [ROOT / 'scripts' / name for name in ('p20_agent.py', 'p20_live_fetch.py', 'p20_extract_live.py',
                                                    'p20_ingest_overlay.py', 'p20_evaluate.py', 'p20_report.py')]
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name not in ('manifest.json', 'current_evaluation.json')
             and not p.name.endswith(('-wal', '-shm'))] + scripts
    inventory = [{'file': str(p.relative_to(ROOT)), 'sha256': digest(p), 'bytes': p.stat().st_size}
                 for p in sorted(set(files))]
    (OUT / 'manifest.json').write_text(json.dumps({
        'at': summary['at'], 'baseline': protocol['baseline'], 'files': inventory,
        'evidence_bytes': sum(x['bytes'] for x in inventory), 'no_truth_certification': True,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(report_path), 'summary': summary['status'],
                      'plans': summary['plans'], 'strict_accepted': summary['strict_accepted_plans'],
                      'files': len(inventory), 'bytes': sum(x['bytes'] for x in inventory)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
