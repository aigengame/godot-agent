"""The ``daemon`` command group: gda's own per-project daemon lifecycle (ADR-0017).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, the five lifecycle operations (formerly ``gda.daemon_ops``),
its human renderers, its ``HeadlessCommand`` descriptors (ADR-0023), its recipe
channels and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``), the shared
failure taxonomy (``gda.errors``), the binary/display probes and the harness
installer — and is imported by nothing but the composition root (``gda.cli``).

It COEXISTS with the ``gda.daemon`` PACKAGE (``server`` / ``session`` /
``discovery`` / ``protocol``), which is the daemon process itself; this module is
the CLI-side group that manages that process. Both are reached by their absolute
import paths (``gda.daemon.discovery``, ``gda.commands.daemon``), never a relative
one, so the two stay distinct.

The group is a deliberate extension of ADR-0005's domain-object grouping to an
infrastructure object (gda-daemon), not a top-level meta singleton. None of its
operations is a sentinel op. The lifecycle commands each run a recipe — like
``export run``: ``start`` gates the platform (live is UNIX-only, ADR-0021),
performs the reported idempotent harness install (ADR-0018), spawns the detached
daemon, and waits until it is accepting; ``stop`` asks it to shut down;
``status`` reports liveness from the pidfile; and ``install`` / ``uninstall``
are the harness half of the lifecycle on their own — the same install ``start``
folds in, and its paired removal. The ONE exception (#657, ADR-0040 amendment)
is ``wait-ready``: ``kind = LIVE``, routed through the daemon socket and
``classify_live`` like ``diag errors``, because its object is the engine session
the running daemon holds — not the daemon process lifecycle.
"""

import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import typer
from pydantic import BaseModel, Field

from gda.binary import resolve_godot_binary
from gda.daemon.discovery import (
    DaemonPaths,
    daemon_paths,
    daemon_pid,
    within_uds_limit,
)
from gda.display import WindowedUnavailable, windowed_unavailable
from gda.daemon.protocol import read_message, write_message
from gda.daemon.server import (
    STATUS_OP,
    STOP_OP,
    WAIT_READY_OP,
    WAIT_READY_TIMEOUT_MAX,
)
from gda.daemon.session import CONNECT_TIMEOUT
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import Failure, make_failure, unresolvable_binary_failure
from gda.execution import MIN_LIVE_VERSION, ExecutionKind
from gda.harness.install import (
    HarnessSnapshot,
    install_harness,
    uninstall_harness,
)
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)


class DaemonStartParams(BaseModel):
    """The params of ``gda daemon start``: its engine session's display mode and scene.

    The project is the ``--project`` context. ``windowed`` is a START-TIME declared
    mode (ADR-0017 refined by #222) — the daemon launches its engine session windowed
    (no ``--headless``) so a ``screen`` capture op has a real ``DisplayServer`` to read
    pixels from; default false keeps the cheap non-visual sessions (``game tree``,
    ``perf``, ``diag``) headless. ``scene`` is a START-TIME selector (ADR-0017 amended
    by #278): when set the daemon boots the session on that chosen scene via Godot's
    ``--scene`` engine option (before ``--path``) instead of the project's
    ``main_scene``; default null runs ``main_scene`` unchanged. Both modes are fixed
    for the session's life (ADR-0020 single session) — NOT switched mid-session.
    """

    windowed: bool = Field(
        default=False,
        description=(
            "Launch the engine session windowed (no --headless) so `screen` capture "
            "ops have a display; default headless. Requires a display/Xvfb on a "
            "headless host."
        ),
    )
    scene: str | None = Field(
        default=None,
        description=(
            "Boot the engine session on this scene (a `res://…` path or a `uid://…` "
            "value, per Godot's `--scene`) instead of the project's main_scene; "
            "default null runs main_scene unchanged. A non-existent scene is a typed "
            "`live_scene_not_found` error, never a silent fall back to main_scene."
        ),
    )


class DaemonStartResult(BaseModel):
    """The result of ``gda daemon start``: the live context it brought up (ADR-0017)."""

    pid: int = Field(description="The gda-daemon process id.")
    socket_path: str = Field(
        description="The per-project CLI socket the daemon listens on."
    )
    installed_harness: bool = Field(
        description="Whether this start installed or updated the harness autoload (ADR-0018)."
    )
    harness_synced: bool = Field(
        default=False,
        description=(
            "Whether this start re-materialized the harness to the running gda's "
            "version because the installed copy declared an older one — true only "
            "on a real version-mismatch rewrite, not merely adding the autoload "
            "entry (#225, ADR-0018)."
        ),
    )
    harness_version: str = Field(
        default="",
        description="The gda harness version now installed in the project (#225).",
    )
    created_paths: list[str] = Field(
        default_factory=list,
        description=(
            "The `res://` paths this start CREATED in the project (outermost "
            "directory first), so the harness install is an auditable mutation "
            "rather than a silent write into a tracked project (#654). Empty on an "
            "idempotent repeat start and on a version resync — those rewrite the "
            "harness (`harness_synced`) but create nothing new. Reversed by "
            "`gda daemon uninstall`, except `res://addons` itself: an empty "
            "directory is invisible to git, and the shared Godot addons directory "
            "may be about to hold another addon."
        ),
    )
    created_sections: list[str] = Field(
        default_factory=list,
        description=(
            "The `project.godot` sections this start CREATED — `[autoload]` when the "
            "project had none. Empty when the harness entry joined a section that "
            "already existed, which `gda daemon uninstall` then leaves in place (#654)."
        ),
    )
    windowed: bool | None = Field(
        default=None,
        description=(
            "Whether the engine session was launched windowed (no --headless), the "
            "mode a `screen` capture op requires. The launched mode on a fresh start; "
            "**null** on an idempotent already-running start, which does not relaunch "
            "the session and cannot re-derive the running daemon's launch-time mode "
            "from the pidfile — null means 'not determined here', not 'headless' "
            "(#222, PR #248 review)."
        ),
    )
    already_running: bool = Field(
        description="Whether a daemon was already running, so start was a no-op."
    )


