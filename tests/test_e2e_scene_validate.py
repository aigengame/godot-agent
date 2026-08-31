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
            # Its own file: every problem names where it was found, the scene the
            # command was given included (#721).
            "scene": "res://main.tscn",
            "path": "res://gone.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        },
        {
            "kind": "missing_resource",
            "scene": "res://main.tscn",
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


# --- The COMPOSED verdict (#721) --------------------------------------------
#
# A parent that instances a broken child. The parent's own walk cannot see the
# break: `res://child.tscn` exists, `ResourceLoader` opens it, and Godot hands back
# a usable PackedScene with the missing script substituted by null — so the parent
# used to validate clean while the child validated broken. Only a real engine shows
# that, which is why these live here.

COMPOSED_CHILD_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://missing_script.gd" id="1_gone"]

[node name="Child" type="Node2D"]
script = ExtResource("1_gone")
"""

COMPOSED_PARENT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://child.tscn" id="1_child"]

[node name="Parent" type="Node2D"]

[node name="ChildInstance" parent="." instance=ExtResource("1_child")]
"""


@pytest.mark.e2e
def test_an_instanced_broken_child_makes_the_parent_invalid(godot_project):
    (godot_project / "child.tscn").write_text(COMPOSED_CHILD_TSCN, encoding="utf-8")
    (godot_project / "parent.tscn").write_text(COMPOSED_PARENT_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    # The child's own verdict is the reference answer.
    child = gda("scene", "validate", "res://child.tscn", "--json")
    assert child.returncode == 0, child.stdout + child.stderr
    assert json.loads(child.stdout)["valid"] is False

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    # Attributed to the CHILD file: `nodes: ["."]` is the child's root, not the
    # parent's, and a reader that missed that would look for a script slot on
    # res://parent.tscn's root that has never had one.
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://child.tscn",
            "path": "res://missing_script.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        }
    ]


@pytest.mark.e2e
def test_a_sound_composed_scene_is_still_valid_and_each_file_checked_once(
    godot_project,
):
    # Two levels deep AND a diamond: `leaf.tscn` is instanced twice by `mid.tscn`
    # and once directly by `top.tscn`. A sound composition must stay `valid: true`
    # — the composed walk is worthless if it invents problems — and the same file
    # reached three ways must be one file when it does break.
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "leaf.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    (godot_project / "mid.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://leaf.tscn" id="1_leaf"]\n\n'
        '[node name="Mid" type="Node2D"]\n\n'
        '[node name="LeafA" parent="." instance=ExtResource("1_leaf")]\n\n'
        '[node name="LeafB" parent="." instance=ExtResource("1_leaf")]\n',
        encoding="utf-8",
    )
    (godot_project / "top.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://mid.tscn" id="1_mid"]\n'
        '[ext_resource type="PackedScene" path="res://leaf.tscn" id="2_leaf"]\n\n'
        '[node name="Top" type="Node2D"]\n\n'
        '[node name="MidInstance" parent="." instance=ExtResource("1_mid")]\n\n'
        '[node name="LeafDirect" parent="." instance=ExtResource("2_leaf")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://top.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["problems"] == []

    # Now break the leaf's script. One broken FILE is one problem however many
    # instancing sites reach it.
    (godot_project / "hero.gd").unlink()

    rechecked = gda("scene", "validate", "res://top.tscn", "--json")

    assert rechecked.returncode == 0, rechecked.stdout + rechecked.stderr
    broken = json.loads(rechecked.stdout)
    assert broken["valid"] is False
    assert broken["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://leaf.tscn",
            "path": "res://hero.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        }
    ]


@pytest.mark.e2e
def test_an_instancing_cycle_terminates_with_a_diagnostic(godot_project):
    # Hand-written text can close a cycle the editor would refuse to create, and
    # gda's own commands write scenes as text. Termination is not enough: a walk
    # that merely stopped would report `valid: true` for a composition Godot
    # refuses to load.
    (godot_project / "a.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://b.tscn" id="1_b"]\n\n'
        '[node name="A" type="Node2D"]\n\n'
        '[node name="BInstance" parent="." instance=ExtResource("1_b")]\n',
        encoding="utf-8",
    )
    (godot_project / "b.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://a.tscn" id="1_a"]\n\n'
        '[node name="B" type="Node2D"]\n\n'
        '[node name="AInstance" parent="." instance=ExtResource("1_a")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://a.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "cyclic_instance"
    # Reported against the file that DECLARES the closing edge, naming the
    # ancestor it re-instances — the pair a reader needs to break the cycle.
    assert problem["scene"] == "res://b.tscn"
    assert problem["path"] == "res://a.tscn"
    assert problem["nodes"] == ["AInstance"]


