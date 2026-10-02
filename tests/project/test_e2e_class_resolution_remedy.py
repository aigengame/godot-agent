"""E2E: a class the engine could not resolve names `gda project scan` (#1073).

On a project the editor never opened there is no class index, so the GDScript
analyzer cannot find a project `class_name` and the op fails with its own code.
One CLI-side seam reads the engine's class-resolution errors in the captured
output and adds the remedy to the message and the class names to Failure
evidence. The code stays the verdict. When the index exists, the remedy is
conditional: the name can be a typo rather than a class the index misses.
Run e2e SERIALLY; not a fresh empty HOME.
"""

import pytest

from tests.project.class_index_project import components_project
from tests.support import Gda

HOLDER_TSCN = (
    "[gd_scene load_steps=2 format=3]\n"
    "\n"
    '[ext_resource type="Script" path="res://holder.gd" id="1"]\n'
    "\n"
    '[node name="Holder" type="Node"]\n'
    'script = ExtResource("1")\n'
)
# An entry script typed with a project class: it does not compile without the
# index, so `script run` reports that it did not run.
TYPED_RUN_GD = (
    "extends SceneTree\n"
    "\n"
    "func _initialize():\n"
    "\tvar a: AttackComponent = null\n"
    "\tprint(a)\n"
    "\tquit()\n"
)
TYPO_GD = "extends Node\n@export var c: AttackComponnt\n"


def _assert_no_scan_remedy(error, name):
    assert error["evidence"]["unresolved_classes"] == [name]
    message = error["message"]
    assert "gda project scan" in message
    assert "no scan has run" in message
    assert f"if {name} still fails after the scan" in message
    assert "not a class_name in this project" in message


@pytest.mark.e2e
def test_a_fresh_clone_names_the_unresolved_class_and_the_scan(tmp_path):
    project = components_project(tmp_path / "p")
    (project / "holder.tscn").write_text(HOLDER_TSCN, encoding="utf-8")
    (project / "typed_run.gd").write_text(TYPED_RUN_GD, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)

    node_set = gda.error(
        "node",
        "set",
        "res://holder.tscn",
        "--node",
        ".",
        "--property",
        "c",
        "--value",
        "null",
        code="unknown_property",
    )
    attached = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://holder.gd",
        code="script_compile_failed",
    )
    created = gda.error(
        "resource",
        "create",
        "res://f.tres",
        "--type",
        "FireAttack",
        code="uninstantiable_script",
    )
    ran = gda.error("script", "run", "res://typed_run.gd", code="script_compile_failed")

    for error in (node_set, attached, created, ran):
        _assert_no_scan_remedy(error, "AttackComponent")
    # The op's own sentence stays first: the remedy is added to it, not put in
    # its place.
    assert node_set["message"].startswith("node . has no settable property: c")
    # `script run` already carried evidence; the class names join it.
    assert ran["evidence"]["script_errors"]
    assert not (project / ".godot" / "global_script_class_cache.cfg").exists()


@pytest.mark.e2e
def test_with_the_index_present_a_misspelled_class_gets_the_conditional_remedy(
    tmp_path,
):
    project = components_project(tmp_path / "p")
    (project / "typo.gd").write_text(TYPO_GD, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)
    gda.json("project", "scan")

    error = gda.error(
        "script",
        "attach",
        "res://main.tscn",
        "--node",
        ".",
        "--script",
        "res://typo.gd",
        code="script_compile_failed",
    )

    assert error["evidence"]["unresolved_classes"] == ["AttackComponnt"]
    message = error["message"]
    assert "if AttackComponnt is a class_name in this project" in message
    assert "gda project scan" in message
    assert "no scan has run" not in message


def _tree(project):
    return sorted(
        str(path.relative_to(project)) for path in project.rglob("*") if path.is_file()
    )


def _calls_the_index_affects(gda):
    """Every non-scan call this file exercises, success or failure alike."""
    gda("script", "validate", "res://holder.gd")
    gda("scene", "validate", "res://holder.tscn")
    gda("scene", "preflight", "res://holder.tscn")
    gda("node", "set", "res://holder.tscn", "--node", ".", "--property", "c")
    gda("resource", "create", "res://f.tres", "--type", "FireAttack")
    gda("script", "run", "res://typed_run.gd")


@pytest.mark.e2e
def test_only_the_scan_writes_the_index_and_gda_keeps_no_freshness_file(tmp_path):
    # No implicit scan: the calls a stale or missing index affects leave the tree
    # as they found it, before a scan and after one. So no other command writes
    # the index, and gda writes no file of its own to track whether it is fresh.
    project = components_project(tmp_path / "p")
    (project / "holder.tscn").write_text(HOLDER_TSCN, encoding="utf-8")
    (project / "typed_run.gd").write_text(TYPED_RUN_GD, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)
    index = project / ".godot" / "global_script_class_cache.cfg"

    fresh = _tree(project)
    _calls_the_index_affects(gda)
    assert _tree(project) == fresh
    assert not index.exists()

    gda.json("project", "scan")
    scanned = _tree(project)
    written = index.read_bytes()
    _calls_the_index_affects(gda)
    # The one file added is the resource `resource create` was asked to write,
    # which now succeeds.
    assert _tree(project) == sorted([*scanned, "f.tres"])
    assert index.read_bytes() == written
