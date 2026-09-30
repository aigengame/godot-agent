"""S3: gda scene create / scene get success paths against a fake runner (issue #18).

The first domain command group (ADR-0005): each command drives the proven
headless pipeline — Typer → binary resolution → runner → sentinel parse →
typed model → JSON — exercised here with canned engine output, no real Godot.
"""

import json

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import (
    SCENE_CREATE_INHERITED_RESULT as INHERITED_CREATE_RESULT,
    SCENE_CREATE_RESULT as CREATE_RESULT,
    SCENE_DELETE_RESULT as DELETE_RESULT,
    SCENE_GET_RESULT as GET_RESULT,
    SCENE_LIST_RESULT as LIST_RESULT,
    invoke_cli,
    minimal_project,
    recording_runner,
    sentinel,
)


def test_scene_create_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "create", "/tmp/proj/main.tscn", "--root-type", "Node2D", "--json"],
        stdout=sentinel(CREATE_RESULT),
        stderr="engine diagnostic\n",
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=stdout,
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


def test_scene_create_inherits_dispatches_the_base_without_a_root_type(monkeypatch):
    # #1050: --inherits replaces --root-type. The dispatch payload carries the
    # base and omits root_type, and the result echoes the base as `inherits`.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "scene",
            "create",
            "/tmp/proj/goblin.tscn",
            "--inherits",
            "res://base_enemy.tscn",
            "--json",
        ],
        stdout=sentinel(INHERITED_CREATE_RESULT),
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == INHERITED_CREATE_RESULT
    assert fake.calls == [
        (
            "scene-create",
            {
                "path": "/tmp/proj/goblin.tscn",
                "root_name": "goblin",
                "inherits": "res://base_enemy.tscn",
            },
        )
    ]


@pytest.mark.parametrize(
    "selectors",
    [
        pytest.param(
            ["--root-type", "Node2D", "--inherits", "res://base_enemy.tscn"],
            id="both",
        ),
        pytest.param([], id="neither"),
    ],
)
def test_scene_create_needs_exactly_one_of_root_type_or_inherits(
    monkeypatch, selectors
):
    # #1050: --root-type and --inherits are mutually exclusive and one is
    # required, the rule node add applies to --type/--instance: on argv a
    # violation is a usage error (exit 2) and no engine is spawned.
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "create", "/tmp/proj/goblin.tscn", *selectors, "--json"],
        stdout=sentinel(INHERITED_CREATE_RESULT),
    )

    assert result.exit_code == 2
    assert "--inherits" in result.output
    assert fake.calls == []


def test_scene_create_params_json_with_both_selectors_is_invalid_params(monkeypatch):
    # The same rule on the --params-json channel is a structured invalid_params.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "scene",
            "create",
            "--params-json",
            json.dumps(
                {
                    "path": "/tmp/proj/goblin.tscn",
                    "root_type": "Node2D",
                    "inherits": "res://base_enemy.tscn",
                }
            ),
            "--json",
        ],
        stdout=sentinel(INHERITED_CREATE_RESULT),
    )

    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_params"
    assert "--inherits" in err["message"]
    assert fake.calls == []


def test_scene_create_inherits_refuses_a_scn_target_on_argv(monkeypatch):
    # The inherited header is .tscn text, and text in a .scn does not load: the
    # target is refused before any engine spawn.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "scene",
            "create",
            "/tmp/proj/goblin.scn",
            "--inherits",
            "res://base_enemy.tscn",
            "--json",
        ],
        stdout=sentinel(INHERITED_CREATE_RESULT),
    )

    assert result.exit_code == 2
    assert ".scn" in result.output
    assert fake.calls == []


def test_scene_create_inherits_refuses_a_scn_target_on_params_json(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        [
            "scene",
            "create",
            "--params-json",
            json.dumps(
                {"path": "/tmp/proj/goblin.scn", "inherits": "res://base_enemy.tscn"}
            ),
            "--json",
        ],
        stdout=sentinel(INHERITED_CREATE_RESULT),
    )

    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_params"
    assert ".scn" in err["message"]
    assert fake.calls == []


def test_scene_create_root_type_still_accepts_a_scn_target(monkeypatch):
    # The .scn refusal is --inherits' alone: a typed root saves through the
    # engine's saver, which writes the binary format for a .scn.
    stdout = sentinel({**CREATE_RESULT, "path": "/tmp/proj/main.scn"})
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "create", "/tmp/proj/main.scn", "--root-type", "Node2D", "--json"],
        stdout=stdout,
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "scene-create",
            {"path": "/tmp/proj/main.scn", "root_type": "Node2D", "root_name": "main"},
        )
    ]


