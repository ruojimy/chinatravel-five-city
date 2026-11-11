"""Prepare a source-backed P22 engineering trial. No participant call here."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/p22_adaptive_delivery'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.adaptive_delivery import prioritize_tasks, evidence_view, rank_candidates, stage_instruction, repair_anchors, revision_locks

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    assert not (OUT/'participant_input.json').exists(),'Preserve prepared trial'
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    protocol=read(ROOT/'results/p21_flash_fixed/public/protocol.json')
    old=ROOT/'results/p21_flash_fixed'
    write(OUT/'protected_previous.json',{'baseline':protocol['baseline'],'sha256':{str(p.relative_to(ROOT)):sha(p) for p in old.rglob('*') if p.is_file() and not p.name.endswith(('-wal','-shm'))}})
    db=sqlite3.connect((ROOT/protocol['baseline']['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
    records={}
    for rid in ['overture:bf20d3c4-aa38-4e2c-80c1-d74913a4cf3e','overture:c825107f-0509-424d-9668-d01e2fa48542','overture:dbff3d67-d928-4b8e-a90e-92a853af0c27','overture:fb0e92cc-1ae3-4384-95dc-3867fb161fb5','overture:64901913-1255-4d7b-89c4-135431c17a18']:
        row=db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()
        if row:records[rid]=json.loads(row[0])
    db.close()
    registry=read(ROOT/'data/travel_source_registry.json')
    registry['ylsy_operator']={'name':'湖南大学岳麓书院','allowed_hosts':['ylsy.hnu.edu.cn'],'authority':'primary_operator','supports':['price','opening_hours','inventory'],'independence_group':'hnu-ylsy'}
    claims=[]
    raw=read(OUT/'live/web_open_001.json')
    # Retain the raw tool packet and the literal source quote, without inventing a source clock or licence.
    for field,value,quote in [('price',40,'全价票：40元/人次'),('opening_hours',{'open':'07:50','close':'17:30'},'5月-10月：7:50-17:30'),('inventory',{'advance_days':4,'confirmed_available':False},'未预约谢绝入院参观')]:
        assert quote in raw
        claims.append({'claim_id':'p22:ylsy:'+field,'entity_id':'overture:dbff3d67-d928-4b8e-a90e-92a853af0c27','field':field,'value':value,
          'unit':'CNY' if field=='price' else None,'source_id':'ylsy_operator','source_url':'https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm',
          'raw_text':raw,'quote':quote,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'entity_verified':True,'extraction_verified':True,'semantic_reviewed':True,
          'binding_basis':'operator exact name and Amap exact POI plus same location category; reviewed here, no independent truth labels',
          'licence_status':'research_read_only_redistribution_unverified','observed_at':None,'source_updated_at':None,'source_published_at':None,'retrieved_at':stamp,
          'context':{'travel_date':'2026-10-24'},'fact_scope':'Published rule only. Page has no visible source time. No booked inventory or current price guarantee.'})
    weather=read(OUT/'live/amap_recovery_probe.json')['claim'];claims.append(weather)
    refs={}
    for name in ('outbound','return'):
        packet=read(OUT/f'live/amap_route_{name}.json');claims+=packet['claims']
        vals={c['field']:c for c in packet['claims']};c=vals['route_duration'];rawroute=json.loads(c['raw_text'])
        eligible=[]
        for route in rawroute['route']['transits']:
            lines=[l for s in route.get('segments',[]) for l in s.get('bus',{}).get('buslines',[])]
            if lines and all('地铁' in str(l.get('type','')) for l in lines):eligible.append(route)
        route=(eligible or rawroute['route']['transits'])[0]
        refs['route:'+name]={'source':'amap','departure_at':c['context']['departure_at'].replace('+00:00','Z'),
             'duration_minutes':c['value'],'fare_per_person_cny':vals['route_fare']['value'],
             'mode_requirement_met':c['mode_requirement_met'],'context':c['context'],
             'walking_meters':int(route.get('walking_distance',0)),
             'lines':[{'name':l['name'],'from':l['departure_stop']['name'],'to':l['arrival_stop']['name']} for s in route['segments'] for l in s.get('bus',{}).get('buslines',[])],
             'claim_ids':[x['claim_id'] for x in packet['claims']]}
        # Use explicit local departure, not a textual timezone replacement.
        refs['route:'+name]['departure_at']='2026-10-24T'+('13:00' if name=='outbound' else '16:00')+':00+08:00'
    views=[evidence_view(c,registry,now=stamp,context=c['context']) for c in claims]
    write(OUT/'claims.json',{'at':stamp,'claims':claims,'views':views,'base_catalogue_modified':False})
    entities={
      'overture:bf20d3c4-aa38-4e2c-80c1-d74913a4cf3e':{'name':'湖南博物馆（湖南博物院）','themes':['history'],'visit_group_id':'hunan-museum','branch_verified':True,'amap_id':'B02DB00018'},
      'overture:dbff3d67-d928-4b8e-a90e-92a853af0c27':{'name':'岳麓书院','themes':['history'],'visit_group_id':'yuelu-complex','branch_verified':True,'amap_id':'B02DB05TQH'},
      'overture:fb0e92cc-1ae3-4384-95dc-3867fb161fb5':{'name':'中国书院博物馆','themes':['history'],'visit_group_id':'yuelu-complex','branch_verified':True},
      'overture:64901913-1255-4d7b-89c4-135431c17a18':{'name':'长沙简牍博物馆','themes':['history'],'visit_group_id':'bamboo-slips','branch_verified':False},
      'amap:B0LRX72TV5':{'name':'蒸浏记·浏阳蒸菜(省博物馆店)','themes':[],'branch_verified':True,'parent':'hunan-museum','origin':'new_session_discovery','amap_id':'B0LRX72TV5'},
    }
    # Grouping is source-reviewed, never inferred from distance alone.
    entity_notes={'yuelu_group_source':'https://ylsy.hnu.edu.cn/wbly/wbsy.htm','museum_alias_note':'Amap exact POI at 东风路50号 vs government address; original dataset coordinates were not used for routing.'}
    refs.update({v['claim_id']:v for v in views})
    refs.update({
      'poi:museum':{'file':'live/amap_poi_01.json','name':'湖南省博物馆','opening_rule':'09:00–17:00 Tue–Sun, except listed adjustments','fact_status':'map_listing_reference'},
      'poi:restaurant':{'file':'live/amap_poi_03.json','name':entities['amap:B0LRX72TV5']['name'],'mean_spend_per_person_cny':37,'open_time':'09:30–16:30 Tue–Sun','fact_status':'listing_reference_not_menu_quote'},
      'decision:free_basic_only':{'type':'spending_cap_decision','value':0,'note':'Only accept free basic-exhibition booking; no paid special exhibition. This is an action choice, not a certified free-price claim.'},
      'decision:lunch_cap':{'type':'spending_cap_decision','value':100,'note':'Two-person spending cap, require seller to confirm no chili/chili oil. Not a menu quote.'},
      'decision:transit_cap':{'type':'spending_cap_decision','value':40},
      'decision:reserve':{'type':'spending_cap_decision','value':100},
      'source:booking':{'url':'https://hunan.voc.com.cn/news/202507/30107492.html','representation':'fulltext of museum statement republished by news outlet','source_published_at':'2025-07-31T23:45:00+08:00','scope':'Official booking channels only, not current inventory'},
      'source:diet':{'url':'https://www.icswb.com/default.php?a=detail&mod=newspaper_article&newspaper_article_id=1816257','representation':'search extracted article; opened page did not expose body','scope':'Historical candidate clue only, not current dish certification'},
    })
    request={**read(ROOT/'results/p21_flash_fixed/public/queries.json')[0],'min_attractions':2,'theme':'history','budget_cny':500,'route_buffer_minutes':10}
    tasks=[]
    for rid,item in entities.items():
        if item.get('themes'):
            tasks.append({'provider':'web','kind':'operator','entity_id':rid,'context':{'travel_date':request['date']},'covers':[rid+':price',rid+':hours',rid+':reservation'],'field_weights':{rid+':price':4,rid+':hours':4,rid+':reservation':3},'relevance':1.5 if item.get('branch_verified') else .5})
    for day in ('2026-10-24','2026-10-25'):
        tasks.append({'provider':'amap','kind':'weather','context':{'city':'长沙','adcode':'430100','travel_date':day},'covers':['weather:'+day],'field_weights':{'weather:'+day:2}})
    for name in ('outbound','return'):
        tasks.append({'provider':'amap','kind':'route','context':refs['route:'+name]['context'],'covers':['route:'+name+':duration','route:'+name+':fare'],'field_weights':{'route:'+name+':duration':6,'route:'+name+':fare':4}})
    queue=prioritize_tasks(tasks,budget=8,paused=['amap'],recovered=['amap'])
    write(OUT/'retrieval_queue.json',queue)
    ranked=rank_candidates([dict(v,entity_id=k) for k,v in entities.items() if v.get('themes')],requested_theme='history',evidence=views)
    write(OUT/'candidate_ranking.json',{'ranked':ranked,'entities':entities,'grouping_evidence':entity_notes,'selection_note':'Source-directed narrowing and one new in-museum restaurant; not an exhaustive city search.'})
    replay=[]
    for q in read(ROOT/'results/p21_flash_fixed/public/queries.json'):
        prior=read(old/'plans'/q['case_id']/'dynamic_first.json');fixed,edits=repair_anchors(prior,q)
        write(OUT/'offline_repaired'/q['case_id']/'proposal.json',fixed)
        replay.append({'case_id':q['case_id'],'decision_edits':edits,'actual_revision_locks':revision_locks(prior),'fresh_evidence_added':False})
    write(OUT/'offline_repair_audit.json',{'cases':replay,'scope':'Decision-only offline replay, not a new LLM or live-evidence run.'})
    inp={'request':request,'stage_instruction':stage_instruction('dynamic_first'),'entities':entities,'ranked_attractions':ranked,'evidence':views,'references':refs,
      'constraints':[
       'Output one JSON object with people_number,date,schedule,budget,before_departure,reasoning. schedule items: type,start_time,end_time,position,entity_id(optional),evidence_refs; travel adds route_ref.',
       'Use museum and Yuelu as two separate history sites; museum on-site lunch is newly discovered via Amap. Do not count the academy museum as a separate visit from Yuelu.',
       'Do not use memory facts. Plan must start exactly 09:00 at 湖南博物院正门 and return there by 18:00.',
       'Two API routes are bound to departure 13:00 and 16:00 on 2026-10-24. Give each travel at least ceil(API minutes)+10 minutes. Preserve route_ref route:outbound and route:return.',
       'Museum 09:00-12:00, one lunch 12:00-12:45, allow 15 minutes to reach exit. Afternoon Yuelu fits 14:00-16:00 and its published rule.',
       'Numeric source values: Yuelu posted 40/person, meal Amap historical/listing mean37/person, transit3/person each direction. Meal is not a live menu quote.',
       'Museum select FREE BASIC EXHIBITION ONLY; use a 0 spending-cap DECISION with decision:free_basic_only, do not claim certified free admission or inventory.',
       'budget items have amount_cny,basis,evidence_refs,label. basis only published_reference|provider_estimate|spending_cap_decision. budget also projection_cny,confirmed_total_cny:null,conditional:true.',
       'Budget conservative envelope: museum0 decision + Yuelu80 published reference + lunch cap100 + transit cap40 + reserve100 =320, within500. Display API meal/route projections separately in reasoning.',
       'before_departure must require official museum morning booking, Yuelu afternoon booking/payment check, current meal no-chili confirmation, recheck routes/weather and price caps; if any fails, replan instead of declaring satisfied.',
       'No external actions or booking. Unknown source times remain unknown. Do not emit official-native plan with fabricated 0 fields.'
      ]}
    write(OUT/'participant_input.json',inp)
    write(OUT/'protocol.json',{'at':stamp,'mode':'engineering_optimization_with_one_live_case_and_four_offline_replays','participant_model':'deepseek-flash','temperature':0,'live_case':'D01','amap_budget':8,'algorithm':'adaptive_delivery.py','not_preregistered':True,'claims_policy':'Legacy hard fact gate unchanged; reference/cost projection is explicitly conditional. No official score inflation.','baseline':protocol['baseline'],'freeze':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'src/shorttrip/adaptive_delivery.py',ROOT/'tests/test_adaptive_delivery.py',OUT/'participant_input.json']}})
    print(json.dumps({'claims':len(claims),'views':{x:sum(v['evidence_use']==x for v in views) for x in ['provider_estimate','published_reference','certified_fact','quarantined']},'queue':len(queue['selected']),'participant_input':str(OUT/'participant_input.json')},ensure_ascii=False))

if __name__=='__main__':main()
