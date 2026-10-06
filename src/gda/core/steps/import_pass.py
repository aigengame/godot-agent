"""The engine import pass, run once for a command — the shared step (#1079).

Two commands run the editor import pass (``godot --headless --path <project>
--import``) through the `Headless launch`: ``gda resource import`` when its
`Import evidence` needs one, and ``gda project scan`` every time. This module is
the one home of the mechanics of that pass and of ADR-0002's #803 child-stderr
rule for it:

- the launch argv, the caller's timeout and the ``Godot import`` timeout label —
  the label is this channel's one contribution to the shared timeout envelope,
  WHICH launch gave up when three channels report the same code (#714);
- the launch and crash classification
  (:func:`gda.core.failure.classify.classify_launch_or_crash`) and the non-zero-exit
  ``operation_failed`` refusal;
- the child stderr, through :func:`gda.core.failure.child_stderr.forward_child_stderr`,
  the one producer-side copy of the rule: a failure carries the pass's stderr on
  ``child_stderr`` for ``emit_failure`` to forward, and a success forwards it now.

Each command keeps its own policy around the pass: what it inventories
(``project scan`` detects rewrites, ``resource import`` does not), when it runs
the pass, and what it reports after it (``engine_errors``, the per-asset
``engine_output``) — data beside the forwarded stream, never a replacement for
it. The step takes no inventory option, no result model and no per-command
message: a reused helper brings its carve-outs with it, so this one has none.

Placement: a core module that owns behaviour, read by the ``resource`` and
``project`` group modules and nothing else — the `gda.core.project.project_tree` precedent
(ADR-0040's #985 note), which the same two commands read for the inventory they
take around this pass.
"""

from pathlib import Path

from gda.core.failure.catalog import Failure, make_failure
from gda.core.failure.child_stderr import forward_child_stderr
from gda.core.failure.classify import classify_launch_or_crash
from gda.core.engine.launch import RunResult, launch

TIMEOUT_LABEL = "Godot import"
"""The pass's timeout label: WHICH launch gave up, on a ``launch_timeout``."""


def run_import_pass(
    binary: Path, project: Path, *, timeout: float
) -> "RunResult | Failure":
    """Run the engine import pass over ``project`` once, under the #803 rule.

    A :class:`RunResult` is a pass that exited 0, its stderr already forwarded to
    gda's stderr (a success has no diagnostics to duplicate); the caller settles
    its own inventory and reads what it reports out of ``stderr``. A
    :class:`Failure` is the classified launch failure or crash — binary not
    found, the timeout, the refused `User-data placement`, a signal death — or
    the non-zero exit as ``operation_failed`` with the stderr as diagnostics;
    every one carries the stderr on ``child_stderr`` and prints nothing.

    Module-global lookup (the one launch seam for both commands): tests patch
    ``gda.core.steps.import_pass.launch``.
    """
    raw = launch(
        binary,
        ["--path", str(project), "--import"],
        cwd=None,
        timeout=timeout,
        timeout_label=TIMEOUT_LABEL,
    )
    failed = classify_launch_or_crash(raw, binary)
    if failed is None and raw.exit_code != 0:
        failed = make_failure(
            "operation_failed",
            f"the engine import pass exited {raw.exit_code}",
            raw.stderr,
        )
    return forward_child_stderr(raw, raw if failed is None else failed)
