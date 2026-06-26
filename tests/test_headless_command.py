"""The headless command module owns the shared command execution interface."""

import json
from pathlib import Path

import pytest
import typer

from gda.execution import ExecutionKind
from gda.headless import HeadlessCommand
from gda.models import EngineVersion, InfoParams
from gda.render import render_engine_version
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


def test_headless_command_emit_owns_runner_classification_and_json_output(capsys):
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

    command: HeadlessCommand[EngineVersion] = HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
        render=render_engine_version,
    )

    command.emit(
        InfoParams(),
        godot="/tmp/Godot",
        project=Path("/tmp/project"),
        json_output=True,
        make_runner=make_runner,
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["string"] == "4.6.3-stable (official)"
    assert "engine diagnostic" in captured.err
    assert fake.calls == [("info", {})]
    assert seen == {"binary": Path("/tmp/Godot"), "project": Path("/tmp/project")}


def test_headless_command_emit_owns_structured_failure_output(capsys):
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

    command: HeadlessCommand[EngineVersion] = HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
        render=render_engine_version,
    )

    with pytest.raises(typer.Exit) as raised:
        command.emit(
            InfoParams(),
            godot="/tmp/missing",
            project=None,
            json_output=False,
            make_runner=make_runner,
        )

    captured = capsys.readouterr()
    assert raised.value.exit_code == 127
    assert json.loads(captured.out)["error"]["code"] == "binary_not_found"
    assert "not found" in captured.err


def test_empty_godot_path_maps_to_structured_binary_not_found(capsys):
    # ``--godot ""`` makes binary resolution raise ``ValueError`` *before* a
    # runner is ever built; that must become the structured ``binary_not_found``
    # environment envelope (exit 127), not escape as a raw traceback (#33).
    def make_runner(binary: Path, project: Path | None):  # pragma: no cover
        raise AssertionError("no runner should be built for an unresolvable binary")

    command: HeadlessCommand[EngineVersion] = HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
        render=render_engine_version,
    )

    with pytest.raises(typer.Exit) as raised:
        command.emit(
            InfoParams(),
            godot="",
            project=None,
            json_output=False,
            make_runner=make_runner,
        )

    captured = capsys.readouterr()
    assert raised.value.exit_code == 127
    assert json.loads(captured.out)["error"]["code"] == "binary_not_found"
