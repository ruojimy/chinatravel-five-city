"""Budgeted route lookup uses pinned station evidence without leaking keys."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json,os,sqlite3,sys,unittest

REPO=Path(__file__).resolve().parents[1]
profile=os.environ.get('CT_SANDBOX_TEST_PROFILE')
if not profile:raise unittest.SkipTest('set CT_SANDBOX_TEST_PROFILE to a verified profile')
sys.path.insert(0,str(REPO/'scripts'))
from g3_sandbox import configure
configure(profile)
sys.path.insert(0,str(REPO/'src/sandbox_runtime'))
import dynamic_live

class Response:
    def __init__(self,payload):self.raw=json.dumps(payload).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.raw

class LiveRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.path=Path(self.tmp.name)
        self.key=self.path/'key';self.key.write_text('example-private-key',encoding='ascii')
    def tearDown(self):self.tmp.cleanup()
    def test_pinned_anchors_and_budgeted_cache(self):
        anchors=dynamic_live.load_anchors(Path(profile))
        self.assertTrue({'西安','杭州','南京'}.issubset(anchors))
        calls=[]
        def opener(req,timeout):
            calls.append(req.full_url)
            return Response({'status':'1','infocode':'10000','route':{'transits':[]}})
        kwargs={'run_dir':self.path/'journal','key_path':self.key,'opener':opener,'budget':1}
        first=dynamic_live.lookup_route('杭州','西安','train',**kwargs)
        again=dynamic_live.lookup_route('杭州','西安','train',**kwargs)
        exhausted=dynamic_live.lookup_route('南京','西安','train',**kwargs)
        self.assertEqual((first['status'],again['status'],exhausted['status']),('ok','cache_hit','budget_exhausted'))
        self.assertEqual(len(calls),1)
        data=(self.path/'journal/dynamic_live.sqlite3').read_bytes()
        self.assertNotIn(b'example-private-key',data)
    def test_provider_rejection_pauses_without_key_rotation(self):
        def opener(req,timeout):return Response({'status':'0','infocode':'10021'})
        kwargs={'run_dir':self.path/'journal','key_path':self.key,'opener':opener,'budget':4}
        self.assertEqual(dynamic_live.lookup_route('杭州','西安','train',**kwargs)['status'],'provider_error')
        self.assertEqual(dynamic_live.lookup_route('南京','西安','train',**kwargs)['status'],'provider_paused')

if __name__=='__main__':unittest.main()
