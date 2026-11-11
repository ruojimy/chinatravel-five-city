import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from shorttrip.strict_v4_reader import V4Reader


class V4ReaderTests(unittest.TestCase):
    def test_join_and_dangling_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db.sqlite'
            db = sqlite3.connect(path)
            db.executescript('''CREATE TABLE records(id TEXT, city TEXT, kind TEXT, payload TEXT, gate TEXT);
            CREATE TABLE claims(id TEXT, entity_id TEXT, evidence_id TEXT, payload TEXT, gate TEXT);
            CREATE TABLE evidence(id TEXT, payload TEXT);
            CREATE TABLE tags(record_id TEXT, tag TEXT, value TEXT);''')
            db.execute('INSERT INTO records VALUES(?,?,?,?,?)', ('x','city','attraction','{}','{}'))
            db.execute('INSERT INTO claims VALUES(?,?,?,?,?)', ('c','x','e','{}','{}'))
            db.commit(); db.close()
            reader = V4Reader(path)
            self.assertEqual(reader.first_by_city_kind(['city'], 'attraction'), ['x'])
            with self.assertRaisesRegex(ValueError, 'dangling'):
                reader.get('x')
            reader.close()
            db = sqlite3.connect(path)
            db.execute('INSERT INTO evidence VALUES(?,?)', ('e',json.dumps({'raw_text':'actual'})))
            db.commit(); db.close()
            reader = V4Reader(path)
            self.assertEqual(reader.get('x')['claims'][0]['evidence']['raw_text'], 'actual')
            with self.assertRaises(KeyError): reader.get('missing')
            reader.close()


if __name__ == '__main__': unittest.main()
