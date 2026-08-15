"""Direct tests for the ScriptRun operation (issue #343, ADR-0031).

``script run`` is the third execution shape: a user-script passthrough run whose
recipe — validate the res:// path + require a resolved project, then launch
``godot --headless --path <project> --script <res://…>`` and BIFURCATE by whose
failure it is — lives in :func:`gda.commands.script.run_script_run_operation`, a PURE
function that RETURNS the outcome (never emits/exits).

These tests drive that function directly with the injected launch seam (a
``FakeLaunch`` returning a canned :class:`~gda.runner.RunResult`), so the whole
bifurcation is asserted without a real engine and without CliRunner:

- a clean engine exit (``exit_code >= 0``) — INCLUDING a non-zero ``quit(1)`` —
  is a SUCCESS ``ScriptRunResult`` with the script's output passed through;
- a launch failure / signal death is a gda-level Error envelope, classified by
  the SAME shared ``classify_launch_or_crash`` the export channel uses;
- the two pre-run ABI edges (non-res:// path, no resolved project) are structured
  failures decided BEFORE any launch.

They are the recipe's own test surface, complementary to the e2e round-trip in
``tests/test_e2e_script_run.py`` (real Godot).
"""

from pathlib import Path

from gda.commands.script import (  # the single fully-bound descriptor (ADR-0023)
    SCRIPT_RUN_COMMAND,
    ScriptRunResult,
    run_script_run_operation,
)
from gda.errors import Failure
from gda.execution import ExecutionKind
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.runner import LaunchFailure, RunResult

PROJECT = Path("/tmp/project")


class FakeLaunch:
    """A fakeable :func:`gda.runner.launch` that records its call and returns a canned run.

    Satisfies the ``LaunchFn`` seam so the operation's launch/crash bifurcation is
    exercised without a real engine — the ``script run`` twin of ``FakeRunner`` /
    ``FakeExportRunner``. Records the ``(binary, args, cwd, timeout, timeout_label)``
    it was called with so argv-tail construction (and ``cwd=None``) can be asserted.
    """

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = "Godot",
    ) -> RunResult:
        self.calls.append((binary, args, cwd, timeout, timeout_label))
        return self.result


def _run(
    result: RunResult,
    *,
    script: str = "res://tests/logic.gd",
    project: Path | None = PROJECT,
    godot: str | None = "/tmp/Godot",
) -> tuple[ScriptRunResult | Failure, FakeLaunch]:
    """Invoke the operation with the launch seam pinned to a ``FakeLaunch``."""
    launch = FakeLaunch(result)
    outcome = run_script_run_operation(
        script=script,
        godot=godot,
        project=project,
        make_launch=launch,
    )
    return outcome, launch


def test_script_run_command_is_the_passthrough_channel():
    # `script run` is the fourth execution shape — a user-script passthrough that
    # emits no ADR-0002 sentinel — so it carries the SCRIPT_RUN kind and routes by
    # its recipe (ADR-0031 / ADR-0023), never `cmd.emit`.
    assert SCRIPT_RUN_COMMAND.kind is ExecutionKind.SCRIPT_RUN
    assert SCRIPT_RUN_COMMAND.recipe is not None


def test_clean_zero_exit_passes_the_run_through():
    # The happy path: the engine exits 0, so the operation RETURNS the typed
    # ScriptRunResult carrying the script's own stdout/stderr verbatim.
    outcome, launch = _run(RunResult(stdout="hello\n", stderr="warn\n", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0
    assert outcome.stdout == "hello\n"
    assert outcome.stderr == "warn\n"
    # The argv tail is `--path <project> --script <res path>`, launched with cwd=None
    # (mirroring the sentinel runner, NOT the export channel's cwd=project).
    (binary, args, cwd, _timeout, label) = launch.calls[0]
    assert args == ["--path", str(PROJECT), "--script", "res://tests/logic.gd"]
    assert cwd is None
    assert label == "Godot script"


def test_non_zero_script_exit_is_a_success_not_a_failure():
    # THE CRUX (ADR-0031): a deliberate quit(1) is a clean engine exit, so it is a
    # SUCCESS result carrying exit_status=1 — gda does not interpret the script's
    # semantics. This is the one command whose success result can be non-zero.
    outcome, _ = _run(RunResult(stdout="assert failed\n", stderr="", exit_code=1))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 1
    assert outcome.stdout == "assert failed\n"


def test_binary_not_found_is_the_shared_classifier_failure():
    # A synthesized NOT_FOUND launch failure → binary_not_found, via the SAME
    # classify_launch_or_crash the export channel uses (no GDScript-mirrored code).
    outcome, _ = _run(
        RunResult(
            stdout="",
            stderr="gda: Godot binary could not be launched\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "binary_not_found"
    assert outcome.exit_code == EXIT_NOT_FOUND


def test_launch_timeout_is_the_shared_classifier_failure():
    # A synthesized TIMEOUT launch failure → launch_timeout.
    outcome, _ = _run(
        RunResult(
            stdout="",
            stderr="gda: Godot script timed out after 120.0s\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert outcome.exit_code == EXIT_TIMEOUT


def test_signal_death_is_engine_crashed():
    # A negative exit_code is a signal death (e.g. SIGSEGV) → engine_crashed, an
    # operation-category gda failure — never a raw negative exit leaking out.
    outcome, _ = _run(RunResult(stdout="", stderr="", exit_code=-11))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "engine_crashed"
    assert outcome.exit_code == EXIT_OPERATION
    assert "11" in outcome.error.message


def test_non_res_path_is_invalid_path_before_any_launch():
    # A non-res:// path is a structured invalid_path decided BEFORE any launch
    # (an explicit ABI edge, ADR-0031) — never a crash.
    outcome, launch = _run(
        RunResult(stdout="", stderr="", exit_code=0), script="tests/logic.gd"
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "invalid_path"
    assert not launch.calls, "no engine launch on an invalid path"


def test_absolute_path_is_invalid_path():
    # An absolute filesystem path is likewise res://-only-rejected.
    outcome, launch = _run(
        RunResult(stdout="", stderr="", exit_code=0), script="/abs/logic.gd"
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "invalid_path"
    assert not launch.calls


def test_no_resolved_project_is_project_not_found_before_any_launch():
    # No resolved project → structured project_not_found, before any launch
    # (the other ABI edge, ADR-0031).
    outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), project=None)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "project_not_found"
    assert not launch.calls


def test_empty_godot_is_a_structured_binary_failure_not_a_traceback():
    # An empty `--godot ""` makes binary resolution raise before any launch; it is
    # mapped to the structured binary_not_found envelope, never a raw traceback.
    outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), godot="")

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "binary_not_found"
    assert not launch.calls


def test_result_is_the_thin_promotion_dropping_launch_failure():
    # The success DTO is the thin boundary promotion of the internal Raw run: it
    # drops `launch_failure` and renames exit_code→exit_status, carrying nothing
    # else. (A clean exit never has a launch_failure set anyway.)
    outcome, _ = _run(RunResult(stdout="out", stderr="err", exit_code=7))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.model_dump() == {
        "exit_status": 7,
        "stdout": "out",
        "stderr": "err",
    }
