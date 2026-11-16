"""Load spatial checks from the exact configured sandbox engine."""
from functools import lru_cache
from pathlib import Path
import importlib.util

@lru_cache(maxsize=4)
def _module(root):
    source=Path(root).resolve()/'chinatravel/environment/station_aliases.py'
    spec=importlib.util.spec_from_file_location('evaluated_station_aliases',source)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def validate_space(query,plan,root):
    return _module(str(Path(root).resolve())).validate_space(query,plan,root)
