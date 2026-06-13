"""`gda <command> --schema` self-description (issue #4, ADR-0004).

`--schema` is a local, no-Godot introspection flag: it derives the command's
input/output JSON Schemas from the same typed models that back `--json` and
prints them to stdout. It spawns no Godot process, so these are unit tests only.
"""

import json

import jsonschema
from typer.testing import CliRunner

from gda.cli import app
from gda.models import EngineVersion, GdaErrorEnvelope, InfoParams

# A sample `gda info` result, shaped as Engine.get_version_info() reports it.
VERSION_INFO = {
    "major": 4,
    "minor": 6,
    "patch": 3,
    "hex": 0x040603,
    "status": "stable",
    "build": "official",
    "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
    "string": "4.6.3-stable (official)",
    "timestamp": 0,
}


def test_info_schema_emits_json_object_with_input_output_and_error():
    result = CliRunner().invoke(app, ["info", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    # The contract is the three-key {input, output, error} object (#43).
    assert set(doc) >= {"input", "output", "error"}
    # All three halves are JSON Schema objects (have a "type"/"properties" shape).
    assert isinstance(doc["input"], dict)
    assert isinstance(doc["output"], dict)
    assert isinstance(doc["error"], dict)


def test_info_output_schema_is_derived_from_the_info_result_model():
    # The output contract is the EngineVersion model's own schema — not a
    # second, hand-written copy (ADR-0004: model-driven self-description).
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    assert doc["output"] == EngineVersion.model_json_schema()


def test_info_error_schema_is_the_uniform_failure_envelope():
    # issue #43 / ADR-0004: --schema now carries a third key, `error`, holding the uniform
    # failure-envelope schema shared by every command (GdaErrorEnvelope). It is
    # the same for all commands and kept OUT of `output` so gda-mcp can map
    # `output` → outputSchema (success) and `error` → the isError channel.
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()


def test_emitted_schemas_are_valid_json_schema():
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    # check_schema raises if the document is not itself a valid JSON Schema.
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])
    # The uniform error envelope is itself well-formed JSON Schema too (#43).
    jsonschema.Draft202012Validator.check_schema(doc["error"])


def test_sample_info_result_validates_against_emitted_output_schema():
    result = CliRunner().invoke(app, ["info", "--schema"])

    output_schema = json.loads(result.stdout)["output"]
    # A real `gda info --json` payload satisfies the contract the flag emits.
    jsonschema.validate(instance=VERSION_INFO, schema=output_schema)


def test_schema_spawns_no_godot(monkeypatch):
    # --schema is a local introspection flag: it must short-circuit before any
    # engine path. Make both binary resolution and the runner explode, then
    # assert the flag still produces its document.
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    result = CliRunner().invoke(app, ["info", "--schema"])

    assert result.exit_code == 0
    assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_schema_is_emit_only_and_rejects_a_supplied_value():
    # ADR-0004: --schema only *emits* a contract, it never *accepts* one.
    # As a bare flag it cannot swallow a caller-supplied schema value.
    result = CliRunner().invoke(app, ["info", "--schema=custom.json"])

    assert result.exit_code != 0


