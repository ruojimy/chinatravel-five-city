"""Curate auditable evidence packets for the three blinded P27 participants."""
import json,hashlib,sys
from pathlib import Path
from datetime import datetime,timedelta
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from shorttrip.retrieval_guard import gate
B=R/'results/p27_focused_deep_retrieval'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():raise FileExistsError(p)
 p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def source(name):return read(B/'capture'/name)
NOW=datetime.now().astimezone().isoformat()
def ev(level,target,city,field,value,raw,url,context=None,**kw):
 e=dict(evidence_id=f'p27:{city}:{field}:{kw.pop("suffix","r1")}',target_id=target,city=city,field=field,value=value,level=level,source_id='operator',source_url=url,raw_text=raw,quote=raw[:100],raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),context=context or {},retrieved_at=NOW,source_observed_at=None,valid_until=None)
 e.update(kw);return e
def main():
 for level in ['easy','hard','human']:
  q=read(B/'private'/level/'query.json');city=q['city_sequence'][0];target=q['candidates'][0]['entity_id'];context={'travel_date':q['dates'][0]};es=[]
  cap=source(f'amap_{level}_target.json');poi=cap['raw']['pois'][0];raw=json.dumps(cap['raw'],ensure_ascii=False)
  e=ev('verified',target,city,'identity',{'provider_id':poi['id'],'name':poi['name'],'city':poi['cityname'],'address':poi['address'],'coordinates':poi['location'],'coordinate_system':'GCJ02'},raw,cap['meta']['endpoint'],source_id='amap',identity_binding={'provider_id':poi['id'],'expected_name':poi['name']},retrieved_at=cap['meta']['retrieved_at'])
  e['binding_review']='Exact city and canonical Chinese name; target has bilingual alias only for Xiamen. Operator address/tel cross-check; provider identity is not independent survey proof.';es.append(e)
  if level=='easy':
   raw=source('web_hainan_about.json');url='https://www.hainanmuseum.org/hnbwgcms/node/169';hours={'open':'09:00','close':'17:00','last_admission':'16:30','closed_weekday':'Monday'}
  elif level=='hard':
   raw=source('web_xiamen_ticket.json');url='https://www.xiamenbg.cn/Home/yyzn3';hours=None
   es.append(ev('reference',target,city,'price',30,raw,url,context,price_scope='adult_general_per_person_CNY',extraction_note='Full-price admission only; optional vehicle/photography excluded; no concession eligibility assumed.'))
  else:
   raw=source('web_round2.json').split('--------------------------------------------------------------------------------')[0];url='https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm';hours={'open':'07:50','close':'18:00','last_admission':'17:40','last_ticket':'17:30','season':'May-October'}
   es.append(ev('reference',target,city,'price',40,raw,url,context,price_scope='adult_general_per_person_CNY'))
  if hours:es.append(ev('reference',target,city,'opening_hours',hours,raw,url,context,extraction_note='Published operating rule, no fact-update timestamp; target-date temporary closure not guaranteed.'))
  w=source(f'amap_{level}_weather.json');observed=w['observed_at'];deadline=(datetime.fromisoformat(observed)+timedelta(hours=1)).isoformat()
  es.append(ev('estimate','weather:'+city,city,'weather_forecast',w['value'],w['raw_text'],w['source_url'],context,source_id='amap',source_observed_at=observed,valid_until=deadline,retrieved_at=w['retrieved_at'],forecast_note='Daily forecast, no hourly rain/heat guarantee. TTL based on reporttime, never capture time.'))
  reqs={ (r['target_id'],r['field']):r for r in q['requirements']}
  for e in es:
   r=reqs[(e['target_id'],e['field'])].copy()
   if e['field'] in ('price','opening_hours'):r['accepted_levels']=['verified','reference']
   e['eligibility']=gate(e,r,NOW)
  notes=['No recommendation-duration source returned; candidate duration is an unverified prior, not measured fact.','Use context.travel_date and weather:'+city+'; root normalized the round0 request aliases and date key, recorded as orchestration assistance.','Published reference prices/hours permit a conditional proposal only; no inventory or booking confirmation.']
  if level=='easy':notes+=['Price remains unknown: failed source URLs are paused. The free-visit exception clause does not independently establish the exact requested general ticket amount.','Reject summer-only July11-Aug30 government hours for October24.','Real-name ID admission and daily cap are published; no claim a place is reserved.']
  else:notes+=['Original origin remains unspecified. Keep the original route unresolved and explicitly request a precise origin. Researcher clarification will be a separate variant after this round.']
  if level=='human':notes+=['Real-name advance booking is mandatory, possible four days including target date; no reservation has been made. Retain this prerequisite explicitly.','Provider 17:30 is ticket-sales stop; operator distinguishes 17:40 last entry and18:00 close. Do not merge these clocks.']
  save(B/'responses'/level/'round1.json',{'round':1,'evaluated_at':NOW,'variant':'original unchanged','evidence':es,'notes':notes,'stopped_urls':['https://www.hainanmuseum.org/','https://www.hainanmuseum.org/hnbwgcms/info/3591'],'next_action':'Revise full plan, retain unknowns, output decision_round1.json and further retrieval requests. No private/capture access.'})
 print('Created three round1 packets')
if __name__=='__main__':main()
