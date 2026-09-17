"""Direct tests for the ArtifactSmoke operation (ADR-0042, #979).

``export smoke`` runs a caller-selected `Export artifact` — resolve it to a Godot
executable, launch that executable once headless under a private ``user://``,
then pass the completed process through or apply the opted-in ``--strict`` gate.
The recipe lives in :func:`gda.commands.export.run_export_smoke_operation`, a PURE
function that RETURNS its outcome (never emits or exits).

These tests drive it directly with the injected launch seam, so every branch is
asserted without a real engine and without CliRunner: the artifact-resolution rule
and its two refusals, the argv tail (``--quit-after`` before Godot's ``--``), the
private-root lifecycle on all five outcomes, the two ``--strict`` triggers, and
the passthrough itself. The real round trip — a genuine ``export run`` artifact
launched by the real engine — is ``tests/export/test_e2e_export_smoke.py``.
"""

import plistlib
import shutil
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from gda.commands.export import (  # the single fully-bound descriptor (ADR-0023)
    DEFAULT_SMOKE_TIMEOUT_SECONDS,
    EXPORT_SMOKE_COMMAND,
    SMOKE_TIMEOUT_LABEL,
    ExportSmokeParams,
    ExportSmokeResult,
    resolve_artifact_executable,
    run_export_smoke_operation,
    smoke_args,
)
from gda.completed_run import STDOUT_CAP
from gda.errors import (
    SMOKE_OUTPUT_STDERR_HEADER,
    SMOKE_OUTPUT_STDOUT_HEADER,
    Failure,
)
from gda.execution import ExecutionKind
from gda.exit_codes import EXIT_OPERATION, EXIT_TIMEOUT
from gda.models import GdaErrorEnvelope
from gda.runner import LaunchFailure, LaunchWatch, RunResult, TimeoutBound
from gda.runner import set_user_data_root

# The engine's exit-time leak sentence, as `gda.script_errors` recognizes it — the
# second `--strict` trigger and the defect the whole command exists for
# (GDA-DF-072: a clean `export run`, a build that leaked at exit).
LEAK_STDERR = (
    "WARNING: ObjectDB instances leaked at exit (run with --verbose for details).\n"
    "   at: cleanup (core/object/object.cpp:2663)\n"
)


@pytest.fixture(autouse=True)
def _no_root_override(monkeypatch):
    """Keep the process-wide root override and its env twin off by default."""
    monkeypatch.delenv("GDA_USER_DATA_ROOT", raising=False)
    set_user_data_root(None)
    yield
    set_user_data_root(None)


class FakeLaunch:
    """A fakeable :func:`gda.runner.launch` that records its call and returns a run.

    Satisfies the ``LaunchFn`` seam, so the operation's resolve/launch/classify
    path runs without an engine — the smoke's twin of ``script run``'s own
    ``FakeLaunch``. It records ADR-0042's ``user_data_root`` as well, because on
    THIS channel the root is the thing under test: the private one the command
    creates, or ``None`` when the caller already named one.

    ``raises`` makes the launch itself blow up, which is how the "unexpected
    exception" cleanup path is reached without inventing a failure mode.
    """

    def __init__(self, result: RunResult, *, raises: BaseException | None = None):
        self.result = result
        self.raises = raises
        self.calls: list[tuple] = []
        self.roots: list[Path | None] = []
        self.root_existed: list[bool] = []

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = "Godot",
        watch: LaunchWatch | None = None,
        user_data_root: Path | None = None,
    ) -> RunResult:
        self.calls.append((binary, args, cwd, timeout, timeout_label, watch))
        self.roots.append(user_data_root)
        # The root must exist BEFORE the spawn (ADR-0042: created after the artifact
        # resolves and before the launch), which only this vantage point can see.
        self.root_existed.append(user_data_root is not None and user_data_root.is_dir())
        if self.raises is not None:
            raise self.raises
        return self.result


def completed(stdout: str = "", stderr: str = "", exit_code: int = 0) -> RunResult:
    """A clean engine exit — the shape every passthrough branch starts from."""
    return RunResult(stdout=stdout, stderr=stderr, exit_code=exit_code)


