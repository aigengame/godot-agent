"""Windows Engine-session ownership through one private Job and startup gate.

The worker holds the engine's Popen object; the daemon owns native process/Job
handles. No process scans, private Popen handles or worker exit-code proxy.
"""

import ctypes
import json
import queue
import subprocess
import sys
import threading
import time
from ctypes import wintypes as w
from typing import Any


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


def _kernel():
    if sys.platform != "win32":
        raise OSError("Windows Engine-session ownership requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, arguments, result in (
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
        ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
        ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
        ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD),
        ("GetExitCodeProcess", [w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        ("CloseHandle", [w.HANDLE], w.BOOL),
    ):
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _checked(value):
    if not value:
        raise _error()
    return value


def _error() -> OSError:
    if sys.platform != "win32":
        return OSError("Windows process ownership is unavailable")
    return ctypes.WinError(ctypes.get_last_error())


class WindowsProcess:
    """The actual Godot leader's poll/wait plus ownership of its whole Job."""

    args: list[str]
    pid: int
    returncode: int | None
    _kernel: Any
    _job: int | None
    _engine: int | None
    _worker_handle: int | None
    _worker: subprocess.Popen[bytes] | None
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
        self._worker_handle = None
        self._worker = None
        self._retired = False
        self._handle_lock = threading.Lock()
        try:
            self._job = _checked(self._kernel.CreateJobObjectW(None, None))
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _checked(
                self._kernel.SetInformationJobObject(
                    self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            worker = subprocess.Popen(
                [sys.executable, "-m", "gda.daemon.windows_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._worker = worker
            assert worker.stdout is not None and worker.stdin is not None
            stream = worker.stdout
            messages: queue.Queue = queue.Queue()

            def read_startup() -> None:
                try:
                    for _ in range(2):
                        line = stream.readline()
                        if not line:
                            raise OSError(
                                "the Windows engine worker closed before spawn acknowledgement"
                            )
                        messages.put(json.loads(line))
                except Exception as error:
                    messages.put(error)

            threading.Thread(target=read_startup, daemon=True).start()

            def receive() -> dict:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(
                        "the engine startup deadline expired at the worker"
                    )
                try:
                    message = messages.get(timeout=left)
                except queue.Empty as error:
                    raise TimeoutError(
                        "the engine worker did not acknowledge within the startup deadline"
                    ) from error
                if isinstance(message, Exception):
                    raise message
                return message

            ready = receive()
            # The venv launcher PID can differ from the gated worker's actual PID.
            self._worker_handle = _checked(
                self._kernel.OpenProcess(
                    0x100 | 0x1 | 0x1000 | 0x100000, False, ready["worker_pid"]
                )
            )
            _checked(
                self._kernel.AssignProcessToJobObject(self._job, self._worker_handle)
            )
            worker.stdin.write(
                json.dumps({"argv": argv, "deadline": deadline}).encode("utf-8") + b"\n"
            )
            worker.stdin.flush()
            spawned = receive()
            if "error" in spawned:
                failure = spawned["error"]
                raise OSError(
                    failure["errno"],
                    failure["message"],
                    failure["filename"],
                    failure["winerror"],
                )
            if self._kernel.WaitForSingleObject(self._worker_handle, 0) != 258:
                raise OSError("the engine worker exited during process-handle handoff")
            self.pid = spawned["engine_pid"]
            self._engine = _checked(
                self._kernel.OpenProcess(0x1000 | 0x100000, False, self.pid)
            )
            if self._kernel.WaitForSingleObject(self._worker_handle, 0) != 258:
                raise OSError("the engine worker exited during process-handle handoff")
        except BaseException:
            self.retire(deadline)
            raise

    def poll(self) -> int | None:
        with self._handle_lock:
            if self.returncode is not None or self._engine is None:
                return self.returncode
            state = self._kernel.WaitForSingleObject(self._engine, 0)
            if state == 258:  # WAIT_TIMEOUT; exit status 259 itself is valid
                return None
            if state != 0:
                raise _error()
            code = w.DWORD()
            _checked(self._kernel.GetExitCodeProcess(self._engine, ctypes.byref(code)))
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
        _checked(
            self._kernel.QueryInformationJobObject(
                self._job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            )
        )
        return accounting.active

    def retire(self, deadline: float) -> None:
        if self._retired:
            return
        self._retired = True
        if self._job is not None:
            # Immediate forced retirement; no Unix SIGTERM/flush or new grace.
            _checked(self._kernel.TerminateJobObject(self._job, 1))
            while self._active() and time.monotonic() < deadline:
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
        if (
            self._active()
            or (self._engine is not None and self.poll() is None)
            or (self._worker is not None and self._worker.poll() is None)
        ):
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
            for attribute in ("_engine", "_worker_handle", "_job"):
                handle = getattr(self, attribute)
                if handle is not None:
                    self._kernel.CloseHandle(handle)
                    setattr(self, attribute, None)
        if self._worker is not None:
            if self._worker.stdin is not None:
                self._worker.stdin.close()
            self._worker.wait()
            if self._worker.stdout is not None:
                self._worker.stdout.close()
