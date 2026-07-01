"""The ScriptRun operation — ``gda script run``'s user-script passthrough run (ADR-0031).

``gda script run res://path.gd`` runs the user's own script as a one-shot
``godot --headless --path <project> --script <res://…>`` process and returns a
structured result. It is the **third execution shape** (ADR-0031): neither the
ADR-0002 sentinel op-dispatch (the entry script is the user's own, so it cannot
emit the sentinel) nor the native-export recipe (gda does not know the script's
semantics, so it has no gda-defined typed result to synthesize). The outcome
therefore **bifurcates by whose failure it is**:

- **gda-/engine-level failure** — the binary could not be launched, the run timed
  out, or the engine died on a signal (``exit_code < 0``) → an **Error envelope**,
  classified by the SAME shared :func:`gda.errors.classify_launch_or_crash` the
  export channel uses, into its existing codes (``binary_not_found`` /
  ``launch_timeout`` / ``engine_crashed``). No new GDScript-mirrored codes.
- **the script ran to completion** — the engine exited normally
  (``exit_code >= 0``) → a **success** :class:`~gda.models.ScriptRunResult`
  carrying ``{exit_status, stdout, stderr}`` **passed through verbatim, even when
  ``exit_status != 0``**. gda does not interpret the script's semantics: a
  deliberate ``quit(1)`` (e.g. an assertion-failed logic-seam test) is meaningful
  DATA the agent reads, not a gda failure.

Two explicit pre-run ABI edges (ADR-0031), both decided at the CLI before any
launch and returned as a structured ``GdaError`` (never a crash): a non-``res://``
or absolute script path → ``invalid_path``; no resolved project →
``project_not_found``.

Like ``export run`` (:mod:`gda.export_run`), this module is the recipe's home:
:func:`run_script_run_operation` RETURNS its outcome
(``ScriptRunResult | Failure``) instead of emitting or exiting, so the CLI command
stays the thin shared shape and the recipe gets its own engine-free test surface.
The engine-touching step delegates to the deep-module headless-launch primitive
:func:`gda.runner.launch` — the SINGLE home of the spawn / timeout /
launch-failure / UTF-8-decode normalization — reused, not re-implemented. It is
injected (``make_launch``) only so the bifurcation is testable without a real
engine.
"""

from pathlib import Path
from typing import Optional, Protocol

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_launch_or_crash,
    script_path_invalid_failure,
    script_run_project_not_found_failure,
    unresolvable_binary_failure,
)
from gda.models import ScriptRunResult
from gda.runner import RunResult, launch

# A user script is arbitrary project code (it may load resources), so give it a
# ceiling more generous than a single sentinel op's tight bound but well below the
# export channel's — enough for a logic-seam test without leaving a hung run to
# block forever. Bounds a hung engine so the CLI fails loudly (as launch_timeout).
DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS = 120.0

# The res:// scheme prefix: script run is res://-only (ADR-0031). A res:// path
# resolves against the --project context, unlike an absolute/filesystem path.
_RES_PREFIX = "res://"


class LaunchFn(Protocol):
    """The headless-launch seam — the shape of :func:`gda.runner.launch` (#343).

    Injected into :func:`run_script_run_operation` so the launch/crash bifurcation
    is exercised with a canned :class:`~gda.runner.RunResult`, without spawning a
    real engine — the ``script run`` twin of the sentinel channel's ``RunnerFactory``
    and the export channel's ``ExportRunnerFactory``. The default is the real
    ``launch`` (the deep module is reused, never re-implemented).
    """

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = ...,
    ) -> RunResult: ...


def run_script_run_operation(
    *,
    script: str,
    godot: Optional[str],
    project: Optional[Path],
    make_launch: Optional[LaunchFn] = None,
    timeout: float = DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
) -> ScriptRunResult | Failure:
    """Run ``script run``'s validate → launch → classify recipe (ADR-0031).

    Returns its outcome instead of emitting or exiting: the passthrough
    :class:`~gda.models.ScriptRunResult` on a clean engine exit (even a non-zero
    ``exit_status``) or a :class:`~gda.errors.Failure` — a pre-run ABI-edge
    failure (``invalid_path`` / ``project_not_found``) or a
    ``classify_launch_or_crash`` env/crash outcome. ``project`` is the
    already-resolved directory (resolution stays CLI-side, ADR-0006); ``None``
    means none resolved. ``make_launch`` is the injected headless-launch seam;
    ``None`` (the default) uses the real deep-module :func:`gda.runner.launch`,
    resolved at call time — the ``screen_ops`` idiom — so a test can inject a fake
    OR patch ``gda.script_run.launch``.
    """
    run_launch = make_launch or launch
    # Pre-run ABI edges (ADR-0031), decided BEFORE any launch so they never surface
    # as a crash or a raw engine failure. Path first (it is the direct argument):
    # res://-only — an absolute or non-res:// path cannot resolve against --path.
    if not script.startswith(_RES_PREFIX):
        return script_path_invalid_failure(script)
    # Then require a resolved project — a res:// path needs one to resolve.
    if project is None:
        return script_run_project_not_found_failure()

    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        # An empty ``--godot ""`` (a natural $GDA_GODOT mistake) makes resolution
        # raise before a launch — the same environment failure as a missing binary,
        # mapped to the structured envelope so it never escapes as a raw traceback
        # (mirrors gda.headless.execute's binary resolution, #33).
        return unresolvable_binary_failure(str(exc))

    # Build only this channel's argv tail — the user script under the resolved
    # project — and delegate the spawn / timeout / OSError / UTF-8-decode handling
    # to the shared launch primitive (the deep module, reused not re-implemented).
    # cwd=None mirrors the sentinel SubprocessGodotRunner: a res:// script resolves
    # via --path, so no working directory is needed (unlike the export channel,
    # whose relative output path needs cwd=project).
    args = ["--path", str(project), "--script", script]
    raw = run_launch(
        binary, args, cwd=None, timeout=timeout, timeout_label="Godot script"
    )

    # Bifurcate by whose failure it is (ADR-0031): a launch failure or a signal
    # death (exit_code < 0) is a gda-/engine-level Error envelope, classified by the
    # SAME shared prefix the export channel uses. Everything else — a clean engine
    # exit, INCLUDING a non-zero exit_status — is a success passthrough.
    crash = classify_launch_or_crash(raw, binary)
    if crash is not None:
        return crash
    # The public promotion of the internal Raw run: the thin boundary DTO built by
    # dropping launch_failure (lifted into the Error envelope above) and renaming
    # exit_code → exit_status. This is the one success result that can be non-zero.
    return ScriptRunResult(
        exit_status=raw.exit_code,
        stdout=raw.stdout,
        stderr=raw.stderr,
    )
