"""S3: gda project info / get / set success paths against a fake runner (issue #111).

The project command group reads and writes the resolved project's
``project.godot`` / ``ProjectSettings`` headlessly. These tests drive the same
proven pipeline as the scene / node / script groups — Typer → binary resolution
→ runner → sentinel parse → typed model → JSON — with canned engine output, no
real Godot.
"""

import json

import jsonschema
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.project import (
    ProjectAddAutoloadParams,
    ProjectAddAutoloadResult,
    ProjectAddInputActionParams,
    ProjectAddInputActionResult,
    ProjectGetParams,
    ProjectGetResult,
    ProjectInfoParams,
    ProjectInfoResult,
    ProjectListParams,
    ProjectListResult,
    ProjectRemoveAutoloadParams,
    ProjectRemoveAutoloadResult,
    ProjectRemoveInputActionParams,
    ProjectRemoveInputActionResult,
    ProjectSetParams,
    ProjectSetResult,
)
from gda.models import GdaErrorEnvelope
from gda.runner import RunResult
from tests.support import VERSION_INFO, FakeRunner, inject_runner, sentinel

INFO_RESULT = {
    "name": "My Game",
    "main_scene": "res://main.tscn",
    "viewport_width": 1152,
    "viewport_height": 648,
    "engine_version": VERSION_INFO,
}

GET_RESULT = {
    "setting": "application/config/name",
    "type": "String",
    "value": "My Game",
}

SET_RESULT = {
    "setting": "display/window/size/viewport_width",
    "type": "int",
    "value": 1920,
}

LIST_RESULT = {
    "settings": [
        {
            "setting": "application/config/name",
            "type": "String",
            "value": "My Game",
            "is_default": False,
        },
        {
            "setting": "display/window/size/viewport_width",
            "type": "int",
            "value": 1152,
            "is_default": True,
        },
    ],
}


# --- project info ---------------------------------------------------------


def test_project_info_json_maps_success_to_json_object_and_exit_zero(monkeypatch):
    # Engine banner noise around the sentinel, diagnostics on stderr (ADR-0002).
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(INFO_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "info", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "My Game"
    assert data["main_scene"] == "res://main.tscn"
    assert data["viewport_width"] == 1152
    assert data["viewport_height"] == 648
    # The engine version is the same shape gda info reports.
    assert data["engine_version"]["string"] == "4.6.3-stable (official)"
    # project info takes no operation params (the project is process context).
    assert fake.calls == [("project-info", {})]
    assert "engine diagnostic" in result.stderr


def test_project_info_human_output_is_a_readable_block(monkeypatch):
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(INFO_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "info"])

    assert result.exit_code == 0
    assert "name: My Game" in result.stdout
    assert "main_scene: res://main.tscn" in result.stdout
    assert "viewport: 1152x648" in result.stdout
    assert "4.6.3-stable (official)" in result.stdout


def test_project_info_human_output_shows_none_for_empty_main_scene(monkeypatch):
    # A new project has no main scene; the human block names that explicitly.
    payload = {**INFO_RESULT, "main_scene": ""}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "info"])

    assert result.exit_code == 0
    assert "main_scene: (none)" in result.stdout


# --- project get ----------------------------------------------------------


def test_project_get_dispatches_setting_param_and_reports_typed_value(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["project", "get", "application/config/name", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == GET_RESULT
    # The setting rides through as the one operation param.
    assert fake.calls == [("project-get", {"setting": "application/config/name"})]


def test_project_get_human_output_is_setting_type_value(monkeypatch):
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "get", "application/config/name"])

    assert result.exit_code == 0
    assert result.stdout.strip() == 'application/config/name (String) = "My Game"'


def test_project_get_carries_packed_value_projection(monkeypatch):
    # A packed-type setting (e.g. a Vector2-ish value) is carried as a JSON list,
    # the same projection node get reports — so get / set round-trip the shape.
    payload = {"setting": "some/vec", "type": "Vector2", "value": [10.0, 20.0]}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "get", "some/vec", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["value"] == [10.0, 20.0]


