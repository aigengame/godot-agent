"""gda-daemon per-project discovery (#7, ADR-0021).

Pure path derivation + pidfile liveness: no daemon process, no engine. A daemon
is located by deriving deterministic socket/pidfile paths from the canonical
project root, under a short private runtime directory.
"""

import os
from pathlib import Path

from gda.daemon.discovery import (
    daemon_paths,
    daemon_pid,
    within_uds_limit,
    write_pidfile,
)

# A pid far above any real process table (macOS pid_max ~99998) — reliably dead.
DEAD_PID = 4_000_000


def test_daemon_paths_are_deterministic_and_canonical_per_project(tmp_path):
    proj = tmp_path / "game"
    proj.mkdir()
    env = {"XDG_RUNTIME_DIR": str(tmp_path / "run")}

    paths = daemon_paths(proj, env=env)

    # Same project referenced differently derives ONE identity (so start / status
    # / attach agree): a trailing slash, and a symlink, both canonicalize to it.
    assert daemon_paths(Path(str(proj) + "/"), env=env) == paths
    link = tmp_path / "alias"
    link.symlink_to(proj)
    assert daemon_paths(link, env=env) == paths

    # A different project derives a different socket.
    other = tmp_path / "other"
    other.mkdir()
    assert daemon_paths(other, env=env).cli_socket != paths.cli_socket

    # The canonical project root is recorded, and the two legs are distinct
    # sockets under the private runtime dir.
    assert paths.project == proj.resolve()
    assert paths.cli_socket != paths.harness_socket
    assert paths.cli_socket.parent == tmp_path / "run" / "gda"
    assert paths.pidfile.parent == tmp_path / "run" / "gda"


def test_daemon_pid_distinguishes_running_stale_and_foreign(tmp_path):
    proj = tmp_path / "game"
    proj.mkdir()
    env = {"XDG_RUNTIME_DIR": str(tmp_path / "run")}
    paths = daemon_paths(proj, env=env)

    # No pidfile -> not running.
    assert daemon_pid(paths) is None

    # A live pid recorded for THIS project -> running (our own pid is alive), and
    # the runtime dir is created private (0700) for the "no other-user surface"
    # property (ADR-0021).
    write_pidfile(paths, os.getpid())
    assert daemon_pid(paths) == os.getpid()
    assert (paths.runtime_dir.stat().st_mode & 0o777) == 0o700

    # A dead pid -> stale -> not running (start reclaims it; status reports down).
    write_pidfile(paths, DEAD_PID)
    assert daemon_pid(paths) is None

    # A live pid but a DIFFERENT recorded project -> foreign -> not running.
    paths.pidfile.write_text(f"{os.getpid()}\n{tmp_path / 'elsewhere'}\n", encoding="utf-8")
    assert daemon_pid(paths) is None


def test_within_uds_limit_flags_overlong_socket_paths():
    assert within_uds_limit(Path("/run/user/1000/gda/0123456789abcdef.cli.sock"))
    assert not within_uds_limit(Path("/" + "x" * 200 + ".sock"))
