"""Field-level price qualification; hypothetical free is not verified free."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import csv,json,math,os,sqlite3,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ingest'))
from entity_evidence import parse as _reextract_entity

CITIES={'北京':'beijing','上海':'shanghai','南京':'nanjing','苏州':'suzhou','杭州':'hangzhou',
        '深圳':'shenzhen','成都':'chengdu','武汉':'wuhan','广州':'guangzhou','重庆':'chongqing','西安':'xian'}
def _num(value):
    if value is None or isinstance(value,bool):return None
    try:x=float(value)
    except (ValueError,TypeError):return None
    return x if math.isfinite(x) and x>=0 else None

def _applicable(entry,query):
    scope=entry.get('field_validity') or {}
    if not scope:return True
    start=query.get('start_date')
    end=query.get('end_date') or start
    return start==scope.get('trip_start_date') and end==scope.get('trip_end_date')

def _generic_zero_assumption(ev,base,record_id,city,name):
    if (ev.get('schema')!='chinatravel-entity-evidence-v1' or ev.get('record_id')!=record_id
            or ev.get('city')!=city or ev.get('name')!=name or ev.get('kind')!='attraction'):
        return False
    journal=(base/str(ev.get('journal') or '')).resolve()
    if not journal.is_relative_to(base.resolve()) or not journal.is_file():return False
    if sha256(journal.read_bytes()).hexdigest()!=ev.get('journal_sha256'):return False
    try:
        con=sqlite3.connect('file:'+journal.as_posix()+'?mode=ro',uri=True)
        hosts=set();source_groups=set()
        try:
            for obs in ev.get('observations',[]):
                if obs.get('purpose')!='ticket_price':continue
                r=con.execute('SELECT status,request_json,raw_sha256,response_text FROM calls WHERE id=?',(obs.get('call_id'),)).fetchone()
                if not r or r[0]!='ok' or not r[3] or sha256(r[3].encode('utf-8')).hexdigest()!=r[2] or r[2]!=obs.get('raw_sha256'):continue
                q=json.loads(r[1]);x=_reextract_entity(r[3],name,city,'attraction',q.get('url'))
                if (q.get('record_id')!=record_id or q.get('name')!=name or q.get('city')!=city
                    or q.get('purpose')!='ticket_price' or q.get('url')!=obs.get('url')
                    or not q.get('source_group') or q.get('source_group')!=obs.get('source_group')
                    or x.get('status')!='identity_matched' or x.get('offers') or x.get('discarded')):continue
                from urllib.parse import urlparse
                u=urlparse(q['url'])
                if u.scheme=='https' and u.hostname and u.hostname==obs.get('host'):
                    hosts.add(u.hostname);source_groups.add(q['source_group'])
        finally:con.close()
        return len(hosts)>=2 and len(source_groups)>=2
    except (ValueError,TypeError,OSError,sqlite3.Error):return False

class AttractionPriceEvidence:
    def __init__(self,root,snapshot=None):
        self.root=Path(root).resolve()
        self.snapshot_path=Path(snapshot).resolve() if snapshot else None
        self.snapshot=json.loads(self.snapshot_path.read_text(encoding='utf-8')) if self.snapshot_path else {}
        grade_file=Path(__file__).resolve().parents[1]/'xian_grade_evidence_v3.json'
        self.grade=json.loads(grade_file.read_text(encoding='utf-8')) if grade_file.is_file() else {}
    @lru_cache(maxsize=None)
    def _city(self,city):
        if city not in CITIES:return []
        database=Path(os.environ['CHINATRAVEL_DATABASE_ROOT']).resolve() if os.environ.get('CHINATRAVEL_DATABASE_ROOT') else self.root/'chinatravel/environment/database'
        path=database/'attractions'/CITIES[city]/'attractions.csv'
        if not path.is_file():return []
        with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        source_sha=sha256(path.read_bytes()).hexdigest()
        return [(r,source_sha) for r in rows]
    def check(self,query,plan):
        city=query.get('target_city');diagnostics=[]
        snapshot_prices=self.snapshot.get('attraction_prices') or []
        for bucket in plan.get('itinerary',[]):
            for activity in bucket.get('activities',[]):
                if activity.get('type')!='attraction':continue
                name=activity.get('position');price=_num(activity.get('price'))
                rows=[(r,h) for r,h in self._city(city) if r.get('name')==name]
                entries=[v for v in snapshot_prices if v.get('city')==city and v.get('name')==name and _applicable(v,query)]
                item={'day':bucket.get('day'),'name':name,'planned_price':price}
                if price is None:
                    item.update(state='fail',reason='missing_or_invalid_plan_price')
                elif len(entries)>1:
                    item.update(state='unknown',reason='ambiguous_dynamic_price_evidence')
                elif entries:
                    entry=entries[0];value=_num(entry.get('price'));status=str(entry.get('status') or '')
                    item['dynamic_status']=status;item['dynamic_evidence_path']=entry.get('evidence_path')
                    item['dynamic_evidence_sha256']=entry.get('evidence_sha256')
                    ref=(self.snapshot_path.parent/str(entry.get('evidence_path') or '')).resolve()
                    evidence_ok=(self.snapshot_path is not None and ref.is_relative_to(self.snapshot_path.parent)
                                 and ref.is_file() and sha256(ref.read_bytes()).hexdigest()==entry.get('evidence_sha256'))
                    identity_ok=(len(rows)==1 and entry.get('record_id')==f"attraction:{CITIES.get(city)}:{rows[0][0].get('id')}")
                    if entry.get('conflict_unresolved'):
                        item.update(state='unknown',reason='dynamic_price_conflict_unresolved')
                    elif not evidence_ok or not identity_ok:
                        item.update(state='unknown',reason='dynamic_evidence_hash_or_identity_unverified')
                    elif value is None:item.update(state='unknown',reason='dynamic_evidence_has_no_valid_price')
                    elif abs(price-value)>0.1:item.update(state='fail',reason='plan_price_disagrees_with_dynamic_reference')
                    else:
                        # Even an observed historical source or user-authorized
                        # assumed zero is conditional, not a verified real fare.
                        item.update(state='unknown',reason='assumed_or_undated_reference_price')
                        if status=='user_authorized_zero_assumption_after_search' and value==0:
                            try:
                                ev=json.loads(ref.read_text(encoding='utf-8'))
                                queries=ev.get('request_queries') or []
                                searches=[q for q in queries if isinstance(q,str) and name in q]
                                legacy=(len(searches)>=2 and bool(ev.get('searched_at')) and bool(ev.get('shiyuan_search')))
                                item['conditional_assumption_eligible']=(legacy or _generic_zero_assumption(
                                    ev,self.snapshot_path.parent,entry.get('record_id'),city,name))
                            except (ValueError,TypeError,OSError):item['conditional_assumption_eligible']=False
                elif not rows:
                    item.update(state='unknown',reason='source_attraction_not_matched')
                else:
                    section=(self.grade.get('kinds') or {}).get('attraction') or {}
                    has_grade=(city=='西安' and section.get('csv_sha256')==rows[0][1] and len(rows)==1)
                    detail=(section.get('records') or {}).get(str(rows[0][0].get('id'))) if has_grade else None
                    derived=bool(detail and 'price' in (detail.get('non_source_fields') or {}))
                    estimated=any(str(r.get('price_status') or '').lower().startswith('estimated') for r,_ in rows)
                    vals={_num(r.get('price')) for r,_ in rows}
                    if derived or estimated:item.update(state='unknown',reason='source_price_derived_or_estimated')
                    elif len(vals)!=1 or None in vals:item.update(state='unknown',reason='source_price_missing_or_ambiguous')
                    else:
                        value=next(iter(vals));item['source_price']=value;item['source_file_sha256']=rows[0][1]
                        item.update(state='pass' if abs(value-price)<=0.1 else 'fail',
                                    reason='matches_frozen_source' if abs(value-price)<=0.1 else 'differs_from_frozen_source')
                diagnostics.append(item)
        return diagnostics
