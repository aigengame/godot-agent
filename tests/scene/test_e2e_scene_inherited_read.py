"""e2e: ``scene get`` and ``node list`` compose an Inherited scene (#1051, ADR-0044).

An Inherited scene's own ``SceneState`` holds only override entries (no type) and
its local nodes. The two static reads compose the base chain without
instantiating anything: the nodes each base declares, base first, then the
scene's own state on top. An override merges into the node it addresses, a local
node is placed by the engine's ``index`` rule, and every non-root inherited node
names the scene that declares it in ``inherited_from``. A ``script run`` oracle
that instantiates the scene is the judge of the composed tree.

The chain is ``Grand.tscn`` (``GA``, ``GB``, ``GC``) ← ``Base.tscn`` (overrides
``GB``, instances ``Hud``, adds ``BaseOnly``) ← ``Derived.tscn`` (a local
``First`` at index 0, an override on ``GA``, a local ``GC/UnderGC``). The files
are hand-written in the shape the engine's saver writes, because an override,
an ``index`` and a missing instance are what the test needs to control.
"""

import json
import shutil

import pytest

from tests.conftest import PROJECT_GODOT
from tests.node.test_e2e_node import _write_instance_fixture
from tests.support import Gda

HUD_TSCN = """\
[gd_scene format=3]

[node name="Hud" type="CanvasLayer"]

[node name="Label" type="Label" parent="."]
"""

GRAND_TSCN = """\
[gd_scene format=3]

[node name="Grand" type="Node2D"]

[node name="GA" type="Sprite2D" parent="."]

[node name="GB" type="Node2D" parent="."]

[node name="GC" type="Area2D" parent="."]
"""

# Base overrides GB, which Grand declares, so GB still reads as Grand's.
BASE_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Grand.tscn" id="1_grand"]
[ext_resource type="PackedScene" path="res://Hud.tscn" id="2_hud"]

[node name="Base" instance=ExtResource("1_grand")]

[node name="GB" parent="." index="1"]
position = Vector2(1, 2)

[node name="Hud" parent="." index="3" instance=ExtResource("2_hud")]

[node name="BaseOnly" type="Node" parent="." index="4"]
"""

DERIVED_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Base.tscn" id="1_base"]

[node name="Derived" instance=ExtResource("1_base")]

[node name="First" type="Node" parent="." index="0"]

[node name="GA" parent="." index="1"]
modulate = Color(1, 0, 0, 1)

[node name="UnderGC" type="Marker2D" parent="GC" index="0"]
"""

# A local node whose index puts it before the last inherited sibling.
MIDDLE_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Grand.tscn" id="1_grand"]

[node name="Middle" instance=ExtResource("1_grand")]

[node name="L" type="Node" parent="." index="2"]
"""

BASE_MISSING_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Gone.tscn" id="1_gone"]

[node name="BaseMissing" type="Node2D"]

[node name="Before" type="Node" parent="."]

[node name="Hud" parent="." instance=ExtResource("1_gone")]
"""

DERIVED_MISSING_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://BaseMissing.tscn" id="1_base"]

[node name="DerivedMissing" instance=ExtResource("1_base")]
"""

# An override written against a Grand node that is no longer there (renamed in
# the base after the override was written), with a local child under it.
RENAMED_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://Grand.tscn" id="1_grand"]

[node name="Renamed" instance=ExtResource("1_grand")]

[node name="Gone" parent="." index="1"]
position = Vector2(5, 5)

[node name="UnderGone" type="Node" parent="Gone"]
"""

ORPHAN_TSCN = """\
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://NoSuchBase.tscn" id="1_base"]

[node name="Orphan" instance=ExtResource("1_base")]
"""

# Prints each scene's runtime tree, depth first in sibling order: the root's
# name and class, then one [path, class, is an instanced child] row per node.
# What the engine BUILDS from the file, not what the file says.
ORACLE_GD = """\
extends SceneTree


func _walk(node: Node, root: Node, out: Array) -> void:
\tfor child in node.get_children():
\t\tout.append([String(root.get_path_to(child)), child.get_class(),
\t\t\t\tnot child.scene_file_path.is_empty()])
\t\t_walk(child, root, out)


func _initialize() -> void:
\tfor scene_path in ["res://Derived.tscn", "res://Middle.tscn"]:
\t\tvar root := (load(scene_path) as PackedScene).instantiate()
\t\tvar rows := []
\t\t_walk(root, root, rows)
\t\tprint("TREE ", scene_path, " ",
\t\t\t\tJSON.stringify([String(root.name), root.get_class(), rows]))
\t\troot.free()
\tquit(0)
"""

