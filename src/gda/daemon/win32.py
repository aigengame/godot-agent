"""The Win32 API surface of the Windows daemon modules (ADR-0047).

One home for three things: loading a DLL with typed functions, the checked-error
helpers, and the Win32 values the daemon passes or compares, each named as the
Windows SDK names it. This is a daemon module, not a utility package.

The module imports on every platform. Its functions call into ``ctypes`` names
that exist only on Windows, so only call them on Windows.
"""

import ctypes
from collections.abc import Iterable, Sequence
from typing import Any

# System error codes.
ERROR_ACCESS_DENIED = 5

# WaitForSingleObject results.
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

# Process access rights.
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000

# Job objects.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation = 1  # JOBOBJECTINFOCLASS
JobObjectExtendedLimitInformation = 9  # JOBOBJECTINFOCLASS

# Access tokens and security descriptors.
TOKEN_QUERY = 0x0008
TokenUser = 1  # TOKEN_INFORMATION_CLASS
SE_FILE_OBJECT = 1  # SE_OBJECT_TYPE
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
AclSizeInformation = 2  # ACL_INFORMATION_CLASS
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_DENIED_ACE_TYPE = 1

# Window stations and desktops.
UOI_FLAGS = 1
WSF_VISIBLE = 0x0001
DESKTOP_CREATEWINDOW = 0x0002


def load(name: str, functions: Iterable[tuple[str, Sequence[Any], Any]]) -> Any:
    """Load the DLL ``name`` and type each ``(function, argtypes, restype)``.

    With ``use_last_error``, ctypes saves the Win32 last error after each call,
    and ``last_error`` reads it.
    """
    library = getattr(ctypes, "WinDLL")(name, use_last_error=True)
    for function, arguments, result in functions:
        bound = getattr(library, function)
        bound.argtypes, bound.restype = arguments, result
    return library


def error(code: int) -> OSError:
    """The ``OSError`` for the Win32 error ``code``."""
    return getattr(ctypes, "WinError")(code)


def last_error() -> OSError:
    """The ``OSError`` for the last Win32 error of the calling thread."""
    return error(getattr(ctypes, "get_last_error")())


def checked(value: Any) -> Any:
    """Return ``value``, or raise ``last_error()`` when the call returned zero."""
    if not value:
        raise last_error()
    return value
