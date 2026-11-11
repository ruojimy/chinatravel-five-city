"""P21: DeepSeek-V4.1-Flash against the expanded sandbox with frozen P20 evidence.

Fixed-interface regression: explicit rooms fields, zero-cost guard, claims_reviewed,
reviewed duplicate aliases, field search, and no new live retrieval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p21_flash_fixed'
SECRETS = ROOT / '.secrets'
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.static_lookup import lookup  # noqa: E402
from shorttrip.expansion_contract import validate_record  # noqa: E402

CASES = ('D01', 'D02', 'D03', 'D04')
ACTION_RE = re.compile(r'^\s*\{.*\}\s*$', re.S)
MAX_RESULT_CHARS = 14000


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def save_new(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError('Preserve existing output: ' + str(p))
    save(p, obj)


def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def compact_json(value, limit=360):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return text if len(text) <= limit else text[:limit] + '…'


def compact_record(record, *, with_assertions=True):
    data = record.get('data') or {}
    keep = ('name', 'type', 'price', 'cuisine', 'opentime', 'endtime', 'recommendmintime',
            'recommendmaxtime', 'numbed', 'featurehoteltype', 'recommendedfood', 'lat', 'lon')
    digest = {
        'record_id': record.get('record_id'),
        'name': record.get('name'),
        'kind': record.get('kind'),
        'city': record.get('city'),
        'data': {k: data.get(k) for k in keep if data.get(k) is not None},
        'tags': [{'tag': t.get('tag'), 'value': t.get('value'), 'status': t.get('status')}
                 for t in record.get('tags', []) if t.get('value') is not None][:14],
    }
    if with_assertions:
        assertions = []
        for a in record.get('operator_assertions', [])[:10]:
            assertions.append({'field': a.get('field'), 'value': compact_json(a.get('value')),
                               'source_url': a.get('source_url'), 'observed_at': a.get('observed_at')})
        digest['operator_assertions'] = assertions
        digest['uncertainty_flags'] = record.get('uncertainty_flags', [])[:8]
        digest['trust_status'] = record.get('trust_status')
    return digest


def candidate_item(record, gate, *, tag_match=None):
    item = {'record': compact_record(record),
            'gate': {'planning_ready': gate.get('planning_ready'),
                     'blockers': gate.get('planning_blockers', [])[:8],
                     'missing': gate.get('missing_planning_fields', [])[:8],
                     'warnings': gate.get('warnings', [])[:6]}}
    if tag_match is not None:
        item['tag_match'] = bool(tag_match)
    return item


class Gateway:
    def __init__(self, protocol, case_id, stage, state):
        self.protocol = protocol
        self.case_id = case_id
        self.stage = stage
        self.state = state
        self.base = (ROOT / protocol['baseline']['catalog']).resolve()
        self.db = sqlite3.connect(self.base.as_uri() + '?mode=ro', uri=True)
        alias_doc = load(OUT / 'private/duplicate_aliases.json')
        self.alias_map = {p['alias_id']: p for p in alias_doc.get('reviewed_pairs', [])}
        self.rules = load(OUT / 'private/constraints.json')

    def close(self):
        self.db.close()

    def event_path(self, op):
        folder = OUT / 'events' / self.case_id
        folder.mkdir(parents=True, exist_ok=True)
        seq = len(list(folder.glob('*.json'))) + 1
        return folder / f'{seq:03d}_{op}.json'

    def claims(self):
        claims = []
        for path in sorted((OUT / 'overlay').glob('v*/claims.json')):
            claims.extend(load(path).get('claims', []))
        out = []
        for c in claims:
            pair = self.alias_map.get(c.get('entity_id'))
            if pair:
                c = dict(c)
                c['original_entity_id'] = c['entity_id']
                c['entity_id'] = pair['canonical_id']
            out.append(c)
        return out

    def canonical_id(self, entity_id):
        pair = self.alias_map.get(entity_id)
        return pair['canonical_id'] if pair else entity_id

    def canonical_record(self, record):
        pair = self.alias_map.get(record.get('record_id'))
        if not pair:
            return record
        canonical = self.entity(pair['canonical_id'])
        if canonical is None:
            return record
        canonical = dict(canonical)
        canonical['alias_of'] = pair['alias_name']
        canonical['alias_reason'] = pair['reason']
        return canonical

    def canonical_candidates(self, records):
        out, seen = [], set()
        for record in records:
            record = self.canonical_record(record)
            if record['record_id'] in seen:
                continue
            seen.add(record['record_id'])
            out.append(record)
        return out

    def entity(self, entity_id):
        entity_id = self.canonical_id(entity_id)
        row = self.db.execute('SELECT payload FROM records WHERE id=?', (entity_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def execute(self, req):
        args = req.get('args') or {}
        op = req.get('action')
        result, full, display = None, None, None
        if op == 'lookup':
            result = lookup(self.base, args['city'], args['kind'], tag=args.get('tag'),
                            limit=min(int(args.get('limit', 6)), 8))
            tag_map = {x['record']['record_id']: x.get('tag_match') for x in result['candidates']}
            records = self.canonical_candidates([x['record'] for x in result['candidates']])
            candidates = [{'record': r, 'gate': validate_record(r),
                           'tag_match': bool(tag_map.get(r['record_id'], any(tag_map.values())))} for r in records]
            full = {**result, 'candidates': candidates}
            display = {'operation': 'lookup', 'checked_at': result['checked_at'],
                       'requested_tag': result.get('requested_tag'),
                       'uncovered_query_tags': result.get('uncovered_query_tags'),
                       'candidates': [candidate_item(x['record'], x['gate'], tag_match=x.get('tag_match'))
                                      for x in candidates],
                       'network_calls': 0,
                       'note': '库内召回，不是已核实事实；已应用 reviewed duplicate alias；planning_ready=false 仅表示不能直接当硬事实。'}
        elif op == 'find_name':
            rows = self.db.execute(
                'SELECT payload FROM records WHERE city=? AND kind=? AND name LIKE ? ORDER BY name,id LIMIT 8',
                (args['city'], args['kind'], '%' + args['term'] + '%')).fetchall()
            records = self.canonical_candidates([json.loads(r[0]) for r in rows])
            full = {'records': records, 'match_method': 'literal name substring only; not verified identity'}
            display = {'operation': 'find_name', 'term': args['term'],
                       'match_method': 'literal name substring only; not verified identity',
                       'candidates': [candidate_item(r, validate_record(r)) for r in records],
                       'network_calls': 0}
        elif op == 'find_field':
            field_whitelist = {'restaurant': ('cuisine', 'recommendedfood'),
                               'accommodation': ('featurehoteltype', 'hotelname_en'),
                               'attraction': ('type',)}
            if args.get('field') not in field_whitelist.get(args.get('kind'), ()):
                raise ValueError('find_field not allowed for this kind/field')
            rows = self.db.execute(
                "SELECT payload FROM records WHERE city=? AND kind=? AND json_extract(payload, ?) LIKE ? "
                "ORDER BY name,id LIMIT 8",
                (args['city'], args['kind'], '$.data.' + args['field'], '%' + args['term'] + '%')).fetchall()
            records = self.canonical_candidates([json.loads(r[0]) for r in rows])
            full = {'records': records, 'field': args['field'], 'term': args['term'],
                    'match_method': 'literal JSON data field substring only; not a verified category or menu'}
            display = {'operation': 'find_field', 'field': args['field'], 'term': args['term'],
                       'match_method': 'literal JSON data field substring only; not a verified category or menu',
                       'candidates': [candidate_item(r, validate_record(r)) for r in records],
                       'network_calls': 0}
        elif op in ('detail', 'evidence'):
            requested = args['entity_id']
            record = self.entity(requested)
            if record is None:
                raise KeyError('Unknown entity id: ' + str(args.get('entity_id')))
            canonical = record.get('record_id')
            gate = validate_record(record)
            static = self.stage == 'static_first'
            claims = [] if static else [c for c in self.claims() if c.get('entity_id') == canonical]
            full = {'record': record, 'gate': gate, 'requested_entity_id': requested,
                    'canonical_entity_id': canonical, 'session_claims': claims,
                    'static_phase_hides_claims': static}
            claim_digest = []
            for c in claims:
                verdict = c.get('ingest_verdict') or {}
                claim_digest.append({
                    'claim_id': c.get('claim_id'), 'field': c.get('field'),
                    'value': compact_json(c.get('value')), 'unit': c.get('unit'),
                    'quote': (c.get('quote') or '')[:280],
                    'source_url': c.get('source_url'), 'retrieved_at': c.get('retrieved_at'),
                    'observed_at': c.get('observed_at'), 'source_published_at': c.get('source_published_at'),
                    'valid_until': c.get('valid_until'), 'context': c.get('context'),
                    'gate': {'status': verdict.get('status'),
                             'usable_as_hard_fact': verdict.get('usable_as_hard_fact'),
                             'usable_as_labelled_estimate': verdict.get('usable_as_labelled_estimate'),
                             'reasons': (verdict.get('checks') and
                                         [x for chk in verdict['checks'] if chk.get('claim_id') == c.get('claim_id')
                                          for x in chk.get('reasons', [])][:8]) or [],
                             'needs_user_confirmation': verdict.get('needs_user_confirmation')},
                    'binding_status': c.get('binding_status'),
                    'fact_scope': c.get('fact_scope'),
                })
            display = {'operation': op, 'record': compact_record(record), 'gate': gate,
                       'requested_entity_id': requested, 'canonical_entity_id': canonical,
                       'session_claims': claim_digest,
                       'note': ('静态阶段不返回会话claims；动态阶段再读。' if op == 'evidence' and static
                                else '原记录与隔离会话claims都只是引用范围，不自动成为硬事实。'
                                if op == 'evidence' else '未读取会话claims；如需动态证据请用evidence。')}
        else:
            raise ValueError('unknown action: ' + str(op))
        path = self.event_path(op)
        event = {'at': now(), 'case_id': self.case_id, 'stage': self.stage,
                 'sequence': int(path.stem.split('_')[0]),
                 'request': req, 'result': full}
        save_new(path, event)
        if display is not None:
            display['event_file'] = str(path.relative_to(ROOT))
        return result, display, path


def normalize_action(content):
    text = content.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('no JSON object in response')
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError('response JSON is not an object')
    action = obj.get('action')
    args = obj.get('args')
    if not isinstance(action, str) or action not in ('lookup', 'find_name', 'find_field', 'detail',
                                                     'evidence', 'submit'):
        raise ValueError('invalid action: ' + str(action))
    if not isinstance(args, dict):
        raise ValueError('args must be an object')
    return obj


def _is_free_value(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    if isinstance(value, dict):
        return any(isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0 for v in value.values())
    return False


def validate_submit(case_id, stage, answer, gateway):
    if not isinstance(answer, dict):
        raise ValueError('answer must be an object')
    required = ('query_tags', 'proposed_plan', 'fact_claims', 'status', 'unresolved', 'reasoning_summary')
    missing = [k for k in required if k not in answer]
    if missing:
        raise ValueError('answer missing: ' + ', '.join(missing))
    plan = answer['proposed_plan']
    if not isinstance(plan, dict) or not isinstance(plan.get('itinerary'), list) or not plan['itinerary']:
        raise ValueError('proposed_plan.itinerary must be a non-empty list')
    allowed = {'start', 'end', 'attraction', 'lunch', 'dinner', 'breakfast', 'accommodation'}
    activities = []
    for day in plan['itinerary']:
        if not isinstance(day, dict) or not isinstance(day.get('activities'), list) or not day['activities']:
            raise ValueError('each day needs activities')
        for a in day['activities']:
            activities.append(a)
            if a.get('type') not in allowed:
                raise ValueError('invalid activity type: ' + str(a.get('type')))
            for key in ('start_time', 'end_time'):
                if not isinstance(a.get(key), str) or not re.fullmatch(r'\d{2}:\d{2}', a[key]):
                    raise ValueError('invalid ' + key + ' in activity')
            if not isinstance(a.get('position'), str) or not a['position'].strip():
                raise ValueError('activity position required')
            entity_id = a.get('entity_id')
            if entity_id:
                record = gateway.entity(entity_id)
                if record is None:
                    raise ValueError('unknown entity_id in plan: ' + str(entity_id))
                if record.get('city') != plan.get('target_city'):
                    raise ValueError('entity city mismatch: ' + str(entity_id))
                kind_map = {'attraction': 'attraction', 'lunch': 'restaurant', 'dinner': 'restaurant',
                            'accommodation': 'accommodation'}
                expected = kind_map.get(a['type'])
                if expected and record.get('kind') != expected:
                    raise ValueError(f'entity kind mismatch for {a["type"]}: {entity_id}')
                if a['position'] != record.get('name'):
                    raise ValueError('position must equal catalog name for grounded activity; '
                                     'use entity_id=null for start/end anchors: ' + str(entity_id))
            if not isinstance(a.get('transports', []), list):
                raise ValueError('transports must be a list')

    rule = gateway.rules[case_id]
    hotels = [a for a in activities if a.get('type') == 'accommodation']
    if rule.get('hotel_nights'):
        if len(hotels) != 1:
            raise ValueError(f'hotel_nights={rule["hotel_nights"]} requires exactly one accommodation activity; '
                             f'got {len(hotels)}')
        hotel = hotels[0]
        if hotel.get('rooms') != rule.get('rooms'):
            raise ValueError(f'accommodation rooms must be {rule.get("rooms")}; got {hotel.get("rooms")}')
        if rule.get('single_beds') == 2:
            room_type = hotel.get('room_type') if isinstance(hotel.get('room_type'), str) else ''
            twin = hotel.get('single_beds') == 2 or any(x in room_type.lower() for x in ('twin', '双床', '两张单人床'))
            if not twin:
                raise ValueError('query requires two single beds; set single_beds=2 or an explicit twin room_type')
    elif hotels:
        raise ValueError('query has no hotel night; accommodation activity not allowed')

    claims = gateway.claims()
    hard_free = {c['entity_id'] for c in claims
                 if c.get('field') == 'price' and (c.get('ingest_verdict') or {}).get('usable_as_hard_fact')
                 and _is_free_value(c.get('value'))}
    zeros = []
    for a in activities:
        for key in ('cost', 'price'):
            if a.get(key) == 0 and a.get('entity_id') not in hard_free:
                zeros.append({'type': a.get('type'), 'key': key, 'entity_id': a.get('entity_id')})
        for t in a.get('transports', []):
            for key in ('cost', 'price'):
                if t.get(key) == 0 and a.get('entity_id') not in hard_free:
                    zeros.append({'type': f'transport:{t.get("mode")}', 'key': key, 'entity_id': a.get('entity_id')})
    if zeros:
        raise ValueError('zero cost/price requires usable_as_hard_fact free evidence; use null instead: '
                         + json.dumps(zeros, ensure_ascii=False))

    if stage in ('dynamic_first', 'revised'):
        selected = {a.get('entity_id') for a in activities if a.get('entity_id')}
        available = [c for c in claims if c.get('entity_id') in selected]
        reviewed = answer.get('claims_reviewed')
        if not isinstance(reviewed, list):
            raise ValueError('dynamic/revised answer requires claims_reviewed list')
        available_ids = {c['claim_id'] for c in available}
        reviewed_ids = {r.get('claim_id') for r in reviewed if isinstance(r, dict)}
        missing_reviews = sorted(available_ids - reviewed_ids)
        if missing_reviews:
            raise ValueError('claims_reviewed missing available claims: ' + ', '.join(missing_reviews))
        extras = sorted(reviewed_ids - available_ids)
        if extras and stage == 'dynamic_first':
            raise ValueError('claims_reviewed contains claims not available for selected entities: ' + ', '.join(extras))
        dispositions = {'used', 'not_used', 'not_relevant'}
        for r in reviewed:
            if not isinstance(r, dict) or r.get('disposition') not in dispositions:
                raise ValueError('each claims_reviewed item needs disposition used/not_used/not_relevant')
        refs = set()
        for c in answer.get('fact_claims') or []:
            refs.update(x for x in (c.get('evidence_refs') or []) if isinstance(x, str))
        for c in answer.get('plan_changes') or []:
            refs.update(x for x in (c.get('evidence_refs') or []) if isinstance(x, str))
        used = {r['claim_id'] for r in reviewed if r.get('disposition') == 'used'}
        uncited = sorted(used - refs)
        if uncited:
            raise ValueError('claims marked used are not cited in fact_claims/plan_changes: ' + ', '.join(uncited))

        events = [load(p) for p in sorted((OUT / 'events' / case_id).glob('*.json'))]
        last_submit = max((i for i, e in enumerate(events) if e['request'].get('action') == 'submit'), default=-1)
        phase = events[last_submit + 1:]
        read = {gateway.canonical_id(e['request'].get('args', {}).get('entity_id'))
                for e in phase if e['request'].get('action') == 'evidence'}
        must_read = {c['entity_id'] for c in available}
        unread = sorted(must_read - read)
        if unread:
            raise ValueError('dynamic phase must read evidence for every selected entity with claims; missing: '
                             + ', '.join(unread))

    if stage == 'static_first':
        ops = [load(p)['request']['action'] for p in sorted((OUT / 'events' / case_id).glob('*.json'))]
        if not any(x in ('lookup', 'find_name', 'find_field') for x in ops):
            raise ValueError('must call lookup, find_name or find_field before static_first')
    return True


class Session:
    def __init__(self, case_id, stage, revision_text=None, max_steps=18):
        self.case_id = case_id
        self.stage = stage
        self.max_steps = max_steps
        self.protocol = load(OUT / 'public/protocol.json')
        self.queries = {q['case_id']: q for q in load(OUT / 'public/queries.json')}
        self.query = self.queries[case_id]
        self.state_path = OUT / 'agent_state' / f'{case_id}.json'
        self.system_prompt = (OUT / 'public/participant_prompt_v2.txt').read_text(encoding='utf-8')
        if self.state_path.exists():
            self.state = load(self.state_path)
        else:
            self.state = {'case_id': case_id, 'stage': stage, 'messages': [], 'usage': {},
                          'created_at': now(), 'updated_at': now(), 'status': {}, 'counts': {},
                          'phase_steps': {}, 'model': self.protocol['participant']['model']}
        self.messages = self.state['messages']
        self.usage = self.state.setdefault('usage', {})
        for _key in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'calls'):
            self.usage.setdefault(_key, 0)
        self.counts = self.state.setdefault('counts', {})
        if not self.messages:
            user = ('案例 ' + case_id + '（' + self.query['city'] + '），请完成下面的旅行请求。\n\n'
                    + self.query['query'] + '\n\n'
                    + '先用 lookup / find_name / find_field 做真实库内候选检索，再决定。需要核对的实体用 evidence。'
                    + '本轮证据已冻结，没有 request_live；静态阶段 evidence 不返回 session claims。'
                    + '完成调研后提交 static_first，然后停止；根代理会在下一阶段提供冻结证据。')
            self.messages.extend([{'role': 'system', 'content': self.system_prompt},
                                  {'role': 'user', 'content': user}])
        elif stage == 'dynamic':
            if not self.state.get('status', {}).get('static_first'):
                raise SystemExit('static_first not submitted yet')
            self.messages.append({'role': 'user', 'content': self._dynamic_message()})
        elif stage == 'revised':
            if not self.state.get('status', {}).get('dynamic_first'):
                raise SystemExit('dynamic_first not submitted yet')
            if not revision_text:
                raise SystemExit('revision text required')
            self.messages.append({'role': 'user', 'content': revision_text})
        self.state['stage'] = stage
        self.stage_start = len(self.messages)
        self.submitted = False

    def _dynamic_message(self):
        claims = sum(len(load(p).get('claims', [])) for p in sorted((OUT / 'overlay').glob('v*/claims.json')))
        versions = [p.name for p in sorted((OUT / 'overlay').glob('v*'))]
        return (f'动态阶段（冻结证据）：会话 overlay {versions} 共 {claims} 条 claims；本轮没有新的 live 检索。\n'
                '这些 claims 仍可能是 unverified / scoped reference，不等于硬事实。\n'
                '请对 static_first 里实际选中的、且有 claims 的实体调用 evidence，读取 session_claims；'
                '在 claims_reviewed 中逐条列出所有可用 claims（used / not_used / not_relevant + 原因）；'
                '标记 used 的 claim 必须出现在 fact_claims 或 plan_changes 的 evidence_refs 中。'
                '然后提交 dynamic_first：保留 static_first 不被覆盖，逐条说明哪些安排因新证据改变、哪些没有改变；'
                '未知价格/路线继续 null。')

    def save_state(self):
        self.state['messages'] = self.messages
        self.state['usage'] = self.usage
        self.state['counts'] = self.counts
        self.state['updated_at'] = now()
        save(self.state_path, self.state)

    def api(self, messages):
        key = (SECRETS / 'deepseek.key').read_text(encoding='ascii').strip()
        p = self.protocol['participant']
        payload = {'model': p['model'], 'messages': messages, 'temperature': p.get('temperature', 0),
                   'max_tokens': p.get('max_output_tokens', 8192),
                   'response_format': {'type': 'json_object'}}
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        last_error = None
        for attempt in range(5):
            try:
                t0 = time.time()
                request = urllib.request.Request(
                    p['endpoint'], data=body,
                    headers={'Authorization': 'Bearer ' + key,
                             'Content-Type': 'application/json', 'Connection': 'close'})
                with urllib.request.urlopen(request, timeout=300) as response:
                    data = json.loads(response.read().decode('utf-8'))
                usage = data.get('usage') or {}
                self.usage['prompt_tokens'] += int(usage.get('prompt_tokens') or 0)
                self.usage['completion_tokens'] += int(usage.get('completion_tokens') or 0)
                self.usage['total_tokens'] += int(usage.get('total_tokens') or 0)
                self.usage['calls'] += 1
                choice = data['choices'][0]
                return (choice['message'].get('content') or '', choice.get('finish_reason'),
                        round(time.time() - t0, 2), data.get('model'))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8', errors='replace')[:500]
                last_error = f'HTTP {exc.code}: {detail}'
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f'{type(exc).__name__}: {exc}'
                time.sleep(4 * (attempt + 1))
        raise RuntimeError('DeepSeek call failed: ' + str(last_error))

    def run(self):
        gateway = Gateway(self.protocol, self.case_id, self.stage, self.state)
        phase_steps = len(list((OUT / 'logs').glob(f'{self.case_id}_{self.stage}_*.json')))
        format_errors = 0
        try:
            while phase_steps < self.max_steps:
                phase_steps += 1
                self.state['phase_steps'][self.stage] = phase_steps
                content, finish_reason, latency, model = self.api(self.messages)
                raw_log = {'at': now(), 'case': self.case_id, 'stage': self.stage,
                           'step': phase_steps, 'latency_s': latency, 'finish_reason': finish_reason,
                           'model': model, 'content': content,
                           'usage': dict(self.usage)}
                save_new(OUT / 'logs' / f'{self.case_id}_{self.stage}_{phase_steps:02d}.json', raw_log)
                if finish_reason == 'length':
                    self.messages.append({'role': 'assistant', 'content': content[:2000]})
                    self.messages.append({'role': 'user', 'content': 'OUTPUT_TRUNCATED：上次输出被截断。'
                                          '请压缩 unresolved/fact_claims/说明文字，重新输出完整JSON，只保留当前动作。'})
                    continue
                self.messages.append({'role': 'assistant', 'content': content})
                try:
                    req = normalize_action(content)
                except Exception as exc:  # noqa: BLE001
                    format_errors += 1
                    if format_errors > 3:
                        raise
                    self.messages.append({'role': 'user', 'content': 'FORMAT_ERROR：' + str(exc)
                                          + '。请只输出一个符合协议的JSON对象。'})
                    self.save_state()
                    continue
                action = req['action']
                args = req['args']
                if args.get('case_id') not in (None, self.case_id):
                    self.messages.append({'role': 'user', 'content': 'CASE_ERROR：case_id 必须是 '
                                          + self.case_id + '。'})
                    self.save_state()
                    continue
                if action == 'submit':
                    stage = args.get('stage')
                    if stage != self.stage:
                        self.messages.append({'role': 'user', 'content': f'STAGE_ERROR：当前阶段只能提交 {self.stage}，'
                                              f'收到 {stage}。'})
                        self.save_state()
                        continue
                    try:
                        validate_submit(self.case_id, stage, args.get('answer'), gateway)
                    except Exception as exc:  # noqa: BLE001
                        self.messages.append({'role': 'user', 'content': 'SUBMIT_REJECTED：' + str(exc)
                                              + '。请修正后再次 submit，不要覆盖已提交文件。'})
                        self.save_state()
                        continue
                    plan_path = OUT / 'plans' / self.case_id / (stage + '.json')
                    if plan_path.exists():
                        self.messages.append({'role': 'user', 'content': 'SUBMIT_REJECTED：该 stage 已存在，不能覆盖。'})
                        self.save_state()
                        continue
                    answer = args['answer']
                    answer['_meta'] = {'case_id': self.case_id, 'stage': stage, 'model': model,
                                       'submitted_at': now(), 'agent_usage': dict(self.usage),
                                       'phase_steps': phase_steps}
                    save_new(plan_path, answer)
                    submit_folder = OUT / 'events' / self.case_id
                    submit_folder.mkdir(parents=True, exist_ok=True)
                    submit_seq = len(list(submit_folder.glob('*.json'))) + 1
                    submit_path = submit_folder / f'{submit_seq:03d}_submit.json'
                    save_new(submit_path, {'at': now(), 'case_id': self.case_id, 'stage': stage,
                                           'sequence': submit_seq,
                                           'request': {'action': 'submit', 'args': {'stage': stage, 'answer': answer}},
                                           'result': {'submitted': True, 'plan': str(plan_path.relative_to(ROOT)),
                                                      'no_checker_feedback': True}})
                    self.state['status'][stage] = {'submitted_at': now(), 'plan': str(plan_path.relative_to(ROOT)),
                                                   'event': str(submit_path.relative_to(ROOT)),
                                                   'usage': dict(self.usage), 'steps': phase_steps}
                    self.submitted = True
                    self.save_state()
                    print(json.dumps({'case': self.case_id, 'stage': stage, 'status': 'submitted',
                                      'plan': str(plan_path), 'usage': self.usage, 'steps': phase_steps},
                                     ensure_ascii=False))
                    return 0
                op_counts = self.counts.setdefault(self.stage, {})
                op_counts[action] = op_counts.get(action, 0) + 1
                limits = {'lookup': 8, 'find_name': 8, 'find_field': 8, 'detail': 6, 'evidence': 10}
                if action in limits and op_counts[action] > limits[action]:
                    self.messages.append({'role': 'user', 'content': f'BUDGET：{action} 已超过本阶段上限。'})
                    self.save_state()
                    continue
                try:
                    result, display, event_path = gateway.execute(req)
                except Exception as exc:  # noqa: BLE001
                    self.messages.append({'role': 'user', 'content': 'TOOL_ERROR：' + str(exc)})
                    self.save_state()
                    continue
                text = json.dumps(display, ensure_ascii=False)
                if len(text) > MAX_RESULT_CHARS:
                    text = text[:MAX_RESULT_CHARS] + '…[TRUNCATED; full result in event file]'
                self.messages.append({'role': 'user', 'content': 'TOOL_RESULT：' + text})
                self.save_state()
            self.state['status'][self.stage + '_incomplete'] = {'at': now(), 'steps': phase_steps}
            self.save_state()
            print(json.dumps({'case': self.case_id, 'stage': self.stage, 'status': 'max_steps',
                              'usage': self.usage, 'steps': phase_steps}, ensure_ascii=False))
            return 2
        finally:
            gateway.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True, choices=CASES)
    parser.add_argument('--stage', required=True, choices=('static', 'dynamic', 'revised'))
    parser.add_argument('--revision', help='revision instruction file (for revised stage)')
    parser.add_argument('--max-steps', type=int, default=18)
    args = parser.parse_args()
    stage_map = {'static': 'static_first', 'dynamic': 'dynamic_first', 'revised': 'revised'}
    revision_text = None
    if args.stage == 'revised':
        if not args.revision:
            raise SystemExit('--revision required for revised stage')
        rev = load(args.revision)
        revision_text = rev.get('participant_instruction') or rev.get('instruction')
        if not revision_text:
            raise SystemExit('revision file needs participant_instruction')
    session = Session(args.case, stage_map[args.stage], revision_text=revision_text,
                      max_steps=args.max_steps)
    raise SystemExit(session.run())


if __name__ == '__main__':
    main()
