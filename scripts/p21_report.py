"""Seal the finite P21 run without altering participant, evaluator or earlier runs."""
from __future__ import annotations

import collections
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p21_flash_fixed'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def activities(answer):
    return [a for d in answer['proposed_plan']['itinerary'] for a in d['activities']]


def main():
    ev = load(OUT / 'evaluation.json')
    assert len(ev['evaluations']) == 9, 'All nine outputs required before sealing'
    protocol = load(OUT / 'public/protocol.json')
    queries = load(OUT / 'public/queries.json')
    plans = {(p.parent.name, p.stem): load(p) for p in (OUT / 'plans').glob('*/*.json')}
    states = [load(p) for p in sorted((OUT / 'agent_state').glob('*.json'))]
    logs = [load(p) for p in sorted((OUT / 'logs').glob('*.json'))]
    events = [load(p) for p in sorted((OUT / 'events').glob('*/*.json'))]
    claims = load(OUT / 'overlay/v001/claims.json')['claims']
    fail_names = collections.Counter(c['name'] for x in ev['evaluations']
                                     for c in x.get('adapted_evidence_aware_checks', []) if c['status'] == 'fail')
    usage = {k: sum(s['usage'].get(k, 0) for s in states)
             for k in ('calls', 'prompt_tokens', 'completion_tokens', 'total_tokens')}
    phases = {}
    for stage in ('static_first', 'dynamic_first', 'revised'):
        selected = [x for x in ev['evaluations'] if x['stage'] == stage]
        counts = collections.Counter()
        for x in selected:
            counts.update(x['check_counts'])
        phases[stage] = {'plans': len(selected), 'check_status_counts': dict(counts)}
    revisions = load(OUT / 'public/revision.json')
    old_ids = {a.get('entity_id') for a in activities(plans['D03', 'dynamic_first'])}
    target_locks = set(revisions['locked_entity_ids'])
    missing_prior_locks = sorted(target_locks - old_ids)
    phase_instruction_delivered = {}
    feedback_counts = collections.Counter()
    for s in states:
        user_messages = [m['content'] for m in s['messages'] if m['role'] == 'user']
        phase_instruction_delivered[s['case_id']] = any(m.startswith('动态阶段（冻结证据）') for m in user_messages)
        for m in user_messages:
            for prefix in ('SUBMIT_REJECTED', 'STAGE_ERROR', 'FORMAT_ERROR', 'TOOL_ERROR', 'BUDGET'):
                if m.startswith(prefix):
                    feedback_counts[prefix] += 1
    comparisons = {}
    for q in queries:
        cid = q['case_id']
        first, dynamic = plans[cid, 'static_first'], plans[cid, 'dynamic_first']
        before, after = activities(first), activities(dynamic)
        comparisons[cid] = {
            'static_entities': [a.get('position') for a in before if a.get('entity_id')],
            'dynamic_entities': [a.get('position') for a in after if a.get('entity_id')],
            'declared_changes': dynamic.get('plan_changes', []),
            'claims_reviewed': dynamic.get('claims_reviewed', []),
            'same_proposed_plan': first['proposed_plan'] == dynamic['proposed_plan'],
            'numeric_activity_costs_static': sum(isinstance(a.get('cost'), (int, float)) for a in before),
            'numeric_activity_costs_dynamic': sum(isinstance(a.get('cost'), (int, float)) for a in after),
        }
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    summary = {
        'at': stamp, 'status': 'finite_fixed_evidence_regression_complete_with_protocol_deviations',
        'participant': protocol['participant'], 'usage': usage,
        'queries': 4, 'plans': 9, 'static_first_proposals': 4,
        'dynamic_first_proposals': 4, 'revised_proposals': 1,
        'metrics': ev['metrics'], 'phases': phases, 'fail_checks': dict(fail_names),
        'tool_events': dict(collections.Counter(e['request']['action'] for e in events)),
        'api_response_models': dict(collections.Counter(x.get('model') for x in logs)),
        'feedback_counts': dict(feedback_counts), 'comparisons': comparisons,
        'evidence': {'mode': 'frozen_p20_overlay', 'claims': len(claims),
                     'all_unverified': all(c['ingest_verdict']['status'] == 'unverified' for c in claims),
                     'new_live_retrieval': 0, 'amap_calls': 0, 'browser_calls': 0},
        'protocol_deviations': {
            'predefined_dynamic_instruction_delivered': phase_instruction_delivered,
            'cause': "Session receives dynamic_first but branches on stage == 'dynamic'. Stage correction and submit guards recovered outputs; this is not the intended clean transition.",
            'revision_target_locks_not_in_prior_p21_plan': missing_prior_locks,
            'revision_note': 'The unchanged revision input reuses P20 hotel/lunch locks. Passing target presence cannot prove preservation from the actual P21 dynamic plan.',
            'freeze_note': 'Freeze was rebuilt after the static phase before this continuation; it is not fully preregistered. Frozen files were not changed in this continuation.',
        },
        'baseline_sha256': protocol['baseline']['sha256'],
        'official_benchmark_scores': None, 'real_world_accuracy': None,
        'limits': ev['limitations'] + [
            'Dynamic instruction dispatch failed for all four cases; outputs recovered using stage and submission feedback.',
            'D03 revision imports P20 target hotel/lunch entities, so target presence is not prior-plan preservation.',
            'P20/P21 differ in model, prompt, gateway and selected entities. This is not a controlled model ranking.',
            'The checker is a finite subset. It does not prove every query constraint, date, semantics or actual route.',
        ],
    }
    save(OUT / 'summary.json', summary)
    save(OUT / 'protocol_audit.json', summary['protocol_deviations'])
    table = ['| Case / 阶段 | pass | fail | unknown |', '|---|---:|---:|---:|']
    for x in ev['evaluations']:
        c = x['check_counts']
        table.append(f"| {x['case_id']} / {x['stage']} | {c.get('pass',0)} | {c.get('fail',0)} | {c.get('unknown',0)} |")
    m = ev['metrics']
    lines = ['# P21 DeepSeek Flash 固定证据回归报告', '',
             '日期：2026-10-23。参与模型配置为 `deepseek-flash`，API 返回名逐次记录在 logs。', '',
             f"已完成 4 份静态稿、4 份动态稿和 1 份修订稿，交付 {m['delivered']}/9，严格接纳 {m['strict_accepted']}/9。",
             f"三值检查合计：pass {m['check_status_counts'].get('pass',0)} / fail {m['check_status_counts'].get('fail',0)} / unknown {m['check_status_counts'].get('unknown',0)}。",
             '本轮仅复用 P20 的 21 条冻结证据，全部 unverified；新增 live 检索、高德与浏览器调用均为 0。', '',
             '## 实验范围与保留', '',
             '- 从 HANDOFF 的静态检查点续跑，未重跑或覆盖静态答案。',
             '- 正式库、P20 全部结果和 P20 PPT 按续跑前哈希核验。',
             '- 参与模型只通过 gateway 获取资料。评分未输入参与模型，但提交协议拒绝会反馈给模型。',
             '- 模型、提示词、gateway 和选中实体均与 P20 有差异，不能将差异归因为 Flash 与 Pro 的能力差异。', '',
             '## 逐稿结果', '', '\n'.join(table), '',
             'fail 分布：' + json.dumps(dict(fail_names), ensure_ascii=False) + '。',
             '严格接纳要求无 fail、无 unknown 且原生 schema 通过。原生 schema 的失败计入 fail，因此“无显式违反率”也受接口缺口影响。', '',
             '## 修复回归观察', '',
             '- 住宿数量、rooms 显式声明、厦门双床声明及证据消费检查，均按 evaluation.json 逐稿列出。房型声明通过不代表有当日库存。',
             '- 未核实免费继续保留 null。没有用 0 补齐价格；数值费用与原生投影审计独立记录。',
             '- Langham 的 reviewed alias 继续生效，原始记录保留，gateway 返回 canonical。',
             '- 原生投影仍受 start/end 扩展活动、未知 cost/price 及 transport 字段阻塞。投影 ready 只表示接口结构可输出，也不证明现实可行。', '',
             '## 静态与动态的实际差异', '']
    for cid, item in comparisons.items():
        lines.extend([f'### {cid}', '',
                      '静态实体：' + '、'.join(item['static_entities']) + '。',
                      '动态实体：' + '、'.join(item['dynamic_entities']) + '。',
                      f"审阅 claims：{len(item['claims_reviewed'])} 条。计划对象完全相同：{item['same_proposed_plan']}。",
                      f"带数值 cost 的活动：{item['numeric_activity_costs_static']} → {item['numeric_activity_costs_dynamic']}。", ''])
        for change in item['declared_changes']:
            lines.append('- 模型自述：' + str(change.get('change', change)) + '；原因：' + str(change.get('reason', '')))
        lines.append('')
    lines.extend(['## 本轮发现的协议偏差', '',
                  '**动态阶段启动分支有误。** CLI 将 dynamic 映射为 dynamic_first，但 Session 的初始化分支判断 dynamic，导致四个 case 都没有收到预定的动态说明。原始日志显示模型经 STAGE_ERROR、SUBMIT_REJECTED 等交互继续，最终通过证据读取/claims_reviewed 门禁。保留所有反馈与答案，本轮不能称为严格按预定流程的干净回归。', '',
                  '**修订输入沿用了 P20 的锁定实体。** P21 的 D03 动态稿选择 Atour Hotel、粤味乡与粤珍轩，而原有 revision.json 要求 Bestay 和两家面馆。该输入保持原样执行，故这些实体在修订中属于新目标，不能把 evaluator 的 locked_entities_preserved 通过解释为真实保留原稿。',
                  '未出现在原 P21 动态稿的锁定 ID：`' + '`, `'.join(missing_prior_locks) + '`。', '',
                  '**冻结时序。** freeze 在静态阶段之后重建，本续跑未修改冻结的 agent/evaluator/prompt/protocol/constraints/alias。不能称完全预注册。', '',
                  '## D03 修订结果', ''])
    revised = plans['D03', 'revised']
    for a in activities(revised):
        lines.append(f"- {a['type']}：{a['position']}，{a['start_time']}–{a['end_time']}。")
    lines.extend(['', '## 调用与证据账目', '',
                  f"P21 累计成功模型响应 {usage['calls']} 次，total_tokens {usage['total_tokens']:,}（静态与续跑合计，来自 usage 回包；不是计费账单）。",
                  '工具事件：`' + json.dumps(summary['tool_events'], ensure_ascii=False) + '`。',
                  '交互反馈：`' + json.dumps(dict(feedback_counts), ensure_ascii=False) + '`。', '',
                  '## 结论与后续', '',
                  '本轮完成有限候选日程与接口门禁回归。预算、实际到达、营业、饮食硬条件及日期房态仍有证据缺口；0 严格接纳不能用于推断模型没有规划能力。',
                  '后续应在新实验目录修正阶段映射，按新首稿生成修订锁定集，并把语义、日期、主题与偏好编译补成独立检查；保留本轮原始输出。再以已知可行解和合格证据构造对照，才能区分资料缺口与规划失败。', '',
                  '## 复核入口', '',
                  '`summary.json`、`evaluation.json`、`native_projection.json`、`protocol_audit.json`、`validation.json`、`manifest.json`、`plans/`、`events/`、`logs/`。',
                  '重算命令：`python scripts/p21_native_projection.py`、`python scripts/p21_evaluate.py`、`python scripts/p21_report.py`、`python scripts/p21_validate.py`。参与模型输出已存在，禁止重跑覆盖。', ''])
    report = OUT / 'REPORT.md'
    assert not report.exists(), 'Preserve first report'
    report.write_text('\n'.join(lines), encoding='utf-8')
    status = load(OUT / 'p21_status.json')
    status.update({'at': stamp, 'phase': summary['status'], 'static_plans': 4,
                   'dynamic_plans': 4, 'revised_plans': 1, 'evaluation_scope': 'all_nine_plans',
                   'check_status_counts': m['check_status_counts'],
                   'strict_accepted_plans': m['strict_accepted'],
                   'native_projection': {'ready': m['native_projection_ready'], 'blocked': m['native_projection_blocked']},
                   'protocol_audit': 'protocol_audit.json', 'next_commands': [], 'next_outputs': []})
    save(OUT / 'p21_status.json', status)
    save(OUT / 'current_evaluation.json', {'at': stamp, 'phase': 'p21_flash_fixed',
         'status': summary['status'], 'report': str(report.relative_to(ROOT)),
         'summary': 'results/p21_flash_fixed/summary.json', 'plans': 9,
         'strict_accepted_plans': m['strict_accepted'], 'baseline_sha256': protocol['baseline']['sha256']})
    print(json.dumps({'plans': 9, 'usage': usage, 'fail_checks': dict(fail_names)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
