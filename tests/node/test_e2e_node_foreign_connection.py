"""e2e: node disconnect-signal refuses a Foreign connection (#1052, ADR-0044).

The packer stores only the connections it does not find already declared: from
the endpoints' common parent up the owner chain, it asks each instanced child's
scene, and at the scene root the scenes of the base chain, whether they declare
the connection (``SceneState::_parse_connections``). A connection found there
has no entry in the file, so the file cannot record its removal, and
``disconnect-signal`` refuses it with ``cannot_target_foreign``, leaving the
file byte-identical. A connection the scene declares itself still disconnects;
a ``script run`` oracle reads what the engine builds.

The fixtures are the #1052 reproductions (Godot 4.6.3): ``BaseEnemy.tscn`` a
scripted ``CharacterBody2D`` with ``Sprite`` and ``Hitbox`` that declares
``Hitbox.body_entered -> ._on_hit``; ``Goblin.tscn`` inherits it and declares
``Hitbox.area_entered -> ._on_area``; ``Host.tscn`` a plain scene with ``Hud``
instanced from the base that declares ``.visibility_changed -> Hud/Sprite.hide``;
``Level.tscn`` a plain scene with ``Gob`` instanced from ``Goblin.tscn``.
"""

import json
import shutil

import pytest

from tests.conftest import PROJECT_GODOT
from tests.support import Gda, assert_foreign_refused, write_inherited_scene

BASE_ENEMY_GD = """\
extends CharacterBody2D


func _on_hit(_body: Node2D) -> void:
\tpass


func _on_area(_area: Area2D) -> void:
\tpass
"""

# Prints each scene's persisted connections as one line per scene: what the
# engine CONNECTS when it instantiates the file, base chain and instances
# included. A scene connection carries CONNECT_PERSIST; an engine-internal one
# does not.
ORACLE_GD = """\
extends SceneTree


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
\tfor scene_path in ["res://Goblin.tscn", "res://Host.tscn", "res://Level.tscn"]:
\t\tvar root := (load(scene_path) as PackedScene).instantiate()
\t\tvar connections := []
\t\t_collect(root, root, connections)
\t\tconnections.sort()
\t\tprint("CONN ", scene_path, " ", JSON.stringify(connections))
\t\troot.free()
\tquit(0)
"""

BASE_HIT = ["Hitbox", "body_entered", ".", "_on_hit"]
GOBLIN_AREA = ["Hitbox", "area_entered", ".", "_on_area"]
HOST_HIDE = [".", "visibility_changed", "Hud/Sprite", "hide"]


def _connect(
    gda: Gda, scene: str, source: str, signal: str, target: str, method: str
) -> None:
    gda.json(
        "node",
        "connect-signal",
        scene,
        "--from",
        source,
        "--signal",
        signal,
        "--to",
        target,
        "--method",
        method,
    )


def _disconnect_argv(
    scene: str, source: str, signal: str, target: str, method: str
) -> tuple[str, ...]:
    return (
        "node",
        "disconnect-signal",
        scene,
        "--from",
        source,
        "--signal",
        signal,
        "--to",
        target,
        "--method",
        method,
    )


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The reproduction project, built once through gda and copied per test."""
    project = tmp_path_factory.mktemp("foreign-connection-template")
    (project / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    gda = Gda(project)
    gda.json(
        "scene", "create", "res://BaseEnemy.tscn", "--root-type", "CharacterBody2D"
    )
    for name, node_type in (("Sprite", "Sprite2D"), ("Hitbox", "Area2D")):
        gda.json(
            "node", "add", "res://BaseEnemy.tscn", "--type", node_type, "--name", name
        )
    (project / "base_enemy.gd").write_text(BASE_ENEMY_GD, encoding="utf-8")
    gda.json(
        "script",
        "attach",
        "res://BaseEnemy.tscn",
        "--node",
        ".",
        "--script",
        "res://base_enemy.gd",
    )
    _connect(gda, "res://BaseEnemy.tscn", *BASE_HIT)

    write_inherited_scene(project / "Goblin.tscn", "Goblin", "res://BaseEnemy.tscn")
    _connect(gda, "res://Goblin.tscn", *GOBLIN_AREA)

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
    _connect(gda, "res://Host.tscn", *HOST_HIDE)

    gda.json("scene", "create", "res://Level.tscn", "--root-type", "Node2D")
    gda.json(
        "node",
        "add",
        "res://Level.tscn",
        "--instance",
        "res://Goblin.tscn",
        "--name",
        "Gob",
    )
    (project / "oracle.gd").write_text(ORACLE_GD, encoding="utf-8")
    return project


@pytest.fixture
def project(_template, tmp_path):
    copy = tmp_path / "project"
    shutil.copytree(_template, copy)
    return copy


def _runtime_connections(gda: Gda) -> dict[str, list[list[str]]]:
    """The oracle's persisted connections per scene, sorted."""
    ran = gda.json("script", "run", "res://oracle.gd")
    assert ran["exit_status"] == 0, ran
    connections = {}
    for line in ran["stdout"].splitlines():
        if line.startswith("CONN "):
            _, scene_path, found = line.split(" ", 2)
            connections[scene_path] = json.loads(found)
    return connections


