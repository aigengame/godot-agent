"""S1 (e2e): the scene create → get round-trip against the real Godot engine.

The tracer for headless file mutation (issue #18): ``gda scene create`` writes
a ``.tscn`` into a temp Godot project, ``gda scene get`` reads it back, and the
structured tree it reports must match what was requested — ``scene get`` IS the
structured-level verification of ``scene create``'s effect.
"""

import json
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
def test_scene_get_missing_file_yields_structured_error_end_to_end(godot_project):
    # The finer operation code (issue #18) survives the whole real stack: the
    # GDScript op reports path_not_found on stderr, the shared classifier
    # surfaces it as the stable code with the operation exit code.
    missing = godot_project / "missing.tscn"

    got = _gda("scene", "get", str(missing), "--json")

    assert got.returncode == 4
    err = json.loads(got.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert str(missing) in err["message"]


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
