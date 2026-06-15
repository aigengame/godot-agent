"""S1 (e2e): the node add → list round-trip against the real Godot engine.

The node-group tracer (issue #53): ``gda node add`` loads a ``.tscn``, adds a
child under a parent node path, packs and saves; ``gda node list`` reads the
tree back with per-node paths — ``node list`` IS the structured-level
verification of ``node add``'s effect.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


def _gda(*args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


def _create_scene(scene_path) -> None:
    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr


@pytest.mark.e2e
def test_node_add_then_list_round_trip(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Hero", "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    # The created node's address: its node path relative to the scene root.
    assert data["scene_path"] == str(scene_path)
    assert data["path"] == "Hero"
    assert data["name"] == "Hero"
    assert data["type"] == "Sprite2D"

    listed = _gda("node", "list", str(scene_path), "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    tree = json.loads(listed.stdout)
    # Round-trip: the saved scene file declares the added node — the mutation
    # is on disk, not just in the reporting process.
    root = tree["root"]
    assert (root["name"], root["type"], root["path"]) == ("main", "Node2D", ".")
    hero = root["children"][0]
    assert (hero["name"], hero["type"], hero["path"]) == ("Hero", "Sprite2D", "Hero")
    assert hero["children"] == []


@pytest.mark.e2e
def test_node_add_under_nested_parent_path(godot_project):
    # Node-path addressing end-to-end (issue #53): the path node list reports
    # for a node ("Hero") is exactly the address node add accepts as --parent,
    # and the second mutation must preserve the first (existing children
    # survive the load → mutate → pack → save round-trip).
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    first = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Hero", "--json",
    )
    assert first.returncode == 0, first.stdout + first.stderr

    second = _gda(
        "node", "add", str(scene_path),
        "--type", "Area2D", "--name", "Hitbox", "--parent", "Hero", "--json",
    )

    assert second.returncode == 0, second.stdout + second.stderr
    data = json.loads(second.stdout)
    assert data["path"] == "Hero/Hitbox"
    assert data["type"] == "Area2D"

    listed = _gda("node", "list", str(scene_path), "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    hero = json.loads(listed.stdout)["root"]["children"][0]
    assert hero["path"] == "Hero"
    assert hero["children"][0]["path"] == "Hero/Hitbox"
    assert hero["children"][0]["type"] == "Area2D"


@pytest.mark.e2e
def test_node_add_default_name_is_the_type_name(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda("node", "add", str(scene_path), "--type", "Sprite2D", "--json")

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert data["name"] == "Sprite2D"
    assert data["path"] == "Sprite2D"


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.mark.e2e
def test_node_add_to_missing_scene_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    added = _gda("node", "add", str(missing), "--type", "Sprite2D", "--json")

    err = _assert_operation_error(added, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_node_add_bad_parent_yields_parent_not_found_and_leaves_file_unchanged(
    godot_project,
):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--parent", "Bogus/Path", "--json",
    )

    err = _assert_operation_error(added, "parent_not_found")
    assert "Bogus/Path" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


def _scene_with_nested_children(godot_project):
    """A scene whose root has child A and grandchild A/B — the fixture tree
    the parent-path addressing tests resolve against."""
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    for name, parent in (("A", "."), ("B", "A")):
        added = _gda(
            "node", "add", str(scene_path),
            "--type", "Node2D", "--name", name, "--parent", parent, "--json",
        )
        assert added.returncode == 0, added.stdout + added.stderr
    return scene_path


@pytest.mark.e2e
@pytest.mark.parametrize("form", ["..", "../A", "/root/A"])
def test_node_add_parent_path_escaping_or_absolute_stays_rejected(
    godot_project, form
):
    # Regression pins for issue #66: these forms were already rejected on main
    # before the strictness change — absolute paths by _resolve_parent's
    # explicit check, and leading ".." because a scene loaded for editing has
    # no parent above its root to escape to. Pinned so the canonical-form
    # tightening can never regress them into resolving.
    scene_path = _scene_with_nested_children(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Marker2D", "--name", "M", "--parent", form, "--json",
    )

    err = _assert_operation_error(added, "parent_not_found")
    assert form in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
@pytest.mark.parametrize(
    "form", ["A/..", "A/", "A/B/", "A//B", "./A", "A/./B", "A:position"]
)
def test_node_add_rejects_non_canonical_parent_path(godot_project, form):
    # Issue #66: node-path addressing is exact — a parent path must be the
    # canonical root-relative form node list reports ('.' or 'Name/Name').
    # Godot's NodePath resolution would happily accept these forms and land
    # the node somewhere other than what the literal string implies (e.g.
    # "A/.." resolved to the ROOT on 4.6.3), so they must be rejected with
    # parent_not_found and the scene file left untouched — never silently
    # normalized into a placement the agent did not ask for.
    scene_path = _scene_with_nested_children(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Marker2D", "--name", "M", "--parent", form, "--json",
    )

    err = _assert_operation_error(added, "parent_not_found")
    assert form in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_add_explicit_dot_parent_addresses_the_root(godot_project):
    # The canonical root address: '.' must keep working verbatim — it is the
    # form node list reports for the root, and the CLI's --parent default.
    scene_path = _scene_with_nested_children(godot_project)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Marker2D", "--name", "M", "--parent", ".", "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout)["path"] == "M"


@pytest.mark.e2e
def test_node_add_name_collision_yields_duplicate_node_name(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    first = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Hero", "--json",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = scene_path.read_text(encoding="utf-8")

    again = _gda(
        "node", "add", str(scene_path),
        "--type", "Area2D", "--name", "Hero", "--json",
    )

    err = _assert_operation_error(again, "duplicate_node_name")
    assert "Hero" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_add_collision_with_internal_child_yields_duplicate_node_name(
    godot_project,
):
    # Issue #65's internal-child mode, pinned as a regression test: some node
    # classes construct INTERNAL children in their constructor (ScrollContainer
    # builds scrollbars named "_h_scroll"/"_v_scroll"), which never appear in
    # the scene file or node list. A name collision with one must still be the
    # accurate duplicate_node_name — not invalid_node_name ("Godot rewrote
    # name") and never a silent engine rename saved into the file. Verified
    # correct on Godot 4.6.3: get_node_or_null resolves through the engine's
    # child-name map, which includes internal children.
    scene_path = godot_project / "ui.tscn"
    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Control", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    added = _gda(
        "node", "add", str(scene_path),
        "--type", "ScrollContainer", "--name", "Scroll", "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr
    before = scene_path.read_text(encoding="utf-8")

    colliding = _gda(
        "node", "add", str(scene_path),
        "--type", "Control", "--name", "_h_scroll", "--parent", "Scroll", "--json",
    )

    err = _assert_operation_error(colliding, "duplicate_node_name")
    assert "_h_scroll" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_add_unknown_type_yields_invalid_node_type(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda("node", "add", str(scene_path), "--type", "NotAClass", "--json")

    err = _assert_operation_error(added, "invalid_node_type")
    assert "NotAClass" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_add_rejects_name_godot_would_rewrite(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Bad%Name", "--json",
    )

    err = _assert_operation_error(added, "invalid_node_name")
    assert "Bad%Name" in err["message"]


# --- node get / node set (issue #55) ---


def _get_property(scene_path, node: str, name: str):
    """Read one property dict (by name) off a node via `gda node get --json`."""
    got = _gda("node", "get", str(scene_path), "--node", node, "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    for prop in json.loads(got.stdout)["properties"]:
        if prop["name"] == name:
            return prop
    return None


@pytest.mark.e2e
def test_node_get_reports_typed_properties(godot_project):
    # node get is the read half of issue #55: it loads a scene and reports the
    # addressed node's storage properties as typed JSON — each with its name,
    # declared Godot type, and value in the JSON projection.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Hero", "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr

    got = _gda("node", "get", str(scene_path), "--node", "Hero", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert (data["path"], data["name"], data["type"]) == ("Hero", "Hero", "Sprite2D")
    by_name = {p["name"]: p for p in data["properties"]}
    # A representative scalar, packed, and bool property carry their declared
    # Godot type and a JSON-projected value.
    assert by_name["position"]["type"] == "Vector2"
    assert by_name["position"]["value"] == [0.0, 0.0]
    assert by_name["visible"] == {"name": "visible", "type": "bool", "value": True}
    assert by_name["z_index"]["type"] == "int"


@pytest.mark.e2e
def test_node_get_addresses_the_root_with_dot(godot_project):
    # The canonical root address works for get too: '.' is the root itself,
    # exactly as node list reports it and node add's --parent default.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    got = _gda("node", "get", str(scene_path), "--node", ".", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert (data["path"], data["name"], data["type"]) == (".", "main", "Node2D")


@pytest.mark.e2e
def test_node_get_missing_node_yields_node_not_found(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    got = _gda("node", "get", str(scene_path), "--node", "Bogus", "--json")

    err = _assert_operation_error(got, "node_not_found")
    assert "Bogus" in err["message"]


@pytest.mark.e2e
@pytest.mark.parametrize(
    "prop,value,want_type,want_value",
    [
        ("position", "3,4", "Vector2", [3.0, 4.0]),
        ("z_index", "7", "int", 7),
        ("rotation", "1.5", "float", 1.5),
        ("visible", "false", "bool", False),
        ("modulate", "1,0,0,1", "Color", [1.0, 0.0, 0.0, 1.0]),
        ("modulate", "#ff0000ff", "Color", [1.0, 0.0, 0.0, 1.0]),
    ],
)
def test_node_set_coerces_and_round_trips_via_get(
    godot_project, prop, value, want_type, want_value
):
    # The core of issue #55: node set coerces the CLI string to the property's
    # declared Godot type, saves, and the change round-trips via node get —
    # the acceptance criterion "set is verifiable via get", across the coercion
    # rules documented in the command catalog.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Sprite2D", "--name", "Hero", "--json")

    was_set = _gda(
        "node", "set", str(scene_path),
        "--node", "Hero", "--property", prop, "--value", value, "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_data = json.loads(was_set.stdout)
    assert (set_data["property"], set_data["type"]) == (prop, want_type)
    assert set_data["value"] == want_value
    # The change is on disk, verified through a fresh get.
    assert _get_property(scene_path, "Hero", prop)["value"] == want_value


@pytest.mark.e2e
def test_node_set_unknown_property_yields_unknown_property_and_leaves_file_unchanged(
    godot_project,
):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Sprite2D", "--name", "Hero", "--json")
    before = scene_path.read_text(encoding="utf-8")

    was_set = _gda(
        "node", "set", str(scene_path),
        "--node", "Hero", "--property", "no_such_prop", "--value", "1", "--json",
    )

    err = _assert_operation_error(was_set, "unknown_property")
    assert "no_such_prop" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_uncoercible_value_yields_uncoercible_value_and_leaves_file_unchanged(
    godot_project,
):
    # The type-coercion contract's failure path: a value that cannot become the
    # property's declared type is a clean error, not a silent wrong value, and
    # the scene file is left untouched.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Sprite2D", "--name", "Hero", "--json")
    before = scene_path.read_text(encoding="utf-8")

    was_set = _gda(
        "node", "set", str(scene_path),
        "--node", "Hero", "--property", "position", "--value", "not_a_vector", "--json",
    )

    err = _assert_operation_error(was_set, "uncoercible_value")
    assert "Vector2" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_missing_node_yields_node_not_found(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    was_set = _gda(
        "node", "set", str(scene_path),
        "--node", "Bogus", "--property", "position", "--value", "1,2", "--json",
    )

    err = _assert_operation_error(was_set, "node_not_found")
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_set_refuses_scene_whose_sub_scene_cannot_resolve(godot_project):
    # node set is the second mutating op (issue #55), so it must honor the same
    # mutation-integrity boundary as node add (issue #64): when an instanced
    # sub-scene cannot resolve on load, set refuses with missing_dependency and
    # leaves the file byte-identical rather than dropping the instance on save.
    parent = _write_instance_fixture(godot_project, child="gone.tscn")
    (godot_project / "gone.tscn").unlink(missing_ok=True)
    before = parent.read_text(encoding="utf-8")

    was_set = _gda(
        "node", "set", str(parent),
        "--node", ".", "--property", "position", "--value", "1,2",
        "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(was_set, "missing_dependency")
    assert "ChildInstance" in err["message"]
    assert parent.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_list_missing_scene_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    listed = _gda("node", "list", str(missing), "--json")

    err = _assert_operation_error(listed, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_node_list_non_scene_file_yields_not_a_scene(godot_project):
    notes = godot_project / "notes.txt"
    notes.write_text("not a scene\n", encoding="utf-8")

    listed = _gda("node", "list", str(notes), "--json")

    _assert_operation_error(listed, "not_a_scene")


# A legal editable-children fixture, in the engine's own serialization (issue
# #64): the parent scene instances child.tscn, overrides nodes inside the
# instance (keyed by node path), adds a node under the editable instance, and
# carries the `[editable path=...]` marker the editor writes.
CHILD_TSCN = """\
[gd_scene format=3]

