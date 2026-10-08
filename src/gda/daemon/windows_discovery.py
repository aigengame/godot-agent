"""Private loopback endpoint discovery and lifetime locks on Windows (ADR-0047)."""

import errno
import json
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from gda.daemon.discovery import DaemonPaths


def _verify_private_acl(path: Path) -> None:
    """Accept only current-user ownership and the private Python 0700 ACL shape.

    This reads native permissions; it never repairs or changes an existing ACL.
    SYSTEM and Administrators retain their normal local-machine access.
    """
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import ctypes
    from ctypes import wintypes as w

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    out_pointer = ctypes.POINTER(pointer)
    advapi.GetNamedSecurityInfoW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        out_pointer,
        out_pointer,
        out_pointer,
        out_pointer,
        out_pointer,
    ]
    advapi.GetNamedSecurityInfoW.restype = w.DWORD
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.OpenProcessToken.restype = w.BOOL
    advapi.GetTokenInformation.argtypes = [
        w.HANDLE,
        w.DWORD,
        pointer,
        w.DWORD,
        ctypes.POINTER(w.DWORD),
    ]
    advapi.GetTokenInformation.restype = w.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = w.BOOL
    advapi.GetAclInformation.argtypes = [pointer, pointer, w.DWORD, w.DWORD]
    advapi.GetAclInformation.restype = w.BOOL
    advapi.GetAce.argtypes = [pointer, w.DWORD, out_pointer]
    advapi.GetAce.restype = w.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer

    def checked(value: object) -> None:
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())

    def sid_text(sid: int | None) -> str:
        if sid is None:
            raise PermissionError("Daemon runtime has no owner SID")
        text = w.LPWSTR()
        checked(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            return text.value or ""
        finally:
            kernel.LocalFree(ctypes.cast(text, pointer))

    token = w.HANDLE()
    checked(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        checked(advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is PSID.
        user_sid = sid_text(ctypes.cast(buffer, out_pointer).contents.value)
    finally:
        kernel.CloseHandle(token)

    owner, dacl, descriptor = pointer(), pointer(), pointer()
    result = advapi.GetNamedSecurityInfoW(
        str(path),
        1,
        5,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )  # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
    if result:
        raise ctypes.WinError(result)
    try:
        if sid_text(owner.value) != user_sid or not dacl.value:
            raise PermissionError("Daemon runtime is not private to the current user")
        allowed = {user_sid, "S-1-3-4", "S-1-5-18", "S-1-5-32-544"}
        info = (w.DWORD * 3)()
        checked(advapi.GetAclInformation(dacl, info, ctypes.sizeof(info), 2))
        for index in range(info[0]):
            ace = pointer()
            checked(advapi.GetAce(dacl, index, ctypes.byref(ace)))
            assert ace.value is not None
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            if ace_type == 1:  # ACCESS_DENIED_ACE does not grant access.
                continue
            # Only ordinary ACCESS_ALLOWED_ACE entries are needed for this ACL.
            if ace_type != 0 or sid_text(ace.value + 8) not in allowed:
                raise PermissionError("Daemon runtime grants access to another user")
    finally:
        kernel.LocalFree(descriptor)


def _private_path(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    if sys.platform == "win32" and (
        info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise PermissionError("Daemon runtime must not use a reparse point")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise PermissionError("Daemon runtime path has the wrong file type")
    _verify_private_acl(path)


def ensure_private_runtime(directory: Path) -> None:
    """Create a private directory or refuse an unsafe existing one."""
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError:
        _private_path(directory, directory=True)
        raise
    _private_path(directory, directory=True)


def acquire_lock(paths: DaemonPaths) -> BinaryIO:
    """Hold the stable lock file's first byte until the returned handle closes."""
    return _acquire_lock_byte(paths, 0)


def acquire_harness_lock(paths: DaemonPaths, timeout: float) -> BinaryIO:
    """Serialize Windows harness/start transactions on the stable second byte.

    Commands hold this through readiness or rollback. The daemon only holds
    byte 0, so it can become ready while its parent owns the transaction.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            return _acquire_lock_byte(paths, 1)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "the Windows harness transaction is occupied"
                ) from error
            time.sleep(0.05)


def _acquire_lock_byte(paths: DaemonPaths, offset: int) -> BinaryIO:
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import msvcrt

    ensure_private_runtime(paths.runtime_dir)
    lock = paths.pidfile.with_suffix(".lock")
    try:
        _private_path(lock)
    except FileNotFoundError:
        pass
    handle = open(lock, "a+b")
    try:
        _private_path(lock)
        handle.seek(offset)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return handle
    except BaseException:
        handle.close()
        raise


def lock_held(paths: DaemonPaths) -> bool:
    """Probe liveness without truncating, replacing, or deleting the lock."""
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import msvcrt

    try:
        _private_path(paths.runtime_dir, directory=True)
        lock = paths.pidfile.with_suffix(".lock")
        _private_path(lock)
    except FileNotFoundError:
        return False
    with open(lock, "r+b") as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            return True
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    return False


@dataclass(frozen=True)
class WindowsEndpoint:
    pid: int
    project: Path
    cli_port: int
    harness_port: int
    token: str = field(repr=False)

    @property
    def address(self) -> tuple[str, int]:
        return "127.0.0.1", self.cli_port


def read_endpoint(paths: DaemonPaths) -> WindowsEndpoint | None:
    """Read private endpoint metadata; malformed or foreign records are absent."""
    endpoint = paths.pidfile.with_suffix(".json")
    try:
        _private_path(paths.runtime_dir, directory=True)
        _private_path(endpoint)
        data = json.loads(endpoint.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, UnicodeError):
        return None
    except OSError:
        # A retiring owner can unlink between lstat and the native ACL read,
        # which Windows may report as access denied. Disappearance is absence;
        # an existing unreadable or unsafe record remains a refusal.
        try:
            endpoint.lstat()
        except FileNotFoundError:
            return None
        raise
    if not isinstance(data, dict):
        return None
    pid, cli, harness = data.get("pid"), data.get("cli_port"), data.get("harness_port")
    token = data.get("token")
    if (
        type(pid) is not int
        or pid <= 0
        or type(cli) is not int
        or not 1 <= cli <= 65535
        or type(harness) is not int
        or not 1 <= harness <= 65535
        or cli == harness
        or data.get("host") != "127.0.0.1"
        or data.get("project") != str(paths.project)
        or not isinstance(token, str)
        or len(token) != 64
        or any(char not in "0123456789abcdef" for char in token)
    ):
        return None
    return WindowsEndpoint(pid, paths.project, cli, harness, token)


def publish_endpoint(
    paths: DaemonPaths, pid: int, cli_port: int, harness_port: int, token: str
) -> WindowsEndpoint:
    """Publish metadata atomically while the caller owns the separate lock."""
    ensure_private_runtime(paths.runtime_dir)
    endpoint = paths.pidfile.with_suffix(".json")
    try:
        _private_path(endpoint)
    except FileNotFoundError:
        pass
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=paths.runtime_dir,
            prefix=endpoint.stem + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                {
                    "pid": pid,
                    "project": str(paths.project),
                    "host": "127.0.0.1",
                    "cli_port": cli_port,
                    "harness_port": harness_port,
                    "token": token,
                },
                handle,
            )
            handle.flush()
        _private_path(temporary)
        temporary.replace(endpoint)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return WindowsEndpoint(pid, paths.project, cli_port, harness_port, token)


def remove_endpoint(paths: DaemonPaths) -> None:
    """Remove metadata during owned shutdown; leave the stable lock file intact."""
    try:
        _private_path(paths.runtime_dir, directory=True)
        endpoint = paths.pidfile.with_suffix(".json")
        _private_path(endpoint)
    except FileNotFoundError:
        return
    endpoint.unlink()
