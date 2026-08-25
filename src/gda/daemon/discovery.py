"""Per-project gda-daemon discovery (ADR-0021).

The CLI and the ``daemon`` lifecycle commands locate a project's daemon by
deriving deterministic socket and pidfile paths from the **canonical** project
root, under a short, private (``0700``) per-user runtime directory. The
derivation is a fixed contract so ``daemon start``, ``daemon status``, and a live
command's attach all agree on one daemon identity (ADR-0021):

- the project root is canonicalized (symlinks resolved) before derivation, so two
  references to one project derive one identity and two projects never collide;
- the socket/pidfile basenames are a stable hash of that canonical path;
- the runtime directory is ``$XDG_RUNTIME_DIR/gda`` when set (Linux), else
  ``~/.gda/run`` — both short, to respect the UDS ``sun_path`` length limit;
- the pidfile records the canonical project path, so a hash collision or a reused
  runtime slot is detectable (a recorded path that differs is *foreign*, not a
  hit) and liveness can be probed without a false match.

This module is pure (paths + filesystem reads); the daemon process that binds the
sockets and reclaims stale slots lives in :mod:`gda.daemon.server` (a later slice).
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# The private runtime directory the sockets/pidfile live in. Kept short so the
# absolute socket path stays under the OS ``sun_path`` limit (104 bytes on macOS,
# 108 on Linux); the long macOS ``$TMPDIR`` is deliberately never used.
XDG_RUNTIME_ENV = "XDG_RUNTIME_DIR"
RUNTIME_SUBDIR = "gda"
HOME_RUNTIME_DIR = "~/.gda/run"

# Conservative UDS path bound (macOS ``sun_path`` is 104 bytes); a derived socket
# longer than this would fail to bind, so we surface it as a clear error here.
UDS_PATH_MAX = 104


@dataclass(frozen=True)
class DaemonPaths:
    """The per-project daemon's on-disk identity (ADR-0021)."""

    project: Path  # the canonical (symlink-resolved) project root
    runtime_dir: Path  # the private 0700 directory the files live in
    cli_socket: Path  # CLI <-> daemon UDS
    harness_socket: Path  # daemon <-> harness UDS (path injected into the session)
    pidfile: Path  # liveness + the recorded canonical project path
    # The daemon-owned Session log (#224): the engine session is launched with
    # `--log-file` on this path so the daemon can read the running game's
    # errors/output back to serve `gda diag` / `gda logger`. Under the private
    # runtime dir (NOT `user://logs` — that shared path caused #180), keyed by the
    # same slug as the sockets/pidfile; `RotatedFileLogger` truncates it each
    # launch, making it session-bound (ADR-0020). Derived here with the rest of
    # the identity (#674) — no consumer re-derives it from a socket filename.
    session_log: Path


def _runtime_dir(env: Mapping[str, str]) -> Path:
    xdg = env.get(XDG_RUNTIME_ENV)
    if xdg:
        return Path(xdg) / RUNTIME_SUBDIR
    return Path(HOME_RUNTIME_DIR).expanduser()


def _project_slug(canonical_project: Path) -> str:
    # A stable, short hash of the canonical absolute path: same project -> same
    # slug, different projects -> different slugs. The full path is recorded in
    # the pidfile, so the (astronomically unlikely) collision is still detectable.
    return hashlib.sha256(str(canonical_project).encode("utf-8")).hexdigest()[:16]


def within_uds_limit(socket_path: Path) -> bool:
    """Whether ``socket_path`` fits the OS ``sun_path`` limit so it can bind.

    Pure derivation never raises on length (so it is testable under any tmp dir);
    the daemon checks this before binding and surfaces a clear error instead of an
    opaque bind failure (ADR-0021). The default runtime dirs are short enough that
    this only ever trips on an unusually long ``$XDG_RUNTIME_DIR``.
    """
    return len(str(socket_path)) <= UDS_PATH_MAX