FILES = {
    "Hud.tscn": HUD_TSCN,
    "Grand.tscn": GRAND_TSCN,
    "Base.tscn": BASE_TSCN,
    "Derived.tscn": DERIVED_TSCN,
    "Middle.tscn": MIDDLE_TSCN,
    "BaseMissing.tscn": BASE_MISSING_TSCN,
    "DerivedMissing.tscn": DERIVED_MISSING_TSCN,
    "Renamed.tscn": RENAMED_TSCN,
    "Orphan.tscn": ORPHAN_TSCN,
    "oracle.gd": ORACLE_GD,
}


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The chain project, written once and copied per test."""
    project = tmp_path_factory.mktemp("inherited-read-template")
    (project / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    for name, text in FILES.items():
        (project / name).write_text(text, encoding="utf-8")
    return project


@pytest.fixture
def project(_template, tmp_path):
    copy = tmp_path / "project"
    shutil.copytree(_template, copy)
    return copy


def _runtime_trees(gda: Gda) -> dict[str, list]:
    """The oracle's runtime tree per scene: [root name, root class, rows]."""
    ran = gda.json("script", "run", "res://oracle.gd")
    assert ran["exit_status"] == 0, ran
    trees = {}
    for line in ran["stdout"].splitlines():
        if line.startswith("TREE "):
            _, scene_path, tree = line.split(" ", 2)
            trees[scene_path] = json.loads(tree)
    return trees


def _without_instance_internals(rows: list) -> list[list[str]]:
    """The oracle rows minus every node inside an instanced child, as [path, class]."""
    instanced = [path for path, _, is_instance in rows if is_instance]
    return [
        [path, cls]
        for path, cls, _ in rows
        if not any(path.startswith(root + "/") for root in instanced)
    ]


def _flatten(node: dict, prefix: str = "") -> list[list[str]]:
    """A static tree's nodes below ``node``, depth first, as [path, type]."""
    rows = []
    for child in node["children"]:
        path = prefix + child["name"]
        rows.append([path, child["type"]])
        rows.extend(_flatten(child, path + "/"))
    return rows


def _listed_paths(node: dict) -> list[str]:
    """Every ``path`` node list reports below ``node``, depth first."""
    paths = []
    for child in node["children"]:
        paths.append(child["path"])
        paths.extend(_listed_paths(child))
    return paths


def _reads(gda: Gda, scene: str) -> tuple[dict, dict]:
    """The root ``scene get`` and ``node list`` report for ``scene``."""
    return (
        gda.json("scene", "get", scene)["root"],
        gda.json("node", "list", scene)["root"],
    )


def _child(node: dict, name: str) -> dict:
    return next(c for c in node["children"] if c["name"] == name)


@pytest.mark.e2e
def test_the_composed_tree_equals_the_instantiated_tree(project):
    gda = Gda(project)
    root_name, root_class, rows = _runtime_trees(gda)["res://Derived.tscn"]
    expected = _without_instance_internals(rows)
    # The oracle does see the instanced child's internals the reads leave out.
    assert ["Hud/Label", "Label", False] in rows

    scene_root, listed = _reads(gda, "res://Derived.tscn")
    for root in (scene_root, listed):
        assert (root["name"], root["type"]) == (root_name, root_class)
        assert _flatten(root) == expected
        assert _child(root, "Hud")["children"] == []
    assert _listed_paths(listed) == [path for path, _ in expected]


@pytest.mark.e2e
def test_a_local_index_places_the_node_before_an_inherited_sibling(project):
    gda = Gda(project)
    _, _, rows = _runtime_trees(gda)["res://Middle.tscn"]
    assert [path for path, _, _ in rows] == ["GA", "GB", "L", "GC"]

    for root in _reads(gda, "res://Middle.tscn"):
        assert _flatten(root) == _without_instance_internals(rows)


