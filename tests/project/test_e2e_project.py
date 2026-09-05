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

import pytest

from tests.support import Gda, panel_text

from tests.conftest import project_godot


# An [input] action holding a real InputEventKey Object literal — the exact
# on-disk shape the Godot editor writes for an InputMap binding (the #381
# reproduction: a compound Dictionary value with an embedded value Object).
INPUT_ACTION_SECTION = (
    "[input]\n\n"
    "fire={\n"
    '"deadzone": 0.5,\n'
    '"events": [Object(InputEventKey,"resource_local_to_scene":false,'
    '"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,'
    '"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,'
    '"pressed":false,"keycode":74,"physical_keycode":0,"key_label":0,'
    '"unicode":106,"location":0,"echo":false,"script":null)\n'
    "]\n"
    "}\n"
)


@pytest.mark.e2e
def test_project_info_reports_metadata(godot_project):
    info = Gda(godot_project)("project", "info", "--json")

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
    got = Gda(godot_project)("project", "get", "application/config/name", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["setting"] == "application/config/name"
    assert data["type"] == "String"
    assert data["value"] == "gda-e2e-fixture"


@pytest.mark.e2e
def test_project_get_input_action_projects_a_structured_dictionary(godot_project):
    # The #381 acceptance case (ADR-0035): an [input] action is a Dictionary
    # holding an embedded InputEventKey. project get returns an indexable JSON
    # object — value.deadzone, value.events[0].keycode — with the event as an
    # inline value projection, not a str() debug dump.
    (godot_project / "project.godot").write_text(
        project_godot(extra=INPUT_ACTION_SECTION), encoding="utf-8"
    )

    got = Gda(godot_project)("project", "get", "input/fire", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["type"] == "Dictionary"
    value = data["value"]
    assert value["deadzone"] == 0.5
    event = value["events"][0]
    assert event["type"] == "InputEventKey"
    assert event["keycode"] == 74
    # The inline value projection excludes the Object/Resource base bookkeeping,
    # so a path-less value Object never masquerades as a reference projection.
    excluded_keys = (
        "resource_path",
        "resource_name",
        "resource_local_to_scene",
        "script",
    )
    for excluded in excluded_keys:
        assert excluded not in event, f"{excluded} must be excluded from the projection"


@pytest.mark.e2e
def test_project_get_packed_string_array_setting_projects_a_json_list(godot_project):
    # A packed-array-valued setting projects to a JSON array (ADR-0035), not the
    # Variant str() form.
    (godot_project / "project.godot").write_text(
        project_godot(extra='[gda]\n\ntags=PackedStringArray("alpha", "beta")\n'),
        encoding="utf-8",
    )

    got = Gda(godot_project)("project", "get", "gda/tags", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["type"] == "PackedStringArray"
    assert data["value"] == ["alpha", "beta"]


@pytest.mark.e2e
def test_project_set_coerces_persists_and_round_trips_via_get(godot_project):
    # The CLI value is a STRING; the operation coerces it to the setting's declared
    # int type, saves project.godot, and the result reports the coerced int (#55
    # coercion reused). A second get reads it back from the saved file.
    was_set = Gda(godot_project)(
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
    got = Gda(godot_project)(
        "project", "get", "display/window/size/viewport_width", "--json"
    )
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == 1920

    # And project info reflects the saved viewport width.
    info = Gda(godot_project)("project", "info", "--json")
    assert info.returncode == 0, info.stdout + info.stderr
    assert json.loads(info.stdout)["viewport_width"] == 1920


@pytest.mark.e2e
def test_project_set_preserves_json_container_integer_and_float_types(godot_project):
    # #427: project set uses ProjectSettings' current value as the target type
    # source. A customized Dictionary setting must preserve JSON int vs float
    # values through set, save, and a fresh project get.
    (godot_project / "project.godot").write_text(
        project_godot(extra='[gda]\n\nstats={"seed":1}\n'),
        encoding="utf-8",
    )

    was_set = Gda(godot_project)(
        "project",
        "set",
        "gda/stats",
        "--value",
        '{"a":2,"b":2.0,"items":[1,1.5]}',
        "--json",
    )

    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    set_value = json.loads(was_set.stdout)["value"]
    assert type(set_value["a"]) is int
    assert type(set_value["b"]) is float
    assert type(set_value["items"][0]) is int
    assert type(set_value["items"][1]) is float

    got = Gda(godot_project)("project", "get", "gda/stats", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    got_value = json.loads(got.stdout)["value"]
    assert type(got_value["a"]) is int
    assert type(got_value["b"]) is float
    assert type(got_value["items"][0]) is int
    assert type(got_value["items"][1]) is float


@pytest.mark.e2e
def test_project_set_string_setting_round_trips(godot_project):
    # A String-typed setting takes the CLI value verbatim and round-trips.
    was_set = Gda(godot_project)(
        "project",
        "set",
        "application/config/name",
        "--value",
        "Renamed Game",
        "--json",
    )
    assert was_set.returncode == 0, was_set.stdout + was_set.stderr
    assert json.loads(was_set.stdout)["value"] == "Renamed Game"

    got = Gda(godot_project)("project", "get", "application/config/name", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == "Renamed Game"


@pytest.mark.e2e
def test_project_list_bare_reports_only_customized_settings(godot_project):
    # A bare list reports only the settings the fixture's project.godot actually
    # writes (customized), each as {setting, type, value, is_default} with
    # is_default false — NOT the hundreds of engine built-in defaults.
    listed = Gda(godot_project)("project", "list", "--json")

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
    listed = Gda(godot_project)("project", "list", "--all", "--json")

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
    listed = Gda(godot_project)(
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
    listed = Gda(godot_project)("project", "list", "--all", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    entry = next(
        e
        for e in json.loads(listed.stdout)["settings"]
        if e["setting"] == "display/window/size/viewport_width"
    )

    got = Gda(godot_project)(
        "project", "get", "display/window/size/viewport_width", "--json"
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
    proc = Gda()("project", "list", "--json", cwd="/tmp")

    assert proc.returncode == 4
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"


@pytest.mark.e2e
def test_project_get_unknown_setting_is_a_clean_error(godot_project):
    got = Gda(godot_project)("project", "get", "application/bogus/key", "--json")

    assert got.returncode == 4
    err = json.loads(got.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "application/bogus/key" in err["message"]


@pytest.mark.e2e
def test_project_set_uncoercible_value_is_a_clean_error(godot_project):
    # An int setting cannot take a non-numeric string — uncoercible_value (#55),
    # exit 4, project.godot left untouched.
    bad = Gda(godot_project)(
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
    got = Gda(godot_project)(
        "project", "get", "display/window/size/viewport_width", "--json"
    )
    assert got.returncode == 0, got.stdout + got.stderr


@pytest.mark.e2e
def test_project_add_autoload_registers_persists_and_round_trips(godot_project):
    # A real script to autoload must exist in the project (path_not_found otherwise).
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")

    added = Gda(godot_project)(
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
    got = Gda(godot_project)("project", "get", "autoload/Global", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    got_data = json.loads(got.stdout)
    assert got_data["setting"] == "autoload/Global"
    assert got_data["value"] == "*res://global.gd"


@pytest.mark.e2e
def test_project_remove_autoload_unregisters_and_round_trips(godot_project):
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")
    added = Gda(godot_project)(
        "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr

    removed = Gda(godot_project)("project", "remove-autoload", "Global", "--json")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout) == {"name": "Global"}

    # Round-trip: the autoload is gone from project.godot — a fresh get reports it
    # as an unknown setting, exit 4.
    got = Gda(godot_project)("project", "get", "autoload/Global", "--json")
    assert got.returncode == 4, got.stdout + got.stderr
    assert json.loads(got.stdout)["error"]["code"] == "unknown_setting"


@pytest.mark.e2e
def test_project_add_autoload_duplicate_name_is_a_clean_error(godot_project):
    (godot_project / "global.gd").write_text("extends Node\n", encoding="utf-8")
    first = Gda(godot_project)(
        "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr

    dup = Gda(godot_project)(
        "project", "add-autoload", "Global", "res://global.gd", "--json"
    )
    assert dup.returncode == 4
    err = json.loads(dup.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"

    # The original registration is untouched: a get still reads it back.
    got = Gda(godot_project)("project", "get", "autoload/Global", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["value"] == "*res://global.gd"


@pytest.mark.e2e
def test_project_add_autoload_missing_target_is_a_clean_error(godot_project):
    # The target script/scene does not exist — path_not_found, exit 4, nothing saved.
    bad = Gda(godot_project)(
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
    got = Gda(godot_project)("project", "get", "autoload/Global", "--json")
    assert got.returncode == 4
    assert json.loads(got.stdout)["error"]["code"] == "unknown_setting"


@pytest.mark.e2e
def test_project_remove_autoload_unknown_name_is_a_clean_error(godot_project):
    bad = Gda(godot_project)("project", "remove-autoload", "Nonexistent", "--json")

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
    added = Gda(godot_project)(
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
    # The editor's device convention (InputMap ALL_DEVICES): a real keyboard
    # event carries its own device id, so a device-pinned event would not fire.
    assert '"device":-1' in normalized


@pytest.mark.e2e
def test_project_add_input_action_physical_binds_physical_keycode(godot_project):
    # --physical binds the keyboard POSITION: the persisted event carries the
    # keycode in physical_keycode, and the layout keycode stays unset (0).
    added = Gda(godot_project)(
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
    first = Gda(godot_project)(
        "project", "add-input-action", "fire", "--key", "F", "--json"
    )
    assert first.returncode == 0, first.stdout + first.stderr
    before = _normalized_project_godot(godot_project)

    dup = Gda(godot_project)(
        "project", "add-input-action", "fire", "--key", "J", "--json"
    )
    assert dup.returncode == 4
    err = json.loads(dup.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"

    # The original registration is untouched: project.godot is byte-identical.
    assert _normalized_project_godot(godot_project) == before


@pytest.mark.e2e
def test_project_add_input_action_unknown_key_is_a_clean_error(godot_project):
    bad = Gda(godot_project)(
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
    added = Gda(godot_project)(
        "project", "add-input-action", "jump", "--key", "J", "--json"
    )
    assert added.returncode == 0, added.stdout + added.stderr

    removed = Gda(godot_project)("project", "remove-input-action", "jump", "--json")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout) == {"name": "jump"}

    # The action is gone from project.godot — no lingering InputEventKey literal.
    normalized = _normalized_project_godot(godot_project)
    assert "jump={" not in normalized
    assert "Object(InputEventKey" not in normalized


@pytest.mark.e2e
def test_project_remove_input_action_unknown_name_is_a_clean_error(godot_project):
    bad = Gda(godot_project)("project", "remove-input-action", "nonexistent", "--json")

    assert bad.returncode == 4
    err = json.loads(bad.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "nonexistent" in err["message"]


@pytest.mark.e2e
def test_project_info_without_project_is_a_clean_error():
    # Projectless: ProjectSettings would report only the engine's bare defaults,
    # not the agent's project, so it is refused with project_not_found.
    proc = Gda()("project", "info", "--json", cwd="/tmp")

    assert proc.returncode == 4
    err = json.loads(proc.stdout)["error"]
    assert err["code"] == "project_not_found"


# --- joypad bindings (#842) --------------------------------------------------

# A headless probe of the InputMap the ENGINE built from project.godot: it prints
# one JSON line per bound event of an action, so the assertion is on what the
# engine loaded, not on what gda wrote. `project get` reads the stored SETTING;
# this reads the InputMap the running game actually consults, which is the thing
# a controller binding has to reach.
INPUT_MAP_PROBE_GD = """\
extends SceneTree

func _initialize() -> void:
\tvar rows := []
\tfor event in InputMap.action_get_events("jump"):
\t\tvar row := {"class": event.get_class(), "device": event.device}
\t\tif event is InputEventKey:
\t\t\trow["keycode"] = event.keycode
\t\telif event is InputEventJoypadButton:
\t\t\trow["button_index"] = event.button_index
\t\telif event is InputEventJoypadMotion:
\t\t\trow["axis"] = event.axis
\t\t\trow["axis_value"] = event.axis_value
\t\trows.append(row)
\tprint("INPUT_MAP=", JSON.stringify(rows))
\tquit(0)
"""


@pytest.mark.e2e
def test_project_add_input_action_persists_key_and_joypad_events_in_var_to_str_form(
    godot_project,
):
    # The #380 byte-equivalence regression, EXTENDED to the joypad event types
    # (#842): one call declares a key, a joypad button and a joypad axis
    # direction, and project.godot carries all three as the engine's own
    # var_to_str Object literals — gda hand-builds none of them (ADR-0033).
    # Issue #843 extends this same fixture with its restored-line assertions.
    added = Gda(godot_project).json(
        "project",
        "add-input-action",
        "jump",
        "--key",
        "Space",
        "--joy-button",
        "A",
        "--joy-axis",
        "LeftX:-",
    )

    assert added["name"] == "jump"
    assert added["events"] == [
        {"kind": "key", "key": "Space", "keycode": 32, "physical": False},
        {"kind": "joy_button", "button": "A", "button_index": 0, "device": -1},
        {
            "kind": "joy_axis",
            "axis": "LeftX:-",
            "axis_index": 0,
            "axis_value": -1.0,
            "device": -1,
        },
    ]

    normalized = _normalized_project_godot(godot_project)
    assert "[input]" in normalized
    assert "Object(InputEventKey" in normalized
    assert "Object(InputEventJoypadButton" in normalized
    assert "Object(InputEventJoypadMotion" in normalized
    # JOY_BUTTON_A is 0 and JOY_AXIS_LEFT_X is 0 (godot 4.6.3-stable,
    # core/input/input_enums.h); the `-` sign is axis_value -1.0.
    assert '"button_index":0' in normalized
    assert '"axis":0' in normalized
    assert '"axis_value":-1.0' in normalized
    # Every event matches ANY device by default (InputMap ALL_DEVICES).
    assert '"device":0' not in normalized
    assert '"device":-1' in normalized


@pytest.mark.e2e
def test_project_add_input_action_joypad_events_read_back_through_project_get(
    godot_project,
):
    # The structured verification the AC asks for: `project get input/<name>`
    # projects the stored compound value, so the joypad events read back with
    # their device, button_index and axis/axis_value (ADR-0035 inline kind).
    Gda(godot_project).json(
        "project",
        "add-input-action",
        "jump",
        "--joy-button",
        "DPadLeft",
        "--joy-axis",
        "TriggerRight",
    )

    value = Gda(godot_project).json("project", "get", "input/jump")["value"]
    assert value["deadzone"] == 0.5
    events = {event["type"]: event for event in value["events"]}
    # JOY_BUTTON_DPAD_LEFT is 13, JOY_AXIS_TRIGGER_RIGHT is 5 (4.6.3-stable).
    assert events["InputEventJoypadButton"]["button_index"] == 13
    assert events["InputEventJoypadButton"]["device"] == -1
    assert events["InputEventJoypadMotion"]["axis"] == 5
    # An omitted sign is the POSITIVE direction.
    assert events["InputEventJoypadMotion"]["axis_value"] == 1.0
    assert events["InputEventJoypadMotion"]["device"] == -1


@pytest.mark.e2e
def test_project_add_input_action_bindings_reach_the_loaded_input_map(godot_project):
    # The engine-side half of the verification: after the project loads, the
    # bindings are in the InputMap the running game consults.
    Gda(godot_project).json(
        "project",
        "add-input-action",
        "jump",
        "--key",
        "Space",
        "--joy-button",
        "A",
        "--joy-axis",
        "LeftX:-",
    )
    (godot_project / "input_map_probe.gd").write_text(
        INPUT_MAP_PROBE_GD, encoding="utf-8"
    )

    run = Gda(godot_project).json(
        "script", "run", "res://input_map_probe.gd", retry=True
    )

    line = next(
        row for row in run["stdout"].splitlines() if row.startswith("INPUT_MAP=")
    )
    rows = json.loads(line.removeprefix("INPUT_MAP="))
    assert rows == [
        {"class": "InputEventKey", "device": -1, "keycode": 32},
        {"class": "InputEventJoypadButton", "device": -1, "button_index": 0},
        {
            "class": "InputEventJoypadMotion",
            "device": -1,
            "axis": 0,
            "axis_value": -1.0,
        },
    ]


@pytest.mark.e2e
def test_project_add_input_action_device_pins_the_joypad_events(godot_project):
    # --device applies to the joypad events of THIS call. The key event stays at
    # ALL_DEVICES: a real keyboard event carries its own device id, so pinning it
    # to a joypad number would stop it matching (the #380 reason).
    added = Gda(godot_project).json(
        "project",
        "add-input-action",
        "jump",
        "--key",
        "Space",
        "--joy-button",
        "A",
        "--device",
        "1",
    )

    assert added["events"][0] == {
        "kind": "key",
        "key": "Space",
        "keycode": 32,
        "physical": False,
    }
    assert added["events"][1]["device"] == 1

    value = Gda(godot_project).json("project", "get", "input/jump")["value"]
    events = {event["type"]: event for event in value["events"]}
    assert events["InputEventKey"]["device"] == -1
    assert events["InputEventJoypadButton"]["device"] == 1


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("option", "token", "accepted"),
    [
        ("--joy-button", "NotAButton", "DPadLeft"),
        ("--joy-axis", "NotAnAxis:-", "TriggerRight"),
        # A recognized axis with an unusable sign is the same refusal: the whole
        # token could not be resolved to a binding.
        ("--joy-axis", "LeftX:sideways", "TriggerRight"),
    ],
)
def test_project_add_input_action_unresolvable_joypad_token_names_the_accepted_set(
    godot_project, option, token, accepted
):
    err = Gda(godot_project).error(
        "project",
        "add-input-action",
        "jump",
        option,
        token,
        code="invalid_key",
    )

    assert err["category"] == "operation"
    assert token.split(":")[0] in err["message"]
    # The message names the accepted set, so a caller can correct without
    # reading the docs (#842 AC).
    assert accepted in err["message"]
    # Nothing was saved.
    assert "[input]" not in _normalized_project_godot(godot_project)


@pytest.mark.e2e
def test_project_add_input_action_with_no_binding_is_a_usage_error(godot_project):
    bad = Gda(godot_project)("project", "add-input-action", "jump", "--json")

    assert bad.returncode == 2, bad.stdout + bad.stderr
    assert "at least one binding" in panel_text(bad.stderr)
    assert (
        not (godot_project / "project.godot")
        .read_text(encoding="utf-8")
        .count("[input]")
    )
