"""E2E: every refusal of the class_name instancing ladder, as `node add --type`
and `resource create --type` report it (#1192).

The ladder takes a class token from the built-in class through the resolver
(ADR-0032) and the script's load, compile, stale-entry (#1073) and constructor
checks to the base-class check. Each step refuses with its own code and message,
and the two groups differ only in the base class, the unknown and wrong-base
code, and that noun. The project is scanned once and then changed with no
second scan, so each class meets exactly one step.
"""

import json

import pytest

from tests.conftest import project_godot
from tests.support import Gda

# Classes that the scan indexes and that are then changed on disk.
GONE_GD = "class_name Gone\nextends Node\n"
BROKEN_GD = "class_name Broken\nextends Node\n"
BROKEN_AFTER_SCAN_GD = "class_name Broken\nextends Node\nfunc broken( -> void:\n"
RENAMED_GD = "class_name Renamed\nextends Node\n"
RENAMED_AFTER_SCAN_GD = "class_name Moved\nextends Node\n"
NEEDS_ARGS_GD = "class_name NeedsArgs\nextends Node\n\n\nfunc _init(speed: float) -> void:\n\tpass\n"
# The two wrong-base classes report when their constructor runs and when the
# instance is freed, so the diagnostics show that each runs once.
LOOT_GD = """\
class_name Loot
extends Resource


func _init() -> void:
\tprinterr("Loot _init")


func _notification(what: int) -> void:
\tif what == NOTIFICATION_PREDELETE:
\t\tprinterr("Loot freed")
"""
WIDGET_GD = """\
class_name Widget
extends Node


func _init() -> void:
\tprinterr("Widget _init")


func _notification(what: int) -> void:
\tif what == NOTIFICATION_PREDELETE:
\t\tprinterr("Widget freed")
"""
# Written after the scan: not in the index, so the static scan finds both.
DUP_GD = "class_name Dup\nextends Resource\n"
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'

UNKNOWN = (
    "not an instantiable {base} class, and no .gd script declares class_name {type}"
    " (check for a misspelled name, or declare it with `class_name {type}`)"
)
SHARED_REFUSALS = {
    "Dup": (
        "ambiguous_class_name",
        "class_name Dup is declared in more than one script, so it cannot be"
        " resolved to a single script; declare it in exactly one .gd. Conflicting"
        " scripts: res://dup_a.gd, res://dup_b.gd",
    ),
    "Gone": (
        "uninstantiable_script",
        "registered class_name Gone script failed to load: res://gone.gd"
        " — broken or removed since the project scan; see diagnostics",
    ),
    "Broken": (
        "uninstantiable_script",
        "registered class_name Broken script cannot be instantiated: res://broken.gd"
        " — it no longer compiles; see diagnostics",
    ),
    "Renamed": (
        "class_index_stale",
        "the class index is stale: its entry Renamed names res://renamed.gd, which"
        " now declares class_name Moved; run `gda project scan` and retry (nothing"
        " was written)",
    ),
    "NeedsArgs": (
        "uninstantiable_script",
        "registered class_name NeedsArgs script constructor failed:"
        " res://needs_args.gd — its _init may require arguments; see diagnostics",
    ),
}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    project = tmp_path_factory.mktemp("class-instancing")
    (project / "project.godot").write_text(
        project_godot(name="gda-class-instancing"), encoding="utf-8"
    )
    for name, text in {
        "gone.gd": GONE_GD,
        "broken.gd": BROKEN_GD,
        "renamed.gd": RENAMED_GD,
        "needs_args.gd": NEEDS_ARGS_GD,
        "loot.gd": LOOT_GD,
        "widget.gd": WIDGET_GD,
        "main.tscn": MAIN_TSCN,
    }.items():
        (project / name).write_text(text, encoding="utf-8")
    Gda(project, timeout=300).json("project", "scan")
    (project / "gone.gd").unlink()
    (project / "broken.gd").write_text(BROKEN_AFTER_SCAN_GD, encoding="utf-8")
    (project / "renamed.gd").write_text(RENAMED_AFTER_SCAN_GD, encoding="utf-8")
    for name in ("dup_a.gd", "dup_b.gd"):
        (project / name).write_text(DUP_GD, encoding="utf-8")
    return project


def _errors(gda, argv, types):
    """The error each class token is refused with; each refusal exits 4."""
    errors = {}
    for type_token in types:
        result = gda(*argv, "--type", type_token, "--json")
        assert result.returncode == 4, result.stdout + result.stderr
        errors[type_token] = json.loads(result.stdout)["error"]
    return errors


def _refusals(errors):
    return {token: (error["code"], error["message"]) for token, error in errors.items()}


def _project_code_lines(diagnostics, class_token):
    """The lines the class's own script printed, in order."""
    lines = (line.strip() for line in diagnostics.splitlines())
    return [line for line in lines if line.startswith(class_token + " ")]


@pytest.mark.e2e
def test_node_add_names_each_step_of_the_ladder_that_refused(project):
    gda = Gda(project)
    scene_before = (project / "main.tscn").read_bytes()
    argv = ("node", "add", "res://main.tscn", "--name", "N")

    errors = _errors(gda, argv, ["Nope", "Resource", *SHARED_REFUSALS, "Loot"])

    assert _refusals(errors) == {
        "Nope": ("invalid_node_type", UNKNOWN.format(base="Node", type="Nope")),
        "Resource": ("invalid_node_type", UNKNOWN.format(base="Node", type="Resource")),
        **SHARED_REFUSALS,
        "Loot": (
            "invalid_node_type",
            "registered class_name Loot is not a Node-derived script: res://loot.gd",
        ),
    }
    assert (project / "main.tscn").read_bytes() == scene_before
    assert _project_code_lines(errors["Loot"]["diagnostics"], "Loot") == [
        "Loot _init",
        "Loot freed",
    ]


@pytest.mark.e2e
def test_resource_create_names_each_step_of_the_ladder_that_refused(project):
    gda = Gda(project)
    argv = ("resource", "create", "res://made.tres")

    errors = _errors(gda, argv, ["Nope", "Node2D", *SHARED_REFUSALS, "Widget"])

    assert _refusals(errors) == {
        "Nope": ("invalid_resource_type", UNKNOWN.format(base="Resource", type="Nope")),
        "Node2D": (
            "invalid_resource_type",
            UNKNOWN.format(base="Resource", type="Node2D"),
        ),
        **SHARED_REFUSALS,
        "Widget": (
            "invalid_resource_type",
            "registered class_name Widget is not a Resource-derived script:"
            " res://widget.gd",
        ),
    }
    assert not (project / "made.tres").exists()
    assert _project_code_lines(errors["Widget"]["diagnostics"], "Widget") == [
        "Widget _init",
        "Widget freed",
    ]
