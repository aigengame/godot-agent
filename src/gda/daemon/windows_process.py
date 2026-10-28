"""Windows Engine-session ownership through one private Job joined at creation.

The daemon creates the engine with ``PROC_THREAD_ATTRIBUTE_JOB_LIST``, so the
engine is in the Job before any of its code runs. Ownership does not depend on
Job inheritance, which a parent with MSIX package identity does not give its
children (#1225). The daemon owns the native process and Job handles. No process
scans, private Popen handles or exit-code proxy.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from ctypes import wintypes as w
from typing import Any

from gda.daemon import win32


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", w.DWORD),
        ("min_ws", ctypes.c_size_t),
        ("max_ws", ctypes.c_size_t),
        ("active_limit", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("user_time", ctypes.c_longlong),
        ("kernel_time", ctypes.c_longlong),
        ("period_user", ctypes.c_longlong),
        ("period_kernel", ctypes.c_longlong),
        ("page_faults", w.DWORD),
        ("total", w.DWORD),
        ("active", w.DWORD),
        ("terminated", w.DWORD),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("x_size", w.DWORD),
        ("y_size", w.DWORD),
        ("x_chars", w.DWORD),
        ("y_chars", w.DWORD),
        ("fill_attribute", w.DWORD),
        ("flags", w.DWORD),
        ("show_window", w.WORD),
        ("reserved2_size", w.WORD),
        ("reserved2", w.LPVOID),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", _StartupInfo), ("attributes", w.LPVOID)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("process", w.HANDLE),
        ("thread", w.HANDLE),
        ("process_id", w.DWORD),
        ("thread_id", w.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", w.LPVOID), ("inherit", w.BOOL)]


def _kernel():
    if sys.platform != "win32":
        raise OSError("Windows Engine-session ownership requires Windows")
    return win32.load(
        "kernel32",
        (
            ("CreateJobObjectW", [w.LPVOID, w.LPCWSTR], w.HANDLE),
            (
                "SetInformationJobObject",
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD],
                w.BOOL,
            ),
            (
                "QueryInformationJobObject",
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID],
                w.BOOL,
            ),
            ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
            (
                "CreateFileW",
                [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE],
                w.HANDLE,
            ),
            (
                "InitializeProcThreadAttributeList",
                [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)],
                w.BOOL,
            ),
            (
                "UpdateProcThreadAttribute",
                [
                    w.LPVOID,
                    w.DWORD,
                    ctypes.c_size_t,
                    w.LPVOID,
                    ctypes.c_size_t,
                    w.LPVOID,
                    w.LPVOID,
                ],
                w.BOOL,
            ),
            ("DeleteProcThreadAttributeList", [w.LPVOID], None),
            (
                "CreateProcessW",
                [
                    w.LPCWSTR,
                    w.LPVOID,
                    w.LPVOID,
                    w.LPVOID,
                    w.BOOL,
                    w.DWORD,
                    w.LPVOID,
                    w.LPCWSTR,
                    w.LPVOID,
                    w.LPVOID,
                ],
                w.BOOL,
            ),
            ("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD),
            ("GetExitCodeProcess", [w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            ("CloseHandle", [w.HANDLE], w.BOOL),
        ),
    )


class WindowsProcess:
    """The actual Godot leader's poll/wait plus ownership of its whole Job."""

    args: list[str]
    pid: int
    returncode: int | None
    _kernel: Any
    _job: int | None
    _engine: int | None
    _retired: bool
    _handle_lock: threading.Lock

    def __init__(self, argv: list[str], deadline: float) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Engine-session ownership requires Windows")
        self.args = argv
        self.pid = 0
        self.returncode: int | None = None
        self._kernel = _kernel()
        self._job = None
        self._engine = None
        self._retired = False
        self._handle_lock = threading.Lock()
        try:
            self._job = win32.checked(self._kernel.CreateJobObjectW(None, None))
            limits = _ExtendedLimits()
            limits.basic.flags = win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32.checked(
                self._kernel.SetInformationJobObject(
                    self._job,
                    win32.JobObjectExtendedLimitInformation,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                )
            )
            if time.monotonic() >= deadline:
                raise TimeoutError("the engine startup deadline expired before spawn")
            self._spawn(argv)
        except BaseException:
            self.retire(deadline)
            raise

    def _spawn(self, argv: list[str]) -> None:
        """Create the engine in the Job, with NUL standard handles and no window."""
        inherit = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        null = self._kernel.CreateFileW(
            "NUL",
            win32.GENERIC_READ | win32.GENERIC_WRITE,
            win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE,
            ctypes.byref(inherit),
            win32.OPEN_EXISTING,
            0,
            None,
        )
        if null is None or null == win32.INVALID_HANDLE_VALUE:
            raise win32.last_error()
        try:
            size = ctypes.c_size_t()
            self._kernel.InitializeProcThreadAttributeList(
                None, 2, 0, ctypes.byref(size)
            )
            attributes = ctypes.create_string_buffer(size.value)
            win32.checked(
                self._kernel.InitializeProcThreadAttributeList(
                    attributes, 2, 0, ctypes.byref(size)
                )
            )
            try:
                # The list points at these arrays, so they live until it is deleted.
                jobs = (w.HANDLE * 1)(self._job)
                # Like Popen's close_fds: the engine inherits the NUL handle only.
                inherited = (w.HANDLE * 1)(null)
                for attribute, value in (
                    (win32.PROC_THREAD_ATTRIBUTE_JOB_LIST, jobs),
                    (win32.PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited),
                ):
                    win32.checked(
                        self._kernel.UpdateProcThreadAttribute(
                            attributes,
                            0,
                            attribute,
                            value,
                            ctypes.sizeof(value),
                            None,
                            None,
                        )
                    )
                startup = _StartupInfoEx()
                startup.startup.cb = ctypes.sizeof(startup)
                startup.startup.flags = win32.STARTF_USESTDHANDLES
                startup.startup.stdin = null
                startup.startup.stdout = null
                startup.startup.stderr = null
                startup.attributes = ctypes.addressof(attributes)
                created = _ProcessInformation()
                win32.checked(
                    self._kernel.CreateProcessW(
                        None,
                        ctypes.create_unicode_buffer(subprocess.list2cmdline(argv)),
                        None,
                        None,
                        True,
                        win32.EXTENDED_STARTUPINFO_PRESENT | win32.CREATE_NO_WINDOW,
                        None,
                        None,
                        ctypes.byref(startup),
                        ctypes.byref(created),
                    )
                )
                self._kernel.CloseHandle(created.thread)
                self._engine = created.process
                self.pid = created.process_id
            finally:
                self._kernel.DeleteProcThreadAttributeList(attributes)
        finally:
            self._kernel.CloseHandle(null)

    def poll(self) -> int | None:
        with self._handle_lock:
            if self.returncode is not None or self._engine is None:
                return self.returncode
            state = self._kernel.WaitForSingleObject(self._engine, 0)
            if state == win32.WAIT_TIMEOUT:  # exit status 259 itself is valid
                return None
            if state != win32.WAIT_OBJECT_0:
                raise win32.last_error()
            code = w.DWORD()
            win32.checked(
                self._kernel.GetExitCodeProcess(self._engine, ctypes.byref(code))
            )
            self.returncode = code.value
            return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while (code := self.poll()) is None:
            if (
                timeout is not None
                and deadline is not None
                and time.monotonic() >= deadline
            ):
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.005)
        return code

    def _active(self) -> int:
        if self._job is None:
            return 0
        accounting = _Accounting()
        win32.checked(
            self._kernel.QueryInformationJobObject(
                self._job,
                win32.JobObjectBasicAccountingInformation,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            )
        )
        return accounting.active

    def retire(self, deadline: float) -> None:
        if self._retired:
            return
        self._retired = True
        if self._job is not None:
            # Immediate forced retirement; no Unix SIGTERM/flush or new grace.
            win32.checked(self._kernel.TerminateJobObject(self._job, 1))
            while self._active() and time.monotonic() < deadline:
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
        if self._active() or (self._engine is not None and self.poll() is None):
            # Preserve handles and collect the actual exit status off this clock,
            # like the existing POSIX best-effort reaper.
            threading.Thread(target=self._finish_retirement, daemon=True).start()
        else:
            self._finish_retirement()

    def _finish_retirement(self) -> None:
        while self._active():
            time.sleep(0.005)
        if self._engine is not None:
            self.wait()
        with self._handle_lock:
            for attribute in ("_engine", "_job"):
                handle = getattr(self, attribute)
                if handle is not None:
                    self._kernel.CloseHandle(handle)
                    setattr(self, attribute, None)
