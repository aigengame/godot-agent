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
