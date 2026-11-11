import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.process_status import observe_pid

class ProcessObservation(unittest.TestCase):
 @unittest.skipUnless(os.name=='nt','Windows query only')
 def test_current_process_is_alive_without_claiming_task_identity(self):
  result=observe_pid(os.getpid())
  self.assertTrue(result['pid_alive']);self.assertFalse(result['task_command_verified'])
  self.assertTrue(result['process_image_name'].lower().endswith('.exe'));self.assertIn('created_at',result)
 def test_invalid_pid_is_not_a_running_collector(self):
  self.assertFalse(observe_pid(-1)['pid_alive']);self.assertFalse(observe_pid(None)['pid_alive'])
if __name__=='__main__':unittest.main()
