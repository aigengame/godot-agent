"""S1 (e2e): the shared ``res://`` walk's behavioural contracts (#764, #760).

The four project-wide collectors in ``operations.gd`` run ONE traversal. These
tests pin, against a real engine, the two things that consolidation had to decide
or preserve:

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

…and the walk's **symlink policy** (#760), which that consolidation deliberately
left undecided: the walk follows a link as the engine does, but identifies what it
reaches by filesystem identity, so an alias cannot re-admit the engine cache and a
cycle cannot spell one file 33 ways.
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


# --- the symlink policy (#760) ---------------------------------------------
#
# The walk had none: it compared paths lexically and descended into whatever the
# listing called a directory, so an alias re-admitted the engine cache the walk
# excludes and a cycle ran to the OS symlink limit. The fixture below carries all
# four shapes at once, because the policy is one decision and the collectors must
# answer it the same way.

# Two files planted INSIDE the engine cache — content no agent authored, which
# every collector must keep out however it is spelled. `class_name` is what makes
# the aliasing visible in the resolver too: it is the exact repro from #760.
ROOT_CACHE_GD = """\
extends RefCounted
class_name RootCacheThing
"""

ROOT_CACHE_TSCN = """\
[gd_scene format=3]

[node name="RootCache" type="Node2D"]
"""

CACHED_IMPORT_GD = """\
extends RefCounted
class_name CachedImport
"""

# The authored content a link legitimately points at: a checkout that physically
# lives OUTSIDE res:// and is reached through a directory link inside it. This is
# the workflow the policy must not break — the ADR-0006 addressing gate already
# treats such a file as inside the project because the engine walks the link.
VENDORED_GD = """\
extends Node
class_name VendoredThing
"""

VENDORED_TSCN = """\
[gd_scene format=3]