@pytest.mark.e2e
def test_a_scene_that_instances_itself_is_one_cycle_not_a_hang(godot_project):
    # The degenerate cycle, and the one a text-writing agent hits first.
    (godot_project / "self.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://self.tscn" id="1_self"]\n\n'
        '[node name="Self" type="Node2D"]\n\n'
        '[node name="Inner" parent="." instance=ExtResource("1_self")]\n\n'
        '[node name="Inner2" parent="." instance=ExtResource("1_self")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://self.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    # ONE cycle, though two nodes close it: the same per-file rule the rest of the
    # walk applies, with both instancing sites merged under `nodes`.
    (problem,) = [p for p in data["problems"] if p["kind"] == "cyclic_instance"]
    assert problem["scene"] == "res://self.tscn"
    assert problem["path"] == "res://self.tscn"
    assert problem["nodes"] == ["Inner", "Inner2"]


@pytest.mark.e2e
def test_a_missing_sub_scene_is_the_parents_problem_and_not_reported_twice(
    godot_project,
):
    # The descent's boundary: a sub-scene gda cannot read gets no problem of its
    # own, because the parent's dependency walk already named it. One problem, not
    # two views of one.
    (godot_project / "parent.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://gone.tscn" id="1_gone"]\n\n'
        '[node name="Parent" type="Node2D"]\n\n'
        '[node name="Missing" parent="." instance=ExtResource("1_gone")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://parent.tscn",
            "path": "res://gone.tscn",
            "type": "PackedScene",
            "nodes": ["Missing"],
            "message": "the referenced file does not exist",
        }
    ]


# --- The depth bound (#721 review) ------------------------------------------
#
# The walk's own cost, not the engine's. Measured on Godot 4.6.3 against a chain
# of N scenes each instancing the next: the pre-#721 command is flat at ~2s for
# N=100 and N=300 (it does ONE load and the engine walks the chain internally),
# while the unbounded composed walk went 5-7s at N=100 and 38-47s at N=300 —
# close enough to the 60s launch ceiling to cross it into launch_timeout under
# machine load. Bounded, the same chains take 3-4s and 5-6s.
#
# What the bound does NOT do, and no test here may be read as claiming: make a
# deep chain safe. At N=1200 the engine's own loader overflows its stack and the
# run dies with signal 11 — on the PRE-#721 base too, where no gda recursion
# exists at all. That failure arrives through the single top-level load, which
# the bound does not touch.


