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

requires_godot = pytest.mark.skipif(
    not GODOT.exists(), reason=f"real Godot binary not found at {GODOT}"
)


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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
def test_node_add_to_missing_scene_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    added = _gda("node", "add", str(missing), "--type", "Sprite2D", "--json")

    err = _assert_operation_error(added, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
@requires_godot
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


@pytest.mark.e2e
@requires_godot
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
@requires_godot
def test_node_add_unknown_type_yields_invalid_node_type(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)
    before = scene_path.read_text(encoding="utf-8")

    added = _gda("node", "add", str(scene_path), "--type", "NotAClass", "--json")

    err = _assert_operation_error(added, "invalid_node_type")
    assert "NotAClass" in err["message"]
    assert scene_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
@requires_godot
def test_node_add_rejects_name_godot_would_rewrite(godot_project):
    scene_path = godot_project / "main.tscn"
    _create_scene(scene_path)

    added = _gda(
        "node", "add", str(scene_path),
        "--type", "Sprite2D", "--name", "Bad%Name", "--json",
    )

    err = _assert_operation_error(added, "invalid_node_name")
    assert "Bad%Name" in err["message"]


@pytest.mark.e2e
@requires_godot
def test_node_list_missing_scene_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    listed = _gda("node", "list", str(missing), "--json")

    err = _assert_operation_error(listed, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
@requires_godot
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


def _write_instance_fixture(project, child: str = "child.tscn"):
    """Write parent.tscn instancing ``res://<child>`` with editable overrides."""
    (project / "child.tscn").write_text(CHILD_TSCN, encoding="utf-8")
    parent = project / "parent.tscn"
    parent.write_text(PARENT_TSCN.format(child=child), encoding="utf-8")
    return parent


@pytest.mark.e2e
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
