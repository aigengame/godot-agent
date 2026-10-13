"""The Unix adapter of the daemon platform seam (ADR-0021, #1189).

The daemon's identity on Unix is a pidfile under a private (``0700``) runtime
directory, held by an advisory ``flock`` for the daemon's whole lifetime, beside
the two Unix domain sockets the CLI and the harness connect to. The held lock
is the liveness signal: a held lock means a live daemon, a grabbable lock a
crashed or stale one, with no reliance on PID liveness, which a reused PID could
spoof. The OS releases the lock when the daemon exits or crashes, so liveness
self-heals with no cleanup.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from gda.daemon.platform import HOME_RUNTIME_DIR

if TYPE_CHECKING:
    from gda.daemon.discovery import DaemonPaths

# The private runtime directory the sockets and the pidfile live in. Kept short
# so the absolute socket path stays under the OS ``sun_path`` limit (104 bytes on
# macOS, 108 on Linux); the long macOS ``$TMPDIR`` is deliberately never used.
XDG_RUNTIME_ENV = "XDG_RUNTIME_DIR"
RUNTIME_SUBDIR = "gda"


class UnixPlatform:
    """Unix domain sockets, a pidfile lock and an owned process group."""

    def runtime_dir(self, env: Mapping[str, str]) -> Path:
        # ``$XDG_RUNTIME_DIR/gda`` when set (Linux), else ``~/.gda/run``: both
        # short, to respect the UDS ``sun_path`` length limit.
        xdg = env.get(XDG_RUNTIME_ENV)
        if xdg:
            return Path(xdg) / RUNTIME_SUBDIR
        return Path(HOME_RUNTIME_DIR).expanduser()

    def daemon_pid(self, paths: DaemonPaths) -> int | None:
        """The pid of a LIVE daemon for THIS project, or ``None`` (ADR-0021).

        Live requires all three: the pidfile's recorded project **matches** this
        project (else *foreign*: a hash collision or a reused slot), the CLI
        socket is **bound** (present), and the pidfile's advisory lock is
        **held** (a grabbable lock means a crashed or stale daemon). So a reused
        PID or a stale socket is never mistaken for a live daemon.
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
