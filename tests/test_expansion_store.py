"""Write-boundary and offline lookup tests; fixtures never count as new places."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from test_expansion_contract import fixture,NOW
from shorttrip.expansion_store import ExpansionStore
from shorttrip.travel_catalog import TravelCatalog
from shorttrip.live_amap import LiveAmapClient
from shorttrip.expansion_contract import validate_inline_claim
from shorttrip.static_lookup import lookup,verification_tasks

class StoreTests(unittest.TestCase):
    def test_reported_closed_reference_is_retained_but_excluded_from_default_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);r=fixture('restaurant')
            r['exclude_from_static_planning']=True;r['operational_status']='reported_closed_reopening_unverified'
            s.load([r],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],1)
            self.assertEqual(s.search(r['city'],r['kind'],include_unverified_city=True,now=NOW),[])
            rows=s.search(r['city'],r['kind'],include_unverified_city=True,include_reported_closed=True,now=NOW)
            self.assertEqual(len(rows),1);self.assertFalse(rows[0]['gate']['planning_ready'])
            self.assertIn('reported_closure_requires_reopening_evidence',rows[0]['gate']['planning_blockers']);s.close()
    def test_new_tag_with_missing_evidence_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);r=fixture()
            r['tags'][0]['evidence_id']='missing'
            with self.assertRaisesRegex(ValueError,'unresolved tag evidence'):s.load([r],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],0);s.close()
    def test_structured_hours_with_missing_evidence_rolls_back(self):
        from shorttrip.scoped_business import today_hours
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);r=fixture('restaurant')
            h=today_hours('09:00-17:00');h.update(schema_version='business-hours-v1',entity_id=r['record_id'],
               source_id=r['source_id'],source_url=r['source_url'],evidence_id='missing',
               raw_rule_sha256=hashlib.sha256(h['raw'].encode()).hexdigest(),observed_at=NOW,
               source_updated_at=None,retrieved_at=NOW,policy_id='opening_hours',ttl_seconds=86400,
               valid_until=None,provider_request_date='2026-10-22')
            r['today_hours_structured']=h
            with self.assertRaisesRegex(ValueError,'unresolved structured hours evidence'):s.load([r],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],0);s.close()
    def test_invalid_second_row_rolls_back_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True)
            a=fixture();b=fixture('restaurant');del b['data']['price']
            with self.assertRaises(ValueError):s.load([a,b],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],0);s.close()
    def test_discovery_unknowns_preserved_readonly_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'c.sqlite3';s=ExpansionStore(path,create=True)
            r=fixture(complete=False);r['source_locator']['provider_city_match']=True
            s.load([r],now=NOW);s.close();before=path.read_bytes()
            s=ExpansionStore(path);got=s.search('合成测试城','attraction',now=NOW)
            self.assertIsNone(got[0]['record']['data']['price']);self.assertFalse(got[0]['gate']['planning_ready'])
            s.close();self.assertEqual(before,path.read_bytes())
    def test_uncertain_city_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);s.load([fixture()],now=NOW)
            self.assertEqual(s.search('合成测试城','attraction',now=NOW),[])
            self.assertEqual(len(s.search('合成测试城','attraction',include_unverified_city=True,now=NOW)),1);s.close()
    def test_snapshot_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'c.sqlite3';s=ExpansionStore(path,create=True);s.close()
            with self.assertRaises(FileExistsError):ExpansionStore(path,create=True)
    def test_tag_reference_cannot_bypass_claim_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);r=fixture();r['tags'][0]['claim_id']='absent'
            with self.assertRaises(ValueError):s.load([r],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],0);s.close()
    def test_claim_with_missing_evidence_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True)
            with self.assertRaises(ValueError):s.load_evidence([], [{'claim_id':'bad','evidence_id':'none'}],registry={},now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM claims').fetchone()[0],0);s.close()
    def test_field_provenance_unresolved_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ExpansionStore(Path(tmp)/'c.sqlite3',create=True);r=fixture()
            r['field_provenance']['price'].update(source_id='other',source_url='https://other.invalid',evidence_id='missing')
            with self.assertRaises(ValueError):s.load([r],now=NOW)
            self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0],0);s.close()
    def test_weather_and_route_tasks_not_suppressed(self):
        result={'city':'合成测试城','candidates':[{'record':fixture()}]}
        tasks=verification_tasks(result,travel_date='2026-10-23')
        self.assertTrue(any(x.get('provider')=='amap' and x.get('mandatory') for x in tasks))
        self.assertTrue(any(x['field']=='weather_forecast' and x.get('mandatory') for x in tasks))
    def test_unknown_tag_survives_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'c.sqlite3';s=ExpansionStore(path,create=True);r=fixture();r['source_locator']['provider_city_match']=True
            s.load([r],now=NOW);s.close()
            got=lookup(path,'合成测试城','attraction',tag='wheelchair',limit=3,now=NOW)
            self.assertEqual(len(got['candidates']),1);self.assertEqual(got['uncovered_query_tags'],['wheelchair'])

class InlineClaimTests(unittest.TestCase):
    def make(self):
        return LiveAmapClient._claim('weather_now',{'temperature':'20'},'weather:330100',{'adcode':'330100'},
            {'status':'1','lives':[]},{'endpoint':'https://restapi.amap.com/v3/weather/weatherInfo','retrieved_at':NOW},observed_at=NOW)
    def test_amap_generated_claim_has_complete_structural_provenance(self):
        self.assertTrue(validate_inline_claim(self.make())['ok'])
    def test_legacy_missing_contract_rejected_on_new_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            cat=TravelCatalog(Path(tmp)/'c.sqlite3');r=self.make();del r['evidence_id']
            with self.assertRaises(ValueError):cat.add_claim(r)
            self.assertEqual(cat.db.execute('SELECT count(*) FROM claims').fetchone()[0],0);cat.close()
    def test_tampered_raw_hash_rejected(self):
        r=self.make();r['raw_text']='changed';self.assertFalse(validate_inline_claim(r)['ok'])
    def test_wrong_evidence_id_type_is_structurally_rejected(self):
        r=self.make();r['evidence_id']=[]
        self.assertFalse(validate_inline_claim(r)['ok'])
    def test_same_id_different_data_does_not_hide_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            cat=TravelCatalog(Path(tmp)/'c.sqlite3');r=self.make();cat.add_claim(r);cat.add_claim(r)
            other=copy.deepcopy(r);other['value']={'temperature':'99'}
            with self.assertRaises(ValueError):cat.add_claim(other)
            self.assertEqual(cat.db.execute('SELECT count(*) FROM claims').fetchone()[0],1);cat.close()

if __name__=='__main__':unittest.main(verbosity=2)