[node name="Vendored" type="Node3D"]
"""

LEAF_GD = """\
extends Node
"""


@pytest.fixture
def symlink_project(tmp_path):
    """A project carrying every symlink shape the policy decides (#760).

    * ``nested/.godot`` -> the root cache: a directory alias AT the cache;
    * ``nested/imported_alias`` -> ``.godot/imported``: an alias INTO the cache;
    * ``alias_cache.gd`` / ``alias_cache.tscn``: FILE aliases at cache files,
      which reach the acceptance test without passing the descent predicate;
    * ``sub/loop`` -> ``sub``: a cycle;
    * ``vendored`` -> a checkout outside the project: the legitimate workflow.
    """
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-symlink-fixture"), encoding="utf-8"
    )

    cache = project / ".godot"
    (cache / "imported").mkdir(parents=True)
    (cache / "root_cache.gd").write_text(ROOT_CACHE_GD, encoding="utf-8")
    (cache / "root_cache.tscn").write_text(ROOT_CACHE_TSCN, encoding="utf-8")
    (cache / "imported" / "cached.gd").write_text(CACHED_IMPORT_GD, encoding="utf-8")

    (project / "nested").mkdir()
    (project / "nested" / ".godot").symlink_to(cache, target_is_directory=True)
    (project / "nested" / "imported_alias").symlink_to(
        cache / "imported", target_is_directory=True
    )
    (project / "alias_cache.gd").symlink_to(cache / "root_cache.gd")
    (project / "alias_cache.tscn").symlink_to(cache / "root_cache.tscn")

    (project / "sub").mkdir()
    (project / "sub" / "leaf.gd").write_text(LEAF_GD, encoding="utf-8")
    (project / "sub" / "loop").symlink_to(project / "sub", target_is_directory=True)

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "vendored.gd").write_text(VENDORED_GD, encoding="utf-8")
    (checkout / "vendored.tscn").write_text(VENDORED_TSCN, encoding="utf-8")
    (project / "vendored").symlink_to(checkout, target_is_directory=True)

    return project


def _walked_paths(project) -> set[str]:
    """Every path the four collectors reach, as one set.

    The policy is one decision, so the assertions are made against the union: a
    path admitted by any collector is a path the walk admitted.
    """
    scripts = {s["path"] for s in _result(project, "script", "list")["scripts"]}
    scenes = {s["path"] for s in _result(project, "scene", "list")["scenes"]}
    sources = {
        d["path"] for d in _result(project, "project", "dependencies")["dependencies"]
    }
    unused = set(_result(project, "project", "find-unused-resources")["unused"])
    return scripts | scenes | sources | unused


@pytest.mark.e2e
def test_an_alias_cannot_re_admit_the_engine_cache(symlink_project):
    # AC2 (#760): the excluded cache stays excluded however it is spelled — as a
    # directory alias AT it, as a directory alias INTO one of its subdirectories,
    # and as a FILE alias at a file inside it. The last one is the shape that
    # never reaches the descent predicate at all.
    walked = _walked_paths(symlink_project)

    # Every spelling that reaches cache content, listed by shape so a leak names
    # which half of the policy let it through. None of these paths contains the
    # excluded directory's own name, which is the whole difficulty: an alias
    # renames it.
    aliased = {
        "res://nested/.godot/root_cache.gd",  # directory alias AT the cache
        "res://nested/.godot/root_cache.tscn",
        "res://nested/imported_alias/cached.gd",  # directory alias INTO it
        "res://alias_cache.gd",  # file alias at a file inside it
        "res://alias_cache.tscn",
    }
    assert not (walked & aliased), walked & aliased

    # `project statistics` counts over the unfiltered universe, so it is the
    # collector that would show the cache re-entering as a raw count.
    stats = _result(symlink_project, "project", "statistics")
    assert stats["script_count"] == 2, stats  # sub/leaf.gd and vendored/vendored.gd
    assert stats["scene_count"] == 1, stats  # vendored/vendored.tscn — nothing aliased

    # And the class_name index, the fifth consumer of the same walk (ADR-0032):
    # both cache-declared classes were resolvable through their aliases before.
    scene = symlink_project / "host.tscn"
    _result(
        symlink_project, "scene", "create", "res://host.tscn", "--root-type", "Node"
    )
    assert scene.exists()
    for cache_class in ("RootCacheThing", "CachedImport"):
        proc = _gda(
            symlink_project,
            "node",
            "add",
            "res://host.tscn",
            "--parent",
            ".",
            "--name",
            "X",
            "--type",
            cache_class,
            "--json",
        )
        error = json.loads(proc.stdout)["error"]
        assert error["code"] == "invalid_node_type", error
        assert cache_class in error["message"]


@pytest.mark.e2e
def test_a_symlink_cycle_terminates_without_fabricated_paths(symlink_project):
    # AC3 (#760): `sub/loop -> sub` used to be descended until the OS refused
    # another symlink hop, and every entry past the first named a file that had
    # already been reported under a shorter path — 33 spellings of one `.gd`, the
    # deepest 174 characters long. The link is now not followed, because it leads
    # back to a directory already on the descent chain, so the real file is
    # reported once and no path is invented.
    walked = _walked_paths(symlink_project)

    assert "res://sub/leaf.gd" in walked
    assert not {p for p in walked if "/loop/" in p}, walked

    # The termination is a rule, not a truncation: the counting collector agrees
    # with the listing rather than reporting the OS limit's leftovers.
    scripts = [s["path"] for s in _result(symlink_project, "script", "list")["scripts"]]
    assert scripts.count("res://sub/leaf.gd") == 1, scripts


@pytest.mark.e2e
def test_a_link_to_authored_content_is_still_walked(symlink_project):
    # AC1 (#760): the policy decides by WHERE a link leads, not by refusing
    # links. A vendored checkout that physically lives outside res:// and is
    # reached through a directory link is ordinary authored content — the engine
    # loads through the link and the ADR-0006 addressing gate already calls such
    # a file inside the project — so the walk enumerates it, and its `class_name`
    # resolves at the instantiating call sites.
    walked = _walked_paths(symlink_project)

    assert "res://vendored/vendored.gd" in walked, walked
    assert "res://vendored/vendored.tscn" in walked, walked

    _result(
        symlink_project, "scene", "create", "res://host.tscn", "--root-type", "Node"
    )
    added = _result(
        symlink_project,
        "node",
        "add",
        "res://host.tscn",
        "--parent",
        ".",
        "--name",
        "Vendored",
        "--type",
        "VendoredThing",
    )
    assert added["script_class"] == "VendoredThing", added
