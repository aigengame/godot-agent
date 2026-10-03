"""S1 (e2e): assign an EXISTING Resource by res:// path to an Object-typed property.

The Object-assignment slice (issue #363, ADR-0033): ``gda node set`` and ``gda
resource set`` accept a ``res://….tres`` ``--value`` for an Object-typed property
that expects a Resource (sub)class (e.g. ``CollisionShape2D.shape``). The path is
``load()``ed, type-checked against the property's declared class — an engine class
through ``is_class``, a project ``class_name`` through the engine's own typed
member (#1075) — and assigned as an EXTERNAL reference (``ext_resource``) — never
inlined. Combined with
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

import pytest

from tests.support import Gda, import_project


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
    gda = Gda(godot_project)
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
    # The declared Godot type is Object; the set echoes the assigned resource as
    # the ADR-0035 reference projection ({type, resource_path}) — the same shape
    # node get reads back, never an inlined blob.
    assert data["type"] == "Object"
    assert data["value"] == {
        "type": "RectangleShape2D",
        "resource_path": "res://box.tres",
    }

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
    got_data = json.loads(got.stdout)
    assert got_data["type"] == "CollisionShape2D"
    # The read side reports the same ADR-0035 reference projection the set
    # echoed above — one shape for one stored value, whichever way it is read.
    shape = next(p for p in got_data["properties"] if p["name"] == "shape")
    assert shape["value"] == {
        "type": "RectangleShape2D",
        "resource_path": "res://box.tres",
    }


@pytest.mark.e2e
def test_resource_set_object_property_wires_ext_resource(godot_project):
    # The resource-on-resource half (ADR-0033): resource set assigns an existing
    # Gradient to GradientTexture1D.gradient (an engine-class-typed Object property)
    # by res:// path, saved as an ext_resource on the .tres.
    gda = Gda(godot_project)
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
    # The set echo is the ADR-0035 reference projection, matching the get below.
    assert data["value"] == {
        "type": "Gradient",
        "resource_path": "res://grad.tres",
    }

    saved = (godot_project / "tex.tres").read_text(encoding="utf-8")
    assert 'ext_resource type="Gradient" path="res://grad.tres"' in saved
    assert "gradient = ExtResource(" in saved

    # resource get reads the assigned value back as the ADR-0035 reference
    # projection ({type, resource_path}), never an inlined dump.
    got = gda("resource", "get", "res://tex.tres", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    gradient = next(
        p for p in json.loads(got.stdout)["properties"] if p["name"] == "gradient"
    )
    assert gradient["value"] == {
        "type": "Gradient",
        "resource_path": "res://grad.tres",
    }


@pytest.mark.e2e
def test_node_set_object_type_mismatch_yields_resource_type_mismatch(godot_project):
    # A res:// resource whose type is incompatible with the property's expected
    # engine class is a DISTINCT resource_type_mismatch — not uncoercible_value —
    # naming both the actual and the expected class; the scene is left untouched.
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    grad = gda("resource", "create", "res://grad.tres", "--type", "Gradient", "--json")
    assert grad.returncode == 0, grad.stdout + grad.stderr
    before = scene_path.read_text(encoding="utf-8")

    err = gda.error(
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
        code="resource_type_mismatch",
    )
    assert "Gradient" in err["message"]
    assert "Shape2D" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_object_non_res_value_yields_expected_resource_path(godot_project):
    # A non-res:// value for an Object-typed property is a DISTINCT
    # expected_resource_path (a comma-form scalar that would coerce for a Vector2 is
    # NOT accepted here) — not uncoercible_value; the scene is left untouched.
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    before = scene_path.read_text(encoding="utf-8")

    err = gda.error(
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
        code="expected_resource_path",
    )
    assert "res://" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_object_missing_resource_yields_not_a_resource(godot_project):
    # A res:// value that does not load as a Resource (here: no such path) is a
    # DISTINCT not_a_resource — not uncoercible_value; the scene is left untouched.
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    before = scene_path.read_text(encoding="utf-8")

    err = gda.error(
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
        code="not_a_resource",
    )
    assert "res://nope.tres" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_non_resource_file_yields_not_a_resource(godot_project):
    # A res:// path that exists but is NOT a resource (a plain text file) also fails
    # not_a_resource — the failure is "does not load as a Resource", not merely
    # "missing path".
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    (godot_project / "notes.txt").write_text("not a resource\n", encoding="utf-8")
    before = scene_path.read_text(encoding="utf-8")

    err = gda.error(
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
        code="not_a_resource",
    )
    assert "res://notes.txt" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_script_property_yields_use_script_attach(godot_project):
    # The script property is EXCLUDED from the generic Object path and routed to
    # `script attach` (#118) — the one authoritative script-binding path. Setting it
    # returns an ACTIONABLE structured error naming `script attach`, never a second
    # attach entry; the scene is left untouched.
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    (godot_project / "foo.gd").write_text("extends Node2D\n", encoding="utf-8")
    before = scene_path.read_text(encoding="utf-8")

    err = gda.error(
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
        code="use_script_attach",
    )
    assert "script attach" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_value_typed_coercion_is_unchanged(godot_project):
    # Regression: the Object branch must not disturb value-typed coercion — a
    # Vector2 property still coerces from the comma form and round-trips as a JSON
    # number pair (the #55 contract, unchanged by ADR-0033).
    gda = Gda(godot_project)
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


# A component Resource class, a subclass of it, an unrelated Resource class, and a
# node script and a resource script that each export a property typed as the
# component class. The exported `attack: AttackComponent` is an Object-typed
# property whose expected class is a project `class_name`, not an engine class: the
# engine's own typed member decides what it holds (#1075).
ATTACK_COMPONENT_GD = """\
class_name AttackComponent
extends Resource

