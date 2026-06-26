"""S1 (e2e): the scene create → get round-trip against the real Godot engine.

The tracer for headless file mutation (issue #18): ``gda scene create`` writes
a ``.tscn`` into a temp Godot project, ``gda scene get`` reads it back, and the
structured tree it reports must match what was requested — ``scene get`` IS the
structured-level verification of ``scene create``'s effect.
"""

import json
import os
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


def _gda(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


@pytest.mark.e2e
def test_res_path_round_trip_against_the_project_fixture(godot_project):
    # The project context (issue #32): with --project pointing at the temp
    # project fixture, a res:// path resolves against it — proving the fixture
    # is actually handed to the engine (it previously never reached it). The
    # created scene lands inside the project and reads back through res://.
    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(godot_project)],
            capture_output=True,
            text=True,
        )

    created = gda(
        "scene", "create", "res://hero.tscn", "--root-type", "Node2D", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    # res:// resolved against the fixture project, not gda's cwd.
    assert (godot_project / "hero.tscn").exists()

    got = gda("scene", "get", "res://hero.tscn", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["type"] == "Node2D"


@pytest.mark.e2e
def test_scene_create_then_get_round_trip(godot_project):
    scene_path = godot_project / "main.tscn"

    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["root_type"] == "Node2D"
    # The .tscn landed on disk inside the temp project.
    assert scene_path.exists()

    got = _gda("scene", "get", str(scene_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    tree = json.loads(got.stdout)
    # Round-trip: the engine loaded the created scene and reports the
    # requested root type back — the scene file is loadable, not just present.
    assert tree["root"]["type"] == "Node2D"
    assert tree["root"]["name"] == "main"
    assert tree["root"]["children"] == []


@pytest.mark.e2e
def test_scene_path_containing_end_sentinel_round_trips(godot_project):
    # issue #34: the result payload echoes the target path verbatim. A path
    # containing the literal end sentinel must round-trip, not be truncated into
    # a parse error (exit 5). root_name is explicit because the sentinel's ':'
    # is not a legal node-name char, so it cannot be derived from this filename.
    scene_path = godot_project / "weird<<<GDA:END>>>name.tscn"

    created = _gda(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--root-name",
        "Main",
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["path"] == str(scene_path)

    got = _gda("scene", "get", str(scene_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    tree = json.loads(got.stdout)
    assert tree["path"] == str(scene_path)
    assert tree["root"]["name"] == "Main"


@pytest.mark.e2e
def test_scene_create_creates_missing_parent_directories(godot_project):
    scene_path = godot_project / "levels" / "demo" / "main.tscn"

    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["created_dirs"] == [
        str(godot_project / "levels"),
        str(godot_project / "levels" / "demo"),
    ]
    assert scene_path.exists()

    got = _gda("scene", "get", str(scene_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["name"] == "main"


@pytest.mark.e2e
def test_scene_create_creates_relative_parent_directories_against_project(
    godot_project,
):
    created = subprocess.run(
        [
            *GDA_CMD,
            "scene",
            "create",
            "demo/main.tscn",
            "--root-type",
            "Node2D",
            "--project",
            str(godot_project),
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == "demo/main.tscn"
    assert data["created_dirs"] == ["demo"]
    assert (godot_project / "demo" / "main.tscn").exists()


@pytest.mark.e2e
def test_scene_create_existing_path_yields_already_exists_without_overwriting(
    godot_project,
):
    scene_path = godot_project / "main.tscn"
    original = "not a scene\n"
    scene_path.write_text(original, encoding="utf-8")

    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )

    assert created.returncode == 4
    err = json.loads(created.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"
    assert str(scene_path) in err["message"]
    assert scene_path.read_text(encoding="utf-8") == original


@pytest.mark.e2e
def test_scene_create_empty_root_name_yields_structured_error(godot_project):
    scene_path = godot_project / ".tscn"

    created = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )

    assert created.returncode == 4
    err = json.loads(created.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_root_name"
    assert "root_name" in err["message"]
    assert not scene_path.exists()


@pytest.mark.e2e
def test_scene_create_rejects_root_name_godot_would_rewrite(godot_project):
    scene_path = godot_project / "bad-name.tscn"

    created = _gda(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--root-name",
        "Bad%Name",
        "--json",
    )

    assert created.returncode == 4
    err = json.loads(created.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_root_name"
    assert "root_name" in err["message"]
    assert not scene_path.exists()


@pytest.mark.e2e
def test_scene_create_rejects_dotted_default_root_name_but_allows_override(
    godot_project,
):
    scene_path = godot_project / "level.v2.tscn"

    rejected = _gda(
        "scene", "create", str(scene_path), "--root-type", "Node2D", "--json"
    )

    assert rejected.returncode == 4
    err = json.loads(rejected.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_root_name"
    assert not scene_path.exists()

    created = _gda(
        "scene",
        "create",
        str(scene_path),
        "--root-type",
        "Node2D",
        "--root-name",
        "LevelV2",
        "--json",
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["root_name"] == "LevelV2"

    got = _gda("scene", "get", str(scene_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["name"] == "LevelV2"


# A hand-written nested scene: Root → Hero → Hitbox, distinct node types.
NESTED_TSCN = """\
[gd_scene format=3]

[node name="Root" type="Node2D"]

[node name="Hero" type="Sprite2D" parent="."]

[node name="Hitbox" type="Area2D" parent="Hero"]
"""


@pytest.mark.e2e
def test_scene_get_reports_nested_tree(godot_project):
    # Guards the SceneState parent/child reconstruction (issue #30): a scene
    # read without instantiation must still report nested structure correctly.
    scene_path = godot_project / "nested.tscn"
    scene_path.write_text(NESTED_TSCN, encoding="utf-8")

    got = _gda("scene", "get", str(scene_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    root = json.loads(got.stdout)["root"]
    assert (root["name"], root["type"]) == ("Root", "Node2D")
    hero = root["children"][0]
    assert (hero["name"], hero["type"]) == ("Hero", "Sprite2D")
    hitbox = hero["children"][0]
    assert (hitbox["name"], hitbox["type"]) == ("Hitbox", "Area2D")


@pytest.mark.e2e
def test_scene_get_missing_file_yields_structured_error_end_to_end(godot_project):
    # The finer operation code (issue #18) survives the whole real stack: the
    # GDScript op reports path_not_found through the ADR-0002 error envelope,
    # and the shared classifier surfaces it as the stable code with the
    # operation exit code.
    missing = godot_project / "missing.tscn"

    got = _gda("scene", "get", str(missing), "--json")

    assert got.returncode == 4
    err = json.loads(got.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_scene_create_unwritable_directory_yields_structured_save_failed(godot_project):
    # The residual save-failure contract (issue #35): when the destination
    # cannot be written, the engine's ERR_CANT_OPEN surfaces as the stable
    # save_failed code. An existing-but-unwritable directory triggers it, so
    # this stays valid once #35 auto-creates missing parent directories.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("directory write permissions do not bind as root")
    locked = godot_project / "locked"
    locked.mkdir()
    target = locked / "main.tscn"
    locked.chmod(0o500)
    try:
        created = _gda(
            "scene", "create", str(target), "--root-type", "Node2D", "--json"
        )
    finally:
        locked.chmod(0o700)

    assert created.returncode == 4
    err = json.loads(created.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "save_failed"
    # The message names the destination the caller must fix.
    assert str(target) in err["message"]
    assert str(locked) in err["message"]
    assert "write probe" in err["message"]
    assert not target.exists()


@pytest.mark.e2e
def test_scene_create_unknown_root_type_yields_structured_error_end_to_end(
    godot_project,
):
    target = godot_project / "bogus.tscn"

    created = _gda("scene", "create", str(target), "--root-type", "NotAClass", "--json")

    assert created.returncode == 4
    err = json.loads(created.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_root_type"
    assert not target.exists()


def _gda_project(project) -> "callable":
    """A ``_gda`` bound to ``--project`` for res:// enumeration/resolution."""

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


@pytest.mark.e2e
def test_scene_list_enumerates_created_scenes(godot_project):
    # scene list (issue #54) enumerates the project's .tscn scenes by walking
    # res://: two scenes created at different depths both appear, each with its
    # res:// path and the root name/type read from stored state. The listing IS
    # the structured-level verification of what scene create wrote.
    gda = _gda_project(godot_project)

    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "scene", "create", "res://ui/menu.tscn", "--root-type", "Control", "--json"
        ).returncode
        == 0
    )

    listed = gda("scene", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    scenes = json.loads(listed.stdout)["scenes"]
    by_path = {s["path"]: s for s in scenes}
    assert by_path["res://main.tscn"]["root_type"] == "Node2D"
    assert by_path["res://main.tscn"]["root_name"] == "main"
    assert by_path["res://ui/menu.tscn"]["root_type"] == "Control"


@pytest.mark.e2e
def test_scene_list_enumerates_dot_prefixed_scenes_but_skips_godot_cache(godot_project):
    # scene list promises to enumerate every .tscn in the project, so a
    # dot-prefixed scene (a hidden file, or one under a hidden directory) must
    # appear — only the engine's res://.godot import cache is skipped, not every
    # dot-prefixed entry. The empty-project test already proves res://.godot does
    # not leak; this proves the skip is scoped to res://.godot, not "anything
    # starting with a dot".
    gda = _gda_project(godot_project)

    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    assert (
        gda(
            "scene",
            "create",
            "res://.hidden.tscn",
            "--root-type",
            "Node2D",
            "--root-name",
            "Hidden",
            "--json",
        ).returncode
        == 0
    )
    assert (
        gda(
            "scene",
            "create",
            "res://.config/deep.tscn",
            "--root-type",
            "Node2D",
            "--json",
        ).returncode
        == 0
    )

    listed = gda("scene", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    paths = {s["path"] for s in json.loads(listed.stdout)["scenes"]}
    assert "res://main.tscn" in paths
    assert "res://.hidden.tscn" in paths
    assert "res://.config/deep.tscn" in paths
    # The engine import cache is still excluded — no res://.godot entry leaks in.
    assert not any(p.startswith("res://.godot") for p in paths)


@pytest.mark.e2e
def test_scene_list_on_empty_project_is_an_empty_listing(godot_project):
    # A project with no scenes is a valid, empty listing — not an error (the
    # res://.godot import cache must not leak in as a phantom scene).
    gda = _gda_project(godot_project)

    listed = gda("scene", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["scenes"] == []


@pytest.mark.e2e
def test_scene_list_without_project_yields_project_not_found(tmp_path):
    # scene list cannot enumerate res:// projectless: run from a non-project
    # directory with no --project, it must refuse with the structured
    # project_not_found code rather than return a misleading empty listing.
    listed = subprocess.run(
        [*GDA_CMD, "scene", "list", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert listed.returncode == 4, listed.stdout + listed.stderr
    err = json.loads(listed.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "project_not_found"
    assert "--project" in err["message"]


@pytest.mark.e2e
def test_scene_delete_removes_a_scene_and_names_what_was_removed(godot_project):
    # scene delete (issue #54) removes a scene file and names the removed root.
    # The round-trip verifier: scene list before shows the scene, delete reports
    # the removed root's name/type, and scene list after no longer shows it.
    gda = _gda_project(godot_project)
    assert (
        gda(
            "scene", "create", "res://main.tscn", "--root-type", "Node2D", "--json"
        ).returncode
        == 0
    )
    scene_path = godot_project / "main.tscn"
    assert scene_path.exists()

    deleted = gda("scene", "delete", "res://main.tscn", "--json")

    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    data = json.loads(deleted.stdout)
    assert data["path"] == "res://main.tscn"
    assert data["root_name"] == "main"
    assert data["root_type"] == "Node2D"
    # The file is gone from disk, not just from the report.
    assert not scene_path.exists()
    assert json.loads(gda("scene", "list", "--json").stdout)["scenes"] == []


@pytest.mark.e2e
def test_scene_delete_missing_file_yields_path_not_found(godot_project):
    missing = godot_project / "missing.tscn"

    deleted = _gda("scene", "delete", str(missing), "--json")

    assert deleted.returncode == 4
    err = json.loads(deleted.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_scene_delete_refuses_non_scene_file_and_leaves_it_on_disk(godot_project):
    # The delete safety boundary (issue #54): delete only removes a file that
    # loads as a PackedScene, so a stray non-scene file is refused with
    # not_a_scene and left untouched — delete never erases arbitrary files.
    notes = godot_project / "notes.txt"
    notes.write_text("not a scene\n", encoding="utf-8")

    deleted = _gda("scene", "delete", str(notes), "--json")

    assert deleted.returncode == 4
    err = json.loads(deleted.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "not_a_scene"
    # The non-scene file survives the refusal.
    assert notes.read_text(encoding="utf-8") == "not a scene\n"
