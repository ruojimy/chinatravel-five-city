"""Seal evidence hashes, publish a report, and checkpoint without new network."""
import json,hashlib,zipfile
from pathlib import Path
from datetime import datetime
R=Path(__file__).resolve().parents[1];B=R/'results/p27_focused_deep_retrieval'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
now=datetime.now().astimezone().isoformat()
save(B/'source_request_audit.json',{'at':now,'search_batches':[
 {'capture':None,'queries':3,'note':'First Haikou/Xiamen/Changsha discovery batch. Exact first response not retained; no accepted evidence derives from it.'},
 {'capture':'web_search_round1.json','queries':3}, {'capture':'web_gov_search.json','queries':2}, {'capture':'web_search_round2.json','queries':2}, {'capture':'web_search_round3.json','queries':2}, {'capture':'web_search_round4.json','queries':4}],
 'page_opens':[
 {'url':'https://www.hainanmuseum.org/hnbwgcms/node/169','ok':True,'capture':'web_hainan_about.json'},
 {'url':'https://www.hainanmuseum.org/','ok':False,'capture':'web_hainan_home.json'},
 {'url':'https://www.xiamenbg.cn/Home/yyzn3','ok':True,'capture':'web_xiamen_ticket.json'},
 {'url':'https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm','ok':True,'capture':'web_round2.json'},
 {'url':'https://www.hainanmuseum.org/hnbwgcms/info/3591','ok':False,'capture':'web_round2.json'},
 {'url':'https://jyj.haikou.gov.cn/hksjyj/zxzx/202608/c6e6e08b4d4a491c93ca6e7d398ba80a.shtml','ok':True,'capture':'web_round2.json'},
 {'url':'https://sight.qunar.com/7675','ok':False,'capture':'web_qunar_failed.json'},
 {'url':'https://www.xiamenbg.cn/','ok':False,'capture':'web_xiamen_home_failed.json'}],
 'actual_amap_attempts':19,'total_attempts':43,'global_cap':48,'amap_cap':20,
 'per_case_web_cap_certified':False,'per_case_web_cap_note':'Per-case allocation was not persisted before dispatch; individual12/18/18 adherence is not certified, and cannot be used for a fair-budget causal comparison.',
 'failed_urls_paused':True,'old_paused_xiamen_hours_url_reopened':False,'no_key_rotation':True})
save(B/'implementation_amendments.json',{'at':now,'items':[
 {'change':'All round0 participant requests used date aliases and noncanonical weather targets; root normalized them into context.travel_date and weather:city.','impact':'Orchestration assistance, not pure model protocol success.'},
 {'change':'Researcher supplied precise origin/route times after original round1; separate clarified UIDs and queries saved.','impact':'Do not count clarified solves as original-task solves.'},
 {'change':'Bus fallback kept numeric diagnostics; gate now rejects real routes without explicit endpoint binding and mode satisfaction.','impact':'Shared retrieval_guard.py changed; old result archives were not rescored.'},
 {'change':'Source fields manually reviewed; no autonomous source-selection claim.','impact':'No randomized/equal-budget strategy comparison.'},
 {'change':'Local verification initially compared a canonical JSON hash with a file-byte hash. Preserved initial failed receipt; corrected verifier to the frozen serialization and direct P24-object equality.','impact':'No query data or freeze hash altered.'}]})
