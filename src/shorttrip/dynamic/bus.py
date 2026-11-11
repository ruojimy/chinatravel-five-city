"""Live sandbox bus: make every already-constructed tool instance see new rows.

Why this is needed: ChinaTravel instantiates its tools *at import time* in three
different modules (`symbol_verification.commonsense_constraint`,
`symbol_verification.concept_func`, `symbol_verification.hard_constraint`) and each
of them keeps its own `{city: DataFrame}` / `{city: {name: (lat, lon)}}` cache.
Writing a CSV to disk would change nothing for a running process, so an update has
to be broadcast to every live instance. `SandboxBus` does exactly that and stamps
a version, which the planner/checker can then record.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import pandas as pd
from ..expansion_contract import VERSION, FIELDS, validate_record

TOOL_TYPES = {"Attractions", "Restaurants", "Accommodations", "Poi"}


@dataclass
class PatchOutcome:
    patched: int
    details: list[str]
    gate: dict = field(default_factory=dict)
    status: str = 'blocked'


def _is_tool(obj) -> bool:
    return type(obj).__name__ in TOOL_TYPES and hasattr(obj, "data")


def _scan(obj, found: list, depth: int = 2) -> None:
    if depth < 0 or obj is None:
        return
    if _is_tool(obj):
        if not any(obj is item for item in found):
            found.append(obj)
        for attr in ("poi", "poi_search"):
            inner = getattr(obj, attr, None)
            if inner is not None:
                _scan(inner, found, depth - 1)
        return
    if isinstance(obj, (dict,list,tuple)):
        for value in list(obj.values()) if isinstance(obj,dict) else obj:
            _scan(value, found, depth - 1)
        return
    if depth <= 0:
        return
    for name in ("poi", "poi_search", "attractions", "restaurants", "accommodations", "transport", "env"):
        child = getattr(obj, name, None)
        if child is not None and child is not obj:
            _scan(child, found, depth - 1)


def discover(extra_roots: list | None = None) -> list:
    """Collect every live sandbox tool instance in this process."""
    found: list = []
    if extra_roots:
        for root in extra_roots:
            _scan(root, found)
    for module_name in (
        "chinatravel.symbol_verification.commonsense_constraint",
        "chinatravel.symbol_verification.concept_func",
        "chinatravel.symbol_verification.hard_constraint",
        "chinatravel.environment.world_env",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for value in list(vars(module).values()):
            _scan(value,found,depth=4)
    return found


def envelope_gate(value,*,now=None,allow_synthetic=False):
    """Full expansion contract; historical flat rows are not planning inputs."""
    envelope=None
    if isinstance(value,dict):
        envelope=value if value.get('schema_version')==VERSION else value.get('expansion_envelope')
    if not isinstance(envelope,dict):
        return None,{'discovery_ok':False,'planning_ready':False,
          'errors':['complete_expansion_envelope_required'],
          'planning_blockers':['legacy_flat_record_not_planning_eligible'],
          'missing_planning_fields':[],'real_world_accuracy_certified':False}
    verdict=validate_record(envelope,now=now,allow_synthetic=allow_synthetic)
    if value is not envelope:
        for key in ('kind','city','name'):
            if key in value and value[key]!=envelope.get(key):
                verdict['errors'].append('wrapper_mismatch:'+key)
        kind=envelope.get('kind')
        for key in FIELDS.get(kind,()) if isinstance(kind,str) else ():
            data=envelope.get('data') if isinstance(envelope.get('data'),dict) else {}
            if key in value and value[key]!=data.get(key):verdict['errors'].append('wrapper_data_mismatch:'+key)
        if verdict['errors']:verdict['discovery_ok']=False;verdict['planning_ready']=False
    return envelope,verdict

def _row_for(kind,record,frame,city,lang,*,now=None,allow_synthetic=False):
    envelope,verdict=envelope_gate(record,now=now,allow_synthetic=allow_synthetic)
    if not verdict['planning_ready']:raise ValueError({'load_gate':verdict})
    if envelope['kind']!=kind or envelope['city']!=city or envelope['language']!=lang:
        raise ValueError('row scope differs from qualified envelope')
    if kind not in ('attraction','restaurant','accommodation'):
        raise ValueError('Legacy bus supports three entity tables only')
    return {key:envelope['data'][key] for key in FIELDS[kind]}

def apply(record,extra_roots=None,*,now=None,allow_synthetic=False):
    """Apply qualified envelopes only; registered cities only; no fact defaults."""
    envelope,gate=envelope_gate(record,now=now,allow_synthetic=allow_synthetic)
    if not gate['planning_ready']:
        return PatchOutcome(0,['blocked: complete planning-ready expansion envelope required'],gate)
    kind=envelope['kind'];city=envelope['city'];name=envelope['name']
    if kind not in ('attraction','restaurant','accommodation'):
        return PatchOutcome(0,['blocked: use isolated adapter for additional kinds'],gate,'unsupported_kind')
    instances=discover(extra_roots);target={'attraction':'Attractions','restaurant':'Restaurants',
                                          'accommodation':'Accommodations'}[kind]
    selected=[x for x in instances if type(x).__name__ in ('Poi',target)
              and getattr(x,'lang',None)==envelope['language']]
    for instance in selected:
        if city not in instance.data:
            return PatchOutcome(0,['blocked: city not registered in every tool'],gate,'unregistered_city')
        if type(instance).__name__==target:
            frame=instance.data[city]
            if 'id' in frame and ((frame['id']==envelope['data']['id']) & (frame['name'].astype(str)!=name)).any():
                return PatchOutcome(0,['blocked: source row id collides with another entity'],gate,'id_conflict')
    changes=[]
    for instance in selected:
        cls=type(instance).__name__
        try:
            if cls=='Poi':
                data=dict(instance.data[city]);data[name]=(envelope['data']['lat'],envelope['data']['lon'])
            else:
                frame=instance.data[city]
                row=_row_for(kind,envelope,frame,city,instance.lang,now=now,allow_synthetic=allow_synthetic)
                frame=frame[frame['name'].astype(str)!=name]
                data=pd.DataFrame([row]) if frame.empty else pd.concat([frame,pd.DataFrame([row])],ignore_index=True)
            changes.append((instance,data,f'{cls}[{city}] += {name}'))
        except Exception as exc:
            return PatchOutcome(0,[f'{cls} preflight failed: {exc}'],gate)
    for instance,data,_ in changes:
        mapping=dict(instance.data);mapping[city]=data;instance.data=mapping
        cache=getattr(instance,'_nearest_station_cache',None)
        if isinstance(cache,dict):cache.clear()
    if not changes:return PatchOutcome(0,['blocked: no registered live tool targets'],gate,'no_targets')
    return PatchOutcome(len(changes),[detail for _,_,detail in changes],gate,
                        'synthetic_fixture' if envelope['synthetic'] else 'applied')

