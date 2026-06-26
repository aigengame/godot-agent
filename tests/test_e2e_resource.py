"""S1 (e2e): the resource create → get round-trip and resource uid resolution against the real Godot engine.

The resource-group tracer (issue #112): ``gda resource create`` writes a .tres
resource of a given type, no-clobber; ``gda resource get`` loads it and reports
its properties as typed JSON — ``resource get`` IS the structured-level
verification of ``resource create``'s effect (create → get reports the
resource). Establishes the .tres load/save plumbing the rest of the group
reuses.

The resource-uid tracer (issue #113): ``gda resource uid`` resolves a Godot
resource UID to/from its resource path in BOTH directions against the engine's
read-only UID cache (``res://.godot/uid_cache.bin``).

The cache is populated by a project import scan, so each uid test scaffolds the
relevant files and runs a one-shot ``godot --headless --import`` to write the
cache before querying it — that import is the realistic precondition for any UID
to resolve at all. A ``.gd`` script is auto-assigned a UID on import (a ``.uid``
sidecar plus a cache entry), which is what makes both resolution directions
resolve; a ``.tres`` resource imported without a sidecar exists but carries no
cached UID, which is the realistic ``no_uid_assigned`` case. Both directions,
plus the unknown-UID / invalid-UID / path-not-found / no-UID-assigned failure
modes, are exercised end to end.
"""

import json
import os
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# A plain custom Resource .tres. On import (without a .uid sidecar) it exists as
# a resource but is NOT assigned a UID in the non-editor reverse cache, so it is
# the realistic no_uid_assigned case.
DATA_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""


def _gda(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT)], capture_output=True, text=True
    )


def _import_project(project) -> None:
    """Run a one-shot headless import so the project's UID cache is written."""
    subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _gda_project(project) -> "callable":
    """A ``gda`` bound to ``--godot`` and ``--project`` for res:// / UID resolution."""

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _gda_env(extra_env: dict, *args: str) -> subprocess.CompletedProcess:
    """``_gda`` with extra env vars in the child's environment (issue #226 seam)."""
    return subprocess.run(
        [*GDA_CMD, *args, "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        env={**os.environ, **extra_env},
    )


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.fixture
def imported_project(godot_project):
    """A project fixture with a script (UID-cached) and a .tres (no cached UID)."""
    (godot_project / "hero.gd").write_text("extends Node\n", encoding="utf-8")
    (godot_project / "data.tres").write_text(DATA_TRES, encoding="utf-8")
    _import_project(godot_project)
    return godot_project


@pytest.mark.e2e
def test_resource_create_then_get_round_trip(godot_project):
    # create writes a .tres of the requested type; get loads it back and reports
    # its type + properties. The round-trip proves the save: get reports the
    # resource create wrote.
    resource_path = godot_project / "palette.tres"

    created = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )

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

    created = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )

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
    first = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = resource_path.read_text(encoding="utf-8")

    second = _gda("resource", "create", str(resource_path), "--type", "Curve", "--json")

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

    created = _gda("resource", "create", str(bad_path), "--type", "Gradient", "--json")

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


# --- resource set / delete: round out .tres CRUD (issue #120) ------------