class DaemonStopParams(BaseModel):
    """The params of ``gda daemon stop``: none."""


class DaemonStopResult(BaseModel):
    """The result of ``gda daemon stop``: whether a running daemon was torn down."""

    stopped: bool = Field(
        description="Whether a running daemon was stopped (False if none was running)."
    )
    pid: int | None = Field(
        default=None, description="The stopped daemon's pid, if one was running."
    )


class DaemonStatusParams(BaseModel):
    """The params of ``gda daemon status``: none."""


class DaemonStatusResult(BaseModel):
    """The result of ``gda daemon status``: whether a per-project daemon is up."""

    running: bool = Field(
        description="Whether a gda-daemon is running for the project."
    )
    pid: int | None = Field(
        default=None, description="The running daemon's pid, if any."
    )
    socket_path: str = Field(description="The per-project CLI socket path.")
    windowed: bool | None = Field(
        default=None,
        description=(
            "Whether the running daemon was launched windowed (no --headless), the "
            "mode a `screen` capture op requires — read over the daemon's STATUS_OP, "
            "the running daemon being the authority for its launch-time mode (#251). "
            "**null** when the mode is undetermined: either no daemon is running "
            "(alongside `running: false`), or a daemon is running (`running: true`) "
            "but its bounded STATUS_OP round trip missed transiently."
        ),
    )


class DaemonWaitReadyParams(BaseModel):
    """The params of ``gda daemon wait-ready``: the readiness budget (#657).

    The daemon launches its engine session LAZILY on the first operation that
    requires one (ADR-0017); this command is the explicit way to BE that
    operation. ``timeout`` is the daemon-side budget for the launch — every wait
    and new-work decision draws from one instant and none is renewed — not a poll
    interval and not a sleep loop: one request, one launch, one answer. A
    synchronous call already in flight can delay when expiry is observed. The
    (0, 50] cap is the shared
    ``gda.daemon.server.WAIT_READY_TIMEOUT_MAX``, which the daemon re-enforces
    at its IPC boundary for non-gda clients.
    """

    timeout: float = Field(
        default=CONNECT_TIMEOUT,
        gt=0,
        le=WAIT_READY_TIMEOUT_MAX,
        allow_inf_nan=False,
        description=(
            "The daemon-side budget, in seconds, shared by the engine launch's "
            "waits and new-work decisions: engine boot, the project's autoloads, "
            "and the in-game harness connecting back and completing its handshake. "
            "A synchronous call already in flight can delay when expiry is "
            "observed. When the budget is exhausted, the reply is "
            "'engine_session_not_running' carrying the launch diagnostics. Must "
            "be a finite number in "
            f"(0, {int(WAIT_READY_TIMEOUT_MAX)}]: the live channel bounds the "
            "whole request round trip at 60s client-side, so the wait has to "
            f"resolve inside it. Defaults to {int(CONNECT_TIMEOUT)}."
        ),
    )


class DaemonWaitReadyResult(BaseModel):
    """The result of ``gda daemon wait-ready``: the engine session serves (#657).

    Success IS the readiness contract: the session's harness has connected and
    presented its token, so subsequent live reads — including a first ``gda diag
    errors``, which deliberately never launches a session itself (ADR-0022) —
    serve without a warm-up read.
    """

    pid: int = Field(description="The serving gda-daemon's process id.")
    launched: bool = Field(
        description=(
            "Whether THIS call launched the engine session (true), or one was "
            "already serving (false — idempotent, nothing was relaunched). "
            "Sessions stay lazily launched (ADR-0017); this command is the "
            "documented way to trigger that launch explicitly."
        )
    )


class DaemonInstallParams(BaseModel):
    """The params of ``gda daemon install``: none (the project is the --project context)."""


class DaemonInstallResult(BaseModel):
    """The result of ``gda daemon install``: the harness install it performed (ADR-0018).

    The same five facts ``daemon start`` reports about its folded-in install, from the
    same ``install_harness`` call — so an agent reads one shape whether the install
    happened on its own or as part of a start.
    """

    installed_harness: bool = Field(
        description=(
            "Whether this call installed or updated the harness autoload; False is "
            "the idempotent no-op when the current version was already installed."
        )
    )
    harness_synced: bool = Field(
        default=False,
        description=(
            "Whether an ALREADY-installed harness was re-materialized because it "
            "declared an older version — true only on a real stale->current rewrite, "
            "never on a first install (#225, ADR-0018)."
        ),
    )
    harness_version: str = Field(
        description="The gda harness version now installed in the project (#225)."
    )
    created_paths: list[str] = Field(
        default_factory=list,
        description=(
            "The `res://` paths this call CREATED in the project (outermost directory "
            "first), so the install is an auditable mutation rather than a silent "
            "write into a tracked project (#654). Empty on an idempotent repeat and "
            "on a version resync — those rewrite the harness (`harness_synced`) but "
            "create nothing new. Reversed by `gda daemon uninstall`, except "
            "`res://addons` itself."
        ),
    )
    created_sections: list[str] = Field(
        default_factory=list,
        description=(
            "The `project.godot` sections this call CREATED — `[autoload]` when the "
            "project had none. Empty when the harness entry joined a section that "
            "already existed, which `gda daemon uninstall` then leaves in place (#654)."
        ),
    )