@export var damage: int = 1
"""

FIRE_ATTACK_GD = """\
class_name FireAttack
extends AttackComponent
"""

LOOT_TABLE_GD = """\
class_name LootTable
extends Resource
"""

ENEMY_GD = """\
class_name Enemy
extends Node2D

@export var attack: AttackComponent
"""

LOADOUT_GD = """\
class_name Loadout
extends Resource

@export var attack: AttackComponent
"""


# A property that names AttackComponent in a RESOURCE_TYPE hint only: a
# _get_property_list entry, stored by _set. The engine checks no type on it, so
# gda cannot delegate the check to the engine's typed member as it does for
# ENEMY_GD's export (the PR #1083 review finding).
HINTED_PROPERTY_GD = """\

var _attack: Resource


func _get_property_list() -> Array[Dictionary]:
	return [{
		"name": "attack",
		"type": TYPE_OBJECT,
		"hint": PROPERTY_HINT_RESOURCE_TYPE,
		"hint_string": "AttackComponent",
		"usage": PROPERTY_USAGE_DEFAULT,
	}]


func _set(property: StringName, value: Variant) -> bool:
	if property == &"attack":
		_attack = value
		return true
	return false


func _get(property: StringName) -> Variant:
	if property == &"attack":
		return _attack
	return null
