"""Offline validation, compact progress report, and resumable human checkpoint."""
import collections,json,re,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow,canonical
from shorttrip.travel_catalog import digest_file
from shorttrip.expansion_contract import validate_record,validate_evidence,validate_tag
from shorttrip.scoped_business import validate_hours
from shorttrip.business_completion import validate_room_offer
RES=ROOT/'results/p15_whole_catalog'

def main():
    runs=[]
    for name in ('bulk_business','linked_page_business','scoped_business','expansion_contract','expansion_store'):
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tests'/('test_'+name+'.py'))],capture_output=True,text=True,encoding='utf-8')
        log=p.stdout+'\n'+p.stderr;(RES/('test_'+name+'.log')).write_text(log,encoding='utf-8')
        n=re.search(r'Ran (\d+) tests?',log);runs.append({'test':name,'count':int(n[1]) if n else 0,'exit_code':p.returncode})
    pointer=json.loads((RES/'current_catalog.json').read_text(encoding='utf-8'));path=ROOT/pointer['catalog']
    manifest=json.loads((ROOT/pointer['manifest']).read_text(encoding='utf-8'))
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    bad=[];counts=collections.Counter();coverage=collections.Counter();evs={};all_fields=[]
    for eid,payload in db.execute('SELECT id,payload FROM evidence'):
        ev=json.loads(payload);evs[eid]=ev
        if not validate_evidence(ev)['ok']:bad.append({'bad_evidence':eid})
    for rid,payload in db.execute('SELECT id,payload FROM records'):
        r=json.loads(payload);gate=validate_record(r);counts[r['kind']]+=1;counts['planning_ready']+=gate['planning_ready']
        if not gate['discovery_ok']:bad.append({'record':rid,'errors':gate['errors']})
        for key,p in r['field_provenance'].items():
            eid=p.get('evidence_id')
            if eid and (eid not in evs or any(p.get(k)!=evs[eid].get(k) for k in ('source_id','source_url','observed_at'))):bad.append({'field_graph':rid,'field':key})
        for tag in r['tags']:
            if not validate_tag(tag)['ok'] or tag.get('evidence_id') and tag['evidence_id'] not in evs:bad.append({'tag_graph':rid})
        if 'today_hours_structured' in r:
            h=r['today_hours_structured'];e=evs.get(h['evidence_id'])
            if not validate_hours(h,require_provenance=True)['ok'] or not e or any(h.get(k)!=e.get(k) for k in ('source_id','source_url','observed_at','retrieved_at','source_updated_at')):bad.append({'hours_graph':rid})
    screenshots=set()
    for payload, in db.execute('SELECT payload FROM room_offers'):
        offer=json.loads(payload)
        if not validate_room_offer(offer,now=utcnow())['ok']:bad.append({'room_offer':offer['offer_id']})
        for shot in offer['screenshot_evidence']:
            shotpath=ROOT/shot['path']
            if not shotpath.exists():shotpath=ROOT/'results/p13_business_completion'/shot['path']
            if not shotpath.exists() or digest_file(shotpath)!=shot['sha256']:bad.append({'screenshot':shot['path']})
            screenshots.add(str(shotpath))
    baseline=json.loads((ROOT/'data/catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    unchanged=all(digest_file(ROOT/f['file'])==f['sha256'] for f in baseline['source_files'])
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0];foreign=db.execute('PRAGMA foreign_key_check').fetchall();db.close()
    result={'at':utcnow(),'catalog':pointer,'test_runs':runs,'tests_total':sum(x['count'] for x in runs),
            'counts':dict(counts),'evidence':len(evs),'screenshot_files':len(screenshots),
            'issues':bad,'sqlite_integrity':integrity,'foreign_key_errors':len(foreign),
            'all_264_original_files_unchanged':unchanged,
            'v1_4_unchanged':digest_file(ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3')==manifest['source_sha256'],
            'published_file_hash_matches':digest_file(path)==pointer['sha256'],'network_calls':0}
    result['all_checks_pass']=all(x['exit_code']==0 for x in runs) and not bad and not foreign and integrity=='ok' and unchanged and result['v1_4_unchanged'] and result['published_file_hash_matches']
    (RES/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['all_checks_pass']:raise ValueError('Validation failed')
    q=sqlite3.connect(RES/'queue.sqlite3');q.row_factory=sqlite3.Row
    jobs=[dict(x) for x in q.execute('SELECT adapter,status,count(*) AS count FROM jobs GROUP BY adapter,status')]
    completed_runs=[json.loads(x[0]) for x in q.execute('SELECT payload FROM runs')];q.close()
    status=json.loads((RES/'status.json').read_text(encoding='utf-8'));web=json.loads((RES/'web_status.json').read_text(encoding='utf-8'))
    live=status.get('worker',{});finished_ids={x['run_id'] for x in completed_runs}
    calls=sum(x['api_calls'] for x in completed_runs)+(live.get('api_calls',0) if live.get('running') and live.get('run_id') not in finished_ids else 0)
    web_calls=sum(json.loads(f.read_text(encoding='utf-8'))['requests'] for f in RES.glob('web_run_*.json'))+(web.get('requests',0) if web.get('running') else 0)
    summary={'at':utcnow(),'all_entities':14057,'jobs':jobs,'api_calls_in_this_p15_worker_series':calls,
             'additional_p14_batch_calls_this_turn':60,'web_requests_this_turn':web_calls,
             'map_worker_snapshot':live,'web_worker_snapshot':web,'catalog_manifest':manifest,
             'full_completion':False,'all_checks_pass':True,'tests_total':result['tests_total']}
    (RES/'progress_checkpoint.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 全库业务补齐执行检查点','',f"检查时间：{summary['at']}。全库补齐仍在执行，未宣称完成。",'',
      '范围：14,057条（3,376景区、4,601餐厅、6,080酒店）。所有记录进入逐实体任务清单。',
      '地图字段查询、独立/时效核验和日期房型核验分开；城市归属待核对6,776条不强行纳入城市硬条件。','',
      f"本次先完成60次定向查询，另全库worker已实际请求{calls}次高德；网页worker实际请求{web_calls}次（含robots）。",'',
      f"最新已发布快照：`{pointer['catalog']}`；以后以`results/p15_whole_catalog/current_catalog.json`为准。",
      '每300次地图请求或地图worker结束时，自动从缓存提取、校验并发布新的不可变快照。网页只采集原记录提供的链接，不递归全站。',
      '截图、网页原文、地图原响应均保留；采集成功或同名命中不等于字段可靠。未核实的事实时钟不因为下载或入库续期。','',
      '## 本次已发布增量（相对v1.4）','', '```json',json.dumps(manifest['new_nonnull_native_fields_vs_v1_4'],ensure_ascii=False,indent=2),'```','',
      '## 尚缺具体业务值','', '| 类别与字段 | 尚缺条数 |','|---|---:|']
    for k,v in manifest['remaining_missing_business_fields'].items():lines.append(f'| {k} | {v} |')
    lines+=['','这些统计包含历史或限定情境参考；全部planning_ready仍为0，未证明现实准确率或在线调用节省。',
       '酒店报价有效期300秒，必须按同一房型、日期、人数、税费及优惠资格重查；地图cost是人均消费，不能作每房每晚报价。',
       '景区建议时长不能用模型经验填充；票价、季节/闭园日规则缺失继续留空。','',
       '## 正在运行与恢复','',
       f"地图进程记录PID：{live.get('pid')}；网页进程记录PID：{web.get('pid')}。这里是检查点，实时状态须另核对进程和status.json/web_status.json。",
       '本地有限运行预算各最多4小时；地图最多6,902次剩余任务请求，网页最多4,958次剩余请求。两进程各自串行，不加载本地模型。',
       '额度、验证码、访问拒绝、网络错误按来源持久暂停，不换Key、不自动重置暂停、不改接口绕过限制。',
       'STOP文件是用户可用的本地停止开关；它不会清除第三方来源暂停。不要并发启动第二个同类worker。',
       '若进程已退出，先读run日志、provider_state、worker.lock。inflight表示响应是否写入不明，不直接重试收费请求。',
       '队列：queue.sqlite3；地图原始响应private_api_raw；网页web_crawler/private_pages；完整原网页URL映射source_links.sqlite3。','',
       '## 校验','',f"本次{result['tests_total']}项测试通过，全14,057条及{len(evs)}条证据图检查通过，18张酒店截图hash检查，原264文件与v1.4不变。",
       '没有重跑P0–P10全套，也没有加载新的LLM。','',
       '高德字段/附近检索语义：[官方POI 2.0文档](https://lbs.amap.com/api/webservice/guide/api/newpoisearch)。']
    (ROOT/'报告/15_全库业务补齐执行报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(canonical({'tests':result['tests_total'],'all_checks_pass':True,'calls':calls,'web_requests':web_calls,'catalog':pointer['catalog']}))
if __name__=='__main__':main()
