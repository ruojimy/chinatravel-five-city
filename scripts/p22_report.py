"""Seal the engineering iteration and a human-readable conditional itinerary."""
import hashlib
import html
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p22_adaptive_delivery'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.adaptive_delivery import evaluate_delivery

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def main():
    assert not (OUT/'REPORT.md').exists(),'Preserve first engineering report'
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    p=read(OUT/'plans/D01/deliverable.json');inp=read(OUT/'participant_input.json')
    evaluation=evaluate_delivery(p,inp['request'],entities=inp['entities'],references=inp['references'])
    assert evaluation['proposal_ok']
    old=read(OUT/'protected_previous.json');bad=[f for f,h in old['sha256'].items() if sha(ROOT/f)!=h]
    assert not bad,bad
    assert sha(ROOT/old['baseline']['catalog'])==old['baseline']['sha256']
    tests=[]
    for name in ('test_adaptive_delivery.py','test_p22_delivery_mutations.py','test_freshness_live.py'):
        proc=subprocess.run([sys.executable,str(ROOT/'tests'/name)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        output=proc.stdout+'\n'+proc.stderr
        (OUT/'logs'/('test_'+name+'.log')).write_text(output,encoding='utf-8')
        match=re.search(r'Ran (\d+) tests?',output)
        tests.append({'suite':name,'passed':proc.returncode==0,'tests':int(match[1]) if match else None})
    assert all(t['passed'] for t in tests),tests
    assertions=[{'name':x['name'],'ok':x['ok']} for x in evaluation['proposal_checks']]
    assertions += [{'name':'P21_protected_artifacts_unchanged','ok':not bad},
      {'name':'formal_catalogue_unchanged','ok':True}, {'name':'regression_suites','ok':all(t['passed'] for t in tests)}]
    ledger=read(OUT/'live/amap_final_ledger.json')
    claims=read(OUT/'claims.json');views=claims['views']
    initial=read(OUT/'protocol.json')['freeze']
    amendments=[{'file':f,'initial_sha256':h,'final_sha256':sha(ROOT/f)} for f,h in initial.items() if sha(ROOT/f)!=h]
    save(OUT/'implementation_amendments.json',{'at':stamp,'amendments':amendments,
      'reason':'Engineering fixes after generation feedback: explicit anchor decision compiler; explicit shared-resource grouping and diverse selection; adversarial tests. Initial inputs and raw model outputs preserved. Not preregistered.'})
    logs=[read(f) for f in sorted((OUT/'logs').glob('participant_*.json'))]
    usage={k:sum(x.get('usage',{}).get(k,0) for x in logs) for k in ('prompt_tokens','completion_tokens','total_tokens')}
    usage.update({'successful_responses':len(logs),'aborted_inflight_request_possible':True,'billing_total_known':False})
    summary={'at':stamp,'status':'one_live_conditional_itinerary_delivered',
      'live_cases':1,'offline_repaired_cases':4,'model':'deepseek-flash','generation':'model output plus deterministic anchor compiler',
      'proposal_checks_passed':sum(x['ok'] for x in assertions),'proposal_checks_total':len(assertions),
      'plan_checks':len(evaluation['proposal_checks']),'tests':tests,'test_count':sum(x['tests'] for x in tests),
      'amap_api_calls':ledger['spent_cumulative'],'weather_claims':1,'route_claims':4,
      'source_estimates':sum(v['evidence_use']=='provider_estimate' for v in views),
      'published_references':sum(v['evidence_use']=='published_reference' for v in views),'certified_facts':sum(v['usable_as_hard_fact'] for v in views),
      'budget_projection_cny':320,'budget_limit_cny':500,'confirmed_total_cny':None,
      'usage':usage,'execution_certified':False,'official_benchmark_acceptance':None,
      'not_preregistered':True,'measured_network_savings':None,
      'retrieval_trace_note':'Root performed bounded source retrieval; queue optimizer replayed saved task sets. This is not proof of unattended retrieval or measured API savings.',
      'frozen_previous_preserved':True,'remaining_prerequisites':p['before_departure']}
    save(OUT/'summary.json',summary)
    save(OUT/'validation.json',{'at':stamp,'ok':all(x['ok'] for x in assertions),'checks':assertions,
      'scope':'Artifact integrity, proposal consistency, and adversarial regression. No inventory or physical-trip certification.'})
    source_urls={
      '岳麓书院票价、开放与预约':'https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm',
      '岳麓书院与中国书院博物馆同一参观组':'https://ylsy.hnu.edu.cn/wbly/wbsy.htm',
      '湖南博物院官方预约渠道声明':'https://hunan.voc.com.cn/news/202507/30107492.html',
      '高德地点/入口文档':'https://lbs.amap.com/api/webservice/guide/api/search/',
      '高德天气与路线':'https://lbs.amap.com/',
    }
    weather=read(OUT/'live/amap_recovery_probe.json')['claim']
    routes={n:inp['references']['route:'+n] for n in ('outbound','return')}
    note='方案依据2026-10-23本轮查询制定，预约尚未代办。交通与天气是提供方估计，出发前需重查；消费上限是计划决策。'
    lines=['# 长沙两人一日行程｜2026年10月24日','',note,'',
      '**安排：湖南博物馆（湖南博物院）—馆内午餐—岳麓书院—返回。09:00从湖南博物院正门开始，计划16:57返回，距离18:00截止仍有63分钟缓冲。**','',
      '| 时段 | 安排 | 具体做法 |','|---|---|---|',
      '| 09:00–12:00 | 湖南博物馆基本陈列 | 正门集合，含安检入馆。只选免费基本陈列预约，不另买收费特展。 |',
      '| 12:00–12:45 | 蒸浏记·浏阳蒸菜（省博物馆店） | 位于馆内餐饮区域。两人限额100元，先请店员确认所选菜不放辣椒、不加辣油。无法确认就更换菜品或餐厅。 |',
      '| 12:45–13:00 | 离馆与集合 | 留15分钟到出口，准备乘地铁。 |',
      '| 13:00–13:59 | 去岳麓书院 | 高德估计48.5分钟，另加至少10分钟缓冲。 |',
      '| 14:00–16:00 | 岳麓书院 | 讲堂、古建筑群及书院文化。中国书院博物馆属于同一参观组，不另算第三个独立景点。 |',
      '| 16:00–16:57 | 返回湖南博物院正门 | 高德估计46.48分钟，另加至少10分钟缓冲。 |',
      '| 16:57–18:00 | 返程余量 | 已回起点，预留63分钟以应对排队、换乘等波动。 |','',
      '## 地铁怎么走','',
      '- 去程：从高德标记的博物馆入口出发，步行到湘雅医院站，6号线至六沟垅，换4号线至湖南大学站，再步行到岳麓书院入口。',
      '- 返程：湖南大学站乘4号线至六沟垅，换6号线至湘雅医院站，步行返回。',
      '- 单人每程3元，两人往返参考12元。API两程步行合计约3.04公里，另有馆内步行；耗时已包含API所列接驳步行。',
      '- 坐标来自高德POI的entr_location，不使用静态库的漂移坐标。它表示提供方入口点，现场正门与实际检票通道仍需核对。','',
      '## 两人预算','',
      '| 项目 | 本方案额度 | 依据 |','|---|---:|---|',
      '| 博物馆基本陈列 | 0元 | 仅接受免费基本陈列预约的选择条件；没有声称已订票或已确认库存 |',
      '| 岳麓书院 | 80元 | 官网公布全价40元/人，2人；购票时复核 |',
      '| 午餐 | 100元 | 两人消费上限；高德分店人均参考37元，不是当前菜单报价 |',
      '| 市内交通 | 40元 | 高德两人往返参考12元，额外留出交通余量 |',
      '| 额外预留 | 100元 | 应急支出上限 |',
      '| 合计 | **320元** | 低于500元总预算180元；这是消费计划，不是已确认总价 |','',
      '## 出发前完成这四步','',
      '1. 在“湖南博物院”官方微信公众号或官方支付宝小程序，确认10月24日上午免费基本陈列预约成功。未预约成功，先调整方案。',
      '2. 通过“岳麓书院”官方微信公众号确认当日下午预约和票价。官网说明未预约谢绝入院，不能现场碰运气。',
      '3. 午餐点单前确认具体菜品不加辣椒、辣油和辣椒酱，且两人不超100元；历史报道和湘菜分类都不能代替店员确认。',
      '4. 当日出发前重查天气与两程地铁。若耗时加缓冲超出安排或票价超额度，触发重排，不把本表当保证。','',
      f"天气参考：高德发布于{weather['observed_at']}的预报，10月24日多云，22/16℃，西北风1–3级。带轻便外套，户外步行段临近出发复查。",'',
      '## 信息来源','']
    lines += ['- ['+name+']('+url+')' for name,url in source_urls.items()]
    lines += ['', '原始API响应、坐标、路线与字段证据位于本目录live/；完整机器行程为plans/D01/deliverable.json。','']
    (OUT/'DELIVERABLE.md').write_text('\n'.join(lines),encoding='utf-8')
    rows=''.join('<tr>'+''.join('<td>'+html.escape(v.strip())+'</td>' for v in line.strip('|').split('|'))+'</tr>' for line in lines if line.startswith('|') and not line.startswith('|---'))
    # Standalone readable artifact, not a hosted website. All underlying plan data remains JSON/Markdown.
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>长沙一日行程</title><style>body{font:18px/1.7 "Microsoft YaHei",sans-serif;max-width:1050px;margin:40px auto;padding:0 25px;color:#18352e}h1{font-size:36px}table{border-collapse:collapse;width:100%;font-size:16px}td{padding:12px;border:1px solid #cbdcd5}tr:nth-child(odd){background:#eff5f2}aside{background:#f8f0d8;padding:15px}a{color:#076f58}</style><h1>长沙两人一日行程</h1><p>2026年10月24日 · 湖南博物馆 / 馆内午餐 / 岳麓书院</p><aside>'+html.escape(note)+'</aside><h2>计划与预算</h2><table>'+rows+'</table><h2>出发前确认</h2><ol>'+''.join('<li>'+html.escape(x)+'</li>' for x in lines if re.match(r"^[1-4]\. ",x))+'</ol><p>预算额度320元，交通提供方两程分别约48.5和46.5分钟。预约和具体菜品确认尚未完成。</p><p><a href="DELIVERABLE.md">查看完整行程、地铁路线与来源</a></p></html>'
    (OUT/'DELIVERABLE.html').write_text(document,encoding='utf-8')
    report=['# P22 动态检索与可交付行程优化','',
      '已交付一份有新天气、入口坐标、双向地铁、票价参考和明确预算的长沙行程。完整路线和出发前步骤见DELIVERABLE.md。', '',
      '## 根因与改动','',
      '- P21 0/9混合了原生schema、资料未知与出发时间错误，且没有新检索，不能用来评判新检索的效果。',
      '- 新增adaptive_delivery.py：按缺口影响/请求成本排序；同城市预报和同运营方页面合并；保留双向/不同出发时刻路线；按明确visit_group去除同景区重复计数。',
      '- 候选重排优先具体分店和可引用字段。新增的馆内餐厅只进会话候选，不改正式库。',
      '- 修正动态阶段映射，修订锁定集从实际前稿生成；旧4个动态稿做离线锚点修复回放，D02出发时间从09:50改为10:00。',
      '- 决策/公布参考/提供方估计/已核实事实分层输出。旧freshness硬事实门没有放宽；8个新字段证据中5个API估计、3个公布规则参考、0个certified fact。',
      '- 对模型的会面/结束备注增加确定性锚点编译，原始模型输出保留，活动时段没有因此移动。', '',
      '## 实际检索与结果','',
      '用户本轮明确恢复高德授权，实际8次调用：1次天气、4次POI文本搜索、1次批量POI详情、2次不同时间和方向的地铁。8次均成功，无换Key。',
      '工具层检索另含15条搜索query（包括API技术文档）、14次来源打开/点击尝试、3次页内查找；底层HTTP请求数未知。部分网页打不开或正文仅搜索可见，按来源分别保留缺口。',
      '去程48.5min、返程46.4833min，均3元/人。入口从Amap entr_location取得，路线上下行时间与24日13:00/16:00绑定。',
      '岳麓书院公布全价40元/人、预约要求和开放规则；网页无可见发布时间，仍为published_reference。分店消费参考37元/人来自地图列表，不是菜单报价。',
      '预算采用320元消费包络（含100元预留），严格区分0元免费场次选择决策与已确认免费票。两处预约、当日餐食不辣仍需实际确认。', '',
      '## 验证','',
      f"行程一致性检查{len(evaluation['proposal_checks'])}/{len(evaluation['proposal_checks'])}通过；旧结果与正式库哈希不变。",
      f"回归共{summary['test_count']}项通过：任务/证据/阶段测试14项，真实交付稿的对抗变异9项，旧freshness测试36项。反例包括错误日期、压缩交通时间、改出发时刻、同景区重复计数、假证据、预算超限和将预算写成报价。", '',
      '## 实验解释','',
      '这是工程迭代：根侧有限检索和人工审阅来源，再由DeepSeek输出并经过确定性编译。并非完全无人干预检索或盲测模型能力。候选与日程窗口经过规则约束，不把文本生成当独立规划能力成绩。',
      '任务队列的7→6请求单元是同一已保存任务集的离线合并回放；不是测得网络节省率，实际API仍为8次。其余3城只有离线决策修复，没有新实时可执行方案。',
      '初稿API默认thinking耗尽6000输出预算并产生空content；之后显式thinking disabled。所有已回包调用计入usage。一次在途请求曾中断，供应商计费总量不能据本地日志确定。',
      '阶段/锚点等实现因反馈继续修改，初始hash与最终hash见implementation_amendments.json，非预注册。旧P21和正式库保持。',
      '36项计划检查通过不代表官方benchmark通过。原生schema仍不能用未知填0过关，本轮未报告官方通过率。预约/菜品/物理到达不作保证。', '',
      '## 复现入口','',
      '算法src/shorttrip/adaptive_delivery.py；准备scripts/p22_prepare.py；生成scripts/p22_run.py；封存scripts/p22_report.py。输入、模型原文、失败及修复均在本目录。已存在的模型行程禁止覆盖，重新实验须换目录。','']
    (OUT/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    save(OUT/'source_index.json',{'sources':source_urls,'raw_packets_local_only':True,'claims':[{'claim_id':c['claim_id'],'field':c['field'],'source_url':c['source_url'],'raw_sha256':c['raw_sha256'],'source_published_at':c.get('source_published_at'),'observed_at':c.get('observed_at')} for c in claims['claims']]})
    files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json' and p.suffix!='.zip']
    files += [ROOT/'src/shorttrip/adaptive_delivery.py']+[ROOT/'scripts'/x for x in ('p22_prepare.py','p22_run.py','p22_report.py')]+[ROOT/'tests'/x for x in ('test_adaptive_delivery.py','test_p22_delivery_mutations.py')]
    save(OUT/'manifest.json',{'at':stamp,'path_base':str(ROOT),'files':[{'file':str(f.relative_to(ROOT)).replace('\\','/'),'sha256':sha(f),'bytes':f.stat().st_size} for f in sorted(set(files))]})
    # No credentials or full copyrighted web responses are redistributed in the handoff zip.
    archive=OUT/'P22_算法与长沙行程交付.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        names=['DELIVERABLE.md','DELIVERABLE.html','REPORT.md','summary.json','validation.json','source_index.json','plans/D01/deliverable.json','delivery_evaluation.json','offline_repair_audit.json','implementation_amendments.json']
        for name in names:z.write(OUT/name,name)
        for f in files:
            if f.is_relative_to(ROOT/'src') or f.is_relative_to(ROOT/'scripts') or f.is_relative_to(ROOT/'tests'):
                z.write(f,str(f.relative_to(ROOT)).replace('\\','/'))
        for f in (OUT/'logs').glob('test_*.log'):z.write(f,'tests/'+f.name)
    assert all(sha(ROOT/x['file'])==x['sha256'] for x in read(OUT/'manifest.json')['files'])
    print(json.dumps({'status':summary['status'],'checks':len(assertions),'tests':summary['test_count'],'amap_calls':8,'zip':str(archive)},ensure_ascii=False))

if __name__=='__main__':main()
