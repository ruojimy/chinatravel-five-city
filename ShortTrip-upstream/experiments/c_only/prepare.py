"""Prepare10 C-only runs from checked-in input cases, without model calls."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]
if (ROOT/'manifest.json').exists():
    raise SystemExit('Already prepared. Keep saved runs, or use a new checkout for a fresh experiment.')
cases=json.loads((ROOT/'cases.json').read_text(encoding='utf-8'))
assert len(cases)==10 and all(c['group']=='C' and c['repetition']==1 for c in cases)
files=[p.relative_to(PROJECT).as_posix() for p in (PROJECT/'chinatravel').rglob('*.py')
       if not any(part in ('database','database_en','__pycache__') for part in p.parts)]
files += ['experiments/c_only/'+name for name in ('experiment_agent.py','dfs_snapshot.py','rules.py','catalog.py','meal_pruning.py')]

digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=dict(created_at=datetime.now(timezone.utc).isoformat(),project=str(PROJECT),language='zh',groups=['C'],repetitions=1,wall_seconds=1800,candidate_target=20,cases=cases,translation_cache='fresh_per_case',oracle_in_planning=False,source_sha256={f:digest(PROJECT/f) for f in files})
manifest['experiment_sha256']={name:digest(ROOT/name) for name in ('worker.py','experiment_agent.py','rules.py','dfs_snapshot.py','catalog.py','meal_pruning.py','driver.py','report.py')}
(ROOT/'prompt_snapshots').mkdir(exist_ok=True)
for name in ('prompts.py','prompts_en.py'):
    shutil.copy2(PROJECT/'chinatravel/agent/nesy_agent/prompts'/name,ROOT/'prompt_snapshots'/name)
(ROOT/'config.json').write_text(json.dumps(dict(project=str(PROJECT),workers=1,model='qwen3.5-4b-q8',base_url='http://127.0.0.1:18080/v1'),indent=2),encoding='utf-8')
(ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared10 C-only runs; no model calls.')
