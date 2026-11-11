import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess,sys,unittest
import driver

class Coordinator(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows process tree behavior')
    def test_timeout_kills_actual_venv_interpreter(self):
        child=subprocess.Popen([sys.executable,'-B','-c','import os,time;print(os.getpid(),flush=True);time.sleep(120)'],stdout=subprocess.PIPE,text=True)
        pid=int(child.stdout.readline().strip())
        self.assertIsNone(child.poll())
        driver.stop_tree(child)
        self.assertIsNotNone(child.poll())
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if handle:
            code=wintypes.DWORD()
            kernel.GetExitCodeProcess(handle,ctypes.byref(code));kernel.CloseHandle(handle)
            self.assertNotEqual(code.value,259,'Real child survived parent timeout')
        child.stdout.close()

if __name__=='__main__':unittest.main()
