"""Versioned validated store. All new rows pass the contract before commit."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .expansion_contract import validate_record, validate_evidence, validate_claim, validate_tag
from .freshness import canonical, utcnow

class ExpansionStore:
    def __init__(self,path,*,create=False):
        self.path=Path(path)
        if create:
            if self.path.exists():raise FileExistsError('Preserve existing snapshot: '+str(self.path))
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(self.path)
            self.db.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,city TEXT,name TEXT,
                provider_city_match INTEGER,planning_ready INTEGER,payload TEXT,gate TEXT);
            CREATE INDEX city_kind ON records(city,kind,provider_city_match);
            CREATE TABLE tags(record_id TEXT REFERENCES records(id),tag TEXT,value TEXT,payload TEXT);
            CREATE INDEX tag_lookup ON tags(tag,value,record_id);
            CREATE TABLE evidence(id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE claims(id TEXT PRIMARY KEY,entity_id TEXT REFERENCES records(id),
                evidence_id TEXT REFERENCES evidence(id),payload TEXT,gate TEXT);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            ''')
        else:
            if not self.path.exists():raise FileNotFoundError(path)
            self.db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)
        self.db.row_factory=sqlite3.Row
    def close(self):self.db.close()
    def load(self,records,*,now=None):
        """One transaction per batch. Bad row rolls back the entire batch."""
        count=0;ready=0
        with self.db:
            for record in records:
                gate=validate_record(record,now=now)
                if not gate['discovery_ok']:raise ValueError({'id':record.get('record_id'),'errors':gate['errors']})
                for field,provenance in record['field_provenance'].items():
                    eid=provenance.get('evidence_id')
                    if not eid:continue
                    stored=self.db.execute('SELECT payload FROM evidence WHERE id=?',(eid,)).fetchone()
                    if not stored:raise ValueError('unresolved field evidence:'+field)
                    evidence=json.loads(stored[0]);ev_gate=validate_evidence(evidence)
                    if not ev_gate['ok'] or any(provenance.get(k)!=evidence.get(k) for k in ('source_id','source_url','observed_at')):
                        raise ValueError('field evidence mismatch:'+field)
                rid=record['record_id'];match=record.get('source_locator',{}).get('provider_city_match',False)
                for assertion in record.get('operator_assertions',[]):
                    from .operator_assertions import check_graph
                    item=self.db.execute('SELECT payload FROM evidence WHERE id=?',(assertion['evidence_id'],)).fetchone()
                    ag=check_graph(assertion,json.loads(item[0]) if item else None)
                    if not ag['ok']:raise ValueError({'operator_assertion_graph':ag['errors']})
                if 'today_hours_structured' in record:
                    h=record['today_hours_structured']
                    item=self.db.execute('SELECT payload FROM evidence WHERE id=?',(h['evidence_id'],)).fetchone()
                    if not item:raise ValueError('unresolved structured hours evidence')
                    item=json.loads(item[0])
                    if any(h.get(k)!=item.get(k) for k in ('source_id','source_url','observed_at','retrieved_at','source_updated_at')):
                        raise ValueError('structured hours evidence mismatch')
                self.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',
                    (rid,record['kind'],record['city'],record['name'],bool(match),gate['planning_ready'],canonical(record),canonical(gate)))
                for tag in record['tags']:
                    if tag.get('evidence_id') and not self.db.execute('SELECT id FROM evidence WHERE id=?',(tag['evidence_id'],)).fetchone():
                        raise ValueError('unresolved tag evidence')
                    references={}
                    if tag.get('claim_id'):
                        row=self.db.execute('SELECT payload FROM claims WHERE id=?',(tag['claim_id'],)).fetchone()
                        if row:references[tag['claim_id']]=json.loads(row[0])
                    verdict=validate_tag(tag,claims_by_id=references)
                    if not verdict['ok']:raise ValueError(verdict)
                    self.db.execute('INSERT INTO tags VALUES(?,?,?,?)',(rid,tag['tag'],canonical(tag['value']),canonical(tag)))
                count+=1;ready+=gate['planning_ready']
            self.db.execute('INSERT INTO metadata VALUES(?,?)',('imported_at',utcnow()))
        return {'records':count,'planning_ready':ready,'discovery_only':count-ready}
    def load_evidence(self,evidence,claims,*,registry,now=None):
        """Atomic auxiliary load; schema validity and fact eligibility stay separate."""
        with self.db:
            for item in evidence:
                gate=validate_evidence(item)
                if not gate['ok']:raise ValueError(gate)
                self.db.execute('INSERT INTO evidence VALUES(?,?)',(item['evidence_id'],canonical(item)))
            for item in claims:
                row=self.db.execute('SELECT payload FROM evidence WHERE id=?',(item.get('evidence_id'),)).fetchone()
                evidence_by_id={item.get('evidence_id'):json.loads(row[0])} if row else {}
                gate=validate_claim(item,evidence_by_id,registry=registry,now=now)
                if not gate['ok']:raise ValueError(gate)
                self.db.execute('INSERT INTO claims VALUES(?,?,?,?,?)',(item['claim_id'],item['entity_id'],
                    item['evidence_id'],canonical(item),canonical(gate)))
    def search(self,city,kind,*,tag=None,limit=6,include_unverified_city=False,include_reported_closed=False,now=None):
        if not isinstance(limit,int) or not 1<=limit<=40:raise ValueError('limit must be 1..40')
        args=[city,kind];where='r.city=? AND r.kind=?'
        if not include_unverified_city:where+=' AND r.provider_city_match=1'
        if not include_reported_closed:where+=" AND COALESCE(json_extract(r.payload,'$.exclude_from_static_planning'),0)=0"
        if tag:where+=' AND EXISTS(SELECT 1 FROM tags t WHERE t.record_id=r.id AND t.tag=?)';args.append(tag)
        args.append(limit)
        rows=self.db.execute('SELECT r.payload FROM records r WHERE '+where+' ORDER BY r.name,r.id LIMIT ?',args)
        # Re-check current time: a cached planning_ready column never renews facts.
        return [{'record':r,'gate':validate_record(r,now=now)} for r in (json.loads(x[0]) for x in rows)]

