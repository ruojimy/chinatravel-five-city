"""Read-only PID observations; a live PID alone never proves collection work."""
import ctypes, os
from datetime import datetime, timezone
from pathlib import PureWindowsPath


def observe_pid(pid):
    result={'pid':pid,'pid_alive':False,'task_command_verified':False}
    if os.name!='nt':return {**result,'unsupported_platform':True}
    if type(pid) is not int or pid<=0:return {**result,'invalid_pid':True}
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    kernel.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return {**result,'open_process_error':ctypes.get_last_error()}
    try:
        exitcode=w.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(exitcode)) or exitcode.value!=259:return result
        result['pid_alive']=True
        buffer=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(buffer))
        if kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
            result['process_image_name']=PureWindowsPath(buffer.value).name
        times=[w.FILETIME() for _ in range(4)]
        if kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in times]):
            ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            result['created_at']=datetime.fromtimestamp((ticks-116444736000000000)/10000000,timezone.utc).isoformat()
        class Counters(ctypes.Structure):
            _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(k,ctypes.c_size_t) for k in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        psapi=ctypes.WinDLL('psapi',use_last_error=True);psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb):result['working_set_bytes']=counters.WorkingSetSize
        return result
    finally:kernel.CloseHandle(handle)
