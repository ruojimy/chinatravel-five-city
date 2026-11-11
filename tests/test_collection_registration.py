"""Offline registration regression: hashed failures never grant access."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import collection_agent
from shorttrip.collection_workflow import AgentMemory


class _Output(io.StringIO):
    def reconfigure(self, **_kwargs):
        pass


class SourceRegistrationTests(unittest.TestCase):
    def test_pending_source_preflight_cannot_reserve_a_business_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AgentMemory(Path(tmp) / 'agent.sqlite3')
            try:
                ledger.begin_run('run', {'web_action': 5, 'api_http': 0})
                with self.assertRaisesRegex(ValueError, 'source_preflight_required'):
                    ledger.reserve('run', 'root-search', 'https://unknown.invalid/',
                                   'web_action', action='search')
                for action in ('robots', 'search'):
                    with self.subTest(action=action):
                        with self.assertRaisesRegex(ValueError, 'preflight_url_out_of_scope'):
                            ledger.reserve('run', action, 'https://unknown.invalid/business',
                                           'web_action', action=action)
                with self.assertRaisesRegex(ValueError, 'preflight_url_out_of_scope'):
                    ledger.reserve('run', 'malformed', '\nhttps://unknown.invalid/robots.txt',
                                   'web_action', action='robots')
                self.assertTrue(ledger.reserve('run', 'robots-ok', 'https://unknown.invalid/robots.txt',
                                               'web_action', action='robots')['allowed'])
                ledger.finish('robots-ok', 'failed', error='tool inaccessible')
                with self.assertRaisesRegex(ValueError, 'source_preflight_required'):
                    ledger.reserve('run', 'fetch', 'https://unknown.invalid/business',
                                   'web_action', field='identity', action='fetch')
            finally:
                ledger.close()

    def test_failed_hashed_reviews_cannot_activate_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = root / 'memory'
            reviews = {}
            for key, content in [('robots_artifact', b'HTTP 403 Forbidden'),
                                 ('terms_review_artifact', b'TERMS REVIEW FAILED')]:
                p = root / (key + '.txt')
                p.write_bytes(content)
                reviews[key] = {'path': p.name, 'sha256': hashlib.sha256(content).hexdigest()}
            profile = {'family': 'audit.invalid', 'domains': ['audit.invalid'],
                       'supports': ['identity'], 'status': 'accessible', 'access_review': reviews}
            path = root / 'profile.json'
            path.write_text(json.dumps(profile), encoding='utf-8')
            with patch.object(collection_agent, 'ROOT', root), patch.object(collection_agent, 'MEM', memory):
                with patch('sys.argv', ['collection_agent.py', 'register-source', str(path)]), \
                        patch('sys.stdout', _Output()):
                    with self.assertRaisesRegex(ValueError, 'accessible registration is blocked'):
                        collection_agent.main()
                ledger = AgentMemory(memory / 'agent.sqlite3')
                try:
                    self.assertFalse(ledger.source_check('https://audit.invalid/page', 'identity')['allowed'])
                    self.assertFalse(ledger.source_check('https://audit.invalid/', action='search')['allowed'])
                    self.assertEqual(ledger.db.execute('select count(*) from sources').fetchone()[0], 0)
                finally:
                    ledger.close()

                profile['status'] = 'unknown'
                path.write_text(json.dumps(profile), encoding='utf-8')
                with patch('sys.argv', ['collection_agent.py', 'register-source', str(path)]), \
                        patch('sys.stdout', _Output()):
                    collection_agent.main()
                ledger = AgentMemory(memory / 'agent.sqlite3')
                try:
                    self.assertFalse(ledger.source_check('https://audit.invalid/page', 'identity')['allowed'])
                    stored = json.loads(ledger.db.execute('select payload from sources').fetchone()[0])
                    self.assertFalse(stored['live_fetch_authorized'])
                    self.assertTrue(stored['preflight_required'])
                finally:
                    ledger.close()

