"""Audited, session-local tools for the query-to-plan LLM pilot. No live network."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.static_lookup import lookup
from shorttrip.expansion_contract import validate_record
from shorttrip.freshness import utcnow

OUT = ROOT / 'results/p19_query_to_plan'

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def save(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError('Preserve first output: ' + str(p))
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    req = read(Path(sys.argv[1]))
    protocol = read(OUT / 'public/protocol.json')
    cid, op = req['case_id'], req['operation']
    assert cid in ('D01', 'D02'), 'unknown case'
    base = ROOT / protocol['baseline']['catalog']
    db = sqlite3.connect(base.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        if op == 'lookup':
            result = lookup(base, req['city'], req['kind'], tag=req.get('tag'), limit=min(req.get('limit', 6), 8))
        elif op == 'find_name':
            rows = db.execute('SELECT payload FROM records WHERE city=? AND kind=? AND name LIKE ? ORDER BY name,id LIMIT 8',
                              (req['city'], req['kind'], '%' + req['term'] + '%'))
            result = {'candidates': [{'record': r, 'gate': validate_record(r)} for r in (json.loads(x[0]) for x in rows)],
                      'match_method': 'literal name substring only; not verified identity', 'network_calls': 0}
        elif op in ('detail', 'evidence'):
            row = db.execute('SELECT payload FROM records WHERE id=?', (req['entity_id'],)).fetchone()
            if not row:
                raise KeyError('Unknown entity id')
            record = json.loads(row[0])
            result = {'record': record, 'gate': validate_record(record), 'network_calls': 0}
            if op == 'evidence':
                result['session_claims'] = []
                for p in sorted((OUT / 'overlay').glob('v*/claims.json')):
                    result['session_claims'].extend(c for c in read(p)['claims'] if c['entity_id'] == req['entity_id'])
                result['note'] = 'Original operator assertions and quarantined session claims are scoped references, not automatically hard facts.'
        elif op == 'request_live':
            assert len(req['requests']) <= 8
            result = {'status': 'queued_for_normal_live_retrieval', 'requests': req['requests'],
                      'note': 'Orchestrator executes actual allowed search/open, preserves raw response, applies source-pause and evidence gates.'}
        elif op == 'submit':
            assert req['stage'] in ('static_first', 'dynamic_first', 'revised')
            answer = req['answer']
            assert all(k in answer for k in ('query_tags', 'proposed_plan', 'fact_claims', 'status', 'unresolved', 'reasoning_summary'))
            save(OUT / 'plans' / cid / (req['stage'] + '.json'), answer)
            result = {'submitted': True, 'stage': req['stage'], 'no_checker_feedback': True}
        else:
            raise ValueError('unknown operation')
    finally:
        db.close()
    log = OUT / 'events' / cid
    log.mkdir(parents=True, exist_ok=True)
    seq = len(list(log.glob('*.json'))) + 1
    event = {'at': utcnow(), 'case_id': cid, 'sequence': seq, 'request': req, 'result': result}
    save(log / f'{seq:03d}_{op}.json', event)
    # Full evidence stays in the event; display a bounded candidate digest.
    display = result
    if 'candidates' in result:
        display = {k: v for k, v in result.items() if k != 'candidates'}
        display['candidates'] = [{'record_id': x['record']['record_id'], 'name': x['record']['name'],
            'kind': x['record']['kind'], 'data': x['record']['data'], 'tags': x['record']['tags'],
            'gate': x['gate'], 'operator_reference_count': len(x['record'].get('operator_assertions', []))}
            for x in result['candidates']]
    print(json.dumps({'event_file': str(log / f'{seq:03d}_{op}.json'), 'result': display}, ensure_ascii=False))

if __name__ == '__main__':
    main()
