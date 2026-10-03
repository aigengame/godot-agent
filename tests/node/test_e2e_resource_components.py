"""E2E: the Resource-based component workflow, end to end with gda and no editor.

The tracer of the "gda resource-based components" milestone (#1075). On a
project the editor never opened, an agent writes a `class_name` Resource
component and a subclass of it, scans the project, saves each component as a
`.tres`, links each to a node through an export typed with the component class,
makes one local to scene, and checks that the scene starts and that the two
links behave as the engine documents: a local-to-scene resource is a distinct
object per scene instance, a shared one is the same object. Every step is a gda
command; the class index comes from `gda project scan`, not from a test helper.
The scene declares its nodes itself (no inheritance, no instanced child).
Run e2e SERIALLY; not a fresh empty HOME.
"""

import pytest

from tests.support import Gda

ATTACK_COMPONENT_GD = """\
class_name AttackComponent
extends Resource

@export var damage: int = 1
"""

FIRE_ATTACK_GD = """\
class_name FireAttack
extends AttackComponent
"""

ENEMY_GD = """\
extends Node2D

@export var attack: AttackComponent
"""

# Instantiates the scene twice and prints, per enemy, the class of the component
# it holds, whether that component is local to scene, and whether the two
# instances hold the same component object.
CHECK_GD = """\
extends SceneTree

func _initialize() -> void:
\tvar packed: PackedScene = load("res://level.tscn")
\tvar first := packed.instantiate()
\tvar second := packed.instantiate()
\tfor enemy in ["Grunt", "Boss"]:
\t\tvar mine: Resource = first.get_node(enemy).get("attack")
\t\tvar theirs: Resource = second.get_node(enemy).get("attack")
\t\tprint("%s class=%s local=%s same=%s" % [enemy,
\t\t\t\tmine.get_script().get_global_name(), mine.resource_local_to_scene,
\t\t\t\tis_same(mine, theirs)])
\tfirst.free()
\tsecond.free()
\tquit(0)
"""


@pytest.mark.e2e
def test_an_agent_builds_resource_components_with_gda_and_no_editor(godot_project):
    project = godot_project
    for name, source in {
        "attack_component.gd": ATTACK_COMPONENT_GD,
        "fire_attack.gd": FIRE_ATTACK_GD,
        "enemy.gd": ENEMY_GD,
        "check.gd": CHECK_GD,
    }.items():
        (project / name).write_text(source, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)

    # (1) The scan builds the engine's class index on a never-opened project.
    scanned = gda.json("project", "scan")
    classes = {entry["name"]: entry["path"] for entry in scanned["classes"]}
    assert classes == {
        "AttackComponent": "res://attack_component.gd",
        "FireAttack": "res://fire_attack.gd",
    }

    # (2) Each component class saved as a .tres.
    gda.json(
        "resource", "create", "res://grunt_attack.tres", "--type", "AttackComponent"
    )
    gda.json("resource", "create", "res://boss_attack.tres", "--type", "FireAttack")

    # (3) A scene that declares two enemies, each carrying enemy.gd.
    gda.json("scene", "create", "res://level.tscn", "--root-type", "Node2D")
    for enemy in ("Grunt", "Boss"):
        gda.json("node", "add", "res://level.tscn", "--type", "Node2D", "--name", enemy)
        gda.json(
            "script",
            "attach",
            "res://level.tscn",
            "--node",
            enemy,
            "--script",
            "res://enemy.gd",
        )

    # (4) Each .tres linked through the class_name-typed export: both accepted.
    for enemy, component in (
        ("Grunt", "res://grunt_attack.tres"),
        ("Boss", "res://boss_attack.tres"),
    ):
        linked = gda.json(
            "node",
            "set",
            "res://level.tscn",
            "--node",
            enemy,
            "--property",
            "attack",
            "--value",
            component,
        )
        assert linked["value"] == {"type": "Resource", "resource_path": component}

    # (5) One component made local to scene.
    gda.json(
        "resource",
        "set",
        "res://boss_attack.tres",
        "--property",
        "resource_local_to_scene",
        "--value",
        "true",
    )

    # (6) The scene starts.
    preflighted = gda.json("scene", "preflight", "res://level.tscn")
    assert preflighted["started"] is True, preflighted

    # (7) Two instances share the plain component and each get their own copy of
    # the local-to-scene one.
    ran = gda.json("script", "run", "res://check.gd")
    assert ran["exit_status"] == 0, ran
    lines = ran["stdout"].splitlines()
    assert "Grunt class=AttackComponent local=false same=true" in lines, ran["stdout"]
    assert "Boss class=FireAttack local=true same=false" in lines, ran["stdout"]