def test_project_get_carries_compound_value_projection_untouched(monkeypatch):
    # A compound-valued setting (ADR-0035): the operation projects a Dictionary
    # to a JSON object — here an InputMap action with an inline-projected
    # InputEventKey in its events list — and the CLI carries the structure
    # through --json untouched (value stays Any; nothing re-shapes it).
    value = {
        "deadzone": 0.5,
        "events": [{"type": "InputEventKey", "keycode": 74, "pressed": False}],
    }
    payload = {"setting": "input/fire", "type": "Dictionary", "value": value}
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "get", "input/fire", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["value"] == value
    # The projection is indexable, the point of #381.
    assert data["value"]["deadzone"] == 0.5
    assert data["value"]["events"][0]["keycode"] == 74


# --- project set ----------------------------------------------------------


def test_project_set_dispatches_setting_and_value_and_round_trips(monkeypatch):
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "project",
            "set",
            "display/window/size/viewport_width",
            "--value",
            "1920",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # The result reports the coerced value as the JSON projection get reports,
    # so a set round-trips through a get (the declared int type, not the string).
    assert data["setting"] == "display/window/size/viewport_width"
    assert data["type"] == "int"
    assert data["value"] == 1920
    # The CLI value is passed as a string; the operation owns the coercion.
    assert fake.calls == [
        (
            "project-set",
            {"setting": "display/window/size/viewport_width", "value": "1920"},
        )
    ]


def test_project_set_human_output_is_set_setting_type_value(monkeypatch):
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["project", "set", "display/window/size/viewport_width", "--value", "1920"]
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip() == "set display/window/size/viewport_width (int) = 1920"
    )


def test_project_set_requires_value(monkeypatch):
    # --value is required: a set with no value is a usage error (exit 2), not a
    # silent no-op or an empty write.
    fake = FakeRunner(RunResult(stdout=sentinel(SET_RESULT), stderr="", exit_code=0))
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(app, ["project", "set", "application/config/name"])

    assert result.exit_code == 2
    assert fake.calls == []


# --- project list ---------------------------------------------------------


def test_project_list_bare_dispatches_customized_scope_and_maps_entries(monkeypatch):
    # A bare list lists only customized settings: include_defaults defaults False,
    # section None. Each entry rides through as {setting, type, value, is_default}.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == LIST_RESULT
    assert fake.calls == [
        ("project-list", {"include_defaults": False, "section": None})
    ]


def test_project_list_all_flag_widens_scope_to_engine_defaults(monkeypatch):
    # --all sets include_defaults True so the engine's built-in defaults are listed
    # too, not just the project's customized settings.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "list", "--all", "--json"])

    assert result.exit_code == 0
    assert fake.calls == [("project-list", {"include_defaults": True, "section": None})]


def test_project_list_section_filter_rides_through_as_a_param(monkeypatch):
    # --section restricts the listing to keys under a section/ prefix; it composes
    # with --all (both ride through as operation params).
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["project", "list", "--all", "--section", "application/", "--json"]
    )

    assert result.exit_code == 0
    assert fake.calls == [
        ("project-list", {"include_defaults": True, "section": "application/"})
    ]


def test_project_list_human_output_lines_settings_and_marks_defaults(monkeypatch):
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["project", "list"])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0] == 'application/config/name (String) = "My Game"'
    # An engine-default entry is tagged so customized vs default reads at a glance.
    assert lines[1] == "display/window/size/viewport_width (int) = 1152 [default]"


