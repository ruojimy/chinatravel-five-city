import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from strict_cohort_draft import CITIES, KINDS, generate
from shorttrip.strict_cohort_adapter import diagnose_development_task
from shorttrip.strict_v4_reader import V4Reader


class MutatingReader:
    def __init__(self, reader, mutate):
        self.reader, self.mutate = reader, mutate
        self.calls = 0
        self.entity_ids = []

    def get(self, entity_id):
        self.calls += 1
        self.entity_ids.append(entity_id)
        record = self.reader.get(entity_id)
        return self.mutate(record)


class StrictCohortAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / 'catalog.sqlite3'
        db = sqlite3.connect(self.db_path)
        db.executescript('''
            CREATE TABLE records(id TEXT, city TEXT, kind TEXT, name TEXT, payload TEXT, gate TEXT);
            CREATE TABLE claims(id TEXT, entity_id TEXT, evidence_id TEXT, payload TEXT, gate TEXT);
            CREATE TABLE evidence(id TEXT, payload TEXT);
            CREATE TABLE tags(record_id TEXT, tag TEXT, value TEXT);
        ''')
        rows = []
        for city in CITIES:
            for kind in KINDS:
                # V6 partitions six distinct records per core kind between
                # development (4) and holdout (2); auxiliary kinds also need
                # enough distinct records for their per-split occurrences.
                for number in range(6):
                    rows.append((f'{city}:{kind}:{number}', city, kind,
                                 f'unverified-label-{number}', json.dumps({'data': {}}), '{}'))
        db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?)', rows)
        db.commit()
        db.close()
        self.reader = V4Reader(self.db_path)
        self.draft = generate(self.db_path)
        self.easy = copy.deepcopy(next(t for t in self.draft['tasks']
            if t['purpose'] == 'development' and t['level'] == 'easy'))

    def tearDown(self):
        self.reader.close()
        self.temp.cleanup()

    def diagnose(self, task=None, **kwargs):
        return diagnose_development_task(task or copy.deepcopy(self.easy),
            reader=kwargs.pop('reader', self.reader), now='2026-10-30T00:00:00Z', **kwargs)

    def test_development_candidates_are_checked_without_constructing_a_plan(self):
        result = self.diagnose(identity_verifier=lambda record: True)
        self.assertEqual(result['label'], 'engineering_only')
        self.assertTrue(result['engineering_only'])
        self.assertIsNone(result['formal_score'])
        self.assertFalse(result['frozen'])
        self.assertIn('solver', result['axes'])
        self.assertTrue(any(g['reason'] == 'missing_start_room_route_and_itinerary_context'
                            for g in result['axes']['solver']))
        self.assertEqual(len(result['candidate_checks']),
                         len(self.easy['candidate_selection']['required_entity_ids']))
        self.assertNotIn('plan', result)
        self.assertEqual(result['constraint_mapping']['field_requirements_derived'], [])
        self.assertEqual(result['business_chain_semantics'],
                         'candidate_coverage_only_not_plan_selection_or_order')

    def test_unverified_identity_and_hard_soft_constraint_states_are_preserved(self):
        task = next(copy.deepcopy(t) for t in self.draft['tasks']
                    if t['purpose'] == 'development' and t['level'] == 'medium')
        result = self.diagnose(task)
        self.assertTrue(result['axes']['data'])
        self.assertTrue(any(x['field'] == 'constraint:total_budget'
                            for x in result['unknown_checks']))
        self.assertTrue(result['soft_checks'])
        self.assertTrue(all(x['state'] == 'unknown' for x in result['soft_checks']))

    def test_malformed_task_is_pipeline_error(self):
        task = copy.deepcopy(self.easy)
        task['candidate_selection']['required_entity_ids'] = 'not-a-list'
        result = self.diagnose(task)
        self.assertTrue(result['axes']['pipeline'])
        self.assertEqual(result['axes']['pipeline'][0]['reason'], 'draft_task_schema_invalid')

    def test_missing_catalog_id_is_pipeline_error(self):
        task = copy.deepcopy(self.easy)
        kind = task['required_kinds'][0]
        missing_id = 'does-not-exist'
        task['candidate_selection']['required_entity_ids'][0] = missing_id
        task['generation']['selected_entities_by_kind'][kind]['id'] = missing_id
        task['generation']['business_chain'][0]['entity_id'] = missing_id
        result = self.diagnose(task)
        self.assertTrue(any(g['reason'] == 'candidate_id_not_found'
                            for g in result['axes']['pipeline']))

    def test_reader_id_mismatch_fails_closed(self):
        def mutate(record):
            record['id'] = 'different-id'
            return record
        reader = MutatingReader(self.reader, mutate)
        result = self.diagnose(reader=reader)
        self.assertTrue(any(g['reason'] == 'reader_id_mismatch'
                            for g in result['axes']['pipeline']))

    def test_catalog_kind_or_city_mismatch_is_context_blocked(self):
        def mutate(record):
            record['city'] = 'other-city'
            return record
        result = self.diagnose(reader=MutatingReader(self.reader, mutate))
        self.assertTrue(any(g['reason'] == 'candidate_kind_or_city_mismatch'
                            for g in result['axes']['context']))

    def test_stored_name_metadata_mismatch_is_context_blocked_without_name_lookup(self):
        task = copy.deepcopy(self.easy)
        kind = task['required_kinds'][0]
        task['generation']['selected_entities_by_kind'][kind]['stored_name_unverified'] = 'wrong label'
        reader = MutatingReader(self.reader, lambda record: record)
        result = self.diagnose(task, reader=reader)
        gap = next(g for g in result['axes']['context']
                   if g['reason'] == 'stored_name_metadata_mismatch')
        self.assertTrue(gap['detail']['comparison_only'])
        self.assertEqual(reader.entity_ids[0], task['candidate_selection']['required_entity_ids'][0])
        self.assertEqual(reader.calls, 4)

    def test_malformed_v4_record_is_pipeline_blocked(self):
        def mutate(record):
            record['payload'] = []
            return record
        result = self.diagnose(reader=MutatingReader(self.reader, mutate))
        self.assertTrue(any(g['reason'] == 'v4_record_shape_malformed'
                            for g in result['axes']['pipeline']))

    def test_holdout_is_rejected_before_reader_access(self):
        task = copy.deepcopy(self.easy)
        task['split'] = 'holdout'
        task['purpose'] = 'holdout'
        reader = MutatingReader(self.reader, lambda record: record)
        result = self.diagnose(task, reader=reader)
        self.assertEqual(result['axes']['adapter'][0]['reason'],
                         'holdout_rejected_from_exploratory_adapter')
        self.assertEqual(reader.calls, 0)

    def test_candidate_id_mapping_mismatch_is_pipeline_blocked(self):
        task = copy.deepcopy(self.easy)
        task['candidate_selection']['required_entity_ids'][0] = 'other-id'
        result = self.diagnose(task)
        self.assertTrue(any(g['reason'] == 'business_chain_mapping_mismatch'
                            for g in result['axes']['pipeline']))

    def test_business_chain_order_mismatch_fails_before_reader_access(self):
        task = copy.deepcopy(self.easy)
        task['generation']['business_chain'][0], task['generation']['business_chain'][1] = (
            task['generation']['business_chain'][1], task['generation']['business_chain'][0])
        reader = MutatingReader(self.reader, lambda record: record)
        result = self.diagnose(task, reader=reader)
        self.assertTrue(any(g['reason'] == 'business_chain_mapping_mismatch'
                            for g in result['axes']['pipeline']))
        self.assertEqual(reader.calls, 0)

    def test_business_chain_id_must_match_kind_mapping_and_required_id(self):
        task = copy.deepcopy(self.easy)
        task['generation']['business_chain'][0]['entity_id'] = 'different-id'
        result = self.diagnose(task)
        gap = next(g for g in result['axes']['pipeline']
                   if g['reason'] == 'business_chain_mapping_mismatch')
        self.assertEqual(gap['detail']['reason'], 'business_chain_entity_id_mismatch')

    def test_exactly_one_auxiliary_kind_must_follow_the_three_kind_chain(self):
        task = copy.deepcopy(self.easy)
        task['generation']['auxiliary_kind'] = 'restaurant'
        result = self.diagnose(task)
        gap = next(g for g in result['axes']['pipeline']
                   if g['reason'] == 'business_chain_mapping_mismatch')
        self.assertEqual(gap['detail']['reason'], 'auxiliary_kind_invalid')


if __name__ == '__main__':
    unittest.main()
