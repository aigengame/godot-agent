"""S1 (e2e): the shared ``res://`` walk's behavioural contracts (#764, #760, #804).

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

…and the walk's **engine skip rule** (#804): the traversal now declines a directory
that holds a ``project.godot`` (a nested project) or a ``.gdignore``, the two
markers ``EditorFileSystem::_should_skip_directory`` skips on, so every collector's
universe is the engine's.
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
#
# They extend **Node** so the index assertion can FAIL. Both once extended
# RefCounted, which made `node add --type RootCacheThing` answer
# `invalid_node_type` whether or not the alias leaked — the leak reported "is not
# a Node-derived script: res://<alias>", the clean walk "no .gd script declares
# class_name" — so the guard for the fifth consumer of the walk asserted a code
# that no regression could change (#795 review). Node-derived, a leak makes the
# same call SUCCEED, which is an outcome no wording can blur.
ROOT_CACHE_GD = """\
extends Node
class_name RootCacheThing
"""

ROOT_CACHE_TSCN = """\
[gd_scene format=3]

[node name="RootCache" type="Node2D"]
"""

CACHED_IMPORT_GD = """\
extends Node
class_name CachedImport
"""

# The authored content a link legitimately points at: a checkout that physically
# lives OUTSIDE res:// and is reached through a directory link inside it. This is
# the workflow the policy must not break — gda's own containment gate
# (``src/gda/project.py``) already treats such a file as inside the project
# because the engine walks the link.
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


def _assert_class_name_unresolvable(project, *classes: str) -> None:
    """Every named ``class_name`` must be unknown to the index (ADR-0032).

    The index is the fifth consumer of the same walk, and the only one that
    reports through another command. The planted cache scripts are Node-derived,
    so a walk that admits one makes ``node add --type <class>`` **succeed** —
    the assertion below then fails on the missing ``error`` key, not on wording.
    The message half is asserted too, because it is the half that distinguishes
    "no script declares this" from every other ``invalid_node_type``.
    """
    _result(project, "scene", "create", "res://host.tscn", "--root-type", "Node")
    for name in classes:
        proc = _gda(
            project,
            "node",
            "add",
            "res://host.tscn",
            "--parent",
            ".",
            "--name",
            "X",
            "--type",
            name,
            "--json",
        )
        payload = json.loads(proc.stdout)
        assert "error" in payload, f"{name} resolved through an alias: {payload}"
        error = payload["error"]
        assert error["code"] == "invalid_node_type", error
        assert f"no .gd script declares class_name {name}" in error["message"], error


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
    _assert_class_name_unresolvable(symlink_project, "RootCacheThing", "CachedImport")


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
    # loads through the link and gda's own containment gate already calls such a
    # file inside the project — so the walk enumerates it, and its `class_name`
    # resolves at the instantiating call sites. Enumerating it is not the same as
    # letting it be NAMED as a target: that is the containment gate's question,
    # not this walk's.
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


# --- the SPELLING that reaches a link is not the directory it lives in --------
#
# The fixture above builds every link with an ABSOLUTE target and never nests one
# link inside another, so it could not see the defect the first fix shipped with:
# a RELATIVE target was joined onto the link's res:// spelling instead of onto the
# directory the kernel reads it from, which is a different directory as soon as
# the link's own parent is a link (#795 review). The two fixtures below carry the
# missing shapes, one per direction of the same error.

# A cache script under the VENDORED checkout's own `.godot`, not the project's.
# #712 decided a nested cache is walked — it is usually authored content — so
# this file must stay VISIBLE. It is the direction in which mistaking a spelling
# for a real directory hides authored content instead of leaking cache content.
VENDORED_SAMPLE_GD = """\
extends Node
class_name VendoredSample
"""

# How far below the engine cache the deep alias points. The ancestor climb used
# to give up after SYMLINK_PROBE_MAX_STEPS components and answer "not the cache",
# so an alias exactly this deep was admitted while one level shallower was not.
CACHE_DEPTH_PAST_THE_OLD_STEP_BOUND = 32


@pytest.fixture
def aliased_spelling_project(tmp_path):
    """One real directory reached under two ``res://`` spellings (#795 review).

    ``sub/deep`` holds three ordinary RELATIVE links into the engine cache, and
    ``link1`` is a second spelling of ``sub/deep`` itself, so ``res://link1/c``
    and ``res://sub/deep/c`` are the same directory entry. ``L2`` adds a link
    THROUGH a link, the shape that survives resolving only one more component.
    """
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-alias-spelling-fixture"), encoding="utf-8"
    )

    cache = project / ".godot"
    (cache / "imported").mkdir(parents=True)
    (cache / "root_cache.gd").write_text(ROOT_CACHE_GD, encoding="utf-8")
    (cache / "root_cache.tscn").write_text(ROOT_CACHE_TSCN, encoding="utf-8")
    (cache / "imported" / "cached.gd").write_text(CACHED_IMPORT_GD, encoding="utf-8")

    (project / "real.gd").write_text(LEAF_GD, encoding="utf-8")
    deep = project / "sub" / "deep"
    deep.mkdir(parents=True)
    (deep / "deep_leaf.gd").write_text(LEAF_GD, encoding="utf-8")
    # Relative targets, as a checked-in repo writes them: a directory link AT the
    # cache, one INTO a subdirectory of it, and a FILE link at a file inside it.
    (deep / "c").symlink_to("../../.godot", target_is_directory=True)
    (deep / "ci").symlink_to("../../.godot/imported", target_is_directory=True)
    (deep / "f_alias.gd").symlink_to("../../.godot/root_cache.gd")
    (project / "link1").symlink_to("sub/deep", target_is_directory=True)
    (project / "L2").symlink_to("link1/c", target_is_directory=True)
    return project


@pytest.fixture
def vendored_cache_project(tmp_path):
    """A vendored checkout outside ``res://`` carrying a cache of its OWN."""
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-vendored-cache-fixture"), encoding="utf-8"
    )
    cache = project / ".godot"
    cache.mkdir()
    (cache / "root_cache.gd").write_text(ROOT_CACHE_GD, encoding="utf-8")
    (project / "real.gd").write_text(LEAF_GD, encoding="utf-8")

    checkout = tmp_path / "checkout"
    (checkout / ".godot").mkdir(parents=True)
    (checkout / ".godot" / "vendored_sample.gd").write_text(
        VENDORED_SAMPLE_GD, encoding="utf-8"
    )
    (checkout / "v").mkdir()
    (checkout / "v" / "x").symlink_to("../.godot", target_is_directory=True)
    (project / "vendored").symlink_to(checkout / "v", target_is_directory=True)
    return project


