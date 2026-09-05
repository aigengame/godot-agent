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
    the missing-class cause and does not cite the editor cache;
(e) the built-in-class tier probe is gated on ``ClassDB.class_exists()`` (#377),
    so a static-scan resolution no longer makes the engine log a spurious
    ``ERROR: Cannot get class`` to stderr (nor into the ``diagnostics`` of
    unrelated error envelopes), while built-in classes resolve exactly as before.
"""

import json

import pytest

from tests.support import Gda, assert_operation_error, import_project

from tests.conftest import project_godot

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

    created = Gda(uncached_project)(
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
    created = Gda(uncached_project)(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = Gda(uncached_project)(
        "node", "add", str(scene_path), "--type", "Hero", "--json"
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

    proc = Gda(uncached_project)("project", "find-references", "Hero", "--json")

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
    # An editor/import scan is what populates .godot/global_script_class_cache.cfg
    # (tier 2). Only this scenario runs it; (a), (c) and (d) deliberately do NOT,
    # so the resolver must fall through to the static scan (tier 3).
    import_project(uncached_project)
    assert (uncached_project / ".godot").exists()
    resource_path = uncached_project / "panda_cached.tres"

    created = Gda(uncached_project)(
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
    created = Gda(ambiguous_project)(
        "resource",
        "create",
        str(ambiguous_project / "x.tres"),
        "--type",
        "Dup",
        "--json",
    )
    _assert_ambiguous(assert_operation_error(created, "ambiguous_class_name"))
    # Nothing was written for the rejected type.
    assert not (ambiguous_project / "x.tres").exists()


@pytest.mark.e2e
def test_node_add_ambiguous_class_name(ambiguous_project):
    scene_path = ambiguous_project / "main.tscn"
    created = Gda(ambiguous_project)(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = Gda(ambiguous_project)(
        "node", "add", str(scene_path), "--type", "Dup", "--json"
    )

    _assert_ambiguous(assert_operation_error(added, "ambiguous_class_name"))


@pytest.mark.e2e
def test_find_references_ambiguous_class_name(ambiguous_project):
    proc = Gda(ambiguous_project)("project", "find-references", "Dup", "--json")

    _assert_ambiguous(assert_operation_error(proc, "ambiguous_class_name"))


# --- (d) unknown type: actionable message, no editor-cache implication -------


@pytest.mark.e2e
def test_resource_create_unknown_type_message_is_actionable(uncached_project):
    err = Gda(uncached_project).error(
        "resource",
        "create",
        str(uncached_project / "nope.tres"),
        "--type",
        "Nope",
        "--json",
        code="invalid_resource_type",
    )
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
    created = Gda(uncached_project)(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    err = Gda(uncached_project).error(
        "node",
        "add",
        str(scene_path),
        "--type",
        "Nope",
        "--json",
        code="invalid_node_type",
    )
    msg = err["message"]
    assert "Nope" in msg
    assert "no .gd script declares class_name Nope" in msg
    assert "cache" not in msg.lower()
    assert "editor" not in msg.lower()
    assert "global class list" not in msg.lower()


# --- (e) no spurious engine ERROR on the static-scan fallback path (#377) -----


@pytest.mark.e2e
def test_resource_create_project_class_emits_no_engine_error(uncached_project):
    # Before #377 the built-in-class tier probed ClassDB.can_instantiate() on a
    # project-local class_name and the engine logged "ERROR: Cannot get class
    # 'PandaStats'." to stderr on a SUCCESSFUL op. class_exists() now gates the
    # probe, so the static-scan resolution is silent.
    assert not (uncached_project / ".godot").exists()

    created = Gda(uncached_project)(
        "resource",
        "create",
        str(uncached_project / "quiet.tres"),
        "--type",
        "PandaStats",
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert "ERROR:" not in created.stderr, created.stderr


@pytest.mark.e2e
def test_node_add_project_class_emits_no_engine_error(uncached_project):
    assert not (uncached_project / ".godot").exists()
    scene_path = uncached_project / "main.tscn"
    created = Gda(uncached_project)(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    added = Gda(uncached_project)(
        "node", "add", str(scene_path), "--type", "Hero", "--json"
    )

    assert added.returncode == 0, added.stdout + added.stderr
    assert "ERROR:" not in added.stderr, added.stderr


@pytest.mark.e2e
def test_ambiguous_class_name_carries_no_cannot_get_class(ambiguous_project):
    # The spurious engine line was also captured verbatim into the diagnostics
    # of UNRELATED error envelopes on the fallback path — an ambiguous_class_name
    # failure carried "Cannot get class 'Dup'", pointing away from the real
    # cause. Neither the envelope's diagnostics nor stderr embeds it now.
    created = Gda(ambiguous_project)(
        "resource",
        "create",
        str(ambiguous_project / "x.tres"),
        "--type",
        "Dup",
        "--json",
    )

    err = assert_operation_error(created, "ambiguous_class_name")
    assert "Cannot get class" not in err.get("diagnostics", "")
    assert "Cannot get class" not in created.stderr


@pytest.mark.e2e
def test_builtin_classes_resolve_unchanged_and_silent(uncached_project):
    # Regression for the class_exists() guard: a built-in Node (Sprite2D) and a
    # built-in Resource (Gradient) still resolve on the ClassDB tier exactly as
    # before — never reaching the class_name resolver — and stay silent.
    scene_path = uncached_project / "builtin.tscn"
    created = Gda(uncached_project)(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--json",
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert "ERROR:" not in created.stderr, created.stderr

    added = Gda(uncached_project)(
        "node", "add", str(scene_path), "--type", "Sprite2D", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout)["type"] == "Sprite2D"
    assert "ERROR:" not in added.stderr, added.stderr

    resource_path = uncached_project / "builtin.tres"
    res = Gda(uncached_project)(
        "resource",
        "create",
        str(resource_path),
        "--type",
        "Gradient",
        "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert json.loads(res.stdout)["type"] == "Gradient"
    assert "ERROR:" not in res.stderr, res.stderr
