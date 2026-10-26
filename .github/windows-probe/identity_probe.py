"""Print this process's own package identity, for S0(c) of #1228.

Run through the sideloaded package's app execution alias, it shows whether that
launch gave the interpreter package identity: ``code`` 122 (ERROR_INSUFFICIENT_BUFFER)
with the package full name means it did, 15700 (APPMODEL_ERROR_NO_PACKAGE) means it
did not. It is a temporary probe: it goes with the probe job that runs it.
"""

import ctypes
import json
import sys


def main() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    length = ctypes.c_uint32(0)
    code = kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
    report = {"executable": sys.executable, "code": code}
    if code == 122:
        name = ctypes.create_unicode_buffer(length.value)
        second = kernel32.GetCurrentPackageFullName(ctypes.byref(length), name)
        report["name"] = name.value if second == 0 else f"error {second}"
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
