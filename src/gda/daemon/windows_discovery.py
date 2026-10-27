"""Private loopback endpoint discovery, lifetime locks and control authentication
on Windows (ADR-0047)."""

import errno
import json
import secrets
import socket
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

from gda.daemon import win32
from gda.daemon.protocol import set_timeout_from_deadline

# The loopback host of the Windows daemon endpoints (ADR-0047). The harness keeps
# its own copy, ``LOOPBACK_HOST`` in ``src/gda/harness/gda_harness.gd``; if you
# change one, change the other.
LOOPBACK_HOST = "127.0.0.1"

# The offset of SidStart in ACCESS_ALLOWED_ACE: an ACE_HEADER (4 bytes), then an
# ACCESS_MASK (4 bytes).
_ACE_SID_START = 8

# The Administrators group, an accepted owner of the private runtime (#1231).
# Under a token whose default owner is this group (the built-in Administrator
# account, as on GitHub's windows-latest image), the runtime directory and the
# lock file gda creates are owned by it. The accepted owners are a fixed set:
# TOKEN_OWNER is the default owner of the objects a process creates, not an
# identity of an object that exists, and the same account reads a different one
# under pwsh and under an MSYS2 bash, so a check that followed it would refuse
# the runtime from the next process of the same account. ADR-0047 keeps the
# owner, SYSTEM and administrators inside the local access boundary, and the
# DACL check lists this group too.
ADMINISTRATORS_SID = "S-1-5-32-544"


class DiscoveryPaths(Protocol):
    """The daemon paths this module reads.

    ``gda.daemon.discovery.DaemonPaths`` derives them (#674). This module does not
    import that module, so the import between the two modules goes in one direction.
    """

    @property
    def project(self) -> Path: ...

    @property
    def runtime_dir(self) -> Path: ...

    @property
    def lock_file(self) -> Path: ...

    @property
    def endpoint_file(self) -> Path: ...


def _accepted_owner(owner_sid: str, user_sid: str) -> bool:
    """Whether ``owner_sid`` may own the private runtime: the token user or the
    Administrators group, and no other SID."""
    return owner_sid in {user_sid, ADMINISTRATORS_SID}


