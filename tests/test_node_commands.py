"""S3: gda node add / node list success paths against a fake runner (issue #53).

The node command group acts on nodes WITHIN a scene file (load → locate →
mutate → pack → save), staying headless. These tests drive the same proven
pipeline as the scene group — Typer → binary resolution → runner → sentinel
parse → typed model → JSON — with canned engine output, no real Godot.
"""

import json


from tests.support import (
    NODE_ADD_RESULT as ADD_RESULT,
    NODE_CONNECT_RESULT as CONNECT_RESULT,
    NODE_DUPLICATE_RESULT as DUPLICATE_RESULT,
    NODE_GET_RESULT as GET_RESULT,
    NODE_LIST_RESULT as LIST_RESULT,
    NODE_MOVE_RESULT as MOVE_RESULT,
    NODE_REMOVE_RESULT as REMOVE_RESULT,
    NODE_SET_RESULT as SET_RESULT,
    invoke_cli,
    sentinel,
)


# Canned node-add result for the --instance mode (issue #399): the op reports
# the instanced scene's res:// path alongside the resolved root type.
ADD_INSTANCE_RESULT = {
    "scene_path": "/tmp/proj/main.tscn",
    "path": "hud",
    "name": "hud",
    "type": "CanvasLayer",
    "script_class": None,
    "instance": "res://hud.tscn",
}


def test_node_add_instance_json_dispatches_instance_param_and_echoes_source(
    monkeypatch,
):
    # Issue #399: `node add --instance` composes an existing .tscn as a child of
    # the host scene — Godot's standard composition primitive. The dispatch
    # carries the instance path instead of a type, the name defaults to the
    # instanced scene's filename stem (model-side, ADR-0015), and the result
    # echoes the instanced res:// path alongside the resolved root type.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "node",
            "add",
            "/tmp/proj/main.tscn",
            "--instance",
            "res://hud.tscn",
            "--json",
        ],
        stdout=sentinel(ADD_INSTANCE_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["scene_path"] == "/tmp/proj/main.tscn"
    # The instanced child is addressable like any added node; its reported type
    # is the instanced scene's ROOT class, resolved by the engine.
    assert (data["path"], data["name"], data["type"]) == ("hud", "hud", "CanvasLayer")
    assert data["instance"] == "res://hud.tscn"
    assert fake.calls == [
        (
            "node-add",
            {
                "path": "/tmp/proj/main.tscn",
                "parent": ".",
                "type": None,
                "instance": "res://hud.tscn",
                "name": "hud",
            },
        )
    ]


def test_node_add_type_and_instance_together_is_a_usage_error(monkeypatch):
    # --type and --instance are mutually exclusive modes (issue #399): mixing
    # them is a usage error (exit 2) that fires before any dispatch — the
    # engine is never reached. The rule lives model-side (ADR-0015), so the
    # --params-json path surfaces the same violation as invalid_params.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "node",
            "add",
            "/tmp/proj/main.tscn",
            "--type",
            "Sprite2D",
            "--instance",
            "res://hud.tscn",
            "--json",
        ],
        stdout=sentinel(ADD_RESULT),
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_node_add_without_type_or_instance_is_a_usage_error(monkeypatch):
    # No mode at all is a usage error too: add always needs exactly one of
    # --type/--instance.
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "add", "/tmp/proj/main.tscn", "--json"],
        stdout=sentinel(ADD_RESULT),
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_node_add_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=sentinel(ADD_RESULT),
        stderr="engine diagnostic\n",
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
                "instance": None,
                "name": "Hero",
            },
        )
    ]
    # Engine/script diagnostics are surfaced on stderr, not stdout.
    assert "engine diagnostic" in result.stderr


def test_node_add_index_dispatches_destination_index(monkeypatch):
    # Issue #415: `--index` is part of the structured authoring request, not
    # prose. The CLI forwards the 0-based insertion index to the operation; the
    # operation owns range validation because the valid upper bound depends on
    # the resolved parent at runtime.
    stdout = sentinel({**ADD_RESULT, "path": "Level", "name": "Level"})
    result, fake = invoke_cli(
        monkeypatch,
        [
            "node",
            "add",
            "/tmp/proj/main.tscn",
            "--type",
            "Label",
            "--name",
            "Level",
            "--index",
            "1",
            "--json",
        ],
        stdout=stdout,
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "node-add",
            {
                "path": "/tmp/proj/main.tscn",
                "parent": ".",
                "type": "Label",
                "instance": None,
                "name": "Level",
                "index": 1,
            },
        )
    ]


def test_node_list_json_emits_node_tree_with_paths_and_exit_zero(monkeypatch):
    # node list is the node-group verifier (issue #53): it reports the scene's
    # tree like scene get, but each node carries its node path — the address an
    # agent feeds back into node add's --parent.
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "list", "/tmp/proj/main.tscn", "--json"],
        stdout=sentinel(LIST_RESULT),
    )

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
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "get", "/tmp/proj/main.tscn", "--node", "Hero", "--json"],
        stdout=sentinel(GET_RESULT),
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=stdout,
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
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "remove", "/tmp/proj/main.tscn", "--node", "Hero", "--json"],
        stdout=sentinel(REMOVE_RESULT),
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
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "duplicate", "/tmp/proj/main.tscn", "--node", "Hero", "--json"],
        stdout=sentinel(DUPLICATE_RESULT),
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=sentinel(MOVE_RESULT),
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


def test_node_move_index_dispatches_destination_index(monkeypatch):
    # Issue #415: `node move --index` requests the moved node's final 0-based
    # sibling position under --to. The operation validates the range after it
    # resolves the source and destination parents.
    result, fake = invoke_cli(
        monkeypatch,
        [
            "node",
            "move",
            "/tmp/proj/main.tscn",
            "--node",
            "Hero",
            "--to",
            "Enemies",
            "--index",
            "1",
            "--json",
        ],
        stdout=sentinel(MOVE_RESULT),
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "node-move",
            {
                "path": "/tmp/proj/main.tscn",
                "node": "Hero",
                "to": "Enemies",
                "index": 1,
            },
        )
    ]


def test_node_add_defaults_parent_to_root_and_name_to_type(monkeypatch):
    # The two ergonomic defaults (issue #53): omitting --parent targets the
    # scene root ('.'), and omitting --name names the node after its type —
    # mirroring how the Godot editor names a freshly added node.
    stdout = sentinel({**ADD_RESULT, "path": "Sprite2D", "name": "Sprite2D"})
    result, fake = invoke_cli(
        monkeypatch,
        ["node", "add", "/tmp/proj/main.tscn", "--type", "Sprite2D", "--json"],
        stdout=stdout,
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "node-add",
            {
                "path": "/tmp/proj/main.tscn",
                "parent": ".",
                "type": "Sprite2D",
                "instance": None,
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=sentinel(CONNECT_RESULT),
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=stdout,
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
    result, fake = invoke_cli(
        monkeypatch,
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
        stdout=sentinel(CONNECT_RESULT),
    )

    assert result.exit_code == 2
    assert fake.calls == []
