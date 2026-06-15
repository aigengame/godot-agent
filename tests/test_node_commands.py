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


GET_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
    "properties": [
        {"name": "position", "type": "Vector2", "value": [10.0, 20.0]},
        {"name": "visible", "type": "bool", "value": True},
    ],
}


def test_node_get_json_emits_typed_properties_and_exit_zero(monkeypatch):
    # node get is the read half of issue #55: it loads a scene and reports the
    # addressed node's properties as typed JSON — the read an agent verifies a
    # `set` against.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(GET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["node", "get", "/tmp/proj/main.tscn", "--node", "Hero", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    assert (data["path"], data["name"], data["type"]) == ("Hero", "Hero", "Sprite2D")
    position = data["properties"][0]
    assert (position["name"], position["type"], position["value"]) == (
        "position",
        "Vector2",
        [10.0, 20.0],
    )
    # The node is addressed by node path, dispatched by the operation name.
    assert fake.calls == [
        ("node-get", {"path": "/tmp/proj/main.tscn", "node": "Hero"})
    ]


SET_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "property": "position",
    "type": "Vector2",
    "value": [3.0, 4.0],
}


def test_node_set_json_echoes_the_coerced_property_and_exit_zero(monkeypatch):
    # node set is the write half of issue #55: it coerces the CLI string value
    # to the property's declared type, saves, and echoes the coerced property —
    # the result an agent asserts (and which round-trips via node get).
    stdout = sentinel(SET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "node",
            "set",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--property",
            "position",
            "--value",
            "3,4",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert (data["path"], data["property"], data["type"]) == (
        "Hero",
        "position",
        "Vector2",
    )
    assert data["value"] == [3.0, 4.0]
    # The CLI value is passed as a raw string; coercion is the operation's job.
    assert fake.calls == [
        (
            "node-set",
            {
                "path": "/tmp/proj/main.tscn",
                "node": "Hero",
                "property": "position",
                "value": "3,4",
            },
        )
    ]


REMOVE_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "Hero",
    "name": "Hero",
    "type": "Sprite2D",
}


def test_node_remove_json_echoes_the_removed_node_and_exit_zero(monkeypatch):
    # node remove is the first structural edit (issue #56): it deletes a node
    # and its subtree, echoing the removed node's address/name/type — the result
    # an agent asserts. The node is addressed by node path, dispatched by name.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(REMOVE_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["node", "remove", "/tmp/proj/main.tscn", "--node", "Hero", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    assert (data["path"], data["name"], data["type"]) == ("Hero", "Hero", "Sprite2D")
    assert fake.calls == [
        ("node-remove", {"path": "/tmp/proj/main.tscn", "node": "Hero"})
    ]


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