class DaemonUninstallParams(BaseModel):
    """The params of ``gda daemon uninstall``: none (the project is the --project context)."""


class DaemonUninstallResult(BaseModel):
    """The result of ``gda daemon uninstall``: the paired harness removal (ADR-0018, #225).

    #654 makes the removal complete AND self-reporting: the engine-generated `.uid`
    sidecar and a now-empty `[autoload]` section go too, so a project that only ever
    ran a live session is left as it was, and ``removed_paths`` / ``removed_sections``
    name every path and section that went.
    """

    removed: bool = Field(
        description=(
            "Whether the harness autoload and files were removed; False is the "
            "idempotent no-op when no harness was installed (mirrors daemon stop)."
        )
    )
    removed_paths: list[str] = Field(
        default_factory=list,
        description=(
            "The `res://` paths removed: the harness script, its engine-generated "
            "`.uid` sidecar, and `res://addons/gda_harness` once empty (#654). "
            "`res://addons` is left in place: an empty directory is invisible to "
            "git, so it causes none of the tracked-file churn this removal is for, "
            "and the shared Godot addons directory may be about to hold another "
            "addon."
        ),
    )
    removed_sections: list[str] = Field(
        default_factory=list,
        description=(
            "The `project.godot` sections removed — `[autoload]` when dropping the "
            "harness entry left it with no keys, so a live session no longer leaves "
            "an empty generated section behind in a tracked file (#654). A section "
            "with any surviving user autoload is kept."
        ),
    )


_READY_TIMEOUT = 8.0
_STOP_TIMEOUT = 8.0
_POLL = 0.05

# Phase-2 live requires Godot 4.6+ (the UDS transport landed in 4.6; ADR-0021).
# The floor itself lives in ``gda.execution`` as the single source of truth — the
# ``live_stack_constraints`` predicate that surfaces it in ``--schema`` (issue
# #233) shares it — and is imported back here for the version gate.
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

# Seams tests override to avoid launching a real process / running the engine.
SpawnDaemon = Callable[[Path, str, bool, Optional[str]], None]
VersionCheck = Callable[[str], Optional[tuple]]
# The pre-launch host-display precondition seam (#345, #667): returns the verdict
# for why a windowed session cannot come up here — which registered code, the prose,
# and the probe that decided it — or None when it can. Injected in unit tests so a
# display-less CI host does not spuriously refuse a windowed start, and so the
# capability/permission split is exercised without needing a real sandbox.
DisplayCheck = Callable[[], Optional[WindowedUnavailable]]


def _is_unix() -> bool:
    return os.name == "posix"


# The UNIX wording differs between `daemon start` and the other three lifecycle
# operations; the two variants predate this extraction and are kept verbatim, so
# `start` passes its own through ``unix_message``.
_UNIX_REQUIRED = (
    "the gda-daemon requires a UNIX platform (macOS/Linux); it uses Unix "
    "domain sockets, which are unavailable here"
)


def _lifecycle_preconditions(
    project: Optional[Path], *, unix_message: str = _UNIX_REQUIRED
) -> "Path | Failure":
    """The two guards every daemon lifecycle operation opens with.

    The platform gate first (a Unix domain socket is the daemon's transport,
    ADR-0021), then the project gate — the daemon is per-project, so there is
    nothing to address without one. Returns the project to operate on, or the
    ``Failure`` that stops the operation before it touches any daemon state.
    """
    if not _is_unix():
        return make_failure("live_unsupported_platform", unix_message, "")
    if project is None:
        return make_failure(
            "project_not_found",
            "gda daemon needs a Godot project; pass --project or run inside one",
            "",
        )
    return project


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


def _spawn_daemon(
    project: Path, binary: str, windowed: bool, scene: Optional[str]
) -> None:
    """Spawn the detached, per-project daemon (its own session, no std streams).

    ``windowed`` is forwarded as ``--windowed`` so the daemon launches its engine
    session with a real ``DisplayServer`` (no ``--headless``) — the start-time
    declared display mode a ``screen`` capture op needs (ADR-0017 refined, #222).
    ``scene`` is forwarded as ``--scene <path|UID>`` so the daemon boots the session
    on that chosen scene instead of the project's main_scene (ADR-0017 amendment,
    #278); omitted when ``None``.
    """
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gda.daemon",
            "--project",
            str(project),
            "--godot",
            str(binary),
            *(["--windowed"] if windowed else []),
            *(["--scene", scene] if scene is not None else []),
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


_START_FAILED = "the gda-daemon did not start (it never began accepting on its socket)"


