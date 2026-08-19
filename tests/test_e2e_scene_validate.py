"""S1 (e2e): ``gda scene validate`` against the real Godot engine (#664).

The defect this closes (dogfooding GDA-DF-040) is only visible against a real
engine, so it is pinned here rather than with a canned payload: **loading a broken
scene succeeds**. Godot substitutes null for an `[ext_resource]` it cannot resolve,
prints an error to stderr, and still returns a usable `PackedScene` — so `scene get`
reports a healthy-looking tree for a scene whose script and texture are both gone.
These tests hold both halves: `scene get` still says nothing, and `scene validate`
returns the verdict.

The fixtures are raw `.tscn` text because the interesting ones are files gda cannot
author: a scene may not reference a script that does not exist, or one that does not
compile, through any gda command.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

GOOD_SCRIPT = """\
extends Node2D


func _ready() -> void:
	print("ready")
"""

BROKEN_SCRIPT = """\
extends Node2D


func _ready() -> void
	print("no colon on the signature line")
"""

GOOD_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://hero.gd" id="1_hero"]

[node name="Hero" type="Node2D"]
script = ExtResource("1_hero")
"""

# A scene whose script AND texture are both gone — the GDA-DF-040 shape.
MISSING_DEPS_TSCN = """\
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://gone.gd" id="1_gone"]
[ext_resource type="Texture2D" path="res://art/gone.png" id="2_art"]

[node name="Hero" type="Node2D"]
script = ExtResource("1_gone")

[node name="Sprite" type="Sprite2D" parent="."]
texture = ExtResource("2_art")
"""

BROKEN_SCRIPT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://broken.gd" id="1_broken"]

[node name="Hero" type="Node2D"]
script = ExtResource("1_broken")
"""


def _gda_project(project):
    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


@pytest.mark.e2e
def test_a_sound_scene_validates_and_names_the_project_it_resolved_against(
    godot_project,
):
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "hero.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://hero.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True
    assert data["problems"] == []
    # The root the res:// dependencies resolved against, absolute and always present.
    assert data["project_root"] == str(godot_project.resolve())


@pytest.mark.e2e
def test_missing_dependencies_are_reported_where_scene_get_reports_nothing(
    godot_project,
):
    (godot_project / "main.tscn").write_text(MISSING_DEPS_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    # BEFORE (GDA-DF-040): the read succeeds and the tree looks healthy — the missing
    # script and texture leave no trace in it. This is the gap, pinned.
    got = gda("scene", "get", "res://main.tscn", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    tree = json.loads(got.stdout)
    assert tree["root"]["name"] == "Hero"
    assert json.dumps(tree).find("gone") == -1

    # AFTER: the verdict names both unresolved files, what each was declared to be,
    # and which node references it.
    validated = gda("scene", "validate", "res://main.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "path": "res://gone.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        },
        {
            "kind": "missing_resource",
            "path": "res://art/gone.png",
            "type": "Texture2D",
            "nodes": ["Sprite"],
            "message": "the referenced file does not exist",
        },
    ]


@pytest.mark.e2e
def test_an_attached_script_that_does_not_compile_is_a_problem_not_a_failure(
    godot_project,
):
    (godot_project / "broken.gd").write_text(BROKEN_SCRIPT, encoding="utf-8")
    (godot_project / "main.tscn").write_text(BROKEN_SCRIPT_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://main.tscn", "--json")

    # An invalid scene is a SUCCESSFUL operation: exit 0, verdict in the result.
    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert len(data["problems"]) == 1
    problem = data["problems"][0]
    assert problem["kind"] == "script_compile_failed"
    assert problem["path"] == "res://broken.gd"
    assert problem["nodes"] == ["."]
    # The remedy points at the command that has the line and the message.
    assert "gda script validate res://broken.gd" in problem["message"]

    # And the two commands agree about the script: the same file is invalid there.
    script = gda("script", "validate", "res://broken.gd", "--json")
    assert script.returncode == 0, script.stdout + script.stderr
    assert json.loads(script.stdout)["valid"] is False


@pytest.mark.e2e
def test_an_asset_that_was_never_imported_is_unloadable_not_missing(godot_project):
    # A .png dropped into the project with no import artifacts: present on disk, but
    # a non-editor engine has no loader for it, so the running game would lose it
    # exactly as the scene does. The two conditions need different remedies, so they
    # are reported as different kinds.
    (godot_project / "dot.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000d4944415478da63fccf000000004010012a4f4b21"
            "0000000049454e44ae426082"
        )
    )
    (godot_project / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Texture2D" path="res://dot.png" id="1_dot"]\n\n'
        '[node name="Hero" type="Node2D"]\n\n'
        '[node name="Sprite" type="Sprite2D" parent="."]\n'
        'texture = ExtResource("1_dot")\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://main.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["problems"][0]["kind"] == "unloadable_resource"
    assert data["problems"][0]["path"] == "res://dot.png"
    assert data["problems"][0]["nodes"] == ["Sprite"]


@pytest.mark.e2e
def test_a_missing_scene_is_refused_not_reported_as_invalid(godot_project):
    # The addressing ladder does not fork for validate: what is not there cannot have
    # a verdict, so it is the same path_not_found every other scene command reports.
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://nosuch.tscn", "--json")

    assert validated.returncode == 4, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["error"]["code"] == "path_not_found"
