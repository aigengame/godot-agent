"""e2e: six writes refuse an instance-internal node the file cannot record (#1054).

A node inside an instanced child is owned by that child, not by the scene root.
The packer saves only the nodes the root owns, plus the internals of an instance
the root holds as editable (``[editable path=...]``), and skips any other node
with its subtree; it also skips a connection whose source is such a node
(``scene/resources/packed_scene.cpp`` L797-L799 and L1137-L1140 at 4.6.3). So
``node set`` and ``script attach`` on such a node, ``node add`` and ``node move``
under it, ``node duplicate`` of its child, and ``node connect-signal`` from it
reach no entry in the file. Each refuses with ``cannot_target_foreign`` and
leaves the file byte-identical. The root, an instanced child's root and an
editable instance's internals stay writable; a ``script run`` oracle reads what
the engine builds from the file.

The fixtures are the #1054 reproductions (Godot 4.6.3), saved by the engine
through gda: ``Weapon.tscn`` a ``Node2D`` with ``Blade``; ``BaseEnemy.tscn`` a
``CharacterBody2D`` with ``Sprite``, ``Shape``, ``Hitbox`` (child ``HitShape``)
and ``Weapon`` instanced from ``Weapon.tscn``; ``Host.tscn`` a plain ``Node2D``
with ``Hud`` instanced from the base and a local ``Loose``; ``Goblin.tscn`` an
inherited scene of the base.
"""

import json
import shutil

import pytest

from tests.conftest import PROJECT_GODOT
from tests.support import Gda, assert_foreign_refused, write_inherited_scene

# Prints, per scene, every node's `visible`, script and children, and the
# persisted connections: what the engine BUILDS from the file. A scene
# connection carries CONNECT_PERSIST; an engine-internal one does not.
ORACLE_GD = """\
extends SceneTree


func _describe(node: Node, root: Node, nodes: Dictionary) -> void:
\tvar script := node.get_script() as Script
\tvar children := []
\tfor child in node.get_children():
\t\tchildren.append(String(child.name))
\tnodes[String(root.get_path_to(node))] = {
\t\t"visible": node.get("visible"),
\t\t"script": script.resource_path if script != null else null,
\t\t"children": children,
\t}
\tfor child in node.get_children():
\t\t_describe(child, root, nodes)


func _collect(node: Node, root: Node, out: Array) -> void:
\tfor sig in node.get_signal_list():
\t\tfor c in node.get_signal_connection_list(sig["name"]):
\t\t\tvar target := (c["callable"] as Callable).get_object() as Node
\t\t\tif target == null or not (c["flags"] & Object.CONNECT_PERSIST):
\t\t\t\tcontinue
\t\t\tout.append([String(root.get_path_to(node)), String(sig["name"]),
\t\t\t\t\tString(root.get_path_to(target)),
\t\t\t\t\tString((c["callable"] as Callable).get_method())])
\tfor child in node.get_children():
\t\t_collect(child, root, out)


func _initialize() -> void:
\tfor scene_path in ["res://Host.tscn", "res://Goblin.tscn"]:
\t\tvar root := (load(scene_path) as PackedScene).instantiate()
\t\tvar nodes := {}
\t\t_describe(root, root, nodes)
\t\tvar connections := []
\t\t_collect(root, root, connections)
\t\tconnections.sort()
\t\tprint("NODES ", scene_path, " ", JSON.stringify(nodes))
\t\tprint("CONN ", scene_path, " ", JSON.stringify(connections))
\t\troot.free()
\tquit(0)
"""

EDITABLE_HUD = '\n[editable path="Hud"]\n'

