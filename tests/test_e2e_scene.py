"""S1 (e2e): the scene create → get round-trip against the real Godot engine.

The tracer for headless file mutation (issue #18): ``gda scene create`` writes
a ``.tscn`` into a temp Godot project, ``gda scene get`` reads it back, and the
structured tree it reports must match what was requested — ``scene get`` IS the
structured-level verification of ``scene create``'s effect.
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()

requires_godot = pytest.mark.skipif(
    not GODOT.exists(), reason=f"real Godot binary not found at {GODOT}"
)


def _gda(*args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


@pytest.mark.e2e
@requires_godot
def test_res_path_round_trip_against_the_project_fixture(godot_project):
    # The project context (issue #32): with --project pointing at the temp
    # project fixture, a res:// path resolves against it — proving the fixture
    # is actually handed to the engine (it previously never reached it). The
    # created scene lands inside the project and reads back through res://.
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [gda_bin, *args, "--godot", str(GODOT), "--project", str(godot_project)],
            capture_output=True,
            text=True,
        )

    created = gda("scene", "create", "res://hero.tscn", "--root-type", "Node2D", "--json")
    assert created.returncode == 0, created.stdout + created.stderr
    # res:// resolved against the fixture project, not gda's cwd.
    assert (godot_project / "hero.tscn").exists()

    got = gda("scene", "get", "res://hero.tscn", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["type"] == "Node2D"


@pytest.mark.e2e
@requires_godot
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
@requires_godot
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
@requires_godot
def test_scene_create_creates_relative_parent_directories_against_project(
    godot_project,
):
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    created = subprocess.run(
        [
            gda_bin,
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
@requires_godot
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
        created = _gda("scene", "create", str(target), "--root-type", "Node2D", "--json")
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
@requires_godot
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