[node name="Child" type="Node2D"]

[node name="Inner" type="Sprite2D" parent="."]

[node name="Deep" type="Node2D" parent="Inner"]
"""

PARENT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://{child}" id="1_child"]

[node name="Parent" type="Node2D"]

[node name="ChildInstance" parent="." instance=ExtResource("1_child")]
position = Vector2(10, 20)

[node name="Inner" parent="ChildInstance" index="0"]
modulate = Color(1, 0, 0, 1)

[node name="Deep" parent="ChildInstance/Inner" index="0"]
position = Vector2(3, 4)

[node name="Extra" type="Marker2D" parent="ChildInstance/Inner"]

[editable path="ChildInstance"]
"""


def _write_instance_fixture(
    project, child: str = "child.tscn", child_content: str = CHILD_TSCN
):
    """Write parent.tscn instancing ``res://<child>`` with editable overrides."""
    (project / "child.tscn").write_text(child_content, encoding="utf-8")
    parent = project / "parent.tscn"
    parent.write_text(PARENT_TSCN.format(child=child), encoding="utf-8")
    return parent


@pytest.mark.e2e
def test_node_add_preserves_editable_instance_overrides(godot_project):
    # Issue #64's data-integrity contract, pinned as a regression test: the
    # load → instantiate → edit → pack → save round-trip must keep every kind
    # of instance state the editor writes — the instance reference itself, the
    # `[editable ...]` marker, property overrides on the instance node and on
    # nodes inside it (node-path-keyed, at any depth), and nodes added under
    # the editable instance. Verified to hold on Godot 4.6.3.
    parent = _write_instance_fixture(godot_project)

    added = _gda(
        "node", "add", str(parent),
        "--type", "Marker2D", "--name", "M",
        "--project", str(godot_project), "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout)["path"] == "M"
    saved = parent.read_text(encoding="utf-8")
    # The sub-scene is still an instance, not a flattened copy.
    assert 'instance=ExtResource(' in saved
    assert '[editable path="ChildInstance"]' in saved
    # Top-level instance property override.
    assert "position = Vector2(10, 20)" in saved
    # Overrides on nodes INSIDE the instance, keyed by node path.
    assert '[node name="Inner" parent="ChildInstance"' in saved
    assert "modulate = Color(1, 0, 0, 1)" in saved
    assert '[node name="Deep" parent="ChildInstance/Inner"' in saved
    assert "position = Vector2(3, 4)" in saved
    # A node added under the editable instance.
    assert '[node name="Extra" type="Marker2D" parent="ChildInstance/Inner"' in saved
    # And the node this command added.
    assert '[node name="M" type="Marker2D" parent="."' in saved


@pytest.mark.e2e
def test_node_add_without_project_context_refuses_rather_than_drops_instances(
    godot_project,
):
    # The same vanish mode from the common invocation mistake: without
    # --project, res:// ext_resources cannot resolve, so the instance would
    # vanish from the re-saved file even though every scene file exists.
    parent = _write_instance_fixture(godot_project)
    before = parent.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(parent), "--type", "Marker2D", "--name", "M", "--json"
    )

    err = _assert_operation_error(added, "missing_dependency")
    assert "ChildInstance" in err["message"]
    assert parent.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_add_refuses_scene_whose_sub_scene_cannot_resolve(godot_project):
    # The real data-loss mode of issue #64: when an instanced sub-scene cannot
    # be resolved on load (broken dependency), instantiate drops the whole
    # instance — and a re-save would silently erase the instance, its
    # overrides, and its editable marker from the file. node add must refuse
    # with a structured error and leave the file byte-identical instead.
    parent = _write_instance_fixture(godot_project, child="gone.tscn")
    (godot_project / "gone.tscn").unlink(missing_ok=True)
    before = parent.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(parent),
        "--type", "Marker2D", "--name", "M",
        "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "missing_dependency")
    assert "ChildInstance" in err["message"]
    assert parent.read_text(encoding="utf-8") == before


