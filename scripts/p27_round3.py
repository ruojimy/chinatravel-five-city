"""Last feedback packet: refresh is sourced to provider reporttime, not fetch time."""
import copy
from datetime import datetime,timedelta
from p27_responses import B,read,save,ev,gate
NOW=datetime.now().astimezone().isoformat()
for level in ['easy','hard','human']:
 p=read(B/'responses'/level/'round2.json');q=read(B/'private'/level/'evaluation_query_round2.json');city=q['city_sequence'][0]
 es=[copy.deepcopy(e) for e in p['evidence'] if e['field']!='weather_forecast'];w=read(B/'capture'/f'amap_{level}_weather_refresh.json');observed=w['observed_at']
 es.append(ev('estimate','weather:'+city,city,'weather_forecast',w['value'],w['raw_text'],w['source_url'],{'travel_date':'2026-10-24'},source_id='amap',source_observed_at=observed,valid_until=(datetime.fromisoformat(observed)+timedelta(hours=1)).isoformat(),retrieved_at=w['retrieved_at'],suffix='refresh',forecast_note='Daily forecast only. Newly fetched report still observed around18:34, not19:03; TTL never reset to download time.'))
 reqs={(r['target_id'],r['field']):r for r in q['requirements']}
 for e in es:e['eligibility']=gate(e,reqs[(e['target_id'],e['field'])],NOW)
 p.update(round=3,evaluated_at=NOW,evidence=es,remaining_feedback_rounds=0,next_action='Write final complete v2 plan participants/LEVEL/round3.json and decision_round3.json, each available clue use/reject/defer with explanation. No more network permitted. Keep unknowns. Conditional proposal is not a reservation or guaranteed execution.')
 p['notes']+=['Weather refresh succeeded and new evidence_id replaces expired old report. A fresh download is not a fresh observation.','No matching temporary-closure notice returned by finite targeted searches. Absence of search hits does not verify normal operation.','No recommended-duration authoritative measurement; durations/buffers are disclosed user/model planning decisions.','Preserve full canonical candidate names and exact endpoint IDs from variant_query.','Available eligibility is field permission, not a passing grade. Financial totals and schedule must be independently calculated.']
 save(B/'responses'/level/'round3.json',p)
print('Created final feedback packets')
