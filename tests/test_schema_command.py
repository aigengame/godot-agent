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


def test_sample_scene_results_validate_against_emitted_output_schemas():
    # The other half of the ADR-0004 hard gate (issue #18): a sample --json
    # payload of each scene command satisfies the contract its --schema emits.
    from tests.test_scene_commands import CREATE_RESULT, GET_RESULT

    create_doc = json.loads(CliRunner().invoke(app, ["scene", "create", "--schema"]).stdout)
    get_doc = json.loads(CliRunner().invoke(app, ["scene", "get", "--schema"]).stdout)

    jsonschema.validate(instance=CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])


def test_scene_schema_spawns_no_godot(monkeypatch):
    # Same locality guarantee the info flag established: --schema must
    # short-circuit before binary resolution or any runner construction.
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (["scene", "create"], ["scene", "get"]):
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