@pytest.mark.e2e
def test_the_cache_stays_excluded_under_a_second_spelling_of_its_parent(
    aliased_spelling_project,
):
    # AC2 (#760), the case the absolute-target fixture cannot build: the walk
    # reads `sub/deep/c -> ../../.godot` against the directory the KERNEL reads
    # it from, so `res://link1/c` — the same entry under a second spelling — is
    # the cache too. Joining the target onto the spelling `res://link1` instead
    # answered `res://link1/../../.godot`, which is not the cache, and every
    # collector then enumerated the cache's contents under that name.
    walked = _walked_paths(aliased_spelling_project)

    leaked = {p for p in walked if p.startswith(("res://link1/c/", "res://L2/"))}
    leaked |= {"res://link1/ci/cached.gd", "res://link1/f_alias.gd"} & walked
    leaked |= {p for p in walked if p.startswith("res://sub/deep/c")}
    leaked |= {"res://sub/deep/ci/cached.gd", "res://sub/deep/f_alias.gd"} & walked
    assert not leaked, leaked

    # The authored file in that same directory is still reported under BOTH of
    # its real spellings — the rule excludes the cache, it does not refuse the
    # link that renamed the directory.
    assert {
        "res://real.gd",
        "res://sub/deep/deep_leaf.gd",
        "res://link1/deep_leaf.gd",
    } <= walked, walked

    stats = _result(aliased_spelling_project, "project", "statistics")
    assert stats["script_count"] == 3, stats
    assert stats["scene_count"] == 0, stats

    _assert_class_name_unresolvable(
        aliased_spelling_project, "RootCacheThing", "CachedImport"
    )


