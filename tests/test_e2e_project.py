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
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


def _gda(project, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*GDA_CMD, *args, "--project", str(project), "--godot", str(GODOT)],
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
def test_project_list_bare_reports_only_customized_settings(godot_project):
    # A bare list reports only the settings the fixture's project.godot actually
    # writes (customized), each as {setting, type, value, is_default} with
    # is_default false — NOT the hundreds of engine built-in defaults.
    listed = _gda(godot_project, "project", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    settings = json.loads(listed.stdout)["settings"]
    by_name = {entry["setting"]: entry for entry in settings}

    # config/name is customized in the fixture's project.godot.
    assert "application/config/name" in by_name
    name_entry = by_name["application/config/name"]
    assert name_entry["type"] == "String"
    assert name_entry["value"] == "gda-e2e-fixture"
    assert name_entry["is_default"] is False
    # Every bare-scope entry is customized (none are defaults).
    assert all(entry["is_default"] is False for entry in settings)
    # A built-in default the fixture never set is absent from the bare listing.
    assert "display/window/size/viewport_width" not in by_name
    # The customized listing stays small — not the engine's hundreds of defaults.
    assert len(settings) < 50


@pytest.mark.e2e
def test_project_list_all_includes_engine_defaults(godot_project):
    # --all widens the listing to the engine's built-in defaults too, so a setting
    # the project never customized appears, flagged is_default true, alongside the
    # customized ones (is_default false).
    listed = _gda(godot_project, "project", "list", "--all", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    settings = json.loads(listed.stdout)["settings"]
    by_name = {entry["setting"]: entry for entry in settings}

    # A built-in default the fixture never set is now present and flagged default.
    assert "display/window/size/viewport_width" in by_name
    assert by_name["display/window/size/viewport_width"]["is_default"] is True
    assert by_name["display/window/size/viewport_width"]["type"] == "int"
    # The customized config/name is still present and still flagged customized.
    assert by_name["application/config/name"]["is_default"] is False
    # --all is the engine's hundreds of registered settings, far more than bare.
    assert len(settings) > 100
    # Internal / non-setting entries are filtered out: no category header, no
    # `script` property, no PROPERTY_USAGE_INTERNAL keys like application/config/features.
    assert "script" not in by_name
    assert "ProjectSettings" not in by_name
    assert "application/config/features" not in by_name


@pytest.mark.e2e
def test_project_list_section_filters_to_a_prefix_and_composes_with_all(godot_project):
    # --section restricts to keys under a section/ prefix; with --all it scopes the
    # engine defaults to that section too.
    listed = _gda(
        godot_project,
        "project",
        "list",
        "--all",
        "--section",
        "application/",
        "--json",
    )

    assert listed.returncode == 0, listed.stdout + listed.stderr
    settings = json.loads(listed.stdout)["settings"]
    names = [entry["setting"] for entry in settings]

    assert names, "section filter should still find application/* keys"
    # Every reported key is under the requested prefix.
    assert all(name.startswith("application/") for name in names)
    assert "application/config/name" in names
    # A different section is excluded by the prefix filter.
    assert not any(name.startswith("display/") for name in names)


@pytest.mark.e2e
def test_project_list_entry_round_trips_through_project_get(godot_project):
    # A listed entry reports the SAME {type, value} projection project get reports
    # for that key — so an agent can list to discover, then get to read one.
    listed = _gda(godot_project, "project", "list", "--all", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    entry = next(
        e
        for e in json.loads(listed.stdout)["settings"]
        if e["setting"] == "display/window/size/viewport_width"
    )

    got = _gda(
        godot_project, "project", "get", "display/window/size/viewport_width", "--json"
    )
    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert entry["type"] == got_data["type"]
    assert entry["value"] == got_data["value"]


@pytest.mark.e2e
def test_project_list_without_project_is_a_clean_error():
    # Projectless: ProjectSettings would report only the engine's bare defaults,
    # not the agent's project, so it is refused with project_not_found (exit 4),
    # consistent with the rest of the project group.
    proc = subprocess.run(
        [*GDA_CMD, "project", "list", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd="/tmp",
    )

    assert proc.returncode == 4
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"


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
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")

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


def _normalized_project_godot(project) -> str:
    # The var_to_str assertions key on token sequences, not layout: Godot writes
    # the action dict across lines with quoted keys, so strip ALL whitespace and
    # compare against the whitespace-free form.
    text = (project / "project.godot").read_text(encoding="utf-8")
    return "".join(text.split())


@pytest.mark.e2e
def test_project_add_input_action_persists_var_to_str_form_and_reports_keycodes(
    godot_project,
):
    # A key NAME and a raw base-10 keycode mix in one action; --deadzone overrides
    # Godot's 0.5 default. The result reports each token's resolved keycode, and
    # project.godot carries the engine's own var_to_str serialization — an [input]
    # section with real Object(InputEventKey, ...) literals (issue #380). The
    # stored-value SHAPE via `project get` is deliberately NOT asserted here (the
    # read-side projection of a compound setting is #381, independent).
    added = _gda(
        godot_project,
        "project",
        "add-input-action",
        "jump",
        "--key",
        "J",
        "--key",
        "32",
        "--deadzone",
        "0.2",
        "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert data["name"] == "jump"
    assert data["deadzone"] == 0.2
    assert data["events"] == [
        {"kind": "key", "key": "J", "keycode": 74, "physical": False},
        {"kind": "key", "key": "32", "keycode": 32, "physical": False},
    ]

    normalized = _normalized_project_godot(godot_project)
    assert "[input]" in normalized
    assert "jump={" in normalized
    # deadzone first — Godot's own key order for an input action.
    assert '"deadzone":0.2' in normalized
    assert "Object(InputEventKey" in normalized
    assert '"keycode":74' in normalized
    assert '"keycode":32' in normalized


@pytest.mark.e2e
def test_project_add_input_action_physical_binds_physical_keycode(godot_project):
    # --physical binds the keyboard POSITION: the persisted event carries the
    # keycode in physical_keycode, and the layout keycode stays unset (0).
    added = _gda(
        godot_project,
        "project",
        "add-input-action",
        "move_up",
        "--key",
        "W",
        "--physical",
        "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert data["events"] == [
        {"kind": "key", "key": "W", "keycode": 87, "physical": True}
    ]

    normalized = _normalized_project_godot(godot_project)
    assert "Object(InputEventKey" in normalized
    assert '"physical_keycode":87' in normalized
    # The layout keycode is NOT also set — physical binds only the position.
    assert '"keycode":87' not in normalized


@pytest.mark.e2e
def test_project_add_input_action_duplicate_name_is_a_clean_error(godot_project):
    first = _gda(
        godot_project, "project", "add-input-action", "fire", "--key", "F", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = _normalized_project_godot(godot_project)

    dup = _gda(
        godot_project, "project", "add-input-action", "fire", "--key", "J", "--json"
    )
    assert dup.returncode == 4
    err = json.loads(dup.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"

    # The original registration is untouched: project.godot is byte-identical.
    assert _normalized_project_godot(godot_project) == before


@pytest.mark.e2e
def test_project_add_input_action_unknown_key_is_a_clean_error(godot_project):
    bad = _gda(
        godot_project,
        "project",
        "add-input-action",
        "jump",
        "--key",
        "NotAKeyName",
        "--json",
    )

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_key"
    assert "NotAKeyName" in err["message"]

    # Nothing was saved: project.godot gained no [input] section.
    assert "[input]" not in _normalized_project_godot(godot_project)


@pytest.mark.e2e
def test_project_remove_input_action_unregisters_and_persists(godot_project):
    added = _gda(
        godot_project, "project", "add-input-action", "jump", "--key", "J", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr

    removed = _gda(godot_project, "project", "remove-input-action", "jump", "--json")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout) == {"name": "jump"}

    # The action is gone from project.godot — no lingering InputEventKey literal.
    normalized = _normalized_project_godot(godot_project)
    assert "jump={" not in normalized
    assert "Object(InputEventKey" not in normalized


@pytest.mark.e2e
def test_project_remove_input_action_unknown_name_is_a_clean_error(godot_project):
    bad = _gda(godot_project, "project", "remove-input-action", "nonexistent", "--json")

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "nonexistent" in err["message"]


@pytest.mark.e2e
def test_project_info_without_project_is_a_clean_error():
    # Projectless: ProjectSettings would report only the engine's bare defaults,
    # not the agent's project, so it is refused with project_not_found.
    proc = subprocess.run(
        [*GDA_CMD, "project", "info", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd="/tmp",
    )

    assert proc.returncode == 4
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"
