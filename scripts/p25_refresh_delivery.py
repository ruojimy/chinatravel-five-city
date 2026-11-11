"""Refresh only the fixed delivery's weather and oriented routes; no key rotation."""
import copy,json,hashlib,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient
from shorttrip.retrieval_guard import evaluate
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=OUT/'real_refresh'/stamp
    folder.mkdir(parents=True,exist_ok=False)
    d=read(OUT/'DELIVERABLE.json');q=d['query'];p=copy.deepcopy(d['plan']);original=read(OUT/'real/corpus.json')['evidence'];client=LiveAmapClient(ROOT,budget=3)
    fresh={};weather=client.weather('430100',travel_date=q['dates'][0]);save(folder/'weather_raw.json',weather)
    w=copy.deepcopy(next(e for e in original if e['field']=='weather_forecast'))
    w.update(evidence_id='refresh:'+stamp+':weather',value=weather['value'],raw_text=weather['raw_text'],quote=weather['quote'],raw_sha256=weather['raw_sha256'],
        source_observed_at=weather['observed_at'],retrieved_at=weather['retrieved_at'],valid_until=(datetime.fromisoformat(weather['observed_at'])+timedelta(hours=1)).isoformat())
    fresh['p25:weather']=w
    for name in ('outbound','return'):
        prior=next(e for e in original if e['evidence_id']=='p25:'+name+':route_duration');c=prior['context']
        claims=client.transit(list(map(float,c['origin'].split(','))),list(map(float,c['destination'].split(','))),city1=c['city1'],city2=c['city2'],departure_at=c['departure_at'],mode=c['mode'])
        save(folder/(name+'_raw.json'),claims)
        for claim in claims:
            previous=next(e for e in original if e['evidence_id']=='p25:'+name+':'+claim['field']);e=copy.deepcopy(previous)
            e.update(evidence_id='refresh:'+stamp+':'+name+':'+claim['field'],value=claim['value'],raw_text=claim['raw_text'],quote=claim['quote'],raw_sha256=claim['raw_sha256'],
                source_observed_at=claim['observed_at'],retrieved_at=claim['retrieved_at'],valid_until=(datetime.fromisoformat(claim['observed_at'])+timedelta(minutes=15 if claim['field']=='route_duration' else 30)).isoformat())
            fresh[previous['evidence_id']]=e
    # IDs and quantities are updated only for the same fixed field/context.
    def replace(value):
        if isinstance(value,dict):
            if set(('value','status','evidence_ids'))<=set(value):
                for oldid in value['evidence_ids']:
                    if oldid in fresh:
                        e=fresh[oldid];factor=1
                        if e['field']=='route_fare' and value['value'] is not None and value['value']==next(x['value'] for x in original if x['evidence_id']==oldid)*q['people_number']:factor=q['people_number']
                        value['value']=e['value']*factor if isinstance(e['value'],(int,float)) else value['value']
            return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,str) and value in fresh:return fresh[value]['evidence_id']
        return value
    p=replace(p);evidence=[fresh.get(e['evidence_id'],e) for e in original];now=datetime.now(timezone.utc).isoformat()
    events=[{'request_id':'refresh-fixed-context','status':'returned','evidence':evidence,'reason':'Fresh delivery refresh, not another LLM run'}]
    result=evaluate(q,p,evidence,events,now=now)
    record={'at':now,'plan':p,'query':q,'assessment':result,'evidence':evidence,'api_calls':client.spent,'audit':client.audit,'base_delivery_sha256':hashlib.sha256((OUT/'DELIVERABLE.json').read_bytes()).hexdigest()}
    save(folder/'receipt.json',record)
    assert result['policy_accepted'] and result['safe'],result
    save(OUT/'DELIVERABLE_LATEST.json',{'receipt':str((folder/'receipt.json').relative_to(ROOT)),'at':now,'assessment':result,'api_calls':client.spent})
    print(json.dumps({'receipt':str(folder.relative_to(ROOT)),'accepted':result['policy_accepted'],'cost':result['budget']['known_projected_cost'],'api_calls':client.spent,'valid_until':[e.get('valid_until') for e in fresh.values()]},ensure_ascii=True))
if __name__=='__main__':main()
