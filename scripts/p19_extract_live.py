"""Root-reviewed literal extraction for the finite P19 search response packets."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p19_query_to_plan'

def main():
    claims, registry = [], {}
    def source(packet, url):
        d = json.loads((OUT / 'live' / packet).read_text(encoding='utf-8'))
        parts = d['result'].split('--------------------------------------------------------------------------------\n')
        matches = [s for s in parts if url in s.split('\n')[0]]
        assert len(matches) == 1, (packet, url)
        return matches[0], d['ended_at'].replace(' UTC', '+00:00').replace(' ', 'T', 1)
    def add(cid, entity, field, value, packet, url, sid, authority, quote, **extra):
        raw, at = source(packet, url)
        assert quote in raw, (sid, field)
        claim_id = f'p19:{cid}:{len(claims)+1:02d}:{field}'
        registry.setdefault(sid, {'name': sid, 'authority': authority, 'independence_group': sid,
                                  'allowed_hosts': [url.split('/')[2]], 'supports': []})
        if field not in registry[sid]['supports']:
            registry[sid]['supports'].append(field)
        claim = {'claim_id': claim_id, 'case_id': cid, 'entity_id': entity,
                 'evidence_id': claim_id + ':evidence', 'field': field, 'value': value,
                 'unit': None, 'quote': quote, 'source_id': sid, 'source_url': url,
                 'raw_text': raw, 'raw_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                 'observed_at': None, 'source_updated_at': None, 'source_published_at': None,
                 'retrieved_at': at, 'valid_until': None, 'context': {'travel_date': '2026-10-24', 'party_size': 2},
                 'authority': authority, 'licence_status': 'research_read_only_redistribution_unverified',
                 'entity_verified': False, 'extraction_verified': True,
                 'binding_status': 'candidate_association_only; current original-entity match not certified',
                 'representation': 'web_tool_text', 'packet': 'live/' + packet, **extra}
        claims.append(claim)
    bamboo = 'overture:64901913-1255-4d7b-89c4-135431c17a18'
    museum = 'overture:1b187ef9-7d32-472b-90e9-faa5c577ced6'
    garden = 'overture:2696c7dc-2d53-427f-b287-8c0c41898047'
    hotel = 'overture:5d5e58a5-dbf5-490b-a63f-5875bfdca965'
    restaurant = 'overture:b49b70c0-d5f8-4d87-aab0-612bc839ad41'
    u = 'https://www.chinajiandu.cn/News/Details/fw'
    add('D01', bamboo, 'price', {'admission_reference': 0, 'currency': 'CNY', 'scope': 'permanent free admission statement, not dated reservation'},
        'open_001.json', u, 'jiandu_operator', 'primary_operator', '长沙简牍博物馆于2007年11月8日起实施对公众永久性免费开放', source_published_literal='2007-11-08; no timezone')
    add('D01', bamboo, 'opening_hours', {'open': '09:00', 'close': '17:00', 'last_entry': '16:30', 'closed_weekday': 'Tuesday'},
        'open_001.json', u, 'jiandu_operator', 'primary_operator', '星期三——次周星期一上午9:00至下午5:00（下午4:30停止领票进馆）开馆，每周二、除夕、正月初一、初二闭馆。')
    u = 'https://hnggwhywap.wentiyun.cn/venue/info/1480.html'
    add('D01', bamboo, 'opening_hours', {'open': '09:00', 'close': '17:00', 'closed_weekday': 'Tuesday'},
        'open_002.json', u, 'hunan_cultural_portal', 'structured_provider', '开放时间：每周三至周一9:00-17:00', upstream_independence='operator metadata may be shared; not proven independent')
    add('D01', bamboo, 'theme', {'history': True, 'subject': '简牍文化史'}, 'open_002.json', u,
        'hunan_cultural_portal', 'structured_provider', '首个全面系统展现湖南简牍文化史的展览')
    u = 'https://you.ctrip.com/sight/changsha148/1674752.html'
    add('D01', museum, 'opening_hours', {'open': '09:00', 'close': '17:00', 'last_entry': '16:30', 'closed_weekday': 'Monday'},
        'open_002.json', u, 'ctrip_scoped_page', 'structured_provider', '全年 周二–周日 09:00-17:00开放（16:30停止入园）')
    add('D01', museum, 'theme', {'history': True}, 'open_002.json', u, 'ctrip_scoped_page', 'structured_provider', '长沙历史文化陈列')
    u = 'https://www.xiamenbg.cn/Home/yyzn2'
    add('D02', garden, 'opening_hours', {'season': '10-08 through 04-30', 'open': '06:30', 'close': '17:30'},
        'open_001.json', u, 'xiamenbg_operator', 'primary_operator', '10月8日-次年4月30日 6：30——17：30')
    add('D02', garden, 'identity', {'preferred_entries': ['虎园路25号西大门', '南门']},
        'open_001.json', u, 'xiamenbg_operator', 'primary_operator', '游客出入请走虎园路25号西大门或南门。')
    u = 'https://www.xiamenbg.cn/Home/yyzn3'
    add('D02', garden, 'price', {'adult_standard_reference': 30, 'currency': 'CNY', 'per': 'person_entry', 'dated_inventory': None},
        'open_003.json', u, 'xiamenbg_operator', 'primary_operator', 'L101: 景区门票\nL102: 30\nL103: 元/人·次', source_policy_literal='厦发改收费〔2023〕354号')
    u = 'https://www.langhamhotels.com/sc/the-langham/xiamen/stay/rooms/superior-room/'
    add('D02', hotel, 'room_configuration', {'room_type': '高级客房', 'alternatives': [{'kind': 'king', 'count': None}, {'kind': 'single', 'count': 2}], 'selected_option': None, 'dated_inventory': None},
        'open_001.json', u, 'langham_operator', 'primary_operator', '特大双人床或两张单人床（可应要求加床）')
    u = 'https://gs.ctrip.com/html5/you/foods/fooddetail/21/16760694.html'
    add('D02', restaurant, 'identity', {'source_branch_name': '1980烧肉粽(鼓浪屿店)', 'source_address': '龙头路64号103室', 'same_as_target': None},
        'open_003.json', u, 'ctrip_scoped_page', 'structured_provider', '1980烧肉粽(鼓浪屿店)',
        binding_status='UNMATCHED_BRANCH: source explicitly Gulangyu; target mainland-entity association not established; no price/menu transfer')
    u = 'https://www.weather.com.cn/textFC/hunan.shtml'
    add('D01', bamboo, 'weather_forecast', {'date': '2026-10-24', 'city': '长沙', 'day': '晴', 'max_c': 24, 'night': '晴', 'min_c': 16},
        'find_001.json', u, 'weather_com_cn', 'official_agency', '长沙  | 【138†长沙】  | 晴  | 北风 <3级  | 24  | 晴  | 北风 <3级  | 16',
        coverage_dates=['2026-10-24'], source_issue_literal='2026-10-23 07:30; timezone not explicit; not normalized', fact_scope='forecast estimate, not guaranteed weather')
    u = 'https://www.weather.com.cn/textFC/fujian.shtml'
    add('D02', garden, 'weather_forecast', {'date': '2026-10-24', 'city': '厦门', 'day': '多云', 'max_c': 32, 'night': '多云', 'min_c': 24},
        'find_001.json', u, 'weather_com_cn', 'official_agency', '厦门  | 【148†厦门】  | 多云  | 西北风 3-4级  | 32  | 多云  | 无持续风向 <3级  | 24',
        coverage_dates=['2026-10-24'], source_issue_literals=['open05:30', 'find07:30'], source_issue_timezone=None,
        fact_scope='same URL yielded changed issue times; do not fuse snapshots or assert25Oct coverage')
    # Keep official registry metadata for weather; do not overwrite its lineage.
    registry.pop('weather_com_cn')
    p = OUT / 'live/ingest_request_001.json'
    if p.exists():
        raise FileExistsError('Preserve first extraction')
    p.write_text(json.dumps({'claims': claims, 'registry_additions': registry}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Literal claims with preserved unknown source clocks:', len(claims))

if __name__ == '__main__':
    main()
