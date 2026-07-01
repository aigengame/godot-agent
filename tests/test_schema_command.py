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
from tests.support import VERSION_INFO


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


def test_scene_get_exports_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for scene get-exports (issue #58): the bare --schema
    # flag — no path — short-circuits into the self-description, derived from the
    # same typed models that back --json.
    from gda.models import SceneGetExportsParams, SceneGetExportsResult

    result = CliRunner().invoke(app, ["scene", "get-exports", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneGetExportsParams.model_json_schema()
    assert doc["output"] == SceneGetExportsResult.model_json_schema()
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
    from tests.support import (
        SCENE_CREATE_RESULT,
        SCENE_DELETE_RESULT,
        SCENE_GET_RESULT,
        SCENE_LIST_RESULT,
    )

    create_doc = json.loads(
        CliRunner().invoke(app, ["scene", "create", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["scene", "get", "--schema"]).stdout)
    list_doc = json.loads(CliRunner().invoke(app, ["scene", "list", "--schema"]).stdout)
    delete_doc = json.loads(
        CliRunner().invoke(app, ["scene", "delete", "--schema"]).stdout
    )

    jsonschema.validate(instance=SCENE_CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=SCENE_GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=SCENE_LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=SCENE_DELETE_RESULT, schema=delete_doc["output"])


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
        ["scene", "get-exports"],
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


def test_node_remove_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node remove (issue #56): the bare --schema flag
    # — no path, no --node — short-circuits into the self-description.
    from gda.models import NodeRemoveParams, NodeRemoveResult

    result = CliRunner().invoke(app, ["node", "remove", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeRemoveParams.model_json_schema()
    assert doc["output"] == NodeRemoveResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    node_description = doc["input"]["properties"]["node"]["description"]
    assert "scene root" in node_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_connect_signal_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node connect-signal (issue #57): the bare
    # --schema flag short-circuits into the self-description. The `from`/`to`
    # params document the root-relative node-path addressing agents must use,
    # and the wire key for the source is `from` (the .tscn [connection] key),
    # not the model's Python field name.
    from gda.models import NodeConnectSignalParams, NodeConnectSignalResult

    result = CliRunner().invoke(app, ["node", "connect-signal", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeConnectSignalParams.model_json_schema()
    assert doc["output"] == NodeConnectSignalResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The four connection parts, addressed as `from`/`signal`/`to`/`method`.
    assert set(doc["input"]["properties"]) == {
        "path",
        "from",
        "signal",
        "to",
        "method",
    }
    assert "scene root" in doc["input"]["properties"]["from"]["description"]
    assert "scene root" in doc["input"]["properties"]["to"]["description"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_duplicate_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node duplicate (issue #56): the bare --schema
    # flag — no path, no --node — short-circuits into the self-description.
    from gda.models import NodeDuplicateParams, NodeDuplicateResult

    result = CliRunner().invoke(app, ["node", "duplicate", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeDuplicateParams.model_json_schema()
    assert doc["output"] == NodeDuplicateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    node_description = doc["input"]["properties"]["node"]["description"]
    assert "scene root" in node_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_move_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node move (issue #56): the bare --schema flag —
    # no path, no --node, no --to — short-circuits into the self-description. The
    # cyclic-target rule is documented in the contract itself.
    from gda.models import NodeMoveParams, NodeMoveResult

    result = CliRunner().invoke(app, ["node", "move", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeMoveParams.model_json_schema()
    assert doc["output"] == NodeMoveResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    node_description = doc["input"]["properties"]["node"]["description"]
    assert "scene root" in node_description
    to_description = doc["input"]["properties"]["to"]["description"]
    assert "cyclic" in to_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_disconnect_signal_schema_emits_model_derived_contract_without_other_args():
    from gda.models import (
        NodeDisconnectSignalParams,
        NodeDisconnectSignalResult,
    )

    result = CliRunner().invoke(app, ["node", "disconnect-signal", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeDisconnectSignalParams.model_json_schema()
    assert doc["output"] == NodeDisconnectSignalResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert set(doc["input"]["properties"]) == {
        "path",
        "from",
        "signal",
        "to",
        "method",
    }
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_node_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each node command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issues
    # #53/#55/#56/#57).
    from tests.support import (
        NODE_ADD_RESULT as ADD_RESULT,
        NODE_CONNECT_RESULT as CONNECT_RESULT,
        NODE_DUPLICATE_RESULT as DUPLICATE_RESULT,
        NODE_GET_RESULT as GET_RESULT,
        NODE_LIST_RESULT as LIST_RESULT,
        NODE_MOVE_RESULT as MOVE_RESULT,
        NODE_REMOVE_RESULT as REMOVE_RESULT,
        NODE_SET_RESULT as SET_RESULT,
    )

    add_doc = json.loads(CliRunner().invoke(app, ["node", "add", "--schema"]).stdout)
    list_doc = json.loads(CliRunner().invoke(app, ["node", "list", "--schema"]).stdout)
    get_doc = json.loads(CliRunner().invoke(app, ["node", "get", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["node", "set", "--schema"]).stdout)
    remove_doc = json.loads(
        CliRunner().invoke(app, ["node", "remove", "--schema"]).stdout
    )
    duplicate_doc = json.loads(
        CliRunner().invoke(app, ["node", "duplicate", "--schema"]).stdout
    )
    move_doc = json.loads(CliRunner().invoke(app, ["node", "move", "--schema"]).stdout)
    connect_doc = json.loads(
        CliRunner().invoke(app, ["node", "connect-signal", "--schema"]).stdout
    )
    disconnect_doc = json.loads(
        CliRunner().invoke(app, ["node", "disconnect-signal", "--schema"]).stdout
    )

    jsonschema.validate(instance=ADD_RESULT, schema=add_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=SET_RESULT, schema=set_doc["output"])
    jsonschema.validate(instance=REMOVE_RESULT, schema=remove_doc["output"])
    jsonschema.validate(instance=DUPLICATE_RESULT, schema=duplicate_doc["output"])
    jsonschema.validate(instance=MOVE_RESULT, schema=move_doc["output"])
    jsonschema.validate(instance=CONNECT_RESULT, schema=connect_doc["output"])
    # connect and disconnect share the four-part connection shape.
    jsonschema.validate(instance=CONNECT_RESULT, schema=disconnect_doc["output"])


def test_node_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (
        ["node", "add"],
        ["node", "list"],
        ["node", "get"],
        ["node", "set"],
        ["node", "remove"],
        ["node", "duplicate"],
        ["node", "move"],
        ["node", "connect-signal"],
        ["node", "disconnect-signal"],
    ):
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


def test_script_set_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for script set (issue #118): the bare --schema flag —
    # no path, no edit mode — short-circuits into the self-description, derived
    # from the same typed models that back --json. The line-range 1-based-over-
    # split rule is documented in the contract itself.
    from gda.models import ScriptSetParams, ScriptSetResult

    result = CliRunner().invoke(app, ["script", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptSetParams.model_json_schema()
    assert doc["output"] == ScriptSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "search" in doc["input"]["properties"]
    assert "start_line" in doc["input"]["properties"]
    assert "content" in doc["input"]["properties"]
    # The line-range addressing rule (1-based over the '\n'-split parts) is in
    # the contract, not just the prose.
    assert "1-based" in doc["input"]["properties"]["start_line"]["description"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_script_attach_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for script attach (issue #118): the node param
    # documents the root-relative node-path addressing agents must use.
    from gda.models import ScriptAttachParams, ScriptAttachResult

    result = CliRunner().invoke(app, ["script", "attach", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptAttachParams.model_json_schema()
    assert doc["output"] == ScriptAttachResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    node_description = doc["input"]["properties"]["node"]["description"]
    assert "scene root" in node_description
    assert "'.'" in node_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_script_validate_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ScriptValidateParams, ScriptValidateResult

    result = CliRunner().invoke(app, ["script", "validate", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptValidateParams.model_json_schema()
    assert doc["output"] == ScriptValidateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "valid" in doc["output"]["properties"]
    assert "diagnostics" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_script_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each script command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issues #110, #117).
    from tests.support import (
        SCRIPT_CREATE_RESULT as CREATE_RESULT,
        SCRIPT_GET_RESULT as GET_RESULT,
        SCRIPT_LIST_RESULT as LIST_RESULT,
        SCRIPT_SET_RESULT as SET_RESULT,
    )

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
    set_doc = json.loads(CliRunner().invoke(app, ["script", "set", "--schema"]).stdout)
    attach_doc = json.loads(
        CliRunner().invoke(app, ["script", "attach", "--schema"]).stdout
    )
    validate_doc = json.loads(
        CliRunner().invoke(app, ["script", "validate", "--schema"]).stdout
    )

    jsonschema.validate(instance=CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    # A sample delete payload, shaped as the script-delete operation emits it.
    jsonschema.validate(
        instance={"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
        schema=delete_doc["output"],
    )
    jsonschema.validate(instance=SET_RESULT, schema=set_doc["output"])
    # Sample attach / validate payloads, shaped as the operations emit them.
    jsonschema.validate(
        instance={
            "scene_path": "res://main.tscn",
            "node": "Hero",
            "script": "res://hero.gd",
            "class_name": "Hero",
        },
        schema=attach_doc["output"],
    )
    jsonschema.validate(
        instance={
            "path": "res://broken.gd",
            "valid": False,
            "error_string": "Parse error.",
            "diagnostics": [{"line": 3, "column": None, "message": "Parse Error: ..."}],
        },
        schema=validate_doc["output"],
    )


def test_resource_uid_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for resource uid (issue #113): the bare --schema
    # flag — no target, no --project — short-circuits into the self-description,
    # derived from the same typed models that back --json.
    from gda.models import ResourceUidParams, ResourceUidResult

    result = CliRunner().invoke(app, ["resource", "uid", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceUidParams.model_json_schema()
    assert doc["output"] == ResourceUidResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "target" in doc["input"]["properties"]
    assert {"queried", "uid", "path"} <= set(doc["output"]["properties"])
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_resource_uid_results_validate_against_emitted_output_schema():
    # A sample --json payload of resource uid satisfies the contract its --schema
    # emits — the other half of the ADR-0004 hard gate (issue #113). Both
    # directions share one result shape, so one sample covers them.
    from tests.support import PATH_TO_UID_RESULT, UID_TO_PATH_RESULT

    doc = json.loads(CliRunner().invoke(app, ["resource", "uid", "--schema"]).stdout)

    jsonschema.validate(instance=UID_TO_PATH_RESULT, schema=doc["output"])
    jsonschema.validate(instance=PATH_TO_UID_RESULT, schema=doc["output"])


def test_resource_uid_schema_spawns_no_godot(monkeypatch):
    # --schema is local introspection: resource uid must short-circuit before any
    # engine path, exactly like the other groups' schema gate.
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    result = CliRunner().invoke(app, ["resource", "uid", "--schema"])

    assert result.exit_code == 0
    assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


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
        ["script", "set"],
        ["script", "attach"],
        ["script", "validate"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_resource_create_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for the resource group (issue #112): the bare
    # --schema flag — no path, no --type — short-circuits into the
    # self-description, derived from the same typed models that back --json.
    from gda.models import ResourceCreateParams, ResourceCreateResult

    result = CliRunner().invoke(app, ["resource", "create", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceCreateParams.model_json_schema()
    assert doc["output"] == ResourceCreateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "type" in doc["input"]["properties"]
    assert "type" in doc["output"]["properties"]
    assert "created_dirs" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_find_references_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for project find-references (issue #116): the bare
    # --schema flag — no target — short-circuits into the self-description,
    # derived from the same typed models that back --json. The target param
    # documents the res://-path-or-class_name addressing agents must use.
    from gda.models import (
        ProjectFindReferencesParams,
        ProjectFindReferencesResult,
    )

    result = CliRunner().invoke(app, ["project", "find-references", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectFindReferencesParams.model_json_schema()
    assert doc["output"] == ProjectFindReferencesResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "target" in doc["input"]["properties"]
    assert "references" in doc["output"]["properties"]
    target_description = doc["input"]["properties"]["target"]["description"]
    assert "class_name" in target_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_export_list_schema_emits_model_derived_contract_without_a_project():
    # The ADR-0004 hard gate for export list (issue #114): the bare --schema flag
    # — no --project — short-circuits into the self-description, derived from the
    # same typed models that back --json. export list takes no operation params,
    # so its input schema is trivially empty (the project is process context,
    # ADR-0006), exactly like scene list / script list.
    from gda.models import ExportListParams, ExportListResult

    result = CliRunner().invoke(app, ["export", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ExportListParams.model_json_schema()
    assert doc["output"] == ExportListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_dependencies_schema_emits_model_derived_contract_without_a_project():
    # dependencies takes no operation params — the project is process context
    # (ADR-0006) — so its input schema is trivially empty, exactly like scene list.
    from gda.models import ProjectDependenciesParams, ProjectDependenciesResult

    result = CliRunner().invoke(app, ["project", "dependencies", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectDependenciesParams.model_json_schema()
    assert doc["output"] == ProjectDependenciesResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_resource_get_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ResourceGetParams, ResourceGetResult

    result = CliRunner().invoke(app, ["resource", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceGetParams.model_json_schema()
    assert doc["output"] == ResourceGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "properties" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_resource_set_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for resource set (issue #120): the bare --schema flag
    # — no path, no --property/--value — short-circuits into the self-description,
    # derived from the same typed models that back --json. The value param
    # documents the type-coercion contract agents must rely on.
    from gda.models import ResourceSetParams, ResourceSetResult

    result = CliRunner().invoke(app, ["resource", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceSetParams.model_json_schema()
    assert doc["output"] == ResourceSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    assert "property" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_resource_delete_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for resource delete (issue #120): the bare --schema
    # flag — no path — short-circuits into the self-description.
    from gda.models import ResourceDeleteParams, ResourceDeleteResult

    result = CliRunner().invoke(app, ["resource", "delete", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceDeleteParams.model_json_schema()
    assert doc["output"] == ResourceDeleteResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "type" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_resource_set_delete_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each new resource command satisfies the contract
    # its --schema emits (the other half of the ADR-0004 hard gate, issue #120).
    from tests.support import (
        RESOURCE_DELETE_RESULT as DELETE_RESULT,
        RESOURCE_SET_RESULT as SET_RESULT,
    )

    set_doc = json.loads(
        CliRunner().invoke(app, ["resource", "set", "--schema"]).stdout
    )
    delete_doc = json.loads(
        CliRunner().invoke(app, ["resource", "delete", "--schema"]).stdout
    )

    jsonschema.validate(instance=SET_RESULT, schema=set_doc["output"])
    jsonschema.validate(instance=DELETE_RESULT, schema=delete_doc["output"])


def test_project_find_unused_resources_schema_emits_model_derived_contract():
    from gda.models import (
        ProjectFindUnusedResourcesParams,
        ProjectFindUnusedResourcesResult,
    )

    result = CliRunner().invoke(app, ["project", "find-unused-resources", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectFindUnusedResourcesParams.model_json_schema()
    assert doc["output"] == ProjectFindUnusedResourcesResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    assert "unused" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_export_get_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for export get (issue #114): the bare --schema flag —
    # no --preset — short-circuits into the self-description. The preset param
    # documents name-based addressing, and the output advertises the
    # template-readiness fields agents check before an export run.
    from gda.models import ExportGetParams, ExportGetResult

    result = CliRunner().invoke(app, ["export", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ExportGetParams.model_json_schema()
    assert doc["output"] == ExportGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "preset" in doc["input"]["properties"]
    assert "templates_installed" in doc["output"]["properties"]
    assert "templates_version" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_statistics_schema_emits_model_derived_contract():
    from gda.models import ProjectStatisticsParams, ProjectStatisticsResult

    result = CliRunner().invoke(app, ["project", "statistics", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectStatisticsParams.model_json_schema()
    assert doc["output"] == ProjectStatisticsResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    for key in ("total_files", "total_lines", "autoloads", "plugins"):
        assert key in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_resource_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each resource command satisfies the contract
    # its --schema emits (the other half of the ADR-0004 hard gate, issue #112).
    from tests.support import (
        RESOURCE_CREATE_RESULT as CREATE_RESULT,
        RESOURCE_GET_RESULT as GET_RESULT,
    )

    create_doc = json.loads(
        CliRunner().invoke(app, ["resource", "create", "--schema"]).stdout
    )
    get_doc = json.loads(
        CliRunner().invoke(app, ["resource", "get", "--schema"]).stdout
    )

    jsonschema.validate(instance=CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])


def test_sample_export_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each export command satisfies the contract its
    # --schema emits (the other half of the ADR-0004 hard gate, issue #114).
    from tests.support import (
        EXPORT_GET_RESULT as GET_RESULT,
        EXPORT_LIST_RESULT as LIST_RESULT,
    )

    list_doc = json.loads(
        CliRunner().invoke(app, ["export", "list", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["export", "get", "--schema"]).stdout)

    jsonschema.validate(instance=LIST_RESULT, schema=list_doc["output"])
    jsonschema.validate(instance=GET_RESULT, schema=get_doc["output"])


def test_sample_project_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each project analysis command satisfies the
    # contract its --schema emits (the other half of the ADR-0004 hard gate).
    from tests.support import (
        DEPENDENCIES_RESULT,
        FIND_REFERENCES_RESULT,
        STATISTICS_RESULT,
        UNUSED_RESULT,
    )

    refs_doc = json.loads(
        CliRunner().invoke(app, ["project", "find-references", "--schema"]).stdout
    )
    deps_doc = json.loads(
        CliRunner().invoke(app, ["project", "dependencies", "--schema"]).stdout
    )
    unused_doc = json.loads(
        CliRunner().invoke(app, ["project", "find-unused-resources", "--schema"]).stdout
    )
    stats_doc = json.loads(
        CliRunner().invoke(app, ["project", "statistics", "--schema"]).stdout
    )

    jsonschema.validate(instance=FIND_REFERENCES_RESULT, schema=refs_doc["output"])
    jsonschema.validate(instance=DEPENDENCIES_RESULT, schema=deps_doc["output"])
    jsonschema.validate(instance=UNUSED_RESULT, schema=unused_doc["output"])
    jsonschema.validate(instance=STATISTICS_RESULT, schema=stats_doc["output"])


def test_grouped_command_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (
        ["resource", "create"],
        ["resource", "get"],
        ["export", "list"],
        ["export", "get"],
        ["project", "find-references"],
        ["project", "dependencies"],
        ["project", "find-unused-resources"],
        ["project", "statistics"],
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


# --- execution kind in --schema (issue #230, ADR-0004/ADR-0012) --------------
#
# Each command's `--schema` carries its static execution `kind` (HEADLESS /
# EXPORT / LIVE), taken from the one source of truth — the command descriptor's
# `HeadlessCommand.kind` — so an agent (and gda-mcp) can branch on a command's
# channel without inferring it. The enum subclasses `str`, so the emitted JSON
# value is the lowercase string ("headless" / "export" / "live"), never the
# Python repr "ExecutionKind.HEADLESS".


def test_headless_command_schema_reports_kind_headless():
    # A default HEADLESS command (scene get routes through operations.gd) reports
    # its channel as the lowercase enum value, not the Python enum repr.
    result = CliRunner().invoke(app, ["scene", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["kind"] == "headless"


def test_export_run_command_schema_reports_kind_export():
    # `export run` is the EXPORT channel (native --export-<mode>, not the
    # operations.gd sentinel) — its schema must say so. Sibling export commands
    # (get/list) stay HEADLESS.
    result = CliRunner().invoke(app, ["export", "run", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["kind"] == "export"


def test_export_get_and_list_commands_schema_report_kind_headless():
    # Only `export run` is EXPORT; the read-only export commands are HEADLESS.
    for command in (["export", "get"], ["export", "list"]):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["kind"] == "headless"


def test_script_run_command_schema_reports_kind_script_run():
    # `script run` is the fourth execution shape (ADR-0031): a user-script
    # passthrough run — neither the operations.gd sentinel nor the native export
    # recipe — so its schema must say `script_run`, the fourth kind value. Sibling
    # script commands (get/list/validate/…) stay HEADLESS.
    result = CliRunner().invoke(app, ["script", "run", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["kind"] == "script_run"


def test_script_run_command_schema_is_model_derived():
    # `script run` self-describes like any command (ADR-0004): input/output from its
    # typed models, the uniform error envelope. Its output carries the passthrough
    # {exit_status, stdout, stderr} — the public promotion of the Raw run.
    from gda.models import ScriptRunParams, ScriptRunResult

    doc = json.loads(CliRunner().invoke(app, ["script", "run", "--schema"]).stdout)

    assert doc["input"] == ScriptRunParams.model_json_schema()
    assert doc["output"] == ScriptRunResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The success output exposes exit_status (can be non-zero on success, ADR-0031).
    assert set(doc["output"]["properties"]) == {"exit_status", "stdout", "stderr"}
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_live_command_schema_reports_kind_live_without_a_daemon():
    # `game tree` is a LIVE command served through gda-daemon — but `--schema` is
    # intercepted in parse_args before any execution, so it self-describes with
    # NO daemon running, reporting its channel as "live".
    result = CliRunner().invoke(app, ["game", "tree", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["kind"] == "live"


def test_game_get_set_schemas_report_kind_live_and_are_model_derived():
    # The LIVE runtime property commands (#220) self-describe like any command —
    # input/output from their typed models, the uniform error envelope, kind=live.
    from gda.models import (
        GameGetParams,
        GameGetResult,
        GameSetParams,
        GameSetResult,
    )

    get_doc = json.loads(CliRunner().invoke(app, ["game", "get", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["game", "set", "--schema"]).stdout)

    assert get_doc["kind"] == set_doc["kind"] == "live"
    assert get_doc["input"] == GameGetParams.model_json_schema()
    assert get_doc["output"] == GameGetResult.model_json_schema()
    assert set_doc["input"] == GameSetParams.model_json_schema()
    assert set_doc["output"] == GameSetResult.model_json_schema()
    assert get_doc["error"] == set_doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The runtime-node param documents the absolute-path addressing agents must use.
    assert "absolute" in get_doc["input"]["properties"]["node"]["description"]
    assert "coerce" in set_doc["input"]["properties"]["value"]["description"].lower()
    jsonschema.Draft202012Validator.check_schema(get_doc["input"])
    jsonschema.Draft202012Validator.check_schema(get_doc["output"])
    jsonschema.Draft202012Validator.check_schema(set_doc["input"])
    jsonschema.Draft202012Validator.check_schema(set_doc["output"])


def test_sample_game_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each game command satisfies the contract its
    # --schema emits (the ADR-0004 hard gate for the LIVE game group, #220).
    from tests.support import (
        GAME_GET_RESULT,
        GAME_SET_RESULT,
        GAME_TREE_RESULT,
    )

    tree_doc = json.loads(CliRunner().invoke(app, ["game", "tree", "--schema"]).stdout)
    get_doc = json.loads(CliRunner().invoke(app, ["game", "get", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["game", "set", "--schema"]).stdout)

    jsonschema.validate(instance=GAME_TREE_RESULT, schema=tree_doc["output"])
    jsonschema.validate(instance=GAME_GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=GAME_SET_RESULT, schema=set_doc["output"])


def test_perf_commands_schema_report_kind_live_and_are_model_derived():
    # The LIVE perf commands (#223) self-describe like any command — input/output
    # contracts derived from their models, plus the LIVE execution kind (ADR-0017).
    monitors_doc = json.loads(
        CliRunner().invoke(app, ["perf", "monitors", "--schema"]).stdout
    )
    monitor_doc = json.loads(
        CliRunner().invoke(app, ["perf", "monitor", "--schema"]).stdout
    )

    for doc in (monitors_doc, monitor_doc):
        assert "input" in doc and "output" in doc
        assert doc["kind"] == "live"


def test_sample_perf_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each perf command satisfies the contract its
    # --schema emits (the ADR-0004 hard gate for the LIVE perf group, #223).
    from tests.support import (
        PERF_MONITOR_PROPERTY_RESULT,
        PERF_MONITOR_SIGNAL_RESULT,
        PERF_MONITORS_RESULT,
    )

    monitors_doc = json.loads(
        CliRunner().invoke(app, ["perf", "monitors", "--schema"]).stdout
    )
    monitor_doc = json.loads(
        CliRunner().invoke(app, ["perf", "monitor", "--schema"]).stdout
    )

    jsonschema.validate(instance=PERF_MONITORS_RESULT, schema=monitors_doc["output"])
    jsonschema.validate(
        instance=PERF_MONITOR_PROPERTY_RESULT, schema=monitor_doc["output"]
    )
    jsonschema.validate(
        instance=PERF_MONITOR_SIGNAL_RESULT, schema=monitor_doc["output"]
    )


def test_input_commands_schema_report_kind_live_and_are_model_derived():
    # The LIVE input commands (#221) self-describe like any command — input/output
    # contracts derived from their models, plus the LIVE execution kind (ADR-0017).
    docs = [
        json.loads(CliRunner().invoke(app, [*cmd, "--schema"]).stdout)
        for cmd in (
            ["input", "key"],
            ["input", "mouse-click"],
            ["input", "mouse-move"],
            ["input", "action"],
            ["input", "sequence"],
        )
    ]
    for doc in docs:
        assert "input" in doc and "output" in doc
        assert doc["error"] == GdaErrorEnvelope.model_json_schema()
        assert doc["kind"] == "live"
        jsonschema.Draft202012Validator.check_schema(doc["input"])
        jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_input_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each input command satisfies the contract its
    # --schema emits (the ADR-0004 hard gate for the LIVE input group, #221).
    from tests.support import (
        INPUT_ACTION_RESULT,
        INPUT_KEY_RESULT,
        INPUT_MOUSE_CLICK_RESULT,
        INPUT_MOUSE_MOVE_RESULT,
        INPUT_SEQUENCE_RESULT,
    )

    key_doc = json.loads(CliRunner().invoke(app, ["input", "key", "--schema"]).stdout)
    click_doc = json.loads(
        CliRunner().invoke(app, ["input", "mouse-click", "--schema"]).stdout
    )
    move_doc = json.loads(
        CliRunner().invoke(app, ["input", "mouse-move", "--schema"]).stdout
    )
    action_doc = json.loads(
        CliRunner().invoke(app, ["input", "action", "--schema"]).stdout
    )
    seq_doc = json.loads(
        CliRunner().invoke(app, ["input", "sequence", "--schema"]).stdout
    )

    jsonschema.validate(instance=INPUT_KEY_RESULT, schema=key_doc["output"])
    jsonschema.validate(instance=INPUT_MOUSE_CLICK_RESULT, schema=click_doc["output"])
    jsonschema.validate(instance=INPUT_MOUSE_MOVE_RESULT, schema=move_doc["output"])
    jsonschema.validate(instance=INPUT_ACTION_RESULT, schema=action_doc["output"])
    jsonschema.validate(instance=INPUT_SEQUENCE_RESULT, schema=seq_doc["output"])


def test_schema_kind_is_identical_via_argv_and_params_json_forms():
    # `--schema` is intercepted at the same single emission point for both the
    # argv form and the `--params-json` form (the --schema check runs first), so
    # the emitted `kind` must be byte-identical between the two — proving the one
    # source of truth is threaded through, not duplicated per path.
    argv_doc = json.loads(CliRunner().invoke(app, ["scene", "get", "--schema"]).stdout)
    params_json_doc = json.loads(
        CliRunner()
        .invoke(app, ["scene", "get", "--params-json", "{}", "--schema"])
        .stdout
    )

    assert argv_doc["kind"] == params_json_doc["kind"] == "headless"
    # The whole contract is identical across the two forms, not just `kind`.
    assert argv_doc == params_json_doc


# --- live-stack constraints in --schema (issue #233, ADR-0004/ADR-0021) ------
#
# Every command that depends on gda's daemon/live stack carries a structured
# `constraints` field — the platform set (macOS/Linux, UDS) and, where the
# command launches/uses the engine, the Godot-4.6+ floor (ADR-0021) — sourced
# from the single `live_stack_constraints` predicate both emission paths share,
# so help/manifest prose and the structured field never drift. Commands with no
# live-stack dependence carry `null`.


def test_live_command_schema_reports_live_stack_constraints():
    # `game tree` is a LIVE command (kind=live): it both runs on UDS-only
    # platforms and uses the engine, so it carries the full constraint —
    # platforms + the Godot-4.6+ floor.
    result = CliRunner().invoke(app, ["game", "tree", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["constraints"] == {
        "platforms": ["linux", "macos"],
        "min_godot_version": "4.6",
    }


def test_daemon_start_schema_carries_constraints_despite_kind_headless():
    # `daemon start` is kind=headless (it runs the process-management recipe, not
    # the engine sentinel) but it launches the engine session, so it is
    # live-stack-dependent and carries the FULL constraint — keying purely on
    # kind==LIVE would have left it prose-only. (#233, PR #232 recheck.)
    result = CliRunner().invoke(app, ["daemon", "start", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["kind"] == "headless"
    assert doc["constraints"] == {
        "platforms": ["linux", "macos"],
        "min_godot_version": "4.6",
    }


def test_daemon_stop_and_status_schema_carry_platforms_but_null_version():
    # `daemon stop` / `daemon status` only talk to an already-running daemon over
    # UDS — they never launch the engine — so they carry the uniform platform set
    # but a NULL min_godot_version: the version floor applies only where a command
    # uses the engine (#233).
    for command in (["daemon", "stop"], ["daemon", "status"]):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0, result.stdout
        doc = json.loads(result.stdout)
        assert doc["constraints"] == {
            "platforms": ["linux", "macos"],
            "min_godot_version": None,
        }


def test_plain_headless_and_export_commands_carry_null_constraints():
    # A plain headless domain op (`scene get`) and the EXPORT command (`export
    # run`) have no live-stack dependence, so `constraints` is null — mirroring
    # how `kind` is null for a backing-less self-description (#233).
    for command in (["scene", "get"], ["export", "run"]):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0, result.stdout
        doc = json.loads(result.stdout)
        assert doc["constraints"] is None, command


def test_schema_constraints_are_identical_via_argv_and_params_json_forms():
    # `--schema` is intercepted at the same single emission point for both the
    # argv and the `--params-json` forms, so the emitted `constraints` must be
    # byte-identical across the two — proving the one predicate is threaded
    # through, not duplicated per path (#233). Use a LIVE command so the field is
    # populated, not null.
    argv_doc = json.loads(CliRunner().invoke(app, ["game", "tree", "--schema"]).stdout)
    params_json_doc = json.loads(
        CliRunner()
        .invoke(app, ["game", "tree", "--params-json", "{}", "--schema"])
        .stdout
    )

    assert argv_doc["constraints"] == params_json_doc["constraints"]
    # The whole contract is identical across the two forms, not just constraints.
    assert argv_doc == params_json_doc


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


def test_shader_create_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for the shader group (issue #115): the bare --schema
    # flag — no path — short-circuits into the self-description, derived from the
    # same typed models that back --json.
    from gda.models import ShaderCreateParams, ShaderCreateResult

    result = CliRunner().invoke(app, ["shader", "create", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ShaderCreateParams.model_json_schema()
    assert doc["output"] == ShaderCreateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "content" in doc["input"]["properties"]
    assert "shader_type" in doc["input"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_shader_get_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ShaderGetParams, ShaderGetResult

    result = CliRunner().invoke(app, ["shader", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ShaderGetParams.model_json_schema()
    assert doc["output"] == ShaderGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "source" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_shader_set_schema_emits_model_derived_contract_without_other_args():
    # The shader set edit-mode interface is the script set interface reused
    # (issue #115); the line-range 1-based rule is documented in the contract.
    from gda.models import ShaderSetParams, ShaderSetResult

    result = CliRunner().invoke(app, ["shader", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ShaderSetParams.model_json_schema()
    assert doc["output"] == ShaderSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "search" in doc["input"]["properties"]
    assert "start_line" in doc["input"]["properties"]
    assert "content" in doc["input"]["properties"]
    assert "1-based" in doc["input"]["properties"]["start_line"]["description"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_theme_create_schema_emits_model_derived_contract_without_other_args():
    from gda.models import ThemeCreateParams, ThemeCreateResult

    result = CliRunner().invoke(app, ["theme", "create", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ThemeCreateParams.model_json_schema()
    assert doc["output"] == ThemeCreateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert "type" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_sample_asset_file_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each asset-file command satisfies the contract
    # its --schema emits (the other half of the ADR-0004 hard gate, issue #115).
    from tests.support import (
        SHADER_CREATE_RESULT,
        SHADER_GET_RESULT,
        SHADER_SET_RESULT,
        THEME_CREATE_RESULT,
    )

    create_doc = json.loads(
        CliRunner().invoke(app, ["shader", "create", "--schema"]).stdout
    )
    get_doc = json.loads(CliRunner().invoke(app, ["shader", "get", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["shader", "set", "--schema"]).stdout)
    theme_doc = json.loads(
        CliRunner().invoke(app, ["theme", "create", "--schema"]).stdout
    )

    jsonschema.validate(instance=SHADER_CREATE_RESULT, schema=create_doc["output"])
    jsonschema.validate(instance=SHADER_GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=SHADER_SET_RESULT, schema=set_doc["output"])
    jsonschema.validate(instance=THEME_CREATE_RESULT, schema=theme_doc["output"])


def test_asset_file_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    for command in (
        ["shader", "create"],
        ["shader", "get"],
        ["shader", "set"],
        ["theme", "create"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}
