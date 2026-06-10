"""The headless command module owns the shared command execution interface."""

import json
from pathlib import Path

import pytest
import typer

from gda.headless import HeadlessCommand
from gda.models import EngineVersion, InfoParams
from gda.runner import RunResult
from tests.support import FakeRunner, sentinel

VERSION_INFO = {
    "major": 4,
    "minor": 6,
    "patch": 3,
    "hex": 0x040603,
    "status": "stable",
    "build": "official",
    "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
    "string": "4.6.3-stable (official)",
    "timestamp": 0,
}


def test_headless_command_emit_owns_runner_classification_and_json_output(capsys):
    fake = FakeRunner(
        RunResult(stdout=sentinel(VERSION_INFO), stderr="engine diagnostic\n", exit_code=0)
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
    )

    command.emit(
        InfoParams(),
        godot="/tmp/Godot",
        project=Path("/tmp/project"),
        json_output=True,
        render_text=lambda version: version.string,
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
        )
    )

    def make_runner(binary: Path, project: Path | None):
        return fake

    command: HeadlessCommand[EngineVersion] = HeadlessCommand(
        operation="info",
        input_model=InfoParams,
        output_model=EngineVersion,
    )

    with pytest.raises(typer.Exit) as raised:
        command.emit(
            InfoParams(),
            godot="/tmp/missing",
            project=None,
            json_output=False,
            render_text=lambda version: version.string,
            make_runner=make_runner,
        )

    captured = capsys.readouterr()
    assert raised.value.exit_code == 127
    assert json.loads(captured.out)["error"]["code"] == "binary_not_found"
    assert "not found" in captured.err