"""

HINTED_HOLDER_GD = "extends Node2D\n" + HINTED_PROPERTY_GD

HINTED_LOADOUT_GD = "class_name HintedLoadout\nextends Resource\n" + HINTED_PROPERTY_GD


def _component_project(gda, project):
    """The component classes, scanned, and ``res://main.tscn`` with an ``Enemy`` node.

    A script ``class_name`` compiles as a type only after a project scan, so the
    scan runs before any command names or loads one.
    """
    for name, source in {
        "attack_component.gd": ATTACK_COMPONENT_GD,
        "fire_attack.gd": FIRE_ATTACK_GD,
        "loot_table.gd": LOOT_TABLE_GD,
        "enemy.gd": ENEMY_GD,
        "loadout.gd": LOADOUT_GD,
        "hinted_holder.gd": HINTED_HOLDER_GD,
        "hinted_loadout.gd": HINTED_LOADOUT_GD,
    }.items():
        (project / name).write_text(source, encoding="utf-8")
    import_project(project)
    created = gda(
        "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    added = gda(
        "node", "add", "res://main.tscn", "--type", "Enemy", "--name", "Enemy", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr
    return project / "main.tscn"


def _resource_of(gda, path, type_name):
    """Create the ``.tres`` at ``path`` as a ``type_name`` resource."""
    created = gda("resource", "create", path, "--type", type_name, "--json")
    assert created.returncode == 0, created.stdout + created.stderr


def _unsaved_bytes(path):
    """Append a blank line the engine's saver does not write, and return the bytes.

    An engine re-save of an unchanged target writes the same bytes again, so a
    byte-identity check alone cannot tell a refusal that wrote nothing from one
    that re-saved. After this edit, any re-save shows.
    """
    path.write_bytes(path.read_bytes() + b"\n")
    return path.read_bytes()


@pytest.mark.e2e
@pytest.mark.parametrize("type_name", ["AttackComponent", "FireAttack"])
def test_node_set_assigns_a_resource_of_the_class_name_or_a_subclass(
    godot_project, type_name
):
    # A project class_name-typed export takes a resource of that class, or of a
    # subclass, by its res:// path. The set echoes the reference projection, the
    # saved scene holds the resource as an external reference, and node get reads
    # the same projection back (#1075).
    gda = Gda(godot_project)
    scene_path = _component_project(gda, godot_project)
    _resource_of(gda, "res://component.tres", type_name)

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Enemy",
        "--property",
        "attack",
        "--value",
        "res://component.tres",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    data = json.loads(was_set.stdout)
    assert data["type"] == "Object"
    assert data["value"] == {
        "type": "Resource",
        "resource_path": "res://component.tres",
    }
    saved = scene_path.read_text(encoding="utf-8")
    assert 'path="res://component.tres"' in saved
    assert "attack = ExtResource(" in saved
    got = gda("node", "get", "res://main.tscn", "--node", "Enemy", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    attack = next(
        p for p in json.loads(got.stdout)["properties"] if p["name"] == "attack"
    )
    assert attack["value"] == data["value"]


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("type_name", "named"), [("Resource", "Resource"), ("LootTable", "LootTable")]
)
def test_node_set_refuses_a_resource_the_class_name_does_not_accept(
    godot_project, type_name, named
):
    # A plain Resource, and a resource of an unrelated class_name, do not read back
    # from the class_name-typed export: the engine dropped them, so the set is a
    # resource_type_mismatch naming both classes, and the scene file is
    # byte-identical to its state before the call (#1075).
    gda = Gda(godot_project)
    scene_path = _component_project(gda, godot_project)
    _resource_of(gda, "res://other.tres", type_name)
    before = _unsaved_bytes(scene_path)

    err = gda.error(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Enemy",
        "--property",
        "attack",
        "--value",
        "res://other.tres",
        "--json",
        code="resource_type_mismatch",
    )

    assert err["message"] == (
        f"resource res://other.tres is a {named}, incompatible with property attack"
        " on node Enemy (expects AttackComponent)"
    )
    assert scene_path.read_bytes() == before


@pytest.mark.e2e
@pytest.mark.parametrize("type_name", ["AttackComponent", "FireAttack"])
def test_resource_set_assigns_a_resource_of_the_class_name_or_a_subclass(
    godot_project, type_name
):
    # The resource-on-resource counterpart: a .tres whose script exports a
    # class_name-typed property takes a resource of that class, or of a subclass,
    # saved as an ext_resource and read back by resource get (#1075).
    gda = Gda(godot_project)
    _component_project(gda, godot_project)
    _resource_of(gda, "res://loadout.tres", "Loadout")
    _resource_of(gda, "res://component.tres", type_name)

    was_set = gda(
        "resource",
        "set",
        "res://loadout.tres",
        "--property",
        "attack",
        "--value",
        "res://component.tres",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    data = json.loads(was_set.stdout)
    assert data["type"] == "Object"
    assert data["value"] == {
        "type": "Resource",
        "resource_path": "res://component.tres",
    }
    saved = (godot_project / "loadout.tres").read_text(encoding="utf-8")
    assert 'path="res://component.tres"' in saved
    assert "attack = ExtResource(" in saved
    got = gda("resource", "get", "res://loadout.tres", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    attack = next(
        p for p in json.loads(got.stdout)["properties"] if p["name"] == "attack"
    )
    assert attack["value"] == data["value"]


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("type_name", "named"), [("Resource", "Resource"), ("LootTable", "LootTable")]
)
def test_resource_set_refuses_a_resource_the_class_name_does_not_accept(
    godot_project, type_name, named
):
    # The resource set counterpart of the node set refusal: resource_type_mismatch,
    # and the .tres is byte-identical to its state before the call (#1075).
    gda = Gda(godot_project)
    _component_project(gda, godot_project)
    _resource_of(gda, "res://loadout.tres", "Loadout")
    _resource_of(gda, "res://other.tres", type_name)
    loadout = godot_project / "loadout.tres"
    before = _unsaved_bytes(loadout)

    err = gda.error(
        "resource",
        "set",
        "res://loadout.tres",
        "--property",
        "attack",
        "--value",
        "res://other.tres",
        "--json",
        code="resource_type_mismatch",
    )

    assert err["message"] == (
        f"resource res://other.tres is a {named}, incompatible with property attack"
        " on resource res://loadout.tres (expects AttackComponent)"
    )
    assert loadout.read_bytes() == before


# A node script whose `anything` property is a storage property of type Object that
# declares NO class: it comes from _get_property_list with no class_name and no
# hint, so there is nothing to check a Resource against.
CLASSLESS_HOLDER_GD = """\
extends Node2D

