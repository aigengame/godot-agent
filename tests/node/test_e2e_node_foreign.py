"""e2e: node remove / node move refuse a Foreign node (#1049, ADR-0044).

A foreign node is one the scene does not declare: a node a scene in the base
chain of an Inherited scene declares, or a node inside an instanced child. The
scene file has no entry that removes, reparents or reorders such a node, so both
commands refuse it with ``cannot_target_foreign`` and leave the file
byte-identical. Local nodes stay removable, reorderable and reparentable, to and
from an inherited parent; a ``script run`` oracle reads what the engine builds.

The fixtures are the ADR-0044 reproductions (Godot 4.6.3): ``BaseEnemy.tscn`` a
scripted ``CharacterBody2D`` with ``Sprite``, ``Shape`` and ``Hitbox``;
``Goblin.tscn`` the three-line inherited header, then an override on ``Sprite``,
a local ``GoblinOnly`` and a local ``Shape/UnderShape``, written through the
engine; ``Host.tscn`` a plain scene with ``Hud`` instanced from the base.
"""

import json
import shutil

import pytest

from tests.conftest import PROJECT_GODOT
from tests.support import Gda


def _inherited_header(root_name: str, base: str) -> str:
    """The inherited-scene text the engine's saver writes (ADR-0044, Context)."""
    return (
        "[gd_scene format=3]\n\n"
        f'[ext_resource type="PackedScene" path="{base}" id="1_base"]\n\n'
        f'[node name="{root_name}" instance=ExtResource("1_base")]\n'
    )


# Prints each scene's runtime tree, depth first in sibling order, as one line per
# scene: what the engine BUILDS from the file, not what the file says.
ORACLE_GD = """\
extends SceneTree


func _walk(node: Node, root: Node, out: Array) -> void:
\tfor child in node.get_children():
\t\tout.append(String(root.get_path_to(child)))
\t\t_walk(child, root, out)


func _initialize() -> void:
\tfor scene_path in ["res://Goblin.tscn", "res://Host.tscn"]:
\t\tvar root := (load(scene_path) as PackedScene).instantiate()
\t\tvar paths := []
\t\t_walk(root, root, paths)
\t\tprint("TREE ", scene_path, " ", JSON.stringify(paths))
\t\troot.free()
\tquit(0)
"""


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The reproduction project, built once through gda and copied per test."""
    project = tmp_path_factory.mktemp("foreign-node-template")
    (project / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    gda = Gda(project)
    gda.json(
        "scene", "create", "res://BaseEnemy.tscn", "--root-type", "CharacterBody2D"
    )
    for name, node_type in (
        ("Sprite", "Sprite2D"),
        ("Shape", "CollisionShape2D"),
        ("Hitbox", "Area2D"),
    ):
        gda.json(
            "node", "add", "res://BaseEnemy.tscn", "--type", node_type, "--name", name
        )
    gda.json("script", "create", "res://base_enemy.gd", "--extends", "CharacterBody2D")
    gda.json(
        "script",
        "attach",
        "res://BaseEnemy.tscn",
        "--node",
        ".",
        "--script",
        "res://base_enemy.gd",
    )

    (project / "Goblin.tscn").write_text(
        _inherited_header("Goblin", "res://BaseEnemy.tscn"), encoding="utf-8"
    )
    gda.json(
        "node",
        "set",
        "res://Goblin.tscn",
        "--node",
        "Sprite",
        "--property",
        "modulate",
        "--value",
        "#ff0000",
    )
    gda.json(
        "node", "add", "res://Goblin.tscn", "--type", "Node2D", "--name", "GoblinOnly"
    )
    gda.json(
        "node",
        "add",
        "res://Goblin.tscn",
        "--parent",
        "Shape",
        "--type",
        "Node2D",
        "--name",
        "UnderShape",
    )

    gda.json("scene", "create", "res://Host.tscn", "--root-type", "Node2D")
    gda.json(
        "node",
        "add",
        "res://Host.tscn",
        "--instance",
        "res://BaseEnemy.tscn",
        "--name",
        "Hud",
    )
    (project / "oracle.gd").write_text(ORACLE_GD, encoding="utf-8")
    return project


@pytest.fixture
def project(_template, tmp_path):
    copy = tmp_path / "project"
    shutil.copytree(_template, copy)
    return copy


def _runtime_trees(gda: Gda) -> dict[str, list[str]]:
    """The oracle's runtime tree per scene: node paths, depth first."""
    ran = gda.json("script", "run", "res://oracle.gd")
    assert ran["exit_status"] == 0, ran
    trees = {}
    for line in ran["stdout"].splitlines():
        if line.startswith("TREE "):
            _, scene_path, paths = line.split(" ", 2)
            trees[scene_path] = json.loads(paths)
    return trees


