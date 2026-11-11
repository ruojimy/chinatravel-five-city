"""Incremental offline HTML/JSON report; explicit denominators and all failures."""
from collections import Counter
from datetime import datetime,timezone
import importlib.util,json,statistics,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
PROJECT=Path(manifest['project'])
sys.path.insert(0,str(PROJECT))
spec=importlib.util.spec_from_file_location('soft_tables',PROJECT/'reproduction/soft_constraints/render.py')
table=importlib.util.module_from_spec(spec);spec.loader.exec_module(table)
base=table.base;e=base.e

def read(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def metrics(plan,audit):
    from rules import timeline,WINDOWS
    rows=timeline(plan)
    openings=[];waits=[];sightseeing=0
    for row in rows:
        if row['kind']=='attraction':sightseeing+=row['end']-row['start']
        legs=row['activity'].get('transports',[])
        if legs:
            # Place incoming clock intervals backwards from activity start.
            last=legs[-1]['end_time'];h,m=map(int,last.split(':'))
            arrival=(row['start']//1440)*1440+h*60+m
            if arrival>row['start']:arrival-=1440
            gap=row['start']-arrival
            if row['kind'] in {'train','airplane'}:waits.append(gap)
            else:openings.append(gap)
    idle_minutes=0
    traffic=[r for r in rows if r['kind'] in {'train','airplane'}]
    if len(traffic)>=2:
        from rules import clock
        for day in plan.get('itinerary',[]):
            offset=(day['day']-1)*1440
            lo=max(offset+540,traffic[0]['end'])
            hi=min(offset+1200,traffic[-1]['start'])
            occupied=[]
            for row in rows:
                if row['kind'] not in {'accommodation','train','airplane'}:
                    occupied.append((max(lo,row['start']),min(hi,row['end'])))
                cursor=row['start']
                for leg in reversed(row['activity'].get('transports',[])):
                    finish=(cursor//1440)*1440+clock(leg['end_time'])
                    if finish>cursor:finish-=1440
                    start=(finish//1440)*1440+clock(leg['start_time'])
                    if start>finish:start-=1440
                    if row is not traffic[0]:occupied.append((max(lo,start),min(hi,finish)))
                    cursor=start
            merged=[]
            for begin,end in sorted((a,b) for a,b in occupied if b>a):
                if merged and begin<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
                else:merged.append((begin,end))
            idle_minutes+=max(0,hi-lo)-sum(b-a for a,b in merged)
    ends=[]
    for day in plan.get('itinerary',[]):
        hotels=[a for a in day['activities'] if a['type']=='accommodation']
        if hotels:
            h,m=map(int,hotels[-1]['start_time'].split(':'))
            ends.append(max(0,1200-h*60-m))
    required=[o for o in audit.get('obligations',[]) if o['status']=='required']
    return dict(sightseeing_minutes=sightseeing,opening_wait_minutes=sum(openings),station_wait_minutes=sum(waits),daytime_unassigned_minutes=idle_minutes,early_hotel_minutes_before20=sum(ends),required_meals=len(required),missing_meals=sum(v['rule']=='missing_meal' for v in audit.get('violations',[])),meal_violations=sum(v['rule'] in {'missing_meal','invalid_meal_time','meal_overlaps_intercity','duplicate_meal'} for v in audit.get('violations',[])),date_pass=audit.get('date_pass',False),day_limit_pass=audit.get('day_limit_pass',False),attraction_hours_pass=audit.get('attraction_hours_pass',False))

def main():
    bundle=[];sections=[];overview=[]
    for entry in manifest['cases']:
        case=entry['case'];status=read(ROOT/'status'/f'{case}.json',dict(state='pending'))
        plan=read(ROOT/'results'/f'{case}.json',{})
        audit=status.get('new_rule_audit',{})
        official=status.get('evaluation',{})
        summary=dict(entry,state=status['state'],candidate_count=status.get('candidate_count',0),official_pass=bool(official.get('all_pass')),new_rule_pass=bool(audit.get('all_pass')),combined_pass=bool(status.get('combined_pass')),api_calls=status.get('api_calls',0),elapsed_seconds=status.get('elapsed_seconds'),metrics=metrics(plan,audit) if plan.get('itinerary') else None)
        bundle.append(dict(summary=summary,status=status,plan=plan))
        overview.append('<tr>'+''.join(f'<td>{e(value)}</td>' for value in (case,entry['group'],status['state'],summary['candidate_count'],summary['official_pass'],summary['new_rule_pass'],summary['combined_pass'],summary['api_calls']))+'</tr>')
        if plan.get('itinerary'):
            sections.append(f'<section class="case" id="{case}"><h2>{e(case)}</h2><p>原版评估：{summary["official_pass"]}；新增规则：{summary["new_rule_pass"]}；候选：{summary["candidate_count"]}/20</p>'+table.plan_tables(plan)+f'<details class="panel"><summary>绝对日期及三餐适用／豁免记录</summary><pre>{e(json.dumps(audit,ensure_ascii=False,indent=2))}</pre></details><details class="panel"><summary>原始输出JSON与运行状态</summary><pre>{e(json.dumps(dict(plan=plan,status=status),ensure_ascii=False,indent=2))}</pre></details></section>')
    groups=[]
    for group in manifest['groups']:
        subset=[b for b in bundle if b['summary']['group']==group]
        generated=[b['summary'] for b in subset if b['plan'].get('itinerary')]
        states=Counter(b['summary']['state'] for b in subset)
        means={key:statistics.mean(item['metrics'][key] for item in generated) if generated else None for key in ('sightseeing_minutes','opening_wait_minutes','station_wait_minutes','daytime_unassigned_minutes','early_hotel_minutes_before20','missing_meals','meal_violations','date_pass','day_limit_pass')}
        groups.append(dict(group=group,total=len(subset),generated=len(generated),official_pass=sum(b['summary']['official_pass'] for b in subset),new_rule_pass=sum(b['summary']['new_rule_pass'] for b in subset),combined_pass=sum(b['summary']['combined_pass'] for b in subset),reached20=sum(b['summary']['candidate_count']==20 for b in subset),states=dict(states),mean_metrics_over_generated_only=means))
    totals=Counter(b['summary']['state'] for b in bundle)
    summary=dict(updated_at=datetime.now(timezone.utc).isoformat(),total=len(bundle),states=dict(totals),groups=groups,metric_denominator='Only generated plans enter quality averages; all planned runs remain in success-rate denominator. Opening waits exclude travel; early hotel time measured until20:00; overnight sleep is not daytime idle.')
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ShortTrip · C组行程结果</title><style>'+base.CSS+'.score-table{table-layout:auto!important}.score-table td,.score-table th{width:auto!important}</style></head><body><main><h1>ShortTrip · C组行程结果</h1><p>原easy、human各五例，每例一次，串行运行，目标20候选，单例最多30分钟。本地Qwen3.5-4B Q8，16K上下文，关闭思考。包含灵活三餐顺序、结构化约束翻译与确定性模板、提前剪枝及原版独立评估。</p><details open><summary>分组统计及指标分母</summary><pre>'+e(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details><div class="scroll"><table class="score-table"><thead><tr>'+''.join('<th>'+s+'</th>' for s in ('案例','组别','状态','候选','原版通过','新规则通过','共同通过','API调用'))+'</tr></thead><tbody>'+''.join(overview)+'</tbody></table></div>'+''.join(sections)+'</main></body></html>'
    page=page.replace('13例×3次，共39次','10例各1次，共10次').replace('等待控制。','等待控制；景点仅08:00–21:00。')
    from worker import save
    save(ROOT/'summary.json',summary)
    save(ROOT/'all_results.json',dict(manifest=manifest,summary=summary,cases=bundle))
    temp=ROOT/'itineraries.html.tmp';temp.write_text(page,encoding='utf-8');temp.replace(ROOT/'itineraries.html')
    print(json.dumps(dict(total=len(bundle),states=dict(totals)),ensure_ascii=False))

if __name__=='__main__':main()
