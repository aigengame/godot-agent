"""One `Editor context` operation, run once for a command — the shared step (ADR-0048).

An editor-context command runs one `Headless launch` of the editor under gda's
editor payload (``godot --headless -e --language en --path <project> --script
editor.gd -- <operation> <params>``). ADR-0048 assigns ``gda project scan`` and
``gda resource import`` to it. This module is the one home of the mechanics of
that launch:

- the argv tail and the ``Godot editor`` timeout label;
- the editor environment (ADR-0048 decision 2): a private root for each call,
  made before the launch and removed after every outcome, or the caller's
  ``--user-data-root``, which is kept. The launch moves all of the editor's
  directories into that root (:func:`gda.core.engine.user_data.editor_dirs_env`);
- the classification, through the shared sentinel classifier
  (:func:`gda.core.failure.classify.classify_run`), and ADR-0002's #803
  child-stderr rule, through
  :func:`gda.core.failure.child_stderr.forward_child_stderr`.

Each command keeps its own policy around the launch: what it inventories, and
what it reports from the launch's stderr. A success therefore returns the stderr
beside the typed payload.

Placement: a core module that owns behaviour, read by the group modules of its
commands (ADR-0045).
"""

import shutil
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from gda.core.engine.launch import launch
from gda.core.engine.sentinel import sentinel_args
from gda.core.engine.user_data import resolve_user_data_root
from gda.core.failure.catalog import Failure, make_failure
from gda.core.failure.child_stderr import forward_child_stderr
from gda.core.failure.classify import classify_run

M = TypeVar("M", bound=BaseModel)

# The editor payload, the second entry beside ``operations.gd`` (ADR-0048).
# Resolved package-relative, two levels up out of ``gda/core/steps/``.
EDITOR_GD = Path(__file__).parent.parent.parent / "ops" / "editor.gd"

TIMEOUT_LABEL = "Godot editor"
"""The launch's timeout label: WHICH launch gave up, on a ``launch_timeout``."""


def run_editor_operation(
    binary: Path,
    project: Path,
    operation: str,
    params: dict,
    *,
    timeout: float,
    output_model: type[M],
) -> "tuple[M, str] | Failure":
    """Run one editor-context ``operation`` over ``project``, under the #803 rule.

    A success is the payload validated as ``output_model``, with the launch's
    stderr, which has already been forwarded to gda's stderr. A :class:`Failure`
    is what the shared sentinel classifier decides — a launch failure or crash
    (the timeout is ``launch_timeout``), a code the payload reported, a non-zero
    exit with no reported code (``operation_failed``), or no valid sentinel
    payload — and it carries the stderr on ``child_stderr``.

    A private root that cannot be created is ``user_data_unwritable``, before any
    spawn. An explicit but empty ``--user-data-root`` is the launch's own refusal:
    a private root in its place would accept a mistaken flag.

    Module-global lookup: tests patch ``gda.core.steps.editor_context.launch``.
    """
    try:
        configured = resolve_user_data_root()
    except ValueError:
        configured = None
        owned = None
    else:
        try:
            owned = (
                None
                if configured is not None
                else Path(tempfile.mkdtemp(prefix="gda-editor-"))
            )
        except OSError as error:
            return make_failure(
                "user_data_unwritable",
                "a private editor data root for this run could not be created "
                f"({error}); the launch was refused. Point TMPDIR at a writable "
                "directory, or pass --user-data-root <writable dir>",
                "",
            )
    try:
        raw = launch(
            binary,
            [
                "-e",
                "--language",
                "en",
                *sentinel_args(operation, params, project=project, script=EDITOR_GD),
            ],
            cwd=None,
            timeout=timeout,
            timeout_label=TIMEOUT_LABEL,
            user_data_root=owned,
            editor_dirs=True,
        )
    finally:
        if owned is not None:
            # Best effort (ADR-0048 decision 2): a root that will not delete does
            # not change the outcome.
            shutil.rmtree(owned, ignore_errors=True)
    outcome = forward_child_stderr(raw, classify_run(raw, binary, output_model))
    if isinstance(outcome, Failure):
        return outcome
    return outcome, raw.stderr
