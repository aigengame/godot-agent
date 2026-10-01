"""e2e: ``scene create --inherits`` authors an Inherited scene (#1050, ADR-0044).

The command writes the text the engine's own saver writes for an inherited scene —
``[gd_scene format=3]``, one path-only ``PackedScene`` ``ext_resource`` naming the
base's ``res://`` path, and a root line ``[node name=... instance=ExtResource(...)]``
— after validating the base by load, without instantiating it, and loads the file
back before it reports success. The engine is the judge of every file here: the
static reads, the node commands, ``scene preflight`` and a ``script run`` oracle
that instantiates the created scene.

The base is ``BaseEnemy.tscn``, built through gda: a scripted ``CharacterBody2D``
root with ``Sprite`` and ``Shape`` children.
"""

import json
import re
import shutil

import pytest

from tests.conftest import PROJECT_GODOT
from tests.support import Gda

# The whole file `scene create --inherits` writes, as the saver writes it: the id
# is the saver's `<index>_<scene unique id>` shape, and the root name is escaped.
INHERITED_TEXT = re.compile(
    r"\[gd_scene format=3\]\n"
    r"\n"
    r'\[ext_resource type="PackedScene" path="(?P<path>[^"]+)" id="(?P<id>1_[a-z0-9]+)"\]\n'
    r"\n"
    r'\[node name="(?P<name>(?:[^"\\]|\\.)*)" instance=ExtResource\("(?P=id)"\)\]\n'
)

# Prints the runtime tree of one scene, depth first in sibling order: what the
# engine BUILDS from the file, not what the file says. `script run` passes no
# arguments to the script, so the scene path is written into it.
ORACLE_GD = """\
extends SceneTree


func _walk(node: Node, root: Node, out: Array) -> void:
\tfor child in node.get_children():
\t\tout.append(String(root.get_path_to(child)))
\t\t_walk(child, root, out)


func _initialize() -> void:
\tvar root := (load("{scene}") as PackedScene).instantiate()
\tvar paths := []
\t_walk(root, root, paths)
\tprint("TREE ", JSON.stringify([String(root.name), paths]))
\troot.free()
\tquit(0)
"""


# The base's script, rewritten to leave a marker file when an instance of it is
# constructed.
INIT_MARKER_GD = """\
extends CharacterBody2D


func _init() -> void:
\tFileAccess.open("{marker}", FileAccess.WRITE).store_string("constructed")
"""


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The base scene, built once through gda and copied per test."""
    project = tmp_path_factory.mktemp("inherits-template")
    (project / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    gda = Gda(project)
    gda.json(
        "scene", "create", "res://BaseEnemy.tscn", "--root-type", "CharacterBody2D"
    )
    for name, node_type in (("Sprite", "Sprite2D"), ("Shape", "CollisionShape2D")):
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
    return project


@pytest.fixture
def project(_template, tmp_path):
    copy = tmp_path / "project"
    shutil.copytree(_template, copy)
    return copy


def _runtime_tree(project, scene_path: str) -> tuple[str, list[str]]:
    """The oracle's instantiated root name and node paths for one scene."""
    (project / "oracle.gd").write_text(
        ORACLE_GD.replace("{scene}", scene_path), encoding="utf-8"
    )
    ran = Gda(project).json("script", "run", "res://oracle.gd")
    assert ran["exit_status"] == 0, ran
    for line in ran["stdout"].splitlines():
        if line.startswith("TREE "):
            root_name, paths = json.loads(line.removeprefix("TREE "))
            return root_name, paths
    raise AssertionError(f"the oracle printed no tree for {scene_path}: {ran}")


