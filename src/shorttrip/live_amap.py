"""Budgeted Amap adapter with explicit dates, safe logs and no key rotation."""
from __future__ import annotations
import hashlib,json,os,urllib.parse,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .freshness import canonical,sha,utcnow,parse_time

class LiveAmapError(RuntimeError):pass

class LiveAmapClient:
    def __init__(self,root,*,budget=4,key=None,transport=None):
        self.root=Path(root);self.budget=int(budget);self.spent=0;self.stopped=False
        if self.budget<0:raise ValueError('negative budget')
        path=self.root/'.secrets/amap.key'
        # Reuse the project key; never enumerate/rotate keys on a service limit.
        self._key=key or os.environ.get('AMAP_KEY') or (path.read_text(encoding='ascii').strip() if path.exists() else '')
        self.transport=transport or self._http
        self.audit=[]

    @staticmethod
    def _http(endpoint,params):
        request=urllib.request.Request(endpoint+'?'+urllib.parse.urlencode(params),headers={'User-Agent':'ShortTripFreshness/1.0'})
        with urllib.request.urlopen(request,timeout=20) as response:
            data=response.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise LiveAmapError('response_size_limit')
            return json.loads(data.decode('utf-8'))

    def _call(self,path,params):
        if self.stopped:raise LiveAmapError('provider_stopped; do not retry or rotate keys')
        if self.spent>=self.budget:raise LiveAmapError('budget_exhausted')
        if not self._key:raise LiveAmapError('missing_amap_key')
        endpoint='https://restapi.amap.com'+path
        self.spent+=1;at=utcnow();meta={'endpoint':endpoint,'params':params,'retrieved_at':at,'call_number':self.spent}
        try:data=self.transport(endpoint,{**params,'key':self._key})
        except Exception as exc:
            self.stopped=True;self.audit.append({**meta,'ok':False,'error_type':type(exc).__name__})
            raise LiveAmapError('request_failed:'+type(exc).__name__) from None
        # Defensive redaction even if an upstream service unexpectedly echoes key.
        data=json.loads(json.dumps(data,ensure_ascii=False).replace(self._key,'[REDACTED]'))
        meta.update(ok=str(data.get('status'))=='1',infocode=str(data.get('infocode','')))
        self.audit.append(meta)
        if not meta['ok']:
            self.stopped=True
            raise LiveAmapError('provider_error:'+meta['infocode']+'; stopped without key rotation')
        return data,meta

    @staticmethod
    def _claim(field,value,entity,context,data,meta,*,unit=None,observed_at=None,entity_verified=True,coverage_dates=None):
        raw=canonical(data)
        return {'claim_id':sha([field,entity,context,raw,meta['retrieved_at']])[:28],
            'evidence_id':'amap-raw:'+sha([meta['endpoint'],meta['retrieved_at'],raw]),
            'field':field,'value':value,'unit':unit,'entity_id':entity,'entity_verified':entity_verified,
            'source_id':'amap','source_url':meta['endpoint'],'retrieved_at':meta['retrieved_at'],
            'source_published_at':None,'source_updated_at':None,'observed_at':observed_at,'valid_until':None,
            'context':context,'coverage_dates':coverage_dates or [],
            'raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'authority':'official_api','licence_status':'api_terms','extraction_verified':True,'retrieval_method':'structured_api',
            'authority_note':'Provider output/estimate, not a measured guarantee. Raw JSON retained for extraction audit.'}

    def weather(self,adcode,*,travel_date=None):
        if not str(adcode).isdigit() or len(str(adcode))!=6:raise ValueError('six digit adcode required')
        extension='all' if travel_date else 'base'
        if travel_date:
            # Validate without falsely claiming the provider can forecast any date.
            datetime.strptime(travel_date,'%Y-%m-%d')
        data,meta=self._call('/v3/weather/weatherInfo',{'city':str(adcode),'extensions':extension,'output':'JSON'})
        rows=data.get('forecasts' if travel_date else 'lives') or []
        if not rows:raise LiveAmapError('empty_weather_response')
        row=rows[0];stamp=row.get('reporttime');observed=None
        try:observed=datetime.fromisoformat(stamp).replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
        except (ValueError,TypeError):pass
        context={'adcode':str(adcode)}
        coverage=[]
        if travel_date:
            context['travel_date']=travel_date;coverage=[r.get('date') for r in row.get('casts',[])]
            value=next((r for r in row.get('casts',[]) if r.get('date')==travel_date),None)
        else:value={k:row.get(k) for k in ('weather','temperature','winddirection','windpower','humidity')}
        claim=self._claim('weather_forecast' if travel_date else 'weather_now',value,'weather:'+str(adcode),context,data,meta,
                          observed_at=observed,entity_verified=str(row.get('adcode'))==str(adcode),coverage_dates=coverage)
        if value is None:claim['extraction_verified']=False
        return claim

    def transit(self,origin,destination,*,city1,city2,departure_at,mode='metro',coord_system='GCJ02'):
        if coord_system!='GCJ02':raise ValueError('Resolve verified GCJ02 coordinates before Amap routing')
        if mode not in ('metro','public_transit'):raise ValueError('mode must be metro or public_transit')
        def coordinate(v):
            if len(v)!=2:raise ValueError('coordinates must be [longitude,latitude]')
            lon,lat=map(float,v)
            if not (-180<=lon<=180 and -90<=lat<=90):raise ValueError('invalid coordinates')
            return f'{lon:.6f},{lat:.6f}'
        origin=coordinate(origin);destination=coordinate(destination)
        departure=parse_time(departure_at)
        if departure is None:raise ValueError('departure_at needs timezone')
        if departure<datetime.now(timezone.utc)-timedelta(minutes=15):raise ValueError('historical departure cannot be live verified')
        if departure>datetime.now(timezone.utc)+timedelta(days=7):raise ValueError('project routing lookahead limit is 7 days; defer recheck')
        local=departure.astimezone(timezone(timedelta(hours=8)))
        context={'origin':origin,'destination':destination,'coord_system':'GCJ02','mode':mode,
                 'departure_at':departure.isoformat(),'travel_date':local.date().isoformat(),'city1':str(city1),'city2':str(city2)}
        params={'origin':origin,'destination':destination,'city1':str(city1),'city2':str(city2),
                'strategy':'7' if mode=='metro' else '0','date':local.strftime('%Y-%m-%d'),
                'time':local.strftime('%H-%M'),'show_fields':'cost','AlternativeRoute':'3','output':'JSON'}
        data,meta=self._call('/v5/direction/transit/integrated',params)
        route=data.get('route') or {};transits=route.get('transits') or []
        if not transits:raise LiveAmapError('no_route_returned')
        def has_only_metro(t):
            lines=[line for s in t.get('segments',[]) for line in (s.get('bus') or {}).get('buslines',[])]
            return bool(lines) and all('地铁' in str(line.get('type','')) or 'subway' in str(line.get('type','')).lower() for line in lines)
        eligible=[t for t in transits if mode!='metro' or has_only_metro(t)]
        chosen=(eligible or transits)[0];cost=chosen.get('cost') or {}
        if not isinstance(cost,dict):cost={}
        def number(v,scale=1):
            try:return float(v)/scale
            except (TypeError,ValueError):return None
        duration=number(cost.get('duration',chosen.get('duration')),60)
        fare=number(cost.get('transit_fee',chosen.get('transit_fee')))
        def same_coords(actual,expected):
            try:return all(abs(float(a)-float(b))<0.00002 for a,b in zip(actual.split(','),expected.split(','))) and len(actual.split(','))==2
            except (ValueError,AttributeError):return False
        bound=same_coords(route.get('origin'),origin) and same_coords(route.get('destination'),destination) and bool(eligible)
        entity='route:'+sha(context)[:24]
        claims=[]
        for field,value,unit in [('route_duration',duration,'minutes'),('route_fare',fare,'CNY')]:
            c=self._claim(field,value,entity,context,data,meta,unit=unit,observed_at=meta['retrieved_at'],entity_verified=bound)
            c['mode_requirement_met']=bool(eligible);c['provider_service_time_guaranteed']=False;claims.append(c)
        return claims