var _anything: Object


func _get_property_list() -> Array[Dictionary]:
	return [{"name": "anything", "type": TYPE_OBJECT, "usage": PROPERTY_USAGE_DEFAULT}]


func _set(property: StringName, value: Variant) -> bool:
	if property == &"anything":
		_anything = value
		return true
	return false


func _get(property: StringName) -> Variant:
	if property == &"anything":
		return _anything
	return null
"""


@pytest.mark.e2e
def test_node_set_refuses_an_object_property_that_declares_no_class(godot_project):
    # An Object property with no declared class keeps unsupported_property_type,
    # with a message that states why (no class to check against) and no longer
    # calls the case deferred; the scene file is byte-identical (#1075).
    gda = Gda(godot_project)
    scene_path = _scene_with_collision_shape(gda, godot_project)
    (godot_project / "holder.gd").write_text(CLASSLESS_HOLDER_GD, encoding="utf-8")
    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        "Col",
        "--script",
        "res://holder.gd",
        "--json",
    )
    assert attached.returncode == 0, attached.stdout + attached.stderr
    _box_shape(gda, godot_project)
    before = _unsaved_bytes(scene_path)

    err = gda.error(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Col",
        "--property",
        "anything",
        "--value",
        "res://box.tres",
        "--json",
        code="unsupported_property_type",
    )

    assert err["message"] == (
        "property anything on node Col declares no class, so gda cannot check a"
        " Resource against it"
    )
    assert scene_path.read_bytes() == before


@pytest.mark.e2e
def test_node_set_refuses_a_class_name_named_in_a_hint_only(godot_project):
    # A property that names a project class_name in a RESOURCE_TYPE hint only (a
    # _get_property_list entry stored by _set) is not a typed script member, so
    # the engine checks nothing on set(): the class_name branch's read-back would
    # accept any Resource. gda keeps unsupported_property_type for it, before the
    # load and the save, so the scene file is byte-identical (PR #1083 review).
    gda = Gda(godot_project)
    scene_path = _component_project(gda, godot_project)
    added = gda(
        "node",
        "add",
        "res://main.tscn",
        "--type",
        "Node2D",
        "--name",
        "Holder",
        "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr
    attached = gda(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        "Holder",
        "--script",
        "res://hinted_holder.gd",
        "--json",
    )
    assert attached.returncode == 0, attached.stdout + attached.stderr
    _resource_of(gda, "res://component.tres", "LootTable")
    before = _unsaved_bytes(scene_path)

    err = gda.error(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Holder",
        "--property",
        "attack",
        "--value",
        "res://component.tres",
        "--json",
        code="unsupported_property_type",
    )

    assert err["message"] == (
        "property attack on node Holder names AttackComponent in a hint only, not as"
        " the type of a script member, so the engine does not check a Resource"
        " against it and gda cannot"
    )
    assert scene_path.read_bytes() == before


@pytest.mark.e2e
def test_resource_set_refuses_a_class_name_named_in_a_hint_only(godot_project):
    # The resource-on-resource counterpart of the test above: the same hint-only
    # property on a .tres is refused with unsupported_property_type, and the
    # .tres is byte-identical (PR #1083 review).
    gda = Gda(godot_project)
    _component_project(gda, godot_project)
    _resource_of(gda, "res://hinted.tres", "HintedLoadout")
    _resource_of(gda, "res://component.tres", "LootTable")
    resource_path = godot_project / "hinted.tres"
    before = _unsaved_bytes(resource_path)

    err = gda.error(
        "resource",
        "set",
        "res://hinted.tres",
        "--property",
        "attack",
        "--value",
        "res://component.tres",
        "--json",
        code="unsupported_property_type",
    )

    assert err["message"] == (
        "property attack on resource res://hinted.tres names AttackComponent in a hint"
        " only, not as the type of a script member, so the engine does not check a"
        " Resource against it and gda cannot"
    )
    assert resource_path.read_bytes() == before


ENGINE_TYPED_ENEMY_GD = """\
extends Node2D

