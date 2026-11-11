"""Offline source-family status for exploratory identity gaps, not dispatch."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.collection_workflow import family_of
from shorttrip.strict_v4_reader import V4Reader

CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'
LEDGER = ROOT / 'collector_agent/memory/agent.sqlite3'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('smoke')
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    source,out=Path(args.smoke),Path(args.output)
    if out.exists():
        raise FileExistsError('preserve source readiness artifact')
    raw=source.read_bytes(); smoke=json.loads(raw)
    queue=smoke.get('gap_queue')
    if not isinstance(queue,dict) or not isinstance(queue.get('identity_resolution_workflow'),list):
        raise ValueError('identity workflow missing')
    db=sqlite3.connect(LEDGER.resolve().as_uri()+'?mode=ro',uri=True)
    statuses={family:status for family,status in db.execute('select family,status from sources')}
    db.close()
    reader=V4Reader(CATALOG); records=[]
    try:
        for job in queue['identity_resolution_workflow']:
            entity_id=job['entity_id']; record=reader.get(entity_id); sources={}
            for item in record['claims']:
                claim,evidence=item['payload'],item['evidence']
                url=claim.get('source_url') or evidence.get('source_url')
                if not isinstance(url,str) or not url:
                    continue
                try:
                    family=family_of(url)
                except ValueError:
                    continue
                entry=sources.setdefault(family,{'family':family,
                    'access_state':statuses.get(family,'unregistered'),
                    'source_ids':[], 'native_fields':[], 'licence_statuses':[],
                    'observed_at_present':False})
                for key,value in [('source_ids',claim.get('source_id')),
                                  ('native_fields',claim.get('native_field')),
                                  ('licence_statuses',evidence.get('licence_status'))]:
                    if value is not None and value not in entry[key]: entry[key].append(value)
                entry['observed_at_present'] |= bool(claim.get('observed_at') or evidence.get('observed_at'))
            records.append({'entity_id':entity_id,'city':record['city'],'kind':record['kind'],
                            'affected_tasks':job.get('affected_tasks',[]),
                            'historical_source_families':sorted(sources.values(),key=lambda x:x['family']),
                            'identity_verified':False,'source_selection_performed':False,
                            'request_authorized':False})
    finally:
        reader.close()
    result={'label':'engineering_source_readiness_not_dispatch',
            'smoke_sha256':hashlib.sha256(raw).hexdigest(),
            'catalog_sha256':hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
            'records':records,'source_access_retested':False,'network_requests':0,
            'frozen_cohort':False,'request_authorized':False}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'records':len(records),'source_families':len({s['family'] for r in records for s in r['historical_source_families']}),
                      'network_requests':0,'request_authorized':False}))


if __name__=='__main__':
    main()