def _verify_private_acl(path: Path) -> None:
    """Accept only an accepted owner and the private Python 0700 ACL shape.

    This reads native permissions; it never repairs or changes an existing ACL.
    SYSTEM and Administrators retain their normal local-machine access.
    """
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import ctypes
    from ctypes import wintypes as w

    pointer = ctypes.c_void_p
    out_pointer = ctypes.POINTER(pointer)
    advapi = win32.load(
        "advapi32",
        (
            (
                "GetNamedSecurityInfoW",
                [
                    w.LPCWSTR,
                    w.DWORD,
                    w.DWORD,
                    out_pointer,
                    out_pointer,
                    out_pointer,
                    out_pointer,
                    out_pointer,
                ],
                w.DWORD,
            ),
            (
                "OpenProcessToken",
                [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)],
                w.BOOL,
            ),
            (
                "GetTokenInformation",
                [w.HANDLE, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            ("ConvertSidToStringSidW", [pointer, ctypes.POINTER(w.LPWSTR)], w.BOOL),
            ("GetAclInformation", [pointer, pointer, w.DWORD, w.DWORD], w.BOOL),
            ("GetAce", [pointer, w.DWORD, out_pointer], w.BOOL),
        ),
    )
    kernel = win32.load(
        "kernel32",
        (
            ("GetCurrentProcess", [], w.HANDLE),
            ("CloseHandle", [w.HANDLE], w.BOOL),
            ("LocalFree", [pointer], pointer),
        ),
    )

    def sid_text(sid: int | None) -> str:
        if sid is None:
            raise PermissionError("Daemon runtime has no owner SID")
        text = w.LPWSTR()
        win32.checked(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            return text.value or ""
        finally:
            kernel.LocalFree(ctypes.cast(text, pointer))

    token = w.HANDLE()
    win32.checked(
        advapi.OpenProcessToken(
            kernel.GetCurrentProcess(), win32.TOKEN_QUERY, ctypes.byref(token)
        )
    )
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, win32.TokenUser, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        win32.checked(
            advapi.GetTokenInformation(
                token, win32.TokenUser, buffer, size, ctypes.byref(size)
            )
        )
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is PSID.
        user_sid = sid_text(ctypes.cast(buffer, out_pointer).contents.value)
    finally:
        kernel.CloseHandle(token)

    owner, dacl, descriptor = pointer(), pointer(), pointer()
    result = advapi.GetNamedSecurityInfoW(
        str(path),
        win32.SE_FILE_OBJECT,
        win32.OWNER_SECURITY_INFORMATION | win32.DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise win32.error(result)
    try:
        if not _accepted_owner(sid_text(owner.value), user_sid) or not dacl.value:
            raise PermissionError("Daemon runtime is not private to the current user")
        allowed = {user_sid, "S-1-3-4", "S-1-5-18", ADMINISTRATORS_SID}
        info = (w.DWORD * 3)()
        win32.checked(
            advapi.GetAclInformation(
                dacl, info, ctypes.sizeof(info), win32.AclSizeInformation
            )
        )
        for index in range(info[0]):
            ace = pointer()
            win32.checked(advapi.GetAce(dacl, index, ctypes.byref(ace)))
            if ace.value is None:
                raise OSError("GetAce returned no ACE")
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            # An ACCESS_DENIED_ACE does not grant access.
            if ace_type == win32.ACCESS_DENIED_ACE_TYPE:
                continue
            # Only ordinary ACCESS_ALLOWED_ACE entries are needed for this ACL.
            if (
                ace_type != win32.ACCESS_ALLOWED_ACE_TYPE
                or sid_text(ace.value + _ACE_SID_START) not in allowed
            ):
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


def acquire_lock(paths: DiscoveryPaths) -> BinaryIO:
    """Hold the stable lock file's first byte until the returned handle closes."""
    return _acquire_lock_byte(paths, 0)


def acquire_harness_lock(paths: DiscoveryPaths, timeout: float) -> BinaryIO:
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


def _acquire_lock_byte(paths: DiscoveryPaths, offset: int) -> BinaryIO:
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import msvcrt

    ensure_private_runtime(paths.runtime_dir)
    lock = paths.lock_file
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


def lock_held(paths: DiscoveryPaths) -> bool:
    """Probe liveness without truncating, replacing, or deleting the lock."""
    if sys.platform != "win32":
        raise OSError("Windows daemon discovery requires Windows")
    import msvcrt

    try:
        _private_path(paths.runtime_dir, directory=True)
        lock = paths.lock_file
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
        return LOOPBACK_HOST, self.cli_port


def read_endpoint(paths: DiscoveryPaths) -> WindowsEndpoint | None:
    """Read private endpoint metadata; malformed or foreign records are absent."""
    endpoint = paths.endpoint_file
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
        or data.get("host") != LOOPBACK_HOST
        or data.get("project") != str(paths.project)
        or not isinstance(token, str)
        or len(token) != 64
        or any(char not in "0123456789abcdef" for char in token)
    ):
        return None
    return WindowsEndpoint(pid, paths.project, cli, harness, token)


def publish_endpoint(
    paths: DiscoveryPaths, pid: int, cli_port: int, harness_port: int, token: str
) -> WindowsEndpoint:
    """Publish metadata atomically while the caller owns the separate lock."""
    ensure_private_runtime(paths.runtime_dir)
    endpoint = paths.endpoint_file
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
                    "host": LOOPBACK_HOST,
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


# How long the removal of the endpoint record waits out a hold on it. Windows
# refuses the deletion of a file that another handle holds open without delete
# sharing, however short the hold, and the stop command's poll opens the
# record that way every 50 ms. Well inside the stop command's wait, so a stop
# that waits here still returns its stop result; a hold that outlasts the bound
# is an environment failure, and the removal raises as it did before (#1236).
REMOVAL_RETRY_BOUND = 2.0
_REMOVAL_RETRY_PAUSE = 0.02


def remove_endpoint(paths: DiscoveryPaths) -> None:
    """Remove metadata during owned shutdown; leave the stable lock file intact.

    A hold on the record is waited out for ``REMOVAL_RETRY_BOUND`` seconds, so
    the order ADR-0047 fixes, the record removed before the slot is released,
    holds against a transient reader (#1236).
    """
    try:
        _private_path(paths.runtime_dir, directory=True)
        endpoint = paths.endpoint_file
        _private_path(endpoint)
    except FileNotFoundError:
        return
    deadline = time.monotonic() + REMOVAL_RETRY_BOUND
    while True:
        try:
            endpoint.unlink()
        except PermissionError as error:
            if (
                getattr(error, "winerror", None) != win32.ERROR_SHARING_VIOLATION
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(_REMOVAL_RETRY_PAUSE)
        else:
            return


def connect_control(paths: DiscoveryPaths, deadline: float) -> socket.socket:
    """Connect to the privately published Windows owner and send its secret."""
    endpoint = read_endpoint(paths)
    if endpoint is None:
        # The same error a Unix connect raises for an absent socket path: there
        # is no endpoint to connect to, which the client tells from a daemon that
        # accepted the connection (client.control_outcome, #1162).
        raise FileNotFoundError("no native daemon endpoint is published")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        set_timeout_from_deadline(sock, deadline)
        sock.connect(endpoint.address)
        set_timeout_from_deadline(sock, deadline)
        sock.sendall(bytes.fromhex(endpoint.token))
        return sock
    except BaseException:
        sock.close()
        raise


def authenticate_control(sock: socket.socket, token: str, deadline: float) -> bool:
    """Read exactly one fixed-size secret within the original request deadline."""
    expected = bytes.fromhex(token)
    received = bytearray()
    while len(received) < len(expected):
        set_timeout_from_deadline(sock, deadline)
        chunk = sock.recv(len(expected) - len(received))
        if not chunk:
            return False
        received.extend(chunk)
    return secrets.compare_digest(received, expected)
