"""Scoped operator facts retain calendars, room alternatives, clocks and evidence."""
import hashlib,json,re
from .freshness import POLICIES,parse_time

VERSION='operator-business-assertion-v1'
def exact_source_quote(raw,quote):
    """Restore captured Windows line endings without changing quoted words."""
    if quote in raw:return quote
    windows=quote.replace('\r\n','\n').replace('\n','\r\n')
    if windows in raw:return windows
    raise ValueError('Unsupported worker quotation')

def validate_assertion(x):
    errors=[]
    if not isinstance(x,dict):return {'ok':False,'errors':['not_object']}
    required=('assertion_id','entity_id','field','value','unit','scope','quote','context','source_id','source_url',
      'source_published_at','source_updated_at','observed_at','retrieved_at','valid_from','valid_until',
      'source_date_text','policy_id','ttl_seconds','authority','licence_status','capture','evidence_id','native_values')
    for key in required:
        if key not in x:errors.append('missing:'+key)
    if x.get('schema_version')!=VERSION:errors.append('schema_version')
    for key in ('assertion_id','entity_id','field','scope','quote','source_id','source_url','authority','licence_status','evidence_id'):
        if not isinstance(x.get(key),str) or not x[key].strip():errors.append('text:'+key)
    for key in ('source_published_at','source_updated_at','observed_at','retrieved_at','valid_from','valid_until'):
        if x.get(key) is not None and not parse_time(x[key]):errors.append('clock:'+key)
    if not parse_time(x.get('retrieved_at')):errors.append('retrieved_at')
    policy=x.get('policy_id')
    if not isinstance(policy,str) or policy not in POLICIES:errors.append('policy')
    elif x.get('ttl_seconds')!=POLICIES[policy][0]:errors.append('ttl')
    if not isinstance(x.get('context'),dict):errors.append('context')
    if not isinstance(x.get('native_values'),dict):errors.append('native_values')
    else:
        for key,value in x['native_values'].items():
            if key not in ('price','numbed','cuisine','recommendmintime','recommendmaxtime'):errors.append('unsupported_native_projection:'+key)
            if key=='numbed' and (type(value) is not int or value<1):errors.append('bed_count')
            if key=='price' and (type(value) not in (int,float) or value<0):errors.append('price')
            if key=='cuisine' and (not isinstance(value,str) or not value.strip()):errors.append('cuisine')
            if key in ('recommendmintime','recommendmaxtime') and (type(value) not in (int,float) or not 0<value<=24):errors.append('visit_duration')
        native=x['native_values']
        if any(k in native for k in ('recommendmintime','recommendmaxtime')):
            if not all(type(native.get(k)) in (int,float) for k in ('recommendmintime','recommendmaxtime')):errors.append('visit_duration_pair')
            elif native['recommendmintime']>native['recommendmaxtime']:errors.append('visit_duration_pair')
    capture=x.get('capture')
    if not isinstance(capture,dict):errors.append('capture')
    else:
        for key in ('file','sha256','representation'):
            if not isinstance(capture.get(key),str) or not capture[key]:errors.append('capture:'+key)
        if not re.fullmatch('[0-9a-f]{64}',str(capture.get('sha256',''))):errors.append('capture_digest')
        if capture.get('representation') not in ('web_tool_text','web_tool_text_excerpt','public_html','public_html_dom_text','rendered_ui_text','saved_original_json_row','saved_response_poi_object_serialized','saved_csv_row_serialized','saved_public_html_json_object_serialized'):errors.append('representation')
    try:json.dumps(x,allow_nan=False)
    except (TypeError,ValueError):errors.append('finite_json')
    return {'ok':not errors,'errors':errors,'truth_certified':False}

def check_graph(x,evidence):
    gate=validate_assertion(x);errors=list(gate['errors'])
    if not isinstance(evidence,dict):errors.append('missing_evidence')
    else:
        for key in ('source_id','source_url','source_published_at','source_updated_at','observed_at','retrieved_at'):
            if x.get(key)!=evidence.get(key):errors.append('evidence_mismatch:'+key)
        if not isinstance(x.get('quote'),str) or x['quote'] not in evidence.get('raw_text',''):errors.append('quote_not_in_evidence')
        if x.get('capture',{}).get('sha256')!=evidence.get('raw_sha256'):errors.append('capture_digest_mismatch')
    return {'ok':not errors,'errors':errors}

def load_approved(root):
    """Only a reviewed local batch is imported; each evidence file is rehashed."""
    from pathlib import Path
    root=Path(root);path=root/'results/p16_multiworker/approved_assertions.json';paths=[]
    if path.exists():paths.append(path)
    index=root/'results/p17_continuous/approved_batches/index.json'
    if index.exists():
        for entry in json.loads(index.read_text(encoding='utf-8'))['batches']:
            batch_path=(root/entry['file']).resolve()
            if not batch_path.is_relative_to((root/'results/p17_continuous/approved_batches').resolve()):raise ValueError('Batch outside approved registry')
            if hashlib.sha256(batch_path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Approved batch changed')
            paths.append(batch_path)
    grouped={};evs={};seen={}
    for path in paths:
      batch=json.loads(path.read_text(encoding='utf-8'))
      for x in batch['assertions']:
        file=(root/x['capture']['file']).resolve()
        if not any(file.is_relative_to((root/'results'/folder).resolve()) for folder in ('p16_multiworker','p17_continuous')):raise ValueError('Capture outside reviewed batch')
        raw=file.read_bytes().decode('utf-8');digest=hashlib.sha256(raw.encode()).hexdigest()
        if digest!=x['capture']['sha256']:raise ValueError('Reviewed source text changed')
        ev={'evidence_id':x['evidence_id'],'raw_text':raw,'raw_sha256':digest,
            **{k:x[k] for k in ('source_id','source_url','source_published_at','source_updated_at','observed_at','retrieved_at','authority','licence_status')}}
        gate=check_graph(x,ev)
        if not gate['ok']:raise ValueError(gate)
        aid=x['assertion_id']
        if aid in seen:
            if seen[aid]!=x:raise ValueError('Conflicting duplicate assertion identity')
            continue
        seen[aid]=x;grouped.setdefault(x['entity_id'],[]).append(x);evs[ev['evidence_id']]=ev
    return grouped,evs

def load_approved_offers(root):
    """Load reviewed UI offers, verifying immutable batch and screenshot bytes."""
    from pathlib import Path
    from .business_completion import validate_room_offer
    root=Path(root);folder=root/'results/p17_continuous/approved_batches';index=folder/'room_offers_index.json'
    if not index.exists():return []
    offers=[];seen=set()
    for entry in json.loads(index.read_text(encoding='utf-8'))['batches']:
        path=(root/entry['file']).resolve()
        if not path.is_relative_to(folder.resolve()):raise ValueError('Offer batch outside reviewed registry')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Reviewed offer batch changed')
        for offer in json.loads(path.read_text(encoding='utf-8'))['offers']:
            if not validate_room_offer(offer)['ok']:raise ValueError('Invalid reviewed room offer')
            for capture in offer['screenshot_evidence']:
                file=(root/capture['file']).resolve()
                if not file.is_relative_to((root/'results/p17_continuous').resolve()):raise ValueError('Screenshot escaped reviewed evidence')
                if hashlib.sha256(file.read_bytes()).hexdigest()!=capture['sha256']:raise ValueError('Reviewed screenshot changed')
            if offer['offer_id'] in seen:raise ValueError('Duplicate reviewed offer')
            seen.add(offer['offer_id']);offers.append(offer)
    return offers
