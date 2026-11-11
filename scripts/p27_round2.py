"""Expose an explicitly researcher-clarified origin variant; preserve original."""
import copy,json,sys
from datetime import datetime,timedelta
from pathlib import Path
from p27_responses import B,read,save,ev
sys.path.insert(0,str(B.parents[1]/'src'))
from shorttrip.retrieval_guard import gate
NOW=datetime.now().astimezone().isoformat()
def main():
 for level in ['easy','hard','human']:
  base=read(B/'responses'/level/'round1.json');es=copy.deepcopy(base['evidence']);q=read(B/'private'/level/'query.json');city=q['city_sequence'][0];target=q['candidates'][0]['entity_id'];notes=[]
  for r in q['requirements']:
   if r['field'] in ('price','opening_hours'):r['accepted_levels']=['verified','reference']
  q['required_entities']=[[city,target]]
  if level!='easy':
   q['uid']+='-clarified';q['budget_cny']=300 if level=='hard' else 200;q['route_buffer_minutes']=10
   points=read(B/'private'/level/('verified_points_west.json' if level=='hard' else 'verified_points.json'))
   origin='amap:'+points['origin']['provider_id'];origin_name='厦门站南广场' if level=='hard' else '长沙火车站(地铁站)'
   q['candidates'].append({'entity_id':origin,'name':origin_name,'city':city,'kind':'anchor','data':{},'dataset':'researcher_clarification'})
   q['requirements']=[r for r in q['requirements'] if r['field'] not in ('route_duration','route_fare')]
   q['requirements'].append({'target_id':origin,'city':city,'field':'identity','context':{}})
   cap=read(B/'capture'/f'amap_{level}_origin.json');poi=next(p for p in cap['raw']['pois'] if p['id']==points['origin']['provider_id']);raw=json.dumps(cap['raw'],ensure_ascii=False)
   es.append(ev('verified',origin,city,'identity',{'provider_id':poi['id'],'name':poi['name'],'city':poi['cityname'],'coordinates':poi['location'],'coordinate_system':'GCJ02'},raw,cap['meta']['endpoint'],source_id='amap',identity_binding={'provider_id':poi['id'],'expected_name':poi['name']},suffix='origin',retrieved_at=cap['meta']['retrieved_at']))
   for direction,time in [('outbound','0900' if level=='hard' else '1300'),('return','1300' if level=='hard' else '1600')]:
    f=f'amap_{level}_{direction}_{time}'+('_west' if level=='hard' else '')+'.json'
    src,dst=(origin,target) if direction=='outbound' else (target,origin)
    for claim in read(B/'capture'/f):
     e=copy.deepcopy(claim);e.update(evidence_id=f'p27:{city}:{direction}:{e["field"]}',target_id='route:'+src+'>'+dst,city=city,level='estimate',source_observed_at=claim['observed_at'],valid_until=(datetime.fromisoformat(claim['observed_at'])+timedelta(minutes=15)).isoformat())
     if e['field']=='route_fare':e['unit']='CNY/person';e['normalization']='Provider transit_fee is per-person fare; group cost must multiply by number of people, not added twice.'
     e['context']['departure_at']=datetime.fromisoformat(e['context']['departure_at']).astimezone(datetime.fromisoformat('2026-10-24T00:00:00+08:00').tzinfo).isoformat()
     q['requirements'].append({k:e[k] for k in ('target_id','city','field','context')});es.append(e)
   q['requirements'].append({'target_id':target,'city':city,'field':'inventory','context':{'travel_date':'2026-10-24'},'prerequisite_only':True})
   q['nature_language']+='\n【研究者补充起点的独立变体，并非原题被自动解决】'+('09:00从厦门站南广场出发，经地铁和步行到植物园西门售票处，13:00从同处返程，18:00前回到起点。游览时间据天气自行安排。' if level=='hard' else '13:00从长沙火车站(地铁站)出发，到岳麓书院，14:00—16:00为可调整的拟议参观窗口，16:00从同一入口返程，18:00前回到起点。')+'两人普通成人票，无优惠资格假设。把往返交通、参考票价、预约未确认和预算一并说明。'
   notes+=['Researcher supplied origin and departure/return times; this is a separately scored variant, never an original-task solve.','All route times include provider walking legs. Add >=10min decision buffer; no guarantee a particular train operates tomorrow.','Return route is independently queried; do not reuse outbound fare/time as proof of reverse route.']
   if level=='hard':notes+=['South-side requests returned a bus fallback, mode_requirement_met=false, entity_verified=false. Rejected; never use1CNY as metro fare.','After model shortened visit for32C heat, root queried west ticket-office endpoint using fresh exact ID/name/parent. New metro-compatible routes returned.','Opening hours remain unresolved: old paused official hours URL was not reopened; official homepage and OTA detail attempts failed. Search-index seasonal text remains discovery, not opened-page evidence.']
   else:notes+=['Mandatory real-name reservation is not confirmed; no inventory adapter/authorization to book. Keep conditional, never complete.']
  else:notes+=['No new exact price proof returned. Search results suggest free admission but failed original page cannot be promoted to verified general price. Keep price unknown.']
  reqs={(r['target_id'],r['field']):r for r in q['requirements']}
  for e in es:e['eligibility']=gate(e,reqs[(e['target_id'],e['field'])],NOW)
  save(B/'private'/level/'evaluation_query_round2.json',q)
  public={k:q[k] for k in ('uid','nature_language','people_number','city_sequence','dates','candidates')}
  save(B/'responses'/level/'round2.json',{'round':2,'evaluated_at':NOW,'variant_query':public,'route_points':points if level!='easy' else None,'evidence':es,'notes':notes,'previous_notes':base['notes'],'remaining_feedback_rounds':1,'next_action':'Write full participants/LEVEL/round2.json and decision_round2.json. Weather may now be expired; final-round provider refresh will be attempted once.'})
 print('Created three round2 packets and separate private evaluation queries')
if __name__=='__main__':main()
