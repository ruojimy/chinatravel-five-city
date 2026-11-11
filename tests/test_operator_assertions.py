import copy,hashlib,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.operator_assertions import VERSION,validate_assertion,check_graph,exact_source_quote,load_approved
from shorttrip.expansion_contract import validate_record
from shorttrip.expansion_store import ExpansionStore
class Assertions(unittest.TestCase):
 def fixture(self):
  raw='Superior Room: two single beds\r\nClosed Monday';digest=hashlib.sha256(raw.encode()).hexdigest()
  x={'schema_version':VERSION,'assertion_id':'a','entity_id':'existing','field':'bed_configuration','value':2,'unit':'beds',
    'scope':'superior twin option only','quote':'two single beds','context':{'room_type':'superior','option':'twin'},
    'source_id':'official','source_url':'https://example.org/rooms','source_published_at':None,'source_updated_at':None,
    'observed_at':None,'retrieved_at':'2026-10-22T15:00:00+00:00','valid_from':None,'valid_until':None,
    'source_date_text':None,'policy_id':'room_configuration','ttl_seconds':2592000,'authority':'primary_operator',
    'licence_status':'public_source_reuse_unverified','capture':{'file':'e.txt','sha256':digest,'representation':'web_tool_text'},
    'evidence_id':'e','native_values':{'numbed':2}}
  ev={'evidence_id':'e','raw_text':raw,'raw_sha256':digest,**{k:x[k] for k in ('source_id','source_url','source_published_at','source_updated_at','observed_at','retrieved_at','authority','licence_status')}}
  return x,ev
 def test_full_assertion_and_graph(self):
  x,e=self.fixture();self.assertTrue(validate_assertion(x)['ok']);self.assertTrue(check_graph(x,e)['ok'])
 def test_explicit_recommended_hour_range_is_preserved(self):
  x,e=self.fixture();x['native_values']={'recommendmintime':1.5,'recommendmaxtime':2};self.assertTrue(validate_assertion(x)['ok'])
 def test_duration_requires_both_endpoints_and_finite_positive_order(self):
  for values in ({'recommendmintime':1},{'recommendmintime':3,'recommendmaxtime':2},{'recommendmintime':0,'recommendmaxtime':2},{'recommendmintime':float('nan'),'recommendmaxtime':2}):
   x,e=self.fixture();x['native_values']=values;self.assertFalse(validate_assertion(x)['ok'])
 def test_invalid_duration_type_returns_gate_without_throwing(self):
  x,e=self.fixture();x['native_values']={'recommendmintime':'one','recommendmaxtime':2};self.assertFalse(validate_assertion(x)['ok'])
 def test_review_registry_hash_and_source_clocks(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);batchdir=root/'results/p17_continuous/approved_batches';batchdir.mkdir(parents=True)
   x,e=self.fixture();capture=root/'results/p17_continuous/capture.txt';capture.write_bytes(e['raw_text'].encode())
   x['capture']['file']=str(capture.relative_to(root));x['capture']['representation']='saved_original_json_row'
   x['native_values']={'cuisine':'Chinese coarse reference'}
   batch=batchdir/'one.json';batch.write_text(json.dumps({'assertions':[x]}),encoding='utf-8')
   index=batchdir/'index.json';index.write_text(json.dumps({'batches':[{'file':str(batch.relative_to(root)),'sha256':hashlib.sha256(batch.read_bytes()).hexdigest()}]}),encoding='utf-8')
   grouped,evs=load_approved(root);self.assertIsNone(grouped['existing'][0]['observed_at']);self.assertEqual(evs['e']['raw_text'],e['raw_text'])
   batch.write_text('{}',encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'Approved batch changed'):load_approved(root)
 def test_review_registry_cannot_escape(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);batchdir=root/'results/p17_continuous/approved_batches';batchdir.mkdir(parents=True)
   (batchdir/'index.json').write_text(json.dumps({'batches':[{'file':'outside.json','sha256':'0'*64}]}),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'outside approved'):load_approved(root)
 def test_review_registry_rejects_changed_original_capture(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);batchdir=root/'results/p17_continuous/approved_batches';batchdir.mkdir(parents=True)
   x,e=self.fixture();capture=root/'results/p17_continuous/capture.txt';capture.write_bytes(b'Changed bed count')
   x['capture']['file']=str(capture.relative_to(root));batch=batchdir/'one.json';batch.write_text(json.dumps({'assertions':[x]}),encoding='utf-8')
   (batchdir/'index.json').write_text(json.dumps({'batches':[{'file':str(batch.relative_to(root)),'sha256':hashlib.sha256(batch.read_bytes()).hexdigest()}]}),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'source text changed'):load_approved(root)
 def test_every_required_key(self):
  x,e=self.fixture()
  for key in x:
   bad=copy.deepcopy(x);del bad[key];self.assertFalse(validate_assertion(bad)['ok'],key)
 def test_unknown_fact_clock_allowed_not_renewed(self):
  x,e=self.fixture();self.assertIsNone(x['observed_at']);self.assertTrue(validate_assertion(x)['ok'])
 def test_wrong_ttl(self):
  x,e=self.fixture();x['ttl_seconds']=99999999;self.assertFalse(validate_assertion(x)['ok'])
 def test_unsupported_native_hour_projection(self):
  x,e=self.fixture();x['native_values']={'opentime':'09:00'};self.assertFalse(validate_assertion(x)['ok'])
 def test_zero_or_bool_bed_count(self):
  for value in (0,True,-1):
   x,e=self.fixture();x['native_values']={'numbed':value};self.assertFalse(validate_assertion(x)['ok'])
 def test_price_nan(self):
  x,e=self.fixture();x['native_values']={'price':float('nan')};self.assertFalse(validate_assertion(x)['ok'])
 def test_bad_quote(self):
  x,e=self.fixture();x['quote']='three beds';self.assertFalse(check_graph(x,e)['ok'])
 def test_wrong_source_or_clock(self):
  x,e=self.fixture();x['retrieved_at']='2026-10-22T15:01:00+00:00';self.assertFalse(check_graph(x,e)['ok'])
 def test_wrong_digest(self):
  x,e=self.fixture();x['capture']['sha256']='0'*64;self.assertFalse(check_graph(x,e)['ok'])
 def test_crlf_bytes_remain_exact(self):
  x,e=self.fixture();self.assertNotEqual(hashlib.sha256(e['raw_text'].replace('\r\n','\n').encode()).hexdigest(),x['capture']['sha256']);self.assertTrue(check_graph(x,e)['ok'])
 def test_quote_can_restore_original_crlf(self):self.assertEqual(exact_source_quote('one\r\ntwo','one\ntwo'),'one\r\ntwo')
 def test_quote_cannot_change_words(self):
  with self.assertRaises(ValueError):exact_source_quote('one\r\ntwo','one\nthree')
 def test_real_loader_rejects_unresolved_operator_evidence(self):
  path=ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3';db=sqlite3.connect(path)
  r=json.loads(db.execute('SELECT payload FROM records LIMIT 1').fetchone()[0]);db.close();x,e=self.fixture();x['entity_id']=r['record_id'];r['operator_assertions']=[x]
  self.assertTrue(validate_record(r)['discovery_ok']);self.assertFalse(validate_record(r)['planning_ready'])
  with tempfile.TemporaryDirectory() as tmp:
   store=ExpansionStore(Path(tmp)/'store.sqlite',create=True)
   # All legacy evidence is copied so rejection is specific to the new graph.
   src=sqlite3.connect(path);store.load_evidence((json.loads(v[0]) for v in src.execute('SELECT payload FROM evidence')),[],registry={});src.close()
   with self.assertRaises(ValueError):store.load([r])
   self.assertEqual(store.db.execute('SELECT count(*) FROM records').fetchone()[0],0);store.close()
if __name__=='__main__':unittest.main(verbosity=2)