@pytest.mark.e2e
def test_an_inherited_scene_is_written_as_the_saver_writes_it_and_follows_its_base(
    project,
):
    gda = Gda(project)

    created = gda.json(
        "scene",
        "create",
        "res://enemies/Goblin.tscn",
        "--inherits",
        "res://BaseEnemy.tscn",
    )

    assert created == {
        "path": "res://enemies/Goblin.tscn",
        "root_name": "Goblin",
        "root_type": "CharacterBody2D",
        "created_dirs": ["res://enemies"],
        "inherits": "res://BaseEnemy.tscn",
    }
    goblin = project / "enemies" / "Goblin.tscn"
    written = INHERITED_TEXT.fullmatch(goblin.read_text(encoding="utf-8"))
    assert written, goblin.read_text(encoding="utf-8")
    # A path-only reference (ADR-0036): no uid on the header or the ext_resource.
    assert written["path"] == "res://BaseEnemy.tscn"
    assert written["name"] == "Goblin"

    # The static read sees an inherited root that resolves to the base.
    listed = {s["path"]: s for s in gda.json("scene", "list")["scenes"]}
    assert listed["res://enemies/Goblin.tscn"] == {
        "path": "res://enemies/Goblin.tscn",
        "root_name": "Goblin",
        "root_type": "CharacterBody2D",
        "root_instance_path": "res://BaseEnemy.tscn",
        "root_instance_status": "resolved",
    }

    # An override on an inherited node is written, and the root stays inherited.
    gda.json(
        "node",
        "set",
        "res://enemies/Goblin.tscn",
        "--node",
        "Sprite",
        "--property",
        "modulate",
        "--value",
        "#ff0000",
    )
    # The engine's own re-save gives the root the unique_id the created file omits.
    saved = goblin.read_text(encoding="utf-8")
    inherited_root = r'^\[node name="Goblin"(?: unique_id=\d+)? instance=ExtResource\('
    assert re.search(inherited_root, saved, re.M), saved
    assert re.search(r'^\[node name="Sprite" parent="\."', saved, re.M), saved

    assert gda.json("scene", "preflight", "res://enemies/Goblin.tscn")["status"] == (
        "ready"
    )

    # The instantiated scene carries the base's children, including one the base
    # gains after the inherited scene was created.
    gda.json(
        "node", "add", "res://BaseEnemy.tscn", "--type", "Area2D", "--name", "Hitbox"
    )
    assert _runtime_tree(project, "res://enemies/Goblin.tscn") == (
        "Goblin",
        ["Sprite", "Shape", "Hitbox"],
    )


# A scene file that exists but does not load: its node tag is never closed.
# (A scene whose own dependency is missing is not one: on 4.6.3 the text loader
# prints a parse error and still returns the scene.)
BROKEN_BASE = """\
[gd_scene format=3]

[node name="Broken" type="Node2D"
"""


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("base", "code"),
    [
        ("res://Ghost.tscn", "missing_dependency"),
        ("res://base_enemy.gd", "not_a_scene"),
        ("res://Broken.tscn", "missing_dependency"),
    ],
    ids=["missing", "not-a-scene", "fails-to-load"],
)
def test_a_base_that_does_not_load_as_a_scene_is_refused_and_writes_nothing(
    project, base, code
):
    (project / "Broken.tscn").write_text(BROKEN_BASE, encoding="utf-8")

    err = Gda(project).error(
        "scene",
        "create",
        "res://enemies/Goblin.tscn",
        "--inherits",
        base,
        "--json",
        code=code,
    )

    assert base in err["message"]
    assert not (project / "enemies").exists()


@pytest.mark.e2e
def test_an_existing_target_is_already_exists_and_stays_untouched(project):
    base = project / "BaseEnemy.tscn"
    before = base.read_text(encoding="utf-8")

    Gda(project).error(
        "scene",
        "create",
        "res://BaseEnemy.tscn",
        "--inherits",
        "res://BaseEnemy.tscn",
        "--json",
        code="already_exists",
    )

    assert base.read_text(encoding="utf-8") == before


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("root_name", "stored"),
    [("Grunt", "Grunt"), ("a\\b", "a\\\\b")],
    ids=["plain", "backslash"],
)
def test_the_root_name_is_honoured_and_written_as_the_saver_escapes_it(
    project, root_name, stored
):
    created = Gda(project).json(
        "scene",
        "create",
        "res://Goblin.tscn",
        "--inherits",
        "res://BaseEnemy.tscn",
        "--root-name",
        root_name,
    )

    assert created["root_name"] == root_name
    text = (project / "Goblin.tscn").read_text(encoding="utf-8")
    written = INHERITED_TEXT.fullmatch(text)
    assert written, text
    assert written["name"] == stored
    assert _runtime_tree(project, "res://Goblin.tscn")[0] == root_name


@pytest.mark.e2e
def test_the_base_is_loaded_not_instantiated_so_its_scripts_run_no_init(project):
    marker = project / "init.marker"
    (project / "base_enemy.gd").write_text(
        INIT_MARKER_GD.replace("{marker}", marker.as_posix()), encoding="utf-8"
    )
    gda = Gda(project)

    gda.json(
        "scene", "create", "res://Goblin.tscn", "--inherits", "res://BaseEnemy.tscn"
    )

    assert not marker.exists()
    # Control: booting the created scene does construct the base's script.
    gda.json("scene", "preflight", "res://Goblin.tscn")
    assert marker.exists()


@pytest.mark.e2e
def test_a_filesystem_path_base_is_written_and_echoed_as_its_res_path(project):
    created = Gda(project).json(
        "scene",
        "create",
        "res://Goblin.tscn",
        "--inherits",
        str(project / "BaseEnemy.tscn"),
    )

    assert created["inherits"] == "res://BaseEnemy.tscn"
    text = (project / "Goblin.tscn").read_text(encoding="utf-8")
    written = INHERITED_TEXT.fullmatch(text)
    assert written, text
    assert written["path"] == "res://BaseEnemy.tscn"
