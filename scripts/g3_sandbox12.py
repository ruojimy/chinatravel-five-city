"""Explicit opt-in to the intercity-only 12-city profile on the main engine."""
from pathlib import Path
from hashlib import sha256
import argparse,json,os,sys
from g3_sandbox import REPO,RUNTIME,ENGINE,configure as configure11

BASE=REPO/'data/sandbox_profiles/xian_n16v2'
PROFILE=REPO/'data/sandbox_profiles/intercity12'
def digest(p):return sha256(p.read_bytes()).hexdigest()
def configure(profile=PROFILE, *, environ=None):
 profile=Path(profile).resolve();target=os.environ if environ is None else environ
 info=configure11(BASE,engine=ENGINE,environ=target)
 receipt=json.loads((profile/'receipt.json').read_text(encoding='utf8'))
 index=profile/'inventory.json'
 if receipt.get('schema')!='intercity12-profile-v1' or digest(index)!=receipt.get('inventory_sha256'):
  raise ValueError('invalid 12-city receipt or inventory')
 if receipt.get('base_snapshot_sha256')!=info['snapshot_sha256']:raise ValueError('base snapshot mismatch')
 entries=json.loads(index.read_text(encoding='utf8'))
 for rel,expected in entries.items():
  p=(profile/rel).resolve()
  if Path(rel).is_absolute() or not p.is_relative_to(profile) or not p.is_file() or digest(p)!=expected:
   raise ValueError('12-city evidence changed: '+rel)
 actual={p.relative_to(profile).as_posix() for p in profile.rglob('*') if p.is_file()
         and p.name not in ('inventory.json','receipt.json') and '__pycache__' not in p.parts and p.suffix!='.pyc'}
 if actual!=set(entries):raise ValueError('12-city file inventory changed')
 target.update(CHINATRAVEL_PROFILE='expanded12',CHINATRAVEL_DATABASE_ROOT=str(profile/'database'),
               CT_SANDBOX_PROFILE_ROOT=str(BASE),CT_SANDBOX_RUNTIME_DIR=str(RUNTIME),
               CT_SANDBOX_ENGINE_ROOT=str(ENGINE),CT_DYNAMIC_MODE='snapshot')
 return {'profile':'expanded12_intercity_only','database':str(profile/'database'),
         'engine':str(ENGINE),'reference_rows':receipt['xiamen_reference_rows'],
         'reference_directions':receipt['xiamen_directions'],'inventory_sha256':receipt['inventory_sha256'],
         'boundary':receipt['boundary']}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,default=PROFILE)
 p.add_argument('--tool',choices=('intercity_search','catalog_list','catalog_search','catalog_entity','catalog_preflight','reference_search','goto'))
 p.add_argument('--args-file',type=Path);a=p.parse_args();info=configure(a.profile)
 if not a.tool:print(json.dumps(info,ensure_ascii=False,indent=2));return
 if not a.args_file:p.error('--args-file is required')
 args=json.loads(a.args_file.read_text(encoding='utf-8-sig'));sys.path.insert(0,str(RUNTIME))
 from sandbox_adapter import Sandbox
 try:result=getattr(Sandbox('G3'),a.tool)(**args)
 except NotImplementedError as e:result={'state':'unknown','reason':str(e)}
 print(json.dumps({'configuration':info,'result':result},ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
