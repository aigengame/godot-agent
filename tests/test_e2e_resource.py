"""S1 (e2e): the resource create → get round-trip against the real Godot engine.

The resource-group tracer (issue #112): ``gda resource create`` writes a .tres
resource of a given type, no-clobber; ``gda resource get`` loads it and reports
its properties as typed JSON — ``resource get`` IS the structured-level
verification of ``resource create``'s effect (create → get reports the
resource). Establishes the .tres load/save plumbing the rest of the group
reuses.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


def _gda(*args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.mark.e2e
def test_resource_create_then_get_round_trip(godot_project):
    # create writes a .tres of the requested type; get loads it back and reports
    # its type + properties. The round-trip proves the save: get reports the
    # resource create wrote.
    resource_path = godot_project / "palette.tres"

    created = _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["path"] == str(resource_path)
    assert data["type"] == "Gradient"
    assert resource_path.exists()
    # The written file is a real Godot .tres declaring the resource type.
    assert 'type="Gradient"' in resource_path.read_text(encoding="utf-8")

    got = _gda("resource", "get", str(resource_path), "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    # Round-trip: get reports the same type create wrote, plus typed properties.
    assert got_data["path"] == str(resource_path)
    assert got_data["type"] == "Gradient"
    by_name = {p["name"]: p for p in got_data["properties"]}
    # A Gradient declares these storage properties, each with its declared Godot
    # type — the same typed projection node get reports.
    assert by_name["interpolation_mode"]["type"] == "int"
    assert by_name["resource_name"]["type"] == "String"


@pytest.mark.e2e
def test_resource_create_into_nested_dir_reports_created_dirs(godot_project):
    # create makes missing parent directories before saving and reports them,
    # outermost to innermost (mirrors scene/script create).
    resource_path = godot_project / "art" / "palettes" / "sunset.tres"

    created = _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert resource_path.exists()
    assert data["created_dirs"] == [
        str(godot_project / "art"),
        str(godot_project / "art" / "palettes"),
    ]


@pytest.mark.e2e
def test_resource_create_no_clobber_yields_already_exists(godot_project):
    # No-clobber: a create whose target already exists is refused with
    # already_exists, leaving the existing file untouched.
    resource_path = godot_project / "palette.tres"
    first = _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")
    assert first.returncode == 0, first.stdout + first.stderr
    before = resource_path.read_text(encoding="utf-8")

    second = _gda(
        "resource", "create", str(resource_path), "--type", "Curve", "--json"
    )

    err = _assert_operation_error(second, "already_exists")
    assert str(resource_path) in err["message"]
    # The original file is untouched — the clobber never happened.
    assert resource_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_resource_create_unknown_type_yields_invalid_resource_type(godot_project):
    resource_path = godot_project / "palette.tres"

    created = _gda(
        "resource", "create", str(resource_path), "--type", "Bogus", "--json"
    )

    err = _assert_operation_error(created, "invalid_resource_type")
    assert "Bogus" in err["message"]
    # Nothing was written for the rejected type.
    assert not resource_path.exists()


@pytest.mark.e2e
def test_resource_create_non_resource_type_yields_invalid_resource_type(godot_project):
    # A real Godot class that is NOT a Resource (a Node) cannot be saved as a
    # .tres, so it is refused with the same code as an unknown type.
    resource_path = godot_project / "thing.tres"

    created = _gda(
        "resource", "create", str(resource_path), "--type", "Node2D", "--json"
    )

    err = _assert_operation_error(created, "invalid_resource_type")
    assert "Node2D" in err["message"]
    assert not resource_path.exists()


@pytest.mark.e2e
def test_resource_create_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"

    created = _gda(
        "resource", "create", str(bad_path), "--type", "Gradient", "--json"
    )

    err = _assert_operation_error(created, "invalid_path")
    assert ".tres" in err["message"]
    assert not bad_path.exists()


@pytest.mark.e2e
def test_resource_get_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    got = _gda("resource", "get", str(missing), "--json")

    err = _assert_operation_error(got, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_get_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"
    bad_path.write_text("not a resource", encoding="utf-8")

    got = _gda("resource", "get", str(bad_path), "--json")

    err = _assert_operation_error(got, "invalid_path")
    assert ".tres" in err["message"]
