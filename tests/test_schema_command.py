"""`gda <command> --schema` self-description (issue #4, ADR-0004).

`--schema` is a local, no-Godot introspection flag: it derives the command's
input/output JSON Schemas from the same typed models that back `--json` and
prints them to stdout. It spawns no Godot process, so these are unit tests only.
"""

import json

import jsonschema
from typer.testing import CliRunner

from gda.cli import app
from gda.models import EngineVersion, InfoParams

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


def test_info_schema_emits_json_object_with_input_and_output():
    result = CliRunner().invoke(app, ["info", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert set(doc) >= {"input", "output"}
    # Both halves are JSON Schema objects (have a "type"/"properties" shape).
    assert isinstance(doc["input"], dict)
    assert isinstance(doc["output"], dict)


def test_info_output_schema_is_derived_from_the_info_result_model():
    # The output contract is the EngineVersion model's own schema — not a
    # second, hand-written copy (ADR-0004: model-driven self-description).
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    assert doc["output"] == EngineVersion.model_json_schema()


def test_emitted_schemas_are_valid_json_schema():
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    # check_schema raises if the document is not itself a valid JSON Schema.
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


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
    assert set(json.loads(result.stdout)) >= {"input", "output"}


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
        assert set(json.loads(result.stdout)) >= {"input", "output"}


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
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_node_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each node command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issue #53).
    from tests.test_node_commands import ADD_RESULT, LIST_RESULT

    add_doc = json.loads(CliRunner().invoke(app, ["node", "add", "--schema"]).stdout)
    list_doc = json.loads(CliRunner().invoke(app, ["node", "list", "--schema"]).stdout)

    jsonschema.validate(instance=ADD_RESULT, schema=add_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])


def test_node_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (["node", "add"], ["node", "list"]):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output"}


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