@pytest.mark.e2e
def test_the_fixture_matches_the_reproduction(project):
    # The premise every test below stands on, read from the files: the base
    # declares the connection, and no scene that inherits or instances it does.
    base = (project / "BaseEnemy.tscn").read_text(encoding="utf-8")
    assert (
        '[connection signal="body_entered" from="Hitbox" to="." method="_on_hit"]'
        in base
    )
    for scene in ("Goblin.tscn", "Host.tscn", "Level.tscn"):
        assert "body_entered" not in (project / scene).read_text(encoding="utf-8")


# --- the three reproductions (#1052) ---


@pytest.mark.e2e
def test_a_connection_the_base_declares_is_refused_in_the_inherited_scene(project):
    # Reproduction 1: before #1052 this reported the connection disconnected,
    # Goblin.tscn gained no entry and the connection stayed.
    message = assert_foreign_refused(
        Gda(project),
        project / "Goblin.tscn",
        *_disconnect_argv("res://Goblin.tscn", *BASE_HIT),
    )

    assert message == (
        "cannot disconnect Hitbox.body_entered -> .._on_hit: the connection is"
        " declared by res://BaseEnemy.tscn, which this scene inherits — edit that"
        " scene"
    )


@pytest.mark.e2e
def test_a_connection_inside_an_instanced_child_is_refused(project):
    # Reproduction 2: the same reported success, with a byte-identical file.
    message = assert_foreign_refused(
        Gda(project),
        project / "Host.tscn",
        *_disconnect_argv(
            "res://Host.tscn", "Hud/Hitbox", "body_entered", "Hud", "_on_hit"
        ),
    )

    assert message == (
        "cannot disconnect Hud/Hitbox.body_entered -> Hud._on_hit: the connection"
        " is declared by res://BaseEnemy.tscn, instanced at Hud — edit that scene"
    )


@pytest.mark.e2e
def test_a_connection_the_base_of_an_instanced_child_declares_is_refused(project):
    # Reproduction 3: Gob instances Goblin.tscn, whose own state does not hold
    # the connection; the base of its chain does, and the message names it.
    message = assert_foreign_refused(
        Gda(project),
        project / "Level.tscn",
        *_disconnect_argv(
            "res://Level.tscn", "Gob/Hitbox", "body_entered", "Gob", "_on_hit"
        ),
    )

    assert message == (
        "cannot disconnect Gob/Hitbox.body_entered -> Gob._on_hit: the connection"
        " is declared by res://BaseEnemy.tscn, instanced at Gob — edit that scene"
    )


@pytest.mark.e2e
def test_an_editable_instanced_child_does_not_open_a_foreign_connection(project):
    # The packer's check does not read is_editable_instance: with [editable]
    # the file still has no entry that could record the removal.
    host = project / "Host.tscn"
    host.write_text(
        host.read_text(encoding="utf-8") + '\n[editable path="Hud"]\n',
        encoding="utf-8",
    )

    message = assert_foreign_refused(
        Gda(project),
        host,
        *_disconnect_argv(
            "res://Host.tscn", "Hud/Hitbox", "body_entered", "Hud", "_on_hit"
        ),
    )

    assert "declared by res://BaseEnemy.tscn, instanced at Hud" in message