def _write_instance_chain(project, depth: int) -> None:
    """A straight chain: s0 instances s1 instances s2 … down to a plain leaf."""
    (project / f"s{depth}.tscn").write_text(
        f'[gd_scene format=3]\n\n[node name="S{depth}" type="Node2D"]\n',
        encoding="utf-8",
    )
    for level in range(depth - 1, -1, -1):
        (project / f"s{level}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="res://s{level + 1}.tscn" id="1_c"]\n\n'
            f'[node name="S{level}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )


@pytest.mark.e2e
def test_a_chain_at_the_depth_bound_is_still_fully_validated(godot_project):
    # 16 levels of sub-scenes below the validated scene is INSIDE the bound, so
    # the verdict is a real one. This is the half that keeps the bound honest: a
    # cap that fires early would turn ordinary compositions into non-answers.
    _write_instance_chain(godot_project, 16)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://s0.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["problems"] == []


@pytest.mark.e2e
def test_past_the_depth_bound_the_walk_stops_and_says_so(godot_project):
    # One level further. The walk stops at the edge into s17 and reports it —
    # rather than answering `valid: true` about a subtree it never looked at.
    _write_instance_chain(godot_project, 17)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://s0.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "instance_depth_exceeded"
    # Reported against the file holding the declining edge, naming the subtree
    # that was not checked — the pair a reader needs to validate it directly.
    assert problem["scene"] == "res://s16.tscn"
    assert problem["path"] == "res://s17.tscn"
    assert problem["nodes"] == ["Child"]
    assert "UNCHECKED" in problem["message"]


@pytest.mark.e2e
def test_the_bound_does_not_hide_a_break_above_it(godot_project):
    # The subtree past the bound is unchecked, but everything inside it still is:
    # a break at level 3 of a 17-deep chain is reported alongside the bound entry,
    # not swallowed by it.
    _write_instance_chain(godot_project, 17)
    (godot_project / "s3.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://s4.tscn" id="1_c"]\n'
        '[ext_resource type="Script" path="res://gone.gd" id="2_gone"]\n\n'
        '[node name="S3" type="Node2D"]\n'
        'script = ExtResource("2_gone")\n\n'
        '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://s0.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    kinds = {(p["kind"], p["scene"]) for p in data["problems"]}
    assert ("missing_resource", "res://s3.tscn") in kinds
    assert ("instance_depth_exceeded", "res://s16.tscn") in kinds


# --- The composition BOUNDARY (#721 review) ---------------------------------
#
# What the walk composes over is the referenced scene FILE, and these pin both
# halves of that against the engine, because the engine is the only authority on
# it. Measured on Godot 4.6.3 while answering the review: `ResourceLoaderText`
# starts a load for EVERY `[ext_resource]` line before it parses a single node,
# and passes the line's `type` to `ResourceLoader` only as a hint — the format
# handler is chosen by extension and accepts every type. So the declared type is
# not a selector, and a `.tscn` referenced as plain metadata breaks its owner
# exactly as an instanced one does.

# A .tscn referenced as ordinary `Resource` metadata and never instanced. The
# review called following this an over-reach; the engine disagrees.
DATA_REFERENCE_PARENT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Resource" path="res://child.tscn" id="1_child"]

[node name="Parent" type="Node2D"]
metadata/other_scene = ExtResource("1_child")
"""


@pytest.mark.e2e
def test_a_sub_scene_referenced_as_data_still_breaks_its_owner(godot_project):
    # The measurement this test exists for: loading the parent below emits the
    # SAME three errors for the child's missing script as a parent that instances
    # it (`Attempt to open script … File not found`, `Failed loading resource`,
    # `res://child.tscn:… Parse Error: [ext_resource] referenced non-existent
    # resource`). Selecting edges on `type="PackedScene"` would answer
    # `valid: true` here, so the extension is the sounder rule — and there is no
    # honest fallback for a line with no type at all, since the engine rejects
    # such a file outright (ERR_FILE_CORRUPT).
    (godot_project / "child.tscn").write_text(COMPOSED_CHILD_TSCN, encoding="utf-8")
    (godot_project / "parent.tscn").write_text(
        DATA_REFERENCE_PARENT_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "missing_resource"
    assert problem["scene"] == "res://child.tscn"
    # Attributed to the node whose PROPERTY holds the reference, exactly as an
    # instancing site would be.
    assert problem["nodes"] == ["."]


BINARY_SUB_SCENE_PARENT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://hero.scn" id="1_bin"]

[node name="Parent" type="Node2D"]

[node name="Kid" parent="." instance=ExtResource("1_bin")]
"""


@pytest.mark.e2e
def test_a_binary_sub_scene_is_reported_unchecked_not_silently_skipped(godot_project):
    # The GDA-DF-030 failure mode, one level down: the parent instances a binary
    # child whose script no longer compiles, and the walk cannot read that child's
    # dependency text. Before this was reported, the answer was
    # `valid: true, problems: []` while the engine's own load of the same parent
    # reported the child's parse error — a gate answering "sound" about a subtree
    # it never opened, which is exactly what `instance_depth_exceeded` exists to
    # prevent one axis over.
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "hero.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    (godot_project / "save_binary.gd").write_text(SAVE_AS_BINARY_GD, encoding="utf-8")
    (godot_project / "parent.tscn").write_text(
        BINARY_SUB_SCENE_PARENT_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)
    saved = gda("script", "run", "res://save_binary.gd", "--json")
    assert saved.returncode == 0, saved.stdout + saved.stderr
    assert (godot_project / "hero.scn").exists(), saved.stdout + saved.stderr
    # Break the script AFTER the binary was written. The .scn itself still LOADS —
    # a GDScript that does not compile is still handed back as a resource — so the
    # parent's own dependency walk finds nothing wrong with it.
    (godot_project / "hero.gd").write_text(BROKEN_SCRIPT, encoding="utf-8")

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "unreadable_sub_scene"
    assert problem["scene"] == "res://parent.tscn"
    assert problem["path"] == "res://hero.scn"
    assert problem["nodes"] == ["Kid"]
    assert "UNCHECKED" in problem["message"]
    # The text form of the same child IS checked, so the report is about the form
    # gda can read and not about the scene.
    text_parent = gda("scene", "validate", "res://hero.tscn", "--json")
    assert text_parent.returncode == 0, text_parent.stdout + text_parent.stderr
    text_data = json.loads(text_parent.stdout)
    assert [p["kind"] for p in text_data["problems"]] == ["script_compile_failed"]


@pytest.mark.e2e
def test_a_binary_sub_scene_that_does_not_load_is_still_reported_once(godot_project):
    # The other half of the boundary, and the reason `unreadable_sub_scene` is not
    # raised for every unreadable target: when the binary child does not load at
    # all, the parent's own dependency walk has ALREADY named it. One finding, not
    # two views of one.
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "hero.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    (godot_project / "save_binary.gd").write_text(SAVE_AS_BINARY_GD, encoding="utf-8")
    (godot_project / "parent.tscn").write_text(
        BINARY_SUB_SCENE_PARENT_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)
    saved = gda("script", "run", "res://save_binary.gd", "--json")
    assert saved.returncode == 0, saved.stdout + saved.stderr
    # Removing the script entirely makes the binary resource itself unloadable.
    (godot_project / "hero.gd").unlink()

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    assert data["problems"] == [
        {
            "kind": "unloadable_resource",
            "scene": "res://parent.tscn",
            "path": "res://hero.scn",
            "type": "PackedScene",
            "nodes": ["Kid"],
            "message": "the resource could not be loaded",
        }
    ]


@pytest.mark.e2e
def test_two_spellings_of_one_sub_scene_are_one_file(godot_project):
    # `res://leaf.tscn` and `res://./leaf.tscn` name the same file, so the walk
    # must answer for it once. Keying the traversal on the raw string reported the
    # child's single missing script TWICE, under two `scene` spellings — and the
    # same lexical alias could have evaded the depth bound and defeated the
    # cycle test, which both key on the same identity.
    (godot_project / "leaf.tscn").write_text(COMPOSED_CHILD_TSCN, encoding="utf-8")
    (godot_project / "alias.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://leaf.tscn" id="1_a"]\n'
        '[ext_resource type="PackedScene" path="res://./leaf.tscn" id="2_a"]\n\n'
        '[node name="Alias" type="Node2D"]\n\n'
        '[node name="A" parent="." instance=ExtResource("1_a")]\n\n'
        '[node name="B" parent="." instance=ExtResource("2_a")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://alias.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://leaf.tscn",
            "path": "res://missing_script.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        }
    ]


