"""The execution-channel taxonomy.

Every ``gda`` command is fulfilled through one of a small, fixed set of
execution channels, chosen at command-definition time and carried as a static
``kind`` on the command descriptor (ADR-0017). The runner factory selects the
channel by this ``kind``; classification, sentinel parsing, and ``--json`` /
``GdaError`` emission are shared across channels.

This is a leaf module with no ``gda`` imports (the same discipline as
``gda.exit_codes``), so the descriptor (``gda.headless``), the dispatcher
(``gda.cli``), and the export/live recipes can all name the taxonomy without an
import cycle.
"""

import enum
from typing import Optional


class ExecutionKind(str, enum.Enum):
    """Which execution channel fulfils a command (ADR-0017).

    - ``HEADLESS`` — the default: a one-shot ``godot --headless --script
      operations.gd`` sentinel op (ADR-0002, ADR-0010).
    - ``EXPORT`` — the native ``--export-<mode>`` recipe, the editor-only export
      capability that cannot run through ``operations.gd`` (ADR-0010).
    - ``LIVE`` — a live operation served by ``gda-daemon`` against a running
      engine session, reached through a daemon IPC client (ADR-0017).
    """

    HEADLESS = "headless"
    EXPORT = "export"
    LIVE = "live"


# Phase-2 live requires Godot 4.6+ (the UDS transport landed in 4.6; ADR-0021).
# The single source of truth for the live-stack Godot floor, named here in the
# leaf taxonomy module so both ``gda.daemon_ops`` (the version gate) and the
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
    can never drift, and ``gda.cli`` needs no edit.

    A command depends on the live stack when it is a LIVE-channel op **or** part
    of the ``daemon`` lifecycle group (``operation`` ``daemon-*``). The two facets:

    - ``platforms`` is uniform ``["linux", "macos"]`` across the whole set — the
      live stack rides Unix domain sockets (ADR-0021), unsupported on Windows.
    - ``min_godot_version`` is the :data:`MIN_LIVE_VERSION` floor **only where a
      command launches/uses the engine** — every LIVE op and ``daemon-start`` —
      and ``None`` for ``daemon-stop`` / ``daemon-status``, which only talk to an
      already-running daemon over UDS and never touch the engine.

    Returned as plain primitives (a ``(platforms, version)`` pair, version a
    dotted string or ``None``); this is a leaf module that must not import
    ``gda.models``, so wrapping into the :class:`~gda.models.LiveStackConstraints`
    model is left to the emission points.
    """
    is_daemon = operation.startswith("daemon-")
    if kind is not ExecutionKind.LIVE and not is_daemon:
        return None
    launches_engine = kind is ExecutionKind.LIVE or operation == "daemon-start"
    version = (
        ".".join(str(part) for part in MIN_LIVE_VERSION) if launches_engine else None
    )
    return ["linux", "macos"], version
