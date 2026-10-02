"""E2E: a stale class-index entry is refused or reported, never written (#1073).

The one stale state that still compiles: a `class_name` renamed (or removed) with
no scan. The index keeps the old entry, the script compiles under its new name,
and a resolver consumer that trusted the entry would write the new name under
the old one. One predicate decides it — does the compiled script still declare
the entry's class? — and its two uses are the write refusal
(`class_index_stale`) and the validate verdict.
Run e2e SERIALLY; not a fresh empty HOME.
"""

import pytest

from tests.project.class_index_project import components_project, rename_class
from tests.support import Gda


def _scanned_then_renamed(tmp_path):
    project = components_project(tmp_path / "p")
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")
    rename_class(project, "attack_component.gd", "AttackComponent", "AttackComp")
    rename_class(project, "mover.gd", "Mover", "Walker")
    return project, gda


@pytest.mark.e2e
def test_a_write_through_a_stale_entry_is_refused_and_writes_nothing(tmp_path):
    project, gda = _scanned_then_renamed(tmp_path)
    scene_before = (project / "main.tscn").read_bytes()

    created = gda.error(
        "resource",
        "create",
        "res://stale.tres",
        "--type",
        "AttackComponent",
        code="class_index_stale",
    )
    added = gda.error(
        "node",
        "add",
        "res://main.tscn",
        "--type",
        "Mover",
        "--name",
        "M",
        code="class_index_stale",
    )

    for error in (created, added):
        assert "gda project scan" in error["message"]
    assert "AttackComp" in created["message"]
    assert "Walker" in added["message"]
    assert not (project / "stale.tres").exists()
    assert (project / "main.tscn").read_bytes() == scene_before


HOLDER_TSCN = (
    "[gd_scene load_steps=2 format=3]\n"
    "\n"
    '[ext_resource type="Script" path="res://holder.gd" id="1"]\n'
    "\n"
    '[node name="Holder" type="Node"]\n'
    'script = ExtResource("1")\n'
)
# A script that uses a class whose BASE is the stale class: the chain case.
USES_FIRE_GD = "extends Node\n@export var f: FireAttack\n"

_STALE_ATTACK = {
    "name": "AttackComponent",
    "path": "res://attack_component.gd",
    "declared_name": "AttackComp",
}


def _validate_both(gda):
    script = gda.json("script", "validate", "res://holder.gd")
    scene = gda.json("scene", "validate", "res://holder.tscn")
    return script, scene


@pytest.mark.e2e
def test_validate_reports_a_renamed_class_as_a_stale_entry_until_a_scan(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "holder.tscn").write_text(HOLDER_TSCN, encoding="utf-8")
    (project / "uses_fire.gd").write_text(USES_FIRE_GD, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")
    rename_class(project, "attack_component.gd", "AttackComponent", "AttackComp")

    script, scene = _validate_both(gda)

    # The scripts still compile, so the per-script verdict keeps its meaning;
    # the aggregate is invalid because the index entry is stale.
    assert script["scripts"][0]["valid"] is True
    assert (script["valid"], script["stale_class_entries"]) == (False, [_STALE_ATTACK])
    assert (scene["valid"], scene["problems"]) == (False, [])
    assert scene["stale_class_entries"] == [_STALE_ATTACK]
    # The chain: a script typed with a class whose base is the stale class.
    chain = gda.json("script", "validate", "res://uses_fire.gd")
    assert (chain["valid"], chain["stale_class_entries"]) == (False, [_STALE_ATTACK])
    # The human verdict names the remedy.
    human = Gda(project, timeout=300)("script", "validate", "res://holder.gd")
    assert "gda project scan" in human.stdout, human.stdout

    # After a scan, both report the engine's own errors and no stale entry.
    gda.json("project", "scan")
    script, scene = _validate_both(gda)
    assert script["scripts"][0]["valid"] is False
    assert script["stale_class_entries"] == []
    assert any(
        'Could not find type "AttackComponent"' in d["message"]
        for d in script["scripts"][0]["diagnostics"]
    ), script
    assert scene["valid"] is False
    assert scene["stale_class_entries"] == []
    assert [p["kind"] for p in scene["problems"]] == ["script_compile_failed"], scene


@pytest.mark.e2e
def test_validate_reports_a_removed_class_name_as_a_stale_entry(tmp_path):
    project = components_project(tmp_path / "p")
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")
    path = project / "attack_component.gd"
    path.write_text(
        path.read_text(encoding="utf-8").replace("class_name AttackComponent ", "", 1),
        encoding="utf-8",
    )

    script = gda.json("script", "validate", "res://holder.gd")

    assert script["valid"] is False
    assert script["stale_class_entries"] == [{**_STALE_ATTACK, "declared_name": ""}]


@pytest.mark.e2e
def test_a_stale_entry_an_autoload_reaches_makes_every_validate_invalid(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "game_state.gd").write_text(
        "extends Node\nvar c: AttackComponent\n", encoding="utf-8"
    )
    with (project / "project.godot").open("a", encoding="utf-8") as config:
        config.write('\n[autoload]\n\nGameState="*res://game_state.gd"\n')
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")
    rename_class(project, "attack_component.gd", "AttackComponent", "AttackComp")

    # mover.gd uses no project class; the autoload loaded the stale script at
    # startup, before the op ran.
    unrelated = gda.json("script", "validate", "res://mover.gd")

    assert unrelated["scripts"][0]["valid"] is True
    assert (unrelated["valid"], unrelated["stale_class_entries"]) == (
        False,
        [_STALE_ATTACK],
    )


BROKEN_NODE_GD = "class_name BrokenNode extends Node\n\nfunc f(\n"
BROKEN_RES_GD = "class_name BrokenRes extends Resource\n\nfunc f(\n"
BROKEN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n"
    "\n"
    '[ext_resource type="Script" path="res://broken_node.gd" id="1"]\n'
    "\n"
    '[node name="Broken" type="Node"]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_a_script_that_does_not_compile_is_never_a_stale_entry(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "broken_node.gd").write_text(BROKEN_NODE_GD, encoding="utf-8")
    (project / "broken_res.gd").write_text(BROKEN_RES_GD, encoding="utf-8")
    (project / "broken.tscn").write_text(BROKEN_TSCN, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)
    scanned = gda.json("project", "scan")
    assert {"BrokenNode", "BrokenRes"} <= {c["name"] for c in scanned["classes"]}

    script = gda.json("script", "validate", "res://broken_node.gd")
    scene = gda.json("scene", "validate", "res://broken.tscn")

    assert script["scripts"][0]["valid"] is False
    assert script["scripts"][0]["diagnostics"], script
    assert script["stale_class_entries"] == []
    assert [p["kind"] for p in scene["problems"]] == ["script_compile_failed"]
    assert scene["stale_class_entries"] == []
    gda.error(
        "resource",
        "create",
        "res://broken.tres",
        "--type",
        "BrokenRes",
        code="uninstantiable_script",
    )
    assert not (project / "broken.tres").exists()
