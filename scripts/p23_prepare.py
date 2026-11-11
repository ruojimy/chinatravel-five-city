"""Freeze a 150-query participant sample and inventory all locally labelled tasks."""
import hashlib,json,random,sys
from collections import Counter,defaultdict
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p23_scaled_llm'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.env import get_env

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def main():
 assert not (OUT/'protocol.json').exists(),'Preserve existing protocol'
 env=get_env('zh');rng=random.Random(20261023);inventory={};selected={};private={}
 for split in ('easy','medium','human','competition_test','human1000'):
  paths=sorted((ROOT/'ChinaTravel/chinatravel/data'/split).glob('*.json'));qs=[read(p) for p in paths]
  inventory[split]={'files':len(qs),'with_hard_labels':sum(bool(q.get('hard_logic_py')) for q in qs),'unique_uids':len({q['uid'] for q in qs})}
  if split not in ('easy','medium','human'):continue
  groups=defaultdict(list)
  for q in qs:groups[(q['target_city'],q['days'])].append(q)
  for group in groups.values():rng.shuffle(group)
  sample=[]
  while len(sample)<50:
   for key in sorted(groups):
    if groups[key] and len(sample)<50:sample.append(groups[key].pop())
  selected[split]=[q['uid'] for q in sample]
  public=[]
  for q in sample:
   private[q['uid']]=q
   clean={k:q[k] for k in ('uid','start_city','target_city','days','people_number','nature_language')}
   city=q['target_city'];nl=q['nature_language'];catalog={}
   for kind,table,fields in [('attractions',env.attraction_table(city),('name','type','price','recommendmintime','opentime','endtime')),('restaurants',env.restaurant_table(city),('name','cuisine','price','opentime','endtime')),('hotels',env.accommodation_table(city),('name','featurehoteltype','price','numbed'))]:
    rows=json.loads(table.to_json(orient='records',force_ascii=False));exact=[r for r in rows if str(r['name']) in nl]
    attrfields=('type','cuisine','featurehoteltype')
    typed=[r for r in rows if any(isinstance(r.get(k),str) and r[k] and r[k] in nl for k in attrfields)]
    ordered=exact+typed+sorted(rows,key=lambda r:float(r.get('price') or 0))
    seen=set();kept=[]
    for r in ordered:
     if r['name'] not in seen:
      kept.append({k:r.get(k) for k in fields});seen.add(r['name'])
     if len(kept)>=16:break
    catalog[kind]=kept
   clean['retrieved_candidates']=catalog
   public.append(clean)
  write(OUT/'public'/split/'queries.json',public)
  write(OUT/'private'/split/'queries.json',sample)
 write(OUT/'private/all_participant_queries.json',private)
 write(OUT/'inventory.json',inventory)
 write(OUT/'selection.json',{'seed':20261023,'method':'round-robin city/day strata; seeded within-stratum shuffle; no outcome filtering','uids':selected})
 write(OUT/'public/intent_schema.json',{'required':['uid','reasoning','preferred_attractions','preferred_restaurants','hotel_names','mode_preference'],
  'optional':{'required_attractions':[],'required_restaurants':[],'attraction_types':[],'restaurant_types':[],'hotel_types':[],'forbidden_attractions':[],'forbidden_restaurants':[],'forbidden_hotels':[],'forbidden_attraction_types':[],'forbidden_restaurant_types':[],'budget':None,'hotel_budget':None,'restaurant_budget':None,'attraction_budget':None,'transport_budget':None,'rooms':None,'room_type':None,'attraction_count':None,'max_attractions_per_day':3,'day_attraction_counts':{},'outbound_mode':'any','return_mode':'any','outbound_after':None,'outbound_before':None,'return_after':None,'return_before':None},
  'contract':'One explicit intent per uid. Names/types must come from the public packet. mode_preference metro|taxi|walk. rooms and room_type are requested decisions, not invented hotel facts. Choose preferred names yourself from candidates; required names only when user explicitly requires them. No hidden DSL/checker/old plans. Scheduler fills numeric fields from the official frozen sandbox; failed choices remain failures.'})
 write(OUT/'protocol.json',{'at':datetime.now(timezone.utc).isoformat(),'participant_queries':150,'samples_per_split':50,'seed':20261023,
   'participant':'three fresh-context Codex subagents, 50 cases each; no model ranking','system':'LLM semantic/content choices plus deterministic sandbox scheduler',
   'official_gates':['schema','commonsense','hard DSL'],'no_oracle_fields_to_participant':True,
   'no_checker_feedback_before_first_output':True,'live_api_calls_in_official_benchmark':0,
   'controls':'all 604 legacy-labelled tasks plus 100 English phase2 labelled tasks; deterministic system only',
   'comparison':'paired default vs intent-guided compiler on the same 150 UIDs; content effects, not a pure retrieval ablation',
   'isolation':'fresh-context role/file boundary, not OS sandbox isolation','limits':['150/604 sample; not full LLM suite','phase2 control is English and reported separately','human1000 has no local hidden labels; not scored','Frozen benchmark validity does not imply real-world feasibility']})
 frozen=[p for p in OUT.rglob('*.json') if 'private' not in p.parts]+[ROOT/'scripts/p23_prepare.py']
 write(OUT/'private/freeze.json',{'files':{str(p.relative_to(ROOT)):digest(p) for p in frozen},'at':datetime.now(timezone.utc).isoformat()})
 print(json.dumps({'inventory':inventory,'participant_queries':150,'public_dirs':list(selected)},ensure_ascii=False))

if __name__=='__main__':main()