@pytest.mark.e2e
def test_a_vendored_checkouts_own_cache_is_not_taken_for_the_projects(
    vendored_cache_project,
):
    # The same error in the other direction, and a regression the first fix
    # introduced: `vendored/x -> ../.godot` is the CHECKOUT's cache, but joining
    # that target onto the res:// spelling `res://vendored` produced
    # `res://.godot`, which is_equivalent then confirmed against the project's own
    # cache — so a nested cache #712 decided to walk was silently hidden.
    scripts = {
        s["path"] for s in _result(vendored_cache_project, "script", "list")["scripts"]
    }

    assert "res://vendored/x/vendored_sample.gd" in scripts, scripts
    # The project's OWN cache is still excluded, under its own name and through
    # the link — the fix widens nothing.
    assert not {p for p in scripts if "root_cache" in p}, scripts
    assert scripts == {"res://real.gd", "res://vendored/x/vendored_sample.gd"}


@pytest.mark.e2e
def test_a_cache_alias_is_excluded_however_deep_below_the_cache_it_points(tmp_path):
    # The exclusion asks whether any ANCESTOR of the resolved path is the cache.
    # That climb once ran on a step budget borrowed from the symlink bound, and
    # exhausting it returned "not the cache" — so an alias exactly
    # SYMLINK_PROBE_MAX_STEPS levels below `res://.godot` was admitted while a
    # shallower one was excluded (#795 review). Path depth is not a symlink
    # count; the climb now ends at the root instead.
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-deep-cache-fixture"), encoding="utf-8"
    )
    (project / "real.gd").write_text(LEAF_GD, encoding="utf-8")

    deep = project / ".godot"
    for level in range(CACHE_DEPTH_PAST_THE_OLD_STEP_BOUND):
        deep = deep / f"d{level}"
    deep.mkdir(parents=True)
    (deep / "deep_cache.gd").write_text(ROOT_CACHE_GD, encoding="utf-8")
    (project / "alias_deep").symlink_to(deep, target_is_directory=True)

    scripts = {s["path"] for s in _result(project, "script", "list")["scripts"]}
    assert scripts == {"res://real.gd"}, scripts
    _assert_class_name_unresolvable(project, "RootCacheThing")


# --- the engine's own skip rule (#804) ---------------------------------------
#
# The walk descended into two kinds of directory the engine's scan never enters:
# one holding a `project.godot` (another project inside this one) and one holding
# a `.gdignore`. Every collector's universe was therefore wider than the engine's,
# and `script validate --all` compiled a nested project's scripts against the
# OUTER root — the same false `res://` cascade ADR-0006's gate refuses when the
# same file is NAMED, so one file got opposite answers depending on the selector.

# The nested project's own script, preloading a path that exists only under the
# NESTED root. Compiled against the outer root it cannot resolve, which is what
# made the cascade visible; it is Node-derived so a leak into the class_name index
# makes `node add --type InnerThing` SUCCEED rather than merely change wording.
INNER_GD = """\
extends Node
class_name InnerThing

const Asset = preload("res://asset.gd")
"""

INNER_TSCN = """\
[gd_scene format=3]

[node name="Inner" type="Node3D"]
"""

IGNORED_GD = """\
extends Node
class_name IgnoredThing
"""

IGNORED_TSCN = """\
[gd_scene format=3]

[node name="Ignored" type="Node3D"]
"""

OUTER_GD = """\
extends Node
class_name OuterThing
"""

