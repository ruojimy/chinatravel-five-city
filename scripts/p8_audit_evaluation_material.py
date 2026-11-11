"""Audit only public blind-review material; no scores, private mapping or APIs.

These are observable schedule facts, not preference labels or a new utility model.
Unallocated time may be intentional free time; do not call it actual waiting.
"""
from pathlib import Path
import csv,json,re,hashlib,html

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'datasets/human_preference/packets.csv'
OUT=ROOT/'results/p8_evaluation_redesign'
EVENT=re.compile(r'(\d{2}:\d{2})[–—-](\d{2}:\d{2})(.*?)(?=；\d{2}:\d{2}| / 第|$)')

def minute(t):return int(t[:2])*60+int(t[3:])
def duration(n):return f'{n//60}小时{n%60:02d}分' if n>=60 else f'{n}分'

def facts(text,cost,transit):
    events=[]
    for m in EVENT.finditer(text):
        start,end,body=m.groups()
        legs=[int(x) for x in re.findall(r'(?:walk|metro|taxi|bus) (\d+)分钟',body)]
        events.append(dict(start=start,end=end,body=body,preceding_transport_minutes=sum(legs)))
    if not events:raise ValueError('No displayed activity times parsed')
    if any(minute(e['end'])<minute(e['start']) for e in events):
        raise ValueError('Overnight activity requires a day-aware parser; do not infer')
    gaps=[]
    for a,b in zip(events,events[1:]):
        delta=minute(b['start'])-minute(a['end'])-b['preceding_transport_minutes']
        gaps.append(dict(after=a['end'],before=b['start'],given_transfer_minutes=b['preceding_transport_minutes'],
                         unallocated_minutes=max(0,delta),displayed_transfer_shortfall_minutes=max(0,-delta)))
    visits=[e for e in events if e['body'].lstrip().startswith('景点：')]
    meals=[e for e in events if e['body'].lstrip().startswith(('早餐：','午餐：','晚餐：'))]
    return dict(cost_yuan=float(cost),transit_minutes=float(transit),
                walk_minutes=sum(map(int,re.findall(r'walk (\d+)分钟',text))),
                attraction_count=len(visits),visit_minutes=sum(minute(e['end'])-minute(e['start']) for e in visits),
                meals=[e['body'].split(' [交通',1)[0] for e in meals],
                first_departure=events[0]['start'],last_arrival=events[-1]['end'],
                largest_unallocated_minutes=max((g['unallocated_minutes'] for g in gaps),default=0),
                schedule_transfer_shortfall=any(g['displayed_transfer_shortfall_minutes'] for g in gaps),
                events=events,gaps=gaps,
                boundary='Given displayed facts only; no live price/route/opening validation; meal presence is not nutritional adequacy.')

def calibrate():
    text='第1天：08:00–09:00 甲→乙（train，10 元/人）；10:00–11:00 景点：公园 [交通 车站→公园 walk 15分钟]；13:30–14:00 午餐：餐厅 [交通 公园→餐厅 metro 30分钟]'
    f=facts(text,30,45)
    assert f['walk_minutes']==15 and f['attraction_count']==1 and f['visit_minutes']==60
    assert len(f['meals'])==1 and f['largest_unallocated_minutes']==120
    assert not f['schedule_transfer_shortfall']
    assert facts(text.replace('10:00–11:00','09:10–11:00'),30,45)['schedule_transfer_shortfall']
    try:facts('23:00–01:00 跨夜',1,0)
    except ValueError:pass
    else:raise AssertionError('Overnight must not silently become a negative duration')
    return {'known_gap_after_transfer':True,'meal_and_visit_parsing':True,'transfer_shortfall_detected':True,'overnight_refuses_inference':True}

