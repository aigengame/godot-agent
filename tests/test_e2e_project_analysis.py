"""S1 (e2e): the project static-analysis reads against the real Godot engine (issue #116).

The four read-only, project-wide analysis commands — find-references,
dependencies, find-unused-resources, statistics — backed by two static scans
over different file universes (the first three share the extension-filtered
walk; statistics counts with an unfiltered one that also sees ``.import``
sidecars and ``project.godot``) under one shared directory-exclusion rule,
both parsing files as text (no instantiation, issue #30). These tests build a
small fixture project WITH cross-references (a main scene that ext_resources a
sub-scene, a script and an image; a script that preloads a sibling; an autoload;
an unreferenced resource) and assert each command reports it correctly off the
real engine. find-unused-resources must agree with find-references (the
acceptance criterion: the same reference graph backs both).
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


# A project.godot with an autoload, a main scene, and an enabled editor plugin —
# the project-level references and the statistics fields the commands report.
# Built through ``project_godot`` so e2e file logging stays disabled (issue #180).
PROJECT_GODOT = project_godot(
    name="gda-refgraph-fixture",
    extra="""\
run/main_scene="res://main.tscn"

[autoload]

GameState="*res://game_state.gd"

[editor_plugins]

enabled=PackedStringArray("res://addons/widget/plugin.cfg")
""",
)

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
    """A fixture project with real cross-references for the analysis commands.

    Also plants binary artifacts (issue #378): an exported-build stand-in with
    invalid-UTF-8 bytes under ``build/`` and an unreferenced binary asset. The
    scan must never UTF-8-decode them (no engine ``Unicode parsing error`` on
    stderr) while still enumerating them as graph nodes.
    """
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "hero.tscn").write_text(HERO_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(MAIN_GD, encoding="utf-8")
    (tmp_path / "util.gd").write_text(UTIL_GD, encoding="utf-8")
    (tmp_path / "game_state.gd").write_text(GAME_STATE_GD, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (tmp_path / "orphan.tres").write_text(ORPHAN_TRES, encoding="utf-8")
    # An unreferenced binary ASSET: skipped decode must not drop it from the
    # graph universe — it stays a find-unused candidate (issue #378).
    (tmp_path / "orphan.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    # A binary build artifact whose bytes are invalid UTF-8 (0xf3 lead byte
    # followed by a non-continuation byte — the exact shape the issue-#378 repro
    # decoded into "Unicode parsing error: Byte d is not a correct continuation
    # byte after f3").
    build = tmp_path / "build"
    build.mkdir()
    (build / "fake.pck").write_bytes(b"\xf3\x0d\x00\xff" * 8)
    addons = tmp_path / "addons" / "widget"
    addons.mkdir(parents=True)
    (addons / "plugin.cfg").write_text(PLUGIN_CFG, encoding="utf-8")
    return tmp_path


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
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
    assert any(r["path"] == "project.godot" and r["kind"] == "main_scene" for r in refs)


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
    proc = _gda(refgraph_project, "project", "find-unused-resources", "--json")

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
            _gda(refgraph_project, "project", "find-references", path, "--json").stdout
        )["references"]
        assert refs == [], f"{path} reported unused but has references {refs}"

    hero_refs = json.loads(
        _gda(
            refgraph_project, "project", "find-references", "res://hero.tscn", "--json"
        ).stdout
    )["references"]
    assert hero_refs != []  # referenced, hence not in unused


@pytest.mark.e2e
def test_find_references_skips_decoding_binary_artifacts(refgraph_project):
    # The fixture plants build/fake.pck with invalid-UTF-8 bytes. The scan must
    # dispatch on extension BEFORE reading, so the binary is never UTF-8-decoded
    # — no engine "Unicode parsing error" on stderr (issue #378) — while the
    # references over the text formats stay byte-for-byte unchanged.
    proc = _gda(
        refgraph_project, "project", "find-references", "res://util.gd", "--json"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Unicode parsing error" not in proc.stderr, proc.stderr
    refs = json.loads(proc.stdout)["references"]
    assert {(r["path"], r["kind"]) for r in refs} == {("res://main.gd", "preload")}


@pytest.mark.e2e
def test_find_unused_resources_skips_decoding_but_keeps_binary_graph_nodes(
    refgraph_project,
):
    # Same clean-stderr guarantee for find-unused-resources (shared graph), AND
    # the graph universe must not shrink (issue #378): binaries are skipped only
    # for DECODING — they stay enumerated as graph nodes, so the unreferenced
    # binary asset (orphan.png) and the build artifact are still unused
    # candidates.
    proc = _gda(refgraph_project, "project", "find-unused-resources", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Unicode parsing error" not in proc.stderr, proc.stderr
    unused = json.loads(proc.stdout)["unused"]
    assert "res://orphan.png" in unused
    assert "res://build/fake.pck" in unused


@pytest.mark.e2e
def test_statistics_reports_counts_autoloads_and_plugins(refgraph_project):
    proc = _gda(refgraph_project, "project", "statistics", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)

    # File/line counts: at least the files the fixture wrote, with positive lines.
    assert data["total_files"] >= 8
    assert data["total_lines"] > 0
    assert data["scene_count"] == 2  # main.tscn, hero.tscn
    assert (
        data["script_count"] >= 3
    )  # main.gd, util.gd, game_state.gd (+ plugin.gd? no)
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
# Built through ``project_godot`` so e2e file logging stays disabled (issue #180).
CLASSNAME_PROJECT_GODOT = project_godot(name="gda-classname-fixture")

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
    proc = _gda(classname_project, "project", "find-references", "Hero", "--json")

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
    proc = _gda(classname_project, "project", "find-references", "Lonely", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["references"] == []


@pytest.mark.e2e
def test_statistics_counts_binary_assets_as_files_but_not_lines(tmp_path):
    # A binary asset whose bytes happen to contain newlines must contribute to
    # the file count but NOT the line count — statistics' documented contract
    # ("binary assets contribute to file counts but not line counts"). Issue #116
    # review: _count_lines previously read every file as text, so a binary asset's
    # newline bytes inflated total_lines.
    # Built through ``project_godot`` so e2e file logging stays disabled (#180).
    (tmp_path / "project.godot").write_text(
        project_godot(name="gda-binary-fixture"), encoding="utf-8"
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
    proc = subprocess.run(
        [*GDA_CMD, "project", "dependencies", "--godot", str(GODOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"


# --- every project walk agrees on a nested `.godot` directory (#712) ----------

# A project-local custom Node declared inside a NESTED `.godot` directory — the
# class the class_name index must find once the resource walk stops excluding
# that directory by name.
NESTED_THING_GD = """\
class_name NestedThing
extends Node
"""

# The same declaration authored INTO the engine's own root cache. It must stay
# invisible, so the correction does not swap one wrong enumeration for another.
CACHED_THING_GD = """\
class_name CachedThing
extends Node
"""

BARE_TSCN = """\
[gd_scene format=3]

[node name="Root" type="Node2D"]
"""


@pytest.mark.e2e
def test_project_walks_agree_on_a_nested_dot_godot_directory(tmp_path):
    # The exclusion is the engine's ONE cache directory, `res://.godot` — not
    # every directory that happens to be named `.godot`. A nested one is user
    # content (an addon vendoring a sample project, a fixture tree). #710 fixed
    # the SCRIPT walk that way and left three siblings comparing the entry name,
    # so one project answered two ways: `script list` reported a script that
    # `project statistics` counted as zero, and `node add --type` could not
    # resolve a class_name `script list` had just shown (#712). This test is that
    # cross-command agreement, not four per-walker checks — each command below
    # rides a different walk over the same tree.
    project = tmp_path / "nested-cache"
    (project / "nested" / ".godot").mkdir(parents=True)
    (project / ".godot").mkdir(parents=True, exist_ok=True)
    (project / "project.godot").write_text(
        project_godot("gda-e2e-nested-walks"), encoding="utf-8"
    )
    (project / "top.tscn").write_text(BARE_TSCN, encoding="utf-8")
    (project / "nested" / ".godot" / "hidden.tscn").write_text(
        BARE_TSCN, encoding="utf-8"
    )
    (project / "nested" / ".godot" / "hidden.gd").write_text(
        NESTED_THING_GD, encoding="utf-8"
    )
    (project / ".godot" / "engine_cache.tscn").write_text(BARE_TSCN, encoding="utf-8")
    (project / ".godot" / "engine_cache.gd").write_text(
        CACHED_THING_GD, encoding="utf-8"
    )

    scene_proc = _gda(project, "scene", "list", "--json")
    script_proc = _gda(project, "script", "list", "--json")
    stats_proc = _gda(project, "project", "statistics", "--json")

    assert scene_proc.returncode == 0, scene_proc.stdout + scene_proc.stderr
    assert script_proc.returncode == 0, script_proc.stdout + script_proc.stderr
    assert stats_proc.returncode == 0, stats_proc.stdout + stats_proc.stderr
    scenes = {s["path"] for s in json.loads(scene_proc.stdout)["scenes"]}
    scripts = {s["path"] for s in json.loads(script_proc.stdout)["scripts"]}
    stats = json.loads(stats_proc.stdout)

    # The nested content is authored content: every walk enumerates it.
    assert scenes == {"res://top.tscn", "res://nested/.godot/hidden.tscn"}
    assert scripts == {"res://nested/.godot/hidden.gd"}
    # The counts and the listings are the same project, so they agree.
    assert stats["scene_count"] == len(scenes)
    assert stats["script_count"] == len(scripts)
    # The root cache stays invisible — in the listings and in the counts alike
    # (it holds one .gd and one .tscn of its own, which must not be counted).
    assert not any(p.startswith("res://.godot/") for p in scenes | scripts)
    by_ext = {e["extension"]: e for e in stats["by_extension"]}
    assert by_ext["gd"]["files"] == 1
    assert by_ext["tscn"]["files"] == 2

    # The class_name index rides the resource walk, so node/resource creation
    # resolves the nested declaration `script list` reports...
    added = _gda(
        project, "node", "add", "res://top.tscn", "--type", "NestedThing", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout)["script_class"] == "NestedThing"
    # ...and still does not resolve one authored into the engine's own cache.
    cached = _gda(
        project, "node", "add", "res://top.tscn", "--type", "CachedThing", "--json"
    )
    assert cached.returncode == 4, cached.stdout + cached.stderr
    assert json.loads(cached.stdout)["error"]["code"] == "invalid_node_type"

    # The three remaining consumers of that same walk. They run AFTER the node
    # add, which wrote an [ext_resource] to the nested script into
    # `res://top.tscn` — so the nested content is a real reference target here,
    # not just an enumerated path.
    deps_proc = _gda(project, "project", "dependencies", "--json")
    refs_proc = _gda(
        project, "project", "find-references", "res://nested/.godot/hidden.gd", "--json"
    )
    unused_proc = _gda(project, "project", "find-unused-resources", "--json")

    assert deps_proc.returncode == 0, deps_proc.stdout + deps_proc.stderr
    assert refs_proc.returncode == 0, refs_proc.stdout + refs_proc.stderr
    assert unused_proc.returncode == 0, unused_proc.stdout + unused_proc.stderr
    by_source = {
        row["path"]: row["depends_on"]
        for row in json.loads(deps_proc.stdout)["dependencies"]
    }
    references = json.loads(refs_proc.stdout)["references"]
    unused = json.loads(unused_proc.stdout)["unused"]

    # Both nested files are graph sources, and top.tscn's edge to the nested
    # script is reported from both ends.
    assert set(by_source) == {
        "res://top.tscn",
        "res://nested/.godot/hidden.tscn",
        "res://nested/.godot/hidden.gd",
    }
    assert by_source["res://top.tscn"] == [
        {"path": "res://nested/.godot/hidden.gd", "kind": "ext_resource"}
    ]
    assert [(r["path"], r["kind"]) for r in references] == [
        ("res://top.tscn", "ext_resource")
    ]
    # The nested script is referenced now, so only the two scenes are orphans.
    assert unused == ["res://nested/.godot/hidden.tscn", "res://top.tscn"]
    # The root cache is invisible to all three. Its `.gd` and `.tscn` would
    # otherwise BOTH be dependency source rows and unused candidates, so this
    # arm fails if the exclusion ever widens past `res://.godot` itself.
    assert not any(p.startswith("res://.godot/") for p in [*by_source, *unused])


# --- alias spellings are one graph node (#774) -------------------------------
#
# A `res://` address has many lexical spellings for one file: `res://leaf.tscn`
# and `res://sub/../leaf.tscn` are the SAME file to the engine, which folds every
# address through `simplify_path` before it resolves one. The three graph reads
# used to key on the raw spelling instead, so an aliased declaration made a graph
# node no file on disk answered to, `find-references` for the real path missed the
# reference, and `find-unused-resources` therefore advised deleting a scene the
# project instances. These tests pin the identity on BOTH sides of the comparison
# — the harvested declaration and the caller's query — over every harvest site:
# an `[ext_resource]` line, a `preload()` argument, and `project.godot`'s own
# main-scene and autoload entries.

ALIAS_PROJECT_GODOT = project_godot(
    name="gda-alias-fixture",
    extra="""\
run/main_scene="res://sub/../parent.tscn"

[autoload]

Hud="*res://sub/../hud.tscn"
""",
)

# The aliased [ext_resource] declaration: parent.tscn really instances leaf.tscn,
# the engine resolves the spelling, and the graph must agree that it does.
ALIAS_PARENT_TSCN = """\
[gd_scene load_steps=2 format=3 uid="uid://baliasparent"]

[ext_resource type="PackedScene" path="res://sub/../leaf.tscn" id="1_leaf"]

[node name="Parent" type="Node2D"]

[node name="Leaf" parent="." instance=ExtResource("1_leaf")]
"""

ALIAS_LEAF_TSCN = """\
[gd_scene format=3 uid="uid://baliasleaf"]

[node name="Leaf" type="Node2D"]
"""

# The autoload scene, named by project.godot under an aliased spelling.
ALIAS_HUD_TSCN = """\
[gd_scene format=3 uid="uid://baliashud"]

[node name="Hud" type="Node"]
"""

# The reverse direction: a CANONICAL declaration the query aliases.
ALIAS_CANONICAL_TSCN = """\
[gd_scene load_steps=2 format=3 uid="uid://baliascanon"]

[ext_resource type="Texture2D" path="res://icon.png" id="1_icon"]

[node name="Canonical" type="Sprite2D"]
texture = ExtResource("1_icon")
"""

# The script-side harvest site: an already-prefixed, aliased preload argument.
ALIAS_USER_GD = """\
extends Node

const Helper = preload("res://sub/../helper.gd")
"""

ALIAS_HELPER_GD = """\
extends RefCounted
"""

ALIAS_ORPHAN_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""


@pytest.fixture
def alias_project(tmp_path):
    """A project whose references are declared under alias spellings (#774).

    Every reference here names a file that really exists and that the engine
    really resolves; only the SPELLING is aliased. ``sub/`` is a real directory
    (it holds the orphan) so the aliases read as something an agent would
    plausibly write, not as a synthetic string.
    """
    (tmp_path / "project.godot").write_text(ALIAS_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "parent.tscn").write_text(ALIAS_PARENT_TSCN, encoding="utf-8")
    (tmp_path / "leaf.tscn").write_text(ALIAS_LEAF_TSCN, encoding="utf-8")
    (tmp_path / "hud.tscn").write_text(ALIAS_HUD_TSCN, encoding="utf-8")
    (tmp_path / "canonical.tscn").write_text(ALIAS_CANONICAL_TSCN, encoding="utf-8")
    (tmp_path / "user.gd").write_text(ALIAS_USER_GD, encoding="utf-8")
    (tmp_path / "helper.gd").write_text(ALIAS_HELPER_GD, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "orphan.tres").write_text(ALIAS_ORPHAN_TRES, encoding="utf-8")
    return tmp_path


@pytest.mark.e2e
def test_dependencies_keys_an_aliased_declaration_canonically(alias_project):
    proc = _gda(alias_project, "project", "dependencies", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    by_source = {
        row["path"]: row["depends_on"]
        for row in json.loads(proc.stdout)["dependencies"]
    }

    # The aliased [ext_resource] and the aliased preload both report the file the
    # engine resolves, not the spelling the declaration used.
    assert by_source["res://parent.tscn"] == [
        {"path": "res://leaf.tscn", "kind": "ext_resource"}
    ]
    assert by_source["res://user.gd"] == [
        {"path": "res://helper.gd", "kind": "preload"}
    ]
    # No graph node names a path that no file on disk answers to.
    named = {dep["path"] for deps in by_source.values() for dep in deps}
    assert not any(".." in path.split("/") for path in named), named


@pytest.mark.e2e
def test_find_references_matches_an_aliased_declaration_from_a_canonical_query(
    alias_project,
):
    scene = _gda(
        alias_project, "project", "find-references", "res://leaf.tscn", "--json"
    )
    script = _gda(
        alias_project, "project", "find-references", "res://helper.gd", "--json"
    )

    assert scene.returncode == 0, scene.stdout + scene.stderr
    assert script.returncode == 0, script.stdout + script.stderr
    assert [(r["path"], r["kind"]) for r in json.loads(scene.stdout)["references"]] == [
        ("res://parent.tscn", "ext_resource")
    ]
    assert [
        (r["path"], r["kind"]) for r in json.loads(script.stdout)["references"]
    ] == [("res://user.gd", "preload")]


@pytest.mark.e2e
def test_find_references_matches_a_canonical_declaration_from_an_aliased_query(
    alias_project,
):
    proc = _gda(
        alias_project,
        "project",
        "find-references",
        "res://sub/../icon.png",
        "--json",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    # The echoed target keeps the caller's own spelling; the MATCHING does not.
    assert data["target"] == "res://sub/../icon.png"
    assert [(r["path"], r["kind"]) for r in data["references"]] == [
        ("res://canonical.tscn", "ext_resource")
    ]


@pytest.mark.e2e
def test_find_references_matches_an_aliased_project_level_entry(alias_project):
    # project.godot is a harvest site too: its main scene and autoloads name a
    # resource by path the way an ext_resource line does.
    main = _gda(
        alias_project, "project", "find-references", "res://parent.tscn", "--json"
    )
    autoload = _gda(
        alias_project, "project", "find-references", "res://hud.tscn", "--json"
    )

    assert main.returncode == 0, main.stdout + main.stderr
    assert autoload.returncode == 0, autoload.stdout + autoload.stderr
    assert ("project.godot", "main_scene") in {
        (r["path"], r["kind"]) for r in json.loads(main.stdout)["references"]
    }
    assert ("project.godot", "autoload") in {
        (r["path"], r["kind"]) for r in json.loads(autoload.stdout)["references"]
    }


@pytest.mark.e2e
def test_find_unused_resources_never_lists_an_aliased_reference(alias_project):
    proc = _gda(alias_project, "project", "find-unused-resources", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    unused = json.loads(proc.stdout)["unused"]

    # The destructive advice this issue is about: leaf.tscn is instanced by
    # parent.tscn, and parent.tscn/hud.tscn are project entry points — all three
    # under alias spellings. None of them is deletable.
    assert "res://leaf.tscn" not in unused
    assert "res://parent.tscn" not in unused
    assert "res://hud.tscn" not in unused
    assert "res://icon.png" not in unused
    # The report still works: the genuinely unreferenced resource is reported.
    assert "res://sub/orphan.tres" in unused

    # The consistency criterion holds under alias spellings too: unused means
    # exactly "find-references returns empty".
    for path in unused:
        refs = json.loads(
            _gda(alias_project, "project", "find-references", path, "--json").stdout
        )["references"]
        assert refs == [], f"{path} reported unused but has references {refs}"