@pytest.mark.e2e
def test_inherited_nodes_name_their_declaring_scene_and_the_base_type(project):
    for root in _reads(Gda(project), "res://Derived.tscn"):
        # The root keeps the #400 instance marker and carries no inherited_from.
        assert "inherited_from" not in root
        assert root["instance_path"] == "res://Base.tscn"
        assert root["instance_status"] == "resolved"
        # GA is overridden here and GB in Base; both are Grand's, with Grand's type.
        assert _child(root, "GA")["type"] == "Sprite2D"
        assert _child(root, "GA")["inherited_from"] == "res://Grand.tscn"
        assert _child(root, "GB")["type"] == "Node2D"
        assert _child(root, "GB")["inherited_from"] == "res://Grand.tscn"
        assert _child(root, "GC")["inherited_from"] == "res://Grand.tscn"
        hud = _child(root, "Hud")
        assert hud["inherited_from"] == "res://Base.tscn"
        assert hud["instance_path"] == "res://Hud.tscn"
        assert hud["instance_status"] == "resolved"
        assert _child(root, "BaseOnly")["inherited_from"] == "res://Base.tscn"
        # Local nodes, including a local child of an inherited node, omit it.
        assert "inherited_from" not in _child(root, "First")
        assert "inherited_from" not in _child(_child(root, "GC"), "UnderGC")


@pytest.mark.e2e
def test_a_missing_instance_in_the_base_reads_missing_through_the_scene(project):
    for root in _reads(Gda(project), "res://DerivedMissing.tscn"):
        assert [c["name"] for c in root["children"]] == ["Before", "Hud"]
        hud = _child(root, "Hud")
        assert hud["instance_path"] == "res://Gone.tscn"
        assert hud["instance_status"] == "missing"


@pytest.mark.e2e
def test_an_override_the_chain_no_longer_holds_is_listed_typeless(project):
    for root in _reads(Gda(project), "res://Renamed.tscn"):
        assert [c["name"] for c in root["children"]] == ["GA", "GB", "GC", "Gone"]
        gone = _child(root, "Gone")
        assert gone["type"] == ""
        assert "inherited_from" not in gone
        assert [(c["name"], c["type"]) for c in gone["children"]] == [
            ("UnderGone", "Node")
        ]


@pytest.mark.e2e
def test_every_listed_path_is_accepted_by_node_set(project):
    gda = Gda(project)
    listed = gda.json("node", "list", "res://Derived.tscn")["root"]
    inherited = _child(listed, "GC")
    local = _child(inherited, "UnderGC")
    assert "inherited_from" in inherited and "inherited_from" not in local

    for node in (inherited, local):
        set_result = gda.json(
            "node",
            "set",
            "res://Derived.tscn",
            "--node",
            node["path"],
            "--property",
            "visible",
            "--value",
            "false",
        )
        assert set_result["path"] == node["path"]


@pytest.mark.e2e
def test_a_missing_base_keeps_not_a_scene_on_both_reads(project):
    gda = Gda(project)
    for command in ("scene get", "node list"):
        gda.error(*command.split(), "res://Orphan.tscn", code="not_a_scene")


# The plain-scene regression: an override on an editable instance's internal
# node, read byte for byte as gda read it before the composition (#1051; pinned
# at dev 2e2f09118, whose projection is the one at ccee96424).
PLAIN_SCENE_GET = (
    '{"path":"res://parent.tscn","root":{"name":"Parent","type":"Node2D",'
    '"children":[{"name":"ChildInstance","type":"Node2D",'
    '"instance_path":"res://child.tscn","instance_status":"resolved",'
    '"children":[{"name":"Inner","type":"","children":['
    '{"name":"Deep","type":"","children":[]},'
    '{"name":"Extra","type":"Marker2D","children":[]}]}]}]}}\n'
)
PLAIN_NODE_LIST = (
    '{"scene_path":"res://parent.tscn","root":{"name":"Parent","type":"Node2D",'
    '"children":[{"name":"ChildInstance","type":"Node2D",'
    '"instance_path":"res://child.tscn","instance_status":"resolved",'
    '"children":[{"name":"Inner","type":"","children":['
    '{"name":"Deep","type":"","children":[],"path":"ChildInstance/Inner/Deep"},'
    '{"name":"Extra","type":"Marker2D","children":[],'
    '"path":"ChildInstance/Inner/Extra"}],"path":"ChildInstance/Inner"}],'
    '"path":"ChildInstance"}],"path":"."}}\n'
)


@pytest.mark.e2e
def test_a_plain_scene_reads_byte_identical(godot_project):
    _write_instance_fixture(godot_project)
    gda = Gda(godot_project)

    got = gda("scene", "get", "res://parent.tscn", "--json")
    listed = gda("node", "list", "res://parent.tscn", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    assert got.stdout == PLAIN_SCENE_GET
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert listed.stdout == PLAIN_NODE_LIST