def test_project_list_human_output_names_an_empty_listing(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel({"settings": []}), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["project", "list"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "(no settings)"


# --- project add-autoload -------------------------------------------------


ADD_AUTOLOAD_RESULT = {
    "name": "Global",
    "path": "*res://global.gd",
}

REMOVE_AUTOLOAD_RESULT = {
    "name": "Global",
}


def test_project_add_autoload_dispatches_name_and_path_and_reports_result(monkeypatch):
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(ADD_AUTOLOAD_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["project", "add-autoload", "Global", "res://global.gd", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "Global"
    # The persisted value is the enabled-singleton form (the leading * prefix).
    assert data["path"] == "*res://global.gd"
    # name and the res:// path ride through as the two operation params; the CLI
    # passes the bare path and the operation owns the autoload/ section + * prefix.
    assert fake.calls == [
        ("project-add-autoload", {"name": "Global", "path": "res://global.gd"})
    ]


def test_project_add_autoload_human_output_names_the_registered_autoload(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(ADD_AUTOLOAD_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["project", "add-autoload", "Global", "res://global.gd"]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "added autoload Global = *res://global.gd"


# --- project remove-autoload ----------------------------------------------


def test_project_remove_autoload_dispatches_name_and_reports_result(monkeypatch):
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(REMOVE_AUTOLOAD_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["project", "remove-autoload", "Global", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == REMOVE_AUTOLOAD_RESULT
    assert fake.calls == [("project-remove-autoload", {"name": "Global"})]


def test_project_remove_autoload_human_output_names_the_unregistered_autoload(
    monkeypatch,
):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(REMOVE_AUTOLOAD_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["project", "remove-autoload", "Global"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "removed autoload Global"


# --- project add-input-action ----------------------------------------------


ADD_INPUT_ACTION_RESULT = {
    "name": "jump",
    "deadzone": 0.5,
    "events": [
        {"kind": "key", "key": "J", "keycode": 74, "physical": False},
        {"kind": "key", "key": "Space", "keycode": 32, "physical": False},
    ],
}

REMOVE_INPUT_ACTION_RESULT = {
    "name": "jump",
}


def test_project_add_input_action_dispatches_full_params_and_reports_result(
    monkeypatch,
):
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(ADD_INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "project",
            "add-input-action",
            "jump",
            "--key",
            "J",
            "--key",
            "Space",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "jump"
    assert data["deadzone"] == 0.5
    # Each event echoes the raw token and the keycode it resolved to.
    assert data["events"][0] == {
        "kind": "key",
        "key": "J",
        "keycode": 74,
        "physical": False,
    }
    # The FULL params model rides through: name, the repeatable keys in order,
    # the default deadzone, and the default physical=False.
    assert fake.calls == [
        (
            "project-add-input-action",
            {
                "name": "jump",
                "keys": ["J", "Space"],
                "deadzone": 0.5,
                "physical": False,
            },
        )
    ]


def test_project_add_input_action_dispatches_deadzone_and_physical_overrides(
    monkeypatch,
):
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(ADD_INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "project",
            "add-input-action",
            "jump",
            "--key",
            "74",
            "--deadzone",
            "0.2",
            "--physical",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "project-add-input-action",
            {"name": "jump", "keys": ["74"], "deadzone": 0.2, "physical": True},
        )
    ]


def test_project_add_input_action_requires_at_least_one_key(monkeypatch):
    # --key is required: an add with no keys is a usage error (exit 2), not a
    # dispatch of an empty key list.
    fake = FakeRunner(
        RunResult(stdout=sentinel(ADD_INPUT_ACTION_RESULT), stderr="", exit_code=0)
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(app, ["project", "add-input-action", "jump"])

    assert result.exit_code == 2
    assert fake.calls == []


def test_project_add_input_action_rejects_out_of_range_deadzone(monkeypatch):
    # The deadzone bounds (0..1, the editor slider's) are validated model-side
    # (ADR-0015) and surface as a clean usage error before any dispatch.
    fake = FakeRunner(
        RunResult(stdout=sentinel(ADD_INPUT_ACTION_RESULT), stderr="", exit_code=0)
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app,
        ["project", "add-input-action", "jump", "--key", "J", "--deadzone", "1.5"],
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_project_add_input_action_human_output_lists_resolved_bindings(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(ADD_INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["project", "add-input-action", "jump", "--key", "J", "--key", "Space"]
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "added input action jump (deadzone 0.5): J -> 74, Space -> 32"
    )


def test_project_add_input_action_human_output_marks_physical_bindings(monkeypatch):
    payload = {
        "name": "jump",
        "deadzone": 0.5,
        "events": [{"kind": "key", "key": "J", "keycode": 74, "physical": True}],
    }
    inject_runner(
        monkeypatch, RunResult(stdout=sentinel(payload), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["project", "add-input-action", "jump", "--key", "J", "--physical"]
    )

    assert result.exit_code == 0
    assert (
        result.stdout.strip()
        == "added input action jump (deadzone 0.5): J -> 74 (physical)"
    )


# --- project remove-input-action --------------------------------------------


def test_project_remove_input_action_dispatches_name_and_reports_result(monkeypatch):
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(REMOVE_INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["project", "remove-input-action", "jump", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == REMOVE_INPUT_ACTION_RESULT
    assert fake.calls == [("project-remove-input-action", {"name": "jump"})]


def test_project_remove_input_action_human_output_names_the_removed_action(
    monkeypatch,
):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(REMOVE_INPUT_ACTION_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["project", "remove-input-action", "jump"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "removed input action jump"


# --- ADR-0004 --schema hard gate -----------------------------------------


def test_project_info_schema_emits_model_derived_contract_without_a_project():
    # The ADR-0004 hard gate for project info (issue #111): the bare --schema flag
    # — no --project — short-circuits into the self-description, derived from the
    # same typed models that back --json. project info takes no operation params,
    # so its input schema is trivially empty (the project is process context).
    result = CliRunner().invoke(app, ["project", "info", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectInfoParams.model_json_schema()
    assert doc["output"] == ProjectInfoResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    assert "engine_version" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_get_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectGetParams.model_json_schema()
    assert doc["output"] == ProjectGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "section/key" in doc["input"]["properties"]["setting"]["description"]
    # The emitted command schema exposes the named Object-projection shapes on
    # the Any-typed value field (ADR-0035 → ADR-0004), not prose alone.
    value_defs = doc["output"]["properties"]["value"]["$defs"]
    assert set(value_defs) == {"ReferenceProjection", "InlineValueProjection"}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_set_schema_emits_model_derived_contract_without_other_args():
    # The value param documents the type-coercion contract agents must rely on.
    result = CliRunner().invoke(app, ["project", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectSetParams.model_json_schema()
    assert doc["output"] == ProjectSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_list_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectListParams.model_json_schema()
    assert doc["output"] == ProjectListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The two scope params are part of the self-described input contract.
    assert "include_defaults" in doc["input"]["properties"]
    assert "section" in doc["input"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_add_autoload_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "add-autoload", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectAddAutoloadParams.model_json_schema()
    assert doc["output"] == ProjectAddAutoloadResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "name" in doc["input"]["properties"]
    assert "path" in doc["input"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_remove_autoload_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "remove-autoload", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectRemoveAutoloadParams.model_json_schema()
    assert doc["output"] == ProjectRemoveAutoloadResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "name" in doc["input"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_add_input_action_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "add-input-action", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectAddInputActionParams.model_json_schema()
    assert doc["output"] == ProjectAddInputActionResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "name" in doc["input"]["properties"]
    assert "keys" in doc["input"]["properties"]
    assert "deadzone" in doc["input"]["properties"]
    assert "physical" in doc["input"]["properties"]
    # The key list is bounded model-side: at least one key (ADR-0015).
    assert doc["input"]["properties"]["keys"]["minItems"] == 1
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_remove_input_action_schema_emits_model_derived_contract_without_other_args():
    result = CliRunner().invoke(app, ["project", "remove-input-action", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectRemoveInputActionParams.model_json_schema()
    assert doc["output"] == ProjectRemoveInputActionResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "name" in doc["input"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_project_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each project command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issue #111).
    info_doc = json.loads(
        CliRunner().invoke(app, ["project", "info", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["project", "get", "--schema"]).stdout)
    list_doc = json.loads(
        CliRunner().invoke(app, ["project", "list", "--schema"]).stdout
    )
    set_doc = json.loads(CliRunner().invoke(app, ["project", "set", "--schema"]).stdout)
    add_doc = json.loads(
        CliRunner().invoke(app, ["project", "add-autoload", "--schema"]).stdout
    )
    remove_doc = json.loads(
        CliRunner().invoke(app, ["project", "remove-autoload", "--schema"]).stdout
    )
    add_input_doc = json.loads(
        CliRunner().invoke(app, ["project", "add-input-action", "--schema"]).stdout
    )
    remove_input_doc = json.loads(
        CliRunner().invoke(app, ["project", "remove-input-action", "--schema"]).stdout
    )

    jsonschema.validate(instance=INFO_RESULT, schema=info_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=SET_RESULT, schema=set_doc["output"])
    jsonschema.validate(instance=ADD_AUTOLOAD_RESULT, schema=add_doc["output"])
    jsonschema.validate(instance=REMOVE_AUTOLOAD_RESULT, schema=remove_doc["output"])
    jsonschema.validate(
        instance=ADD_INPUT_ACTION_RESULT, schema=add_input_doc["output"]
    )
    jsonschema.validate(
        instance=REMOVE_INPUT_ACTION_RESULT, schema=remove_input_doc["output"]
    )


def test_project_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

    for command in (
        ["project", "info"],
        ["project", "get"],
        ["project", "list"],
        ["project", "set"],
        ["project", "add-autoload"],
        ["project", "remove-autoload"],
        ["project", "add-input-action"],
        ["project", "remove-input-action"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}