@pytest.mark.e2e
def test_resource_set_coerces_persists_and_round_trips_via_get(godot_project):
    # create → set → get: set coerces the CLI string to the property's declared
    # type, saves the .tres, and get reports the coerced value — resource get IS
    # the structured-level verification that set persisted.
    resource_path = godot_project / "palette.tres"
    created = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    was_set = _gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "interpolation_mode",
        "--value",
        "1",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_data = json.loads(was_set.stdout)
    # The result reports the coerced value (the declared int, not the string).
    assert set_data["path"] == str(resource_path)
    assert set_data["property"] == "interpolation_mode"
    assert set_data["type"] == "int"
    assert set_data["value"] == 1

    got = _gda("resource", "get", str(resource_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    # Round-trip: get reports the value set persisted to the .tres.
    assert by_name["interpolation_mode"]["value"] == 1


@pytest.mark.e2e
def test_resource_set_string_property_round_trips(godot_project):
    # A String property coerces trivially and round-trips through get.
    resource_path = godot_project / "palette.tres"
    _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    was_set = _gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "resource_name",
        "--value",
        "Sunset",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    assert json.loads(was_set.stdout)["type"] == "String"

    got = _gda("resource", "get", str(resource_path), "--json")
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    assert by_name["resource_name"]["value"] == "Sunset"


@pytest.mark.e2e
def test_resource_set_with_external_edit_in_window_yields_file_changed_externally(
    godot_project,
):
    # Staleness guard for the ResourceSaver path (issue #226): resource set loads the
    # .tres, coerces and sets a property, then re-saves; if the file changes on disk in
    # that window a blind save would clobber the external edit. The production-inert seam
    # (GDA_TEST_PERTURB_BEFORE_SAVE) simulates that edit, and the guard refuses.
    resource_path = godot_project / "palette.tres"
    created = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr

    was_set = _gda_env(
        {"GDA_TEST_PERTURB_BEFORE_SAVE": "1"},
        "resource",
        "set",
        str(resource_path),
        "--property",
        "resource_name",
        "--value",
        "Sunset",
        "--json",
    )

    err = _assert_operation_error(was_set, "file_changed_externally")
    assert str(resource_path) in err["message"]

    # The set did NOT land: resource_name is still empty (the default), not "Sunset".
    got = _gda("resource", "get", str(resource_path), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    by_name = {p["name"]: p for p in json.loads(got.stdout)["properties"]}
    assert by_name["resource_name"]["value"] != "Sunset"
    assert not list(godot_project.rglob(".gda-*"))


@pytest.mark.e2e
def test_resource_set_unknown_property_is_a_clean_error(godot_project):
    # set edits an existing property; an unknown property is unknown_property,
    # never a silent create — the agent fixes the property name.
    resource_path = godot_project / "palette.tres"
    _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")

    was_set = _gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "bogus_property",
        "--value",
        "1",
        "--json",
    )

    err = _assert_operation_error(was_set, "unknown_property")
    assert "bogus_property" in err["message"]


@pytest.mark.e2e
def test_resource_set_uncoercible_value_is_a_clean_error(godot_project):
    # An int property cannot take a non-numeric string — uncoercible_value (#55),
    # the .tres left untouched.
    resource_path = godot_project / "palette.tres"
    _gda("resource", "create", str(resource_path), "--type", "Gradient", "--json")
    before = resource_path.read_text(encoding="utf-8")

    was_set = _gda(
        "resource",
        "set",
        str(resource_path),
        "--property",
        "interpolation_mode",
        "--value",
        "not-a-number",
        "--json",
    )

    err = _assert_operation_error(was_set, "uncoercible_value")
    assert "not-a-number" in err["message"]
    # The file is untouched — the rejected coercion never wrote.
    assert resource_path.read_text(encoding="utf-8") == before


@pytest.mark.e2e
def test_resource_set_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    was_set = _gda(
        "resource", "set", str(missing), "--property", "x", "--value", "1", "--json"
    )

    err = _assert_operation_error(was_set, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_delete_removes_file_and_round_trips_against_get(godot_project):
    # create → delete → get: delete removes the .tres and reports what was removed
    # (path + type); a subsequent get is now path_not_found, closing the lifecycle.
    resource_path = godot_project / "palette.tres"
    created = _gda(
        "resource", "create", str(resource_path), "--type", "Gradient", "--json"
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert resource_path.exists()

    deleted = _gda("resource", "delete", str(resource_path), "--json")

    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    del_data = json.loads(deleted.stdout)
    assert del_data["path"] == str(resource_path)
    assert del_data["type"] == "Gradient"
    # The file is gone from disk.
    assert not resource_path.exists()

    # Round-trip: get now reports path_not_found — the lifecycle's now-not-found.
    got = _gda("resource", "get", str(resource_path), "--json")
    _assert_operation_error(got, "path_not_found")


@pytest.mark.e2e
def test_resource_delete_missing_yields_path_not_found(godot_project):
    missing = godot_project / "nope.tres"

    deleted = _gda("resource", "delete", str(missing), "--json")

    err = _assert_operation_error(deleted, "path_not_found")
    assert str(missing) in err["message"]


@pytest.mark.e2e
def test_resource_delete_non_tres_path_yields_invalid_path(godot_project):
    bad_path = godot_project / "palette.txt"
    bad_path.write_text("not a resource", encoding="utf-8")

    deleted = _gda("resource", "delete", str(bad_path), "--json")

    err = _assert_operation_error(deleted, "invalid_path")
    assert ".tres" in err["message"]
    # The non-.tres file is untouched — the rejected addressing never deleted.
    assert bad_path.exists()


@pytest.mark.e2e
def test_resource_uid_resolves_both_directions_round_trip(imported_project):
    # path -> uid -> path: the script's import-assigned UID resolves back to the
    # same path. This is the bidirectional contract: query a path, get its UID;
    # query that UID, get the path back — proving both directions read one
    # consistent cache.
    gda = _gda_project(imported_project)

    path_to_uid = gda("resource", "uid", "res://hero.gd", "--json")
    assert path_to_uid.returncode == 0, path_to_uid.stdout + path_to_uid.stderr
    forward = json.loads(path_to_uid.stdout)
    assert forward["queried"] == "path"
    assert forward["path"] == "res://hero.gd"
    assert forward["uid"].startswith("uid://")

    uid = forward["uid"]
    uid_to_path = gda("resource", "uid", uid, "--json")
    assert uid_to_path.returncode == 0, uid_to_path.stdout + uid_to_path.stderr
    back = json.loads(uid_to_path.stdout)
    assert back["queried"] == "uid"
    assert back["uid"] == uid
    # The round-trip closes: the UID resolves back to the original path.
    assert back["path"] == "res://hero.gd"


@pytest.mark.e2e
def test_resource_uid_human_output_renders_uid_arrow_path(imported_project):
    # Without --json, a resolved mapping renders as `<uid> -> <path>`.
    gda = _gda_project(imported_project)

    proc = gda("resource", "uid", "res://hero.gd")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().endswith("-> res://hero.gd")
    assert proc.stdout.strip().startswith("uid://")


@pytest.mark.e2e
def test_resource_uid_unknown_uid_is_unknown_uid(imported_project):
    # A syntactically valid uid:// not in the project's cache is unknown_uid.
    gda = _gda_project(imported_project)

    proc = gda("resource", "uid", "uid://b00000000000b", "--json")

    _assert_operation_error(proc, "unknown_uid")


@pytest.mark.e2e
def test_resource_uid_invalid_uid_is_invalid_uid(imported_project):
    # A uid:// whose body holds illegal characters fails text_to_id (INVALID_ID),
    # reported as invalid_uid — distinct from a well-formed-but-unknown UID.
    gda = _gda_project(imported_project)

    proc = gda("resource", "uid", "uid://<invalid>", "--json")

    _assert_operation_error(proc, "invalid_uid")


@pytest.mark.e2e
def test_resource_uid_path_not_found_is_path_not_found(imported_project):
    # A res:// path naming no resource is path_not_found.
    gda = _gda_project(imported_project)

    proc = gda("resource", "uid", "res://missing.tres", "--json")

    _assert_operation_error(proc, "path_not_found")


@pytest.mark.e2e
def test_resource_uid_path_without_uid_is_no_uid_assigned(imported_project):
    # A resource that exists but has no UID in the non-editor reverse cache is
    # no_uid_assigned — distinct from path_not_found (the file is there) and from
    # a UID-direction failure (the query was a path).
    gda = _gda_project(imported_project)

    proc = gda("resource", "uid", "res://data.tres", "--json")

    _assert_operation_error(proc, "no_uid_assigned")


@pytest.mark.e2e
def test_resource_uid_projectless_run_is_project_not_found():
    # Resolution queries the project's UID cache, so a projectless run is refused
    # with project_not_found rather than a misleading "no UID" answer.
    proc = subprocess.run(
        [
            *GDA_CMD,
            "resource",
            "uid",
            "uid://b00000000000b",
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    _assert_operation_error(proc, "project_not_found")
