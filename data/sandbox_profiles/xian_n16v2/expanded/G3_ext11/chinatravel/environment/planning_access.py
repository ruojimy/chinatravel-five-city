"""Apply the same repaired planning visibility to model and rule APIs."""
from functools import lru_cache
from pathlib import Path
import sys
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_BASE = _ROOT.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))
from sandbox_adapter import Sandbox, _xian_grade_evidence, _sha

_ARM = {'G2_ext10':'G2', 'G3_ext11':'G3'}.get(_ROOT.name)
if not _ARM:
    raise RuntimeError('Access gate is only valid in the named repaired sandbox copies')

@lru_cache(maxsize=1)
def _sandbox():
    return Sandbox(_ARM)

def scoped_frame(frame, kind, slug, lang):
    if lang != 'zh':
        raise NotImplementedError('Repaired benchmark gate currently supports zh only')
    sandbox = _sandbox()
    city = next(c for c,s in sandbox.cities.items() if s == slug)
    items = sandbox._eligible(kind,city)
    rows = [item['payload']['data'] for _,item in items]
    output = pd.DataFrame(rows, columns=frame.columns)
    for key in ('id','lat','lon','price','numbed','recommendmintime','recommendmaxtime'):
        if key in output:
            output[key] = pd.to_numeric(output[key], errors='coerce')
    return output.reset_index(drop=True)

@lru_cache(maxsize=None)
def blocked_poi_names(city):
    sandbox = _sandbox()
    if city not in sandbox.cities:
        city = next((name for name,slug in sandbox.cities.items() if slug == city), city)
    if city not in sandbox.cities:
        return set()
    excluded, admitted = set(), set()
    for kind in ('attraction','restaurant','accommodation'):
        _, _, _, exact, _, _, _ = sandbox._catalog(kind,city)
        for index,_ in exact:
            item = sandbox._record(kind,city,index)
            access = item['payload']['access']
            # Directory visibility is broader than routeability. Do not expose
            # derived coordinates through the raw POI table and let the rule
            # planner bypass the same on-route verification used by the model.
            routeable = access['main_path'] and access['planning_position_available']
            (admitted if routeable else excluded).add(item['name'])
    # Keep a name if a different, independently eligible record uses it.
    return excluded - admitted