# Declared TWICE — once in the outer project, once in the nested one. While the
# walk entered the nested project this was `ambiguous_class_name`; the skip rule
# makes it resolve, which is the reversal ADR-0032 records.
DUPLICATE_GD = """\
extends Node
class_name DuplicateThing
"""

# A sidecar with a declared importer and no `.md5` receipt: the engine's own
# "reimport" state, so the asset counts as an import GAP wherever the scan reaches
# it.
STALE_IMPORT = """\
[remap]

importer="texture"
type="CompressedTexture2D"
uid="uid://c8gda804test"
"""


@pytest.fixture
def skipped_directory_project(tmp_path):
    """An outer project holding a nested project and a ``.gdignore`` tree (#804).

    Both skipped directories carry a script, a scene, and a stale-sidecar asset,
    so every collector — the four listings, the class_name index, and the import
    gap inventory — has something to report there if the walk still reaches it.
    """
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-skip-rule-fixture"), encoding="utf-8"
    )
    (project / "outer.gd").write_text(OUTER_GD, encoding="utf-8")
    (project / "duplicate.gd").write_text(DUPLICATE_GD, encoding="utf-8")
    (project / "outer.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (project / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (project / "pic.png.import").write_text(STALE_IMPORT, encoding="utf-8")

    nested = project / "nested"
    nested.mkdir()
    (nested / "project.godot").write_text(
        project_godot(name="gda-skip-rule-inner"), encoding="utf-8"
    )
    (nested / "asset.gd").write_text(LEAF_GD, encoding="utf-8")
    (nested / "inner.gd").write_text(INNER_GD, encoding="utf-8")
    (nested / "duplicate.gd").write_text(DUPLICATE_GD, encoding="utf-8")
    (nested / "inner.tscn").write_text(INNER_TSCN, encoding="utf-8")
    (nested / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (nested / "pic.png.import").write_text(STALE_IMPORT, encoding="utf-8")

    ignored = project / "ignored"
    ignored.mkdir()
    (ignored / ".gdignore").write_text("", encoding="utf-8")
    (ignored / "ignored.gd").write_text(IGNORED_GD, encoding="utf-8")
    (ignored / "ignored.tscn").write_text(IGNORED_TSCN, encoding="utf-8")
    (ignored / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (ignored / "pic.png.import").write_text(STALE_IMPORT, encoding="utf-8")
    return project


# Every res:// path inside the two skipped directories. A collector reporting any
# of them has walked where the engine's scan does not.
SKIPPED_PATHS = frozenset(
    {
        "res://nested/project.godot",
        "res://nested/asset.gd",
        "res://nested/inner.gd",
        "res://nested/duplicate.gd",
        "res://nested/inner.tscn",
        "res://nested/pic.png",
        "res://nested/pic.png.import",
        "res://ignored/.gdignore",
        "res://ignored/ignored.gd",
        "res://ignored/ignored.tscn",
        "res://ignored/pic.png",
        "res://ignored/pic.png.import",
    }
)


@pytest.mark.e2e
def test_the_listings_skip_a_nested_project_and_a_gdignore_directory(
    skipped_directory_project,
):
    # AC1/AC3 (#804): the rule lives in the ONE shared traversal, so the four
    # listings answer together. Before it, `script list` named
    # res://nested/inner.gd, res://nested/duplicate.gd, res://nested/asset.gd and
    # res://ignored/ignored.gd; `scene list` named both skipped scenes; and
    # `project statistics` counted the second `project.godot` and the `.gdignore`
    # marker as files of this project.
    walked = _walked_paths(skipped_directory_project)
    assert not (walked & SKIPPED_PATHS), walked & SKIPPED_PATHS

    scripts = {
        s["path"]
        for s in _result(skipped_directory_project, "script", "list")["scripts"]
    }
    assert scripts == {"res://outer.gd", "res://duplicate.gd"}, scripts

    scenes = {
        s["path"] for s in _result(skipped_directory_project, "scene", "list")["scenes"]
    }
    assert scenes == {"res://outer.tscn"}, scenes

    # The unfiltered universe is the one that counts a `project.godot` and the
    # `.gdignore` marker itself, so it is where a re-entry shows up as a raw count.
    stats = _result(skipped_directory_project, "project", "statistics")
    by_ext = {e["extension"]: e["files"] for e in stats["by_extension"]}
    assert stats["script_count"] == 2, stats
    assert stats["scene_count"] == 1, stats
    assert by_ext.get("godot") == 1, by_ext  # the OUTER project.godot alone
    assert "gdignore" not in by_ext, by_ext

    # The outer project's own content is untouched: only a marked directory
    # changes answer.
    assert {"res://outer.gd", "res://duplicate.gd", "res://outer.tscn"} <= walked


@pytest.mark.e2e
def test_validate_all_and_the_named_target_agree_on_a_nested_projects_script(
    skipped_directory_project,
):
    # AC2 (#804): the same file must not get opposite answers depending on the
    # selector. `--all` used to compile res://nested/inner.gd against the OUTER
    # root and report `Preload file "res://asset.gd" does not exist.` — a false
    # cascade — while NAMING that file is refused outright by ADR-0006's ownership
    # gate. The walk no longer reaches it, so `--all` reports only what the outer
    # project owns and the refusal stays the one true answer for the nested file.
    validated = _result(skipped_directory_project, "script", "validate", "--all")
    assert {s["path"] for s in validated["scripts"]} == {
        "res://outer.gd",
        "res://duplicate.gd",
    }, validated
    assert validated["valid"] is True, validated

    proc = _gda(
        skipped_directory_project,
        "script",
        "validate",
        "res://nested/inner.gd",
        "--json",
    )
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "target_outside_project", error
    assert error["evidence"]["owning_project"].endswith("/nested"), error


@pytest.mark.e2e
def test_the_class_name_index_follows_the_walk_out_of_a_skipped_directory(
    skipped_directory_project,
):
    # AC3 (#804): the class_name index is the FIFTH consumer of the same walk
    # (ADR-0032), and the skip rule REVERSES the vendored-tree trade #712/#760
    # recorded. Both consequences are asserted, because both are the point:
    _assert_class_name_unresolvable(
        skipped_directory_project, "InnerThing", "IgnoredThing"
    )

    # ...and a duplicate that existed only because the walk entered the nested
    # project is no longer a duplicate, so a name that reported
    # `ambiguous_class_name` now resolves — to the outer project's declaration.
    added = _result(
        skipped_directory_project,
        "node",
        "add",
        "res://host.tscn",  # created by the helper above
        "--parent",
        ".",
        "--name",
        "Dup",
        "--type",
        "DuplicateThing",
    )
    assert added["script_class"] == "DuplicateThing", added

    # `find-references` shares the identical resolver, so it agrees: the outer
    # class is a resolvable target, the nested one is not a class at all.
    assert (
        _result(skipped_directory_project, "project", "find-references", "OuterThing")[
            "target"
        ]
        == "OuterThing"
    )
    proc = _gda(
        skipped_directory_project,
        "project",
        "find-references",
        "InnerThing",
        "--json",
    )
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "invalid_target", error
    assert "no .gd script declares class_name InnerThing" in error["message"], error


@pytest.mark.e2e
def test_the_import_gap_listing_promises_nothing_in_a_skipped_directory(
    skipped_directory_project,
):
    # AC3 (#804), the sixth surface. `pass_will_also_import` PREDICTS what a
    # project-wide `--import` pass will re-import besides the request; the engine's
    # scan skips both marked directories, so their stale sidecars were a promise of
    # work the pass never does. It listed res://ignored/pic.png and
    # res://nested/pic.png before.
    predicted = _result(
        skipped_directory_project,
        "resource",
        "import",
        "res://pic.png",
        "--dry-run",
    )
    assert predicted["engine_pass"] is True, predicted  # the request itself is stale
    assert predicted["pass_will_also_import"] == [], predicted
