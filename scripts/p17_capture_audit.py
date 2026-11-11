"""Root-side audit of retained original HTML and derived evidence; no network."""
import argparse, gzip, hashlib, importlib.util, json, sqlite3, sys, re, inspect
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.source_identity import language_aliases
from shorttrip.business_archives import normalize_name
from shorttrip.freshness import utcnow

def main():
    p=argparse.ArgumentParser();p.add_argument('packet',type=Path);args=p.parse_args();path=args.packet.resolve()
    packet=json.loads(path.read_text(encoding='utf-8'));pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text())
    db=sqlite3.connect(ROOT/pointer['catalog']);sources={};rooms={};cards={};records={};errors=[]
    for s in packet['sources']:
        loc=s.get('source_locator',{});raw=gzip.open(loc['original_html_file'],'rb').read()
        if hashlib.sha256(raw).hexdigest()!=loc['original_response_sha256']:raise ValueError('Original HTML digest changed')
        if loc.get('original_gzip_sha256') and hashlib.sha256(Path(loc['original_html_file']).read_bytes()).hexdigest()!=loc['original_gzip_sha256']:raise ValueError('Gzip digest changed')
        text=(path.parent/s['content_file']).read_bytes()
        if hashlib.sha256(text).hexdigest()!=s['content_sha256']:raise ValueError('Derived view digest changed')
        if any(s.get(k) is not None for k in ('observed_at','source_published_at','source_updated_at')):raise ValueError('Unexpected clock upgrade')
        if s['source_id'].startswith(('p17-healthy-operator-cached:','p17-niccolo-detail:','p17-pan-observed:','p17-millennium-cached:','p17-ascott-public-schema:','p17-langham-observed:','p17-pan-remaining:')):
            file=ROOT/loc['dom_parser'].rsplit(':',1)[0]
            if hashlib.sha256(file.read_bytes()).hexdigest()!=loc['parser_sha256']:raise ValueError('Parser changed after capture extraction')
            sys.path.insert(0,str(file.parent))
            if loc.get('base_parser_sha256'):
                basefile=ROOT/'results/p17_continuous/hotels/healthy_operator_parser.py'
                if hashlib.sha256(basefile.read_bytes()).hexdigest()!=loc['base_parser_sha256']:raise ValueError('Base parser changed')
                sys.path.insert(0,str(basefile.parent))
            spec=importlib.util.spec_from_file_location('checked_room_parser',file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            parsed=mod.parse_rooms(raw,s['source_url']) if len(inspect.signature(mod.parse_rooms).parameters)==2 else mod.parse_rooms(raw)
            if isinstance(parsed,list):
                converted=[]
                for room in parsed:
                    facts=[{'field':'bed_configuration','value':{'literal':room['bed'],'count':None,'explicit_components':room['bed_components'],'total_count':None},'quote':room['bed']}]
                    if room['occupancy_text']:facts.append({'field':'room_occupancy_text','value':room['occupancy_text'],'quote':room['occupancy_text']})
                    converted.append({'room_type_name':room['name'],'name_quote':room['name'],'facts':facts})
                rooms[s['source_id']]=converted
            else:rooms[s['source_id']]=[{**r,'room_type_name':r.get('room_type_name') or r['name']} for r in parsed['rooms']]
        if s['source_id'].startswith('p17-ctrip-card:'):
            file=ROOT/loc['dom_parser'].rsplit(':',1)[0]
            if hashlib.sha256(file.read_bytes()).hexdigest()!=loc['parser_sha256']:raise ValueError('Card parser changed')
            spec=importlib.util.spec_from_file_location('checked_card_parser',file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            cards[s['source_id']]=mod.card_values(raw.decode('utf-8','replace'))
        sources[s['source_id']]=(s,text.decode(),raw)
    for a in packet['assertions']:
        s,text,raw=sources[a['source_id']]
        if a['quote'] not in text:raise ValueError('Quote not in derived view')
        rid=a['entity_id']
        if rid not in records:records[rid]=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0])
        record=records[rid]
        if a.get('native_projection_permitted'):raise ValueError('Unexpected native permission')
        if a['field']=='room_area':
            ranged=re.search(r'(\d+(?:\.\d+)?)\s*(?:-|–|—|至|to)\s*(\d+(?:\.\d+)?)\s*(?:平方米|sq\.?\s*m|m[²2])',a['quote'],re.I)
            if ranged and a['value']!={'minimum':float(ranged[1]),'maximum':float(ranged[2])}:raise ValueError('Area interval collapsed or changed')
        if a['field']=='bed_configuration' and isinstance(a['value'],dict):
            value=a['value']
            if value.get('alternatives_present') and (value.get('count') is not None or value.get('total_count') is not None):raise ValueError('Alternative beds summed or implicitly selected')
        if a['source_id'] in rooms:
            scope=json.loads(a['scope']) if isinstance(a['scope'],str) else a['scope'];name=scope['room_type_name']
            possible=[r for r in rooms[a['source_id']] if r['room_type_name']==name]
            if a['field']=='room_type_name':okay=any(r['name_quote']==a['quote'] and r['room_type_name']==a['value'] for r in possible)
            else:okay=any(f['field']==a['field'] and f['quote']==a['quote'] and f['value']==a['value'] for r in possible for f in r['facts'])
            if not okay:raise ValueError('Room fact not reproduced from original DOM')
        elif a['source_id'].startswith('p17-ctrip-alias-cache:'):
            basis=a['identity_match_basis'];original=(ROOT/basis['raw_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Attraction original entity mismatch')
            aliases=language_aliases(row);name=normalize_name(s['source_locator']['source_name'])
            alias=aliases.get(name)
            if alias is None and basis.get('script_normalization')=='OpenCC t2s then normalize_name; original alias locator retained':
                from opencc import OpenCC
                converter=OpenCC('t2s');matching=[value for value in aliases.values() if normalize_name(converter.convert(value['value']))==normalize_name(converter.convert(s['source_locator']['source_name']))]
                if len(matching)==1:alias=matching[0]
            if alias!=basis['literal_alias']:raise ValueError('Attraction alias differs from retained row')
            if record['city'] not in (basis.get('source_address') or '') and basis.get('source_city_context')!=record['city']:raise ValueError('Attraction city not explicitly supported')
        elif a['source_id'] in cards:
            loc=s['source_locator'];basis=a['identity_match_basis']
            original=(ROOT/loc['original_entity_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Card entity original row mismatch')
            aliases=language_aliases(row);alias=aliases.get(normalize_name(loc['card_title']))
            if alias is None and basis.get('script_normalization')=='OpenCC t2s then normalize_name; original alias locator remains literal':
                from opencc import OpenCC
                converter=OpenCC('t2s');matching=[value for value in aliases.values() if normalize_name(converter.convert(value['value']))==normalize_name(converter.convert(loc['card_title']))]
                if len(matching)==1:alias=matching[0]
            if alias!=basis['alias'] or basis['city']!=record['city']:raise ValueError('Card literal name/city mismatch')
            possible=[c for c in cards[a['source_id']] if c['name']==loc['card_title'] and c['detail_observed_href']==loc['observed_detail_href']]
            if not any(c['field']==a['field'] and c['quote']==a['quote'] and c['value']==a['value'] for c in possible):raise ValueError('Card fact not reproduced from original DOM')
            if a['value'].get('display_label')=='免费' and a['value'].get('booking_required') is not None:raise ValueError('Free label cannot establish reservation requirement')
        elif a['source_id'].startswith('p17-http-review:'):
            from urllib.parse import urlsplit
            basis=a['identity_match_basis'];original=(ROOT/basis['raw_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Restaurant source binding mismatch')
            if basis['original_http_url'] not in row.get('websites',[]):raise ValueError('Transport original URL not in retained entity')
            old=urlsplit(basis['original_http_url']);new=urlsplit(s['source_url'])
            if old.hostname!=new.hostname or (old.path or '/')!=(new.path or '/') or old.query!=new.query or new.scheme!='https':raise ValueError('Transport candidate changed host/path/query')
            if a['field']=='opening_rules':
                norm=lambda x:re.sub(r'[^\w\u4e00-\u9fff]','',str(x)).casefold()
                address=basis['matched_address'];phone=basis['matched_phone']
                if address not in [z.get('freeform') for z in row.get('addresses') or []] or norm(address) not in norm(text):raise ValueError('Operator address not corroborated')
                if norm(phone) not in [norm(z) for z in row.get('phones') or []] or norm(phone) not in norm(text):raise ValueError('Operator phone not corroborated')
        elif a['source_id'].startswith('p17-ctrip-intro:'):
            from bs4 import BeautifulSoup
            from opencc import OpenCC
            convert=OpenCC('t2s');loc=s['source_locator'];original=(ROOT/loc['original_entity_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Introduction entity original mismatch')
            if normalize_name(convert.convert(record['name']))!=normalize_name(convert.convert(loc['source_name'])) or loc['source_city_context']!=record['city']:raise ValueError('Introduction name/city mismatch')
            soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser');intro=[]
            for h in soup.select('.detailModule .moduleTitle'):
                if h.get_text(' ',strip=True)=='介绍':
                    node=h.find_next_sibling(class_='moduleContent')
                    if node:intro.append(node.get_text(' ',strip=True))
            if not any(a['quote'] in text for text in intro):raise ValueError('Quote not in introduction module')
        elif a['source_id'].startswith('p17-feinfood-provider:'):
            basis=a['identity_match_basis'];original=(ROOT/basis['raw_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Restaurant original row mismatch')
            phone_norm=lambda x:re.sub(r'\D','',x).removeprefix('00')
            phone=basis.get('matched_phone_quote');address=basis.get('matched_address');part=basis.get('matched_explicit_bilingual_address_component')
            phone_ok=bool(phone and phone in text and phone_norm(phone) in [phone_norm(z) for z in row.get('phones') or []])
            originals=[z.get('freeform','') for z in row.get('addresses') or []]
            address_ok=bool(address and address in originals and normalize_name(address) in normalize_name(text))
            part_ok=bool(part and any(part in re.split(r'\s{2,}',full) for full in originals) and len(normalize_name(part))>=7 and normalize_name(part) in normalize_name(text))
            if not any((phone_ok,address_ok,part_ok)):raise ValueError('No literal original branch address or international phone corroboration')
            from opencc import OpenCC
            converter=OpenCC('t2s');name_norm=lambda value:normalize_name(converter.convert(value))
            if name_norm(record['name']) not in name_norm(basis['source_property_name']) or name_norm(basis['source_property_name']) not in name_norm(text):raise ValueError('Literal source property name not found after punctuation/spacing/script normalization')
            if a['field']=='average_price':
                m=re.fullmatch(r'RMB\s*(\d+(?:\.\d+)?)',a['quote'])
                if not m or float(m[1])!=a['value']:raise ValueError('Price differs from explicit RMB amount')
        elif a['source_id'].startswith('p17-ctrip-embedded-duration:'):
            from shorttrip.public_duration import verify_public_duration
            loc=s['source_locator'];parser=ROOT/loc['html_parser'].rsplit(':',1)[0]
            if hashlib.sha256(parser.read_bytes()).hexdigest()!=loc['parser_sha256']:raise ValueError('Duration parser changed')
            if s['representation']!='saved_public_html_json_object_serialized':raise ValueError('Derived projection must not claim original HTML bytes')
            original=(ROOT/loc['original_entity_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Duration entity original mismatch')
            projection=json.loads(text);verify_public_duration(raw,projection,record,s['source_url'])
            if a['field']!='recommended_duration_raw' or a['value']!=projection['playSpendTime'] or a['quote']!=a['value']:raise ValueError('Duration field differs from exact public source attribute')
        elif a['source_id'].startswith('p17-bingsheng:'):
            basis=a['identity_match_basis'];original=(ROOT/basis['raw_row_file']).read_bytes();row=json.loads(original)
            if hashlib.sha256(original).hexdigest()!=record['source_locator']['raw_sha256'] or row['id']!=rid.removeprefix('overture:') or row['names']['primary']!=record['name']:raise ValueError('Brand cuisine branch source mismatch')
            detail_source,detail_text,_=sources[basis['shop_detail_source_id']]
            if detail_source['content_sha256']!=basis['shop_detail_content_sha256'] or basis['shop_detail_quote'] not in detail_text:raise ValueError('Branch detail evidence changed')
            original_value=basis['original_value'];quote=basis['shop_detail_quote']
            if basis['contact_type']=='phone':
                digits=lambda value:re.sub(r'\D','',value)
                if original_value not in (row.get('phones') or []) or digits(original_value)!='86'+digits(quote).removeprefix('0'):raise ValueError('Original full phone and local operator phone disagree')
            elif basis['contact_type']=='address':
                if original_value not in [z.get('freeform') for z in row.get('addresses') or []] or original_value!=quote:raise ValueError('Original operator address differs')
            else:raise ValueError('Unapproved branch contact binding')
            if a['field']=='cuisine_reference' and (a['value']!='粤菜（运营方品牌自述）' or '粤菜体系' not in a['quote']):raise ValueError('Cuisine is not scoped to literal brand positioning')
    db.close();receipt={'at':utcnow(),'packet_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sources':len(sources),'assertions':len(packet['assertions']),
        'entities':len(records),'original_html_rehashed':True,'unknown_fact_clocks_unchanged':True,'no_native_projection':True,'network_requests':0,'passed':True}
    out=path.parent/'root_capture_audit.json'
    if out.exists():raise FileExistsError('Immutable audit receipt exists')
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(receipt))

if __name__=='__main__':main()
