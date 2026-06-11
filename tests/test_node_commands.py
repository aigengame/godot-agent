"""S3: gda node add / node list success paths against a fake runner (issue #53).

The node command group acts on nodes WITHIN a scene file (load → locate →
mutate → pack → save), staying headless. These tests drive the same proven
pipeline as the scene group — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import inject_runner, sentinel

ADD_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
    "script_class": None,
}


def test_node_add_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(ADD_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "node",
            "add",
            "/tmp/proj/main.tscn",
            "--type",
            "Sprite2D",
            "--parent",
            ".",
            "--name",
            "Hero",
            "--json",
        ],
    )

    assert result.exit_code == 0
    # stdout carries ONLY the result payload — a single valid JSON object.
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    # The created node's path/name/type (issue #53): path is the node path
    # relative to the scene root, so an agent can address the node afterwards.
    assert data["path"] == "Hero"
    assert data["name"] == "Hero"
    assert data["type"] == "Sprite2D"
    # The operation was dispatched by name with the command's typed params.
    assert fake.calls == [
        (
            "node-add",
            {
                "path": "/tmp/proj/main.tscn",
                "parent": ".",
                "type": "Sprite2D",
                "name": "Hero",
            },
        )
    ]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


LIST_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "root": {
        "name": "main",
        "type": "Node2D",
        "path": ".",
        "children": [
            {
                "name": "Hero",
                "type": "Sprite2D",
                "path": "Hero",
                "children": [
                    {
                        "name": "Hitbox",
                        "type": "Area2D",
                        "path": "Hero/Hitbox",
                        "children": [],
                    }
                ],
            }
        ],
    },
}


def test_node_list_json_emits_node_tree_with_paths_and_exit_zero(monkeypatch):
    # node list is the node-group verifier (issue #53): it reports the scene's
    # tree like scene get, but each node carries its node path — the address an
    # agent feeds back into node add's --parent.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(LIST_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["node", "list", "/tmp/proj/main.tscn", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    # The root is addressed as '.', matching node add's --parent default.
    assert data["root"]["path"] == "."
    hero = data["root"]["children"][0]
    assert (hero["name"], hero["type"], hero["path"]) == ("Hero", "Sprite2D", "Hero")
    assert hero["children"][0]["path"] == "Hero/Hitbox"
    assert fake.calls == [("node-list", {"path": "/tmp/proj/main.tscn"})]


def test_node_add_defaults_parent_to_root_and_name_to_type(monkeypatch):
    # The two ergonomic defaults (issue #53): omitting --parent targets the
    # scene root ('.'), and omitting --name names the node after its type —
    # mirroring how the Godot editor names a freshly added node.
    stdout = sentinel({**ADD_RESULT, "path": "Sprite2D", "name": "Sprite2D"})
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["node", "add", "/tmp/proj/main.tscn", "--type", "Sprite2D", "--json"],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "node-add",
            {
                "path": "/tmp/proj/main.tscn",
                "parent": ".",
                "type": "Sprite2D",
                "name": "Sprite2D",
            },
        )
    ]
