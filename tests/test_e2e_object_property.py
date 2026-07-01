"""S1 (e2e): assign an EXISTING Resource by res:// path to an Object-typed property.

The Object-assignment slice (issue #363, ADR-0033): ``gda node set`` and ``gda
resource set`` accept a ``res://….tres`` ``--value`` for an Object-typed property
that expects a Resource (sub)class (e.g. ``CollisionShape2D.shape``). The path is
``load()``ed, type-checked against the property's declared ENGINE class, and
assigned as an EXTERNAL reference (``ext_resource``) — never inlined. Combined with
``resource create`` and ``resource set`` this completes the external sub-resource
workflow with no new command:

    gda resource create res://shapes/box.tres --type RectangleShape2D
    gda resource set    res://shapes/box.tres --property size  --value 32,64
    gda node set res://main.tscn --node Col --property shape --value res://shapes/box.tres

These tests dispatch through the real engine (``operations.gd``), not a stub: the
happy path proves the saved file reloads with the resource wired as an
``ext_resource``, and each failure mode proves a DISTINCT structured code (never
the generic ``uncoercible_value``), leaving the target file untouched.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


def _gda_project(project):
    """A ``gda`` bound to ``--godot`` and ``--project`` so ``res://`` resolves."""

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _import_project(project) -> None:
    """Run a one-shot headless import so the project's class_name list is written.

    A script ``class_name`` only registers in
    ``.godot/global_script_class_list.cfg`` after a project scan — the realistic
    precondition for resolving ``Player`` / ``PlayerConfig`` by class_name
    (mirrors the node/resource class_name e2e tests).
    """
    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


def _scene_with_collision_shape(gda, project):
    """A scene ``res://main.tscn`` whose root has a ``CollisionShape2D`` 'Col'.

    ``Col.shape`` is an engine-class-typed Object property (expects ``Shape2D``) —
    the canonical target for the Object-assignment slice.
    """
    created = gda(
        "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    added = gda(
        "node",
        "add",
        "res://main.tscn",
        "--type",
        "CollisionShape2D",
        "--name",
        "Col",
        "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr
    return project / "main.tscn"


def _box_shape(gda, project):
    """A ``res://box.tres`` RectangleShape2D (a Shape2D) with a set size."""
    created = gda(
        "resource", "create", "res://box.tres", "--type", "RectangleShape2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    was_set = gda(
        "resource",
        "set",
        "res://box.tres",
        "--property",
        "size",
        "--value",
        "32,64",
        "--json",
    )
    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    return project / "box.tres"


@pytest.mark.e2e
def test_node_set_object_property_wires_ext_resource_end_to_end(godot_project):
    # The core acceptance criterion (ADR-0033): the full create → set → node set
    # workflow wires CollisionShape2D.shape to an existing RectangleShape2D by its
    # res:// path, and the saved scene reloads with the resource attached as an
    # EXTERNAL reference (ext_resource), never inlined.
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    _box_shape(gda, godot_project)

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "shape",
        "--value",
        "res://box.tres",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    data = json.loads(was_set.stdout)
    assert data["property"] == "shape"
    # The declared Godot type is Object; the assigned value round-trips as the
    # res:// reference (not an inlined blob).
    assert data["type"] == "Object"
    assert data["value"] == "res://box.tres"

    # The mutation is on disk as an EXTERNAL reference: an [ext_resource ...] entry
    # for the .tres and a `shape = ExtResource(...)` binding — not an inlined
    # [sub_resource].
    saved = scene_path.read_text(encoding="utf-8")
    assert 'ext_resource type="Shape2D" path="res://box.tres"' in saved
    assert "shape = ExtResource(" in saved
    assert "[sub_resource" not in saved

    # The saved scene reloads cleanly (the ext_resource resolves), so node get sees
    # the addressed node again — proving the wiring is not a torn file.
    got = gda("node", "get", "res://main.tscn", "--node", "Col", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["type"] == "CollisionShape2D"


@pytest.mark.e2e
def test_resource_set_object_property_wires_ext_resource(godot_project):
    # The resource-on-resource half (ADR-0033): resource set assigns an existing
    # Gradient to GradientTexture1D.gradient (an engine-class-typed Object property)
    # by res:// path, saved as an ext_resource on the .tres.
    gda = _gda_project(godot_project)
    tex = gda(
        "resource", "create", "res://tex.tres", "--type", "GradientTexture1D", "--json"
    )
    assert tex.returncode == 0, tex.stdout + tex.stderr
    grad = gda("resource", "create", "res://grad.tres", "--type", "Gradient", "--json")
    assert grad.returncode == 0, grad.stdout + grad.stderr

    was_set = gda(
        "resource",
        "set",
        "res://tex.tres",
        "--property",
        "gradient",
        "--value",
        "res://grad.tres",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    data = json.loads(was_set.stdout)
    assert data["property"] == "gradient"
    assert data["type"] == "Object"
    assert data["value"] == "res://grad.tres"

    saved = (godot_project / "tex.tres").read_text(encoding="utf-8")
    assert 'ext_resource type="Gradient" path="res://grad.tres"' in saved
    assert "gradient = ExtResource(" in saved


@pytest.mark.e2e
def test_node_set_object_type_mismatch_yields_resource_type_mismatch(godot_project):
    # A res:// resource whose type is incompatible with the property's expected
    # engine class is a DISTINCT resource_type_mismatch — not uncoercible_value —
    # naming both the actual and the expected class; the scene is left untouched.
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    grad = gda("resource", "create", "res://grad.tres", "--type", "Gradient", "--json")
    assert grad.returncode == 0, grad.stdout + grad.stderr
    before = scene_path.read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "shape",
        "--value",
        "res://grad.tres",
        "--json",
    )

    err = _assert_operation_error(was_set, "resource_type_mismatch")
    assert "Gradient" in err["message"]
    assert "Shape2D" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_object_non_res_value_yields_expected_resource_path(godot_project):
    # A non-res:// value for an Object-typed property is a DISTINCT
    # expected_resource_path (a comma-form scalar that would coerce for a Vector2 is
    # NOT accepted here) — not uncoercible_value; the scene is left untouched.
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    before = scene_path.read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "shape",
        "--value",
        "32,64",
        "--json",
    )

    err = _assert_operation_error(was_set, "expected_resource_path")
    assert "res://" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_object_missing_resource_yields_not_a_resource(godot_project):
    # A res:// value that does not load as a Resource (here: no such path) is a
    # DISTINCT not_a_resource — not uncoercible_value; the scene is left untouched.
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    before = scene_path.read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "shape",
        "--value",
        "res://nope.tres",
        "--json",
    )

    err = _assert_operation_error(was_set, "not_a_resource")
    assert "res://nope.tres" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_non_resource_file_yields_not_a_resource(godot_project):
    # A res:// path that exists but is NOT a resource (a plain text file) also fails
    # not_a_resource — the failure is "does not load as a Resource", not merely
    # "missing path".
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    (godot_project / "notes.txt").write_text("not a resource\n", encoding="utf-8")
    before = scene_path.read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "shape",
        "--value",
        "res://notes.txt",
        "--json",
    )

    err = _assert_operation_error(was_set, "not_a_resource")
    assert "res://notes.txt" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_script_property_yields_use_script_attach(godot_project):
    # The script property is EXCLUDED from the generic Object path and routed to
    # `script attach` (#118) — the one authoritative script-binding path. Setting it
    # returns an ACTIONABLE structured error naming `script attach`, never a second
    # attach entry; the scene is left untouched.
    gda = _gda_project(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    (godot_project / "foo.gd").write_text("extends Node2D\n", encoding="utf-8")
    before = scene_path.read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "script",
        "--value",
        "res://foo.gd",
        "--json",
    )

    err = _assert_operation_error(was_set, "use_script_attach")
    assert "script attach" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_value_typed_coercion_is_unchanged(godot_project):
    # Regression: the Object branch must not disturb value-typed coercion — a
    # Vector2 property still coerces from the comma form and round-trips as a JSON
    # number pair (the #55 contract, unchanged by ADR-0033).
    gda = _gda_project(godot_project)
    _scene_with_collision_shape(gda, godot_project)

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "position",
        "--value",
        "3,4",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    data = json.loads(was_set.stdout)
    assert data["type"] == "Vector2"
    assert data["value"] == [3.0, 4.0]


