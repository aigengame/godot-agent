"""S1 (e2e): the project info / get / set round-trip against the real Godot engine.

The project-group tracer (issue #111): ``gda project info`` reports the resolved
project's metadata from ``ProjectSettings``; ``gda project get`` reads one
setting; ``gda project set`` coerces a CLI value to the setting's declared type,
saves ``project.godot``, and is verified by ``project get`` reading the new value
back — ``project get`` IS the structured-level verification of ``project set``.

Every project op runs against an explicit project context (--project) and so, like
any --project op, runs the project's autoloads at engine startup (#61, ADR-0009);
the e2e fixture has none, so that surface is exercised as a no-op here.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--project", str(project), "--godot", str(GODOT)],
        capture_output=True,
        text=True,
    )


@pytest.mark.e2e
def test_project_info_reports_metadata(godot_project):
    info = _gda(godot_project, "project", "info", "--json")

    assert info.returncode == 0, info.stdout + info.stderr
    data = json.loads(info.stdout)
    # The fixture's project.godot sets config/name to this.
    assert data["name"] == "gda-e2e-fixture"
    # A fresh project has no explicit main scene.
    assert data["main_scene"] == ""
    # Viewport falls back to the engine's built-in defaults (positive integers).
    assert isinstance(data["viewport_width"], int) and data["viewport_width"] > 0
    assert isinstance(data["viewport_height"], int) and data["viewport_height"] > 0
    # The engine version is the same shape (and minimum, ADR-0003) gda info reports.
    version = data["engine_version"]
    assert (version["major"], version["minor"]) >= (4, 4)


@pytest.mark.e2e
def test_project_get_reads_a_setting_as_typed_json(godot_project):
    got = _gda(godot_project, "project", "get", "application/config/name", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["setting"] == "application/config/name"
    assert data["type"] == "String"
    assert data["value"] == "gda-e2e-fixture"


@pytest.mark.e2e
def test_project_set_coerces_persists_and_round_trips_via_get(godot_project):
    # The CLI value is a STRING; the operation coerces it to the setting's declared
    # int type, saves project.godot, and the result reports the coerced int (#55
    # coercion reused). A second get reads it back from the saved file.
    was_set = _gda(
        godot_project,
        "project",
        "set",
        "display/window/size/viewport_width",
        "--value",
        "1920",
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_data = json.loads(was_set.stdout)
    assert set_data["setting"] == "display/window/size/viewport_width"
    assert set_data["type"] == "int"
    # Coerced to an int, not left as the string "1920".
    assert set_data["value"] == 1920

    # Round-trip: a fresh process reads the persisted value back from project.godot.
    got = _gda(
        godot_project, "project", "get", "display/window/size/viewport_width", "--json"
    )
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == 1920

    # And project info reflects the saved viewport width.
    info = _gda(godot_project, "project", "info", "--json")
    assert info.returncode == 0, info.stdout + info.stderr
    assert json.loads(info.stdout)["viewport_width"] == 1920


@pytest.mark.e2e
def test_project_set_string_setting_round_trips(godot_project):
    # A String-typed setting takes the CLI value verbatim and round-trips.
    was_set = _gda(
        godot_project,
        "project",
        "set",
        "application/config/name",
        "--value",
        "Renamed Game",
        "--json",
    )
    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    assert json.loads(was_set.stdout)["value"] == "Renamed Game"

    got = _gda(godot_project, "project", "get", "application/config/name", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == "Renamed Game"


@pytest.mark.e2e
def test_project_get_unknown_setting_is_a_clean_error(godot_project):
    got = _gda(godot_project, "project", "get", "application/bogus/key", "--json")

    assert got.returncode == 4
    err = json.loads(got.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "application/bogus/key" in err["message"]


@pytest.mark.e2e
def test_project_set_uncoercible_value_is_a_clean_error(godot_project):
    # An int setting cannot take a non-numeric string — uncoercible_value (#55),
    # exit 4, project.godot left untouched.
    bad = _gda(
        godot_project,
        "project",
        "set",
        "display/window/size/viewport_width",
        "--value",
        "not-a-number",
        "--json",
    )

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "uncoercible_value"

    # The file was untouched: a subsequent get still returns the original value.
    got = _gda(
        godot_project, "project", "get", "display/window/size/viewport_width", "--json"
    )
    assert got.returncode == 0, got.stdout + got.stderr


@pytest.mark.e2e
def test_project_add_autoload_registers_persists_and_round_trips(godot_project):
    # A real script to autoload must exist in the project (path_not_found otherwise).
    (godot_project / "global.gd").write_text(
        "extends Node\n", encoding="utf-8"
    )

    added = _gda(
        godot_project,
        "project",
        "add-autoload",
        "Global",
        "res://global.gd",
        "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    add_data = json.loads(added.stdout)
    assert add_data["name"] == "Global"
    # Persisted in the enabled-singleton form, with the leading * prefix.
    assert add_data["path"] == "*res://global.gd"

    # Round-trip: a fresh process reads the autoload back from project.godot via get.
    got = _gda(godot_project, "project", "get", "autoload/Global", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["setting"] == "autoload/Global"
    assert got_data["value"] == "*res://global.gd"


@pytest.mark.e2e
def test_project_remove_autoload_unregisters_and_round_trips(godot_project):
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")
    added = _gda(
        godot_project, "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr

    removed = _gda(godot_project, "project", "remove-autoload", "Global", "--json")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout) == {"name": "Global"}

    # Round-trip: the autoload is gone from project.godot — a fresh get reports it
    # as an unknown setting, exit 4.
    got = _gda(godot_project, "project", "get", "autoload/Global", "--json")
    assert got.returncode == 4, got.stdout + got.stderr
    assert json.loads(got.stdout)["error"]["code"] == "unknown_setting"


@pytest.mark.e2e
def test_project_add_autoload_duplicate_name_is_a_clean_error(godot_project):
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")
    first = _gda(
        godot_project, "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr

    dup = _gda(
        godot_project, "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert dup.returncode == 4
    err = json.loads(dup.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"

    # The original registration is untouched: a get still reads it back.
    got = _gda(godot_project, "project", "get", "autoload/Global", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == "*res://global.gd"


@pytest.mark.e2e
def test_project_add_autoload_missing_target_is_a_clean_error(godot_project):
    # The target script/scene does not exist — path_not_found, exit 4, nothing saved.
    bad = _gda(
        godot_project,
        "project",
        "add-autoload",
        "Global",
        "res://nope.gd",
        "--json",
    )

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"

    # Nothing was registered: a get reports the autoload as unknown.
    got = _gda(godot_project, "project", "get", "autoload/Global", "--json")
    assert got.returncode == 4
    assert json.loads(got.stdout)["error"]["code"] == "unknown_setting"


@pytest.mark.e2e
def test_project_remove_autoload_unknown_name_is_a_clean_error(godot_project):
    bad = _gda(godot_project, "project", "remove-autoload", "Nonexistent", "--json")

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "Nonexistent" in err["message"]


@pytest.mark.e2e
def test_project_info_without_project_is_a_clean_error():
    # Projectless: ProjectSettings would report only the engine's bare defaults,
    # not the agent's project, so it is refused with project_not_found.
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    proc = subprocess.run(
        [gda_bin, "project", "info", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd="/tmp",
    )

    assert proc.returncode == 4
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"
