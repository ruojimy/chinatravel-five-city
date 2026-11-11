"""Read immutable v4 records and their actual claim/evidence joins.

Reading a row does not certify it. Bad JSON or dangling references are pipeline
errors, and callers must never replace them with an empty set of claims.
"""
from pathlib import Path
import json
import sqlite3


class V4Reader:
    def __init__(self, catalog):
        path = Path(catalog).resolve(strict=True)
        self.db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def get(self, entity_id):
        row = self.db.execute('SELECT * FROM records WHERE id=?', (entity_id,)).fetchone()
        if row is None:
            raise KeyError(entity_id)
        record = dict(row)
        record['payload'] = json.loads(record['payload'])
        record['gate'] = json.loads(record['gate'])
        items = []
        for item in self.db.execute('SELECT * FROM claims WHERE entity_id=? ORDER BY id', (entity_id,)):
            claim = dict(item)
            claim['payload'] = json.loads(claim['payload'])
            claim['gate'] = json.loads(claim['gate'])
            evidence = self.db.execute('SELECT payload FROM evidence WHERE id=?', (claim['evidence_id'],)).fetchone()
            if evidence is None:
                raise ValueError('dangling evidence: ' + str(claim['evidence_id']))
            claim['evidence'] = json.loads(evidence['payload'])
            items.append(claim)
        record['claims'] = items
        record['tags'] = [dict(x) for x in self.db.execute('SELECT * FROM tags WHERE record_id=? ORDER BY tag,value', (entity_id,))]
        return record

    def first_by_city_kind(self, cities, kind):
        result = []
        for city in cities:
            row = self.db.execute('SELECT id FROM records WHERE city=? AND kind=? ORDER BY id LIMIT 1', (city, kind)).fetchone()
            if row is None:
                raise ValueError('no record for ' + city + '/' + kind)
            result.append(row['id'])
        return result
