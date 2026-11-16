"""Apply the same repaired planning visibility to model and rule APIs."""
from functools import lru_cache
from pathlib import Path
import os,sys
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_PROFILE = os.environ.get('CHINATRAVEL_PROFILE')
_ENABLED = _PROFILE == 'expanded11'
if _ENABLED:
    _BASE = Path(os.environ.get('CT_SANDBOX_RUNTIME_DIR',
                 Path(__file__).resolve().parents[3] / 'src' / 'sandbox_runtime')).resolve()
    if str(_BASE) not in sys.path:
        sys.path.insert(0, str(_BASE))
    from sandbox_adapter import Sandbox

@lru_cache(maxsize=1)
def _sandbox():
    if not _ENABLED:
        raise RuntimeError('Expanded sandbox profile is not active')
    return Sandbox('G3')

def scoped_frame(frame, kind, slug, lang):
    if not _ENABLED:
        return frame
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
    if not _ENABLED:
        return set()
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