SPRITE_VIS = ["Hud/Sprite", "visibility_changed", ".", "_on_sprite_vis"]


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The reproduction project, built once through gda and copied per test."""
    project = tmp_path_factory.mktemp("instance-internal-template")
    (project / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    gda = Gda(project)
    gda.json("scene", "create", "res://Weapon.tscn", "--root-type", "Node2D")
    gda.json("node", "add", "res://Weapon.tscn", "--type", "Node2D", "--name", "Blade")

    gda.json(
        "scene", "create", "res://BaseEnemy.tscn", "--root-type", "CharacterBody2D"
    )
    for parent, name, node_type in (
        (".", "Sprite", "Sprite2D"),
        (".", "Shape", "CollisionShape2D"),
        (".", "Hitbox", "Area2D"),
        ("Hitbox", "HitShape", "CollisionShape2D"),
    ):
        gda.json(
            "node",
            "add",
            "res://BaseEnemy.tscn",
            "--parent",
            parent,
            "--type",
            node_type,
            "--name",
            name,
        )
    gda.json(
        "node",
        "add",
        "res://BaseEnemy.tscn",
        "--instance",
        "res://Weapon.tscn",
        "--name",
        "Weapon",
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
    gda.json("node", "add", "res://Host.tscn", "--type", "Node2D", "--name", "Loose")

    write_inherited_scene(project / "Goblin.tscn", "Goblin", "res://BaseEnemy.tscn")
    gda.json("script", "create", "res://goblin_sprite.gd", "--extends", "Sprite2D")
    (project / "oracle.gd").write_text(ORACLE_GD, encoding="utf-8")
    return project


@pytest.fixture
def project(_template, tmp_path):
    copy = tmp_path / "project"
    shutil.copytree(_template, copy)
    return copy


def _oracle(gda: Gda) -> dict[str, dict]:
    """Per scene: ``nodes`` (path -> visible/script/children) and ``connections``."""
    ran = gda.json("script", "run", "res://oracle.gd")
    assert ran["exit_status"] == 0, ran
    seen: dict[str, dict] = {}
    for line in ran["stdout"].splitlines():
        kind, _, rest = line.partition(" ")
        if kind in ("NODES", "CONN"):
            scene_path, payload = rest.split(" ", 1)
            key = "nodes" if kind == "NODES" else "connections"
            seen.setdefault(scene_path, {})[key] = json.loads(payload)
    return seen


def _make_hud_editable(project) -> None:
    """Append the marker the editor writes for Editable Children on ``Hud``."""
    host = project / "Host.tscn"
    host.write_text(host.read_text(encoding="utf-8") + EDITABLE_HUD, encoding="utf-8")


# --- the six reproductions: refused, file byte-identical ---


@pytest.mark.e2e
def test_node_set_on_a_node_inside_an_instanced_child_is_refused(project):
    # Reproduction 1: before #1054 this echoed the value and the file did not
    # change; the oracle still saw visible=true.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        "node",
        "set",
        "res://Host.tscn",
        "--node",
        "Hud/Sprite",
        "--property",
        "visible",
        "--value",
        "false",
    )

    assert message == (
        "cannot set Hud/Sprite: the node is inside res://BaseEnemy.tscn,"
        " instanced at Hud — edit that scene, or mark the instance's children"
        " editable in the editor"
    )


@pytest.mark.e2e
def test_script_attach_to_a_node_inside_an_instanced_child_is_refused(project):
    # Reproduction 2: before #1054 this reported success; the oracle saw no script.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        "script",
        "attach",
        "res://Host.tscn",
        "--node",
        "Hud/Sprite",
        "--script",
        "res://goblin_sprite.gd",
    )

    assert message.startswith("cannot attach a script to Hud/Sprite: the node is ")
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in message


@pytest.mark.e2e
def test_node_add_under_a_node_inside_an_instanced_child_is_refused(project):
    # Reproduction 3: before #1054 this reported success; the oracle saw no child.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        "node",
        "add",
        "res://Host.tscn",
        "--parent",
        "Hud/Sprite",
        "--type",
        "Node2D",
        "--name",
        "UnderSprite",
    )

    assert message.startswith("cannot add under Hud/Sprite: the parent is ")
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in message


@pytest.mark.e2e
def test_node_move_of_a_local_node_under_an_instanced_childs_node_is_refused(project):
    # Reproduction 4: before #1054 this reported Hud/Sprite/Loose and the file
    # LOST the Loose entry — a local node and its subtree gone. The refusal keeps
    # Loose where it was, in the file and at runtime (the data-loss guard).
    gda = Gda(project)

    message = assert_foreign_refused(
        gda,
        project / "Host.tscn",
        "node",
        "move",
        "res://Host.tscn",
        "--node",
        "Loose",
        "--to",
        "Hud/Sprite",
    )

    assert message.startswith("cannot move Loose to Hud/Sprite: the target parent is ")
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in message
    listed = gda.json("node", "list", "res://Host.tscn")["root"]["children"]
    assert [child["path"] for child in listed] == ["Hud", "Loose"]
    nodes = _oracle(gda)["res://Host.tscn"]["nodes"]
    assert nodes["."]["children"] == ["Hud", "Loose"]
    assert nodes["Hud/Sprite"]["children"] == []


@pytest.mark.e2e
def test_connect_signal_from_a_node_inside_an_instanced_child_is_refused(project):
    # Reproduction 5: before #1054 this reported success and the file gained no
    # [connection]; the packer skips a source inside such an instance.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        "node",
        "connect-signal",
        "res://Host.tscn",
        "--from",
        "Hud/Sprite",
        "--signal",
        "visibility_changed",
        "--to",
        ".",
        "--method",
        "_on_sprite_vis",
    )

    assert message.startswith("cannot connect a signal from Hud/Sprite: the node is ")
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in message


@pytest.mark.e2e
def test_node_duplicate_into_a_parent_inside_an_instanced_child_is_refused(project):
    # Reproduction 6: before #1054 this reported Hud/Hitbox/HitShape2 and the
    # file did not change. The copy goes under the source's parent, Hud/Hitbox,
    # whose subtree the packer skips.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        "node",
        "duplicate",
        "res://Host.tscn",
        "--node",
        "Hud/Hitbox/HitShape",
    )

    assert message.startswith(
        "cannot duplicate Hud/Hitbox/HitShape under Hud/Hitbox: the parent is "
    )
    assert "inside res://BaseEnemy.tscn, instanced at Hud" in message


# --- controls: what keeps reaching the file ---


def _host(gda: Gda) -> dict:
    return _oracle(gda)["res://Host.tscn"]


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("argv", "saved"),
    [
        (
            ["node", "set", "--node", "Hud/Sprite", "--property", "visible"]
            + ["--value", "false"],
            lambda host: host["nodes"]["Hud/Sprite"]["visible"] is False,
        ),
        (
            ["script", "attach", "--node", "Hud/Sprite"]
            + ["--script", "res://goblin_sprite.gd"],
            lambda host: (
                host["nodes"]["Hud/Sprite"]["script"] == "res://goblin_sprite.gd"
            ),
        ),
        (
            ["node", "add", "--parent", "Hud/Sprite", "--type", "Node2D"]
            + ["--name", "UnderSprite"],
            lambda host: host["nodes"]["Hud/Sprite"]["children"] == ["UnderSprite"],
        ),
        (
            ["node", "move", "--node", "Loose", "--to", "Hud/Sprite"],
            lambda host: (
                host["nodes"]["Hud/Sprite"]["children"] == ["Loose"]
                and host["nodes"]["."]["children"] == ["Hud"]
            ),
        ),
        (
            ["node", "connect-signal", "--from", "Hud/Sprite"]
            + ["--signal", "visibility_changed", "--to", ".", "--method"]
            + ["_on_sprite_vis"],
            lambda host: SPRITE_VIS in host["connections"],
        ),
        (
            ["node", "duplicate", "--node", "Hud/Hitbox/HitShape"],
            lambda host: (
                host["nodes"]["Hud/Hitbox"]["children"] == ["HitShape", "HitShape2"]
            ),
        ),
    ],
    ids=["set", "attach", "add", "move", "connect", "duplicate"],
)
def test_the_six_writes_reach_the_file_inside_an_editable_instance(
    project, argv, saved
):
    # With [editable path="Hud"] the packer records Hud's internals, so the same
    # six writes save: the editor shows those children and saves their edits.
    _make_hud_editable(project)
    gda = Gda(project)

    gda.json(argv[0], argv[1], "res://Host.tscn", *argv[2:])

    assert saved(_host(gda))


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("argv", "saved"),
    [
        (
            ["node", "set", "--node", ".", "--property", "visible", "--value"]
            + ["false"],
            lambda host: host["nodes"]["."]["visible"] is False,
        ),
        (
            ["node", "add", "--parent", ".", "--type", "Node2D", "--name", "AtRoot"],
            lambda host: "AtRoot" in host["nodes"]["."]["children"],
        ),
        (
            ["node", "set", "--node", "Hud", "--property", "visible", "--value"]
            + ["false"],
            lambda host: host["nodes"]["Hud"]["visible"] is False,
        ),
        (
            ["node", "add", "--parent", "Hud", "--type", "Node2D", "--name"]
            + ["UnderHud"],
            lambda host: "UnderHud" in host["nodes"]["Hud"]["children"],
        ),
        (
            # The copy goes under Hud, which the root owns, and is re-owned.
            ["node", "duplicate", "--node", "Hud/Sprite"],
            lambda host: "Sprite2" in host["nodes"]["Hud"]["children"],
        ),
    ],
    ids=["set-root", "add-under-root", "set-hud", "add-under-hud", "duplicate-sprite"],
)
def test_writes_whose_node_the_root_owns_reach_the_file(project, argv, saved):
    # No [editable]: the root and an instanced child's root are the scene's own.
    gda = Gda(project)

    gda.json(argv[0], argv[1], "res://Host.tscn", *argv[2:])

    assert saved(_host(gda))


@pytest.mark.e2e
def test_a_connection_to_a_node_inside_an_instanced_child_connects_and_disconnects(
    project,
):
    # The source is the root, so the packer stores the connection and its target
    # by path; --to is not checked, and the disconnect removes the entry.
    gda = Gda(project)
    wiring = (
        "res://Host.tscn",
        "--from",
        ".",
        "--signal",
        "visibility_changed",
        "--to",
        "Hud/Sprite",
        "--method",
        "hide",
    )
    to_sprite = [".", "visibility_changed", "Hud/Sprite", "hide"]

    gda.json("node", "connect-signal", *wiring)
    connected = _host(gda)["connections"]
    gda.json("node", "disconnect-signal", *wiring)

    assert to_sprite in connected
    assert to_sprite not in _host(gda)["connections"]


@pytest.mark.e2e
def test_the_editable_marker_reaches_one_level(project):
    # Blade's owner is the Weapon instance inside Hud, which the root does not
    # hold as editable; Weapon's owner is Hud, which it does.
    _make_hud_editable(project)
    gda = Gda(project)

    message = assert_foreign_refused(
        gda,
        project / "Host.tscn",
        "node",
        "set",
        "res://Host.tscn",
        "--node",
        "Hud/Weapon/Blade",
        "--property",
        "visible",
        "--value",
        "false",
    )
    gda.json(
        "node",
        "set",
        "res://Host.tscn",
        "--node",
        "Hud/Weapon",
        "--property",
        "visible",
        "--value",
        "false",
    )

    assert message == (
        "cannot set Hud/Weapon/Blade: the node is inside res://Weapon.tscn,"
        " instanced at Hud/Weapon — edit that scene, or mark the instance's"
        " children editable in the editor"
    )
    nodes = _host(gda)["nodes"]
    assert nodes["Hud/Weapon"]["visible"] is False
    assert nodes["Hud/Weapon/Blade"]["visible"] is True


@pytest.mark.e2e
def test_writes_on_an_inherited_node_reach_the_file(project):
    # ADR-0044 decision 3: an inherited node is owned by the root under the
    # mutation's edit state, so it is not instance-internal.
    gda = Gda(project)

    gda.json(
        "node",
        "set",
        "res://Goblin.tscn",
        "--node",
        "Sprite",
        "--property",
        "visible",
        "--value",
        "false",
    )
    gda.json(
        "script",
        "attach",
        "res://Goblin.tscn",
        "--node",
        "Sprite",
        "--script",
        "res://goblin_sprite.gd",
    )
    gda.json(
        "node",
        "add",
        "res://Goblin.tscn",
        "--parent",
        "Sprite",
        "--type",
        "Node2D",
        "--name",
        "UnderSprite",
    )
    gda.json(
        "node",
        "connect-signal",
        "res://Goblin.tscn",
        "--from",
        "Sprite",
        "--signal",
        "visibility_changed",
        "--to",
        ".",
        "--method",
        "_on_sprite_vis",
    )

    goblin = _oracle(gda)["res://Goblin.tscn"]
    assert goblin["nodes"]["Sprite"] == {
        "visible": False,
        "script": "res://goblin_sprite.gd",
        "children": ["UnderSprite"],
    }
    assert ["Sprite", "visibility_changed", ".", "_on_sprite_vis"] in goblin[
        "connections"
    ]
