"""Measure why the daemon runtime directory is refused on the hosted Windows runner.

Temporary (#1228 S2): this file and its workflow step leave the branch once a run
has answered. Run as ``uv run --frozen python .github/windows-probe/owner_probe.py``.
The ``--child <directory>`` form is what the probe spawns to see whether a child
process inherits the default owner its parent set.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import traceback
from ctypes import wintypes as w
from pathlib import Path

from gda.daemon import win32
from gda.daemon.windows_discovery import _verify_private_acl, ensure_private_runtime

TOKEN_ADJUST_DEFAULT = 0x0080
TokenOwner = 4  # TOKEN_INFORMATION_CLASS
TokenElevationType = 18
TokenElevation = 20
ADMINISTRATORS = "S-1-5-32-544"

pointer = ctypes.c_void_p
out_pointer = ctypes.POINTER(pointer)

advapi = win32.load(
    "advapi32",
    (
        ("OpenProcessToken", [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
        (
            "GetTokenInformation",
            [w.HANDLE, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)],
            w.BOOL,
        ),
        ("SetTokenInformation", [w.HANDLE, w.DWORD, pointer, w.DWORD], w.BOOL),
        ("ConvertSidToStringSidW", [pointer, ctypes.POINTER(w.LPWSTR)], w.BOOL),
        ("ConvertStringSidToSidW", [w.LPCWSTR, out_pointer], w.BOOL),
        ("CheckTokenMembership", [w.HANDLE, pointer, ctypes.POINTER(w.BOOL)], w.BOOL),
        (
            "GetNamedSecurityInfoW",
            [w.LPCWSTR, w.DWORD, w.DWORD] + [out_pointer] * 5,
            w.DWORD,
        ),
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


def sid_text(sid):
    text = w.LPWSTR()
    win32.checked(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
    try:
        return text.value or ""
    finally:
        kernel.LocalFree(ctypes.cast(text, pointer))


def open_token(access):
    token = w.HANDLE()
    win32.checked(
        advapi.OpenProcessToken(kernel.GetCurrentProcess(), access, ctypes.byref(token))
    )
    return token


def token_information(token, cls):
    size = w.DWORD()
    advapi.GetTokenInformation(token, cls, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    win32.checked(
        advapi.GetTokenInformation(token, cls, buffer, size, ctypes.byref(size))
    )
    return buffer


def first_pointer(buffer):
    return ctypes.cast(buffer, out_pointer).contents.value


def first_dword(buffer):
    return ctypes.cast(buffer, ctypes.POINTER(w.DWORD)).contents.value


def token_facts():
    token = open_token(win32.TOKEN_QUERY)
    try:
        facts = {
            "token_user": sid_text(
                first_pointer(token_information(token, win32.TokenUser))
            ),
            "token_owner": sid_text(
                first_pointer(token_information(token, TokenOwner))
            ),
            "elevation_type": first_dword(token_information(token, TokenElevationType)),
            "is_elevated": first_dword(token_information(token, TokenElevation)),
        }
    finally:
        kernel.CloseHandle(token)
    admin = pointer()
    win32.checked(advapi.ConvertStringSidToSidW(ADMINISTRATORS, ctypes.byref(admin)))
    try:
        member = w.BOOL()
        win32.checked(advapi.CheckTokenMembership(None, admin, ctypes.byref(member)))
        facts["administrators_enabled"] = bool(member.value)
    finally:
        kernel.LocalFree(admin)
    return facts


def registry_value(key, name):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"error: {exc}"


def security(path):
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
        return {"error": str(win32.error(result))}
    try:
        aces = []
        if dacl.value:
            info = (w.DWORD * 3)()
            win32.checked(
                advapi.GetAclInformation(
                    dacl, info, ctypes.sizeof(info), win32.AclSizeInformation
                )
            )
            for index in range(info[0]):
                ace = pointer()
                win32.checked(advapi.GetAce(dacl, index, ctypes.byref(ace)))
                address = ace.value
                aces.append(
                    {
                        "type": ctypes.c_ubyte.from_address(address).value,
                        "flags": hex(ctypes.c_ubyte.from_address(address + 1).value),
                        "mask": hex(ctypes.c_uint32.from_address(address + 4).value),
                        "sid": sid_text(address + 8),
                    }
                )
        return {"owner": sid_text(owner.value), "aces": aces}
    finally:
        kernel.LocalFree(descriptor)


def verdict(path):
    try:
        _verify_private_acl(path)
    except Exception as exc:  # the refusal text is the measurement
        return f"{type(exc).__name__}: {exc}"
    return "ok"


def probe_directory(root, label):
    directory = Path(root) / f"gda-owner-probe-{os.getpid()}-{label}" / "gda" / "run"
    record = {"root": label, "path": str(directory)}
    try:
        try:
            ensure_private_runtime(directory)
            record["ensure_private_runtime"] = "ok"
        except Exception as exc:
            record["ensure_private_runtime"] = f"{type(exc).__name__}: {exc}"
            directory.mkdir(parents=True, exist_ok=True)
        record["directory"] = security(directory)
        record["directory_verdict"] = verdict(directory)
        lock = directory / "probe.lock"
        with open(lock, "xb"):
            pass
        record["file"] = security(lock)
        record["file_verdict"] = verdict(lock)
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        shutil.rmtree(directory.parent.parent, ignore_errors=True)
    return record


def set_default_owner(sid_string):
    sid = pointer()
    win32.checked(advapi.ConvertStringSidToSidW(sid_string, ctypes.byref(sid)))
    token = open_token(win32.TOKEN_QUERY | TOKEN_ADJUST_DEFAULT)
    try:
        owner = pointer(sid.value)  # TOKEN_OWNER is one PSID
        if not advapi.SetTokenInformation(
            token, TokenOwner, ctypes.byref(owner), ctypes.sizeof(owner)
        ):
            return str(win32.last_error())
        return "ok"
    finally:
        kernel.CloseHandle(token)
        kernel.LocalFree(sid)


def pivot_measurement(root):
    base = Path(root) / f"gda-pivot-probe-{os.getpid()}"
    record = {}
    try:
        game = base / "game"
        game.mkdir(parents=True)
        deep = base / "outside" / "deep"
        deep.mkdir(parents=True)
        (base / "outside" / "deck.gd").write_text("extends Node\n", encoding="utf-8")
        try:
            (game / "pivot").symlink_to(deep, target_is_directory=True)
        except OSError as exc:
            record["symlink"] = f"winerror {exc.winerror}: {exc}"
            return record
        spelled = game / "pivot" / ".." / "deck.gd"
        record["spelled"] = str(spelled.relative_to(base))
        record["realpath"] = str(Path(os.path.realpath(spelled)).relative_to(base))
        record["resolve"] = str(spelled.resolve().relative_to(base))
        record["exists"] = os.path.exists(spelled)
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return record


def child(directory):
    record = {"token": token_facts()}
    try:
        ensure_private_runtime(directory)
        record["ensure_private_runtime"] = "ok"
    except Exception as exc:
        record["ensure_private_runtime"] = f"{type(exc).__name__}: {exc}"
    if directory.is_dir():
        record["directory"] = security(directory)
        shutil.rmtree(directory.parent.parent, ignore_errors=True)
    print(json.dumps(record))


def main():
    if sys.platform != "win32":
        print("owner_probe: Windows only")
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
        return
    roots = {
        name: os.environ.get(name)
        for name in ("LOCALAPPDATA", "RUNNER_TEMP", "GITHUB_WORKSPACE")
    }
    report = {
        "python": sys.version,
        "token": token_facts(),
        "registry": {
            "NoDefaultAdminOwner": registry_value(
                r"SYSTEM\CurrentControlSet\Control\Lsa", "NoDefaultAdminOwner"
            ),
            "EnableLUA": registry_value(
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                "EnableLUA",
            ),
        },
        "before": [probe_directory(path, name) for name, path in roots.items() if path],
        "pivot": pivot_measurement(roots["RUNNER_TEMP"] or "."),
    }
    report["set_default_owner_to_user"] = set_default_owner(
        report["token"]["token_user"]
    )
    report["token_after"] = token_facts()
    report["after"] = [probe_directory(roots["LOCALAPPDATA"], "LOCALAPPDATA-after")]
    child_dir = (
        Path(roots["LOCALAPPDATA"])
        / f"gda-owner-probe-child-{os.getpid()}"
        / "gda"
        / "run"
    )
    run = subprocess.run(
        [sys.executable, __file__, "--child", str(child_dir)],
        capture_output=True,
        text=True,
    )
    report["child"] = {
        "exit": run.returncode,
        "stdout": run.stdout[-4000:],
        "stderr": run.stderr[-2000:],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