# A child that loads as a valid PackedScene resource but cannot instantiate:
# its root illegally declares a parent, which SceneState::instantiate refuses
# with an engine null. The nested null propagates (packed_scene.cpp fails the
# instanced node with nullptr), so the PARENT scene's own top-level
# instantiate() also returns null — there is no tree to diff, edit, or save.
UNINSTANTIABLE_CHILD_TSCN = """\
[gd_scene format=3]

[node name="Child" type="Node2D" parent="."]
"""


@pytest.mark.e2e
def test_node_add_refuses_scene_that_instantiates_to_null(godot_project):
    # The nested-null mode of issue #64: the sub-scene resource loads fine but
    # instantiates to nothing, and the parent scene's instantiate() returns
    # null. node add must refuse with the structured missing_dependency
    # envelope — not dereference the null and surface as the unstructured
    # operation_failed classification.
    parent = _write_instance_fixture(
        godot_project, child_content=UNINSTANTIABLE_CHILD_TSCN
    )
    before = parent.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(parent),
        "--type", "Marker2D", "--name", "M",
        "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "missing_dependency")
    assert str(parent) in err["message"]
    assert parent.read_text(encoding="utf-8") == before


# A scene declaring a node class that does not exist in a stock 4.6.3 headless
# engine — the shape of an absent GDExtension/module class.
MISSING_CLASS_TSCN = """\
[gd_scene format=3]

[node name="Root" type="Node2D"]

[node name="Widget" type="TotallyMissingClass" parent="."]
"""