def daemon_paths(project: Path, env: Mapping[str, str] | None = None) -> DaemonPaths:
    """Derive the per-project daemon paths from ``project`` (ADR-0021)."""
    env = os.environ if env is None else env
    canonical = Path(project).expanduser().resolve()
    runtime = _runtime_dir(env)
    slug = _project_slug(canonical)
    return DaemonPaths(
        project=canonical,
        runtime_dir=runtime,
        cli_socket=runtime / f"{slug}.cli.sock",
        harness_socket=runtime / f"{slug}.harness.sock",
        pidfile=runtime / f"{slug}.pid",
        session_log=runtime / f"{slug}.session.log",
    )


def ensure_runtime_dir(paths: DaemonPaths) -> Path:
    """Create the private (``0700``) runtime directory, returning it.

    Owner-only so the socket is never in a world-reachable directory — the "no
    other-user surface" half of ADR-0021's "no localhost surface".
    """
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.runtime_dir, 0o700)
    return paths.runtime_dir


def acquire_pidfile(paths: DaemonPaths, pid: int):
    """Open + advisory-lock the pidfile, record ``pid`` + canonical path; return the held handle.

    The daemon keeps the returned file open for its whole lifetime so the ``flock``
    is *held* — that held lock IS the liveness signal (ADR-0021): a held lock means
    a live daemon, a grabbable lock means a crashed/stale one, with no reliance on
    ``os.kill`` PID-liveness (which a reused PID could spoof). The OS releases the
    lock when the daemon exits or crashes, so liveness self-heals with no cleanup.
    Raises ``OSError`` if another live daemon already holds it (a start race).

    Opened WITHOUT truncation, and truncated only AFTER the lock is won (#723
    review): ``open("w")`` zeroed the file before ``flock`` could refuse, so a
    LOSING start erased the live winner's recorded identity — ``daemon_pid``
    then read the running daemon as not running.
    """
    import fcntl

    ensure_runtime_dir(paths)
    handle = os.fdopen(
        os.open(paths.pidfile, os.O_RDWR | os.O_CREAT, 0o644), "r+", encoding="utf-8"
    )
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise
    handle.seek(0)
    handle.truncate()
    handle.write(f"{pid}\n{paths.project}\n")
    handle.flush()
    return handle


def read_pidfile(paths: DaemonPaths) -> tuple[int, Path] | None:
    """Parse the pidfile into ``(pid, recorded_project)``, or ``None`` if absent/malformed."""
    try:
        text = paths.pidfile.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].strip().isdigit():
        return None
    return int(lines[0].strip()), Path(lines[1].strip())


def _pidfile_lock_held(pidfile: Path) -> bool:
    """Whether the pidfile's advisory lock is currently held by a live daemon."""
    import fcntl

    try:
        probe = open(pidfile, "r", encoding="utf-8")
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True  # could not grab it -> held by a live daemon
    else:
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)  # we grabbed it -> stale; release
        return False
    finally:
        probe.close()


def daemon_pid(paths: DaemonPaths) -> int | None:
    """The pid of a LIVE daemon for THIS project, or ``None`` (ADR-0021).

    Live requires all three: the pidfile's recorded project **matches** this
    project (else *foreign* — a hash collision / reused slot), the CLI socket is
    **bound** (present), and the pidfile's advisory lock is **held** (a grabbable
    lock means a crashed/stale daemon). So a reused PID or a stale socket is never
    mistaken for a live daemon. ``daemon start`` reclaims a stale slot; ``status``
    and a live command's attach read this as not-running.
    """
    info = read_pidfile(paths)
    if info is None:
        return None
    pid, recorded = info
    if recorded != paths.project:
        return None  # foreign
    if not paths.cli_socket.exists():
        return None  # not bound -> stale
    if not _pidfile_lock_held(paths.pidfile):
        return None  # grabbable -> crashed/stale
    return pid