def _refused(gda: Gda, scene, *argv: str) -> str:
    """Run a node command that must be refused as foreign; return its message.

    Asserts the ADR-0002 operation envelope (exit 4, ``cannot_target_foreign``)
    and that the scene file is byte-identical afterwards.
    """
    before = scene.read_bytes()
    err = gda.error(*argv, code="cannot_target_foreign")
    assert scene.read_bytes() == before
    return err["message"]


# --- the four reproductions (ADR-0044, Context items 1-2) ---


@pytest.mark.e2e
def test_node_remove_of_an_inherited_node_is_refused(project):
    # Reproduction 1: the base declares Shape, so the file has no entry that can
    # delete it. Before #1049 this reported success, rewrote GoblinOnly's index and
    # dropped the local Shape/UnderShape entry while Shape stayed.
    message = _refused(
        Gda(project),
        project / "Goblin.tscn",
        "node",
        "remove",
        "res://Goblin.tscn",
        "--node",
        "Shape",
    )

    assert message == (
        "cannot remove Shape: the node is declared by res://BaseEnemy.tscn, which"
        " this scene inherits — edit that scene, or override its properties here"
    )


@pytest.mark.e2e
def test_node_move_of_an_inherited_node_to_a_local_parent_is_refused(project):
    # Reproduction 2: before #1049 the move forked Sprite into a second, local,
    # typed node under GoblinOnly and dropped the root-level override entry.
    message = _refused(
        Gda(project),
        project / "Goblin.tscn",
        "node",
        "move",
        "res://Goblin.tscn",
        "--node",
        "Sprite",
        "--to",
        "GoblinOnly",
    )

    assert message.startswith("cannot move Sprite: ")
    assert "res://BaseEnemy.tscn" in message


@pytest.mark.e2e
@pytest.mark.parametrize(
    "index",
    [
        # Reproduction 3: before #1049 only a sibling override's index was
        # rewritten, and the runtime order did not change.
        ["--index", "0"],
        # The same-parent form without --index was a successful no-op; it is
        # refused too, so the answer does not depend on the flag (ADR-0044).
        [],
    ],
    ids=["with-index", "without-index"],
)
def test_node_move_of_an_inherited_node_under_its_own_parent_is_refused(project, index):
    message = _refused(
        Gda(project),
        project / "Goblin.tscn",
        "node",
        "move",
        "res://Goblin.tscn",
        "--node",
        "Shape",
        "--to",
        ".",
        *index,
    )

    assert message.startswith("cannot move Shape: ")
    assert "res://BaseEnemy.tscn" in message


@pytest.mark.e2e
def test_node_remove_of_a_node_inside_an_instanced_child_is_refused(project):
    # Reproduction 4: Hud/Sprite belongs to the scene Hud instances. Before #1049
    # this reported success with an unchanged file.
    message = _refused(
        Gda(project),
        project / "Host.tscn",
        "node",
        "remove",
        "res://Host.tscn",
        "--node",
        "Hud/Sprite",
    )

    assert message == (
        "cannot remove Hud/Sprite: the node is inside res://BaseEnemy.tscn,"
        " instanced at Hud — edit that scene"
    )


@pytest.mark.e2e
def test_an_editable_instanced_child_does_not_open_structural_edits(project):
    # The editor refuses whether or not the instanced child is editable, and so
    # does gda: [editable] changes which overrides the file can hold, not what
    # it can delete or place.
    host = project / "Host.tscn"
    host.write_text(
        host.read_text(encoding="utf-8") + '\n[editable path="Hud"]\n',
        encoding="utf-8",
    )
    gda = Gda(project)

    removed = _refused(
        gda, host, "node", "remove", "res://Host.tscn", "--node", "Hud/Sprite"
    )
    moved = _refused(
        gda,
        host,
        "node",
        "move",
        "res://Host.tscn",
        "--node",
        "Hud/Shape",
        "--to",
        "Hud",
        "--index",
        "0",
    )

    assert "inside res://BaseEnemy.tscn, instanced at Hud" in removed
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in moved


