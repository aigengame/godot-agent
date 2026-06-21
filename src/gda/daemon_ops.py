"""The ``gda daemon`` lifecycle recipe (ADR-0017), parallel to ``export_run``.

The ``daemon start`` / ``stop`` / ``status`` commands are not ``operations.gd``
ops and not a live execution channel — they manage the daemon *process*. So, like
``export run``, each is a recipe that RETURNS its typed outcome (never emits/exits)
and the CLI owns emission. ``start`` gates the platform (live is UNIX-only,
ADR-0021), performs the reported idempotent harness install (ADR-0018), spawns the
detached daemon, and waits until it is accepting; ``stop`` asks it to shut down;
``status`` reports liveness from the pidfile.

The engine session the daemon holds — and the live-version gate that needs it —
land in the next slice; this recipe stands up the process lifecycle.
"""

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from gda.binary import resolve_godot_binary
from gda.daemon.discovery import DaemonPaths, daemon_paths, daemon_pid
from gda.daemon.protocol import read_message, write_message
from gda.daemon.server import STATUS_OP, STOP_OP
from gda.errors import Failure, _failure, unresolvable_binary_failure
from gda.harness.install import install_harness
from gda.models import DaemonStartResult, DaemonStatusResult, DaemonStopResult

_READY_TIMEOUT = 8.0
_STOP_TIMEOUT = 8.0
_POLL = 0.05

# Phase-2 live requires Godot 4.6+ (the UDS transport landed in 4.6; ADR-0021).
MIN_LIVE_VERSION = (4, 6)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

# Seams tests override to avoid launching a real process / running the engine.
SpawnDaemon = Callable[[Path, str], None]
VersionCheck = Callable[[str], Optional[tuple]]


def _is_unix() -> bool:
    return os.name == "posix"


def _engine_version(binary: str) -> Optional[tuple]:
    """The running engine's (major, minor) via ``--version``, or None if unknown."""
    try:
        result = subprocess.run(
            [str(binary), "--headless", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError:
        return None
    match = _VERSION_RE.search(result.stdout + result.stderr)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _spawn_daemon(project: Path, binary: str) -> None:
    """Spawn the detached, per-project daemon (its own session, no std streams)."""
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gda.daemon",
            "--project",
            str(project),
            "--godot",
            str(binary),
        ],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _control(cli_socket: Path, op: str, timeout: float = 2.0) -> Optional[dict]:
    """Send a control op (``__status__`` / ``__stop__``) and return the reply."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(cli_socket))
            write_message(sock, {"op": op})
            return read_message(sock)
    except OSError:
        return None


def _await_ready(paths: DaemonPaths, timeout: float = _READY_TIMEOUT) -> Optional[int]:
    """Wait until the daemon is alive AND accepting; return its pid or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = daemon_pid(paths)
        if pid is not None:
            reply = _control(paths.cli_socket, STATUS_OP)
            if reply and reply.get("ok"):
                return pid
        time.sleep(_POLL)
    return None


def _await_gone(paths: DaemonPaths, pid: int, timeout: float = _STOP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_pid(paths) is None:
            return
        time.sleep(_POLL)
    # Graceful stop did not take — fall back to a signal.
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def run_daemon_start_operation(
    project: Optional[Path],
    godot: Optional[str],
    *,
    spawn: Optional[SpawnDaemon] = None,
    version_check: Optional[VersionCheck] = None,
) -> "DaemonStartResult | Failure":
    if not _is_unix():
        return _failure(
            "live_unsupported_platform",
            "live operations require a UNIX platform (macOS/Linux); the daemon uses "
            "Unix domain sockets, which are unavailable here",
            "",
        )
    if project is None:
        return _failure(
            "project_not_found",
            "gda daemon needs a Godot project; pass --project or run inside one",
            "",
        )
    paths = daemon_paths(project)
    existing = daemon_pid(paths)
    if existing is not None:
        # Idempotent: a daemon is already up for this project.
        return DaemonStartResult(
            pid=existing,
            socket_path=str(paths.cli_socket),
            installed_harness=False,
            already_running=True,
        )

    # The daemon needs the engine binary for its sessions; resolve it and gate the
    # live version here (ADR-0021), so the floor is reported at start, not midway.
    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        return unresolvable_binary_failure(str(exc))
    version = (version_check or _engine_version)(str(binary))
    if version is None or tuple(version) < MIN_LIVE_VERSION:
        minimum = ".".join(str(part) for part in MIN_LIVE_VERSION)
        found = ".".join(str(part) for part in version) if version else "unknown"
        return _failure(
            "unsupported_version",
            f"live operations require Godot {minimum}+ (the daemon transport uses Unix "
            f"domain sockets, added in {minimum}); the engine reports {found}",
            "",
        )

    installed = install_harness(project)
    (spawn or _spawn_daemon)(project, str(binary))
    pid = _await_ready(paths)
    if pid is None:
        return _failure(
            "daemon_not_running",
            "the gda-daemon did not start (it never began accepting on its socket)",
            "",
        )
    return DaemonStartResult(
        pid=pid,
        socket_path=str(paths.cli_socket),
        installed_harness=installed,
        already_running=False,
    )


def run_daemon_stop_operation(project: Optional[Path]) -> "DaemonStopResult | Failure":
    if project is None:
        return _failure(
            "project_not_found",
            "gda daemon needs a Godot project; pass --project or run inside one",
            "",
        )
    paths = daemon_paths(project)
    pid = daemon_pid(paths)
    if pid is None:
        return DaemonStopResult(stopped=False, pid=None)
    _control(paths.cli_socket, STOP_OP)
    _await_gone(paths, pid)
    return DaemonStopResult(stopped=True, pid=pid)


def run_daemon_status_operation(project: Optional[Path]) -> "DaemonStatusResult | Failure":
    if project is None:
        return _failure(
            "project_not_found",
            "gda daemon needs a Godot project; pass --project or run inside one",
            "",
        )
    paths = daemon_paths(project)
    pid = daemon_pid(paths)
    return DaemonStatusResult(
        running=pid is not None, pid=pid, socket_path=str(paths.cli_socket)
    )