@pytest.mark.e2e
def test_node_add_refuses_scene_whose_declared_class_is_substituted(godot_project):
    # The degraded-node mode of issue #64: when a declared class is unavailable
    # at instantiate time, the engine warns and substitutes a placeholder node
    # at the same path (observed on 4.6.3 headless: a plain Node), so an
    # existence check alone passes — but a re-save would rewrite the node as
    # the substitute type, silently dropping its declared class. node add must
    # refuse, naming declared vs materialized class, and leave the file alone.
    scene_path = godot_project / "widget.tscn"
    scene_path.write_text(MISSING_CLASS_TSCN, encoding="utf-8")
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Marker2D", "--name", "M", "--json",
    )

    err = _assert_operation_error(added, "missing_dependency")
    assert "Widget (declared TotallyMissingClass, materialized" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


HERO_GD = """\
class_name Hero
extends Node2D
"""


def _import_project(project) -> None:
    # class_name registration lives in .godot/global_script_class_list.cfg,
    # which only a project scan produces — run the engine's headless import
    # step the way a CI pipeline would before using script classes.
    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr


@pytest.mark.e2e
def test_node_add_by_class_name_attaches_the_script(godot_project):
    # The second half of --type's contract (issue #53): a class_name registered
    # in the project's global class list resolves like a built-in type. The
    # created node reports its engine class as type and the class_name as
    # script_class, so an agent can assert the script attach without reading
    # the .tscn.
    (godot_project / "hero.gd").write_text(HERO_GD, encoding="utf-8")
    _import_project(godot_project)
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Hero", "--project", str(godot_project), "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert data["name"] == "Hero"
    assert data["path"] == "Hero"
    assert data["type"] == "Node2D"
    assert data["script_class"] == "Hero"

    listed = _gda("node", "list", str(scene_path), "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    hero = json.loads(listed.stdout)["root"]["children"][0]
    # The .tscn stores a scripted node under its engine class; the script ref
    # itself is in the saved file.
    assert (hero["name"], hero["type"]) == ("Hero", "Node2D")
    assert "hero.gd" in scene_path.read_text(encoding="utf-8")


@pytest.mark.e2e
def test_node_add_by_unregistered_class_name_yields_invalid_node_type(godot_project):
    # Without a project import there is no global class list: the class_name
    # cannot resolve, and the failure must be the structured invalid_node_type,
    # not a crash or a silent plain-Node fallback.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Hero", "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "invalid_node_type")
    assert "Hero" in err["message"]


# The same class_name, broken AFTER registration: a parse error the import-time
# scan never saw, so the stale global class list still maps Hero to this script.
BROKEN_HERO_GD = """\
class_name Hero
extends Node2D
func broken( -> void:
"""


@pytest.mark.e2e
def test_node_add_by_registered_but_broken_class_name_names_the_script(godot_project):
    # Issue #65's broken-class_name mode: the class_name IS in the global class
    # list (the import scanned a then-valid script), but the script on disk has
    # since broken. Reporting invalid_node_type ("not a registered class_name")
    # misdiagnoses a script problem as an unknown type — the agent fix is to
    # repair the script, not the type name. The failure must surface as the
    # distinct uninstantiable_script code naming the script, with the scene
    # file left unchanged.
    (godot_project / "hero.gd").write_text(HERO_GD, encoding="utf-8")
    _import_project(godot_project)
    (godot_project / "hero.gd").write_text(BROKEN_HERO_GD, encoding="utf-8")
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Hero", "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "uninstantiable_script")
    assert "Hero" in err["message"]
    assert "hero.gd" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


