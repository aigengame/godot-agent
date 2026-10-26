"""Temporary #1228 S2 probe: token privileges and ACL enforcement under the step shell.

Under a `shell: bash` step the fast tier's DACL-denial fixtures stop denying
directory listing and directory creation while file creation stays denied. The
MSYS2 runtime enables SeRestorePrivilege and SeBackupPrivilege for an
administrator token at startup (winsup/cygwin/sec/helper.cc,
set_cygwin_privileges). This probe measures the token's privileges and the three
operations under the step shell as it is, then with the two privileges toggled.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes as w
from pathlib import Path

advapi = ctypes.WinDLL("advapi32", use_last_error=True)
kernel = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_USER = 1
TOKEN_PRIVILEGES = 3
TOKEN_OWNER = 4
SE_PRIVILEGE_ENABLED = 0x2
TOGGLED = ("SeRestorePrivilege", "SeBackupPrivilege")


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", w.DWORD)]


class TOKEN_PRIVILEGES_ONE(ctypes.Structure):
    _fields_ = [("PrivilegeCount", w.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
advapi.GetTokenInformation.argtypes = [
    w.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    w.DWORD,
    ctypes.POINTER(w.DWORD),
]
advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
advapi.LookupPrivilegeNameW.argtypes = [
    w.LPCWSTR,
    ctypes.POINTER(LUID),
    w.LPWSTR,
    ctypes.POINTER(w.DWORD),
]
advapi.LookupPrivilegeValueW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.POINTER(LUID)]
advapi.AdjustTokenPrivileges.argtypes = [
    w.HANDLE,
    w.BOOL,
    ctypes.c_void_p,
    w.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
kernel.GetCurrentProcess.restype = w.HANDLE
kernel.LocalFree.argtypes = [ctypes.c_void_p]


def open_token() -> w.HANDLE:
    token = w.HANDLE()
    access = TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES
    if not advapi.OpenProcessToken(
        kernel.GetCurrentProcess(), access, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return token


def token_info(token: w.HANDLE, cls: int) -> ctypes.Array:
    size = w.DWORD()
    advapi.GetTokenInformation(token, cls, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, cls, buffer, size, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer


def sid_text(sid: int) -> str:
    text = w.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value or ""
    finally:
        kernel.LocalFree(text)


def first_sid(buffer: ctypes.Array) -> str:
    return sid_text(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])


def privileges(token: w.HANDLE) -> dict[str, str]:
    buffer = token_info(token, TOKEN_PRIVILEGES)
    count = ctypes.cast(buffer, ctypes.POINTER(w.DWORD))[0]
    entries = ctypes.cast(
        ctypes.addressof(buffer) + ctypes.sizeof(w.DWORD),
        ctypes.POINTER(LUID_AND_ATTRIBUTES * count),
    )[0]
    out: dict[str, str] = {}
    for entry in entries:
        name = ctypes.create_unicode_buffer(256)
        length = w.DWORD(256)
        if advapi.LookupPrivilegeNameW(
            None, ctypes.byref(entry.Luid), name, ctypes.byref(length)
        ):
            out[name.value] = f"0x{entry.Attributes:x}"
    return out


def set_privilege(token: w.HANDLE, name: str, enable: bool) -> str:
    luid = LUID()
    if not advapi.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        return f"lookup failed, last_error={ctypes.get_last_error()}"
    attributes = SE_PRIVILEGE_ENABLED if enable else 0
    adjust = TOKEN_PRIVILEGES_ONE(1, (LUID_AND_ATTRIBUTES(luid, attributes),))
    ok = advapi.AdjustTokenPrivileges(token, False, ctypes.byref(adjust), 0, None, None)
    error = ctypes.get_last_error()
    return "ok" if ok and error == 0 else f"ok={bool(ok)} last_error={error}"


def powershell(script: str, extra_env: dict[str, str]) -> str:
    env = {**os.environ, **extra_env}
    env.pop("PSMODULEPATH", None)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference = 'Stop'; "
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def deny_everyone(path: Path, rights: str) -> str:
    env = {"GDA_TEST_ACL_PATH": str(path), "GDA_TEST_ACL_RIGHTS": rights}
    saved = powershell(
        "$acl = Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH; "
        "$acl.GetSecurityDescriptorSddlForm("
        "[System.Security.AccessControl.AccessControlSections]::Access)",
        env,
    )
    powershell(
        "$acl = Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH; "
        "$rule = [System.Security.AccessControl.FileSystemAccessRule]::new("
        "[System.Security.Principal.SecurityIdentifier]::new('S-1-1-0'), "
        "[System.Security.AccessControl.FileSystemRights]$env:GDA_TEST_ACL_RIGHTS, "
        "[System.Security.AccessControl.AccessControlType]::Deny); "
        "$acl.AddAccessRule($rule); "
        "Set-Acl -LiteralPath $env:GDA_TEST_ACL_PATH -AclObject $acl",
        env,
    )
    return saved


def restore(path: Path, saved: str) -> None:
    powershell(
        "$acl = Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH; "
        "$acl.SetSecurityDescriptorSddlForm($env:GDA_TEST_ACL_SDDL, "
        "[System.Security.AccessControl.AccessControlSections]::Access); "
        "Set-Acl -LiteralPath $env:GDA_TEST_ACL_PATH -AclObject $acl",
        {"GDA_TEST_ACL_PATH": str(path), "GDA_TEST_ACL_SDDL": saved},
    )


def current_sddl(path: Path) -> str:
    return powershell(
        "(Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH).Sddl",
        {"GDA_TEST_ACL_PATH": str(path)},
    )


def attempt(action) -> str:
    try:
        action()
    except OSError as exc:
        return f"{type(exc).__name__} winerror={getattr(exc, 'winerror', None)}"
    return "ok"


def measure_acl(label: str) -> dict[str, str]:
    root = Path(tempfile.mkdtemp(prefix=f"gda-priv-{label}-"))
    locked = root / "locked"
    locked.mkdir()
    existing = locked / "existing.txt"
    existing.write_text("x")
    report: dict[str, str] = {}
    saved = deny_everyone(locked, "WriteData,AppendData")
    try:
        report["write_denied_sddl"] = current_sddl(locked)
        report["create_file"] = attempt(
            lambda: open(locked / "probe.bin", "xb").close()
        )
        report["mkdir"] = attempt(lambda: (locked / "sub").mkdir())
        report["mkdir_parents"] = attempt(
            lambda: (locked / "root" / "logs").mkdir(parents=True)
        )
    finally:
        restore(locked, saved)
    saved = deny_everyone(locked, "ReadData")
    try:
        report["list_denied_sddl"] = current_sddl(locked)
        report["listdir"] = attempt(lambda: os.listdir(locked))
        report["scandir"] = attempt(lambda: list(os.scandir(locked)))
    finally:
        restore(locked, saved)
    saved = deny_everyone(existing, "ReadData")
    try:
        report["open_denied_file"] = attempt(lambda: open(existing, "rb").close())
    finally:
        restore(existing, saved)
    return report


def main() -> int:
    token = open_token()
    report: dict[str, object] = {
        "shell_hints": {k: os.environ.get(k) for k in ("MSYSTEM", "SHELL", "TERM")},
        "user": first_sid(token_info(token, TOKEN_USER)),
        "owner": first_sid(token_info(token, TOKEN_OWNER)),
        "privileges": privileges(token),
    }
    report["acl_as_is"] = measure_acl("asis")
    enabled_now = any(
        int(report["privileges"].get(name, "0x0"), 16) & SE_PRIVILEGE_ENABLED
        for name in TOGGLED
    )
    toggle_to = not enabled_now
    report["toggle"] = {name: set_privilege(token, name, toggle_to) for name in TOGGLED}
    after = privileges(token)
    report["privileges_after_toggle"] = {name: after.get(name) for name in TOGGLED}
    report["acl_after_toggle"] = measure_acl("enabled" if toggle_to else "disabled")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