report=R/'报告/20_集中预算动态检索闭环测试与不足.md';report.write_bytes((B/'REPORT.md').read_bytes())
cp=R/'current_retrieval_state.json';state=read(cp);state.update(at=now,phase='p27_focused_deep_retrieval')
state['p27']={'cases':3,'llm_plan_drafts':12,'source_attempts':43,'amap_http_attempts':19,'final_conditionally_accepted_clarified_variants':1,'original_tasks_round1_accepted':0,'execution_confirmed':0,'snapshot_at':'2026-10-23T19:04:45+08:00','report':'results/p27_focused_deep_retrieval/REPORT.md','shared_guard_changed':True,'per_case_budget_certified':False}
state['new_paused_urls']=['https://www.hainanmuseum.org/','https://www.hainanmuseum.org/hnbwgcms/info/3591','https://sight.qunar.com/7675','https://www.xiamenbg.cn/'];save(cp,state)
sp=R/'STATE.md';old=sp.read_text(encoding='utf-8');heading,rest=old.split('\n',1)
checkpoint='''

## 最新检查点：2026-10-23，P27 集中预算三任务动态检索闭环

用户认为P24的40/528及96题调用太分散，要求优先给少量任务足够核验。新增 `results/p27_focused_deep_retrieval`、`报告/20_集中预算动态检索闭环测试与不足.md`。三个原题easy/E20海口、hard/H08厦门、human/H29长沙；3个参与子代理，各1首稿+3动态稿，共12完整plan及12决策记录。

- 实际43次来源请求=16搜索查询+8页面打开(4成功4失败)+19高德，均无换Key；总量43/48、高德19/20。单题12/18/18网页归属未在调用前逐次记账，无法认证个别题未超限，不作严格公平预算实验。首3查询完整回包未留，不供接纳证据。
- 原题round1接纳0/3，厦门和长沙精确起点未知。随后研究者给定起点及出返程时刻另建clarified UID，不能计原题完成。最终核心来源覆盖海口3/4、厦门8/9、长沙9/9；长沙条件方案原稿接纳，执行确认0。两个补起点变体接纳1/2，长沙复用岳麓书院是正向复验，不是新城泛化。
- 海口门票数值未知不填0；厦门运营原文缺失仍blocked，但西门往返地铁47.8167分钟/3元每人已通，两人预计72元。长沙火车站地铁站13:00出发、岳麓书院14–16点、17:00计划回站，两人门票80+往返地铁12=92元，预算200；实名预约未完成、临时运营/明日班次未保证。
- 发现厦门南侧请求metro却返回公交备选，旧门未核对entity_verified/mode_requirement_met。新增真实路线必须两个标记true的检查，公交1元数字拒用，保留失败捕获并另查西门。共享retrieval_guard.py改变，旧P21—P26归档未重新评分；当前22门控+23旧接口=45单元测试通过，34完整性检查通过。
- 最终快照19:04:45北京时间，路线最早19:14:38到期、天气最早19:34:00到期。报告是有限快照，现实出行须刷新。根侧检索审阅、请求别名修正、起点澄清及中途门控修复均披露；不称纯LLM无人值守或完全预注册。
- 入口REPORT.md、DELIVERABLE.md、summary.json、validation.json、source_request_audit.json、participants/round0..3、responses、evaluations及本地capture。离线复核scripts/p27_evaluate.py，联网capture不可当离线复现。新失败URL暂停见current_retrieval_state.json；旧暂停不恢复。下一步统一原子预算账本、补齐两条断链、独立新城正例与同题同预算分组对照。

---
'''
if 'P27 集中预算三任务动态检索闭环' not in old:sp.write_text(heading+checkpoint+rest,encoding='utf-8')
manifest=[]
for p in sorted(B.rglob('*')):
 if p.is_file() and p.name not in ('manifest.json',) and p.suffix!='.zip':manifest.append({'path':str(p.relative_to(B)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
save(B/'manifest.json',{'created_at':now,'files':manifest,'note':'Local evidence hashes. Public zip omits full-page/API evidence captures and response payloads; they remain local for audit.'})
with zipfile.ZipFile(B/'P27_集中检索测试与条件方案.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in B.rglob('*'):
  if p.is_file() and p.suffix!='.zip' and not any(part in ('capture','responses','private') for part in p.relative_to(B).parts):z.write(p,str(p.relative_to(B)))
print(json.dumps({'report':str(report),'files_hashed':len(manifest),'validation':read(B/'validation.json')['passed'],'public_zip_excludes_full_source_payloads':True},ensure_ascii=False))
