"""S1 (e2e): the project static-analysis reads against the real Godot engine (issue #116).

The four read-only, project-wide analysis commands — find-references,
dependencies, find-unused-resources, statistics — backed by a single static scan
that parses files as text (no instantiation, issue #30). These tests build a
small fixture project WITH cross-references (a main scene that ext_resources a
sub-scene, a script and an image; a script that preloads a sibling; an autoload;
an unreferenced resource) and assert each command reports it correctly off the
real engine. find-unused-resources must agree with find-references (the
acceptance criterion: the same reference graph backs both).
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


# A project.godot with an autoload, a main scene, and an enabled editor plugin —
# the project-level references and the statistics fields the commands report.
PROJECT_GODOT = """\
config_version=5

[application]

config/name="gda-refgraph-fixture"
run/main_scene="res://main.tscn"

[autoload]

GameState="*res://game_state.gd"

[editor_plugins]

enabled=PackedStringArray("res://addons/widget/plugin.cfg")
"""

# A main scene that ext_resources a sub-scene, a script and an image — three
# outgoing references, the shape Godot 4 writes.
MAIN_TSCN = """\
[gd_scene load_steps=4 format=3 uid="uid://bmain"]

[ext_resource type="PackedScene" uid="uid://bhero" path="res://hero.tscn" id="1_hero"]
[ext_resource type="Script" path="res://main.gd" id="2_main"]
[ext_resource type="Texture2D" uid="uid://bicon" path="res://icon.png" id="3_icon"]

[node name="Main" type="Node2D"]
script = ExtResource("2_main")

[node name="Hero" parent="." instance=ExtResource("1_hero")]

[node name="Sprite" type="Sprite2D" parent="."]
texture = ExtResource("3_icon")
"""

# A sub-scene with no external references.
HERO_TSCN = """\
[gd_scene format=3 uid="uid://bhero"]

[node name="Hero" type="CharacterBody2D"]
"""

# main.gd preloads a sibling script — a .gd → .gd reference via preload.
MAIN_GD = """\
extends Node2D

const Util = preload("res://util.gd")

func _ready() -> void:
	Util.greet()
"""

UTIL_GD = """\
extends RefCounted

static func greet() -> void:
	print("hi")
"""

GAME_STATE_GD = """\
extends Node

var score := 0
"""

# A .tres resource that nothing references — the unused resource the report finds.
ORPHAN_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""

PLUGIN_CFG = """\
[plugin]

