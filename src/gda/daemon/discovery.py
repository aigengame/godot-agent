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
    )


def ensure_runtime_dir(paths: DaemonPaths) -> Path:
    """Create the private (``0700``) runtime directory, returning it.

    Owner-only so the socket is never in a world-reachable directory — the "no
    other-user surface" half of ADR-0021's "no localhost surface".
    """
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.runtime_dir, 0o700)
    return paths.runtime_dir


def write_pidfile(paths: DaemonPaths, pid: int) -> None:
    """Record ``pid`` and the canonical project path for liveness/foreign checks."""
    ensure_runtime_dir(paths)
    paths.pidfile.write_text(f"{pid}\n{paths.project}\n", encoding="utf-8")


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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # no such process — stale
    except PermissionError:
        return True  # alive, owned by another user
    except OSError:
        return False
    return True


def daemon_pid(paths: DaemonPaths) -> int | None:
    """The pid of a LIVE daemon for THIS project, or ``None``.

    ``None`` when there is no pidfile, it is malformed, the recorded process is
    dead (**stale**), or the recorded project path differs from this project
    (**foreign** — a hash collision or a reused runtime slot). ``daemon start``
    reclaims a stale slot; ``daemon status`` and a live command's attach read this
    as not-running (``daemon_not_running``).
    """
    info = read_pidfile(paths)
    if info is None:
        return None
    pid, recorded = info
    if recorded != paths.project:
        return None  # foreign
    if not _pid_alive(pid):
        return None  # stale
    return pid