def _write_cross_boundary_diamond(project, *, deep_first: bool) -> None:
    """A leaf reachable BOTH past the depth bound and one edge below the root.

    `d1 … d16` is a straight chain ending at `shared.tscn`, which puts `shared` 17
    levels below the root — past the bound. The root also references `shared`
    directly. Only the DECLARATION ORDER of the root's two lines differs between
    the two files this writes.
    """
    (project / "shared.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Shared" type="Node2D"]\n', encoding="utf-8"
    )
    for level in range(1, 17):
        target = f"res://d{level + 1}.tscn" if level < 16 else "res://shared.tscn"
        (project / f"d{level}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="{target}" id="1_c"]\n\n'
            f'[node name="D{level}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )
    deep = '[ext_resource type="PackedScene" path="res://d1.tscn" id="1_deep"]'
    direct = '[ext_resource type="PackedScene" path="res://shared.tscn" id="2_direct"]'
    deep_node = '[node name="Deep" parent="." instance=ExtResource("1_deep")]'
    direct_node = '[node name="Direct" parent="." instance=ExtResource("2_direct")]'
    lines = [deep, direct] if deep_first else [direct, deep]
    nodes = [deep_node, direct_node] if deep_first else [direct_node, deep_node]
    (project / "root.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        + "\n".join(lines)
        + '\n\n[node name="Root" type="Node2D"]\n\n'
        + "\n\n".join(nodes)
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "deep_first", [True, False], ids=["deep-first", "direct-first"]
)
@pytest.mark.e2e
def test_the_depth_verdict_does_not_depend_on_declaration_order(
    godot_project, deep_first
):
    # One graph, one verdict. Reporting the bound the moment an edge crossed it
    # made the published answer a function of which of the root's two lines came
    # first: deep-first reported `instance_depth_exceeded` and then validated the
    # same leaf through the short route anyway (`valid: false`, with a finding
    # nothing stood behind), while direct-first validated the leaf first and let
    # `visited` swallow the deep edge in silence (`valid: true`).
    _write_cross_boundary_diamond(godot_project, deep_first=deep_first)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["problems"] == []


@pytest.mark.e2e
def test_a_target_no_route_reaches_in_bound_is_still_reported(godot_project):
    # The other direction of the same rule: deferring must not become dropping.
    # Remove the root's short route and the identical leaf is genuinely unchecked,
    # so the bound is reported.
    _write_cross_boundary_diamond(godot_project, deep_first=True)
    (godot_project / "root.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://d1.tscn" id="1_deep"]\n\n'
        '[node name="Root" type="Node2D"]\n\n'
        '[node name="Deep" parent="." instance=ExtResource("1_deep")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "instance_depth_exceeded"
    assert problem["scene"] == "res://d16.tscn"
    assert problem["path"] == "res://shared.tscn"


# --- The residues of round 3 (#721 review) ----------------------------------
#
# Three of the four had one shape: a rule bound to a proxy instead of to the
# boundary it is a property of. The file EXTENSION stood in for "is a
# PackedScene", one visited set stood in for "answered AND expanded at minimum
# depth", and the ROOT bypassed the identity its children went through.

SAVE_AS_RES_GD = """\
extends SceneTree


func _initialize() -> void:
	var packed := ResourceLoader.load("res://hero.tscn", "PackedScene") as PackedScene
	var err := ResourceSaver.save(packed, "res://hero_pack.res")
	if err != OK:
		printerr("save failed: ", err)
	quit(0 if err == OK else 1)
"""

RES_SUB_SCENE_PARENT_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://hero_pack.res" id="1_pack"]

[node name="Parent" type="Node2D"]

[node name="Kid" parent="." instance=ExtResource("1_pack")]
"""


@pytest.mark.e2e
def test_a_packed_scene_saved_as_a_res_is_reported_not_skipped(godot_project):
    # A PackedScene under NO scene extension. `ResourceFormatSaverBinary` accepts
    # `.res` for any resource (the text saver does not, so `.tres` is not a form a
    # PackedScene can be saved in), and the extension test alone skipped such a
    # child before any check ran: this parent answered `valid: true, problems: []`
    # while the engine's own load of it reported the child's parse error. The
    # declared type is the second trigger that catches it.
    (godot_project / "hero.gd").write_text(GOOD_SCRIPT, encoding="utf-8")
    (godot_project / "hero.tscn").write_text(GOOD_TSCN, encoding="utf-8")
    (godot_project / "save_res.gd").write_text(SAVE_AS_RES_GD, encoding="utf-8")
    (godot_project / "parent.tscn").write_text(
        RES_SUB_SCENE_PARENT_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)
    saved = gda("script", "run", "res://save_res.gd", "--json")
    assert saved.returncode == 0, saved.stdout + saved.stderr
    assert (godot_project / "hero_pack.res").exists(), saved.stdout + saved.stderr
    # Break the script AFTER the .res was written. The .res still LOADS, so the
    # parent's own dependency walk finds nothing wrong with it.
    (godot_project / "hero.gd").write_text(BROKEN_SCRIPT, encoding="utf-8")

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "unreadable_sub_scene"
    assert problem["scene"] == "res://parent.tscn"
    assert problem["path"] == "res://hero_pack.res"
    assert problem["nodes"] == ["Kid"]
    assert "UNCHECKED" in problem["message"]


@pytest.mark.e2e
def test_a_res_declared_as_something_else_is_still_not_a_scene_edge(godot_project):
    # The other side of the union, and the reason it is a TRIGGER and not a load:
    # a `.res` that is not a PackedScene stays outside the walk however it is
    # declared. Here the same file is declared `type="PackedScene"` over a plain
    # resource — the engine ignores the declaration and loads what is there, so
    # there is no sub-scene and nothing to report.
    (godot_project / "plain.tres").write_text(
        '[gd_resource type="Resource" format=3]\n\n[resource]\n', encoding="utf-8"
    )
    (godot_project / "parent.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://plain.tres" id="1_p"]\n\n'
        '[node name="Parent" type="Node2D"]\n'
        'metadata/thing = ExtResource("1_p")\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://parent.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["problems"] == []


def _write_ancestor_convergence(project, *, deep_first: bool, break_leaf: bool) -> None:
    """A CONVERGENCE above the deep target rather than at it.

    `m.tscn` sits 16 levels below the root through `d1 … d15` — inside the bound,
    so it is expanded there — and its own child `t.tscn` sits one level further,
    outside it. The root also references `m.tscn` directly, one level down, which
    puts `t.tscn` two levels down on that route. Only the DECLARATION ORDER of the
    root's two lines differs between the two files this writes.
    """
    leaf = (
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://gone.gd" id="1_gone"]\n\n'
        '[node name="T" type="Node2D"]\n'
        'script = ExtResource("1_gone")\n'
        if break_leaf
        else '[gd_scene format=3]\n\n[node name="T" type="Node2D"]\n'
    )
    (project / "t.tscn").write_text(leaf, encoding="utf-8")
    (project / "m.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://t.tscn" id="1_t"]\n\n'
        '[node name="M" type="Node2D"]\n\n'
        '[node name="TInst" parent="." instance=ExtResource("1_t")]\n',
        encoding="utf-8",
    )
    for level in range(1, 16):
        target = f"res://d{level + 1}.tscn" if level < 15 else "res://m.tscn"
        (project / f"d{level}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="{target}" id="1_c"]\n\n'
            f'[node name="D{level}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )
    deep = '[ext_resource type="PackedScene" path="res://d1.tscn" id="1_deep"]'
    direct = '[ext_resource type="PackedScene" path="res://m.tscn" id="2_direct"]'
    deep_node = '[node name="Deep" parent="." instance=ExtResource("1_deep")]'
    direct_node = '[node name="Direct" parent="." instance=ExtResource("2_direct")]'
    lines = [deep, direct] if deep_first else [direct, deep]
    nodes = [deep_node, direct_node] if deep_first else [direct_node, deep_node]
    (project / "root.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        + "\n".join(lines)
        + '\n\n[node name="Root" type="Node2D"]\n\n'
        + "\n\n".join(nodes)
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "deep_first", [True, False], ids=["deep-first", "direct-first"]
)
@pytest.mark.e2e
def test_a_sound_graph_converging_above_the_bound_is_valid_in_both_orders(
    godot_project, deep_first
):
    # The shape the round-2 fix did not cover. Deferring the depth finding settles
    # a target reached both ways; it says nothing about a target whose ANCESTOR is
    # reached both ways. `m.tscn` was expanded on whichever route came first, and a
    # visited record that meant only "answered" made the shorter route skip it — so
    # `t.tscn`, one edge below it, was reached on the direct-first file and left
    # past the bound on the deep-first one. Same graph, two verdicts.
    _write_ancestor_convergence(godot_project, deep_first=deep_first, break_leaf=False)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is True, data
    assert data["problems"] == []


@pytest.mark.parametrize(
    "deep_first", [True, False], ids=["deep-first", "direct-first"]
)
@pytest.mark.e2e
def test_a_break_below_the_convergence_is_found_in_both_orders(
    godot_project, deep_first
):
    # The same graph with the leaf broken: re-expanding on the shorter route must
    # find the break, not merely stop reporting the bound. One problem, the same
    # one, whichever line the root declares first.
    _write_ancestor_convergence(godot_project, deep_first=deep_first, break_leaf=True)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://t.tscn",
            "path": "res://gone.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        }
    ]


@pytest.mark.e2e
def test_a_subtree_only_the_deep_route_reaches_is_still_reported(godot_project):
    # Re-expanding must not become "never report the bound". Remove the root's
    # short route and `t.tscn` is genuinely outside the walk, so it is reported —
    # attributed to `m.tscn`, the file whose edge declined.
    _write_ancestor_convergence(godot_project, deep_first=True, break_leaf=False)
    (godot_project / "root.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://d1.tscn" id="1_deep"]\n\n'
        '[node name="Root" type="Node2D"]\n\n'
        '[node name="Deep" parent="." instance=ExtResource("1_deep")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    (problem,) = data["problems"]
    assert problem["kind"] == "instance_depth_exceeded"
    assert problem["scene"] == "res://m.tscn"
    assert problem["path"] == "res://t.tscn"


@pytest.mark.e2e
def test_an_aliased_root_is_the_same_file_as_the_reference_back_to_it(godot_project):
    # The root goes through the SAME identity as its children. Seeded raw, the
    # alias `res://./root.tscn` was a key no child reference back to
    # `res://root.tscn` could match, so the root was answered for twice — its one
    # missing script reported under two `scene` spellings — and the cycle was only
    # recognized one level lower than it closes.
    (godot_project / "root.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="Script" path="res://gone.gd" id="1_gone"]\n'
        '[ext_resource type="PackedScene" path="res://root.tscn" id="2_self"]\n\n'
        '[node name="Root" type="Node2D"]\n'
        'script = ExtResource("1_gone")\n\n'
        '[node name="Inner" parent="." instance=ExtResource("2_self")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    canonical = gda("scene", "validate", "res://root.tscn", "--json")
    aliased = gda("scene", "validate", "res://./root.tscn", "--json")

    assert aliased.returncode == 0, aliased.stdout + aliased.stderr
    data = json.loads(aliased.stdout)
    # The result echoes the CANONICAL spelling, not the caller's — one spelling
    # across `path`, every problem's `scene`, and every problem's `path`.
    assert data["path"] == "res://root.tscn"
    assert data == json.loads(canonical.stdout)
    assert [p["kind"] for p in data["problems"]] == [
        "missing_resource",
        "cyclic_instance",
    ]


@pytest.mark.e2e
def test_an_edge_problem_lists_every_id_that_names_the_target(godot_project):
    # One target, two [ext_resource] ids, two instancing nodes. The problem is
    # deduplicated by the target file, so its `nodes` must merge every site that
    # names that file — reading only the id that happened to settle the edge lost
    # `InnerB`.
    (godot_project / "self.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://self.tscn" id="1_a"]\n'
        '[ext_resource type="PackedScene" path="res://./self.tscn" id="2_b"]\n\n'
        '[node name="Self" type="Node2D"]\n\n'
        '[node name="InnerA" parent="." instance=ExtResource("1_a")]\n\n'
        '[node name="InnerB" parent="." instance=ExtResource("2_b")]\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://self.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    (problem,) = data["problems"]
    assert problem["kind"] == "cyclic_instance"
    assert problem["path"] == "res://self.tscn"
    assert problem["nodes"] == ["InnerA", "InnerB"]


@pytest.mark.e2e
def test_a_cycle_below_a_re_expanded_scene_is_reported_once(godot_project):
    # Where the two new mechanisms meet. `y.tscn` is reached at depth 2 through
    # `x.tscn` and at depth 1 directly, so the shorter route expands it again — and
    # the cycle `z.tscn` closes back onto `y.tscn` is met once per expansion. The
    # edge record therefore belongs to the WALK, not to one descent, or the same
    # cycle is published twice.
    (godot_project / "root.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://x.tscn" id="1_x"]\n'
        '[ext_resource type="PackedScene" path="res://y.tscn" id="2_y"]\n\n'
        '[node name="Root" type="Node2D"]\n\n'
        '[node name="XInst" parent="." instance=ExtResource("1_x")]\n\n'
        '[node name="YInst" parent="." instance=ExtResource("2_y")]\n',
        encoding="utf-8",
    )
    for name, target in (("x", "y"), ("y", "z"), ("z", "y")):
        (godot_project / f"{name}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="res://{target}.tscn" id="1_c"]\n\n'
            f'[node name="{name.upper()}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert [(p["kind"], p["scene"], p["path"]) for p in data["problems"]] == [
        ("cyclic_instance", "res://z.tscn", "res://y.tscn")
    ]


# --- The residue of round 4 (#721 review) -----------------------------------
#
# The same shape a fourth time: ONE record standing for two states. A depth
# deferral is PROVISIONAL — it stands only while nothing reaches its target — and a
# cycle is TERMINAL, but a single "already reported" flag covered both, so a deep
# route's deferral suppressed the cycle a shorter route proved on the same edge,
# and the deferral was then dropped because its target had been reached. An edge
# now carries an OUTCOME that a cycle can be PROMOTED into.


def _write_deferred_cycle(project, *, deep_first: bool) -> None:
    """A cycle whose closing edge is ALSO met past the depth bound.

    `d1 … d15` puts `s.tscn` 16 levels below the root — the last level INSIDE the
    bound — so `s`'s own edge to `t.tscn` is one level past it and is deferred. The
    root also references `t.tscn` directly, and `t` references `s` back, so the
    short route re-expands `s` at depth 2 and finds that same edge closing a real
    cycle. Every file here is sound on its own; the only defect is `s ↔ t`. Only
    the DECLARATION ORDER of the root's two lines differs between the two files
    this writes.
    """
    for level in range(1, 16):
        target = f"res://d{level + 1}.tscn" if level < 15 else "res://s.tscn"
        (project / f"d{level}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="{target}" id="1_c"]\n\n'
            f'[node name="D{level}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )
    for name, target in (("s", "t"), ("t", "s")):
        (project / f"{name}.tscn").write_text(
            "[gd_scene load_steps=2 format=3]\n\n"
            f'[ext_resource type="PackedScene" path="res://{target}.tscn" id="1_c"]\n\n'
            f'[node name="{name.upper()}" type="Node2D"]\n\n'
            '[node name="Child" parent="." instance=ExtResource("1_c")]\n',
            encoding="utf-8",
        )
    deep = '[ext_resource type="PackedScene" path="res://d1.tscn" id="1_deep"]'
    direct = '[ext_resource type="PackedScene" path="res://t.tscn" id="2_direct"]'
    deep_node = '[node name="Deep" parent="." instance=ExtResource("1_deep")]'
    direct_node = '[node name="Direct" parent="." instance=ExtResource("2_direct")]'
    lines = [deep, direct] if deep_first else [direct, deep]
    nodes = [deep_node, direct_node] if deep_first else [direct_node, deep_node]
    (project / "root.tscn").write_text(
        "[gd_scene load_steps=3 format=3]\n\n"
        + "\n".join(lines)
        + '\n\n[node name="Root" type="Node2D"]\n\n'
        + "\n\n".join(nodes)
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "deep_first", [True, False], ids=["deep-first", "direct-first"]
)
@pytest.mark.e2e
def test_a_deferred_depth_edge_does_not_suppress_a_later_cycle(
    godot_project, deep_first
):
    # A genuinely broken composition read as SOUND, and only in one declaration
    # order: deep-first answered `valid: true, problems: []` while direct-first
    # reported the cycle (measured on Godot 4.6.3 before the fix). One graph, one
    # verdict — the cycle, attributed to the file that declares the closing edge.
    _write_deferred_cycle(godot_project, deep_first=deep_first)
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://root.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False, data
    assert [
        (p["kind"], p["scene"], p["path"], p["nodes"]) for p in data["problems"]
    ] == [("cyclic_instance", "res://s.tscn", "res://t.tscn", ["Child"])]


# A hand-written scene whose [node] header carries a decoy attribute ending in
# `name` ahead of the real one, and whose [ext_resource] line carries a decoy
# ending in `type` (#775). Both are read WHOLE-NAME by the one owner of each
# recognition, so the verdict names the node that really references the missing
# file, and the class the line really declares. Read by substring, the header
# attributes answer "Decoy" and the type answers "Resource".
DECOY_ATTR_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" subtype="Resource" path="res://gone.gd" id="1_gone"]

[node name="Root" type="Node2D"]

[node instance_name="Decoy" name="Sprite" type="Sprite2D" parent="."]
script = ExtResource("1_gone")
"""


@pytest.mark.e2e
def test_a_problem_names_the_node_a_whole_name_header_read_finds(godot_project):
    (godot_project / "main.tscn").write_text(DECOY_ATTR_TSCN, encoding="utf-8")
    gda = _gda_project(godot_project)

    validated = gda("scene", "validate", "res://main.tscn", "--json")

    assert validated.returncode == 0, validated.stdout + validated.stderr
    data = json.loads(validated.stdout)
    assert data["valid"] is False
    assert data["problems"] == [
        {
            "kind": "missing_resource",
            "scene": "res://main.tscn",
            "path": "res://gone.gd",
            "type": "Script",
            # "Decoy" before the [node] header was read by whole attribute name:
            # an agent sent to fix the reference would open the wrong node.
            "nodes": ["Sprite"],
            "message": "the referenced file does not exist",
        }
    ]