def test_scene_get_json_emits_structured_node_tree_and_exit_zero(monkeypatch):
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "get", "/tmp/proj/main.tscn", "--json"],
        stdout=sentinel(GET_RESULT),
    )

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
    minimal_project(tmp_path)
    projects = recording_runner(
        monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["scene", "get", "res://main.tscn", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert projects[0] == tmp_path


def test_scene_get_expands_user_home_in_filesystem_path_but_not_res(monkeypatch):
    # Path normalization lives at the CLI layer (issue #32): a filesystem path
    # gets ~ expanded; an engine-resolved res:// path passes through untouched.
    _, fake = invoke_cli(
        monkeypatch,
        ["scene", "get", "~/game/main.tscn", "--json"],
        stdout=sentinel(GET_RESULT),
    )
    assert "~" not in fake.calls[0][1]["path"]
    assert fake.calls[0][1]["path"].endswith("/game/main.tscn")

    fake.calls.clear()
    CliRunner().invoke(app, ["scene", "get", "res://main.tscn", "--json"])
    assert fake.calls[0][1]["path"] == "res://main.tscn"


GET_EXPORTS_RESULT = {
    "path": "/tmp/proj/main.tscn",
    "nodes": [
        {
            "path": ".",
            "name": "main",
            "type": "Node2D",
            "script": "res://main.gd",
            "exports": [
                {
                    "name": "speed",
                    "type": "float",
                    "hint": 0,
                    "hint_string": "",
                    "value": 3.5,
                },
                {
                    "name": "title",
                    "type": "String",
                    "hint": 0,
                    "hint_string": "",
                    "value": "Hello",
                },
            ],
        },
        {
            "path": "Hero",
            "name": "Hero",
            "type": "Sprite2D",
            "script": "res://hero.gd",
            "exports": [
                {
                    "name": "max_hp",
                    "type": "int",
                    "hint": 1,
                    "hint_string": "0,100",
                    "value": 100,
                }
            ],
        },
    ],
}


def test_scene_get_exports_json_emits_per_node_exports_and_exit_zero(monkeypatch):
    # scene get-exports loads a scene and reports, per node (by node path), the
    # @export properties its attached script declares (issue #58): each export's
    # name, declared type, hint/hint_string, and value as typed JSON.
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "get-exports", "/tmp/proj/main.tscn", "--json"],
        stdout=sentinel(GET_EXPORTS_RESULT),
        stderr="engine diagnostic\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/main.tscn"
    # The root node, addressed as '.', carries the exports its script declares.
    root = data["nodes"][0]
    assert (root["path"], root["name"], root["type"]) == (".", "main", "Node2D")
    assert root["script"] == "res://main.gd"
    speed = root["exports"][0]
    assert (speed["name"], speed["type"], speed["value"]) == ("speed", "float", 3.5)
    # A descendant node carries its own exports with hint/hint_string.
    hero = data["nodes"][1]
    assert hero["path"] == "Hero"
    assert hero["exports"][0]["hint_string"] == "0,100"
    # The operation is dispatched by name with the command's typed params.
    assert fake.calls == [("scene-get-exports", {"path": "/tmp/proj/main.tscn"})]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


def test_scene_get_exports_expands_user_home_in_filesystem_path_but_not_res(
    monkeypatch,
):
    # Path normalization at the CLI layer (issue #32) applies to get-exports too:
    # a filesystem path gets ~ expanded; a res:// path passes through untouched.
    _, fake = invoke_cli(
        monkeypatch,
        ["scene", "get-exports", "~/game/main.tscn", "--json"],
        stdout=sentinel(GET_EXPORTS_RESULT),
    )
    assert "~" not in fake.calls[0][1]["path"]
    assert fake.calls[0][1]["path"].endswith("/game/main.tscn")

    fake.calls.clear()
    CliRunner().invoke(app, ["scene", "get-exports", "res://main.tscn", "--json"])
    assert fake.calls[0][1]["path"] == "res://main.tscn"


def test_scene_get_exports_empty_scene_is_a_valid_empty_listing(monkeypatch):
    # A scene with no exported variables anywhere is a successful, empty listing
    # (nodes == []), not a failure.
    stdout = sentinel({"path": "/tmp/proj/bare.tscn", "nodes": []})
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "get-exports", "/tmp/proj/bare.tscn", "--json"],
        stdout=stdout,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["nodes"] == []


def test_scene_list_json_enumerates_project_scenes_and_exit_zero(monkeypatch, tmp_path):
    # scene list enumerates the resolved project's .tscn files (issue #54):
    # each entry carries its res:// path plus the root name/type read cheaply
    # from the scene's stored state.
    minimal_project(tmp_path)
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "list", "--project", str(tmp_path), "--json"],
        stdout=sentinel(LIST_RESULT),
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
    minimal_project(tmp_path)
    projects = recording_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["scene", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert projects[0] == tmp_path


def test_scene_delete_json_reports_what_was_removed_and_exit_zero(monkeypatch):
    # scene delete removes a scene file and names what it deleted (issue #54):
    # the path plus the removed scene's root name/type, so the result names the
    # content, not just the file.
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "delete", "/tmp/proj/old.tscn", "--json"],
        stdout=sentinel(DELETE_RESULT),
        stderr="engine diagnostic\n",
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
    _, fake = invoke_cli(
        monkeypatch,
        ["scene", "delete", "~/game/old.tscn", "--json"],
        stdout=sentinel(DELETE_RESULT),
    )
    assert "~" not in fake.calls[0][1]["path"]
    assert fake.calls[0][1]["path"].endswith("/game/old.tscn")

    fake.calls.clear()
    CliRunner().invoke(app, ["scene", "delete", "res://old.tscn", "--json"])
    assert fake.calls[0][1]["path"] == "res://old.tscn"