@pytest.mark.e2e
def test_a_connection_the_scene_redeclares_over_its_base_is_refused(project):
    # The base wins: the packer skips a connection the base declares even when
    # the scene's own state holds it too, so the removal cannot be recorded.
    goblin = project / "Goblin.tscn"
    goblin.write_text(
        goblin.read_text(encoding="utf-8")
        + '\n[connection signal="body_entered" from="Hitbox" to="."'
        ' method="_on_hit"]\n',
        encoding="utf-8",
    )

    message = assert_foreign_refused(
        Gda(project), goblin, *_disconnect_argv("res://Goblin.tscn", *BASE_HIT)
    )

    assert "declared by res://BaseEnemy.tscn, which this scene inherits" in message


@pytest.mark.e2e
def test_the_check_walks_from_the_instanced_child_up_to_the_scene_root(project):
    # Both endpoints sit inside Hud, so the walk starts at Hud, whose scene does
    # not declare the connection, and goes up the owner chain to the root, whose
    # base chain does: HostBase, which stores it through [editable]. Before
    # #1052 the disconnect reported success and the connection stayed.
    host = project / "Host.tscn"
    host.write_text(
        host.read_text(encoding="utf-8") + '\n[editable path="Hud"]\n',
        encoding="utf-8",
    )
    gda = Gda(project)
    inside_hud = ("Hud/Hitbox", "body_exited", "Hud/Sprite", "hide")
    _connect(gda, "res://Host.tscn", *inside_hud)
    derived = write_inherited_scene(
        project / "HostDerived.tscn", "HostDerived", "res://Host.tscn"
    )

    message = assert_foreign_refused(
        gda, derived, *_disconnect_argv("res://HostDerived.tscn", *inside_hud)
    )

    assert message == (
        "cannot disconnect Hud/Hitbox.body_exited -> Hud/Sprite.hide: the connection"
        " is declared by res://Host.tscn, which this scene inherits — edit that scene"
    )


# --- control cases: a connection the scene declares itself ---


@pytest.mark.e2e
def test_a_connection_the_inherited_scene_declares_from_an_inherited_node_disconnects(
    project,
):
    gda = Gda(project)

    disconnected = gda.json(*_disconnect_argv("res://Goblin.tscn", *GOBLIN_AREA))

    assert disconnected["signal"] == "area_entered"
    assert "area_entered" not in (project / "Goblin.tscn").read_text(encoding="utf-8")
    assert _runtime_connections(gda)["res://Goblin.tscn"] == [BASE_HIT]


@pytest.mark.e2e
def test_a_connection_the_scene_declares_to_an_instance_internal_target_disconnects(
    project,
):
    gda = Gda(project)

    disconnected = gda.json(*_disconnect_argv("res://Host.tscn", *HOST_HIDE))

    assert disconnected["to"] == "Hud/Sprite"
    assert "visibility_changed" not in (project / "Host.tscn").read_text(
        encoding="utf-8"
    )
    assert _runtime_connections(gda)["res://Host.tscn"] == [
        ["Hud/Hitbox", "body_entered", "Hud", "_on_hit"]
    ]


@pytest.mark.e2e
def test_an_absent_connection_is_still_connection_not_found(project):
    goblin = project / "Goblin.tscn"
    before = goblin.read_bytes()

    Gda(project).error(
        *_disconnect_argv("res://Goblin.tscn", "Hitbox", "body_exited", ".", "_on_hit"),
        code="connection_not_found",
    )

    assert goblin.read_bytes() == before


@pytest.mark.e2e
def test_connecting_what_the_base_declares_is_already_connected(project):
    # Pinned (#1052): the base's connection is live on the instantiated tree, so
    # connect-signal reports it rather than recording a duplicate.
    goblin = project / "Goblin.tscn"
    before = goblin.read_bytes()

    Gda(project).error(
        "node",
        "connect-signal",
        "res://Goblin.tscn",
        "--from",
        "Hitbox",
        "--signal",
        "body_entered",
        "--to",
        ".",
        "--method",
        "_on_hit",
        code="already_connected",
    )

    assert goblin.read_bytes() == before
