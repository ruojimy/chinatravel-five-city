"""Seal query/plan/evidence outputs and render the finite pilot report."""
import collections
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p19_query_to_plan'

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    assert not (OUT / 'REPORT.md').exists(), 'Use another report version rather than overwrite first pilot'
    evaluation = load(OUT / 'evaluation.json')
    assert len(evaluation['evaluations']) == 5, 'Both first stages and D01 revision required'
    protocol = load(OUT / 'public/protocol.json')
    queries = load(OUT / 'public/queries.json')
    events = [load(p) for p in sorted((OUT / 'events').glob('*/*.json'))]
    claims = load(OUT / 'overlay/v001/claims.json')['claims']
    live_claims = {c['claim_id'] for c in claims} | {c['evidence_id'] for c in claims}
    lines = ['# 动态沙盒 Query → Plan：LLM实测报告', '',
             '时间：' + datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M +08:00'), '',
             '本轮已在我们扩展的动态沙盒中完成两条完整旅行请求，以及一次带锁定项的多轮修改。子代理实际担当规划LLM；根代理执行它提出的有限检索、证据审核和独立判定。不是把旧库交给确定性planner，也没有提供现成答案。', '',
             '**结果：两份候选日程已经生成并在动态证据后修订；目前0份达到可核验的完整执行方案。** 主要未解项为日期房价/双床库存、餐厅具体菜品、门票和营业的当日适用性、地铁路线时耗和费用。模型把这些项留为未知，没有把未知费用填成0来满足预算。', '',
             '## 与ChinaTravel测试的关系', '',
             '保留“自然语言query → 工具查询 → plan → 独立约束验证”的实验结构。使用仓库原生输出schema和DSL执行器检查格式及可计算的部分；新增城市、字段时效、来源与动态交通适用性由项目自己的三值门判定：通过、违反、未知。未知不计通过，也不作为无解证明。', '',
             '本轮不是原论文公开split、没有已知可行解见证，也没有把新增城市的discovery记录硬塞进官方环境检查器。因此不报告官方DR/EPR/LPR/FPR或模型排名。论文强调先满足环境真实性再谈逻辑条件；我们同样不因为算术预算看似满足就计成功。论文原文抽取依据为项目 `.ppt-build/sources/01.txt` 的Metrics及benchmark construction段。', '',
             '初始query与隐藏约束在规划前封存。评分器实现与首稿生成并行，代码封存时首稿文件已经存在；不能称整个实验完全预注册。规划代理未获评分反馈，报告也不把同一模型后端的角色分离当独立人工真值。', '',
             '## 实际用到的机制', '',
             '- TAG召回调用当前 `static_lookup.lookup`；模型解析值、否定和软硬条件，再据返回值选点。中文标签直接匹配失败、改用history/nature等键的轨迹保留。现有工具主要按TAG键查找，尚未实现完整的值/否定约束编译。',
             '- 字段/时间检查实际调用 `validate_record`、`fresh_state`、`retrieval_task`。导入时间不能刷新事实时钟；按字段缺口产生补查。',
             '- 模型先提交static_first，再提出8项检索请求。根侧遵守来源暂停和预算，实际发出10条搜索查询、12个来源打开尝试和4个页内查找。地铁必须高德的请求保持受阻，没有换网页数值替代。',
             '- 13条逐字引文断言经过原文哈希、结构、实体引用检查及 `reconcile`，进入会话overlay/v001；全部保持unverified，没有覆盖正式原字段或伪造观察时间。规划模型再调用evidence读取此版本。',
             '- 单一规划子代理，零外部模型API、零本地模型。静态正式库哈希保持不变。', '',
             '## Query与实际生成的日程', '']
    stage_changes = []
    for q in queries:
        cid = q['case_id']
        first = load(OUT / 'plans' / cid / 'static_first.json')
        final = load(OUT / 'plans' / cid / 'dynamic_first.json')
        lines += ['### ' + cid + ' ' + q['city'], '', '> ' + q['query'], '',
                  '以下时段是模型提出的安排，不是已核实的交通到达保证。费用为null的项目在表中记为待核验。', '',
                  '| 天 | 计划时段 | 活动/地点 | 费用状态 |', '|---|---|---|---|']
        for day in final['proposed_plan']['itinerary']:
            for a in day['activities']:
                lines.append(f"| {day['day']} | {a.get('start_time')}–{a.get('end_time')} | {a['type']} · {a.get('position','')} | {'待核验' if a.get('cost') is None else str(a['cost'])} |")
        first_acts = [a for d in first['proposed_plan']['itinerary'] for a in d['activities']]
        final_acts = [a for d in final['proposed_plan']['itinerary'] for a in d['activities']]
        changes = []
        for i, a in enumerate(final_acts):
            if i < len(first_acts):
                before = first_acts[i]
                if any(a.get(k) != before.get(k) for k in ('position', 'start_time', 'end_time')):
                    changes.append({'position': a.get('position'), 'before': [before.get('start_time'), before.get('end_time')],
                                    'after': [a.get('start_time'), a.get('end_time')]})
        refs = [r for c in final.get('fact_claims', []) for r in c.get('evidence_refs', []) if isinstance(r, str) and r in live_claims]
        stage_changes.append({'case_id': cid, 'schedule_changes': changes, 'cited_new_evidence_ids': sorted(set(refs)),
                              'model_status': final['status']})
        lines += ['', '动态后状态：`' + final['status'] + '`。', '', '仍需核验：']
        lines += ['- ' + x for x in final['unresolved']]
        lines += ['', f'原始初稿与动态稿：`plans/{cid}/static_first.json`、`plans/{cid}/dynamic_first.json`。', '']
    lines += ['## 独立判定', '', '| Query/阶段 | 已通过的项目检查 | 明确违反 | 未知 | 完整方案获接纳 |', '|---|---:|---:|---:|---|']
    for e in evaluation['evaluations']:
        c = e['check_counts']
        lines.append(f"| {e['case_id']} / {e['stage']} | {c.get('pass',0)} | {c.get('fail',0)} | {c.get('unknown',0)} | {'是' if e['strict_accepted_plan'] else '否'} |")
    lines += ['', '这里的通过项包含人数、天数、午餐数、不同景点、TAG匹配和计划时序等，不是现实准确率。两条初始/动态稿的官方DSL结构子集各4项均可单独查看；不能由此替代完整环境验证。', '',
              '原生ChinaTravel schema未通过：候选稿保留null费用/交通，并包含start/end/checkout等扩展锚点活动，未完成原生schema转换。拒绝给null补0是正确的数据边界，但这也意味着当前输出接口尚未接成可直接参加官方评分的完整plan。schema错误逐路径保留在evaluation.json。', '',
              '## 动态更新与多轮修改产生了什么', '',
              '长沙保留原有行程，新增一般开放、展陈主题与隔离的天气参考；2007年服务页面没有被重新下载时间洗成当前预约保证。厦门把植物园从13:45–17:00调整到14:30–16:30，拟选官网建议的虎园路西门；30元门票公示仍是范围参考。朗豪“特大床或两张单人床”没有被当成已确认双床库存；鼓浪屿1980分店没有把菜单/人均移植给大陆实体。此类动作证明模型消费了新证据，不能证明修改后的行程一定可行。', '',
              '再向模型提出“排除简牍博物馆、保留长沙博物馆和午餐/起终点、其他约束不变”的修改。`public/revision.json`和`plans/D01/revised.json`保存输入输出。网络预算已用完，替换过程继续实际调用本地TAG/证据工具；新增缺口不编造。锁定项、排除项与活动变化见下方机器结果。', '']
    revision = load(OUT / 'plans/D01/revised.json')
    lines += ['修订后的D01景点：' + ' → '.join(a['position'] for d in revision['proposed_plan']['itinerary'] for a in d['activities'] if a['type'] == 'attraction') + '。', '',
              '额外事后诊断：岳麓书院原生建议1–2小时，另一范围原文写2–3小时，修订安排105分钟落在前者范围但低于后者。模型将其解释为精简参观；这不是105分钟不可能的证明，也不能悄悄挑选较短的参考来宣称可靠。范围冲突另存posthoc_reference_duration_audit.json，不算进事先主评分。', '',
              '## 目前能得出的结论', '',
              '完整的“query→TAG选点→缺口检索→动态证据版本→模型改plan→独立检查”已跑通；没有停留在收集回答或判断单字段。当前能够生成带证据和未决项的候选日程，尚不能证明满足所有现实硬约束。', '',
              '这轮只能定位瓶颈，不能说明模型没有规划能力：题目没有已知可行解，数据和API可用性也限制完成率。继续扩大样本前，优先补齐三处接口：TAG值/否定/硬软约束的程序级处理；可用动态证据到规划事实的受控接入；候选稿与原生plan格式的分离及转换。后续应补含已知可行解的对照，再测通过率与实际调用成本。', '',
              '来源权威、引文命中、结构通过均不是准确率。13条新断言的未通过原因包括身份绑定、事实时钟、适用情境或使用权未确认；不是13条都被证伪。没有高德路线、合格日期房价及独立人工真值时，不宣称预算或抵达时间已保证。', '',
              '## 证据入口', '',
              '- `public/queries.json`、`public/protocol.json`：测试输入与预算。',
              '- `events/`、`decision_trace.md`：真实工具调用和模型简要决策轨迹。',
              '- `plans/`：两条初稿、动态稿及一次修改；第一稿未覆盖。',
              '- `live/`：完整搜索/打开/页内查找结果、时间和暂停记录。',
              '- `overlay/v001/`：13条追加断言、SQLite会话证据及哈希收据。',
              '- `evaluation.json`、`summary.json`、`manifest.json`：评分细项、摘要与全量证据清单。', '']
    report = OUT / 'REPORT.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    counts = collections.Counter(e['request']['operation'] for e in events)
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'status': 'finite_pilot_complete_not_full_benchmark',
               'queries': 2, 'revision_queries': 1, 'planning_participants': 1,
               'static_first_proposals': 2, 'dynamic_first_proposals': 2, 'revised_proposals': 1,
               'strict_accepted_dynamic_plans': sum(e['strict_accepted_plan'] for e in evaluation['evaluations'] if e['stage'] == 'dynamic_first'),
               'tool_events': dict(counts), 'schedule_and_citation_changes': stage_changes,
               'live_search_tool_calls': 3, 'live_search_queries': 10, 'source_open_attempts': 12,
               'source_find_operations': 4, 'opened_applicable_or_scoped_documents': 10,
               'source_open_failures': {'timeout': 1, '404_document': 1}, 'page_find_misses': 1,
               'underlying_http_requests': None, 'amap_calls': 0, 'browser_calls': 0,
               'external_model_api_calls': 0, 'new_scoped_claims': len(claims),
               'new_corroborated_hard_claims': sum(c['ingest_verdict']['usable_as_hard_fact'] for c in claims),
               'catalogue_base_unchanged': True, 'official_benchmark_scores': None,
               'real_world_accuracy': None, 'measured_network_savings': None,
               'limits': evaluation['limitations']}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    scripts = [ROOT / 'scripts' / name for name in ('p19_sandbox_tool.py', 'p19_ingest_overlay.py', 'p19_extract_live.py', 'p19_evaluate.py', 'p19_report.py')]
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name not in ('manifest.json', 'current_evaluation.json') and not p.name.endswith(('-wal', '-shm'))] + scripts
    inventory = [{'file': str(p.relative_to(ROOT)), 'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(set(files))]
    (OUT / 'manifest.json').write_text(json.dumps({'at': summary['at'], 'baseline': protocol['baseline'], 'files': inventory,
                    'evidence_bytes': sum(e['bytes'] for e in inventory), 'no_truth_certification': True}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'queries': 2, 'revision_queries': 1, 'events': dict(counts), 'evidence_files': len(inventory), 'strict_accepted': summary['strict_accepted_dynamic_plans']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
