"""S0(a) of #1228: can the runner account create a symbolic link?

The ``symbolic_link`` test helper skips a test on WinError 1314, a missing
SeCreateSymbolicLinkPrivilege. This probe creates one file link and one directory
link in a temporary directory and reports each outcome as JSON on stdout, with the
Developer Mode registry value the privilege is usually granted through. It is a
temporary probe: it goes with the probe job that runs it.
"""

import json
import sys
import tempfile
from pathlib import Path


def _link(link: Path, target: Path, *, directory: bool) -> dict:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        return {
            "created": False,
            "errno": exc.errno,
            "winerror": getattr(exc, "winerror", None),
            "message": str(exc),
        }
    return {"created": True, "is_symlink": link.is_symlink(), "resolves": link.exists()}


def _developer_mode() -> dict:
    if sys.platform != "win32":
        return {"read": False, "reason": "not Windows"}
    import winreg

    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
    except OSError as exc:
        return {"read": False, "winerror": getattr(exc, "winerror", None)}
    return {"read": True, "AllowDevelopmentWithoutDevLicense": value}


def main() -> int:
    report = {"probe": "symlink", "platform": sys.platform}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target_file = root / "target.txt"
        target_file.write_text("target", encoding="utf-8")
        target_dir = root / "target_dir"
        target_dir.mkdir()
        report["file_link"] = _link(root / "link.txt", target_file, directory=False)
        report["directory_link"] = _link(root / "link_dir", target_dir, directory=True)
    report["developer_mode"] = _developer_mode()
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