@dataclass(frozen=True)
class _RestoreOutcome:
    """What undoing a failed harness install achieved, and what it left behind.

    Exactly one of the two is meaningful: ``residue`` is the sentence naming the
    rollback failure AND the paths still differing from their pre-install state (files
    and created directories, measured off the snapshot); ``undone`` is what came back
    when there was no such failure — empty when the operation had written nothing to
    undo. Kept as one value so the two callers below decide only HOW to report it,
    never how to phrase it.
    """

    undone: tuple[str, ...] = ()
    residue: Optional[str] = None


def _restore_harness_install(snapshot: HarnessSnapshot) -> _RestoreOutcome:
    """Undo a failed harness install, and describe the outcome for the caller to report.

    Takes ONLY the snapshot: the restore must work for an operation that failed at any
    point after the snapshot was taken, including PART WAY THROUGH the install itself
    (a read-only ``project.godot`` makes ``install_harness`` raise after it has
    already materialized the harness), where no receipt exists to consult (PR #680
    recheck 2).

    Never raises: a restore failure must not replace the failure the caller is
    already reporting — it is reported ALONGSIDE it, as the mutation the user now has
    to clean up by hand. Measuring the residue must not throw either, so the whole
    sentence is built here, once, for both ways it is reported.
    """
    try:
        return _RestoreOutcome(undone=snapshot.restore())
    except OSError as exc:
        return _RestoreOutcome(
            residue=(
                f"the harness install could NOT be rolled back ({exc}); these paths "
                f"still differ from their pre-install state: "
                f"{', '.join(snapshot.pending())}"
            )
        )


def _note_failed_restore(exc: BaseException, snapshot: HarnessSnapshot) -> None:
    """Roll the harness install back, and annotate ``exc`` if the rollback also failed.

    The exception arm shared by the two operations that install the harness
    (``daemon start`` and ``daemon install``): the ORIGINAL error stays the primary
    failure, and only when the restore itself fails does the residue ride along as a
    note. Silently dropping it would hide residue ADR-0018 requires reporting.
    """
    outcome = _restore_harness_install(snapshot)
    if outcome.residue is not None:
        exc.add_note(f"additionally, {outcome.residue}")


def _failed_start_failure(snapshot: HarnessSnapshot) -> Failure:
    """The ``daemon_not_running`` failure for a start that never became ready.

    Carries the harness install's fate in the ``diagnostics`` prose (ADR-0004 shape
    unchanged, no new error code): what was restored, or — when the restore itself
    failed — the residue the same rollback reports to the exception arm above. The
    two spellings of "what happened to the install" are one sentence, built once.
    """
    outcome = _restore_harness_install(snapshot)
    if outcome.residue is not None:
        return make_failure("daemon_not_running", _START_FAILED, outcome.residue)
    if not outcome.undone:
        return make_failure("daemon_not_running", _START_FAILED, "")
    return make_failure(
        "daemon_not_running",
        _START_FAILED,
        f"rolled back this start's harness install: {', '.join(outcome.undone)}",
    )


