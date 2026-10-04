"""The headless command module owns the shared command execution interface."""

from pathlib import Path

from gda.errors import Failure
from gda.execution import ExecutionKind
from gda.headless import HeadlessCommand
from gda.commands.meta import InfoParams, render_engine_version
from gda.models import EngineVersion
from gda.runner import LaunchFailure, RunResult
from tests.support import VERSION_INFO, FakeRunner, sentinel


def test_headless_command_classifies_its_execution_channel_as_headless_by_default():
    # A command carries a static execution-channel `kind` (ADR-0017); a plain
    # sentinel-pipeline command is HEADLESS without having to say so.
    command: HeadlessCommand[EngineVersion] = HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
        render=render_engine_version,
    )

    assert command.kind is ExecutionKind.HEADLESS


def _info_command() -> HeadlessCommand[EngineVersion]:
    return HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
        render=render_engine_version,
    )


def test_headless_command_execute_owns_runner_classification(capsys):
    # The outcome step: it builds the runner from the resolved binary and project,
    # classifies the run into the typed model, and tees a success's stderr. Emitting
    # the result is the dispatch entry's tail, not this module's.
    fake = FakeRunner(
        RunResult(
            stdout=sentinel(VERSION_INFO), stderr="engine diagnostic\n", exit_code=0
        )
    )
    seen: dict[str, Path | None] = {}

    def make_runner(binary: Path, project: Path | None):
        seen["binary"] = binary
        seen["project"] = project
        return fake

    outcome = _info_command().execute(
        InfoParams(),
        godot="/tmp/Godot",
        project=Path("/tmp/project"),
        make_runner=make_runner,
    )

    captured = capsys.readouterr()
    assert isinstance(outcome, EngineVersion)
    assert outcome.string == "4.6.3-stable (official)"
    assert captured.out == ""
    assert "engine diagnostic" in captured.err
    assert fake.calls == [("info", {})]
    assert seen == {"binary": Path("/tmp/Godot"), "project": Path("/tmp/project")}


def test_headless_command_execute_returns_a_structured_failure(capsys):
    fake = FakeRunner(
        RunResult(
            stdout="",
            stderr="gda: Godot binary not found: /tmp/missing\n",
            exit_code=127,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
    )

    def make_runner(binary: Path, project: Path | None):
        return fake

    outcome = _info_command().execute(
        InfoParams(), godot="/tmp/missing", project=None, make_runner=make_runner
    )

    # A failure is RETURNED, never emitted: its stderr rides `child_stderr` to the
    # emission point, which alone knows the caller's channel (ADR-0002's #803 note).
    captured = capsys.readouterr()
    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 127
    assert outcome.error.code == "binary_not_found"
    assert "not found" in outcome.child_stderr
    assert captured.out == "" and captured.err == ""


def test_empty_godot_path_maps_to_structured_binary_not_found():
    # ``--godot ""`` makes binary resolution raise ``ValueError`` *before* a
    # runner is ever built; that must become the structured ``binary_not_found``
    # environment failure (exit 127), not escape as a raw traceback (#33).
    def make_runner(binary: Path, project: Path | None):  # pragma: no cover
        raise AssertionError("no runner should be built for an unresolvable binary")

    outcome = _info_command().execute(
        InfoParams(), godot="", project=None, make_runner=make_runner
    )

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 127
    assert outcome.error.code == "binary_not_found"
