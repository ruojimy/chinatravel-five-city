"""Versioned overlay store.

The sandbox CSVs are never modified. Accepted records live in a SQLite overlay
that carries provenance, the gate verdict and a freeze-dried `version` string, so
any plan can be traced back to the exact data it was planned against.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    version TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    note TEXT,
    n_records INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    uid TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    kind TEXT NOT NULL,
    city TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS load_events (
    event_id TEXT PRIMARY KEY, version TEXT, requested_status TEXT, effective_status TEXT,
    verdict TEXT, payload TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    uid TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    retrieved_at TEXT,
    digest TEXT,
    chars INTEGER,
    authority REAL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class OverlayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.last_gate=None

    # New writes are quarantined unless the full current envelope is eligible.
    def add(self, update: dict, status: str = "active", *, now=None,
            allow_synthetic=False) -> str:
        from .bus import envelope_gate
        from ..expansion_contract import validate_evidence
        from uuid import uuid4
        if status not in ('active','quarantine','rejected'):
            raise ValueError('unsupported requested overlay status')
        if not isinstance(update,dict):raise ValueError('update must be an object')
        candidate=update.get('expansion_envelope')
        record=update.get('record')
        if candidate is None:candidate=record
        if isinstance(candidate,dict) and candidate.get('schema_version'):
            value=candidate
        else:value=candidate
        envelope,gate=envelope_gate(value,now=now,allow_synthetic=allow_synthetic)
        if envelope is not None:
            request=update.get('request',{})
            if not isinstance(request,dict):
                gate['errors'].append('request_type')
            else:
                for key in ('kind','city','name'):
                    if key in request and request[key]!=envelope.get(key):
                        gate['errors'].append('request_mismatch:'+key)
            if isinstance(record,dict) and record is not envelope and not record.get('schema_version'):
                _,wrapped=envelope_gate({**record,'expansion_envelope':envelope},now=now,
                                        allow_synthetic=allow_synthetic)
                gate['errors'].extend(e for e in wrapped['errors'] if e not in gate['errors'])
        evidence=update.get('evidence',[])
        if not isinstance(evidence,list):
            gate['errors'].append('evidence_list_required');evidence=[]
        for index,item in enumerate(evidence):
            checked=validate_evidence(item)
            gate['errors'].extend('evidence:'+str(index)+':'+e for e in checked['errors'])
        if gate['errors']:gate['discovery_ok']=False;gate['planning_ready']=False
        effective=('synthetic_fixture' if envelope and envelope.get('synthetic') else 'active') if gate['planning_ready'] and status=='active' else status
        if not gate['planning_ready']:effective='quarantine'
        version='sb-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+uuid4().hex[:8]
        load_gate={**gate,'requested_status':status,'effective_status':effective,
                   'version':version,'real_world_accuracy_certified':False}
        self.last_gate=load_gate
        # Preserve a visible final verdict for the calling pipeline. No source
        # record is enriched or repaired by this operation.
        update['load_gate']=load_gate
        payload=dict(update)
        if envelope is not None:payload['expansion_envelope']=envelope
        try:encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        except (TypeError,ValueError):
            load_gate['planning_ready']=False;load_gate['effective_status']='quarantine'
            load_gate['errors'].append('non_finite_or_non_json_payload')
            effective='quarantine'
            payload={'quarantine_raw_repr':repr(update),'load_gate':load_gate}
            encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        reference=envelope if isinstance(envelope,dict) else (record if isinstance(record,dict) else {})
        def label(key):
            value=reference.get(key)
            return value if isinstance(value,str) and value else 'unknown'
        kind,city,name=label('kind'),label('city'),label('name')
        uid=kind+':'+city+':'+name
        if effective!='active':uid+=':'+effective+':'+version
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)',
                (uid,version,kind,city,name,effective,encoded,
                 json.dumps({'load_gate':load_gate},ensure_ascii=False,allow_nan=False),_now()))
            self.conn.execute('INSERT INTO load_events VALUES(?,?,?,?,?,?,?)',
                (version,version,status,effective,json.dumps(load_gate,ensure_ascii=False),encoded,_now()))
            for item in evidence:
                if not isinstance(item,dict):continue
                source=item.get('source_id',item.get('source'))
                url=item.get('source_url',item.get('url'))
                stamp=item.get('retrieved_at')
                digest=item.get('raw_sha256',item.get('digest'))
                chars=len(item['raw_text']) if isinstance(item.get('raw_text'),str) else None
                authority=item.get('authority')
                if not isinstance(authority,(float,int)) or isinstance(authority,bool):authority=None
                self.conn.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',
                    (uid,str(source) if source is not None else None,
                     str(url) if url is not None else None,str(stamp) if stamp is not None else None,
                     str(digest) if digest is not None else None,chars,authority))
        self._stamp(version,note=name+' ('+kind+'): '+effective,now=now)
        return version

    def _stamp(self,version,note='',*,now=None):
        active=len(self.active(now=now))
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO versions VALUES(?,?,?,?)',(version,_now(),note,active))

    def active(self,kind=None,city=None,*,now=None,allow_synthetic=False):
        """Only qualified envelopes; historical flat active rows never rehydrate."""
        from .bus import envelope_gate
        from ..expansion_contract import validate_evidence
        statuses=('active','synthetic_fixture') if allow_synthetic else ('active',)
        sql='SELECT payload FROM records WHERE status IN ('+','.join('?' for _ in statuses)+')'
        params=list(statuses)
        for column,value in (('kind',kind),('city',city)):
            if value is not None:sql+=' AND '+column+'=?';params.append(value)
        result=[]
        for row in self.conn.execute(sql,params):
            try:
                payload=json.loads(row[0])
                if not isinstance(payload,dict):continue
                value=payload.get('expansion_envelope')
                envelope,gate=envelope_gate(value,now=now,allow_synthetic=allow_synthetic)
                if envelope is not None:
                    request=payload.get('request',{})
                    if not isinstance(request,dict) or any(k in request and request[k]!=envelope.get(k) for k in ('kind','city','name')):
                        gate['planning_ready']=False
                    record=payload.get('record')
                    if isinstance(record,dict) and not record.get('schema_version'):
                        _,wrapped=envelope_gate({**record,'expansion_envelope':envelope},now=now,allow_synthetic=allow_synthetic)
                        if not wrapped['planning_ready']:gate['planning_ready']=False
                    evidence=payload.get('evidence',[])
                    if not isinstance(evidence,list) or any(not validate_evidence(e)['ok'] for e in evidence):
                        gate['planning_ready']=False
            except (TypeError,ValueError,KeyError):continue
            if gate['planning_ready']:result.append(envelope)
        return result

    def historical(self,*,status=None):
        """Read-only evidence access, including legacy rows, with no promotion."""
        sql='SELECT uid,version,status,payload FROM records';params=[]
        if status is not None:sql+=' WHERE status=?';params=[status]
        result=[]
        for uid,version,state,payload in self.conn.execute(sql,params):
            try:value=json.loads(payload)
            except (TypeError,ValueError):value={'unparsed_payload':payload}
            result.append({'uid':uid,'version':version,'status':state,'payload':value,
                           'planning_eligibility_requires_current_gate':True})
        return result

    def quarantine_version(self,version,reason):
        """Ensure a failed live bus patch cannot leave an allegedly active row."""
        with self.conn:
            self.conn.execute("UPDATE records SET status='quarantine' WHERE version=?",(version,))
        if self.last_gate and self.last_gate.get('version')==version:
            self.last_gate['effective_status']='quarantine'
            self.last_gate['planning_ready']=False
            self.last_gate['errors'].append('live_patch_blocked:'+reason)
            self.conn.execute("UPDATE load_events SET effective_status='quarantine',verdict=? WHERE version=?",
                              (json.dumps(self.last_gate,ensure_ascii=False),version))
            self.conn.commit()

    def latest_version(self):
        row=self.conn.execute('SELECT version FROM versions ORDER BY created_at DESC LIMIT 1').fetchone()
        return row[0] if row else None

    def history(self):
        return [{'version':v,'created_at':at,'note':note,'n_records':n}
                for v,at,note,n in self.conn.execute('SELECT version,created_at,note,n_records FROM versions ORDER BY created_at')]

    def summary(self):
        return {'path':str(self.path),'records':self.conn.execute('SELECT COUNT(*) FROM records').fetchone()[0],
          'active':len(self.active()),'stored_active_rows':self.conn.execute("SELECT COUNT(*) FROM records WHERE status='active'").fetchone()[0],
          'quarantine':self.conn.execute("SELECT COUNT(*) FROM records WHERE status='quarantine'").fetchone()[0],
          'evidence':self.conn.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],
          'versions':self.history(),'legacy_rows_are_not_automatically_planning_eligible':True}

