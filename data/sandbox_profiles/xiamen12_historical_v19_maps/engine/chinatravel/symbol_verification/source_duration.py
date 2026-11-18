"""Resolve intercity duration from exact matching local frozen evidence only."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json,math,importlib.util,os
from .date_timeline import parse_amap_rail_clock

def _clock(value):
    if not isinstance(value,str):return None
    value=value.strip()
    try:return parse_amap_rail_clock(value,1)['clock']
    except ValueError:return None

def _matches_name(value, *candidates):
    if value is None:return False
    return any(str(value).strip()==str(c).strip() for c in candidates if c is not None)

class DurationResolver:
    def __init__(self,root):
        self.root=Path(root).resolve()
        database=Path(os.environ['CHINATRAVEL_DATABASE_ROOT']).resolve() if os.environ.get('CHINATRAVEL_DATABASE_ROOT') else self.root/'chinatravel/environment/database'
        self.db=database/'intercity_transport'
        if not self.db.is_dir():raise FileNotFoundError('intercity evidence directory not found')
        self.station_aliases=None
        alias_file=self.root/'chinatravel/environment/station_aliases.py'
        if alias_file.is_file():
            spec=importlib.util.spec_from_file_location('duration_station_aliases',alias_file)
            self.station_aliases=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.station_aliases)

    def _matches_station(self,city,value,*candidates):
        if _matches_name(value,*candidates):return True
        if self.station_aliases is None:return False
        for candidate in candidates:
            if not isinstance(candidate,str):continue
            try:
                if self.station_aliases.compare(self.root,city,value,candidate,station_context=True)['state']=='pass':
                    return True
            except (FileNotFoundError,ValueError):
                pass
        return False

    @lru_cache(maxsize=None)
    def _read(self,path):
        path=Path(path)
        if not path.is_file():return []
        raw=path.read_bytes();text=raw.decode('utf-8-sig')
        if path.suffix=='.jsonl':rows=[json.loads(x) for x in text.splitlines() if x.strip()]
        else:rows=json.loads(text)
        return [{'row':row,'path':str(path),'sha256':sha256(raw).hexdigest()} for row in rows if isinstance(row,dict)]

    def __call__(self,query,activity):
        kind=activity.get('type')
        if kind not in ('train','airplane'):return None
        ident=activity.get('TrainID' if kind=='train' else 'FlightID')
        if not ident:return None
        if _clock(activity.get('start_time')) is None or _clock(activity.get('end_time')) is None:return None
        if kind=='train':
            start,end=query.get('start_city'),query.get('target_city')
            if not isinstance(start,str) or not isinstance(end,str):return None
            if any(c in start+end for c in ('/','\\','..')):return None
            files=[(self.db/'train'/f'from_{start}_to_{end}.json',start,end),
                   (self.db/'train'/f'from_{end}_to_{start}.json',end,start)]
        else:files=[(self.db/'airplane.jsonl',None,None)]
        found=[]
        for path,origin,destination in files:
            for item in self._read(path):
                r=item['row']
                if r.get('TrainID' if kind=='train' else 'FlightID')!=ident:continue
                name_match=self._matches_station if kind=='train' else lambda city,value,*candidates:_matches_name(value,*candidates)
                if not name_match(origin,activity.get('start'),r.get('From'),r.get('FromName')):continue
                if not name_match(destination,activity.get('end'),r.get('To'),r.get('ToName')):continue
                if _clock(r.get('BeginTime'))!=_clock(activity.get('start_time')):continue
                if _clock(r.get('EndTime'))!=_clock(activity.get('end_time')):continue
                try:duration=float(r.get('Duration'))
                except (TypeError,ValueError):continue
                if not math.isfinite(duration) or duration<=0:continue
                found.append({'minutes':duration*60,'path':item['path'],'sha256':item['sha256']})
        if not found:return None
        if max(x['minutes'] for x in found)-min(x['minutes'] for x in found)>0.01:return None
        return {'minutes':found[0]['minutes'],'matches':len(found),
                'source_files':[{'path':x['path'],'sha256':x['sha256']} for x in found]}