# A perfectly healthy class_name that just is not a node: instantiable, but
# never addable to a scene tree.
LOOT_GD = """\
class_name Loot
extends Resource
"""


@pytest.mark.e2e
def test_node_add_by_non_node_class_name_yields_invalid_node_type(godot_project):
    # The boundary of issue #65's distinction: a registered class_name whose
    # script is fine but not Node-derived is a true type error — it stays
    # invalid_node_type (not uninstantiable_script), with a message naming the
    # script and the real cause rather than "not a registered class_name".
    (godot_project / "loot.gd").write_text(LOOT_GD, encoding="utf-8")
    _import_project(godot_project)
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Loot", "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "invalid_node_type")
    assert "Loot" in err["message"]
    assert "not a Node-derived script" in err["message"]
    assert "loot.gd" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


# A class_name that compiles and registers fine but cannot be constructed
# without arguments: script.new() has no args to give _init.
NEEDS_ARGS_HERO_GD = """\
class_name Hero
extends Node2D


func _init(speed: float) -> void:
\tpass
"""


@pytest.mark.e2e
def test_node_add_by_class_name_whose_init_requires_args_names_the_constructor(
    godot_project,
):
    # The other half of issue #65's broken-class_name mode: the script is
    # valid and registered, but its _init requires constructor args, so
    # script.new() cannot construct it. Same misdiagnosis risk as the broken
    # script: the type IS registered, the constructor is the problem.
    (godot_project / "hero.gd").write_text(NEEDS_ARGS_HERO_GD, encoding="utf-8")
    _import_project(godot_project)
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Hero", "--project", str(godot_project), "--json",
    )

    err = _assert_operation_error(added, "uninstantiable_script")
    assert "Hero" in err["message"]
    assert "hero.gd" in err["message"]
    assert "_init" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


# --- node remove (issue #56) ---


@pytest.mark.e2e
def test_node_remove_deletes_node_and_subtree_round_trip(godot_project):
    # node remove is the first structural edit (issue #56): it deletes a node
    # and its whole subtree, verified through a fresh node list — the deletion
    # is on disk, not just in the reporting process. A sibling is untouched.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "C", "--json")

    removed = _gda("node", "remove", str(scene_path), "--node", "A", "--json")

    assert removed.returncode == 0, removed.stdout + removed.stderr
    data = json.loads(removed.stdout)
    assert (data["path"], data["name"], data["type"]) == ("A", "A", "Node2D")

    listed = _gda("node", "list", str(scene_path), "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    children = json.loads(listed.stdout)["root"]["children"]
    names = {child["name"] for child in children}
    # A (and its child B) are gone; the sibling C survives.
    assert names == {"C"}


@pytest.mark.e2e
def test_node_remove_nested_node_leaves_ancestors(godot_project):
    # Removing a descendant deletes only its subtree; its parent survives.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B

    removed = _gda("node", "remove", str(scene_path), "--node", "A/B", "--json")

    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout)["path"] == "A/B"

    listed = _gda("node", "list", str(scene_path), "--json")
    a = json.loads(listed.stdout)["root"]["children"][0]
    assert a["name"] == "A"
    assert a["children"] == []


@pytest.mark.e2e
def test_node_remove_missing_node_yields_node_not_found(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    removed = _gda("node", "remove", str(scene_path), "--node", "Bogus", "--json")

    err = _assert_operation_error(removed, "node_not_found")
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


# --- node connect-signal / disconnect-signal (issue #57) ---


def _scene_with_emitter_and_receiver(godot_project):
    """A scene whose root has a Timer 'Emitter' and a Node2D 'Receiver' — the
    fixture the signal-wiring tests connect across."""
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    for node_type, name in (("Timer", "Emitter"), ("Node2D", "Receiver")):
        added = _gda(
            "node", "add", str(scene_path),
            "--type", node_type, "--name", name, "--json",
        )
        assert added.returncode == 0, added.stdout + added.stderr
    return scene_path


def _connection_lines(scene_path) -> list[str]:
    """The [connection ...] lines a saved scene file declares (the persisted wiring)."""
    return [
        line
        for line in scene_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("[connection")
    ]


@pytest.mark.e2e
def test_node_connect_signal_records_a_connection_that_round_trips(godot_project):
    # The core of issue #57: connect-signal wires a source node's signal to a
    # target node's method, persisted as a [connection] in the .tscn — the
    # mutation is on disk (a re-read shows it), not just in the reporting process.
    scene_path = _scene_with_emitter_and_receiver(godot_project)

    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    assert connected.returncode == 0, connected.stdout + connected.stderr
    data = json.loads(connected.stdout)
    assert data["scene_path"] == str(scene_path)
    assert (data["from"], data["signal"]) == ("Emitter", "timeout")
    assert (data["to"], data["method"]) == ("Receiver", "on_timeout")
    # Round-trip: the saved file declares the connection.
    lines = _connection_lines(scene_path)
    assert lines == [
        '[connection signal="timeout" from="Emitter" to="Receiver" method="on_timeout"]'
    ]


@pytest.mark.e2e
def test_node_connect_signal_allows_a_not_yet_defined_target_method(godot_project):
    # issue #57's design decision: the target METHOD need not exist at connect
    # time — a .tscn [connection] is persisted data, and Godot's own editor lets
    # you wire a signal to a not-yet-written method, so the handler can be
    # authored afterward. The connection is recorded with the dangling method.
    scene_path = _scene_with_emitter_and_receiver(godot_project)

    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "not_yet_written", "--json",
    )

    assert connected.returncode == 0, connected.stdout + connected.stderr
    assert json.loads(connected.stdout)["method"] == "not_yet_written"
    assert _connection_lines(scene_path) == [
        '[connection signal="timeout" from="Emitter" to="Receiver" method="not_yet_written"]'
    ]


