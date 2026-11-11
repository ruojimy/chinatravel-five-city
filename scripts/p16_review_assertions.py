"""Normalize reviewed worker packets; scopes cannot silently become native defaults."""
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import POLICIES,utcnow,parse_time,canonical
from shorttrip.operator_assertions import VERSION,validate_assertion,check_graph,exact_source_quote
RES=ROOT/'results/p16_multiworker'
def main():
    out=RES/'approved_assertions.json'
    if out.exists():raise FileExistsError('Review batches are immutable; use another explicit batch version')
    assertions=[];source_files=[]
    def create(entity,field,value,unit,scope,quote,context,source,capture,native=None):
        file=capture['file'];raw=(ROOT/file).read_bytes().decode('utf-8');digest=hashlib.sha256(raw.encode()).hexdigest()
        if digest!=capture['sha256']:raise ValueError('Worker capture digest mismatch')
        quote=exact_source_quote(raw,quote)
        published=source.get('source_published_at');published_iso=published if parse_time(published) else None
        policy='room_configuration' if field in ('room_type_name','bed_configuration') else 'price' if field=='admission' else 'theme' if 'duration' in field else 'opening_hours'
        eid='operator:'+hashlib.sha256((source['source_id']+source['source_url']+source['retrieved_at']+raw).encode()).hexdigest()
        assertion={'schema_version':VERSION,'assertion_id':'operator-assertion:'+hashlib.sha256(canonical([entity,field,value,scope,eid]).encode()).hexdigest(),
          'entity_id':entity,'field':field,'value':value,'unit':unit,'scope':scope,'quote':quote,'context':context,
          'source_id':source['source_id'],'source_url':source['source_url'],'source_published_at':published_iso,
          'source_updated_at':None,'observed_at':None,'retrieved_at':source['retrieved_at'],
          'valid_from':None,'valid_until':None,'source_date_text':published,
          'policy_id':policy,'ttl_seconds':POLICIES[policy][0],
          'authority':source['authority'],'licence_status':'public_source_reuse_unverified',
          'capture':capture,'evidence_id':eid,'native_values':native or {}}
        gate=validate_assertion(assertion)
        if not gate['ok']:raise ValueError(gate)
        assertions.append(assertion)
    path=RES/'attractions/field_assertions.json';batch=json.loads(path.read_text(encoding='utf-8'));source_files.append(path)
    sources={x['source_id']:x for x in batch['sources']}
    for a in batch['assertions']:
        s=sources[a['source_id']];file=path.parent/s['content_file'];native={}
        # Root reviewed the exact "all exhibition halls free" wording. Historical,
        # ordinary-only and paid-special-exhibit prices remain scoped assertions.
        if a['entity_name']=='中国港口博物馆' and a['field']=='admission' and a['value']==0 and '所有展厅免费参观' in a['quote']:native={'price':0.0}
        create(a['entity_id'],a['field'],a['value'],a['unit'],a['scope'],a['quote'],
          {'applicability':a.get('applicability'),'notes':a.get('notes',[]),'status':a['status'],
           'entity_match':a['identity_match_basis'],'entity_verified':False,'calendar_and_product_scope_required':True},
          {**s,'authority':'primary_operator' if s['independent_source_group']!='china_gansu_news_republished' else 'government_hosted_secondary'},
          {'file':str(file.relative_to(ROOT)),'sha256':s['content_sha256'],'representation':s['representation']},native)
    path=RES/'hotels/hotel_field_assertions.json';batch=json.loads(path.read_text(encoding='utf-8'));source_files.append(path)
    for a in batch['assertions']:
        e=a['evidence'];file=path.parent/e['path'];native={};quote=e['excerpt'];repair=None
        if a['entity_id']=='overture:b165cfac-cdff-4b48-b378-168b38b06aa1' and e['path']=='raw_web_tool_text/rooms_02.txt':
            # The worker joined two adjacent tool lines with a space. Restore the
            # actual retained L101/L102 range, including its line marker.
            raw=file.read_bytes().decode('utf-8');first='King size bed: around 1.98m wide.';last='Twin size bed: around 0.99m-1.22m wide.'
            start=raw.index(first);end=raw.index(last,start)+len(last);quote=raw[start:end]
            repair='Root restored exact tool line range; worker excerpt joined adjacent lines'
        if a['field']=='bed_configuration' and a['entity_id']=='overture:5d5e58a5-dbf5-490b-a63f-5875bfdca965' and '两张单人床' in e['excerpt']:
            native={'numbed':2}
        create(a['entity_id'],a['field'],a['value'],a['unit'],canonical(a['scope']),quote,
          {'room_scope':a['scope'],'entity_match':a['entity_match'],'entity_verified':False,
           'bed_alternatives_are_not_additive':True,'native_projection_context':'twin option only' if native else None,'quote_repair':repair},
          {'source_id':'official-hotel:'+e['source_organization'],'source_url':e['source_url'],'retrieved_at':a['retrieved_at'],
           'source_published_at':None,'authority':'primary_operator'},
          {'file':str(file.relative_to(ROOT)),'sha256':e['sha256'],'representation':e['representation']},native)
    pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
    db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
    for x in assertions:
        row=db.execute('SELECT payload FROM records WHERE id=?',(x['entity_id'],)).fetchone()
        if not row:raise ValueError('Assertion entity is not in existing catalog')
    db.close()
    report={'reviewed_at':utcnow(),'reviewer':'root_agent','assertions':assertions,
       'source_packets':[{'file':str(f.relative_to(ROOT)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in source_files],
       'existing_entities':len({x['entity_id'] for x in assertions}),
       'native_projection_candidates':sum(bool(x['native_values']) for x in assertions),
       'no_new_entities':True,'planning_ready_certified':False}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Restrictions discovered by independent workers are now shared with every downloader.
    db=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30)
    pauses=[]
    for file,key in ((RES/'attractions/source_pauses.json','new_pauses'),(RES/'hotels/source_pauses.json','hosts')):
        pauses+=json.loads(file.read_text(encoding='utf-8')).get(key,[])
    with db:
        for pause in pauses:
            existing=db.execute('SELECT status FROM hosts WHERE host=?',(pause['host'],)).fetchone()
            if existing and existing[0]=='paused':continue
            if existing:db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(pause['reason'],pause['host']))
            else:db.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',(pause['host'],'paused',0,8,'',pause['reason']))
    db.close()
    print(canonical({k:report[k] for k in ('existing_entities','native_projection_candidates','no_new_entities')}))
if __name__=='__main__':main()
