"""Fetch one public live page verbatim, with pause-ledger enforcement and no retries."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p20_deepseek_dynamic_sandbox'
LEDGER = OUT / 'live/source_pauses.json'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ledger():
    if LEDGER.exists():
        return load(LEDGER)
    return {'at': now(), 'paused_hosts': [], 'blocked_tasks': [],
            'note': 'A failed host is paused with zero retries; no alternate-domain bypass.'}


def host_matches(host, paused):
    return host == paused or host.endswith('.' + paused) or paused.endswith('.' + host)


def add_pause(host, reason, url):
    data = ledger()
    if not any(host_matches(host, p['host']) for p in data.get('paused_hosts', [])):
        data.setdefault('paused_hosts', []).append({'host': host, 'reason': reason,
                                                    'url': url, 'at': now(), 'retries': 0})
        data['at'] = now()
        save(LEDGER, data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--out', required=True, help='open_XXX.json')
    parser.add_argument('--case', required=True)
    parser.add_argument('--purpose', default='')
    args = parser.parse_args()
    host = urlparse(args.url).hostname or ''
    data = ledger()
    for pause in data.get('paused_hosts', []):
        if host_matches(host, pause['host']):
            print(json.dumps({'error': 'source_paused', 'host': host, 'pause': pause}, ensure_ascii=False))
            return 3
    if len(list((OUT / 'live').glob('open_*.json'))) >= 24:
        print(json.dumps({'error': 'open_budget_exhausted', 'max': 24}, ensure_ascii=False))
        return 4
    target = OUT / 'live' / args.out
    if target.exists():
        print(json.dumps({'error': 'preserve_existing_packet', 'path': str(target)}, ensure_ascii=False))
        return 5
    request = urllib.request.Request(args.url, headers={
        'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6'})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = response.read(5_500_000)
            charset = response.headers.get_content_charset()
            status = response.status
            final_url = response.geturl()
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        packet = {'at': now(), 'case': args.case, 'url': args.url, 'purpose': args.purpose,
                  'status': exc.code, 'error': 'http_error', 'body_head': exc.read(2000).decode('utf-8', 'replace')}
        save(target.with_suffix('.failed.json'), packet)
        if exc.code in (403, 404, 410, 429):
            add_pause(host, f'http_{exc.code}', args.url)
        print(json.dumps({'error': 'http_error', 'status': exc.code, 'host': host}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001
        packet = {'at': now(), 'case': args.case, 'url': args.url, 'purpose': args.purpose,
                  'error': f'{type(exc).__name__}: {exc}'}
        save(target.with_suffix('.failed.json'), packet)
        add_pause(host, f'{type(exc).__name__}', args.url)
        print(json.dumps({'error': f'{type(exc).__name__}: {exc}', 'host': host}, ensure_ascii=False))
        return 1
    text = None
    for encoding in (charset, 'utf-8', 'gb18030', 'latin-1'):
        if not encoding:
            continue
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = raw.decode('utf-8', 'replace')
    packet = {'at': now(), 'case': args.case, 'url': args.url, 'final_url': final_url,
              'purpose': args.purpose, 'status': status, 'content_type': headers.get('content-type'),
              'headers_subset': {k: headers.get(k) for k in ('content-type', 'last-modified', 'date', 'cache-control')},
              'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
              'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
              'text': text}
    save(target, packet)
    print(json.dumps({'saved': str(target.relative_to(ROOT)), 'status': status, 'bytes': len(raw),
                      'text_chars': len(text), 'final_url': final_url}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