def main():
    calibration=calibrate()
    source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    with SOURCE.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==30 and all(float(r['days'])==1 for r in rows),'This version audits the provided one-day material only'
    unique={};pairs=[]
    for row in rows:
        sides={}
        for side in ('A','B'):
            text=row[side+'_text'];key=(row['query_uid'],text,float(row[side+'_cost']),float(row[side+'_transit_min']))
            if key not in unique:
                unique[key]=dict(public_id=f'P{len(unique)+1:03d}',city=row['city'],query_uid=row['query_uid'],
                                 original_request=row['request'],text=text,
                                 facts=facts(text,row[side+'_cost'],row[side+'_transit_min']))
            sides[side]=unique[key]
        pairs.append(dict(pair_id=row['pair_id'],city=row['city'],request=row['request'],
                          A=sides['A']['public_id'],B=sides['B']['public_id'],
                          reference_choice=None,reason='Original request does not specify the trade-offs needed for a unique subjective preference label.'))
    plans=list(unique.values());OUT.mkdir(parents=True,exist_ok=True)
    result=dict(source=str(SOURCE.relative_to(ROOT)),source_sha256=source_hash,
                pairs=len(pairs),unique_visible_plans=len(plans),
                plans_with_unallocated_gap_at_least_180_minutes=sum(p['facts']['largest_unallocated_minutes']>=180 for p in plans),
                unallocated_gap_range_minutes=[min(p['facts']['largest_unallocated_minutes'] for p in plans),max(p['facts']['largest_unallocated_minutes'] for p in plans)],
                meaning='Unexplained schedule allowance after subtracting displayed transfer durations; not proved waiting, infeasibility or dissatisfaction.',
                private_mapping_read=False,model_scores_read=False,preference_labels_created=0,calibration=calibration,
                plans=plans,pair_cards=pairs)
    (OUT/'material_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    byid={p['public_id']:p for p in plans}
    md=['# 成对评价差异卡（无标准偏好答案）','','只比较给定事实；长空档可能是自由活动，不能直接判错。陌生景点保留可展开原文，不用猜其品质。','']
    cards=[]
    for pair in pairs:
        a,b=byid[pair['A']],byid[pair['B']]
        body=[]
        metrics=[('总费用','cost_yuan','元'),('市内交通','transit_minutes','分钟'),('给定步行','walk_minutes','分钟'),('景点数量','attraction_count','处'),('景点游览时长','visit_minutes','分钟'),('出发时间','first_departure',''),('返抵时间','last_arrival',''),('最大未说明余量','largest_unallocated_minutes','分钟')]
        md += [f'## {pair["pair_id"]} · {pair["city"]}',pair['request'],'','|给定指标|A|B|','|---|---|---|']
        for label,key,unit in metrics:
            av,bv=a['facts'][key],b['facts'][key]
            md.append(f'|{label}|{av}{unit}|{bv}{unit}|')
            body.append(f'<tr><th>{label}</th><td>{html.escape(str(av))}{unit}</td><td>{html.escape(str(bv))}{unit}</td></tr>')
        meal_a='；'.join(a['facts']['meals']) or '未列出';meal_b='；'.join(b['facts']['meals']) or '未列出'
        md += [f'|餐饮条目|{meal_a}|{meal_b}|','','还需要知道：对景点类型、游玩节奏、步行、餐饮和大段自由活动的偏好。未补充时可以无法判断，不预填A/B。','']
        cards.append(f'<section><h2>{html.escape(pair["pair_id"])}</h2><p>{html.escape(pair["request"])}</p><table><tr><th>给定指标</th><th>A</th><th>B</th></tr>{"".join(body)}<tr><th>餐饮条目</th><td>{html.escape(meal_a)}</td><td>{html.escape(meal_b)}</td></tr></table><p class="note">偏好参考答案：未定义。无需猜测陌生景点的质量。最大未说明余量已扣除材料列出的交通，可作为自由活动，不能直接判错。</p><details><summary>查看A原文</summary><p>{html.escape(a["text"])}</p></details><details><summary>查看B原文</summary><p>{html.escape(b["text"])}</p></details></section>')
    (OUT/'pair_cards.md').write_text('\n'.join(md),encoding='utf-8')
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>行程评价差异卡</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 20px;color:#18332c;background:#f5f8f6}section{padding:20px;margin:24px 0;background:white;border:1px solid #dbe5df;border-radius:12px}h2{font-size:18px;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #dbe5df;text-align:left}th{width:25%;background:#eef5f0}.note{color:#596b61}details p{white-space:pre-wrap}summary{cursor:pointer}</style><h1>先看差异，再谈偏好</h1><p>30对行程已压缩为可观察事实。没有读取模型分数或来源，也没有预填“标准答案”。</p><p>你只需表达自己更在乎什么：紧凑还是悠闲、愿意走多久、预算内省钱还是多体验、景点类型，以及大段自由时间是否可接受。无需替陌生餐厅和景点打分。</p>'''+''.join(cards)+'</html>'
    (OUT/'pair_cards.html').write_text(document,encoding='utf-8')
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash,'Source must remain unchanged'
    print(json.dumps({k:result[k] for k in ('pairs','unique_visible_plans','plans_with_unallocated_gap_at_least_180_minutes','unallocated_gap_range_minutes','preference_labels_created','calibration')},ensure_ascii=False))

if __name__=='__main__':main()