@pytest.mark.e2e
def test_node_connect_signal_unknown_signal_yields_signal_not_found(godot_project):
    # The SIGNAL must exist on the source node (the other half of the design
    # decision): a typo'd or absent signal is a clean signal_not_found, and the
    # scene file is left untouched.
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "no_such_signal",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(connected, "signal_not_found")
    assert "no_such_signal" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_connect_signal_already_connected_yields_already_connected(godot_project):
    # Wiring the same signal->method twice is a clean already_connected error
    # rather than a noisy engine failure or a silent re-apply; the file is
    # unchanged after the second attempt.
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    first = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = scene_path.read_text(encoding="utf-8")

    again = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(again, "already_connected")
    assert "Receiver.on_timeout" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_connect_signal_missing_source_node_yields_node_not_found(godot_project):
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Bogus", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(connected, "node_not_found")
    assert "source" in err["message"]
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_remove_root_yields_cannot_target_root(godot_project):
    # Removing the scene root has no defined meaning — the root has no parent to
    # be detached from, and a re-pack needs a root. node remove refuses with the
    # registered cannot_target_root code and leaves the file untouched, rather
    # than emptying the scene.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    removed = _gda("node", "remove", str(scene_path), "--node", ".", "--json")

    err = _assert_operation_error(removed, "cannot_target_root")
    assert scene_path.read_text(encoding="utf-8") == before


# --- node duplicate (issue #56) ---


@pytest.mark.e2e
def test_node_duplicate_copies_node_under_same_parent_with_fresh_name(godot_project):
    # node duplicate (issue #56): the copy lands under the source node's OWN
    # parent (a sibling) with a fresh, non-colliding name, and the new node path
    # is reported — verified through a fresh node list. The source survives.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Sprite2D", "--name", "Hero", "--json")

    duplicated = _gda("node", "duplicate", str(scene_path), "--node", "Hero", "--json")

    assert duplicated.returncode == 0, duplicated.stdout + duplicated.stderr
    data = json.loads(duplicated.stdout)
    assert data["source_path"] == "Hero"
    assert data["type"] == "Sprite2D"
    # The fresh name is non-colliding and the new node path is a root-relative
    # sibling of the source.
    assert data["name"] != "Hero"
    assert "/" not in data["path"]
    assert data["path"] == data["name"]

    listed = _gda("node", "list", str(scene_path), "--json")
    children = json.loads(listed.stdout)["root"]["children"]
    names = sorted(child["name"] for child in children)
    # Both the source and its fresh-named copy are present as siblings.
    assert "Hero" in names
    assert data["name"] in names
    assert len(names) == 2


@pytest.mark.e2e
def test_node_duplicate_copies_the_whole_subtree(godot_project):
    # Duplicate copies the node AND its subtree: the source has a child, and the
    # copy must carry an equivalent child under the new node path.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "Hero", "--json")
    _gda(
        "node", "add", str(scene_path),
        "--type", "Area2D", "--name", "Hitbox", "--parent", "Hero", "--json",
    )

    duplicated = _gda("node", "duplicate", str(scene_path), "--node", "Hero", "--json")
    assert duplicated.returncode == 0, duplicated.stdout + duplicated.stderr
    new_name = json.loads(duplicated.stdout)["name"]

    listed = _gda("node", "list", str(scene_path), "--json")
    by_name = {c["name"]: c for c in json.loads(listed.stdout)["root"]["children"]}
    copy = by_name[new_name]
    # The copied subtree carries the child, re-pathed under the new parent.
    assert copy["children"][0]["name"] == "Hitbox"
    assert copy["children"][0]["type"] == "Area2D"
    assert copy["children"][0]["path"] == f"{new_name}/Hitbox"


@pytest.mark.e2e
def test_node_duplicate_nested_node_lands_under_its_own_parent(godot_project):
    # A nested source is duplicated under ITS parent, not the scene root: the new
    # node path shares the source's parent prefix.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B

    duplicated = _gda("node", "duplicate", str(scene_path), "--node", "A/B", "--json")

    assert duplicated.returncode == 0, duplicated.stdout + duplicated.stderr
    data = json.loads(duplicated.stdout)
    assert data["source_path"] == "A/B"
    # The copy is a sibling of B, under A.
    assert data["path"].startswith("A/")
    assert data["path"] != "A/B"


