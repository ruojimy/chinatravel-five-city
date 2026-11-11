"""Append a validated research-session evidence version; never renew fact clocks."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.expansion_contract import validate_inline_claim
from shorttrip.freshness import reconcile, utcnow
from shorttrip.travel_catalog import TravelCatalog

OUT = ROOT / 'results/p19_query_to_plan'

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def main():
    request = load(Path(sys.argv[1]))
    protocol = load(OUT / 'public/protocol.json')
    base = ROOT / protocol['baseline']['catalog']
    assert hashlib.sha256(base.read_bytes()).hexdigest() == protocol['baseline']['sha256']
    registry = load(ROOT / 'data/travel_source_registry.json')
    # Explicit operator entries aid provenance classification only. They do not
    # grant reuse rights, entity verification or fact observation timestamps.
    registry.update(request.get('registry_additions', {}))
    db = sqlite3.connect(base.resolve().as_uri() + '?mode=ro', uri=True)
    prior = []
    for p in sorted((OUT / 'overlay').glob('v*/claims.json')):
        prior.extend(load(p)['claims'])
    ids = {c['claim_id'] for c in prior}
    additions = []
    for c in request['claims']:
        assert c['claim_id'] not in ids
        assert db.execute('SELECT 1 FROM records WHERE id=?', (c['entity_id'],)).fetchone(), c['entity_id']
        gate = validate_inline_claim(c)
        if not gate['ok']:
            raise ValueError(gate)
        verdict = reconcile([x for x in prior + additions if x['entity_id'] == c['entity_id'] and x['field'] == c['field']] + [c],
                            c['field'], registry, context=c['context'], entity_id=c['entity_id'])
        c = {**c, 'ingest_verdict': verdict, 'new_native_projection': False}
        additions.append(c)
        ids.add(c['claim_id'])
    db.close()
    n = len(list((OUT / 'overlay').glob('v*'))) + 1
    folder = OUT / 'overlay' / f'v{n:03d}'
    folder.mkdir(parents=True, exist_ok=False)
    packet = {'at': utcnow(), 'version': f'v{n:03d}', 'baseline': protocol['baseline'],
              'claims': additions, 'record_count_unchanged': True,
              'note': 'Delta evidence includes quarantined references; original business values are not silently overwritten.'}
    (folder / 'claims.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    cat = TravelCatalog(folder / 'claims.sqlite3')
    try:
        for c in prior + additions:
            cat.add_claim(c)
    finally:
        cat.close()
    receipt = {'at': utcnow(), 'version': packet['version'], 'new_claims': len(additions),
               'cumulative_claims': len(prior) + len(additions),
               'corroborated_new_claims': sum(c['ingest_verdict']['usable_as_hard_fact'] for c in additions),
               'gates': {c['claim_id']: c['ingest_verdict']['status'] for c in additions},
               'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()},
               'base_catalogue_modified': False, 'source_clock_renewed': False}
    (folder / 'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'current_overlay.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'files'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