# A script-defined custom Resource, and a node script that exports a property
# typed as that script `class_name`. The exported `config: PlayerConfig` is an
# Object-typed property whose expected class is a SCRIPT class_name — not an
# engine class — which ADR-0033 defers.
PLAYER_CONFIG_GD = """\
class_name PlayerConfig
extends Resource

@export var hp: int = 5
"""

PLAYER_GD = """\
class_name Player
extends Node2D

@export var config: PlayerConfig
"""


@pytest.mark.e2e
def test_node_set_script_class_name_typed_property_is_deferred(godot_project):
    # ADR-0033 DEFERS script-class_name-typed Object properties (their validation
    # will reuse ADR-0032's class_name resolver): only ENGINE-class-typed Object
    # properties are in scope this slice. A node whose script exports a
    # script-class_name-typed Object property (config: PlayerConfig) refuses a
    # res:// assignment with the DISTINCT, public unsupported_property_type code —
    # never a misleading resource_type_mismatch — naming the class and the deferral,
    # and leaves the scene untouched. Pins the deferred branch as a checked-in
    # contract (the code is public ABI), dispatching through operations.gd.
    gda = _gda_project(godot_project)
    (godot_project / "player_config.gd").write_text(PLAYER_CONFIG_GD, encoding="utf-8")
    (godot_project / "player.gd").write_text(PLAYER_GD, encoding="utf-8")
    _import_project(godot_project)

    created = gda(
        "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    # Add the scripted node by its class_name so it carries the config export.
    added = gda(
        "node",
        "add",
        "res://main.tscn",
        "--type",
        "Player",
        "--name",
        "Player",
        "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr
    cfg = gda(
        "resource", "create", "res://cfg.tres", "--type", "PlayerConfig", "--json"
    )
    assert cfg.returncode == 0, cfg.stdout + cfg.stderr
    before = (godot_project / "main.tscn").read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Player",
        "--property",
        "config",
        "--value",
        "res://cfg.tres",
        "--json",
    )

    err = _assert_operation_error(was_set, "unsupported_property_type")
    assert "PlayerConfig" in err["message"]
    assert (godot_project / "main.tscn").read_text(encoding="utf-8") == before