@pytest.mark.e2e
def test_node_duplicate_missing_node_yields_node_not_found(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    duplicated = _gda("node", "duplicate", str(scene_path), "--node", "Bogus", "--json")

    err = _assert_operation_error(duplicated, "node_not_found")
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_duplicate_root_yields_cannot_target_root(godot_project):
    # The scene root has no parent to host a sibling copy, so duplicating '.' is
    # refused with cannot_target_root and the file is left untouched.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    duplicated = _gda("node", "duplicate", str(scene_path), "--node", ".", "--json")

    _assert_operation_error(duplicated, "cannot_target_root")
    assert scene_path.read_text(encoding="utf-8") == before


# --- node move (issue #56) ---


@pytest.mark.e2e
def test_node_move_reparents_node_and_subtree_round_trip(godot_project):
    # node move (issue #56) reparents a node and its whole subtree under a new
    # parent, returning the node's new node path — verified through a fresh node
    # list: the moved node now sits under the target, carrying its child.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "Hero", "--json")
    _gda(
        "node", "add", str(scene_path),
        "--type", "Area2D", "--name", "Hitbox", "--parent", "Hero", "--json",
    )
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "Enemies", "--json")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "Hero", "--to", "Enemies", "--json"
    )

    assert moved.returncode == 0, moved.stdout + moved.stderr
    data = json.loads(moved.stdout)
    assert data["source_path"] == "Hero"
    assert data["new_parent"] == "Enemies"
    assert data["path"] == "Enemies/Hero"

    listed = _gda("node", "list", str(scene_path), "--json")
    by_name = {c["name"]: c for c in json.loads(listed.stdout)["root"]["children"]}
    # Hero is no longer a direct child of the root; it sits under Enemies, with
    # its subtree intact.
    assert "Hero" not in by_name
    enemies = by_name["Enemies"]
    hero = enemies["children"][0]
    assert hero["name"] == "Hero"
    assert hero["path"] == "Enemies/Hero"
    assert hero["children"][0]["name"] == "Hitbox"


@pytest.mark.e2e
def test_node_move_to_root_reparents_under_the_root(godot_project):
    # The target may be the root itself ('.'): a deeply nested node can be moved
    # up to be a direct child of the scene root.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B

    moved = _gda(
        "node", "move", str(scene_path), "--node", "A/B", "--to", ".", "--json"
    )

    assert moved.returncode == 0, moved.stdout + moved.stderr
    data = json.loads(moved.stdout)
    assert data["new_parent"] == "."
    assert data["path"] == "B"

    listed = _gda("node", "list", str(scene_path), "--json")
    names = {c["name"] for c in json.loads(listed.stdout)["root"]["children"]}
    assert names == {"A", "B"}


@pytest.mark.e2e
def test_node_move_under_own_descendant_yields_cyclic_target(godot_project):
    # The cyclic case (issue #56): moving a node under one of its own
    # descendants would detach the whole subtree from the scene. It is refused
    # with the registered cyclic_target code, leaving the file untouched.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "A", "--to", "A/B", "--json"
    )

    err = _assert_operation_error(moved, "cyclic_target")
    assert "A/B" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_under_itself_yields_cyclic_target(godot_project):
    # Moving a node under itself is the degenerate cyclic case — the node cannot
    # be its own parent.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "A", "--to", "A", "--json"
    )

    _assert_operation_error(moved, "cyclic_target")
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_to_missing_parent_yields_parent_not_found(godot_project):
    # An invalid target (no such parent node) reuses the node group's
    # parent_not_found code, the same as node add's --parent.
    scene_path = _scene_with_nested_children(godot_project)  # root -> A -> B
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "A/B", "--to", "Bogus", "--json"
    )

    err = _assert_operation_error(moved, "parent_not_found")
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_name_collision_at_destination_yields_duplicate_node_name(
    godot_project,
):
    # The target already has a child with the moved node's name: reparenting
    # would collide, so it is refused with duplicate_node_name (the same code
    # node add reports), leaving the file untouched.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "Hero", "--json")
    _gda("node", "add", str(scene_path), "--type", "Node2D", "--name", "Enemies", "--json")
    _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Hero", "--parent", "Enemies", "--json",
    )
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "Hero", "--to", "Enemies", "--json"
    )

    err = _assert_operation_error(moved, "duplicate_node_name")
    assert "Hero" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_connect_signal_missing_target_node_yields_node_not_found(godot_project):
    scene_path = _scene_with_emitter_and_receiver(godot_project)

    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Bogus", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(connected, "node_not_found")
    assert "target" in err["message"]
    assert "Bogus" in err["message"]


