"""The execution-channel taxonomy.

Every ``gda`` command is fulfilled through one of a small, fixed set of
execution channels, chosen at command-definition time and carried as a static
``kind`` on the command descriptor (ADR-0017). The runner factory selects the
channel by this ``kind``; classification, sentinel parsing, and ``--json`` /
``GdaError`` emission are shared across channels.

This is a leaf module with no ``gda`` imports (the same discipline as
``gda.exit_codes``), so the descriptor (``gda.surface.descriptor``), the dispatcher
(``gda.surface.dispatch``), and the export/live recipes can all name the taxonomy
without an import cycle.
"""

import enum
import os
import sys
from typing import Optional


class ExecutionKind(str, enum.Enum):
    """Which execution channel fulfils a command (ADR-0017).

    - ``headless`` — the default: a one-shot ``godot --headless --script
      operations.gd`` sentinel op (ADR-0002, ADR-0010).
    - ``export`` — the native ``--export-<mode>`` recipe, the editor-only export
      capability that cannot run through ``operations.gd`` (ADR-0010).
    - ``live`` — a live operation served by ``gda-daemon`` against a running
      engine session, reached through a daemon IPC client (ADR-0017).
    - ``script_run`` — a user-script passthrough run: a one-shot ``godot
      --headless --path <project> --script <res://…>`` whose success result is the
      user script's own ``{exit_status, stdout, stderr}`` passed through verbatim,
      only launch/crash being classified (ADR-0031). Like ``export`` it routes by
      its ``recipe`` (ADR-0023), so this value is self-description only — it adds
      no runner-selection branch.
    - ``import`` — the engine's native project-wide ``--import`` pass, run
      through the shared launch primitive when a requested asset's cache is
      missing (#668). Like ``script_run`` it routes by its ``recipe``
      (ADR-0023): self-description only, no runner-selection branch — but the
      published ``kind`` must not claim the ``operations.gd`` sentinel pipeline
      it never uses.
    - ``artifact_smoke`` — a bounded headless run of a caller-selected `Export
      artifact`: the one channel whose executable is NOT the configured Godot but
      the one resolved inside the artifact, run through the same shared launch
      primitive, with its completed process passed through as the result
      (ADR-0042). Like ``script_run`` and ``import`` it routes by its ``recipe``,
      so this value too is self-description only — it exists because a caller
      reading ``--schema`` must be able to tell this execution shape from the
      sentinel pipeline and from ``script run``'s project-scoped one.
    """

    HEADLESS = "headless"
    EXPORT = "export"
    LIVE = "live"
    SCRIPT_RUN = "script_run"
    IMPORT = "import"
    ARTIFACT_SMOKE = "artifact_smoke"


# Phase-2 live requires Godot 4.6+ (ADR-0021, ADR-0047).
# The single source of truth for the live-stack Godot floor, named here in the
# leaf taxonomy module so both ``gda.commands.daemon`` (the version gate) and the
# ``live_stack_constraints`` predicate below read the same tuple. Surfaced in
# ``--schema`` as the dotted ``"4.6"`` string (issue #233).
MIN_LIVE_VERSION = (4, 6)


def live_stack_constraints(
    kind: ExecutionKind, operation: str
) -> Optional[tuple[list[str], Optional[str]]]:
    """The live-stack constraint for a command, or ``None`` if it has none.

    The single authority that marks a command as depending on gda's daemon/live
    stack (issue #233), keyed on the two static descriptor facts both ``--schema``
    emission paths already share — the command's :class:`ExecutionKind` and its
    operation name — so the per-command ``--schema`` and the aggregate manifest
    can never drift, and no command module needs an edit.

    A command depends on the live stack when it is a LIVE-channel op **or** part
    of the ``daemon`` lifecycle group (``operation`` ``daemon-*``). The two facets:

    - ``platforms`` includes Windows for verified lifecycle, headless Live and
      screen routes (#1116–#1122, ADR-0047). Unknown Live routes remain Unix-only.
    - ``min_godot_version`` is the :data:`MIN_LIVE_VERSION` floor **only where a
      command launches/uses the engine** — every LIVE op and ``daemon-start`` —
      and ``None`` for ``daemon-stop`` / ``daemon-status``, which only talk to an
      already-running daemon and never launch the engine.

    Returned as plain primitives (a ``(platforms, version)`` pair, version a dotted
    string or ``None``); this is a leaf module that must not import
    ``gda.core.contract.envelope``, so wrapping into the
    :class:`~gda.core.contract.envelope.LiveStackConstraints` model is left to the
    emission points.
    """
    is_daemon = operation.startswith("daemon-")
    if kind is not ExecutionKind.LIVE and not is_daemon:
        return None
    launches_engine = kind is ExecutionKind.LIVE or operation == "daemon-start"
    version = (
        ".".join(str(part) for part in MIN_LIVE_VERSION) if launches_engine else None
    )
    platforms = ["linux", "macos"]
    if (
        kind is ExecutionKind.LIVE
        and operation
        in {
            "daemon-wait-ready",
            "game-tree",
            "game-find",
            "game-get",
            "game-rect",
            "game-set",
            "game-call",
            "input-key",
            "input-mouse-click",
            "input-mouse-move",
            "input-action",
            "input-tap",
            "input-sequence",
            "perf-monitors",
            "perf-sample",
            "perf-monitor",
            "diag-errors",
            "logger-tail",
            "screen-capture",
            "screen-frames",
        }
    ) or (
        kind is not ExecutionKind.LIVE
        and operation
        in {
            "daemon-install",
            "daemon-uninstall",
            "daemon-start",
            "daemon-status",
            "daemon-stop",
        }
    ):
        platforms.append("windows")
    return platforms, version


def reads_unscanned_class_index(kind: ExecutionKind, operation: str) -> bool:
    """Whether a command's engine reads the class index WITHOUT running the import pass.

    The channel scope of the class-resolution remedy (#1073,
    ``gda.core.failure.classify.class_resolution_remedy``), keyed on the same two static
    descriptor facts as :func:`live_stack_constraints`. Two channels are in: the
    sentinel ops (``HEADLESS``, less the ``daemon`` lifecycle, which serves the live
    stack) and ``script run`` (``SCRIPT_RUN``). Each starts an engine that reads the
    index once, at startup, so a project class the index misses is a cause that ``gda
    project scan`` removes before the same call.

    Every other channel is out. ``IMPORT`` (``project scan``, ``resource import``)
    and ``EXPORT`` run the import pass themselves, so after it the index is fresh
    and a class-resolution error is a real source error — a scan remedy would be
    wrong advice. ``LIVE`` reads the index when its Engine session launches
    (ADR-0017), and ``ARTIFACT_SMOKE`` runs a caller's exported game, not the
    project.
    """
    if kind is ExecutionKind.SCRIPT_RUN:
        return True
    return (
        kind is ExecutionKind.HEADLESS
        and live_stack_constraints(kind, operation) is None
    )


def _is_unix() -> bool:
    return os.name == "posix"


def live_stack_supported(kind: ExecutionKind, operation: str) -> bool:
    """Whether this platform can serve the command's route.

    Unix serves every route. Windows serves a route only when
    :func:`live_stack_constraints` lists ``windows`` for it, which is the
    allow-list of verified Windows routes (ADR-0047). The lifecycle gate, the
    Live client and the daemon's request gate all ask this function.
    """
    if _is_unix():
        return True
    constraints = live_stack_constraints(kind, operation)
    return (
        sys.platform == "win32"
        and constraints is not None
        and "windows" in constraints[0]
    )
