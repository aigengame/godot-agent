"""Static model-content sampling is typed and discoverable on both channels."""

import json
import sys

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.game import (
    GameInspectModelContentParams,
    GameInspectModelContentResult,
    run_game_inspect_model_content_operation,
)
from gda.commands.resource import (
    ResourceInspectModelContentParams,
    ResourceInspectModelContentResult,
    run_resource_inspect_model_content_operation,
)
from gda.errors import Failure
from gda.runner import RunResult
from tests.support import (
    FakeRunner,
    minimal_project,
    sentinel,
    structured_argv_error_message,
)


CONTENT = {
    "measurement": "godot-static-model-content-v1",
    "engine_version": {
        "major": 4,
        "minor": 6,
        "patch": 3,
        "hex": 0x040603,
        "status": "stable",
        "build": "official",
        "hash": "test",
        "string": "4.6.3-stable (official)",
        "timestamp": 0,
    },
    "complete": True,
    "digest": "a" * 64,
    "nodes": 3,
    "surfaces": 1,
    "vertices": 24,
    "unsupported": [],
    "omitted": [],
}


def test_resource_and_game_commands_publish_the_same_bounded_content_shape():
    runner = CliRunner()
    resource = runner.invoke(app, ["resource", "inspect-model-content", "--schema"])
    game = runner.invoke(app, ["game", "inspect-model-content", "--schema"])

    assert resource.exit_code == game.exit_code == 0
    resource_schema = json.loads(resource.stdout)
    game_schema = json.loads(game.stdout)
    for schema in (resource_schema, game_schema):
        props = schema["input"]["properties"]
        assert props["max_nodes"]["default"] == 256
        assert props["max_nodes"]["minimum"] == 1
        assert props["max_nodes"]["maximum"] == 1024
        assert props["max_vertices"]["default"] == 200000
        assert props["max_vertices"]["minimum"] == 1
        assert props["max_vertices"]["maximum"] == 1000000
        content = schema["output"]["$defs"]["ModelContent"]
        assert content["properties"]["measurement"]["const"] == (
            "godot-static-model-content-v1"
        )
        assert content["properties"]["nodes"]["minimum"] == 0
        assert content["properties"]["surfaces"]["minimum"] == 0
        assert content["properties"]["vertices"]["minimum"] == 0
    assert resource_schema["kind"] == "headless"
    assert game_schema["kind"] == "live"


def test_resource_returning_operation_normalizes_and_classifies_native_result(tmp_path):
    project = minimal_project(tmp_path / "project")
    source = project / "models" / "asset.glb"
    source.parent.mkdir()
    source.write_bytes(b"glb")
    fake = FakeRunner(
        RunResult(
            stdout=sentinel({"path": "res://models/asset.glb", "content": CONTENT}),
            stderr="",
            exit_code=0,
        )
    )

    result = run_resource_inspect_model_content_operation(
        project,
        ResourceInspectModelContentParams(
            path=str(source), max_nodes=7, max_vertices=9
        ),
        godot=sys.executable,
        make_runner=lambda binary, selected: fake,
    )

    assert isinstance(result, ResourceInspectModelContentResult)
    assert result.content.digest == "a" * 64
    assert fake.calls == [
        (
            "resource-inspect-model-content",
            {"path": "res://models/asset.glb", "max_nodes": 7, "max_vertices": 9},
        )
    ]


def test_resource_returning_operation_rejects_wrong_type_and_escape_before_native(
    tmp_path,
):
    project = minimal_project(tmp_path / "project")
    outside = tmp_path / "outside.glb"
    outside.write_bytes(b"glb")

    def no_runner(*args):
        raise AssertionError("invalid paths must not start Godot")

    wrong_type = run_resource_inspect_model_content_operation(
        project,
        ResourceInspectModelContentParams(path="res://asset.tscn"),
        godot=sys.executable,
        make_runner=no_runner,
    )
    escaped = run_resource_inspect_model_content_operation(
        project,
        ResourceInspectModelContentParams(path=str(outside)),
        godot=sys.executable,
        make_runner=no_runner,
    )

    assert isinstance(wrong_type, Failure)
    assert wrong_type.error.code == "invalid_params"
    assert isinstance(escaped, Failure)
    assert escaped.error.code == "target_outside_project"


def test_live_returning_operation_uses_live_classifier_and_preserves_identity(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    payload = {
        "node": "/root/Main/Model",
        "instance_id": 42,
        "scene_file_path": "res://model.glb",
        "session_id": "session-1",
        "engine_frame": 12,
        "content": CONTENT,
    }
    fake = FakeRunner(RunResult(stdout=sentinel(payload), stderr="", exit_code=0))
    monkeypatch.setattr("gda.dispatch.make_live_runner", lambda binary, selected: fake)

    result = run_game_inspect_model_content_operation(
        project,
        GameInspectModelContentParams(
            node="/root/Main/Model", max_nodes=8, max_vertices=10
        ),
    )

    assert isinstance(result, GameInspectModelContentResult)
    assert result.instance_id == 42
    assert result.session_id == "session-1"
    assert fake.calls == [
        (
            "game-inspect-model-content",
            {"node": "/root/Main/Model", "max_nodes": 8, "max_vertices": 10},
        )
    ]


def test_live_node_must_be_absolute_before_dispatch(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "game",
            "inspect-model-content",
            "--node",
            "Main/Model",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "absolute" in structured_argv_error_message(result)
