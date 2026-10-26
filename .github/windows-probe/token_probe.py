"""Measure the token owner of the step's process and what it does to new files.

Temporary (#1228 S2). Probe 3 showed the same install test passing under a
``bash`` step and refused under a ``pwsh`` step, at the owner comparison of
``_verify_private_acl``. This probe prints the token's user, owner, primary
group, elevation and integrity, the Administrators group attributes, then the
owner and SDDL of a directory from ``mkdir(0o700)`` and a file in it, before
and after setting the token owner to the token user, and what a child process
and the real CLI see under each state.
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import traceback
from ctypes import wintypes as w
from pathlib import Path

advapi = ctypes.WinDLL("advapi32", use_last_error=True)
kernel = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TokenUser, TokenGroups, TokenOwner, TokenPrimaryGroup = 1, 2, 4, 5
TokenElevationType, TokenElevation, TokenIntegrityLevel = 18, 20, 25
SE_FILE_OBJECT = 1
OWNER_INFO, GROUP_INFO, DACL_INFO = 1, 2, 4

advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
advapi.GetTokenInformation.argtypes = [
    w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)
]
advapi.SetTokenInformation.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD]
advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
advapi.GetNamedSecurityInfoW.argtypes = [
    w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
]
advapi.GetNamedSecurityInfoW.restype = w.DWORD
advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
    ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.ULONG)
]
kernel.GetCurrentProcess.restype = w.HANDLE
kernel.LocalFree.argtypes = [ctypes.c_void_p]


def sid_text(sid):
    text = w.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        return f"<ConvertSidToStringSidW failed {ctypes.get_last_error()}>"
    try:
        return text.value
    finally:
        kernel.LocalFree(text)


def token_info(token, cls):
    size = w.DWORD()
    advapi.GetTokenInformation(token, cls, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(max(size.value, 8))
    if not advapi.GetTokenInformation(token, cls, buffer, size, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer


def first_sid(buffer):
    return sid_text(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value)


def token_summary(token):
    out = {
        "user": first_sid(token_info(token, TokenUser)),
        "owner": first_sid(token_info(token, TokenOwner)),
        "primary_group": first_sid(token_info(token, TokenPrimaryGroup)),
        "elevation_type": ctypes.cast(
            token_info(token, TokenElevationType), ctypes.POINTER(w.DWORD)
        ).contents.value,
        "elevated": ctypes.cast(
            token_info(token, TokenElevation), ctypes.POINTER(w.DWORD)
        ).contents.value,
    }
    label = token_info(token, TokenIntegrityLevel)
    label_sid = ctypes.cast(label, ctypes.POINTER(ctypes.c_void_p)).contents.value
    out["integrity"] = sid_text(label_sid)
    groups = token_info(token, TokenGroups)
    count = ctypes.cast(groups, ctypes.POINTER(w.DWORD)).contents.value
    base = ctypes.addressof(groups) + ctypes.sizeof(ctypes.c_void_p)  # aligned
    entry = ctypes.sizeof(ctypes.c_void_p) * 2
    attributes = {}
    for index in range(count):
        sid = ctypes.c_void_p.from_address(base + index * entry).value
        attr = w.DWORD.from_address(base + index * entry + ctypes.sizeof(ctypes.c_void_p)).value
        text = sid_text(sid)
        if text in {"S-1-5-32-544", "S-1-5-32-545", "S-1-5-114"} or attr & 0x8:
            attributes[text] = hex(attr)
    out["groups_of_interest"] = attributes  # 0x8 = SE_GROUP_OWNER, 0x4 = ENABLED
    return out


def security(path):
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    result = advapi.GetNamedSecurityInfoW(
        str(path), SE_FILE_OBJECT, OWNER_INFO | DACL_INFO,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
    )
    if result:
        return {"error": result}
    try:
        text, length = w.LPWSTR(), w.ULONG()
        ok = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, OWNER_INFO | GROUP_INFO | DACL_INFO,
            ctypes.byref(text), ctypes.byref(length),
        )
        sddl = text.value if ok else f"<sddl failed {ctypes.get_last_error()}>"
        if ok:
            kernel.LocalFree(text)
        return {"owner": sid_text(owner.value), "sddl": sddl}
    finally:
        kernel.LocalFree(descriptor)


def verdict(path, directory):
    from gda.daemon.windows_discovery import _private_path

    try:
        _private_path(path, directory=directory)
    except Exception as exc:  # the error is the measurement
        return f"REFUSED {exc!r}"
    return "ok"


def create_and_measure(label):
    root = Path(tempfile.mkdtemp(prefix=f"gda-token-probe-{label}-"))
    directory = root / "gda" / "run"
    directory.mkdir(mode=0o700, parents=True)
    lock = directory / "probe.lock"
    with open(lock, "a+b"):
        pass
    return {
        "dir": {**security(directory), "verdict": verdict(directory, True)},
        "file": {**security(lock), "verdict": verdict(lock, False)},
        "root": str(root),
    }


def run_cli(label):
    project = Path(tempfile.mkdtemp(prefix=f"gda-token-cli-{label}-"))
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    appdata = Path(tempfile.mkdtemp(prefix=f"gda-token-appdata-{label}-"))
    env = {**os.environ, "GDA_GODOT": "", "LOCALAPPDATA": str(appdata)}
    out = {}
    for argv in (("daemon", "install"), ("daemon", "uninstall")):
        run = subprocess.run(
            [sys.executable, "-m", "gda", *argv, "--project", str(project), "--json"],
            capture_output=True, text=True, env=env, timeout=180,
        )
        out[" ".join(argv)] = {"exit": run.returncode, "stdout": run.stdout[-700:]}
    return out


def main():
    token = w.HANDLE()
    if not advapi.OpenProcessToken(
        kernel.GetCurrentProcess(), TOKEN_QUERY | TOKEN_ADJUST_DEFAULT, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if "--child" in sys.argv:
        print(json.dumps({"child_token": token_summary(token)}))
        return
    report = {
        "shell_hints": {
            key: os.environ.get(key)
            for key in ("SHELL", "MSYSTEM", "PSModulePath", "TERM", "COMSPEC")
        },
        "parent_token_before": token_summary(token),
    }
    report["objects_before"] = create_and_measure("before")
    child = subprocess.run(
        [sys.executable, __file__, "--child"], capture_output=True, text=True
    )
    report["child_before"] = child.stdout.strip() or child.stderr[-500:]
    report["cli_before"] = run_cli("before")

    user = token_info(token, TokenUser)
    user_sid = ctypes.cast(user, ctypes.POINTER(ctypes.c_void_p)).contents.value
    owner = ctypes.c_void_p(user_sid)
    if advapi.SetTokenInformation(token, TokenOwner, ctypes.byref(owner), ctypes.sizeof(owner)):
        report["set_token_owner_to_user"] = "ok"
    else:
        report["set_token_owner_to_user"] = f"failed {ctypes.get_last_error()}"
    report["parent_token_after"] = token_summary(token)
    report["objects_after"] = create_and_measure("after")
    child = subprocess.run(
        [sys.executable, __file__, "--child"], capture_output=True, text=True
    )
    report["child_after"] = child.stdout.strip() or child.stderr[-500:]
    report["cli_after"] = run_cli("after")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
