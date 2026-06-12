"""S3: gda scene create / scene get success paths against a fake runner (issue #18).

The first domain command group (ADR-0005): each command drives the proven
headless pipeline — Typer → binary resolution → runner → sentinel parse →
typed model → JSON — exercised here with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import FakeRunner, inject_runner, sentinel

CREATE_RESULT = {
    "path": "/tmp/proj/main.tscn",
    "root_name": "main",
    "root_type": "Node2D",
    "created_dirs": [],
}


def test_scene_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(CREATE_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["scene", "create", "/tmp/proj/main.tscn", "--root-type", "Node2D", "--json"],
    )

    assert result.exit_code == 0
    # stdout carries ONLY the result payload — a single valid JSON object.
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/main.tscn"
    assert data["root_type"] == "Node2D"
    assert data["root_name"] == "main"
    # The operation was dispatched by name with the command's typed params.
    assert fake.calls == [
        (
            "scene-create",
            {
                "path": "/tmp/proj/main.tscn",
                "root_type": "Node2D",
                "root_name": "main",
            },
        )
    ]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


def test_scene_create_accepts_explicit_root_name(monkeypatch):
    stdout = sentinel(
        {**CREATE_RESULT, "path": "/tmp/proj/level.v2.tscn", "root_name": "LevelV2"}
    )
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "/tmp/proj/level.v2.tscn",
            "--root-type",
            "Node2D",
            "--root-name",
            "LevelV2",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["root_name"] == "LevelV2"
    assert fake.calls == [
        (
            "scene-create",
            {
                "path": "/tmp/proj/level.v2.tscn",
                "root_type": "Node2D",
                "root_name": "LevelV2",
            },
        )
    ]


GET_RESULT = {
    "path": "/tmp/proj/main.tscn",
    "root": {
        "name": "main",
        "type": "Node2D",
        "children": [
            {
                "name": "Hero",
                "type": "Sprite2D",
                "children": [{"name": "Hitbox", "type": "Area2D", "children": []}],
            }
        ],
    },
}


def test_scene_get_json_emits_structured_node_tree_and_exit_zero(monkeypatch):
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(GET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["scene", "get", "/tmp/proj/main.tscn", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # Root node name + type, nested children where present (issue #18).
    assert data["root"]["name"] == "main"
    assert data["root"]["type"] == "Node2D"
    assert data["root"]["children"][0]["type"] == "Sprite2D"
    assert data["root"]["children"][0]["children"][0]["name"] == "Hitbox"
    assert fake.calls == [("scene-get", {"path": "/tmp/proj/main.tscn"})]


def test_scene_get_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # --project resolves to a project dir and is handed to the runner (which
    # turns it into the engine's --path so res:// resolves there, issue #32).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    seen: dict = {}

    def record(binary, project):
        seen["project"] = project
        return FakeRunner(
            RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
        )

    monkeypatch.setattr("gda.cli._make_runner", record)

    result = CliRunner().invoke(
        app, ["scene", "get", "res://main.tscn", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path


def test_scene_get_expands_user_home_in_filesystem_path_but_not_res(monkeypatch):
    # Path normalization lives at the CLI layer (issue #32): a filesystem path
    # gets ~ expanded; an engine-resolved res:// path passes through untouched.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
    )

    CliRunner().invoke(app, ["scene", "get", "~/game/main.tscn", "--json"])
    assert "~" not in fake.calls[0][1]["path"]
    assert fake.calls[0][1]["path"].endswith("/game/main.tscn")

    fake.calls.clear()
    CliRunner().invoke(app, ["scene", "get", "res://main.tscn", "--json"])
    assert fake.calls[0][1]["path"] == "res://main.tscn"


LIST_RESULT = {
    "scenes": [
        {"path": "res://main.tscn", "root_name": "main", "root_type": "Node2D"},
        {"path": "res://ui/menu.tscn", "root_name": "Menu", "root_type": "Control"},
        {"path": "res://broken.tscn", "root_name": None, "root_type": None},
    ]
}


def test_scene_list_json_enumerates_project_scenes_and_exit_zero(monkeypatch, tmp_path):
    # scene list enumerates the resolved project's .tscn files (issue #54):
    # each entry carries its res:// path plus the root name/type read cheaply
    # from the scene's stored state.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(LIST_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["scene", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [s["path"] for s in data["scenes"]] == [
        "res://main.tscn",
        "res://ui/menu.tscn",
        "res://broken.tscn",
    ]
    assert data["scenes"][1]["root_type"] == "Control"
    assert data["scenes"][2]["root_name"] is None
    # scene list takes no operation params: the project is process context.
    assert fake.calls == [("scene-list", {})]


def test_scene_list_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # scene list enumerates res:// in the resolved project, so --project must
    # reach the runner (which hands it to the engine as --path, issue #32).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    seen: dict = {}

    def record(binary, project):
        seen["project"] = project
        return FakeRunner(
            RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
        )

    monkeypatch.setattr("gda.cli._make_runner", record)

    result = CliRunner().invoke(
        app, ["scene", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path


DELETE_RESULT = {
    "path": "/tmp/proj/old.tscn",
    "root_name": "old",
    "root_type": "Node2D",
}


def test_scene_delete_json_reports_what_was_removed_and_exit_zero(monkeypatch):
    # scene delete removes a scene file and names what it deleted (issue #54):
    # the path plus the removed scene's root name/type, so the result names the
    # content, not just the file.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(DELETE_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["scene", "delete", "/tmp/proj/old.tscn", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/old.tscn"
    assert data["root_name"] == "old"
    assert data["root_type"] == "Node2D"
    # The operation was dispatched by name with the command's typed params.
    assert fake.calls == [("scene-delete", {"path": "/tmp/proj/old.tscn"})]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


def test_scene_delete_expands_user_home_in_filesystem_path_but_not_res(monkeypatch):
    # Path normalization at the CLI layer (issue #32) applies to delete too: a
    # filesystem path gets ~ expanded; a res:// path passes through untouched.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(DELETE_RESULT), stderr="", exit_code=0)
    )

    CliRunner().invoke(app, ["scene", "delete", "~/game/old.tscn", "--json"])
    assert "~" not in fake.calls[0][1]["path"]
    assert fake.calls[0][1]["path"].endswith("/game/old.tscn")

    fake.calls.clear()
    CliRunner().invoke(app, ["scene", "delete", "res://old.tscn", "--json"])
    assert fake.calls[0][1]["path"] == "res://old.tscn"
