"""S1 (e2e): gda scene get-exports against the real Godot engine (issue #58).

``gda scene get-exports`` loads a scene, instantiates it, and reports — per node
(by node path) — the ``@export`` properties its attached script declares: name,
declared Godot type, hint/hint_string, and current (default) value as typed
JSON. It reuses ``node get``'s property-value introspection, so an export's
value reads exactly as ``node get`` would report it.

The scene is built end-to-end with the real CLI: ``scene create`` →
``script create`` (a ``.gd`` with ``@export`` vars) → ``script attach`` →
``scene get-exports``. Auto-skipped when no engine resolves (conftest gate).
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


def _gda(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


# A script declaring a representative @export surface: a typed scalar with a
# default, a string, a packed Vector2, and a hinted range — plus one PLAIN
# (non-exported) var that must NOT appear in the exports listing.
EXPORTING_SCRIPT = """\
extends Node2D

@export var speed: float = 3.5
@export var title: String = "Hello"
@export var start: Vector2 = Vector2(1, 2)
@export_range(0, 100) var max_hp: int = 100

var not_exported: int = 7
"""


def _build_scene_with_exports(project) -> "tuple":
    """scene create → script create (exports) → script attach to the root."""
    scene_path = project / "main.tscn"
    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    script_path = project / "actor.gd"
    script_path.write_text(EXPORTING_SCRIPT, encoding="utf-8")

    attached = _gda(
        "script",
        "attach",
        str(scene_path),
        "--node",
        ".",
        "--script",
        str(script_path),
        "--project",
        str(project),
        "--json",
    )
    assert attached.returncode == 0, attached.stdout + attached.stderr
    return scene_path, script_path


@pytest.mark.e2e
def test_scene_get_exports_reports_declared_exports_per_node(godot_project):
    # The core of issue #58: get-exports loads the scene and reports the @export
    # properties the root node's attached script declares — each with its name,
    # declared Godot type, hint/hint_string, and value (its default here), as
    # typed JSON. A plain (non-@export) var is NOT reported.
    scene_path, _ = _build_scene_with_exports(godot_project)

    got = _gda(
        "scene",
        "get-exports",
        str(scene_path),
        "--project",
        str(godot_project),
        "--json",
    )

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["path"] == str(scene_path)
    # The root node, addressed as '.', carries the exports its script declares.
    nodes = {n["path"]: n for n in data["nodes"]}
    assert "." in nodes
    root = nodes["."]
    assert root["type"] == "Node2D"
    exports = {e["name"]: e for e in root["exports"]}

    # Each declared @export appears with its declared Godot type and default
    # value in the same JSON projection node get uses.
    assert exports["speed"]["type"] == "float"
    assert exports["speed"]["value"] == 3.5
    assert exports["title"]["type"] == "String"
    assert exports["title"]["value"] == "Hello"
    assert exports["start"]["type"] == "Vector2"
    assert exports["start"]["value"] == [1.0, 2.0]
    # The hinted range carries its PropertyHint and companion hint_string.
    assert exports["max_hp"]["type"] == "int"
    assert exports["max_hp"]["value"] == 100
    assert exports["max_hp"]["hint"] != 0
    assert "100" in exports["max_hp"]["hint_string"]

    # A plain (non-exported) var is excluded — get-exports reports the @export
    # surface, not the script's whole property list.
    assert "not_exported" not in exports


@pytest.mark.e2e
def test_scene_get_exports_omits_nodes_without_declared_exports(godot_project):
    # A node whose script declares no @export, or that carries no script, does
    # not appear: get-exports lists only nodes that actually declare exports. A
    # bare scene (no scripts anywhere) is a valid, empty listing.
    scene_path = godot_project / "bare.tscn"
    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    got = _gda(
        "scene",
        "get-exports",
        str(scene_path),
        "--project",
        str(godot_project),
        "--json",
    )

    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["nodes"] == []


@pytest.mark.e2e
def test_scene_get_exports_reports_nested_node_by_path(godot_project):
    # Exports are reported per node by node path: a script attached to a NESTED
    # node is reported under that node's canonical path ('Child'), the same
    # addressing node get / node set use, so an agent can read/set the export
    # afterwards. The root here carries no script, so only the child is listed —
    # which also pins that a scriptless node is omitted.
    scene_path = godot_project / "main.tscn"
    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    script_path = godot_project / "actor.gd"
    script_path.write_text(EXPORTING_SCRIPT, encoding="utf-8")

    added = _gda(
        "node",
        "add",
        str(scene_path),
        "--type",
        "Node2D",
        "--name",
        "Child",
        "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr
    attached = _gda(
        "script",
        "attach",
        str(scene_path),
        "--node",
        "Child",
        "--script",
        str(script_path),
        "--project",
        str(godot_project),
        "--json",
    )
    assert attached.returncode == 0, attached.stdout + attached.stderr

    got = _gda(
        "scene",
        "get-exports",
        str(scene_path),
        "--project",
        str(godot_project),
        "--json",
    )

    assert got.returncode == 0, got.stdout + got.stderr
    nodes = {n["path"]: n for n in json.loads(got.stdout)["nodes"]}
    # The nested node is addressed by its canonical node path.
    assert "Child" in nodes
    assert {e["name"] for e in nodes["Child"]["exports"]} >= {"speed", "max_hp"}
    # The scriptless root is omitted: only export-declaring nodes are listed.
    assert "." not in nodes


@pytest.mark.e2e
def test_scene_get_exports_missing_file_yields_path_not_found(godot_project):
    got = _gda(
        "scene",
        "get-exports",
        str(godot_project / "nope.tscn"),
        "--project",
        str(godot_project),
        "--json",
    )

    err = _assert_operation_error(got, "path_not_found")
    assert "nope.tscn" in err["message"]


@pytest.mark.e2e
def test_scene_get_exports_non_scene_file_yields_not_a_scene(godot_project):
    # A file that exists but does not load as a PackedScene is refused with the
    # shared not_a_scene code, exactly like scene get / delete.
    notes = godot_project / "notes.txt"
    notes.write_text("not a scene\n", encoding="utf-8")

    got = _gda(
        "scene",
        "get-exports",
        str(notes),
        "--project",
        str(godot_project),
        "--json",
    )

    _assert_operation_error(got, "not_a_scene")
