"""Per-project gda-daemon discovery (ADR-0021).

The CLI and the ``daemon`` lifecycle commands locate a project's daemon by
deriving deterministic socket and pidfile paths from the **canonical** project
root, under a short, private (``0700``) per-user runtime directory. The
derivation is a fixed contract so ``daemon start``, ``daemon status``, and a live
command's attach all agree on one daemon identity (ADR-0021):

- the project root is canonicalized (symlinks resolved) before derivation, so two
  references to one project derive one identity and two projects never collide;
- the socket/pidfile basenames are a stable hash of that canonical path;
- the runtime directory is the platform adapter's (:mod:`gda.daemon.platform`):
  short, so a Unix socket path stays under the ``sun_path`` length limit;
- the pidfile records the canonical project path, so a hash collision or a reused
  runtime slot is detectable (a recorded path that differs is *foreign*, not a
  hit) and liveness can be probed without a false match.

On Windows (ADR-0047) the identity is a lock file (the daemon slot and the harness
transaction) plus a private endpoint metadata file that records the loopback
endpoints and the pid. How each platform reads and holds the slot is its
adapter's (:mod:`gda.daemon.unix`, :mod:`gda.daemon.windows`).

This module is pure (paths + filesystem reads); the daemon process that binds the
sockets and reclaims stale slots lives in :mod:`gda.daemon.server`.
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gda.core.project.paths import expand_user
from gda.daemon.platform import DaemonPlatform, host_platform

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
    # Windows (ADR-0047): the stable lock file (a lock on byte 0 holds the daemon
    # slot, a lock on byte 1 the harness transaction), and the private endpoint
    # metadata file. Derived here with the rest of the identity (#674), so no
    # module derives them from the pidfile name.
    lock_file: Path
    endpoint_file: Path
    # The daemon-owned Session log (#224): the engine session is launched with
    # `--log-file` on this path so the daemon can read the running game's
    # errors/output back to serve `gda diag` / `gda logger`. Under the private
    # runtime dir (NOT `user://logs` — that shared path caused #180), keyed by the
    # same slug as the sockets/pidfile; `RotatedFileLogger` truncates it each
    # launch, making it session-bound (ADR-0020). Derived here with the rest of
    # the identity (#674) — no consumer re-derives it from a socket filename.
    session_log: Path


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


def daemon_paths(
    project: Path,
    env: Mapping[str, str] | None = None,
    platform: DaemonPlatform | None = None,
) -> DaemonPaths:
    """Derive the per-project daemon paths from ``project`` (ADR-0021).

    ``platform`` locates the runtime directory; a caller that holds no adapter
    gets the host's.
    """
    env = os.environ if env is None else env
    canonical = expand_user(Path(project)).resolve()
    runtime = (platform or host_platform()).runtime_dir(env)
    slug = _project_slug(canonical)
    return DaemonPaths(
        project=canonical,
        runtime_dir=runtime,
        cli_socket=runtime / f"{slug}.cli.sock",
        harness_socket=runtime / f"{slug}.harness.sock",
        pidfile=runtime / f"{slug}.pid",
        lock_file=runtime / f"{slug}.lock",
        endpoint_file=runtime / f"{slug}.json",
        session_log=runtime / f"{slug}.session.log",
    )


def runtime_unusable_message(paths: DaemonPaths) -> str:
    """The `daemon_runtime_unusable` message for a directory that is not private
    or not usable (#1162).

    The lifecycle recipes and the daemon IPC client refuse that directory with the
    same recovery, so they share this message. The Unix socket-path refusal mints
    the same code with its own message, since its recovery is a shorter path.
    """
    return (
        f"the daemon runtime directory {paths.runtime_dir} is not private or not usable"
    )