name="Widget"
script="plugin.gd"
"""


@pytest.fixture
def refgraph_project(tmp_path):
    """A fixture project with real cross-references for the analysis commands."""
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "hero.tscn").write_text(HERO_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(MAIN_GD, encoding="utf-8")
    (tmp_path / "util.gd").write_text(UTIL_GD, encoding="utf-8")
    (tmp_path / "game_state.gd").write_text(GAME_STATE_GD, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (tmp_path / "orphan.tres").write_text(ORPHAN_TRES, encoding="utf-8")
    addons = tmp_path / "addons" / "widget"
    addons.mkdir(parents=True)
    (addons / "plugin.cfg").write_text(PLUGIN_CFG, encoding="utf-8")
    return tmp_path


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT), "--project", str(project)],
        capture_output=True,
        text=True,
    )


@pytest.mark.e2e
def test_dependencies_maps_each_scene_to_its_ext_resources(refgraph_project):
    proc = _gda(refgraph_project, "project", "dependencies", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    by_path = {d["path"]: d for d in data["dependencies"]}

    # main.tscn references the sub-scene, the script and the image.
    main_deps = {d["path"] for d in by_path["res://main.tscn"]["depends_on"]}
    assert main_deps == {"res://hero.tscn", "res://main.gd", "res://icon.png"}
    # main.gd preloads util.gd — a .gd → .gd reference is in the graph too.
    main_gd_deps = {d["path"] for d in by_path["res://main.gd"]["depends_on"]}
    assert "res://util.gd" in main_gd_deps
    # hero.tscn has no external references — reported with an empty depends_on,
    # not dropped.
    assert by_path["res://hero.tscn"]["depends_on"] == []


@pytest.mark.e2e
def test_find_references_to_a_script_finds_every_referencing_site(refgraph_project):
    proc = _gda(
        refgraph_project, "project", "find-references", "res://util.gd", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["target"] == "res://util.gd"
    referencing = {(r["path"], r["kind"]) for r in data["references"]}
    # main.gd preloads util.gd.
    assert ("res://main.gd", "preload") in referencing


@pytest.mark.e2e
def test_find_references_to_a_scene_finds_the_ext_resource(refgraph_project):
    proc = _gda(
        refgraph_project, "project", "find-references", "res://hero.tscn", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    refs = json.loads(proc.stdout)["references"]
    referencing = {(r["path"], r["kind"]) for r in refs}
    assert ("res://main.tscn", "ext_resource") in referencing


@pytest.mark.e2e
def test_find_references_to_the_main_scene_includes_the_project_level_reference(
    refgraph_project,
):
    proc = _gda(
        refgraph_project, "project", "find-references", "res://main.tscn", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    refs = json.loads(proc.stdout)["references"]
    # The main scene is referenced by project.godot's run/main_scene, not a file.
    assert any(
        r["path"] == "project.godot" and r["kind"] == "main_scene" for r in refs
    )


@pytest.mark.e2e
def test_find_references_to_an_unreferenced_resource_is_empty(refgraph_project):
    proc = _gda(
        refgraph_project, "project", "find-references", "res://orphan.tres", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["references"] == []


@pytest.mark.e2e
def test_find_unused_resources_reports_the_orphan_and_is_consistent_with_find_references(
    refgraph_project,
):
    proc = _gda(
        refgraph_project, "project", "find-unused-resources", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    unused = json.loads(proc.stdout)["unused"]

    # The orphan .tres nothing references is reported unused.
    assert "res://orphan.tres" in unused
    # Referenced resources are NOT reported unused.
    assert "res://hero.tscn" not in unused
    assert "res://icon.png" not in unused
    # The main scene is an entry point (project.godot run/main_scene), never unused.
    assert "res://main.tscn" not in unused

    # Consistency (the acceptance criterion): a resource is unused exactly when
    # find-references for it returns empty, and a referenced one returns non-empty.
    for path in unused:
        refs = json.loads(
            _gda(
                refgraph_project, "project", "find-references", path, "--json"
            ).stdout
        )["references"]
        assert refs == [], f"{path} reported unused but has references {refs}"

    hero_refs = json.loads(
        _gda(
            refgraph_project, "project", "find-references", "res://hero.tscn", "--json"
        ).stdout
    )["references"]
    assert hero_refs != []  # referenced, hence not in unused


@pytest.mark.e2e
def test_statistics_reports_counts_autoloads_and_plugins(refgraph_project):
    proc = _gda(refgraph_project, "project", "statistics", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    # File/line counts: at least the files the fixture wrote, with positive lines.
    assert data["total_files"] >= 8
    assert data["total_lines"] > 0
    assert data["scene_count"] == 2  # main.tscn, hero.tscn
    assert data["script_count"] >= 3  # main.gd, util.gd, game_state.gd (+ plugin.gd? no)
    by_ext = {e["extension"]: e for e in data["by_extension"]}
    assert by_ext["gd"]["files"] >= 3
    assert by_ext["gd"]["lines"] > 0

    # Autoloads read from ProjectSettings (the '*' enable marker stripped).
    autoloads = {a["name"]: a["path"] for a in data["autoloads"]}
    assert autoloads["GameState"] == "res://game_state.gd"

    # Enabled plugins read from editor_plugins/enabled.
    assert "res://addons/widget/plugin.cfg" in data["plugins"]


@pytest.mark.e2e
def test_find_references_bad_target_is_invalid_target(refgraph_project):
    # A target that is neither a res:// path nor a registered class_name is a
    # structured invalid_target operation error (exit 4), not an empty result.
    proc = _gda(
        refgraph_project, "project", "find-references", "/abs/not/a/target", "--json"
    )

    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_target"


# --- class_name find-references fixture (issue #116 review) -----------------
#
# A project whose only references to a class are by its class_name token: a
# defining script (`class_name Hero`, no other use of the token), genuine
# consumers (`extends Hero`, a `var x: Hero` annotation, `Hero.new()`), and an
# UNREFERENCED class (`class_name Lonely`) nothing names. find-references for
# Hero must report the consumers but NOT Hero's own `class_name Hero` declaration
# line (the definition site, not a reference); find-references for Lonely must be
# empty.
CLASSNAME_PROJECT_GODOT = """\
config_version=5

[application]

config/name="gda-classname-fixture"
"""

HERO_GD = """\
extends Node

class_name Hero

func greet() -> void:
	print("hero")
"""

VILLAIN_GD = """\
extends Hero

func taunt() -> void:
	print("villain")
"""

SPAWNER_GD = """\
extends Node

