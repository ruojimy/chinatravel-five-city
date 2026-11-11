"""Incremental P27 Amap capture with a persisted 20-call circuit-breaker ledger."""
import argparse,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
OUT=ROOT/'results/p27_focused_deep_retrieval'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['base','origins','details','west_entry','refresh_weather','routes'],required=True);ap.add_argument('--level',choices=['hard','human']);ap.add_argument('--departure',default='09:00');ap.add_argument('--return-time',default='14:30');ap.add_argument('--route-version',default='');a=ap.parse_args()
    lp=OUT/'capture/amap_ledger.json';ledger=read(lp) if lp.exists() else {'max_calls':20,'spent':0,'stopped':False,'calls':[]}
    if ledger['stopped']:raise SystemExit('Provider already stopped; do not retry')
    client=LiveAmapClient(ROOT,budget=20-ledger['spent'])
    def call(label,level,fn):
        fp=OUT/'capture'/('amap_'+label+'.json')
        if fp.exists():raise FileExistsError('Preserve '+str(fp))
        before=client.spent
        try:
            result=fn();save(fp,result)
            status='ok';error=None
        except Exception as exc:
            result=None;status='failed';error=str(exc)
            save(fp,{'error':error,'no_retry':True})
            if client.stopped:ledger['stopped']=True
        spent=client.spent-before;ledger['spent']+=spent
        ledger['calls'].append({'label':label,'level':level,'actual_http_attempts':spent,'status':status,'error':error,'at':datetime.now(timezone.utc).isoformat(),'audit':client.audit[-1] if spent else None})
        save(lp,ledger)
        if status!='ok':raise SystemExit('Stopped task: '+str(error))
        return result
    cities={'easy':('海口','460100'),'hard':('厦门','350200'),'human':('长沙','430100')}
    if a.mode=='base':
        for level,keywords in [('easy','海南省博物馆'),('hard','厦门园林植物园'),('human','岳麓书院')]:
            city,code=cities[level]
            call(level+'_target',level,lambda k=keywords,c=code:dict(zip(('raw','meta'),client._call('/v5/place/text',{'keywords':k,'region':c,'city_limit':'true','page_size':10,'show_fields':'business,children'}))))
            call(level+'_weather',level,lambda c=code:client.weather(c,travel_date='2026-10-24'))
    elif a.mode=='origins':
        for level,keywords in [('hard','厦门站(南广场)'),('human','长沙站')]:
            city,code=cities[level]
            call(level+'_origin',level,lambda k=keywords,c=code:dict(zip(('raw','meta'),client._call('/v5/place/text',{'keywords':k,'region':c,'city_limit':'true','page_size':10,'show_fields':'business,children'}))))
    elif a.mode=='details':
        call('route_points_detail','shared',lambda:dict(zip(('raw','meta'),client._call('/v3/place/detail',{'id':'B025003OPX|B0FFG4WHQX|B02DB05TQH|BV10230535','extensions':'all','output':'JSON'}))))
    elif a.mode=='west_entry':
        call('hard_west_entry','hard',lambda:dict(zip(('raw','meta'),client._call('/v5/place/text',{'keywords':'厦门园林植物园 西门','region':'350200','city_limit':'true','page_size':10,'show_fields':'business,children'}))))
    elif a.mode=='refresh_weather':
        for level,(city,code) in cities.items():
            call(level+'_weather_refresh',level,lambda c=code:client.weather(c,travel_date='2026-10-24'))
    else:
        assert a.level
        level=a.level;suffix=('_'+a.route_version) if a.route_version else '';points=read(OUT/'private'/level/('verified_points'+suffix+'.json'))
        for direction,t in [('outbound',a.departure),('return',a.return_time)]:
            src,dst=(points['origin'],points['destination']) if direction=='outbound' else (points['destination'],points['origin'])
            call(level+'_'+direction+'_'+t.replace(':','')+suffix,level,
                 lambda src=src,dst=dst,t=t:client.transit(src['coordinates'],dst['coordinates'],city1=points['citycode'],city2=points['citycode'],departure_at='2026-10-24T'+t+':00+08:00'))
    print(json.dumps({'spent':ledger['spent'],'stopped':ledger['stopped'],'calls':[(c['label'],c['status']) for c in ledger['calls']]},ensure_ascii=False))
if __name__=='__main__':main()