@pytest.mark.e2e
def test_node_disconnect_signal_removes_an_existing_connection(godot_project):
    # disconnect-signal removes a connection connect-signal recorded; the round-
    # trip read shows the [connection] is gone from the saved file.
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    connected = _gda(
        "node", "connect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )
    assert connected.returncode == 0, connected.stdout + connected.stderr
    assert _connection_lines(scene_path)  # the connection is there first

    disconnected = _gda(
        "node", "disconnect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    assert disconnected.returncode == 0, disconnected.stdout + disconnected.stderr
    data = json.loads(disconnected.stdout)
    assert (data["from"], data["to"]) == ("Emitter", "Receiver")
    # Round-trip: the connection is gone from the saved file.
    assert _connection_lines(scene_path) == []


@pytest.mark.e2e
def test_node_disconnect_signal_absent_connection_yields_connection_not_found(
    godot_project,
):
    # Disconnecting a connection that does not exist is a clean
    # connection_not_found error, not a silent success; the file is untouched.
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    disconnected = _gda(
        "node", "disconnect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(disconnected, "connection_not_found")
    assert "Emitter.timeout" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_missing_node_yields_node_not_found(godot_project):
    scene_path = _scene_with_nested_children(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", "Bogus", "--to", ".", "--json"
    )

    err = _assert_operation_error(moved, "node_not_found")
    assert "Bogus" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_disconnect_signal_missing_signal_yields_signal_not_found(godot_project):
    # A missing/typo'd source signal is signal_not_found on disconnect too —
    # symmetric with connect-signal and the documented contract, not collapsed
    # into connection_not_found (issue #57 review). The file is untouched.
    scene_path = _scene_with_emitter_and_receiver(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    disconnected = _gda(
        "node", "disconnect-signal", str(scene_path),
        "--from", "Emitter", "--signal", "no_such_signal",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(disconnected, "signal_not_found")
    assert "no_such_signal" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_root_yields_cannot_target_root(godot_project):
    # The scene root has no parent to be reparented out of, so moving '.' is
    # refused with cannot_target_root and the file is left untouched.
    scene_path = _scene_with_nested_children(godot_project)
    before = scene_path.read_text(encoding="utf-8")

    moved = _gda(
        "node", "move", str(scene_path), "--node", ".", "--to", "A", "--json"
    )

    _assert_operation_error(moved, "cannot_target_root")
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_node_move_to_current_parent_is_a_noop_preserving_sibling_order(godot_project):
    # Moving a node to the parent it already sits under is a no-op (issue #56
    # review): sibling order is meaningful in Godot, so re-homing the node under
    # the same parent must not detach-and-reappend it (which would shuffle it to
    # the end, [A, B, C] -> [B, C, A]). The order is read back off a fresh node
    # list, so it reflects what was saved to disk, not just the reporting process.
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    for name in ("A", "B", "C"):
        added = _gda(
            "node", "add", str(scene_path), "--type", "Node2D", "--name", name, "--json"
        )
        assert added.returncode == 0, added.stdout + added.stderr

    moved = _gda("node", "move", str(scene_path), "--node", "A", "--to", ".", "--json")

    assert moved.returncode == 0, moved.stdout + moved.stderr
    data = json.loads(moved.stdout)
    # The node is reported at its (unchanged) home.
    assert data["new_parent"] == "."
    assert data["path"] == "A"

    listed = _gda("node", "list", str(scene_path), "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    order = [c["name"] for c in json.loads(listed.stdout)["root"]["children"]]
    # Sibling order is preserved: A was not shuffled to the end.
    assert order == ["A", "B", "C"]


@pytest.mark.e2e
def test_node_move_preserves_editable_instance_overrides(godot_project):
    # Moving an instanced sub-scene must keep its instance inheritance intact
    # (issue #56 review, the #64 mutation-integrity boundary): the reparent must
    # not rewrite the editable instance's inherited/override children into
    # locally-owned `type=` nodes, which would break instance inheritance. The
    # whole sub-scene — its `instance=ExtResource(...)`, its `[editable ...]`
    # marker, and its override nodes (Inner/Deep) — survives the move as-is.
    # Verified empirically against Godot 4.6.3.
    parent = _write_instance_fixture(godot_project)
    # A destination parent to reparent the instance under.
    added = _gda(
        "node", "add", str(parent),
        "--type", "Node2D", "--name", "Dest",
        "--project", str(godot_project), "--json",
    )
    assert added.returncode == 0, added.stdout + added.stderr

    moved = _gda(
        "node", "move", str(parent),
        "--node", "ChildInstance", "--to", "Dest",
        "--project", str(godot_project), "--json",
    )

    assert moved.returncode == 0, moved.stdout + moved.stderr
    assert json.loads(moved.stdout)["path"] == "Dest/ChildInstance"
    saved = parent.read_text(encoding="utf-8")
    # The sub-scene is still an instance under its new parent, not a flattened copy.
    assert 'instance=ExtResource(' in saved
    assert '[editable path="Dest/ChildInstance"]' in saved
    # The override nodes inside the instance keep their override form (parent +
    # index, NO type=) rather than being rewritten as local typed nodes.
    assert '[node name="Inner" parent="Dest/ChildInstance" index=' in saved
    assert '[node name="Deep" parent="Dest/ChildInstance/Inner" index=' in saved
    assert 'name="Inner" type=' not in saved
    assert 'name="Deep" type=' not in saved
    # The property overrides survive the move.
    assert "position = Vector2(10, 20)" in saved
    assert "modulate = Color(1, 0, 0, 1)" in saved
    assert "position = Vector2(3, 4)" in saved


@pytest.mark.e2e
def test_node_connect_signal_to_missing_scene_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    connected = _gda(
        "node", "connect-signal", str(missing),
        "--from", "Emitter", "--signal", "timeout",
        "--to", "Receiver", "--method", "on_timeout", "--json",
    )

    err = _assert_operation_error(connected, "path_not_found")
    assert str(missing) in err["message"]