func make() -> void:
	var h: Hero = Hero.new()
	h.greet()
"""

LONELY_GD = """\
extends Node

class_name Lonely

func sigh() -> void:
	print("nobody references me")
"""


def _import_project(project) -> None:
    # class_name registration lives in the project's global class list, which only
    # a project scan produces — run the engine's headless import step the way a CI
    # pipeline would before resolving a find-references target by class_name.
    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr


@pytest.fixture
def classname_project(tmp_path):
    """A project where a class is referenced only by its class_name token."""
    (tmp_path / "project.godot").write_text(CLASSNAME_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "hero.gd").write_text(HERO_GD, encoding="utf-8")
    (tmp_path / "villain.gd").write_text(VILLAIN_GD, encoding="utf-8")
    (tmp_path / "spawner.gd").write_text(SPAWNER_GD, encoding="utf-8")
    (tmp_path / "lonely.gd").write_text(LONELY_GD, encoding="utf-8")
    _import_project(tmp_path)
    return tmp_path


@pytest.mark.e2e
def test_find_references_to_a_class_name_excludes_its_own_declaration(
    classname_project,
):
    # find-references Hero must report the genuine consumers (extends Hero, a
    # `var x: Hero` annotation, Hero.new()) but NEVER hero.gd's own
    # `class_name Hero` declaration line — that is the definition site, not a
    # reference (issue #116 review: false positive).
    proc = _gda(
        classname_project, "project", "find-references", "Hero", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["target"] == "Hero"
    referencing = {(r["path"], r["kind"]) for r in data["references"]}
    # Genuine consumers are reported as class_reference hits.
    assert ("res://villain.gd", "class_reference") in referencing
    assert ("res://spawner.gd", "class_reference") in referencing
    # The defining file's `class_name Hero` line is NOT reported as a reference.
    hero_class_refs = [
        r
        for r in data["references"]
        if r["path"] == "res://hero.gd"
        and r["kind"] == "class_reference"
        and r["context"].strip().startswith("class_name ")
    ]
    assert hero_class_refs == [], (
        f"the class_name declaration is reported as a self-reference: {hero_class_refs}"
    )


@pytest.mark.e2e
def test_find_references_to_an_unreferenced_class_name_is_empty(classname_project):
    # A class declared via class_name that NOTHING consumes returns an empty
    # reference set — its own declaration line must not count as a reference.
    proc = _gda(
        classname_project, "project", "find-references", "Lonely", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["references"] == []


@pytest.mark.e2e
def test_statistics_counts_binary_assets_as_files_but_not_lines(tmp_path):
    # A binary asset whose bytes happen to contain newlines must contribute to
    # the file count but NOT the line count — statistics' documented contract
    # ("binary assets contribute to file counts but not line counts"). Issue #116
    # review: _count_lines previously read every file as text, so a binary asset's
    # newline bytes inflated total_lines.
    (tmp_path / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="gda-binary-fixture"\n',
        encoding="utf-8",
    )
    # A two-line .gd: a real text file contributing 2 lines.
    (tmp_path / "code.gd").write_text("extends Node\n\n", encoding="utf-8")
    # A binary .png with many newline (0x0A) bytes — text-decoded it would look
    # like dozens of lines, but as a binary asset it must contribute 0 lines.
    (tmp_path / "blob.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + (b"\n" * 50) + b"\x00\xff\x10binary\n"
    )

    proc = _gda(tmp_path, "project", "statistics", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    by_ext = {e["extension"]: e for e in data["by_extension"]}

    # The binary asset is counted as a file...
    assert by_ext["png"]["files"] == 1
    # ...but contributes 0 lines despite its ~52 newline bytes.
    assert by_ext["png"]["lines"] == 0
    # The text .gd contributes its 2 lines.
    assert by_ext["gd"]["lines"] == 2
    # total_lines is exactly the sum of the per-extension (text-only) line counts;
    # the binary png's newline bytes are not in it (far below the 52 it carries).
    assert data["total_lines"] == sum(e["lines"] for e in data["by_extension"])
    assert data["total_lines"] < 50


@pytest.mark.e2e
def test_dependencies_without_project_is_project_not_found(tmp_path):
    # Run projectless (no --project, cwd is not a project): the res:// scan has no
    # tree to walk, so it refuses with the registered project_not_found code.
    gda_bin = shutil.which("gda")
    assert gda_bin
    proc = subprocess.run(
        [gda_bin, "project", "dependencies", "--godot", str(GODOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"
