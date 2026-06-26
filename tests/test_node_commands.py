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
from tests.support import (
    NODE_ADD_RESULT as ADD_RESULT,
    NODE_CONNECT_RESULT as CONNECT_RESULT,
    NODE_DUPLICATE_RESULT as DUPLICATE_RESULT,
    NODE_GET_RESULT as GET_RESULT,
    NODE_LIST_RESULT as LIST_RESULT,
    NODE_MOVE_RESULT as MOVE_RESULT,
    NODE_REMOVE_RESULT as REMOVE_RESULT,
    NODE_SET_RESULT as SET_RESULT,
    inject_runner,
    sentinel,
)


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
    assert fake.calls == [("node-get", {"path": "/tmp/proj/main.tscn", "node": "Hero"})]


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


def test_node_duplicate_json_echoes_the_new_copy_and_exit_zero(monkeypatch):
    # node duplicate (issue #56) copies a node and its subtree under the source's
    # own parent with a fresh name, echoing the source and the new copy's
    # address/name/type — the result an agent feeds back into other node commands.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(DUPLICATE_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["node", "duplicate", "/tmp/proj/main.tscn", "--node", "Hero", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["source_path"] == "Hero"
    assert (data["path"], data["name"], data["type"]) == ("Hero2", "Hero2", "Sprite2D")
    assert fake.calls == [
        ("node-duplicate", {"path": "/tmp/proj/main.tscn", "node": "Hero"})
    ]


def test_node_move_json_echoes_the_reparented_node_and_exit_zero(monkeypatch):
    # node move (issue #56) reparents a node and its subtree under a new parent,
    # echoing the source, the new parent, and the node's new address — the
    # result an agent feeds back into other node commands. Both node paths are
    # passed through as raw strings; the operation resolves them.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(MOVE_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "node",
            "move",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--to",
            "Enemies",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["source_path"] == "Hero"
    assert data["new_parent"] == "Enemies"
    assert (data["path"], data["name"], data["type"]) == (
        "Enemies/Hero",
        "Hero",
        "Sprite2D",
    )
    assert fake.calls == [
        (
            "node-move",
            {"path": "/tmp/proj/main.tscn", "node": "Hero", "to": "Enemies"},
        )
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


def test_node_connect_signal_json_dispatches_the_four_part_connection(monkeypatch):
    # node connect-signal is the wire half of issue #57: it records a source
    # node's signal -> target node's method connection in the .tscn. The four
    # parts are addressed by --from/--signal/--to/--method; the wire param key
    # for the source is `from` (matching the .tscn [connection] key), since
    # `from` is a Python keyword only at the model layer.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(CONNECT_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "node",
            "connect-signal",
            "/tmp/proj/main.tscn",
            "--from",
            "Emitter",
            "--signal",
            "timeout",
            "--to",
            "Receiver",
            "--method",
            "on_timeout",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    assert (data["from"], data["signal"]) == ("Emitter", "timeout")
    assert (data["to"], data["method"]) == ("Receiver", "on_timeout")
    assert fake.calls == [
        (
            "node-connect-signal",
            {
                "path": "/tmp/proj/main.tscn",
                "from": "Emitter",
                "signal": "timeout",
                "to": "Receiver",
                "method": "on_timeout",
            },
        )
    ]


def test_node_disconnect_signal_json_dispatches_the_four_part_connection(monkeypatch):
    # node disconnect-signal is the unwire half of issue #57: same four-part
    # addressing, dispatched by its own operation name.
    stdout = sentinel(CONNECT_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "node",
            "disconnect-signal",
            "/tmp/proj/main.tscn",
            "--from",
            "Emitter",
            "--signal",
            "timeout",
            "--to",
            "Receiver",
            "--method",
            "on_timeout",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert (data["from"], data["to"]) == ("Emitter", "Receiver")
    assert fake.calls == [
        (
            "node-disconnect-signal",
            {
                "path": "/tmp/proj/main.tscn",
                "from": "Emitter",
                "signal": "timeout",
                "to": "Receiver",
                "method": "on_timeout",
            },
        )
    ]


def test_node_connect_signal_requires_all_four_connection_flags(monkeypatch):
    # The four connection flags are mandatory (no sensible default for any part
    # of a connection): omitting one is a usage error (exit 2), surfaced before
    # any engine path so no Godot process is spawned.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(CONNECT_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "node",
            "connect-signal",
            "/tmp/proj/main.tscn",
            "--from",
            "Emitter",
            "--signal",
            "timeout",
            "--to",
            "Receiver",
            # --method omitted
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert fake.calls == []
