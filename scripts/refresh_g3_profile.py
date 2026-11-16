"""Capture, validate and install dynamic observations as a new G3 profile.

Entity requests require candidate HTTPS URLs from a separate discovery step;
search results are never themselves treated as source evidence. The input
profile and any existing profile remain unchanged.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,subprocess,sys
from g3_sandbox import configure,REPO,RUNTIME

INGEST=RUNTIME/'ingest'
sys.path.insert(0,str(RUNTIME));sys.path.insert(0,str(INGEST))

def read_list(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data,list):raise ValueError('request file must be a JSON array')
    return data

def invoke(script,args,log):
    process=subprocess.run([sys.executable,'-X','utf8',str(script),*map(str,args)],
                           capture_output=True,text=True,encoding='utf-8',errors='replace')
    log.write_text(json.dumps({'returncode':process.returncode,'stdout':process.stdout,
                               'stderr':process.stderr},ensure_ascii=False,indent=2),encoding='utf-8')
    if process.returncode:raise RuntimeError('materialization failed; see '+str(log))
    return json.loads(process.stdout)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--name',required=True)
    p.add_argument('--work-dir',type=Path,required=True)
    rail=p.add_mutually_exclusive_group();rail.add_argument('--route-requests',type=Path);rail.add_argument('--rail-journal',type=Path)
    entity=p.add_mutually_exclusive_group();entity.add_argument('--entity-requests',type=Path);entity.add_argument('--entity-journal',type=Path)
    p.add_argument('--trip-date',help='ISO date for explicitly date-scoped entity evidence')
    a=p.parse_args();base=a.base.resolve();work=a.work_dir.resolve()
    if not any((a.route_requests,a.rail_journal,a.entity_requests,a.entity_journal)):
        p.error('provide at least one request list or evidence journal')
    if work.exists():raise FileExistsError('work directory already exists; retain previous attempts')
    if work==base or work.is_relative_to(base):raise ValueError('work directory must be outside the input profile')
    config=configure(base,live_dir=work/'amap_live')
    work.mkdir(parents=True)
    log={'started_utc':datetime.now(timezone.utc).isoformat(),'base':config,'route_results':[],
         'entity_results':[],'boundary':'Supplied URLs require separate discovery; observed prices are conditional.'}
    log_path=work/'capture_receipt.json'
    def save():log_path.write_text(json.dumps(log,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();rail_journal=a.rail_journal.resolve() if a.rail_journal else None
    if a.route_requests:
        import dynamic_live
        for request in read_list(a.route_requests):
            if not isinstance(request,dict) or set(request)-{'from_city','to_city','mode'}:
                raise ValueError('invalid route request')
            result=dynamic_live.lookup_route(request['from_city'],request['to_city'],request.get('mode','train'))
            log['route_results'].append({'request':request,'result':result});save()
        candidate=work/'amap_live/dynamic_live.sqlite3'
        if candidate.is_file():rail_journal=candidate
    entity_journal=a.entity_journal.resolve() if a.entity_journal else None
    if a.entity_requests:
        from entity_evidence import capture
        entity_journal=work/'entity_live.sqlite3'
        for request in read_list(a.entity_requests):
            result=capture(entity_journal,request,budget=12)
            log['entity_results'].append({'request':request,'result':result});save()
    current=base
    if rail_journal:
        output=work/'rail_snapshot'
        log['rail_materialization']=invoke(INGEST/'materialize_live.py',
            ['--base',current,'--journal',rail_journal,'--output',output],work/'rail_materialization.log.json')
        current=output;save()
    if entity_journal:
        output=work/'entity_snapshot';args=['--base',current,'--journal',entity_journal,'--output',output]
        if a.trip_date:args+=['--trip-date',a.trip_date]
        log['entity_materialization']=invoke(INGEST/'materialize_entities.py',args,work/'entity_materialization.log.json')
        current=output;save()
    if current==base:
        log['status']='no_usable_capture';save();return
    result=invoke(REPO/'scripts/install_g3_profile.py',['--source',current,'--name',a.name],work/'install.log.json')
    log.update(status='installed',installed_profile=result['profile'],snapshot_sha256=result['snapshot_sha256']);save()
    print(json.dumps({'status':log['status'],'profile':result['profile'],
                      'snapshot_sha256':result['snapshot_sha256'],'receipt':str(log_path)},ensure_ascii=False))

if __name__=='__main__':main()
