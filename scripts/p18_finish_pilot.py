"""Assemble the first finite pilot without changing its frozen implementation."""
import collections
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p18_dynamic_eval'
HOTEL = ROOT / 'results/p17_continuous/hotels/dynamic_hotel_eval_002'

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def rawtext(d):
    r = d['complete_tool_result']
    return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)

def main():
    if (OUT / 'summary.json').exists():
        raise SystemExit('First pilot already frozen. Use a new output version; do not overwrite first results.')
    now = datetime.now(timezone.utc).isoformat()
    protocol = read(OUT / 'protocol.json')
    assert sha(ROOT / protocol['catalogue_basis']['catalog']) == protocol['catalogue_basis']['sha256']
    code_checks = {f: sha(ROOT / f) == h for f, h in protocol['implementation_hashes'].items()}
    assert all(code_checks.values()), code_checks
    specs = [
        ('R01_missing_hours', 'scoped_reference_only',
         '两篇用户游记给出约20:30结束营业的历史参考；无法保证2026-10-24的20:30仍接待，不能承诺21:30前完成用餐。',
         ['当日营业与最后点单时间', '20:30入店是否接待', '用餐完成时限'],
         [('open_01.json', '营业时间：约 10:30 - 20:30'),
          ('open_02.json', '地址：(长春)西民主大街1059号'),
          ('open_02.json', '营业时间：11:00-20:30')],
         '是否改到更早时段，或换一家能核实晚间接待的餐厅？'),
        ('R02_branch_conflict', 'conflict_retained',
         '2023年区政府文章支持第十甫路67号的历史地址；品牌档案不能证明139号与原实体同店，原研究城市归属也不能由品牌名修正。不套用另一分店的人均。',
         ['67号与139号当前分店关系', '适用分店的当日人均与营业', '研究城市窗口与现实城市对应'],
         [('open_01.json', '发布时间: 2023-08-03'),
          ('open_01.json', '莲香楼位于荔湾区第十甫路67号')],
         '请先选定实际分店地址；也可换一家身份已经核实的候选。'),
        ('R03_uncertified_diet', 'insufficient_evidence',
         '用户社区仅表达看起来以植物性食材为主，且区分素面馆与相邻素菜馆；文化条目介绍传统素菜。均不能证明指定分店无蛋奶或避免交叉接触。',
         ['准确分店身份', '所选菜品无蛋奶', '厨房交叉接触控制'],
         [('open_01.json', 'Last update on 23 Jan 2024'),
          ('open_01.json', 'if anyone discovers egg or dairy here please update HappyCow.'),
          ('open_02.json', '部分信息来源于网络')],
         '需要向目标餐厅核实具体菜品和厨房流程；未核实前是否换候选？'),
    ]
    cases, sources, searches = [], [], []
    for cid, outcome, answer, missing, quotes, question in specs:
        directory = OUT / 'restaurants' / cid
        frozen = read(directory / 'static_first.json')
        assert frozen['catalogue_basis']['sha256'] == protocol['catalogue_basis']['sha256']
        opens = sorted(directory.glob('open_*.json'))
        assert 2 <= len(opens) <= 3
        for p in sorted(directory.glob('search_*.json')):
            d = read(p)
            searches.append({'case_id': cid, 'file': str(p.relative_to(OUT)),
                             'sha256': sha(p), 'query': d['query'],
                             'started_at': d['started_at'], 'ended_at': d['ended_at']})
        for p in opens:
            d = read(p)
            failed = 'Internal Error' in rawtext(d) or 'Failed to fetch' in rawtext(d)
            matching = [q for f, q in quotes if f == p.name]
            assert all(q in rawtext(d) for q in matching), (cid, p.name)
            sources.append({'case_id': cid, 'file': str(p.relative_to(OUT)), 'sha256': sha(p),
                            'url': d['url'], 'declared_publisher_group': d['independent_source_group'],
                            'independent_factual_confirmation_established': False,
                            'open_success': not failed, 'quote_membership_verified': True,
                            'short_quotes': matching, 'retrieved_at': d['ended_at'],
                            'observed_at': None, 'source_updated_at': None,
                            'source_published_at': ('2023-08-03' if cid.startswith('R02') and p.name == 'open_01.json' else None),
                            'publication_date_scope': 'article date only; not current fact observation',
                            'ttl_policy': 'opening rules/diet/identity require applicable current evidence; retrieval does not renew fact age'})
        cases.append({'case_id': cid, 'query': frozen['query'],
                      'target_record_id': frozen['target_record']['record_id'],
                      'static_baseline_file': str((directory / 'static_first.json').relative_to(OUT)),
                      'static_hard_requirements_met': False, 'outcome': outcome,
                      'strictly_resolved_fields': 0, 'safe_answer': answer,
                      'unresolved_fields': missing, 'proposed_user_question': question,
                      'unsupported_hard_claims_in_self_audit': 0,
                      'source_open_attempts': len(opens), 'formal_ingestion': False})
    restaurant = {'at': now, 'catalogue_basis': protocol['catalogue_basis'],
                  'case_selection': 'purposive known defects, no blind or human truth labels',
                  'synthesis': 'Root completed saved evidence review after agent capacity error; no model switch.',
                  'cases': cases, 'sources': sources,
                  'request_ledger': {'search_tool_calls': len(searches), 'search_queries': len(searches),
                                     'source_open_tool_calls': len(sources), 'source_open_attempts': len(sources),
                                     'successful_source_opens': sum(s['open_success'] for s in sources),
                                     'failed_source_opens': sum(not s['open_success'] for s in sources),
                                     'searches': searches},
                  'source_clock_notes': ['Sina article displays 26-02-09, year/zone not normalized.',
                                         'Autohome trip narrative says December2020; exact publication clock blank.',
                                         'HappyCow listing update23Jan2024 is not observed date; individual reviews differ.',
                                         'Government publication2023-08-03 is historical; ministry/cultural page current fact clocks unknown.'],
                  'pause': {'host': 'www.feinfood.com', 'reason': 'web tool Internal Error; do not retry through another interface', 'http_status': None}}
    write(OUT / 'restaurants/case_results.json', restaurant)
    attraction = read(OUT / 'attractions/case_results.json')
    hotel = read(HOTEL / 'case_packet.json')
    assert hotel['source_catalog']['sha256'] == protocol['catalogue_basis']['sha256']
    for s in hotel['sources']:
        for key, hashkey in [('content_file', 'content_sha256'), ('dom_text_file', 'dom_text_sha256')]:
            assert sha(HOTEL / s[key]) == s[hashkey], s[key]
    unified = [dict(case_id=c['case_id'], kind='attraction', outcome=c['outcome'], strict_new_fields=len(c['strictly_resolved_fields']) if isinstance(c['strictly_resolved_fields'], list) else c['strictly_resolved_fields']) for c in attraction['cases']]
    unified += [dict(case_id=c['case_id'], kind='restaurant', outcome=c['outcome'], strict_new_fields=c['strictly_resolved_fields']) for c in cases]
    unified += [dict(case_id=c['case_id'], kind='accommodation', outcome=c['skill_live_arm']['outcome'], strict_new_fields=c['skill_live_arm']['newly_resolved_hard_fields']) for c in hotel['cases']]
    hm, am, rm = hotel['measurement'], attraction['request_ledger'], restaurant['request_ledger']
    ledger = {'search_tool_calls': hm['search_tool_calls'] + am['search_tool_calls'] + rm['search_tool_calls'],
              'search_query_count': hm['search_query_count'] + am['search_queries'] + rm['search_queries'],
              'web_source_open_tool_calls': hm['supplemental_source_open_tool_calls'] + am['source_open_tool_calls'] + rm['source_open_tool_calls'],
              'direct_operator_http_opens': hm['primary_http_requests'],
              'source_open_attempts': hm['source_open_attempts_total'] + am['source_open_attempts'] + rm['source_open_attempts'],
              'successful_source_opens': 5 + am['successful_source_opens'] + rm['successful_source_opens'],
              'failed_source_opens': 1 + am['failed_source_opens'] + rm['failed_source_opens'],
              'underlying_search_http_requests': None,
              'note': 'Tool calls, queries and source attempts differ. Redirect/subrequest counts and comparable counterfactual network costs unmeasured.'}
    policy, lookup = read(OUT / 'policy_replay/results.json'), read(OUT / 'static_lookup/results.json')
    summary = {'at': now, 'version': 'p18-first-pilot-v1', 'status': 'first_pilot_complete_followup_required',
               'baseline': protocol['catalogue_basis'], 'code_hashes_unchanged': code_checks,
               'live_cases': unified, 'outcome_counts': dict(collections.Counter(c['outcome'] for c in unified)),
               'new_strictly_resolved_hard_fields': sum(c['strict_new_fields'] for c in unified),
               'request_ledger': ledger,
               'controlled_policy': {k: policy[k] for k in ['cases', 'method_trigger_correct', 'method_status_correct', 'synthetic_only']},
               'static_lookup': {k: lookup[k] for k in ['queries', 'total_returned_candidate_occurrences', 'total_logical_tasks']},
               'unsupported_hard_claims_report_self_audit': 0,
               'real_world_accuracy': None, 'measured_network_savings': None,
               'full_catalog_completion': False, 'live_weather_transit_validated': False,
               'implementation_gaps': ['Current CLI schedules field tasks unconditionally; policy replay selection is a separate controlled orchestration.',
                                       'TAG lookup API accepts keys, lacks requested value/negation/hard-soft constraints.',
                                       'Amap adapter stop is instance local; mock recreation repeats transport. Persistent outer source pause guard required.'],
               'limitations': ['9 deliberately difficult known-defect cases, not random/held-out.',
                               'Protocol froze 3seconds after first attraction search completion; not a fully prospective preregistered study.',
                               'Static arm is exact catalogue/unknown output, not a matched LLM answer generator.',
                               'Live skill execution uses manual agent judgement; current CLI does not automate the whole skill.',
                               'Zero unsupported hard claims is report self-audit, not externally judged factual accuracy.',
                               'No current weather/transit, end-to-end feasible itinerary or ChinaTravel score improvement demonstrated.']}
    write(OUT / 'summary.json', summary)
    # Hash every first-pilot evidence file, including the separate hotel packet.
    files = list(OUT.rglob('*')) + list(HOTEL.rglob('*'))
    entries = []
    excluded = {'manifest.json', 'evidence_validation.json', 'REPORT.md', 'current_evaluation.json'}
    for p in sorted(set(files)):
        if p.is_file() and p.name not in excluded and not p.name.endswith(('-wal', '-shm', '.lock')):
            entries.append({'file': str(p.relative_to(ROOT)), 'sha256': sha(p), 'bytes': p.stat().st_size})
    write(OUT / 'manifest.json', {'at': now, 'baseline_sha256': protocol['catalogue_basis']['sha256'], 'files': entries,
                                'scope': 'Evidence inventory; not proof of source truth or licence. Runtime SQLite is supplementary; raw HTML/packets are primary captured evidence.'})
    write(OUT / 'evidence_validation.json', {'at': now, 'pass': True, 'baseline_hash_verified': True,
          'frozen_code_hashes_unchanged': True, 'hotel_html_text_hashes_verified': 6,
          'restaurant_short_quote_membership_checks': sum(len(s['short_quotes']) for s in sources),
          'live_case_count': len(unified), 'max_source_open_attempts_per_case': 3,
          'manifest_files': len(entries), 'no_real_world_accuracy_proof': True})
    print(json.dumps({'cases': len(unified), 'outcomes': summary['outcome_counts'], 'ledger': ledger, 'manifest_files': len(entries)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
