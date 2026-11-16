"""Profile selection is explicit and corrupted evidence cannot be activated."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import copy,json,os,subprocess,sys,unittest

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
from g3_sandbox import configure

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.profile=self.root/'profile';self.data=self.profile/'data_integration'
        self.db=self.profile/'expanded/G3_ext11/chinatravel/environment/database'
        self.data.mkdir(parents=True);self.db.mkdir(parents=True)
        self.engine=self.root/'engine';(self.engine/'chinatravel').mkdir(parents=True)
        self.proof=self.data/'proof.json';self.proof.write_bytes(b'good evidence')
        self.direct=self.db/'sample.json';self.direct.write_bytes(b'good data')
        self.snap={'schema':'chinatravel-dynamic-snapshot-v4.2',
          'evidence_files':[{'path':'proof.json','sha256':sha256(self.proof.read_bytes()).hexdigest()}],
          'changed_direct_files':[{'path':self.direct.relative_to(self.profile).as_posix(),
                                   'after_sha256':sha256(self.direct.read_bytes()).hexdigest()}]}
        self.save()
    def tearDown(self):self.temp.cleanup()
    def save(self):
        (self.data/'dynamic_snapshot_v2.json').write_text(json.dumps(self.snap),encoding='utf-8')
    def test_selected_profile_sets_only_given_environment(self):
        env={};result=configure(self.profile,engine=self.engine,environ=env)
        self.assertEqual(env['CHINATRAVEL_PROFILE'],'expanded11')
        self.assertEqual(Path(env['CHINATRAVEL_DATABASE_ROOT']),self.db)
        self.assertEqual(result['mode'],'snapshot')
        self.assertNotIn('CT_DYNAMIC_LIVE_DIR',env)
    def test_changed_evidence_and_direct_data_are_refused(self):
        self.proof.write_bytes(b'tampered')
        with self.assertRaises(ValueError):configure(self.profile,engine=self.engine,environ={})
        self.proof.write_bytes(b'good evidence');self.direct.write_bytes(b'tampered')
        with self.assertRaises(ValueError):configure(self.profile,engine=self.engine,environ={})
    def test_parent_traversal_is_refused(self):
        self.snap['evidence_files'][0]['path']='../outside.json';self.save()
        with self.assertRaises(ValueError):configure(self.profile,engine=self.engine,environ={})
    def test_unknown_snapshot_schema_is_refused(self):
        self.snap['schema']='unrecognized';self.save()
        with self.assertRaises(ValueError):configure(self.profile,engine=self.engine,environ={})
    def test_live_journal_cannot_modify_immutable_profile(self):
        with self.assertRaises(ValueError):
            configure(self.profile,engine=self.engine,live_dir=self.profile/'journal',environ={})
    def test_inventory_catches_other_changed_or_added_files(self):
        files={p.relative_to(self.profile).as_posix():sha256(p.read_bytes()).hexdigest()
               for p in self.profile.rglob('*') if p.is_file()}
        inventory=self.profile/'profile_file_hashes.json'
        inventory.write_text(json.dumps(files),encoding='utf-8')
        configure(self.profile,engine=self.engine,environ={})
        (self.db/'unrecorded.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):configure(self.profile,engine=self.engine,environ={})

class NativeDefaultTests(unittest.TestCase):
    def test_unconfigured_native_remains_ten_cities(self):
        env=dict(os.environ)
        for key in ('CHINATRAVEL_PROFILE','CHINATRAVEL_DATABASE_ROOT','CHINATRAVEL_DATABASE_ROOT_EN',
                    'CT_SANDBOX_PROFILE_ROOT','CT_SANDBOX_ENGINE_ROOT','CT_SANDBOX_RUNTIME_DIR'):
            env.pop(key,None)
        code=("import sys;sys.path.insert(0,sys.argv[1]);"
              "from chinatravel.environment.language import CITY_NAMES,CITY_SLUGS;"
              "assert len(CITY_SLUGS)==len(CITY_NAMES['zh'])==len(CITY_NAMES['en'])==10")
        subprocess.run([sys.executable,'-c',code,str(REPO/'ShortTrip-upstream')],env=env,check=True)

if __name__=='__main__':unittest.main()
