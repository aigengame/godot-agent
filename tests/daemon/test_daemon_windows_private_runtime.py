"""The Windows private-runtime check accepts a fixed owner set (#1231, ADR-0047).

The check refused gda's own runtime under a token whose default owner is
``BUILTIN\\Administrators``: the runtime directory and the lock file gda creates are
owned by that group, and the owner rule accepted the token user alone. The rule now
accepts the token user or the Administrators group, and reads nothing from the token
beyond the user, because ``TOKEN_OWNER`` is the default owner of new objects, not an
identity of an existing one, and the same account reads a different one under
``pwsh`` and under an MSYS2 bash.

The rule is held as a table over literal SIDs, on every platform. The native path
is proven on Windows: a directory the Administrators group owns is accepted from a
process whose token default owner is the user, the shape a rule that followed the
token refused.
"""

import json
import subprocess
import sys

import pytest

from gda.daemon.windows_discovery import _accepted_owner
from tests.support import _windows_powershell

USER = "S-1-5-21-1000000000-2000000000-3000000000-1001"
ADMINISTRATORS = "S-1-5-32-544"


@pytest.mark.parametrize(
    ("owner", "accepted"),
    [
        pytest.param(USER, True, id="token-user"),
        pytest.param(ADMINISTRATORS, True, id="administrators-group"),
        # Another account of the same machine: an administrator's own SID is one.
        pytest.param(
            "S-1-5-21-1000000000-2000000000-3000000000-1002", False, id="other-account"
        ),
        pytest.param("S-1-5-32-545", False, id="users-group"),
        pytest.param("S-1-5-18", False, id="system"),
        pytest.param("S-1-3-4", False, id="owner-rights"),
    ],
)
def test_the_owner_rule_accepts_the_user_and_the_administrators_group(owner, accepted):
    assert _accepted_owner(owner, USER) is accepted


# A process that gives its own token the user as default owner, the shape an MSYS2
# bash or a UAC-filtered token has, and then runs the real check on one path.
_CHECK_UNDER_A_USER_DEFAULT_TOKEN = """
import ctypes, json, sys
from ctypes import wintypes as w
from pathlib import Path
from gda.daemon import win32
from gda.daemon.windows_discovery import _verify_private_acl

TOKEN_ADJUST_DEFAULT, TokenOwner = 0x0080, 4
pointer = ctypes.c_void_p
advapi = win32.load("advapi32", (
    ("OpenProcessToken", [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
    ("GetTokenInformation",
     [w.HANDLE, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
    ("SetTokenInformation", [w.HANDLE, w.DWORD, pointer, w.DWORD], w.BOOL),
    ("ConvertSidToStringSidW", [pointer, ctypes.POINTER(w.LPWSTR)], w.BOOL),
))
kernel = win32.load("kernel32", (
    ("GetCurrentProcess", [], w.HANDLE),
    ("LocalFree", [pointer], pointer),
))

def information(token, kind):
    size = w.DWORD()
    advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    win32.checked(
        advapi.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size))
    )
    return buffer

def first_sid(buffer):
    # TOKEN_USER starts with SID_AND_ATTRIBUTES and TOKEN_OWNER is one PSID: the
    # first pointer of either is the SID.
    sid = ctypes.cast(buffer, ctypes.POINTER(pointer)).contents.value
    text = w.LPWSTR()
    win32.checked(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
    try:
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, pointer))

token = w.HANDLE()
win32.checked(advapi.OpenProcessToken(
    kernel.GetCurrentProcess(), win32.TOKEN_QUERY | TOKEN_ADJUST_DEFAULT,
    ctypes.byref(token),
))
user = information(token, win32.TokenUser)
win32.checked(
    advapi.SetTokenInformation(token, TokenOwner, user, ctypes.sizeof(pointer))
)
report = {
    "user": first_sid(user),
    "default_owner": first_sid(information(token, TokenOwner)),
}
try:
    _verify_private_acl(Path(sys.argv[1]))
    report["verdict"] = "accepted"
except PermissionError as exc:
    report["verdict"] = f"refused: {exc}"
print(json.dumps(report))
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native ownership")
def test_an_administrators_owned_runtime_is_accepted_under_a_user_default_token(
    tmp_path,
):
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    # Give the directory to the Administrators group. The platform agrees only
    # where that group may own objects (SE_GROUP_OWNER): the built-in Administrator
    # account and an elevated token, not a UAC-filtered one.
    owner = _windows_powershell(
        "$acl = Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH; "
        "$acl.SetOwner([System.Security.Principal.SecurityIdentifier]::new("
        "$env:GDA_TEST_ACL_OWNER)); "
        "try { Set-Acl -LiteralPath $env:GDA_TEST_ACL_PATH -AclObject $acl } catch { }; "
        "(Get-Acl -LiteralPath $env:GDA_TEST_ACL_PATH).GetOwner("
        "[System.Security.Principal.SecurityIdentifier]).Value",
        {"GDA_TEST_ACL_PATH": str(runtime), "GDA_TEST_ACL_OWNER": ADMINISTRATORS},
    )
    if owner != ADMINISTRATORS:
        pytest.skip(
            "this case requires a token whose Administrators group may own objects"
        )

    child = subprocess.run(
        [sys.executable, "-c", _CHECK_UNDER_A_USER_DEFAULT_TOKEN, str(runtime)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["default_owner"] == report["user"]
    assert report["verdict"] == "accepted"
