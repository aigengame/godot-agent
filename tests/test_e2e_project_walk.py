"""S1 (e2e): the shared ``res://`` walk's two behavioural contracts (#764).

The four project-wide collectors in ``operations.gd`` run ONE traversal. These
tests pin the two things that consolidation had to decide or preserve, against a
real engine:

* **The acceptance test is case-insensitive.** The scene walk used to compare the
  extension as written while the script walk lowercased it, so a ``Level.TSCN``
  counted as a scene in ``project statistics`` (which lowercases) and was
  invisible to ``scene list``. The engine is the arbiter and is case-insensitive
  — ``ResourceFormatLoader::recognize_path`` matches the extension with
  ``nocasecmp_to`` — so the listings match it, and ``scene list`` grew that entry.
* **The two file universes survive.** A shared traversal is not a shared
  universe: ``project statistics`` must keep counting the ``.import`` sidecars and
  ``project.godot`` that the extension-filtered walk behind ``dependencies`` /
  ``find-unused-resources`` excludes.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

PROJECT_GODOT = project_godot(name="gda-walk-fixture")

# Two scenes and two scripts, one of each written with an UPPERCASE extension.
# The base names differ so the fixture is also valid on a case-insensitive
# filesystem (macOS APFS preserves case but would collapse main.tscn/MAIN.TSCN).
MAIN_TSCN = """\
[gd_scene format=3]

[node name="Main" type="Node2D"]
"""

LEVEL_TSCN = """\
[gd_scene format=3]

[node name="Level" type="Node3D"]
"""

HELPER_GD = """\
extends RefCounted
"""

WIDGET_GD = """\
extends Node
"""

# An import sidecar for a leaf asset — the engine's own bookkeeping, in the
# unfiltered universe only.
ICON_IMPORT = """\
[remap]

importer="texture"
type="CompressedTexture2D"
"""


@pytest.fixture
def walk_project(tmp_path):
    """A project holding both extension cases and both file universes."""
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "Level.TSCN").write_text(LEVEL_TSCN, encoding="utf-8")
    (tmp_path / "helper.gd").write_text(HELPER_GD, encoding="utf-8")
    (tmp_path / "Widget.GD").write_text(WIDGET_GD, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (tmp_path / "icon.png.import").write_text(ICON_IMPORT, encoding="utf-8")
    return tmp_path


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
        capture_output=True,
        text=True,
    )


def _result(project, *args: str) -> dict:
    proc = _gda(project, *args, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.e2e
def test_the_listings_accept_an_extension_in_any_case_as_the_engine_does(walk_project):
    # AC2 (#764): the case-sensitivity drift is resolved case-INSENSITIVELY, on
    # both sides. `Level.TSCN` is a scene to the engine (it loads as a
    # PackedScene, reported below through root_type) so `scene list` reports it;
    # `Widget.GD` was already accepted by the script walk and stays accepted.
    scenes = {s["path"]: s for s in _result(walk_project, "scene", "list")["scenes"]}
    scripts = {s["path"] for s in _result(walk_project, "script", "list")["scripts"]}

    assert set(scenes) == {"res://main.tscn", "res://Level.TSCN"}
    assert scripts == {"res://helper.gd", "res://Widget.GD"}

    # The engine really reads the uppercase file AS a scene — the listing is not
    # reporting a path it could not load.
    assert scenes["res://Level.TSCN"]["root_type"] == "Node3D"

    # And the two ends now agree, which is the point: `project statistics`
    # classifies by a lowercased extension, so its counts match the listings.
    # Before this change it counted a scene `scene list` could not see (#712's
    # failure shape, on the acceptance test instead of the descent decision).
    stats = _result(walk_project, "project", "statistics")
    assert stats["scene_count"] == len(scenes)
    assert stats["script_count"] == len(scripts)


@pytest.mark.e2e
def test_the_two_file_universes_survive_the_shared_traversal(walk_project):
    # AC4 (#764): one traversal, two universes. `project statistics` counts every
    # file it reaches — including the `.import` sidecar and `project.godot` — while
    # the extension-filtered walk behind the reference graph excludes exactly
    # those, and still sees the leaf asset beside them.
    stats = _result(walk_project, "project", "statistics")
    by_ext = {e["extension"]: e["files"] for e in stats["by_extension"]}

    assert by_ext.get("import") == 1, by_ext  # icon.png.import
    assert by_ext.get("godot") == 1, by_ext  # project.godot
    assert stats["total_files"] == sum(by_ext.values())

    # The filtered universe: the sidecar and the project file are not resources,
    # so they are neither unused-resource candidates nor dependency sources...
    unused = set(_result(walk_project, "project", "find-unused-resources")["unused"])
    sources = {
        d["path"]
        for d in _result(walk_project, "project", "dependencies")["dependencies"]
    }
    excluded = {"res://icon.png.import", "res://project.godot"}
    assert not (unused & excluded), unused
    assert not (sources & excluded), sources

    # ...while the leaf asset sitting right next to the sidecar still is one, so
    # the exclusion is the acceptance test's, not an emptied walk.
    assert "res://icon.png" in unused
