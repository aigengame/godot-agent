"""Measure which step of the Windows daemon lock chain fails on the hosted runner.

Temporary (#1228 S2). Probe 1 showed that the runtime directory and a file in it
pass the privacy check on the runner, yet every `daemon install` and `daemon
start` answers `daemon_runtime_unusable`. Both go through `_acquire_lock_byte`.
This probe runs that chain one step at a time with the error kept, then runs the
real CLI as the failing test does.
"""

import json
import msvcrt
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from gda.daemon import windows_discovery as wd
from gda.daemon.discovery import daemon_paths
from gda.daemon.windows import WindowsPlatform


def attempt(label, fn):
    try:
        value = fn()
    except BaseException as exc:  # the error is the measurement
        return {
            "step": label,
            "ok": False,
            "error": repr(exc),
            "errno": getattr(exc, "errno", None),
            "winerror": getattr(exc, "winerror", None),
            "traceback": traceback.format_exc()[-1800:],
        }
    if not isinstance(value, (dict, list)):
        value = repr(value)[:400]
    return {"step": label, "ok": True, "value": value}


def manual_chain(lock):
    out = {}
    out["lstat_before"] = attempt("lstat", lambda: hex(lock.lstat().st_file_attributes))
    handle = open(lock, "a+b")
    try:
        out["private_path_while_open"] = attempt(
            "_private_path(lock)", lambda: wd._private_path(lock)
        )
        out["attributes_while_open"] = hex(lock.lstat().st_file_attributes)
        handle.seek(1)
        out["tell"] = handle.tell()
        out["locking_byte_1"] = attempt(
            "msvcrt.locking",
            lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1),
        )
        if out["locking_byte_1"]["ok"]:
            handle.seek(1)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()
    return out


def chain(label, env_override):
    project = Path(tempfile.mkdtemp(prefix=f"gda-lock-probe-{label}-"))
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    env = {**os.environ, **env_override}
    platform = WindowsPlatform()
    paths = daemon_paths(project, env, platform=platform)
    steps = [
        attempt(
            "ensure_private_runtime",
            lambda: wd.ensure_private_runtime(paths.runtime_dir),
        ),
        attempt(
            "_private_path(runtime_dir)",
            lambda: wd._private_path(paths.runtime_dir, directory=True),
        ),
        attempt("read_endpoint", lambda: wd.read_endpoint(paths)),
        attempt("lock_held (no lock file)", lambda: wd.lock_held(paths)),
    ]

    def acquire(offset):
        held = wd._acquire_lock_byte(paths, offset)
        held.close()
        return "held and released"

    steps.append(attempt("_acquire_lock_byte(1)", lambda: acquire(1)))
    steps.append(attempt("_acquire_lock_byte(0)", lambda: acquire(0)))
    steps.append(attempt("lock_held (lock file exists)", lambda: wd.lock_held(paths)))
    steps.append(attempt("platform.daemon_pid", lambda: platform.daemon_pid(paths)))
    steps.append(
        attempt("platform.check_runtime", lambda: platform.check_runtime(paths))
    )
    steps.append(attempt("manual chain", lambda: manual_chain(paths.lock_file)))
    cli_env = {**env, "GDA_GODOT": ""}
    for argv in (("daemon", "install"), ("daemon", "status"), ("daemon", "uninstall")):
        run = subprocess.run(
            [sys.executable, "-m", "gda", *argv, "--project", str(project), "--json"],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=180,
        )
        steps.append(
            {
                "step": "cli " + " ".join(argv),
                "exit": run.returncode,
                "stdout": run.stdout[-900:],
                "stderr": run.stderr[-900:],
            }
        )
    steps.append(
        attempt(
            "runtime listing",
            lambda: sorted(p.name for p in paths.runtime_dir.iterdir()),
        )
    )
    return {"label": label, "runtime_dir": str(paths.runtime_dir), "steps": steps}


def main():
    if sys.platform != "win32":
        print("lock_probe: Windows only")
        return
    report = {
        "python": sys.version,
        "executable": sys.executable,
        "real LOCALAPPDATA": chain("real", {}),
        "temp LOCALAPPDATA": chain(
            "temp", {"LOCALAPPDATA": tempfile.mkdtemp(prefix="gda-lock-probe-appdata-")}
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
