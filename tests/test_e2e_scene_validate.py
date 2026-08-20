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


# A dependency referenced from a [sub_resource] rather than from a node. Godot
# tolerates the node form (it substitutes null and the scene still loads) but
# hard-fails the WHOLE load for this one, which is why the verdict cannot be gated
# on the load succeeding.
SUB_RESOURCE_TSCN = """\
[gd_scene load_steps=3 format=3]

[ext_resource type="Texture2D" path="res://art/gone.png" id="1_gone"]

[sub_resource type="AtlasTexture" id="Atlas_1"]
atlas = ExtResource("1_gone")

[node name="Hero" type="Node2D"]

[node name="Sprite" type="Sprite2D" parent="."]
texture = SubResource("Atlas_1")
"""

# Re-saves a .tscn as a binary .scn, so the refusal below is tested against a REAL
# binary scene rather than a path that merely ends in .scn.
SAVE_AS_BINARY_GD = """\
extends SceneTree


func _initialize() -> void:
	var packed := ResourceLoader.load("res://hero.tscn", "PackedScene") as PackedScene
	var err := ResourceSaver.save(packed, "res://hero.scn")
	if err != OK:
		printerr("save failed: ", err)
	quit(0 if err == OK else 1)
"""


@pytest.mark.e2e
def test_a_dependency_broken_from_a_sub_resource_is_a_verdict_not_a_refusal(
    godot_project,
):
    # The load fails outright here, so gating the verdict on it would answer
    # `not_a_scene` about a file that IS a scene — hiding exactly the broken
    # dependency this command exists to report.
    (godot_project / "main.tscn").write_text(SUB_RESOURCE_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://main.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    problem = data["problems"][0]
    assert problem["kind"] == "missing_resource"
    assert problem["path"] == "res://art/gone.png"
    # No node references it directly — a sub-resource does — so the attribution is
    # empty rather than wrong.
    assert problem["nodes"] == []


@pytest.mark.e2e
def test_a_binary_scene_is_refused_rather_than_reported_valid(godot_project):
    # The regression this guards is the worst answer a gate can give: the dependency
    # set is read from the scene's TEXT, and a binary .scn carries none — so a
    # dependency walk over one finds nothing and would report a clean verdict for a
    # scene with definitively broken dependencies.
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "hero.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    (godot_project / "save_binary.gd").write_text(SAVE_AS_BINARY_GD, encoding="utf-8")
    gda = _gda_project(godot_project)

    saved = gda("script", "run", "res://save_binary.gd", "--json")
    assert saved.returncode == 0, saved.stdout + saved.stderr
    assert (godot_project / "hero.scn").exists(), saved.stdout + saved.stderr
    # Break it AFTER the binary was written, so the .scn genuinely references a
    # script that is now gone.
    (godot_project / "hero.gd").unlink()

    validated = gda("scene", "validate", "res://hero.scn", "--json")

    assert validated.returncode == 4, validated.stdout + validated.stderr
    error = json.loads(validated.stdout)["error"]
    assert error["code"] == "invalid_path"
    assert ".tscn" in error["message"]

    # And the text form of the same broken scene is still answered, so the refusal
    # is about the FORM gda can read, not about the scene.
    text_verdict = gda("scene", "validate", "res://hero.tscn", "--json")
    assert text_verdict.returncode == 0, text_verdict.stdout + text_verdict.stderr
    assert json.loads(text_verdict.stdout)["valid"] is False


# An `extends Resource` script on a Node2D: it compiles, every file resolves, and
# the engine still refuses the binding at instance time — the PR #720 review's
# first false positive.
RESOURCE_SCRIPT = """\
extends Resource


func describe() -> String:
	return "a resource script"
"""

INCOMPATIBLE_BINDING_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://res_script.gd" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""

# A syntax error inside an EMBEDDED [sub_resource type="GDScript"]: it is not an
# [ext_resource], so the dependency walk never sees it — the review's second
# false positive.
BROKEN_EMBEDDED_TSCN = """\
[gd_scene load_steps=2 format=3]

[sub_resource type="GDScript" id="GDScript_1"]
script/source = "extends Node
func _ready() -> void:
	this is not gdscript at all
"

[node name="Root" type="Node"]
script = SubResource("GDScript_1")
"""


@pytest.mark.e2e
def test_an_incompatible_script_binding_is_a_problem_not_a_pass(godot_project):
    (godot_project / "res_script.gd").write_text(RESOURCE_SCRIPT, encoding="utf-8")
    (godot_project / "badbind.tscn").write_text(
        INCOMPATIBLE_BINDING_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://badbind.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "incompatible_script"
    assert problem["path"] == "res://res_script.gd"
    assert problem["nodes"] == ["."]
    assert "extends Resource" in problem["message"]
    assert "Node2D" in problem["message"]


@pytest.mark.e2e
def test_a_broken_embedded_script_is_a_problem_not_a_pass(godot_project):
    (godot_project / "badembed.tscn").write_text(BROKEN_EMBEDDED_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://badembed.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "script_compile_failed"
    # The embedded script's identity is its ::id sub-resource address.
    assert problem["path"] == "res://badembed.tscn::GDScript_1"
    assert problem["nodes"] == ["."]


# A plain Resource declared `type="Script"` — the #709 review's counterexample.
# Every file resolves and loads, but the value bound to the script slot is not a
# Script, so the engine refuses the assignment at instance time ("Cannot set
# object script") and the node boots script-less.
PLAIN_RESOURCE_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""

NOT_A_SCRIPT_BINDING_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://data.tres" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""

# The same shape reached through an EMBEDDED [sub_resource]: no [ext_resource]
# line exists, so only the loaded scene's state can see it.
EMBEDDED_NOT_A_SCRIPT_TSCN = """\
[gd_scene load_steps=2 format=3]

[sub_resource type="Resource" id="Resource_1"]

[node name="Root" type="Node2D"]
script = SubResource("Resource_1")
"""


@pytest.mark.e2e
def test_a_non_script_resource_declared_as_script_is_a_problem_not_a_pass(
    godot_project,
):
    (godot_project / "data.tres").write_text(PLAIN_RESOURCE_TRES, encoding="utf-8")
    (godot_project / "notascript.tscn").write_text(
        NOT_A_SCRIPT_BINDING_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://notascript.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "incompatible_script"
    assert problem["path"] == "res://data.tres"
    assert problem["nodes"] == ["."]
    assert "not a Script" in problem["message"]


@pytest.mark.e2e
def test_an_embedded_non_script_bound_as_script_is_a_problem_not_a_pass(
    godot_project,
):
    (godot_project / "embednotascript.tscn").write_text(
        EMBEDDED_NOT_A_SCRIPT_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://embednotascript.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "incompatible_script"
    assert problem["path"] == "res://embednotascript.tscn::Resource_1"
    assert problem["nodes"] == ["."]
    assert "not a Script" in problem["message"]


@pytest.mark.e2e
def test_a_tscn_that_is_not_a_scene_document_is_refused_not_diagnosed(godot_project):
    # A dependency finding must not bypass scene admission (#720 review): garbage
    # text carrying an [ext_resource] line used to come back as a scene VERDICT.
    (godot_project / "garbage.tscn").write_text(
        '[ext_resource type="Texture2D" path="res://missing.png" id="1"]\n'
        "this is not a scene file at all\n",
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://garbage.tscn", "--json")

    payload = json.loads(validated.stdout)
    assert payload["error"]["code"] == "not_a_scene"


@pytest.mark.e2e
def test_a_header_that_merely_starts_with_gd_scene_is_still_refused(godot_project):
    # Admission must recognize the COMPLETE section header, not a prefix (#720
    # recheck): `[gd_scenery]` names a different section, so a dependency line
    # inside it must not buy the file a scene verdict.
    (godot_project / "scenery.tscn").write_text(
        "[gd_scenery]\n"
        "\n"
        '[ext_resource type="Texture2D" path="res://missing.png" id="1_missing"]\n'
        "\n"
        "this is not a Godot scene\n",
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://scenery.tscn", "--json")

    payload = json.loads(validated.stdout)
    assert payload["error"]["code"] == "not_a_scene"


@pytest.mark.e2e
def test_an_unclosed_gd_scene_header_is_still_refused(godot_project):
    # Admission must require the header LINE to close (#720 recheck ×2): with a
    # dependency problem in the text the load is skipped, so an unclosed
    # `[gd_scene …` would otherwise buy garbage a scene verdict with no
    # downstream check left to catch it.
    (godot_project / "unclosed.tscn").write_text(
        "[gd_scene load_steps=2 format=3\n"
        "\n"
        '[ext_resource type="Texture2D" path="res://missing.png" id="1_missing"]\n'
        "\n"
        "this is not a Godot scene\n",
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://unclosed.tscn", "--json")

    payload = json.loads(validated.stdout)
    assert payload["error"]["code"] == "not_a_scene"
