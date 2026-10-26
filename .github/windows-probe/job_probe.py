# Copied from aigengame/godot-agent#1225, the reporter's probe of 2026-10-25, with the
# formatter applied and nothing else changed. Temporary: it goes with the probe job.
"""Does gda's Job ownership hold for a given Python interpreter?

Mirrors windows_process.py: a KILL_ON_JOB_CLOSE Job, a worker launched with
CREATE_NO_WINDOW, the worker's reported pid assigned to the Job, a child spawned by
the worker after assignment, then TerminateJobObject. Reports whether each process
was in the Job, its kernel parent pid and package identity, and whether the child
survived.

Usage: python -I job_probe.py [--assign-child] <interpreter> [<interpreter> ...]

--assign-child: when the child is not in the Job, assign it from this process too,
then check membership and TerminateJobObject as before.
"""

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateJobObjectW.restype = wintypes.HANDLE
k.OpenProcess.restype = wintypes.HANDLE
k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k.GetPackageFullName.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_uint32),
    wintypes.LPWSTR,
]
k.GetPackageFullName.restype = ctypes.c_long


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def parent_of(pid):
    """The kernel's parent pid for a live process, from a Toolhelp snapshot."""
    snapshot = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    try:
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return None


def package_of(handle):
    """GetPackageFullName with a zero-length buffer: 15700 = no identity, 122 = identity."""
    length = ctypes.c_uint32(0)
    code = k.GetPackageFullName(handle, ctypes.byref(length), None)
    if code != 122:
        return {"code": code}
    name = ctypes.create_unicode_buffer(length.value)
    second = k.GetPackageFullName(handle, ctypes.byref(length), name)
    return {"code": code, "name": name.value if second == 0 else f"error {second}"}


class Basic(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class Extended(ctypes.Structure):
    _fields_ = [
        ("basic", Basic),
        ("io", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


ACCESS = (
    0x0100 | 0x0001 | 0x1000 | 0x00100000
)  # SET_QUOTA | TERMINATE | QUERY_LIMITED | SYNCHRONIZE


def in_job(handle, job):
    result = wintypes.BOOL()
    ok = k.IsProcessInJob(handle, job, ctypes.byref(result))
    return bool(result.value) if ok else f"error {ctypes.get_last_error()}"


def probe(interpreter):
    report = {"interpreter": interpreter}
    job = k.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    worker = subprocess.Popen(
        [interpreter, "-I", str(Path(__file__).with_name("job_worker.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    child_handle = None
    try:
        hello = json.loads(worker.stdout.readline())
        report["launcher_pid"], report["worker_pid"] = worker.pid, hello["worker_pid"]
        report["worker_exe"] = hello["exe"]
        launcher = k.OpenProcess(ACCESS, False, worker.pid)
        report["launcher_package"] = package_of(launcher)
        k.CloseHandle(launcher)
        handle = k.OpenProcess(ACCESS, False, hello["worker_pid"])
        report["worker_parent_pid"] = parent_of(hello["worker_pid"])
        report["worker_package"] = package_of(handle)
        report["worker_in_any_job_before"] = in_job(handle, None)
        assigned = k.AssignProcessToJobObject(job, handle)
        report["assign_ok"] = bool(assigned) or f"error {ctypes.get_last_error()}"
        report["worker_in_job"] = in_job(handle, job)
        worker.stdin.write(b"go\n")
        worker.stdin.flush()
        child_pid = json.loads(worker.stdout.readline())["child_pid"]
        child_handle = k.OpenProcess(ACCESS, False, child_pid)
        report["child_in_job"] = in_job(child_handle, job)
        report["child_in_any_job"] = in_job(child_handle, None)
        report["child_parent_pid"] = parent_of(child_pid)
        report["child_package"] = package_of(child_handle)
        if "--assign-child" in sys.argv and not report["child_in_job"]:
            assigned = k.AssignProcessToJobObject(job, child_handle)
            report["child_assign_ok"] = (
                bool(assigned) or f"error {ctypes.get_last_error()}"
            )
            report["child_in_job_after_assign"] = in_job(child_handle, job)
        k.TerminateJobObject(job, 1)
        time.sleep(1.5)
        report["child_survived_terminate"] = (
            k.WaitForSingleObject(child_handle, 0) == 0x102
        )
    finally:
        if child_handle:
            k.TerminateProcess(child_handle, 1)
            k.CloseHandle(child_handle)
        worker.kill()
        k.CloseHandle(job)
    return report


if __name__ == "__main__":
    for interp in sys.argv[1:]:
        if interp.startswith("--"):
            continue
        print(json.dumps(probe(interp), indent=1))
