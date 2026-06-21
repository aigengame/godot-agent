"""gda-daemon per-project discovery (#7, ADR-0021).

Pure path derivation + pidfile liveness: no daemon process, no engine. A daemon
is located by deriving deterministic socket/pidfile paths from the canonical
project root, under a short private runtime directory.
"""

import os
from pathlib import Path

import pytest

from gda.daemon.discovery import (
    acquire_pidfile,
    daemon_paths,
    daemon_pid,
    ensure_runtime_dir,
    within_uds_limit,
)


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


@pytest.mark.skipif(os.name != "posix", reason="pidfile liveness uses flock (UNIX)")
def test_daemon_pid_requires_recorded_path_socket_and_held_lock(tmp_path):
    proj = tmp_path / "game"
    proj.mkdir()
    env = {"XDG_RUNTIME_DIR": str(tmp_path / "run")}
    paths = daemon_paths(proj, env=env)

    # Nothing yet -> not running.
    assert daemon_pid(paths) is None

    handle = acquire_pidfile(paths, os.getpid())  # holds the advisory lock
    try:
        # Lock held but the CLI socket is not bound yet -> not running.
        assert daemon_pid(paths) is None
        # Bind the socket -> all three hold (recorded path + socket + held lock),
        # and the runtime dir is private (0700) for the no-other-user-surface
        # property (ADR-0021).
        paths.cli_socket.touch()
        assert daemon_pid(paths) == os.getpid()
        assert (paths.runtime_dir.stat().st_mode & 0o777) == 0o700
    finally:
        handle.close()  # releases the advisory lock

    # Socket still present, but the lock is now grabbable -> stale -> not running.
    # This is what makes a crashed daemon / reused PID self-heal (ADR-0021): the OS
    # drops the lock on exit, so no os.kill PID-liveness guess is needed.
    assert daemon_pid(paths) is None


@pytest.mark.skipif(os.name != "posix", reason="pidfile liveness uses flock (UNIX)")
def test_daemon_pid_foreign_recorded_path_is_not_a_hit(tmp_path):
    proj = tmp_path / "game"
    proj.mkdir()
    env = {"XDG_RUNTIME_DIR": str(tmp_path / "run")}
    paths = daemon_paths(proj, env=env)
    ensure_runtime_dir(paths)
    paths.cli_socket.touch()

    # A pidfile recording a DIFFERENT project is foreign (a hash collision / reused
    # slot), regardless of socket/lock — never this project's daemon.
    paths.pidfile.write_text(
        f"{os.getpid()}\n{tmp_path / 'elsewhere'}\n", encoding="utf-8"
    )
    assert daemon_pid(paths) is None


def test_within_uds_limit_flags_overlong_socket_paths():
    assert within_uds_limit(Path("/run/user/1000/gda/0123456789abcdef.cli.sock"))
    assert not within_uds_limit(Path("/" + "x" * 200 + ".sock"))
