"""Build literal-quote claims from saved live pages. Root-reviewed specs, exact match enforced."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p20_deepseek_dynamic_sandbox'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def main():
    specs = load(OUT / 'live/claim_specs.json')['claims']
    claims, registry = [], {}
    for spec in specs:
        packet_path = OUT / 'live' / spec['packet']
        packet = load(packet_path)
        quote = spec['quote']
        assert quote in packet['text'], ('quote not found', spec['source_id'], quote[:80])
        claim_id = f"p20:{spec['case_id']}:{len(claims)+1:02d}:{spec['field']}"
        source_id = spec['source_id']
        registry.setdefault(source_id, {
            'name': spec.get('source_name', source_id),
            'authority': spec.get('authority', 'structured_provider'),
            'independence_group': spec.get('independence_group', source_id),
            'allowed_hosts': spec['allowed_hosts'],
            'supports': spec['supports'],
        })
        for field in spec['supports']:
            if field not in registry[source_id]['supports']:
                registry[source_id]['supports'].append(field)
        claim = {
            'claim_id': claim_id,
            'case_id': spec['case_id'],
            'entity_id': spec['entity_id'],
            'evidence_id': claim_id + ':evidence',
            'field': spec['field'],
            'value': spec['value'],
            'unit': spec.get('unit'),
            'quote': quote,
            'source_id': source_id,
            'source_url': packet['final_url'],
            'raw_text': packet['text'],
            'raw_sha256': hashlib.sha256(packet['text'].encode('utf-8')).hexdigest(),
            'observed_at': spec.get('observed_at'),
            'source_updated_at': spec.get('source_updated_at'),
            'source_published_at': spec.get('source_published_at'),
            'retrieved_at': packet['at'],
            'valid_until': None,
            'context': spec.get('context', {'travel_date': '2026-10-24', 'party_size': 2}),
            'authority': spec.get('authority', 'structured_provider'),
            'licence_status': 'research_read_only_redistribution_unverified',
            'entity_verified': False,
            'extraction_verified': True,
            'binding_status': spec.get('binding_status',
                                       'candidate_association_only; current original-entity match not certified'),
            'representation': 'web_tool_text',
            'packet': 'live/' + spec['packet'],
            'fact_scope': spec.get('fact_scope'),
            'source_issue_literal': spec.get('source_issue_literal'),
        }
        if spec.get('coverage_dates'):
            claim['coverage_dates'] = spec['coverage_dates']
        claims.append(claim)
    out = OUT / 'live/ingest_request_001.json'
    if out.exists():
        raise FileExistsError('Preserve first extraction: ' + str(out))
    out.write_text(json.dumps({'claims': claims, 'registry_additions': registry},
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'claims': len(claims), 'sources': len(registry),
                      'out': str(out.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