def runnable_file(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    """A regular file this host may execute — the simplest accepted artifact."""
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def app_bundle(
    root: Path,
    *,
    executable_name: str | None = "Game",
    write_executable: bool = True,
    executable_runnable: bool = True,
    plist: bool = True,
) -> Path:
    """A macOS ``.app`` bundle, with each resolution requirement switchable off."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    if plist:
        declared = {"CFBundleName": root.stem}
        if executable_name is not None:
            declared["CFBundleExecutable"] = executable_name
        with (root / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump(declared, handle)
    if write_executable and executable_name is not None:
        target = root / "Contents" / "MacOS" / executable_name
        if executable_runnable:
            runnable_file(target)
        else:
            target.write_text("not executable", encoding="utf-8")
    return root


# --- The descriptor ----------------------------------------------------------


def test_export_smoke_is_the_artifact_smoke_channel_and_takes_no_project():
    # The published kind must not claim the operations.gd sentinel pipeline this
    # command never uses, nor `script run`'s project-scoped shape (ADR-0042); and
    # `inherits_project=False` is what keeps an inherited $GDA_PROJECT out of a
    # command whose operand is a path outside any project.
    assert EXPORT_SMOKE_COMMAND.kind is ExecutionKind.ARTIFACT_SMOKE
    assert EXPORT_SMOKE_COMMAND.inherits_project is False
    assert EXPORT_SMOKE_COMMAND.recipe is not None


# --- Artifact resolution (ADR-0042's two refusals) ---------------------------


def test_an_absent_artifact_is_not_found(tmp_path):
    outcome = resolve_artifact_executable(str(tmp_path / "never-built"))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_found"
    assert outcome.exit_code == EXIT_OPERATION
    assert "never-built" in outcome.error.message


def test_a_runnable_file_is_accepted_as_given(tmp_path):
    artifact = runnable_file(tmp_path / "game")

    assert resolve_artifact_executable(str(artifact)) == artifact


def test_a_file_without_execute_permission_is_not_runnable(tmp_path):
    artifact = tmp_path / "game"
    artifact.write_text("payload", encoding="utf-8")
    artifact.chmod(0o644)

    outcome = resolve_artifact_executable(str(artifact))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert "execute" in outcome.error.message


def test_a_symlink_to_a_runnable_file_is_runnable(tmp_path):
    # `os.stat` follows links, the same symlink-agnostic reading the rest of gda's
    # path handling uses: what matters is what the path names, not how.
    target = runnable_file(tmp_path / "game")
    link = tmp_path / "latest"
    link.symlink_to(target)

    assert resolve_artifact_executable(str(link)) == link


def test_a_broken_symlink_is_not_found(tmp_path):
    link = tmp_path / "latest"
    link.symlink_to(tmp_path / "gone")

    outcome = resolve_artifact_executable(str(link))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_found"


def test_a_plain_directory_is_not_runnable(tmp_path):
    (tmp_path / "build").mkdir()

    outcome = resolve_artifact_executable(str(tmp_path / "build"))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert ".app" in outcome.error.message


def test_a_bundle_resolves_to_the_executable_its_plist_names(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app", executable_name="Game")

    assert resolve_artifact_executable(str(bundle)) == (
        bundle / "Contents" / "MacOS" / "Game"
    )


def test_a_bundle_whose_plist_names_another_file_resolves_to_that_one(tmp_path):
    # The key is read, not guessed from the bundle name: Godot's own macOS export
    # names the executable after the project, which need not match the .app stem.
    bundle = app_bundle(tmp_path / "Shipped.app", executable_name="MyGame")

    assert resolve_artifact_executable(str(bundle)) == (
        bundle / "Contents" / "MacOS" / "MyGame"
    )


def test_a_bundle_without_a_plist_is_not_runnable(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app", plist=False)

    outcome = resolve_artifact_executable(str(bundle))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert "Info.plist" in outcome.error.message


def test_a_bundle_with_an_unreadable_plist_is_not_runnable(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app")
    (bundle / "Contents" / "Info.plist").write_text("not a plist", encoding="utf-8")

    outcome = resolve_artifact_executable(str(bundle))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert "Info.plist" in outcome.error.message


def test_a_bundle_whose_plist_declares_no_executable_is_not_runnable(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app", executable_name=None)

    outcome = resolve_artifact_executable(str(bundle))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert "CFBundleExecutable" in outcome.error.message


def test_a_bundle_missing_the_file_its_plist_names_is_not_runnable(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app", write_executable=False)

    outcome = resolve_artifact_executable(str(bundle))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"
    assert "CFBundleExecutable" in outcome.error.message


def test_a_bundle_whose_named_file_is_not_executable_is_not_runnable(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app", executable_runnable=False)

    outcome = resolve_artifact_executable(str(bundle))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "export_artifact_not_runnable"


def test_a_relative_artifact_resolves_against_the_invocation_cwd(tmp_path, monkeypatch):
    # The command is projectless, so a relative path has exactly one meaning: where
    # the CALLER stands (ADR-0042). The absolute `output_path` from `export run`
    # therefore passes through untouched, and `build/Game` means the same thing a
    # shell would mean by it.
    (tmp_path / "build").mkdir()
    artifact = runnable_file(tmp_path / "build" / "game")
    monkeypatch.chdir(tmp_path)

    assert resolve_artifact_executable("build/game") == Path("build/game")

    launch = FakeLaunch(completed())
    outcome = run_export_smoke_operation(
        artifact="build/game", args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.artifact == str(artifact)


def test_a_tilde_artifact_expands_at_the_params_model(monkeypatch, tmp_path):
    # `NormalizedPath`, the one path-field mechanism (ADR-0015), so argv and
    # --params-json expand identically and `~` is never read as a directory name.
    monkeypatch.setenv("HOME", str(tmp_path))

    assert ExportSmokeParams(artifact="~/build/game").artifact == str(
        tmp_path / "build" / "game"
    )


# --- The argv tail -----------------------------------------------------------


def test_an_omitted_quit_after_adds_no_engine_flag():
    assert smoke_args([], 0) == ["--"]


def test_a_positive_quit_after_is_placed_before_godots_separator():
    # Measured, not assumed (ADR-0042's follow-up probe): the same words AFTER `--`
    # became user arguments and the game did not exit.
    assert smoke_args(["alpha"], 30) == ["--quit-after", "30", "--", "alpha"]


def test_caller_arguments_keep_their_order_after_the_separator():
    assert smoke_args(["one", "two", "three"], 0) == ["--", "one", "two", "three"]


def test_a_user_argument_that_looks_like_an_engine_flag_stays_after_the_separator():
    assert smoke_args(["--quit-after", "9"], 0) == ["--", "--quit-after", "9"]


def test_the_launch_gets_the_resolved_executable_and_this_channels_label(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app")
    launch = FakeLaunch(completed())

    run_export_smoke_operation(
        artifact=str(bundle), args=["alpha"], quit_after=5, make_launch=launch
    )

    (binary, args, cwd, timeout, label, watch) = launch.calls[0]
    assert binary == bundle / "Contents" / "MacOS" / "Game"
    assert args == ["--quit-after", "5", "--", "alpha"]
    # No working directory (the artifact is addressed absolutely) and no watch: the
    # `Completion marker` is `script run`'s policy and this channel has none.
    assert cwd is None
    assert watch is None
    assert timeout == DEFAULT_SMOKE_TIMEOUT_SECONDS
    assert label == SMOKE_TIMEOUT_LABEL


def test_the_callers_timeout_reaches_the_launch(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed())

    run_export_smoke_operation(
        artifact=str(artifact), args=[], timeout=7.5, make_launch=launch
    )

    assert launch.calls[0][3] == 7.5


# --- The private user:// root (ADR-0042) -------------------------------------


def test_a_private_root_is_created_before_the_launch_and_removed_after(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed())

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    root = launch.roots[0]
    assert root is not None
    assert launch.root_existed == [True]
    assert not root.exists()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(completed(exit_code=3), id="completed"),
        pytest.param(
            RunResult(
                stdout="",
                stderr="",
                exit_code=EXIT_TIMEOUT,
                launch_failure=LaunchFailure.TIMEOUT,
                timeout_bound=TimeoutBound(SMOKE_TIMEOUT_LABEL, 1.0),
            ),
            id="timeout",
        ),
        pytest.param(
            RunResult(
                stdout="",
                stderr="",
                exit_code=127,
                launch_failure=LaunchFailure.NOT_FOUND,
            ),
            id="launch-failure",
        ),
        pytest.param(completed(stderr=LEAK_STDERR), id="strict-failure"),
    ],
)
def test_the_private_root_is_removed_on_every_outcome_that_created_it(tmp_path, raw):
    # ADR-0042 lists the paths by name — completed, timeout, launch failure, strict
    # failure and unexpected exception — because the cleanup is in `finally` exactly
    # so that none of them can leak a directory. The fifth is its own test below.
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(raw)

    run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    root = launch.roots[0]
    assert root is not None and not root.exists()


def test_the_private_root_is_removed_when_the_launch_raises(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(), raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        run_export_smoke_operation(artifact=str(artifact), args=[], make_launch=launch)

    root = launch.roots[0]
    assert root is not None and not root.exists()


def test_a_cleanup_failure_does_not_replace_the_outcome(tmp_path, monkeypatch):
    # Cleanup is best-effort internal hygiene (ADR-0042): a root that will not delete
    # must not turn a good run into a failure, and must add no result field, code or
    # evidence. The double refuses unless the call is the ignoring one, so dropping
    # `ignore_errors=True` — the only thing holding this promise — turns this red.
    artifact = runnable_file(tmp_path / "game")
    real = shutil.rmtree

    def only_if_ignoring(path, *args, **kwargs):
        if not kwargs.get("ignore_errors"):
            raise OSError("Device or resource busy")
        return None  # left behind, as a real failed deletion would

    monkeypatch.setattr(shutil, "rmtree", only_if_ignoring)
    launch = FakeLaunch(completed(stdout="ok\n"))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.stdout == "ok\n"
    root = launch.roots[0]
    assert root is not None and root.exists()
    real(root, ignore_errors=True)


def test_an_explicit_root_is_used_by_the_launch_and_is_not_removed(tmp_path):
    # An override is CALLER-owned: the command hands the launch nothing, so the
    # primitive's own process-wide resolution places the run, and nothing is
    # removed afterwards.
    artifact = runnable_file(tmp_path / "game")
    mine = tmp_path / "mine"
    mine.mkdir()
    set_user_data_root(str(mine))
    launch = FakeLaunch(completed())

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert launch.roots == [None]
    assert mine.is_dir()


def test_the_environment_twin_is_honoured_like_the_flag(tmp_path, monkeypatch):
    artifact = runnable_file(tmp_path / "game")
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "from-the-env"))
    launch = FakeLaunch(completed())

    run_export_smoke_operation(artifact=str(artifact), args=[], make_launch=launch)

    assert launch.roots == [None]


def test_an_explicit_but_empty_root_is_left_to_the_launchs_own_refusal(tmp_path):
    # The caller named a root, badly. Supplying a private one instead would silently
    # accept a mistaken flag, so the launch gets nothing and its shared
    # `user_data_unwritable` refusal stands — the same answer every other channel
    # gives for the same input.
    artifact = runnable_file(tmp_path / "game")
    set_user_data_root("")
    launch = FakeLaunch(completed())

    run_export_smoke_operation(artifact=str(artifact), args=[], make_launch=launch)

    assert launch.roots == [None]


def test_a_private_root_that_cannot_be_created_is_a_typed_refusal(
    tmp_path, monkeypatch
):
    artifact = runnable_file(tmp_path / "game")

    def denied(*args, **kwargs):
        raise OSError("Read-only file system")

    monkeypatch.setattr("gda.commands.export.tempfile.mkdtemp", denied)
    launch = FakeLaunch(completed())

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "user_data_unwritable"
    assert not launch.calls


# --- The passthrough ---------------------------------------------------------


def test_a_completed_run_is_passed_through_with_both_paths(tmp_path):
    bundle = app_bundle(tmp_path / "Game.app")
    launch = FakeLaunch(completed(stdout="hello\n", stderr="noise\n", exit_code=0))

    outcome = run_export_smoke_operation(
        artifact=str(bundle), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.artifact == str(bundle)
    assert outcome.executable == str(bundle / "Contents" / "MacOS" / "Game")
    assert outcome.exit_status == 0
    assert outcome.stdout == "hello\n"
    assert outcome.stderr == "noise\n"
    assert outcome.stdout_bytes == len("hello\n")
    assert outcome.stdout_truncated is False
    assert outcome.stdout_file is None


def test_a_non_zero_exit_is_data_not_a_failure(tmp_path):
    # The ADR-0042 crux, inherited from ADR-0031: gda does not interpret what the
    # game meant by its status, so a deliberate non-zero exit is a SUCCESS result.
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(exit_code=3))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.exit_status == 3


def test_recognized_errors_reach_diagnostics_on_a_successful_run(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stderr=LEAK_STDERR))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert [d.kind.value for d in outcome.diagnostics] == ["shutdown_leak"]


def test_a_timeout_is_the_shared_envelope_naming_this_launch(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(
        RunResult(
            stdout="partial out\n",
            stderr="partial err\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
            elapsed_seconds=5.0,
            timeout_bound=TimeoutBound(SMOKE_TIMEOUT_LABEL, 5.0),
        )
    )

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], timeout=5.0, make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert SMOKE_TIMEOUT_LABEL in outcome.error.message
    # The capture the streaming launch preserved is what the envelope carries.
    assert "partial out" in outcome.error.diagnostics
    assert "partial err" in outcome.error.diagnostics


def test_a_signal_death_is_the_shared_crash_envelope(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(exit_code=-11))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "engine_crashed"


def test_a_stdout_above_the_cap_is_bounded_and_names_the_exported_artifact(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stdout="y" * (STDOUT_CAP + 5)))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.stdout_truncated is True
    assert outcome.stdout_bytes == STDOUT_CAP + 5
    assert outcome.stdout_file is not None
    spill = Path(outcome.stdout_file)
    assert spill.read_bytes() == b"y" * (STDOUT_CAP + 5)
    assert spill.name.startswith("gda-smoke-stdout-")
    spill.unlink()


def test_a_spill_gda_cannot_write_is_the_typed_refusal(tmp_path, monkeypatch):
    artifact = runnable_file(tmp_path / "game")

    def denied(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr("gda.completed_run.tempfile.mkstemp", denied)
    launch = FakeLaunch(completed(stdout="y" * (STDOUT_CAP + 5)))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "stdout_spill_failed"
    # The message leads with WHAT ran: the second consumer is an exported game, not
    # a script, and that is the whole generalization the wording needed.
    assert "the exported artifact ran" in outcome.error.message


def test_the_result_inherits_the_shared_bounded_stdout_truth_table():
    # The base's whole job (`gda.completed_run.CompletedRunResult`): the four stdout
    # markers are ONE machine contract, and the smoke gets the same enforcement
    # `script run` has without a second copy of the rule.
    ok = dict(
        artifact="/tmp/Game.app",
        executable="/tmp/Game.app/Contents/MacOS/Game",
        exit_status=0,
        stdout="hi",
        stderr="",
        stdout_bytes=2,
        stdout_truncated=False,
        stdout_file=None,
        diagnostics=[],
    )
    assert ExportSmokeResult(**ok).stdout_bytes == 2

    with pytest.raises(
        ValidationError, match="must name its complete-stream spill file"
    ):
        ExportSmokeResult(**{**ok, "stdout_truncated": True})
    with pytest.raises(ValidationError, match="carries no spill file"):
        ExportSmokeResult(**{**ok, "stdout_file": "/tmp/spill.log"})
    with pytest.raises(ValidationError, match="byte count is the returned"):
        ExportSmokeResult(**{**ok, "stdout_bytes": 99})


# --- --strict, the two triggers ----------------------------------------------


def test_strict_fails_a_non_zero_exit_with_typed_evidence(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stdout="out\n", stderr="err\n", exit_code=3))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "smoke_failed"
    assert outcome.exit_code == EXIT_OPERATION
    assert outcome.error.evidence is not None
    assert outcome.error.evidence.exit_status == 3
    assert outcome.error.evidence.script_errors == []
    # Both streams, labelled — a game that reports through print() would otherwise
    # hand a --strict caller a failure with no content.
    assert SMOKE_OUTPUT_STDOUT_HEADER in outcome.error.diagnostics
    assert SMOKE_OUTPUT_STDERR_HEADER in outcome.error.diagnostics
    assert "out" in outcome.error.diagnostics
    assert "err" in outcome.error.diagnostics


def test_strict_fails_a_zero_exit_that_leaked_at_shutdown(tmp_path):
    # The trigger a status-only gate cannot see, and the one GDA-DF-072 needed: the
    # build exited 0 and still left objects alive.
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stderr=LEAK_STDERR, exit_code=0))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "smoke_failed"
    assert "leak at exit" in outcome.error.message
    assert outcome.error.evidence is not None
    assert outcome.error.evidence.exit_status == 0
    assert [e.kind.value for e in outcome.error.evidence.script_errors or []] == [
        "shutdown_leak"
    ]


def test_strict_keeps_the_status_in_the_message_when_a_run_has_both(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stderr=LEAK_STDERR, exit_code=2))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    assert isinstance(outcome, Failure)
    assert "status 2" in outcome.error.message
    assert "leak at exit" not in outcome.error.message


def test_strict_passes_a_clean_run_through(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stdout="fine\n", exit_code=0))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.exit_status == 0


def test_without_strict_a_leaking_non_zero_run_is_still_a_success(tmp_path):
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(stderr=LEAK_STDERR, exit_code=9))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], make_launch=launch
    )

    assert isinstance(outcome, ExportSmokeResult)
    assert outcome.exit_status == 9


def test_the_strict_envelope_carries_no_placement(tmp_path):
    # The smoke's root is a private one it creates and removes, so naming it would
    # hand a caller a directory that no longer exists (#862's three named builders
    # stay three).
    artifact = runnable_file(tmp_path / "game")
    launch = FakeLaunch(completed(exit_code=1))

    outcome = run_export_smoke_operation(
        artifact=str(artifact), args=[], strict=True, make_launch=launch
    )

    assert isinstance(outcome, Failure)
    emitted = GdaErrorEnvelope(error=outcome.error).model_dump(exclude_none=True)
    evidence = emitted["error"]["evidence"]
    assert set(evidence) == {"exit_status", "script_errors"}
