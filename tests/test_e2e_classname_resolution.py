"""S1 (e2e): project-local ``class_name`` resolution via the gda-owned static scan (ADR-0032, #360).

Before #360, ``node add --type <class_name>``, ``resource create --type
<class_name>`` and ``project find-references <class_name>`` resolved a
project-local ``class_name`` ONLY through the editor global class list
(``ProjectSettings.get_global_class_list()``), which is populated exclusively by
the Godot editor scan into ``.godot/global_script_class_cache.cfg``. In a
headless, **editor-never-opened** project — gda's core target — there is no
``.godot/``, so the list is empty and a valid project-local ``class_name`` was
unresolvable.

ADR-0032 adds a single unified resolver shared by all three sites: cache-first
(the editor global class list stays first, so editor-opened projects are
unchanged), then a gda-owned static scan of the project's own ``.gd`` sources
when the cache misses. These tests exercise the change through the REAL engine
(so operations.gd is loaded and parsed), across the four contract scenarios:

(a) no ``.godot/`` + a project-local ``class_name`` → all three commands resolve;
(b) an editor-opened project (with a populated ``.godot/`` cache) resolves
    exactly as before — the fallback is unobservable;
(c) a ``class_name`` declared in more than one ``.gd`` → ``ambiguous_class_name``
    naming the conflicting paths, for all three commands;
(d) a truly unknown ``--type`` still errors with an ACTIONABLE message that names
    the missing-class cause and does not cite the editor cache.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# Built through ``project_godot`` so e2e file logging stays disabled (issue #180).
CLASSNAME_RES_PROJECT_GODOT = project_godot(name="gda-classname-res-fixture")

# A project-local custom Resource: `class_name PandaStats extends Resource`.
PANDA_STATS_GD = """\
class_name PandaStats
extends Resource

@export var speed: float = 2.5
"""

# A project-local custom Node: `class_name Hero extends Node2D`.
HERO_GD = """\
class_name Hero
extends Node2D
"""

# A genuine consumer of Hero — the reference find-references must report.
VILLAIN_GD = """\
extends Hero

func taunt() -> void:
	pass
