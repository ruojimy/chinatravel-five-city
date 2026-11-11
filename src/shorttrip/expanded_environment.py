"""Scoped ChinaTravel adapter for an immutable expansion snapshot.

Use in a dedicated sequential process. Original CSVs and source modules are not
written. All runtime aliases/caches are restored on exit, including exceptions.
Unknown routes return an explicit unavailable result; no distance/speed guesses.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from copy import copy, deepcopy
from importlib import import_module
import sys
from .expansion_contract import FIELDS, validate_record
from .freshness import parse_time

CLASS_TO_KEY={'Accommodations':'accommodations','Attractions':'attractions',
              'Restaurants':'restaurants','Poi':'poi','Transportation':'transportation',
              'IntercityTransport':'intercitytransport'}
_ACTIVE=False

def _synthetic_transport_only(item,allow_synthetic):
    if not isinstance(item,dict):raise ValueError('transport record must be an object')
    if item.get('synthetic') is not True:
        raise NotImplementedError('Real raw transport injection is disabled: a source_id/source_ref is not a P11-gated evidence bundle. Resolve claims through the live retrieval pipeline, not this fixture adapter.')
    if not allow_synthetic:raise ValueError('synthetic transport is disabled')
    if item.get('source_id','synthetic_fixture')!='synthetic_fixture':
        raise ValueError('synthetic transport may not impersonate amap or a real source')
    if not isinstance(item.get('source_ref'),str) or not item['source_ref'].strip():raise ValueError('synthetic source reference required')
    if not isinstance(item.get('retrieved_at'),str) or parse_time(item['retrieved_at']) is None:
        raise ValueError('timezone-aware synthetic retrieval clock required')

def _minutes(value):
    if not isinstance(value,str) or len(value)!=5 or value[2]!=':':raise ValueError('HH:MM required')
    hour,minute=map(int,value.split(':'))
    if not (0<=hour<=23 and 0<=minute<=59):raise ValueError('invalid clock')
    return hour*60+minute

def _nonnegative(value):
    import math
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


class FrozenRoutes:
    """Only exact frozen city/origin/destination/mode/departure matches replay."""
    def __init__(self, base, poi, routes=(), *, allow_synthetic=False):
        self.base=base;self.poi_search=poi;self.routes={};self.lang=base.lang
        self.city_list=list(poi.city_list);self.city_list_chinese=list(poi.city_cn_list)
        for item in routes:
            _synthetic_transport_only(item,allow_synthetic)
            key=tuple(item.get(k) for k in ('city','start','end','mode','departure'))
            if any(not isinstance(x,str) or not x.strip() for x in key) or not isinstance(item.get('legs'),list) or not item['legs']:
                raise ValueError('incomplete frozen route')
            if item['mode'] not in ('walk','taxi','metro'):raise ValueError('unsupported route mode')
            _minutes(item['departure'])
            if key in self.routes:raise ValueError('duplicate frozen route key')
            previous=None;end_time=None
            for leg in item['legs']:
                if not isinstance(leg,dict):raise ValueError('route leg must be an object')
                if any(k not in leg for k in ('start','end','mode','start_time','end_time','cost','distance')):
                    raise ValueError('incomplete route leg')
                if any(not isinstance(leg[k],str) or not leg[k].strip() for k in ('start','end','mode')):
                    raise ValueError('invalid route text')
                if leg['mode'] not in ('walk','taxi','metro') or not _nonnegative(leg['cost']) or not _nonnegative(leg['distance']):
                    raise ValueError('invalid route mode, cost or distance')
                begin=_minutes(leg['start_time']);finish=_minutes(leg['end_time'])
                if finish<begin or (end_time is not None and begin<end_time):raise ValueError('invalid route chronology')
                if previous is not None and leg['start']!=previous:raise ValueError('disconnected route legs')
                previous=leg['end'];end_time=finish
            if item['legs'][0]['start']!=item['start'] or previous!=item['end'] or item['legs'][0]['start_time']!=item['departure']:
                raise ValueError('route context mismatch')
            self.routes[key]=deepcopy(item['legs'])

    def goto(self,city,start,end,start_time,transport_type,verbose=False):
        # Deliberately no fallback to the sandbox's fixed speeds or fares, even
        # for existing cities, when this evidence adapter is enabled.
        key=(city,start,end,transport_type,start_time)
        return deepcopy(self.routes[key]) if key in self.routes else 'Unavailable: no exact frozen route evidence'

    def __getattr__(self,name):return getattr(self.base,name)


class FrozenIntercity:
    def __init__(self,base,records=(),*,allow_synthetic=False):
        self.base=base;self.lang=base.lang;self.rows=[]
        for item in records:
            _synthetic_transport_only(item,allow_synthetic)
            row=item.get('data',{})
            if not isinstance(row,dict):raise ValueError('intercity data must be an object')
            if item.get('mode') not in ('train','airplane'):raise ValueError('unsupported intercity mode')
            if any(not isinstance(item.get(k),str) or not item[k].strip() for k in ('start_city','end_city')):
                raise ValueError('intercity city context required')
            required=('From','To','BeginTime','EndTime','Cost')
            identifier='TrainID' if item.get('mode')=='train' else 'FlightID'
            if any(k not in row for k in required+(identifier,)):raise ValueError('incomplete intercity row')
            if any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('From','To',identifier)):
                raise ValueError('intercity identity invalid')
            _minutes(row['BeginTime']);_minutes(row['EndTime'])
            if not _nonnegative(row['Cost']):raise ValueError('intercity cost invalid')
            if 'Duration' not in row or not _nonnegative(row['Duration']) or row['Duration']==0:
                raise ValueError('intercity positive duration required')
            self.rows.append(item)

    def select(self,start_city,end_city,intercity_type,earliest_leave_time='00:00'):
        import pandas as pd
        rows=[dict(i['data']) for i in self.rows if i['start_city']==start_city
              and i['end_city']==end_city and i['mode']==intercity_type
              and i['data']['BeginTime']>=earliest_leave_time]
        cols=['From','To','BeginTime','EndTime','Cost','TrainID','FlightID','Duration']
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

    def __getattr__(self,name):return getattr(self.base,name)


class ExpandedEnvironment(AbstractContextManager):
    def __init__(self,records,*,version,now=None,routes=(),intercity=(),city_slugs=None,
                 allow_synthetic=False):
        if not version:raise ValueError('immutable version required')
        self.version=version;self.now=now;self.records=[];self.ready=[];self.verdicts=[]
        self.routes=routes;self.intercity=intercity;self.allow_synthetic=allow_synthetic
        self.city_slugs=dict(city_slugs or {});self._restore=[];self.tools={}
        seen=set();groups={}
        for record in records:
            verdict=validate_record(record,now=now,allow_synthetic=allow_synthetic)
            if not verdict['discovery_ok']:raise ValueError({'record_id':record.get('record_id') if isinstance(record,dict) else None,'errors':verdict['errors']})
            rid=record['record_id'];key=(record['city'],record['kind'],record['name'])
            if rid in seen:raise ValueError('duplicate expansion record_id '+str(rid))
            if record['language']!='zh':raise ValueError('This scoped adapter currently supports zh only')
            seen.add(rid);self.records.append(record);self.verdicts.append(verdict)
            groups.setdefault(key,[]).append(len(self.records)-1)
        self.ambiguous_names=[]
        for key,indexes in groups.items():
            if len(indexes)<2:continue
            self.ambiguous_names.append({'city':key[0],'kind':key[1],'name':key[2],
                                         'record_ids':[self.records[i]['record_id'] for i in indexes]})
            for index in indexes:
                self.verdicts[index]['planning_ready']=False
                self.verdicts[index]['planning_blockers'].append('ambiguous_name_not_officially_addressable')
        self.ready=[r for r,v in zip(self.records,self.verdicts) if v['planning_ready']]

    def discover(self,city,kind=None):
        return [r for r in self.records if r['city']==city and (kind is None or r['kind']==kind)]

    def _set(self,obj,key,value):
        self._restore.append((obj,key,hasattr(obj,key),getattr(obj,key,None)));setattr(obj,key,value)

    def __enter__(self):
        global _ACTIVE
        if _ACTIVE:raise RuntimeError('ExpandedEnvironment is process-scoped; nested/concurrent adapters forbidden')
        _ACTIVE=True
        try:
            self._install()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info());raise

    def _install(self):
        import pandas as pd
        common=import_module('chinatravel.symbol_verification.commonsense_constraint')
        concept=import_module('chinatravel.symbol_verification.concept_func')
        hard=import_module('chinatravel.symbol_verification.hard_constraint')
        world=import_module('chinatravel.environment.world_env')
        language=import_module('chinatravel.environment.language')
        old=common._TOOLS_BY_LANG['zh']
        bases=dict(zip(('accommodations','restaurants','attractions','intercitytransport','transportation'),old))
        bases['poi']=old[-1].poi_search
        cities=sorted({r['city'] for r in self.records})
        old_names=list(language.CITY_NAMES['zh']);old_slugs=list(language.CITY_SLUGS)
        added=[c for c in cities if c not in old_names]
        for c in added:
            slug=self.city_slugs.get(c)
            if not slug or slug in old_slugs or slug in [self.city_slugs[x] for x in added if x!=c and x in self.city_slugs]:
                raise ValueError('new city needs a distinct explicit slug: '+c)
        poi=copy(bases['poi']);poi.data=dict(poi.data)
        poi.city_cn_list=old_names+added;poi.city_list=old_slugs+[self.city_slugs[c] for c in added]
        for c in cities:poi.data[c]=dict(poi.data.get(c,{}))
        # Discovery-only entity identity/coordinates are intentionally NOT leaked
        # into routable official tables.
        for r in self.ready:
            if r['kind'] in ('train','flight'):continue
            if r['kind']=='poi':coord=tuple(r['data']['position'])
            elif r['kind']=='metro_station':
                lon,lat=map(float,r['data']['position'].split(','));coord=(lat,lon)
            else:coord=(r['data']['lat'],r['data']['lon'])
            previous=poi.data[r['city']].get(r['name'])
            if previous is not None and previous!=coord:
                raise ValueError('conflicting coordinates for '+r['name'])
            poi.data[r['city']][r['name']]=coord
        self.tools={'poi':poi}
        for key,kind in (('attractions','attraction'),('restaurants','restaurant'),('accommodations','accommodation')):
            tool=copy(bases[key]);tool.data=dict(tool.data);tool.poi=poi
            fields=FIELDS[kind]
            for c in cities:
                frame=tool.data.get(c,pd.DataFrame(columns=fields))
                rows=[r['data'] for r in self.ready if r['city']==c and r['kind']==kind]
                if rows:
                    overlap=set(frame['name'].astype(str)) & {r['name'] for r in rows}
                    if overlap:raise ValueError('expansion may not silently replace baseline entities: '+str(overlap))
                    frame=(pd.DataFrame(rows,columns=fields) if frame.empty else
                           pd.concat([frame,pd.DataFrame(rows)],ignore_index=True))
                tool.data[c]=frame
            meta='key_type_tuple_list' if kind=='accommodation' else 'key_type_tuple_list_map'
            keymap=dict(getattr(tool,meta))
            for c in cities:keymap[c]=[(col,str(tool.data[c][col].dtype)) for col in tool.data[c]]
            setattr(tool,meta,keymap)
            if kind!='accommodation':
                attr='type_list_map' if kind=='attraction' else 'cuisine_list_map'
                index='type' if kind=='attraction' else 'cuisine'
                mapping=dict(getattr(tool,attr))
                for c in cities:mapping[c]=tool.data[c][index].unique()
                setattr(tool,attr,mapping)
            self.tools[key]=tool
        self.tools['transportation']=FrozenRoutes(bases['transportation'],poi,self.routes,allow_synthetic=self.allow_synthetic)
        journeys=list(self.intercity)+[{'start_city':r['start_city'],'end_city':r['end_city'],
            'mode':'train' if r['kind']=='train' else 'airplane','data':r['data'],
            'source_ref':r['source_url'] or r['source_locator'],'retrieved_at':r['retrieved_at'],
            'synthetic':r['synthetic']} for r in self.ready if r['kind'] in ('train','flight')]
        self.tools['intercitytransport']=FrozenIntercity(bases['intercitytransport'],journeys,allow_synthetic=self.allow_synthetic)
        triple=(self.tools['accommodations'],self.tools['restaurants'],self.tools['attractions'])
        quint=triple+(self.tools['intercitytransport'],self.tools['transportation'])
        self._set(common,'_TOOLS_BY_LANG',{**common._TOOLS_BY_LANG,'zh':quint})
        self._set(hard,'_TOOLS_BY_LANG',{**hard._TOOLS_BY_LANG,'zh':triple})
        self._set(concept,'_TOOLS_BY_LANG',{**concept._TOOLS_BY_LANG,'zh':{
            k:self.tools[k] for k in ('accommodations','restaurants','attractions')}})
        for module in (common,hard):
            for attr,key in (('accommodation','accommodations'),('restaurants','restaurants'),('attractions','attractions')):
                self._set(module,attr,self.tools[key])
        self._set(common,'intercity_transport',self.tools['intercitytransport'])
        self._set(common,'innercity_transport',self.tools['transportation'])
        # Constructor aliases in already loaded ChinaTravel modules are scoped to
        # this snapshot as well, so WorldEnv and new tool consumers see one data.
        originals={getattr(world,name):key for name,key in CLASS_TO_KEY.items()}
        for module_name,module in list(sys.modules.items()):
            if module is None or not (module_name.startswith('chinatravel.') or module_name=='shorttrip.env'):continue
            for attr,value in list(vars(module).items()):
                try:key=originals.get(value)
                except TypeError:continue
                if key is not None:
                    def factory(*args,_key=key,**kwargs):
                        if kwargs.get('lang','zh') not in ('zh',None):raise ValueError('zh expansion context only')
                        if kwargs.get('en_version'):raise ValueError('en unavailable in zh expansion context')
                        return self.tools[_key]
                    self._set(module,attr,factory)
        # Keep old registry objects unchanged; patch imported aliases by identity.
        new_names={**language.CITY_NAMES,'zh':old_names+added,
                   'en':list(language.CITY_NAMES['en'])+[self.city_slugs[c] for c in added]}
        old_names_obj=language.CITY_NAMES;old_slugs_obj=language.CITY_SLUGS
        for module_name,module in list(sys.modules.items()):
            if module is None or not module_name.startswith('chinatravel.'):continue
            for attr,value in list(vars(module).items()):
                if value is old_names_obj:self._set(module,attr,new_names)
                elif value is old_slugs_obj:self._set(module,attr,poi.city_list)
        # Explicit language setting avoids accidental previous en context.
        self._set(concept,'_current_lang','zh')
        self.registration_report={'version':self.version,'cities':cities,
            'discovery_records':len(self.records),'planning_ready_records':len(self.ready),
            'ambiguous_names':self.ambiguous_names,
            'source_files_modified':0,'traffic_policy':'exact frozen evidence only',
            'baseline_transport_fallback':False,'real_world_accuracy_certified':False}
        self.registration_report['real_raw_transport_injection']='disabled_requires_separate_P11_gated_live_pipeline'

    def world(self):
        if not self.tools:raise RuntimeError('enter context first')
        return import_module('chinatravel.environment.world_env').WorldEnv(lang='zh')

    def __exit__(self,exc_type,exc,tb):
        global _ACTIVE
        for obj,key,existed,value in reversed(self._restore):
            if existed:setattr(obj,key,value)
            else:delattr(obj,key)
        self._restore.clear();_ACTIVE=False
        return False
