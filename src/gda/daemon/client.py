"""The daemon IPC client (ADR-0017, ADR-0021): the LIVE execution channel, and the
control round trip and owner check that the ``daemon`` lifecycle commands use.

A ``LIVE`` command's runner is a client of the per-project ``gda-daemon`` rather
than a one-shot ``godot`` subprocess. It returns the SAME ``RunResult`` shape a
headless subprocess returns — ``stdout`` carrying the ADR-0002 sentinel payload —
so classification, sentinel parsing, output-model validation, and ``--json`` /
``GdaError`` emission are reused unchanged (the dispatcher's one new decision is
which runner factory to use, keyed on the command's ``kind``).

With no running daemon (or no resolved project) the client synthesizes a
``daemon_not_running`` sentinel envelope — the attach-or-fail typed error that
makes the daemon's start timing self-revealing (ADR-0017). A dropped connection
becomes ``engine_disconnected``. Both ride the normal classify pipeline via
``classify_live``.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from gda.daemon.discovery import DaemonPaths, daemon_paths
from gda.daemon.platform import (
    ControlOutcome,
    DaemonPlatform,
    RuntimeUnusable,
    host_platform,
)
from gda.daemon.protocol import (
    LIVE_REQUEST_TIMEOUT,
    error_reply,
    read_message,
    unsupported_platform_reply,
    write_message,
)
from gda.core.engine.launch import GodotRunner, RunResult
from gda.core.engine.execution import ExecutionKind, live_stack_supported


def _round_trip(
    paths: DaemonPaths, request: dict, deadline: float, platform: DaemonPlatform
) -> Any | None:
    """Send one request frame and read its reply frame.

    The connect, the write and the read all spend the one absolute ``deadline``
    (#725 re-review). A socket timeout bounds each ``recv``, so a reply that
    arrives in many chunks would otherwise restart the bound on every chunk.
    """
    with platform.connect(paths, deadline) as sock:
        write_message(sock, request, deadline)
        return read_message(sock, deadline)


def control_outcome(
    paths: DaemonPaths,
    op: str,
    timeout: float | None = None,
    *,
    platform: DaemonPlatform | None = None,
) -> ControlOutcome:
    """Send a control op (``__status__`` / ``__stop__``) and report its outcome.

    The default reply wait is the platform's ``control_timeout``, which follows
    its owner rule (ADR-0047, #1162). A caller that polls passes its own bound.

    A refused connection, or no published endpoint, is an outcome no daemon
    accepted. A deadline expiry, a dropped connection, a malformed reply or a
    reply that is not ``ok`` is an accepted outcome with no reply.
    """
    platform = platform or host_platform()
    if timeout is None:
        timeout = platform.control_timeout
    try:
        reply = _round_trip(paths, {"op": op}, time.monotonic() + timeout, platform)
    except (ConnectionRefusedError, FileNotFoundError):
        return ControlOutcome(None, accepted=False)
    except (OSError, ValueError):
        return ControlOutcome(None)
    return ControlOutcome(
        reply if isinstance(reply, dict) and reply.get("ok") else None
    )


def control(
    paths: DaemonPaths,
    op: str,
    timeout: float | None = None,
    *,
    platform: DaemonPlatform | None = None,
) -> Optional[dict]:
    """The ``ok`` reply of :func:`control_outcome`, or ``None``.

    For a caller that reads the reply and not the slot's state: the status read
    and the readiness poll.
    """
    return control_outcome(paths, op, timeout, platform=platform).reply


def owner_pid(reply: Optional[dict], pid: Optional[int]) -> Optional[int]:
    """The host platform's owner rule, until the lifecycle takes its adapter."""
    return host_platform().owner_pid(reply, pid)


def make_daemon_runner(project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return DaemonRunner(project)


@dataclass
class DaemonRunner:
    """A :class:`~gda.core.engine.launch.GodotRunner` that serves a live op via gda-daemon."""

    project: Optional[Path]
    # The one platform selection of this client (#1189).
    platform: DaemonPlatform = field(default_factory=host_platform)

    def run(self, operation: str, params: dict) -> RunResult:
        # Refuse a host the Live stack does not serve before project/daemon lookup.
        if not live_stack_supported(ExecutionKind.LIVE, operation):
            return RunResult(**unsupported_platform_reply())
        if self.project is None:
            # No resolved project is a project-resolution error, not a daemon one
            # (ADR-0021): a live op is per-project, so there is no daemon to find.
            return _live_error_result(
                "project_not_found",
                "no Godot project resolved; a live operation needs a project "
                "(pass --project or run inside one)",
            )
        paths = daemon_paths(self.project, platform=self.platform)
        try:
            pid = self.platform.find_daemon(paths)
        except RuntimeUnusable as exc:
            return _live_error_result("daemon_runtime_unusable", str(exc))
        if pid is None:
            return _live_error_result(
                "daemon_not_running",
                f"no gda-daemon is running for {self.project}; "
                "start one with `gda daemon start`",
            )
        return self._request(paths, operation, params)

    def _request(self, paths: DaemonPaths, operation: str, params: dict) -> RunResult:
        try:
            # An absolute instant, so the ceiling covers the WHOLE round trip
            # (#725 re-review). A socket timeout bounds each recv, and the reply
            # arrives in as many as the daemon sends — so 60s of socket timeout
            # was 60s of inactivity, not 60s of waiting.
            reply = _round_trip(
                paths,
                {"op": operation, "params": params},
                time.monotonic() + LIVE_REQUEST_TIMEOUT,
                self.platform,
            )
        except TimeoutError:
            return _live_error_result(
                "live_timeout",
                f"the live operation did not return within {int(LIVE_REQUEST_TIMEOUT)}s",
            )
        except OSError:
            return _live_error_result(
                "engine_disconnected",
                "the gda-daemon connection dropped before the live operation returned",
            )
        if reply is None:
            return _live_error_result(
                "engine_disconnected",
                "the gda-daemon closed the connection before replying",
            )
        # The daemon relays the engine session's sentinel payload verbatim as the
        # RunResult fields; classify_live / parse_result handle it like any op.
        return RunResult(
            stdout=str(reply.get("stdout", "")),
            stderr=str(reply.get("stderr", "")),
            exit_code=int(reply.get("exit_code", 0)),
        )


def _live_error_result(code: str, message: str) -> RunResult:
    """A synthesized RunResult carrying a LIVE error envelope in the sentinel.

    The client surfaces its own failures (no daemon, dropped connection) through
    the SAME ADR-0002 envelope a real op error uses — built once by
    :func:`gda.daemon.protocol.error_reply` (the daemon synthesizes the identical
    reply dict) — so ``classify_live`` maps them to the registered code through the
    normal pipeline, no special path.
    """
    return RunResult(**error_reply(code, message))
