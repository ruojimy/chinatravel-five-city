"""Verify report completeness against actual saved plans, not generated fixtures."""
import hashlib
import json
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reproduction'


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.split = None
        self.capture = None
        self.json_text = {}
        self.counts = {s: {'activities': 0, 'transports': 0} for s in ('easy', 'medium', 'human')}
        self.totals = {}
        self.days = {s: {} for s in self.counts}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and attrs.get('id') in self.counts:
            self.split = attrs['id']
            assert self.split not in self.totals, 'Duplicate case section'
            self.totals[self.split] = attrs['data-total-cost']
        if self.split:
            if 'data-day' in attrs:
                day = attrs['data-day']
                assert day not in self.days[self.split], 'Duplicate day section'
                self.days[self.split][day] = attrs['data-day-cost']
            for attr, key in [('data-activity', 'activities'), ('data-transport', 'transports')]:
                if attr in attrs:
                    self.counts[self.split][key] += 1
        if tag == 'pre' and attrs.get('id', '').startswith('json-'):
            self.capture = attrs['id'][5:]
            self.json_text[self.capture] = ''

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.capture = None

    def handle_data(self, data):
        if self.capture:
            self.json_text[self.capture] += data


def verify_case(plan, rendered_counts, rendered_total, rendered_day_costs):
    itinerary = plan.get('itinerary', [])
    activities = [a for d in itinerary for a in d.get('activities', [])]
    expected_counts = {'activities': len(activities),
                       'transports': sum(len(a.get('transports', [])) for a in activities)}
    assert rendered_counts == expected_counts, 'Missing or duplicate activities/transports'
    expected_days = {}
    for day in itinerary:
        cost = sum((Decimal(str(a.get('cost', 0))) + sum((Decimal(str(t.get('cost', 0)))
                    for t in a.get('transports', [])), Decimal(0))
                    for a in day.get('activities', [])), Decimal(0))
        expected_days[str(day['day'])] = cost
    assert set(rendered_day_costs) == set(expected_days), 'Missing or duplicate days'
    for key, cost in expected_days.items():
        assert abs(Decimal(rendered_day_costs[key]) - cost) < Decimal('0.000001'), 'Wrong daily cost'
    total = sum(expected_days.values(), Decimal(0))
    assert abs(Decimal(rendered_total) - total) < Decimal('0.000001'), 'Wrong case total'
    return total


def main():
    status = json.loads((OUT / 'run_status.json').read_text(encoding='utf-8'))
    summary = json.loads((OUT / 'report_verification.json').read_text(encoding='utf-8'))
    report = (OUT / 'itineraries.html').read_text(encoding='utf-8')
    bundle = json.loads((OUT / 'all_results.json').read_text(encoding='utf-8'))
    parser = ReportParser()
    parser.feed(report)
    from prepare import SAMPLES
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    expected = {(s, uid) for s, uid in SAMPLES.items()}
    assert {(x['split'], x['uid']) for x in manifest['samples']} == expected
    assert len(manifest['samples']) == len(summary) == len(bundle['cases']) == 3
    assert {(x['split'], x['uid']) for x in summary} == expected
    assert {(x['split'], x['uid']) for x in bundle['cases']} == expected
    assert set(parser.totals) == set(SAMPLES)
    results = []
    for sample in manifest['samples']:
        split, uid = sample['split'], sample['uid']
        item = next(x for x in summary if x['split'] == split)
        assert item['has_result'], f'Missing actual result: {split}'
        assert status['cases'][split]['run_exit_code'] == 0, f'Agent failed: {split}'
        assert status['cases'][split]['eval_exit_code'] == 0, f'Evaluator failed: {split}'
        plan = json.loads((ROOT / 'results' / status['method'] / f'{uid}.json').read_text(encoding='utf-8'))
        assert json.loads(parser.json_text[split]) == plan, f'Embedded JSON differs: {split}'
        assert next(c['plan'] for c in bundle['cases'] if c['split'] == split) == plan
        total = verify_case(plan, parser.counts[split], parser.totals[split], parser.days[split])
        assert abs(total - Decimal(str(item['cost']))) < Decimal('0.000001')
        assert f'¥{total:,.2f}' in report
        results.append({'split': split, 'json_exact': True, 'all_activities_rendered': True,
                        'all_transports_rendered': True, 'cost_verified': str(total)})
    core = json.loads((OUT / 'core_checksums.json').read_text())
    assert all(hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == h for f, h in core.items())
    # Check actual saved credentials without ever printing their values.
    for path in (ROOT.parent / '.env.local', ROOT / '.env.local', OUT / '.env.local'):
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.partition('=')
                if sep and 'API_KEY' in key:
                    secret = value.strip().strip('\"\'')
                    if len(secret) > 10:
                        for artifact in list(OUT.glob('*.html')) + list(OUT.glob('*.json')) + list((OUT / 'logs').glob('*.log')):
                            assert secret not in artifact.read_text(encoding='utf-8', errors='replace'), 'Credential leaked into an output artifact'
    result = {'reports': results, 'original_core_files_unchanged': len(core),
              'credential_scan': 'passed', 'browser_visual_qa': 'unavailable: no enabled browser surface'}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
