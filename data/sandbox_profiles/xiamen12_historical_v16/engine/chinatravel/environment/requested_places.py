"""Visible destination requirements, independent of frozen private DSL.

The small city vocabulary describes areas, not benchmark question IDs. A
matched name is an itinerary intention; it is not evidence of actual travel.
"""
import csv,os,re
from functools import lru_cache
from pathlib import Path

VOCAB={
 '厦门':[
  {'key':'鼓浪屿','mentions':['鼓浪屿'],'aliases':['鼓浪屿'],'kinds':['attraction'],'ferry_required':True},
  {'key':'植物园','mentions':['植物园'],'aliases':['厦门园林植物园','厦门植物园'],'kinds':['attraction']},
  {'key':'集美学村','mentions':['集美学村'],'aliases':['集美学村'],'kinds':['attraction']},
  {'key':'沙坡尾','mentions':['沙坡尾'],'aliases':['沙坡尾'],'kinds':['attraction']},
  {'key':'环岛路','mentions':['环岛路'],'aliases':['环岛路'],'kinds':['attraction']},
  {'key':'中山路','mentions':['中山路'],'aliases':['中山路'],'kinds':['attraction','breakfast','lunch','dinner']},
 ]}
NEGATIVE=re.compile(r'(?:不想去|不想逛|不去|不要去|避开|不安排|不考虑|无需去|不前往)\s*$')
CUE=re.compile(r'(?:想去|必去|一定去|希望去|希望到|去|前往|参观|游览|逛|到访|打卡|安排|想看|指定|必须)')
AFTER_CUE=re.compile(r'^[^，。；]{0,3}(?:是必去|必去|希望|必须|一定|要去|想去|安排)')
SLUGS={'厦门':'xiamen','西安':'xian','北京':'beijing','上海':'shanghai','杭州':'hangzhou',
       '南京':'nanjing','苏州':'suzhou','武汉':'wuhan','成都':'chengdu','重庆':'chongqing',
       '广州':'guangzhou','深圳':'shenzhen'}
@lru_cache(maxsize=32)
def catalog_names(root,city):
    slug=SLUGS.get(city)
    if not root or not slug:return ()
    path=Path(root)/'attractions'/slug/'attractions.csv'
    if not path.is_file():return ()
    with path.open(encoding='utf-8-sig',newline='') as f:
        return tuple(sorted({r.get('name','') for r in csv.DictReader(f) if len(r.get('name',''))>=4},key=len,reverse=True))
def requirements(query):
    text=str(query.get('nature_language') or '');out=[];spans=[]
    for spec in VOCAB.get(query.get('target_city'),[]):
        hits=[(text.find(w),w) for w in spec['mentions'] if w in text]
        if not hits:continue
        index,mention=min(hits)
        before=text[max(0,index-8):index];after=text[index+len(mention):index+len(mention)+12]
        if NEGATIVE.search(before) or not (CUE.search(before) or AFTER_CUE.match(after)):continue
        out.append(dict(spec))
        spans.append((index,index+len(mention)))
    # General exact-name support for any catalogue city; only explicit visit
    # language is promoted. Overlapping aliases prefer the longest match.
    for name in catalog_names(os.environ.get('CHINATRAVEL_DATABASE_ROOT'),query.get('target_city')):
        start=text.find(name)
        if start<0 or any(start < b and start+len(name)>a for a,b in spans):continue
        before=text[max(0,start-8):start];after=text[start+len(name):start+len(name)+8]
        if NEGATIVE.search(before) or not (CUE.search(before) or re.match(r'[^，。；]{0,3}(?:必去|一定|要去)',after)):continue
        out.append({'key':name,'mentions':[name],'aliases':[name],'kinds':['attraction']})
        spans.append((start,start+len(name)))
    return out
def matches(spec,kind,name):
    return kind in spec['kinds'] and isinstance(name,str) and any(a in name for a in spec['aliases'])
def evaluate(query,plan):
    req=requirements(query);results=[]
    activities=[a for day in (plan.get('itinerary') or []) if isinstance(day,dict)
                  for a in day.get('activities',[]) if isinstance(a,dict)] if isinstance(plan,dict) else []
    for item in req:
        positions=[a.get('position') for a in activities if matches(item,a.get('type'),a.get('position'))]
        state='pass' if positions else 'fail'
        reason='named activity found' if positions else 'requested named area absent from activities'
        if positions and item.get('ferry_required'):
            state='unknown';reason='island visit named, but this frozen schema cannot verify a ferry connection'
        results.append({'target':item['key'],'state':state,'matched_positions':positions,'reason':reason})
    state='fail' if any(x['state']=='fail' for x in results) else 'unknown' if any(x['state']=='unknown' for x in results) else 'pass'
    return {'state':state,'items':results,'boundary':'Name/alias match is not proof of opening, geographic identity, ferry or real-world access.'}