@pytest.mark.e2e
def test_the_declaring_scene_is_the_one_that_adds_the_node(project):
    # A chain Grand <- Base <- Derived. Base overrides Core, which Grand declares:
    # an override entry does not declare, so the message names Grand. BaseOnly is
    # a node Base adds, so its message names Base.
    gda = Gda(project)
    gda.json("scene", "create", "res://Grand.tscn", "--root-type", "Node2D")
    gda.json("node", "add", "res://Grand.tscn", "--type", "Node2D", "--name", "Core")
    (project / "Base.tscn").write_text(
        _inherited_header("Base", "res://Grand.tscn"), encoding="utf-8"
    )
    gda.json(
        "node",
        "set",
        "res://Base.tscn",
        "--node",
        "Core",
        "--property",
        "position",
        "--value",
        "1,2",
    )
    gda.json("node", "add", "res://Base.tscn", "--type", "Node2D", "--name", "BaseOnly")
    base_text = (project / "Base.tscn").read_text(encoding="utf-8")
    assert '[node name="Core" parent="."' in base_text
    assert 'name="Core" type=' not in base_text
    derived = project / "Derived.tscn"
    derived.write_text(
        _inherited_header("Derived", "res://Base.tscn"), encoding="utf-8"
    )

    core = _refused(
        gda, derived, "node", "remove", "res://Derived.tscn", "--node", "Core"
    )
    base_only = _refused(
        gda, derived, "node", "remove", "res://Derived.tscn", "--node", "BaseOnly"
    )

    assert "declared by res://Grand.tscn, which this scene inherits" in core
    assert "declared by res://Base.tscn, which this scene inherits" in base_only


# --- control cases: what stays allowed (ADR-0044 decision 3) ---


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("node", "remaining"),
    [
        ("GoblinOnly", ["Sprite", "Shape", "Shape/UnderShape", "Hitbox"]),
        # A local node under an inherited parent: its entry is the scene's own.
        ("Shape/UnderShape", ["Sprite", "Shape", "Hitbox", "GoblinOnly"]),
    ],
    ids=["at-the-root", "under-an-inherited-parent"],
)
def test_a_local_node_of_an_inherited_scene_is_removable(project, node, remaining):
    gda = Gda(project)

    removed = gda.json("node", "remove", "res://Goblin.tscn", "--node", node)

    assert removed["path"] == node
    assert _runtime_trees(gda)["res://Goblin.tscn"] == remaining


@pytest.mark.e2e
def test_a_local_node_is_reorderable_among_inherited_siblings(project):
    # The engine saves index for every node of an inherited scene and applies it
    # when it adds the local node (ADR-0044, Context).
    gda = Gda(project)

    moved = gda.json(
        "node",
        "move",
        "res://Goblin.tscn",
        "--node",
        "GoblinOnly",
        "--to",
        ".",
        "--index",
        "0",
    )

    assert moved["path"] == "GoblinOnly"
    assert _runtime_trees(gda)["res://Goblin.tscn"] == [
        "GoblinOnly",
        "Sprite",
        "Shape",
        "Shape/UnderShape",
        "Hitbox",
    ]


@pytest.mark.e2e
def test_a_local_node_moves_to_and_from_an_inherited_parent(project):
    # --to is not checked by this guard: an inherited parent takes a local child.
    gda = Gda(project)

    into = gda.json(
        "node", "move", "res://Goblin.tscn", "--node", "GoblinOnly", "--to", "Shape"
    )
    out_of = gda.json(
        "node", "move", "res://Goblin.tscn", "--node", "Shape/UnderShape", "--to", "."
    )

    assert into["path"] == "Shape/GoblinOnly"
    assert out_of["path"] == "UnderShape"
    tree = _runtime_trees(gda)["res://Goblin.tscn"]
    assert "Shape/GoblinOnly" in tree
    assert "UnderShape" in tree
    assert "GoblinOnly" not in tree
    assert "Shape/UnderShape" not in tree


@pytest.mark.e2e
def test_an_instanced_child_itself_is_removable(project):
    # Hud is owned by the scene root: the instance entry is the scene's own, so
    # removing it drops the entry and its ext_resource.
    gda = Gda(project)

    removed = gda.json("node", "remove", "res://Host.tscn", "--node", "Hud")

    assert removed["path"] == "Hud"
    saved = (project / "Host.tscn").read_text(encoding="utf-8")
    assert "BaseEnemy.tscn" not in saved
    assert 'name="Hud"' not in saved
    assert _runtime_trees(gda)["res://Host.tscn"] == []
