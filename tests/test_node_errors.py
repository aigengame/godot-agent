"""S3: gda node failure modes map to structured JSON errors + stable exit codes.

Issue #53's acceptance: node-command failures (scene not found, bad parent
path, invalid type, name collision) surface as structured ``GdaError``s with
registered operation codes (ADR-0002) — exit 4 for the operation category,
finer stable codes so an agent can branch on the mode without parsing prose.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke_node_add(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: node-add\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(
        app,
        ["node", "add", "/x/main.tscn", "--type", "Sprite2D", "--json"],
    )


def test_node_add_bad_parent_maps_to_stable_parent_not_found_code(monkeypatch):
    # The scene exists but the requested parent node path resolves to nothing —
    # a new node-group code, distinct from the file-level path_not_found, so an
    # agent knows to fix the node path, not the scene path.
    result = _invoke_node_add(
        monkeypatch, "parent_not_found", "parent node not found in scene: Bogus/Path"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "parent_not_found"
    assert "Bogus/Path" in err["message"]
    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert err["diagnostics"] == "gda: running operation: node-add\n"


def test_node_add_non_canonical_parent_maps_to_stable_parent_not_found_code(
    monkeypatch,
):
    # Issue #66: a non-canonical parent path ("A/..", "A/", "./A", …) is
    # rejected by the operation rather than silently resolved to a node the
    # literal string never named. The refusal reuses the registered
    # parent_not_found code — under strict addressing the path resolves to
    # nothing — with a message naming the canonical form. Mapping pin: the
    # envelope rides through the same parent_not_found path as a missing
    # canonical parent.
    result = _invoke_node_add(
        monkeypatch,
        "parent_not_found",
        "non-canonical parent path: A/.. — address the parent exactly as "
        "node list reports it: '.' for the root, 'A/B' for a descendant",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "parent_not_found"
    assert "A/.." in err["message"]
    assert "non-canonical" in err["message"]


def test_node_add_unknown_type_maps_to_stable_invalid_node_type_code(monkeypatch):
    result = _invoke_node_add(
        monkeypatch,
        "invalid_node_type",
        "not an instantiable Node class or registered class_name: Foo",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_node_type"
    assert "Foo" in err["message"]


def test_node_add_name_collision_maps_to_stable_duplicate_node_name_code(monkeypatch):
    result = _invoke_node_add(
        monkeypatch, "duplicate_node_name", "parent already has a child named: Hero"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "duplicate_node_name"
    assert "Hero" in err["message"]


def test_node_add_bad_name_maps_to_stable_invalid_node_name_code(monkeypatch):
    result = _invoke_node_add(
        monkeypatch, "invalid_node_name", "invalid name: Bad%Name"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_node_name"
    assert "Bad%Name" in err["message"]


def test_node_add_vanished_instance_maps_to_stable_missing_dependency_code(monkeypatch):
    # Issue #64: a scene whose instanced sub-scene cannot be resolved on load
    # would lose the whole instance on re-save; the refusal surfaces as the
    # registered missing_dependency code so an agent knows to fix the scene's
    # dependencies or its project context rather than retry the add.
    result = _invoke_node_add(
        monkeypatch,
        "missing_dependency",
        "scene nodes vanished on load (unresolvable instanced sub-scene?): "
        "ChildInstance — re-saving would silently drop them",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "missing_dependency"
    assert "ChildInstance" in err["message"]


def test_node_add_substituted_class_maps_to_stable_missing_dependency_code(monkeypatch):
    # Issue #64's degraded mode: a declared class unavailable in this engine
    # run materializes as a substitute node, so a re-save would rewrite its
    # type. The refusal reuses missing_dependency — an unavailable class IS a
    # missing dependency (extension/module), the same agent fix applies.
    result = _invoke_node_add(
        monkeypatch,
        "missing_dependency",
        "scene nodes vanished or degraded on load: "
        "Widget (declared TotallyMissingClass, materialized Node) — "
        "re-saving would silently drop or downgrade them",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "missing_dependency"
    assert "declared TotallyMissingClass, materialized Node" in err["message"]


def test_node_add_broken_class_name_maps_to_stable_uninstantiable_script_code(
    monkeypatch,
):
    # Issue #65: a class_name still present in the global class list but whose
    # script broke after registration is a script problem, not an unknown type.
    # The refusal surfaces as the registered uninstantiable_script code so an
    # agent knows to repair the script rather than the type name.
    result = _invoke_node_add(
        monkeypatch,
        "uninstantiable_script",
        "registered class_name Hero script cannot be instantiated: "
        "res://hero.gd — it no longer compiles; see diagnostics",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "uninstantiable_script"
    assert "res://hero.gd" in err["message"]


def test_node_add_missing_scene_reuses_stable_path_not_found_code(monkeypatch):
    # The scene-file-level failure reuses the registered scene code: the
    # node group introduces no parallel code for the same mode.
    result = _invoke_node_add(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/main.tscn" in err["message"]
