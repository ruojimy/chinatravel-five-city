"""Build into a temporary sibling, publish only after full success."""
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import io,json,sys

def atomic_main(build):
    original=list(sys.argv)
    if '--output' not in original:raise ValueError('--output is required')
    ix=original.index('--output')+1
    if ix>=len(original):raise ValueError('--output requires a value')
    destination=Path(original[ix]).resolve()
    if destination.exists():raise FileExistsError('output exists; snapshots are immutable')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.'+destination.name+'-',dir=str(destination.parent)) as temp:
        staged=Path(temp)/'snapshot';sys.argv[ix]=str(staged);captured=io.StringIO()
        try:
            with redirect_stdout(captured):build()
        finally:sys.argv[:]=original
        if destination.exists():raise FileExistsError('output appeared during build')
        staged.rename(destination)
        result=json.loads(captured.getvalue())
        if 'snapshot' in result:result['snapshot']=str(destination/'data_integration/dynamic_snapshot_v2.json')
        print(json.dumps(result,ensure_ascii=False))