@export var attack: Resource
"""


@pytest.mark.e2e
def test_local_to_scene_resource_reads_back_as_the_reference_node_set_echoes(
    godot_project,
):
    # #1074: a resource marked local to scene, assigned to a node the scene file
    # creates, reads back from node get and scene get-exports as the reference
    # projection node set echoes. Both reads instantiate the scene. Without the
    # edit state the engine gave the node a path-less per-instance copy, which
    # projected as the str() fallback.
    gda = Gda(godot_project)
    (godot_project / "enemy.gd").write_text(ENGINE_TYPED_ENEMY_GD, encoding="utf-8")
    for args in (
        ("resource", "create", "res://attack.tres", "--type", "Resource"),
        (
            "resource",
            "set",
            "res://attack.tres",
            "--property",
            "resource_local_to_scene",
            "--value",
            "true",
        ),
        ("scene", "create", "res://main.tscn", "--root-type", "Node2D"),
        ("node", "add", "res://main.tscn", "--type", "Node2D", "--name", "Enemy"),
        (
            "script",
            "attach",
            "res://main.tscn",
            "--node",
            "Enemy",
            "--script",
            "res://enemy.gd",
        ),
    ):
        done = gda(*args, "--json")
        assert done.returncode == 0, done.stdout + done.stderr
    assert "resource_local_to_scene = true" in (
        godot_project / "attack.tres"
    ).read_text(encoding="utf-8")

    was_set = gda(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Enemy",
        "--property",
        "attack",
        "--value",
        "res://attack.tres",
        "--json",
    )
    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    echo = json.loads(was_set.stdout)["value"]
    assert echo == {"type": "Resource", "resource_path": "res://attack.tres"}

    got = gda("node", "get", "res://main.tscn", "--node", "Enemy", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    properties = json.loads(got.stdout)["properties"]
    assert next(p for p in properties if p["name"] == "attack")["value"] == echo

    listed = gda("scene", "get-exports", "res://main.tscn", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    enemy = next(n for n in json.loads(listed.stdout)["nodes"] if n["path"] == "Enemy")
    assert next(e for e in enemy["exports"] if e["name"] == "attack")["value"] == echo