def test_scene_create_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for the first domain commands (issue #18): the
    # bare `--schema` flag — no path, no --root-type — short-circuits into the
    # self-description, derived from the same typed models that back --json.
    from gda.models import SceneCreateParams, SceneCreateResult

    result = CliRunner().invoke(app, ["scene", "create", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneCreateParams.model_json_schema()
    assert doc["output"] == SceneCreateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "root_name" in doc["input"]["properties"]
    assert "created_dirs" in doc["output"]["properties"]
    root_name_description = doc["input"]["properties"]["root_name"]["description"]
    assert '"' in root_name_description
    assert "%" in root_name_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_get_schema_emits_model_derived_contract_without_other_args():
    from gda.models import SceneGetParams, SceneGetResult

    result = CliRunner().invoke(app, ["scene", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneGetParams.model_json_schema()
    assert doc["output"] == SceneGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_list_schema_emits_model_derived_contract_without_a_project():
    # The ADR-0004 hard gate for scene list (issue #54): the bare --schema flag
    # — no --project — short-circuits into the self-description, derived from the
    # same typed models that back --json. scene list takes no operation params,
    # so its input schema is trivially empty (the project is process context,
    # ADR-0006), exactly like info.
    from gda.models import SceneListParams, SceneListResult

    result = CliRunner().invoke(app, ["scene", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneListParams.model_json_schema()
    assert doc["output"] == SceneListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_delete_schema_emits_model_derived_contract_without_other_args():
    from gda.models import SceneDeleteParams, SceneDeleteResult

    result = CliRunner().invoke(app, ["scene", "delete", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneDeleteParams.model_json_schema()
    assert doc["output"] == SceneDeleteResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_scene_results_validate_against_emitted_output_schemas():
    # The other half of the ADR-0004 hard gate (issues #18, #54): a sample
    # --json payload of each scene command satisfies the contract its --schema
    # emits.
    from tests.test_scene_commands import (
        CREATE_RESULT,
        DELETE_RESULT,
        GET_RESULT,
        LIST_RESULT,
    )

    create_doc = json.loads(
        CliRunner().invoke(app, ["scene", "create", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["scene", "get", "--schema"]).stdout)
    list_doc = json.loads(CliRunner().invoke(app, ["scene", "list", "--schema"]).stdout)
    delete_doc = json.loads(
        CliRunner().invoke(app, ["scene", "delete", "--schema"]).stdout
    )

    jsonschema.validate(instance=CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=DELETE_RESULT, schema=delete_doc["output"])


def test_scene_schema_spawns_no_godot(monkeypatch):
    # Same locality guarantee the info flag established: --schema must
    # short-circuit before binary resolution or any runner construction.
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (
        ["scene", "create"],
        ["scene", "get"],
        ["scene", "list"],
        ["scene", "delete"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_node_add_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for the node group (issue #53): the bare --schema
    # flag — no path, no --type — short-circuits into the self-description,
    # derived from the same typed models that back --json.
    from gda.models import NodeAddParams, NodeAddResult

    result = CliRunner().invoke(app, ["node", "add", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeAddParams.model_json_schema()
    assert doc["output"] == NodeAddResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # Node-path addressing is defined in the contract itself: the parent param
    # documents the root-relative convention agents must use.
    parent_description = doc["input"]["properties"]["parent"]["description"]
    assert "scene root" in parent_description
    assert "'.'" in parent_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_list_schema_emits_model_derived_contract_without_other_args():
    from gda.models import NodeListParams, NodeListResult

    result = CliRunner().invoke(app, ["node", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeListParams.model_json_schema()
    assert doc["output"] == NodeListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_get_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node get (issue #55): the bare --schema flag —
    # no path, no --node — short-circuits into the self-description.
    from gda.models import NodeGetParams, NodeGetResult

    result = CliRunner().invoke(app, ["node", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeGetParams.model_json_schema()
    assert doc["output"] == NodeGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    node_description = doc["input"]["properties"]["node"]["description"]
    assert "scene root" in node_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_set_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node set (issue #55): the value param documents
    # the type-coercion contract agents must rely on.
    from gda.models import NodeSetParams, NodeSetResult

    result = CliRunner().invoke(app, ["node", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeSetParams.model_json_schema()
    assert doc["output"] == NodeSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_node_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each node command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issues #53/#55).
    from tests.test_node_commands import (
        ADD_RESULT,
        GET_RESULT,
        LIST_RESULT,
        SET_RESULT,
    )

    add_doc = json.loads(CliRunner().invoke(app, ["node", "add", "--schema"]).stdout)
    list_doc = json.loads(CliRunner().invoke(app, ["node", "list", "--schema"]).stdout)
    get_doc = json.loads(CliRunner().invoke(app, ["node", "get", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["node", "set", "--schema"]).stdout)

    jsonschema.validate(instance=ADD_RESULT, schema=add_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=SET_RESULT, schema=set_doc["output"])


def test_node_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (["node", "add"], ["node", "list"], ["node", "get"], ["node", "set"]):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_script_create_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for the script group (issue #110): the bare
    # --schema flag — no path — short-circuits into the self-description,
    # derived from the same typed models that back --json.
    from gda.models import ScriptCreateParams, ScriptCreateResult

    result = CliRunner().invoke(app, ["script", "create", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptCreateParams.model_json_schema()
    assert doc["output"] == ScriptCreateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The template/content surface is in the contract itself.
    assert "content" in doc["input"]["properties"]
    assert "extends_type" in doc["input"]["properties"]
    assert "class_name" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_script_get_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ScriptGetParams, ScriptGetResult

    result = CliRunner().invoke(app, ["script", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptGetParams.model_json_schema()
    assert doc["output"] == ScriptGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "source" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_script_list_schema_emits_model_derived_contract_without_a_project():
    # The ADR-0004 hard gate for script list (issue #117): the bare --schema flag
    # — no --project — short-circuits into the self-description, derived from the
    # same typed models that back --json. script list takes no operation params,
    # so its input schema is trivially empty (the project is process context,
    # ADR-0006), exactly like scene list.
    from gda.models import ScriptListParams, ScriptListResult

    result = CliRunner().invoke(app, ["script", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptListParams.model_json_schema()
    assert doc["output"] == ScriptListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_script_delete_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ScriptDeleteParams, ScriptDeleteResult

    result = CliRunner().invoke(app, ["script", "delete", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptDeleteParams.model_json_schema()
    assert doc["output"] == ScriptDeleteResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_script_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each script command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issues #110, #117).
    from tests.test_script_commands import CREATE_RESULT, GET_RESULT, LIST_RESULT

    create_doc = json.loads(
        CliRunner().invoke(app, ["script", "create", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["script", "get", "--schema"]).stdout)
    list_doc = json.loads(
        CliRunner().invoke(app, ["script", "list", "--schema"]).stdout
    )
    delete_doc = json.loads(
        CliRunner().invoke(app, ["script", "delete", "--schema"]).stdout
    )

    jsonschema.validate(instance=CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    # A sample delete payload, shaped as the script-delete operation emits it.
    jsonschema.validate(
        instance={"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
        schema=delete_doc["output"],
    )


def test_script_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (
        ["script", "create"],
        ["script", "get"],
        ["script", "list"],
        ["script", "delete"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_info_input_schema_is_derived_from_the_params_model():
    # info takes no operation params, so its input schema is trivially empty —
    # expected, not an error — and still derived model-side (ADR-0004).
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    assert doc["input"] == InfoParams.model_json_schema()
    assert doc["input"].get("properties", {}) == {}


def test_help_takes_precedence_over_schema_regardless_of_argv_order():
    # issue #36 (1): both --schema and --help were eager, so the winner
    # depended on argv order. --help must always win, either order.
    runner = CliRunner()

    schema_first = runner.invoke(app, ["info", "--schema", "--help"])
    help_first = runner.invoke(app, ["info", "--help", "--schema"])

    for result in (schema_first, help_first):
        assert result.exit_code == 0
        assert "Usage" in result.stdout
        # The help screen, not the schema document.
        assert not result.stdout.lstrip().startswith("{")


def test_extra_positional_args_are_a_usage_error_even_with_schema():
    # issue #36 (2): --schema must not swallow a malformed command line. Extra
    # positional args still fail with a usage error (exit 2), not exit 0 + schema.
    result = CliRunner().invoke(app, ["scene", "create", "--schema", "a", "b", "c"])

    assert result.exit_code == 2
    # No schema document was emitted for the malformed invocation.
    assert not result.stdout.lstrip().startswith("{")


def test_schema_flag_binds_false_not_none_when_absent():
    # issue #36 (3): the flag must bind a real bool default (False), not None,
    # so a command body reads a correct boolean. Exercise the shared option in a
    # throwaway app and observe the value the body receives.
    import typer

    from gda.headless import schema_option

    probe = typer.Typer()

    @probe.command()
    def run(schema: bool = schema_option()) -> None:
        typer.echo(f"schema={schema!r}")

    result = CliRunner().invoke(probe, [])

    assert result.exit_code == 0
    assert result.stdout.strip() == "schema=False"