def run_daemon_start_operation(
    project: Optional[Path],
    godot: Optional[str],
    *,
    windowed: bool = False,
    scene: Optional[str] = None,
    spawn: Optional[SpawnDaemon] = None,
    version_check: Optional[VersionCheck] = None,
    display_check: Optional[DisplayCheck] = None,
) -> "DaemonStartResult | Failure":
    checked = _lifecycle_preconditions(
        project,
        unix_message=(
            "live operations require a UNIX platform (macOS/Linux); the daemon uses "
            "Unix domain sockets, which are unavailable here"
        ),
    )
    if isinstance(checked, Failure):
        return checked
    project = checked
    paths = daemon_paths(project)
    if not (
        within_uds_limit(paths.cli_socket) and within_uds_limit(paths.harness_socket)
    ):
        # Fail clearly here rather than letting the daemon's bind() overflow the
        # OS sun_path limit and the start time out into a vague error (ADR-0021).
        return make_failure(
            "daemon_not_running",
            "the runtime directory yields a socket path longer than the OS limit "
            "for a Unix domain socket; set a shorter $XDG_RUNTIME_DIR",
            "",
        )
    existing = daemon_pid(paths)
    if existing is not None:
        if scene is not None:
            # `--scene` only takes effect at daemon START (the daemon holds it for the
            # session it launches). A daemon is already up, so the chosen scene would
            # be silently ignored — surface a typed refusal instead of a quiet no-op
            # (#278 review finding 3). The remediation: stop, then start --scene.
            return make_failure(
                "daemon_already_running",
                "a gda-daemon is already running for this project, so `--scene` would "
                "be ignored — it only takes effect when the daemon starts. Run "
                "`gda daemon stop`, then `gda daemon start --scene <path|UID>`",
                "",
            )
        # Idempotent: a daemon is already up for this project — but still self-sync
        # the installed harness (#225), so upgrading `gda` while an old daemon stays
        # up never leaves a stale harness on disk. The next engine session the
        # daemon launches reads the synced copy (sessions launch lazily and relaunch
        # once the prior one dies, ADR-0017), so a `daemon start` before any live op
        # — the common flow — is fully resynced. `harness_synced` is true only on a
        # real stale→current rewrite, so a steady-state repeat start still reports
        # false and writes nothing (no mtime bump, no concurrent-editor prompt).
        installed = install_harness(project)
        return DaemonStartResult(
            pid=existing,
            socket_path=str(paths.cli_socket),
            installed_harness=installed.changed,
            harness_synced=installed.synced,
            harness_version=installed.version,
            created_paths=list(installed.created_paths),
            created_sections=list(installed.created_sections),
            # An idempotent start does not relaunch the session and cannot re-derive
            # the running daemon's display mode from the pidfile, so report `None`
            # ("not determined here") rather than a misleading `False` — a daemon
            # launched windowed would otherwise read as headless (#222, PR #248 review).
            windowed=None,
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
        return make_failure(
            "unsupported_version",
            f"live operations require Godot {minimum}+ (the daemon transport uses Unix "
            f"domain sockets, added in {minimum}); the engine reports {found}",
            "",
        )

    if windowed:
        # A windowed session needs a usable host DisplayServer; without one Godot
        # aborts during DisplayServer registration (before its file logger is even
        # installed), so the failure would otherwise surface only as a generic
        # engine_session_not_running at lazy launch (#345 Part A). Refuse fast HERE —
        # pre-launch, pre-harness-install, WITHOUT spawning — with the typed
        # live_windowed_unavailable (ENVIRONMENT / 127), mirroring the platform
        # precondition above. `daemon start` is where `windowed` already flows in.
        #
        # The probe decides WHICH refusal (#667): no detected window-server session
        # is live_windowed_unavailable; a DENIED window-server lookup — which proves
        # nothing about whether the host has one — is live_windowed_permission_denied,
        # i.e. "skip rendered QA here" versus "re-run outside the restriction to find
        # out". Both carry
        # the deciding probe as machine-readable envelope context (ADR-0004
        # amendment) so an agent branches without parsing the sentence.
        unavailable = (display_check or windowed_unavailable)()
        if unavailable is not None:
            return make_failure(
                unavailable.code,
                unavailable.reason,
                "",
                probe=unavailable.probe,
            )

    # The harness install happens BEFORE the daemon exists, so everything from the
    # install onward runs against a project gda has already mutated. The snapshot is
    # therefore taken FIRST and the install itself sits INSIDE the guarded region
    # (PR #680 recheck 2): `install_harness` materializes the harness file before it
    # writes the autoload config, so a config write that fails — a read-only
    # `project.godot` is enough — used to escape with the harness already on disk,
    # before any restore could run and with no receipt ever produced.
    #
    # The restore is driven by the SNAPSHOT alone, never by the install's receipt: a
    # receipt cannot describe how to undo an install that re-materialized a stale
    # body or re-pointed an existing entry (both CREATE nothing), and a half-finished
    # install has no receipt at all. The exception arm re-raises the ORIGINAL error as
    # the primary failure and reports a restore that also failed alongside it — the
    # arm `daemon install` shares (`_note_failed_restore`).
    snapshot = HarnessSnapshot.capture(project)
    try:
        installed = install_harness(project)
        (spawn or _spawn_daemon)(project, str(binary), windowed, scene)
        pid = _await_ready(paths)
    except BaseException as exc:
        _note_failed_restore(exc, snapshot)
        raise
    if pid is None:
        return _failed_start_failure(snapshot)
    return DaemonStartResult(
        pid=pid,
        socket_path=str(paths.cli_socket),
        installed_harness=installed.changed,
        harness_synced=installed.synced,
        harness_version=installed.version,
        created_paths=list(installed.created_paths),
        created_sections=list(installed.created_sections),
        windowed=windowed,
        already_running=False,
    )


def run_daemon_stop_operation(project: Optional[Path]) -> "DaemonStopResult | Failure":
    checked = _lifecycle_preconditions(project)
    if isinstance(checked, Failure):
        return checked
    project = checked
    paths = daemon_paths(project)
    pid = daemon_pid(paths)
    if pid is None:
        return DaemonStopResult(stopped=False, pid=None)
    _control(paths.cli_socket, STOP_OP)
    _await_gone(paths, pid)
    return DaemonStopResult(stopped=True, pid=pid)


def run_daemon_status_operation(
    project: Optional[Path],
) -> "DaemonStatusResult | Failure":
    checked = _lifecycle_preconditions(project)
    if isinstance(checked, Failure):
        return checked
    project = checked
    paths = daemon_paths(project)
    pid = daemon_pid(paths)
    # Liveness stays the pidfile's call (ADR-0021). When a daemon is up, round-trip
    # its STATUS_OP to read the launch-time display mode — the running daemon is the
    # only authority for the mode it was started with, which a pidfile cannot record
    # (#251). No daemon -> no round trip; a transient round-trip miss on a dying
    # daemon -> `windowed` stays None. `_control`'s bounded timeout means no hang.
    windowed = None
    if pid is not None:
        reply = _control(paths.cli_socket, STATUS_OP)
        if reply and reply.get("ok"):
            windowed = reply.get("windowed")
    return DaemonStatusResult(
        running=pid is not None,
        pid=pid,
        socket_path=str(paths.cli_socket),
        windowed=windowed,
    )


def run_daemon_install_operation(
    project: Optional[Path],
) -> "DaemonInstallResult | Failure":
    """Install (or re-sync) the harness autoload in the project (ADR-0018, #670).

    The install ``daemon start`` folds in, made runnable on its own — the SAME
    ``install_harness`` seam, never a second implementation — so an agent can put the
    project in the state a live session needs, and see what that did, without starting
    a daemon. Idempotent: a repeat over a current install writes nothing.

    Unlike ``uninstall`` it is NOT refused while a daemon runs: installing over a live
    daemon is exactly what a repeat ``daemon start`` already does, and it takes nothing
    away from the running session. It is transactional for the same reason ``start``
    is: the install is multi-step, so a config write that fails must not leave the
    materialized harness behind.
    """
    checked = _lifecycle_preconditions(project)
    if isinstance(checked, Failure):
        return checked
    project = checked
    snapshot = HarnessSnapshot.capture(project)
    try:
        installed = install_harness(project)
    except BaseException as exc:
        _note_failed_restore(exc, snapshot)
        raise
    return DaemonInstallResult(
        installed_harness=installed.changed,
        harness_synced=installed.synced,
        harness_version=installed.version,
        created_paths=list(installed.created_paths),
        created_sections=list(installed.created_sections),
    )


def run_daemon_uninstall_operation(
    project: Optional[Path],
) -> "DaemonUninstallResult | Failure":
    """Remove the harness autoload + files from the project (ADR-0018, #225).

    A release-hygiene step (ADR-0018 point 3): removal is paired and crash-safe
    (autoload entry first, then files — :func:`uninstall_harness`). It is **refused
    while a daemon is running** (``daemon_running``): the daemon holds a live engine
    session whose autoload this would yank out from under it. Idempotent: a no-op
    success when nothing is installed (mirrors ``daemon stop``).
    """
    checked = _lifecycle_preconditions(project)
    if isinstance(checked, Failure):
        return checked
    project = checked
    paths = daemon_paths(project)
    if daemon_pid(paths) is not None:
        return make_failure(
            "daemon_running",
            "a gda-daemon is running for this project; stop it first with "
            "`gda daemon stop` before uninstalling the harness",
            "",
        )
    result = uninstall_harness(project)
    return DaemonUninstallResult(
        removed=result.removed,
        removed_paths=list(result.removed_paths),
        removed_sections=list(result.removed_sections),
    )


def render_daemon_start(started: "DaemonStartResult") -> str:
    """Render a `gda daemon start` outcome for humans."""
    state = "already running" if started.already_running else "started"
    if started.harness_synced:
        harness = f" (synced harness to v{started.harness_version})"
    elif started.installed_harness:
        harness = " (installed harness)"
    else:
        harness = ""
    # The session's display mode is part of the live context the start brought up
    # (#222) — note it only when windowed, since headless is the default.
    mode = " [windowed]" if started.windowed else ""
    return f"daemon {state}: pid {started.pid} on {started.socket_path}{mode}{harness}"


def render_daemon_stop(stopped: "DaemonStopResult") -> str:
    """Render a `gda daemon stop` outcome for humans."""
    if stopped.stopped:
        return f"daemon stopped (pid {stopped.pid})"
    return "no daemon was running"


def render_daemon_status(status: "DaemonStatusResult") -> str:
    """Render a `gda daemon status` outcome for humans."""
    if status.running:
        # Mirror `daemon start`: note the display mode only when windowed (#251),
        # since headless is the default and an unknown mode (null) has nothing to say.
        mode = " [windowed]" if status.windowed else ""
        return f"daemon running: pid {status.pid} on {status.socket_path}{mode}"
    return "daemon not running"


def render_daemon_wait_ready(ready: "DaemonWaitReadyResult") -> str:
    """Render a `gda daemon wait-ready` outcome for humans."""
    state = "launched now" if ready.launched else "already serving"
    return f"engine session ready ({state}; daemon pid {ready.pid})"


def render_daemon_install(installed: "DaemonInstallResult") -> str:
    """Render a `gda daemon install` outcome for humans.

    Naming what changed is the point of running it explicitly, so the line reports
    which of the three things happened — a resync, a no-op, or a real install — and,
    for the install, the same mutation set the JSON result enumerates (mirroring
    `daemon uninstall`).
    """
    if installed.harness_synced:
        return f"harness synced to v{installed.harness_version}"
    if not installed.installed_harness:
        return f"harness already installed (v{installed.harness_version})"
    created = [
        *installed.created_paths,
        *(f"{section} in project.godot" for section in installed.created_sections),
    ]
    if not created:
        # The entry was all that was missing: the files were already in place and the
        # section already existed, so nothing was created — name the entry instead.
        return (
            f"harness installed (v{installed.harness_version}): the GdaHarness "
            "autoload entry in project.godot"
        )
    return f"harness installed (v{installed.harness_version}): " + ", ".join(created)


def render_daemon_uninstall(uninstalled: "DaemonUninstallResult") -> str:
    """Render a `gda daemon uninstall` outcome for humans.

    Naming what went is the point of this command (#654) — it is the step that
    hands a tracked project back — so the human line carries the same removal set
    the JSON result enumerates, not just the fact that something was removed.
    """
    if not uninstalled.removed:
        return "no harness was installed"
    removed = [
        *uninstalled.removed_paths,
        *(f"{section} in project.godot" for section in uninstalled.removed_sections),
    ]
    if not removed:
        # The entry was the only thing left to remove: the harness files were already
        # gone AND a sibling autoload keeps the section alive, so neither list has
        # anything in it. Name the entry rather than render a bare "uninstalled".
        return "harness uninstalled: the GdaHarness [autoload] entry in project.godot"
    return "harness uninstalled: " + ", ".join(removed)


# --- Recipe channels (ADR-0023) -----------------------------------------------
# Each daemon lifecycle command carries one of these on its descriptor (``recipe=``).
# A recipe PRODUCES the outcome — run the CLI-side operation over the ALREADY-resolved
# ``project`` (resolution happens once in :func:`gda.dispatch.dispatch_recipe`, kept
# CLI-side per ADR-0006, so an invalid --project is a structured project_not_found
# before any recipe runs, #353) — and RETURNS the typed result or a Failure; emission
# stays the shared tail (:func:`gda.dispatch.dispatch_recipe` → ``cmd.render``), so a
# recipe command renders exactly like a sentinel one. ``params`` is the built model —
# the single source of truth (ADR-0015), identical on the argv and ``--params-json``
# paths — so windowed/scene are read off it, never special-cased.


def _daemon_start_recipe(params, *, project, godot):
    return run_daemon_start_operation(
        project,
        godot,
        windowed=params.windowed,
        scene=params.scene,
    )


def _daemon_stop_recipe(params, *, project, godot):
    return run_daemon_stop_operation(project)


def _daemon_status_recipe(params, *, project, godot):
    return run_daemon_status_operation(project)


def _daemon_install_recipe(params, *, project, godot):
    return run_daemon_install_operation(project)


def _daemon_uninstall_recipe(params, *, project, godot):
    return run_daemon_uninstall_operation(project)


DAEMON_START_COMMAND: HeadlessCommand[DaemonStartResult] = HeadlessCommand(
    operation="daemon-start",
    input_model=DaemonStartParams,
    output_model=DaemonStartResult,
    render=render_daemon_start,
    recipe=_daemon_start_recipe,
)

DAEMON_STOP_COMMAND: HeadlessCommand[DaemonStopResult] = HeadlessCommand(
    operation="daemon-stop",
    input_model=DaemonStopParams,
    output_model=DaemonStopResult,
    render=render_daemon_stop,
    recipe=_daemon_stop_recipe,
)

DAEMON_STATUS_COMMAND: HeadlessCommand[DaemonStatusResult] = HeadlessCommand(
    operation="daemon-status",
    input_model=DaemonStatusParams,
    output_model=DaemonStatusResult,
    render=render_daemon_status,
    recipe=_daemon_status_recipe,
)

# `wait-ready` is the group's one `kind = LIVE` command (#657): it routes through
# the live channel — the daemon socket, `classify_live`, the 60s client bound —
# like `diag errors` does, and is daemon-served rather than harness-relayed. The
# rest of the group stays the recipe-run lifecycle family (ADR-0017); this one is
# about the SESSION the daemon holds, which is exactly the live channel's object.
DAEMON_WAIT_READY_COMMAND: HeadlessCommand[DaemonWaitReadyResult] = HeadlessCommand(
    operation=WAIT_READY_OP,
    input_model=DaemonWaitReadyParams,
    output_model=DaemonWaitReadyResult,
    render=render_daemon_wait_ready,
    kind=ExecutionKind.LIVE,
)

DAEMON_INSTALL_COMMAND: HeadlessCommand[DaemonInstallResult] = HeadlessCommand(
    operation="daemon-install",
    input_model=DaemonInstallParams,
    output_model=DaemonInstallResult,
    render=render_daemon_install,
    recipe=_daemon_install_recipe,
)

DAEMON_UNINSTALL_COMMAND: HeadlessCommand[DaemonUninstallResult] = HeadlessCommand(
    operation="daemon-uninstall",
    input_model=DaemonUninstallParams,
    output_model=DaemonUninstallResult,
    render=render_daemon_uninstall,
    recipe=_daemon_uninstall_recipe,
)


# The daemon command group (Phase 2, ADR-0017): gda's own per-project daemon
# lifecycle — a deliberate extension of ADR-0005's domain-object grouping to an
# infrastructure object (gda-daemon), not a top-level meta singleton. start /
# stop / status manage the daemon PROCESS, so — like `export run` — they run a
# recipe (the operations above) rather than the sentinel pipeline.
_app = typer.Typer(
    help="Manage the per-project gda-daemon (live ops).",
    no_args_is_help=True,
)


@_app.command(name="start", cls=DAEMON_START_COMMAND.command_class())
def daemon_start(
    windowed: bool = typer.Option(
        False,
        "--windowed",
        help=(
            "Launch the engine session windowed (no --headless) so `screen` capture "
            "ops have a display; default headless. Needs a display/Xvfb on a "
            "headless host (#222)."
        ),
    ),
    scene: Optional[str] = typer.Option(
        None,
        "--scene",
        help=(
            "Boot the engine session on this scene (a res:// path or uid:// value) "
            "instead of the project's main_scene; default runs main_scene. A "
            "non-existent scene is a typed `live_scene_not_found` error, never a "
            "silent fall back (#278)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = DAEMON_START_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Start the per-project gda-daemon (idempotent), installing the harness.

    Brings up the live context: a long-lived, per-project daemon, after a reported
    idempotent harness install (ADR-0018). Never auto-spawned by a live call —
    launching the engine is a deliberate, declared effect (ADR-0017). The
    platform/Godot-version precondition is the structured `constraints` field of
    `--schema` (ADR-0021), not restated here. `--windowed` is a start-time declared
    mode for the engine session a `screen` capture op needs (#222); `--scene` boots
    the session on a chosen scene instead of the project's main_scene (#278).
    """
    # Build the params model from the argv options (the single source of truth,
    # ADR-0015) so the recipe reads `windowed`/`scene` off it on BOTH the argv and
    # --params-json paths — no special-casing.
    dispatch_recipe(
        DAEMON_START_COMMAND,
        DaemonStartParams(windowed=windowed, scene=scene),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="stop", cls=DAEMON_STOP_COMMAND.command_class())
def daemon_stop(
    json_output: bool = json_option(),
    schema: bool = DAEMON_STOP_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Stop the per-project gda-daemon (a no-op if none is running).

    On an unsupported platform this reports `live_unsupported_platform`; the
    platform precondition is the structured `constraints` field of `--schema`.
    """
    dispatch_recipe(
        DAEMON_STOP_COMMAND,
        DaemonStopParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="status", cls=DAEMON_STATUS_COMMAND.command_class())
def daemon_status(
    json_output: bool = json_option(),
    schema: bool = DAEMON_STATUS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report whether a per-project gda-daemon is running.

    On an unsupported platform this reports `live_unsupported_platform`; the
    platform precondition is the structured `constraints` field of `--schema`.
    """
    dispatch_recipe(
        DAEMON_STATUS_COMMAND,
        DaemonStatusParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="wait-ready", cls=DAEMON_WAIT_READY_COMMAND.command_class())
def daemon_wait_ready(
    timeout: float = typer.Option(
        CONNECT_TIMEOUT,
        "--timeout",
        help=(
            "Daemon-side budget for the session launch's waits and new-work "
            "decisions (engine boot + autoloads + harness connect). A synchronous "
            "call already in flight can delay when expiry is observed. When the "
            "budget is exhausted, the daemon reports "
            "'engine_session_not_running' with the launch diagnostics. A finite "
            f"number in (0, 50]; defaults to {int(CONNECT_TIMEOUT)}."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = DAEMON_WAIT_READY_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Establish the engine session under one budget until live reads serve.

    The daemon launches its engine session LAZILY, on the first operation that
    REQUIRES one (ADR-0017) — and a read-only diagnostic never does: right
    after `gda daemon start`, `gda diag errors` reports
    `engine_session_not_running` by design, because a read must never be the
    thing that runs the project's code (ADR-0022). This command is the
    documented way to trigger the launch explicitly: it asks the daemon to
    launch the session — running the
    project's autoloads and its scene, inside the trusted-project assumption
    (ADR-0009) — and returns once the in-game harness has connected, after
    which live reads (including a first `diag errors`) serve. Idempotent while
    a session is alive: `launched: false`, nothing relaunched. With no daemon
    it reports `daemon_not_running`; when the daemon-side `--timeout` budget is
    exhausted, it reports `engine_session_not_running` with the launch
    diagnostics. The budget governs waits and new-work decisions, not the wall
    time of a synchronous call already in flight.
    """
    # The params model owns the bounds (ADR-0015); this argv body only
    # translates a model refusal into the Click usage error.
    dispatch_domain(
        DAEMON_WAIT_READY_COMMAND,
        params_or_bad_parameter(DaemonWaitReadyParams, timeout=timeout),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="install", cls=DAEMON_INSTALL_COMMAND.command_class())
def daemon_install(
    json_output: bool = json_option(),
    schema: bool = DAEMON_INSTALL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Install the gda harness autoload into the project, without starting a daemon.

    The setup step for live operations, made explicit (ADR-0018, #670): it writes the
    harness into `project.godot`'s autoload section and reports exactly what it
    created, so the one mutation gda makes to a tracked project is visible before a
    session runs. `gda daemon start` performs the same install itself, so this is
    never a prerequisite for it — it is for putting the project in that state
    deliberately (to review or commit the change), or for checking what is installed.

    Idempotent: a repeat over a current install writes nothing and reports
    `installed_harness: false`; a harness from an older gda is re-materialized and
    reported as `harness_synced`. Allowed while a daemon is running, unlike
    `gda daemon uninstall`, which takes the autoload away from a live session. The
    platform precondition is the structured `constraints` field of `--schema`.
    """
    dispatch_recipe(
        DAEMON_INSTALL_COMMAND,
        DaemonInstallParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="uninstall", cls=DAEMON_UNINSTALL_COMMAND.command_class())
def daemon_uninstall(
    json_output: bool = json_option(),
    schema: bool = DAEMON_UNINSTALL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Remove the gda harness autoload and files from the project (ADR-0018).

    A release-hygiene step: removal is paired and crash-safe — the harness autoload
    entry is stripped first, then the files — so a mid-failure never leaves a
    dangling autoload (which an exported game logs `ERR_CONTINUE` and skips at
    startup — error spam, not a hard crash; ADR-0028). It restores the project: the
    harness script, its engine-generated `.uid` sidecar and the emptied addon
    directory all go, and an autoload section left with no keys loses its header
    too, so `project.godot` returns to its pre-install bytes. The result enumerates
    every path and section removed. Idempotent (a no-op if not installed). Refused
    while a daemon is running (`daemon_running`); stop it first with
    `gda daemon stop`. Live is macOS/Linux only; elsewhere reports
    `live_unsupported_platform`.
    """
    # The docstring above spells section names WITHOUT their square brackets on
    # purpose: Typer renders it through Rich, which reads `[autoload]` as a markup
    # tag and silently drops it (the pre-#654 text read "the  entry is stripped
    # first"). The bracketed spelling survives in the result-model field
    # descriptions, which reach agents as JSON and are never Rich-rendered.
    dispatch_recipe(
        DAEMON_UNINSTALL_COMMAND,
        DaemonUninstallParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``daemon`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="daemon")