"""


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
        capture_output=True,
        text=True,
    )


def _import_project(project) -> None:
    # An editor/import scan is what populates .godot/global_script_class_cache.cfg
    # (tier 2). Scenario (b) runs it; scenarios (a), (c), (d) deliberately do NOT,
    # so the resolver must fall through to the static scan (tier 3).
    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.fixture
def uncached_project(tmp_path):
    """An editor-never-opened project (NO .godot/) with project-local classes."""
    (tmp_path / "project.godot").write_text(
        CLASSNAME_RES_PROJECT_GODOT, encoding="utf-8"
    )
    (tmp_path / "panda_stats.gd").write_text(PANDA_STATS_GD, encoding="utf-8")
    (tmp_path / "hero.gd").write_text(HERO_GD, encoding="utf-8")
    (tmp_path / "villain.gd").write_text(VILLAIN_GD, encoding="utf-8")
    return tmp_path


# --- (a) no .godot/ : the static scan resolves all three sites ---------------


@pytest.mark.e2e
def test_resource_create_resolves_project_class_name_without_editor_cache(
    uncached_project,
):
    # The core #360 scenario: resource create resolves a project-local
    # class_name via the static scan, with NO editor-generated .godot/ cache.
    assert not (uncached_project / ".godot").exists()
    resource_path = uncached_project / "panda.tres"

    created = _gda(
        uncached_project,
        "resource",
        "create",
        str(resource_path),
        "--type",
        "PandaStats",
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["type"] == "PandaStats"
    assert resource_path.exists()
    # The written .tres is a real Godot resource carrying the script class.
    assert 'script_class="PandaStats"' in resource_path.read_text(encoding="utf-8")
    # The resolver never triggers an editor scan / writes into the project.
    assert not (uncached_project / ".godot").exists()


@pytest.mark.e2e
def test_node_add_resolves_project_class_name_without_editor_cache(uncached_project):
    # node add resolves a project-local class_name Node via the static scan.
    assert not (uncached_project / ".godot").exists()
    scene_path = uncached_project / "main.tscn"
    created = _gda(
        uncached_project,
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = _gda(
        uncached_project, "node", "add", str(scene_path), "--type", "Hero", "--json"
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert data["type"] == "Node2D"
    assert data["script_class"] == "Hero"
    assert "hero.gd" in scene_path.read_text(encoding="utf-8")


@pytest.mark.e2e
def test_find_references_resolves_project_class_name_without_editor_cache(
    uncached_project,
):
    # find-references resolves the class_name via the SAME static scan, so it and
    # resource create agree on whether Hero resolves in a never-opened project —
    # no more "not a res:// path or a registered class_name" for a real class.
    assert not (uncached_project / ".godot").exists()

    proc = _gda(uncached_project, "project", "find-references", "Hero", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["target"] == "Hero"
    referencing = {(r["path"], r["kind"]) for r in data["references"]}
    # villain.gd's `extends Hero` is reported as a class_reference.
    assert ("res://villain.gd", "class_reference") in referencing


# --- (b) editor-opened project (with .godot cache) resolves unchanged --------


@pytest.mark.e2e
def test_editor_opened_project_resolves_via_cache_unchanged(uncached_project):
    # With a populated .godot/ cache (tier 2), resolution is unchanged — the
    # static-scan fallback is unobservable for an editor-opened project.
    _import_project(uncached_project)
    assert (uncached_project / ".godot").exists()
    resource_path = uncached_project / "panda_cached.tres"

    created = _gda(
        uncached_project,
        "resource",
        "create",
        str(resource_path),
        "--type",
        "PandaStats",
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["type"] == "PandaStats"
    assert 'script_class="PandaStats"' in resource_path.read_text(encoding="utf-8")


# --- (c) duplicate class_name → ambiguous_class_name (all three sites) -------

DUP_A_GD = """\
class_name Dup
extends Resource
"""

DUP_B_GD = """\
class_name Dup
extends Resource
"""


@pytest.fixture
def ambiguous_project(tmp_path):
    """A never-opened project where two .gd both declare `class_name Dup`."""
    (tmp_path / "project.godot").write_text(
        CLASSNAME_RES_PROJECT_GODOT, encoding="utf-8"
    )
    (tmp_path / "dup_a.gd").write_text(DUP_A_GD, encoding="utf-8")
    (tmp_path / "dup_b.gd").write_text(DUP_B_GD, encoding="utf-8")
    return tmp_path


def _assert_ambiguous(err: dict) -> None:
    # The message names BOTH conflicting scripts, never a nondeterministic pick.
    assert "Dup" in err["message"]
    assert "res://dup_a.gd" in err["message"]
    assert "res://dup_b.gd" in err["message"]


@pytest.mark.e2e
def test_resource_create_ambiguous_class_name(ambiguous_project):
    created = _gda(
        ambiguous_project,
        "resource",
        "create",
        str(ambiguous_project / "x.tres"),
        "--type",
        "Dup",
        "--json",
    )
    _assert_ambiguous(_assert_operation_error(created, "ambiguous_class_name"))
    # Nothing was written for the rejected type.
    assert not (ambiguous_project / "x.tres").exists()


@pytest.mark.e2e
def test_node_add_ambiguous_class_name(ambiguous_project):
    scene_path = ambiguous_project / "main.tscn"
    created = _gda(
        ambiguous_project,
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = _gda(
        ambiguous_project, "node", "add", str(scene_path), "--type", "Dup", "--json"
    )

    _assert_ambiguous(_assert_operation_error(added, "ambiguous_class_name"))


@pytest.mark.e2e
def test_find_references_ambiguous_class_name(ambiguous_project):
    proc = _gda(ambiguous_project, "project", "find-references", "Dup", "--json")

    _assert_ambiguous(_assert_operation_error(proc, "ambiguous_class_name"))


# --- (d) unknown type: actionable message, no editor-cache implication -------


@pytest.mark.e2e
def test_resource_create_unknown_type_message_is_actionable(uncached_project):
    created = _gda(
        uncached_project,
        "resource",
        "create",
        str(uncached_project / "nope.tres"),
        "--type",
        "Nope",
        "--json",
    )

    err = _assert_operation_error(created, "invalid_resource_type")
    msg = err["message"]
    assert "Nope" in msg
    # The actionable cause: the class is not declared in a .gd (a misspelling).
    assert "no .gd script declares class_name Nope" in msg
    # No longer implies the missing editor cache as the root cause (ADR-0032).
    assert "cache" not in msg.lower()
    assert "editor" not in msg.lower()
    assert "global class list" not in msg.lower()


@pytest.mark.e2e
def test_node_add_unknown_type_message_is_actionable(uncached_project):
    scene_path = uncached_project / "main.tscn"
    created = _gda(
        uncached_project,
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = _gda(
        uncached_project, "node", "add", str(scene_path), "--type", "Nope", "--json"
    )

    err = _assert_operation_error(added, "invalid_node_type")
    msg = err["message"]
    assert "Nope" in msg
    assert "no .gd script declares class_name Nope" in msg
    assert "cache" not in msg.lower()
    assert "editor" not in msg.lower()
    assert "global class list" not in msg.lower()
