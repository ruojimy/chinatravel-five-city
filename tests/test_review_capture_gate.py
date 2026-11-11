"""Approval must not proceed after a failed original-capture audit."""
import hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('capture_gate_review',ROOT/'scripts/p17_review_batch.py')
reviewer=importlib.util.module_from_spec(spec);spec.loader.exec_module(reviewer)

class CaptureGate(unittest.TestCase):
 def test_unreviewed_packet_fails_before_any_catalogue_or_registry_write(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);res=root/'results/p17_continuous';res.mkdir(parents=True)
   packet=res/'packet.json';packet.write_text(json.dumps({'sources':[{'source_id':'p17-ctrip-card:test'}],'assertions':[]}))
   oldroot,oldres=reviewer.ROOT,reviewer.RES;reviewer.ROOT,reviewer.RES=root,res
   try:
    with self.assertRaisesRegex(ValueError,'audit receipt required'):reviewer._review(packet,'never_approved')
    self.assertFalse((res/'approved_batches').exists())
   finally:reviewer.ROOT,reviewer.RES=oldroot,oldres

 def test_changed_packet_cannot_reuse_an_earlier_successful_audit(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);res=root/'results/p17_continuous';res.mkdir(parents=True)
   packet=res/'packet.json';packet.write_text(json.dumps({'sources':[{'source_id':'p17-feinfood-provider:test'}],'assertions':[]}))
   digest=hashlib.sha256(packet.read_bytes()).hexdigest()
   (res/'root_capture_audit.json').write_text(json.dumps({'passed':True,'packet_sha256':digest}))
   packet.write_text(packet.read_text()+'\n')
   oldroot,oldres=reviewer.ROOT,reviewer.RES;reviewer.ROOT,reviewer.RES=root,res
   try:
    with self.assertRaisesRegex(ValueError,'does not cover these packet bytes'):reviewer._review(packet,'never_approved')
    self.assertFalse((res/'approved_batches').exists())
   finally:reviewer.ROOT,reviewer.RES=oldroot,oldres
if __name__=='__main__':unittest.main()
