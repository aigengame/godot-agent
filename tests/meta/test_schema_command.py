"""`gda <command> --schema` self-description (issue #4, ADR-0004).

`--schema` is a local, no-Godot introspection flag: it derives the command's
input/output JSON Schemas from the same typed models that back `--json` and
prints them to stdout. It spawns no Godot process, so these are unit tests only.
"""

import json

import jsonschema
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.meta import InfoParams
from gda.models import EngineVersion, GdaErrorEnvelope
from gda.runner import RunResult
from tests.support import VERSION_INFO


def _assert_json_container_number_rule(description: str) -> None:
    lower = description.lower()
    assert "json integer" in lower
    assert "json float" in lower


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
    # `output` → output_schema (success) and `error` → the is_error channel.
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()


def test_the_published_error_schema_declares_the_optional_evidence_key():
    # #687 (the ADR-0004 amendment): the typed evidence must be DISCOVERABLE, not
    # only present at runtime — this repo's reviews have repeatedly caught a runtime
    # rule the machine contract did not carry. Pinned on the emitted document rather
    # than on the model, since the emitted document is what an agent reads.
    result = CliRunner().invoke(app, ["info", "--schema"])

    doc = json.loads(result.stdout)
    error = doc["error"]["$defs"]["GdaError"]
    assert "evidence" in error["properties"]
    # OPTIONAL, on the axis `probe` and `hint` established: a consumer must not be
    # made to expect a key that most failures never carry. (`diagnostics` has a
    # default and so is not required either; the three that ARE are the stable trio
    # ADR-0004 fixes.)
    assert set(error["required"]) == {"category", "code", "message"}
    # And its value shape is published inline, so the fields are discoverable too —
    # a bare `object` would leave an agent guessing which facts it may find.
    evidence = doc["error"]["$defs"]["FailureEvidence"]
    assert set(evidence["properties"]) == {
        "exit_status",
        "elapsed_seconds",
        "timeout_seconds",
        "termination_phase",
        "script_errors",
        # The three coordinates of a `target_outside_project` refusal
        # (#697/#763): where the target is, which project gda used, and which
        # one owns it.
        "target_location",
        "project_root",
        "owning_project",
        # The two export-templates directories a --user-data-root redirect puts at
        # odds (#840): the one this run checked, and the host one holding the
        # templates it could not see.
        "templates_root_checked",
        "templates_root_host",
    }
    assert doc["error"]["$defs"]["TerminationPhase"]["enum"] == [
        "launched",
        "output_seen",
        "aborted_on_error",
    ]


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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    from gda.commands.scene import SceneCreateParams, SceneCreateResult

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
    from gda.commands.scene import SceneGetParams, SceneGetResult

    result = CliRunner().invoke(app, ["scene", "get", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneGetParams.model_json_schema()
    assert doc["output"] == SceneGetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    scene_node = doc["output"]["$defs"]["SceneNode"]["properties"]
    assert "instanced scene" in scene_node["type"]["description"]
    assert "referenced PackedScene path" in scene_node["instance_path"]["description"]
    assert "missing" in scene_node["instance_status"]["description"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_get_exports_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for scene get-exports (issue #58): the bare --schema
    # flag — no path — short-circuits into the self-description, derived from the
    # same typed models that back --json.
    from gda.commands.scene import SceneGetExportsParams, SceneGetExportsResult

    result = CliRunner().invoke(app, ["scene", "get-exports", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneGetExportsParams.model_json_schema()
    assert doc["output"] == SceneGetExportsResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The per-export value is a listed ADR-0035 read surface: its description
    # names the recursive value projection and the emitted schema carries the
    # named Object-projection shapes — a stale scalar-only doc fails here.
    export_value = doc["output"]["$defs"]["SceneExport"]["properties"]["value"]
    assert "value projection" in export_value["description"]
    assert set(export_value["$defs"]) == {
        "ReferenceProjection",
        "TextureProjection",
        "InlineValueProjection",
    }
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_list_schema_emits_model_derived_contract_without_a_project():
    # The ADR-0004 hard gate for scene list (issue #54): the bare --schema flag
    # — no --project — short-circuits into the self-description, derived from the
    # same typed models that back --json. scene list takes no operation params,
    # so its input schema is trivially empty (the project is process context,
    # ADR-0006), exactly like info.
    from gda.commands.scene import SceneListParams, SceneListResult

    result = CliRunner().invoke(app, ["scene", "list", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == SceneListParams.model_json_schema()
    assert doc["output"] == SceneListResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    assert doc["input"].get("properties", {}) == {}
    listed_scene = doc["output"]["$defs"]["ListedScene"]["properties"]
    assert "inherited/instanced root" in listed_scene["root_type"]["description"]
    assert (
        "referenced PackedScene path"
        in listed_scene["root_instance_path"]["description"]
    )
    assert "missing" in listed_scene["root_instance_status"]["description"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_scene_delete_schema_emits_model_derived_contract_without_other_args():
    from gda.commands.scene import SceneDeleteParams, SceneDeleteResult

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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    from gda.commands.node import NodeAddParams, NodeAddResult

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
    index_description = doc["input"]["properties"]["index"]["description"]
    assert "0-based" in index_description
    assert "Omit to append" in index_description
    assert "child_count" in index_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_list_schema_emits_model_derived_contract_without_other_args():
    from gda.commands.node import NodeListParams, NodeListResult

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
    from gda.commands.node import NodeGetParams, NodeGetResult

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
    from gda.commands.node import NodeSetParams, NodeSetResult

    result = CliRunner().invoke(app, ["node", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == NodeSetParams.model_json_schema()
    assert doc["output"] == NodeSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    _assert_json_container_number_rule(value_description)
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_remove_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for node remove (issue #56): the bare --schema flag
    # — no path, no --node — short-circuits into the self-description.
    from gda.commands.node import NodeRemoveParams, NodeRemoveResult

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
    from gda.commands.node import NodeConnectSignalParams, NodeConnectSignalResult

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
    from gda.commands.node import NodeDuplicateParams, NodeDuplicateResult

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
    from gda.commands.node import NodeMoveParams, NodeMoveResult

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
    index_description = doc["input"]["properties"]["index"]["description"]
    assert "0-based" in index_description
    assert "same-parent move is a no-op" in index_description
    assert "target_child_count" in index_description
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_node_disconnect_signal_schema_emits_model_derived_contract_without_other_args():
    from gda.commands.node import (
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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    from gda.commands.script import ScriptCreateParams, ScriptCreateResult

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
    from gda.commands.script import ScriptGetParams, ScriptGetResult

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
    from gda.commands.script import ScriptListParams, ScriptListResult

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
    from gda.commands.script import ScriptDeleteParams, ScriptDeleteResult

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
    from gda.commands.script import ScriptSetParams, ScriptSetResult

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
    from gda.commands.script import ScriptAttachParams, ScriptAttachResult

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
    from gda.commands.script import ScriptValidateParams, ScriptValidateResult

    result = CliRunner().invoke(app, ["script", "validate", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ScriptValidateParams.model_json_schema()
    assert doc["output"] == ScriptValidateResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The batch contract (#663): repeated paths in, one aggregate verdict plus one
    # entry per script out.
    assert doc["input"]["properties"]["paths"]["type"] == "array"
    assert "all_scripts" in doc["input"]["properties"]
    assert "valid" in doc["output"]["properties"]
    assert doc["output"]["properties"]["scripts"]["type"] == "array"
    assert "diagnostics" in doc["output"]["$defs"]["ValidatedScript"]["properties"]
    # project_root is REQUIRED and nullable (#658): every emitted verdict carries
    # the key, so an agent reads it unconditionally rather than probing for it.
    assert "project_root" in doc["output"]["required"]
    assert doc["output"]["properties"]["project_root"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
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
    # The validate sample carries project_root: it is REQUIRED on the public
    # result (#658), because the CLI stamps the ADR-0006-resolved project onto
    # every emitted verdict. A payload without it is the engine's internal
    # sentinel half, not something gda ever emits. The BATCH shape (#663) is the
    # only shape: one aggregate verdict over one entry per validated script.
    jsonschema.validate(
        instance={
            "valid": False,
            "scripts": [
                {
                    "path": "res://ok.gd",
                    "valid": True,
                    "error_string": None,
                    "diagnostics": [],
                },
                {
                    "path": "res://broken.gd",
                    "valid": False,
                    "error_string": "Parse error.",
                    "diagnostics": [
                        {"line": 3, "column": None, "message": "Parse Error: ..."}
                    ],
                },
            ],
            "project_root": "/work/game",
        },
        schema=validate_doc["output"],
    )
    # ...and a projectless batch of one still satisfies it, since the field is
    # nullable and the shape does not vary with the batch size.
    jsonschema.validate(
        instance={
            "valid": True,
            "scripts": [
                {
                    "path": "/work/standalone.gd",
                    "valid": True,
                    "error_string": None,
                    "diagnostics": [],
                }
            ],
            "project_root": None,
        },
        schema=validate_doc["output"],
    )


def test_resource_uid_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for resource uid (issue #113): the bare --schema
    # flag — no target, no --project — short-circuits into the self-description,
    # derived from the same typed models that back --json.
    from gda.commands.resource import ResourceUidParams, ResourceUidResult

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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

    result = CliRunner().invoke(app, ["resource", "uid", "--schema"])

    assert result.exit_code == 0
    assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_script_schema_spawns_no_godot(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    from gda.commands.resource import ResourceCreateParams, ResourceCreateResult

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
    from gda.commands.project import (
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
    from gda.commands.export import ExportListParams, ExportListResult

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
    from gda.commands.project import (
        ProjectDependenciesParams,
        ProjectDependenciesResult,
    )

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
    from gda.commands.resource import ResourceGetParams, ResourceGetResult

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
    from gda.commands.resource import ResourceSetParams, ResourceSetResult

    result = CliRunner().invoke(app, ["resource", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ResourceSetParams.model_json_schema()
    assert doc["output"] == ResourceSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    _assert_json_container_number_rule(value_description)
    assert "property" in doc["output"]["properties"]
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_project_set_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for project set: the bare --schema flag — no
    # setting/--value — short-circuits into the self-description, including the
    # shared value-coercion contract.
    from gda.commands.project import ProjectSetParams, ProjectSetResult

    result = CliRunner().invoke(app, ["project", "set", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["input"] == ProjectSetParams.model_json_schema()
    assert doc["output"] == ProjectSetResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    value_description = doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    _assert_json_container_number_rule(value_description)
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])


def test_resource_delete_schema_emits_model_derived_contract_without_other_args():
    # The ADR-0004 hard gate for resource delete (issue #120): the bare --schema
    # flag — no path — short-circuits into the self-description.
    from gda.commands.resource import ResourceDeleteParams, ResourceDeleteResult

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
    from gda.commands.project import (
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
    from gda.commands.export import ExportGetParams, ExportGetResult

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
    from gda.commands.project import (
        ProjectStatisticsParams,
        ProjectStatisticsResult,
    )

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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

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
    # {exit_status, stdout, stderr} — the public promotion of the Raw run — plus the
    # classified `diagnostics` gda reads out of the engine's stderr (#651) and the
    # canonical res:// `path` both accepted input forms converge on (#675).
    from gda.commands.script import ScriptRunParams, ScriptRunResult

    doc = json.loads(CliRunner().invoke(app, ["script", "run", "--schema"]).stdout)

    assert doc["input"] == ScriptRunParams.model_json_schema()
    assert doc["output"] == ScriptRunResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # The success output exposes exit_status (can be non-zero on success, ADR-0031)
    # and `path`, the declared schema addition of the ADR-0031 path-form amendment.
    assert set(doc["output"]["properties"]) == {
        "path",
        "exit_status",
        "stdout",
        "stderr",
        # The bounded-stdout markers (#665): full byte count, truncation flag,
        # and the spill file (required-but-nullable).
        "stdout_bytes",
        "stdout_truncated",
        "stdout_file",
        "diagnostics",
        # The launch's user-data placement (#850): where this run's `user://`
        # actually was, so a persistence failure is attributable from the result.
        "user_data_root",
        "engine_data_path",
        "log_file",
    }
    # The markers are ALWAYS present (#665): a standard consumer sees them
    # required, with the spill file required-but-nullable.
    assert {"stdout_bytes", "stdout_truncated", "stdout_file"} <= set(
        doc["output"]["required"]
    )
    spill_branches = doc["output"]["properties"]["stdout_file"]["anyOf"]
    assert {"type": "null"} in spill_branches
    # The placement's own presence rule (#850): `engine_data_path` is
    # required-but-nullable (null = the platform's variable is unset), while the
    # two root-only keys are OPTIONAL — omitted, not null, on a default run.
    required = set(doc["output"]["required"])
    assert "engine_data_path" in required
    assert {"user_data_root", "log_file"} & required == set()
    assert {"type": "null"} in doc["output"]["properties"]["engine_data_path"]["anyOf"]
    # `--strict` is a params field, so the JSON/MCP callers can opt in like argv (#651).
    # `timeout` / `completion_marker` are params for the same reason (#655): the
    # per-invocation ceiling and the opt-in early-termination marker have to be
    # reachable from a JSON/MCP caller, not only from argv (ADR-0015).
    assert set(doc["input"]["properties"]) == {
        "path",
        "strict",
        "timeout",
        "completion_marker",
    }
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


def test_game_get_rect_set_schemas_report_kind_live_and_are_model_derived():
    # The LIVE runtime property/control commands self-describe like any command —
    # input/output from their typed models, the uniform error envelope, kind=live.
    from gda.commands.game import (
        GameGetParams,
        GameGetResult,
        GameRectParams,
        GameRectResult,
        GameSetParams,
        GameSetResult,
    )

    get_doc = json.loads(CliRunner().invoke(app, ["game", "get", "--schema"]).stdout)
    rect_doc = json.loads(CliRunner().invoke(app, ["game", "rect", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["game", "set", "--schema"]).stdout)

    assert get_doc["kind"] == rect_doc["kind"] == set_doc["kind"] == "live"
    assert get_doc["input"] == GameGetParams.model_json_schema()
    assert get_doc["output"] == GameGetResult.model_json_schema()
    assert rect_doc["input"] == GameRectParams.model_json_schema()
    assert rect_doc["output"] == GameRectResult.model_json_schema()
    assert set_doc["input"] == GameSetParams.model_json_schema()
    assert set_doc["output"] == GameSetResult.model_json_schema()
    assert (
        get_doc["error"]
        == rect_doc["error"]
        == set_doc["error"]
        == GdaErrorEnvelope.model_json_schema()
    )
    # The runtime-node param documents the absolute-path addressing agents must use.
    assert "absolute" in get_doc["input"]["properties"]["node"]["description"]
    assert "absolute" in rect_doc["input"]["properties"]["node"]["description"]
    value_description = set_doc["input"]["properties"]["value"]["description"]
    assert "coerce" in value_description.lower()
    _assert_json_container_number_rule(value_description)
    jsonschema.Draft202012Validator.check_schema(get_doc["input"])
    jsonschema.Draft202012Validator.check_schema(get_doc["output"])
    jsonschema.Draft202012Validator.check_schema(rect_doc["input"])
    jsonschema.Draft202012Validator.check_schema(rect_doc["output"])
    jsonschema.Draft202012Validator.check_schema(set_doc["input"])
    jsonschema.Draft202012Validator.check_schema(set_doc["output"])


def test_sample_game_results_validate_against_emitted_output_schemas():
    # A sample --json payload of each game command satisfies the contract its
    # --schema emits (the ADR-0004 hard gate for the LIVE game group, #220).
    from tests.support import (
        GAME_GET_RESULT,
        GAME_RECT_RESULT,
        GAME_SET_RESULT,
        GAME_TREE_RESULT,
        GAME_TREE_TRUNCATED_RESULT,
    )

    tree_doc = json.loads(CliRunner().invoke(app, ["game", "tree", "--schema"]).stdout)
    get_doc = json.loads(CliRunner().invoke(app, ["game", "get", "--schema"]).stdout)
    rect_doc = json.loads(CliRunner().invoke(app, ["game", "rect", "--schema"]).stdout)
    set_doc = json.loads(CliRunner().invoke(app, ["game", "set", "--schema"]).stdout)

    jsonschema.validate(instance=GAME_TREE_RESULT, schema=tree_doc["output"])
    # The bounded read's shape is published too (#849): the optional per-node
    # `children_omitted` and the two result totals.
    jsonschema.validate(instance=GAME_TREE_TRUNCATED_RESULT, schema=tree_doc["output"])
    jsonschema.validate(instance=GAME_GET_RESULT, schema=get_doc["output"])
    jsonschema.validate(instance=GAME_RECT_RESULT, schema=rect_doc["output"])
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

    jsonschema.validate(
        instance={"kind": "snapshot", **PERF_MONITORS_RESULT},
        schema=monitors_doc["output"],
    )
    window_instance = {
        "kind": "window",
        "frames": 1,
        "max_frames": 600,
        "stats": {
            "fps": {
                "count": 1,
                "min": 60.0,
                "max": 60.0,
                "mean": 60.0,
                "p50": 60.0,
                "p95": 60.0,
            }
        },
        "samples": [{"frame": 0, "timestamp": 100, "values": {"fps": 60.0}}],
        "budget": {
            "fps": {
                "stat": "p50",
                "value": 60.0,
                "min": 60.0,
                "max": None,
                "passed": True,
            }
        },
        "passed": True,
    }
    jsonschema.validate(instance=window_instance, schema=monitors_doc["output"])
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

    click_input = docs[1]["input"]
    move_input = docs[2]["input"]
    assert (
        "engine-tracked mouse positions may remain stale"
        in (click_input["properties"]["x"]["description"])
    )
    assert (
        "engine-tracked mouse positions may remain stale"
        in (move_input["properties"]["x"]["description"])
    )
    assert (
        "event.position" in docs[1]["output"]["properties"]["position"]["description"]
    )

    sequence_input = docs[-1]["input"]
    events_description = sequence_input["properties"]["events"]["description"]
    assert "process-clock `frame`" in events_description
    assert "physics-clock `physics_frame`" in events_description
    # The event kinds are a discriminated union (#669): each kind's variant is
    # reached through the discriminator mapping rather than one flat shape.
    mapping = sequence_input["properties"]["events"]["items"]["discriminator"][
        "mapping"
    ]
    assert "mouse_button" in mapping
    variants = {
        kind: sequence_input["$defs"][ref.rsplit("/", 1)[-1]]
        for kind, ref in mapping.items()
    }
    key_props = variants["key"]["properties"]
    assert "harness/process-frame" in key_props["frame"]["description"]
    assert "physics-frame" in key_props["physics_frame"]["description"]
    assert (
        "engine-tracked mouse positions may remain stale"
        in (variants["mouse_move"]["properties"]["x"]["description"])
    )
    assert (
        "one of `pressed` or `release`"
        in variants["mouse_button"]["properties"]["pressed"]["description"]
    )


def test_sample_input_results_validate_against_emitted_output_schemas(
    monkeypatch, tmp_path
):
    # The --json payload each input command EMITS satisfies the contract its
    # --schema emits (the ADR-0004 hard gate for the LIVE input group, #221).
    # The EMITTED payload, not the harness reply it is built from: since #838 the
    # two differ — gda derives the injection route CLI-side and folds it into the
    # result — so validating the reply would no longer check what agents read.
    from tests.support import (
        INPUT_ACTION_RESULT,
        INPUT_KEY_RESULT,
        INPUT_MOUSE_CLICK_RESULT,
        INPUT_MOUSE_MOVE_RESULT,
        INPUT_SEQUENCE_RESULT,
        INPUT_TAP_ACTION_RESULT,
        inject_live_runner,
        minimal_project,
        sentinel,
    )

    project = str(minimal_project(tmp_path))
    cases = [
        (["input", "key", "Right"], INPUT_KEY_RESULT),
        (["input", "mouse-click", "100", "200"], INPUT_MOUSE_CLICK_RESULT),
        (["input", "mouse-move", "50", "60"], INPUT_MOUSE_MOVE_RESULT),
        (["input", "action", "jump"], INPUT_ACTION_RESULT),
        (["input", "tap", "--action", "jump"], INPUT_TAP_ACTION_RESULT),
        (
            [
                "input",
                "sequence",
                "--events",
                json.dumps([{"type": "action", "action": "jump"}]),
            ],
            # The reply must agree with the request it answers: gda correlates the
            # applied-event count before it publishes the request-derived phases
            # (#838), so the shared 3-event sample would be a contract_violation.
            {**INPUT_SEQUENCE_RESULT, "events": 1, "frames": 1},
        ),
    ]

    for argv, reply in cases:
        inject_live_runner(
            monkeypatch, RunResult(stdout=sentinel(reply), stderr="", exit_code=0)
        )
        emitted = CliRunner().invoke(app, [*argv, "--project", project, "--json"])
        assert emitted.exit_code == 0, emitted.stdout + emitted.stderr
        doc = json.loads(CliRunner().invoke(app, [*argv[:2], "--schema"]).stdout)
        jsonschema.validate(instance=json.loads(emitted.stdout), schema=doc["output"])


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
    from gda.commands.shader import ShaderCreateParams, ShaderCreateResult

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
    from gda.commands.shader import ShaderGetParams, ShaderGetResult

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
    from gda.commands.shader import ShaderSetParams, ShaderSetResult

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
    from gda.commands.theme import ThemeCreateParams, ThemeCreateResult

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
    monkeypatch.setattr("gda.dispatch.make_runner", boom)

    for command in (
        ["shader", "create"],
        ["shader", "get"],
        ["shader", "set"],
        ["theme", "create"],
    ):
        result = CliRunner().invoke(app, [*command, "--schema"])
        assert result.exit_code == 0
        assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


# --- argv binding in --schema (issue #669, ADR-0004/ADR-0012/ADR-0023 §2) -----
#
# GDA-DF-003: the emitted schema stated a command's required fields but not how
# to SPELL them on a command line — `screen capture` needs `--output` while
# `input mouse-click` needs positional `x y` and `input action` a positional
# ACTION it rejects as `--action`. The `argv` key answers that from the live
# Typer/Click parameters (never a hand-maintained table, ADR-0023 §2).


def _argv(command: list[str]) -> dict[str, dict]:
    """The command's ``--schema`` argv bindings, keyed by binding name."""
    result = CliRunner().invoke(app, [*command, "--schema"])
    assert result.exit_code == 0, result.stdout
    return {b["name"]: b for b in json.loads(result.stdout)["argv"]}


def test_schema_argv_names_a_required_options_spelling():
    # GDA-DF-003 case 1: `screen capture` takes its required `output` as an
    # OPTION, so the schema must publish the `--output` spelling.
    binding = _argv(["screen", "capture"])["output"]

    assert binding["kind"] == "option"
    assert binding["option"] == "--output"
    assert binding["required"] is True
    assert binding["position"] is None


def test_schema_argv_places_positional_parameters_in_order():
    # GDA-DF-003 case 2: `input mouse-click` takes `x y` POSITIONALLY — the
    # schema publishes their order, and that they carry no option spelling.
    bindings = _argv(["input", "mouse-click"])

    assert bindings["x"]["kind"] == "argument"
    assert bindings["x"]["position"] == 0
    assert bindings["x"]["option"] is None
    assert bindings["y"]["position"] == 1
    assert bindings["x"]["required"] is True


def test_schema_argv_reports_a_positional_that_has_no_option_form():
    # GDA-DF-003 case 3: `input action` requires a positional ACTION and rejects
    # `--action`; the schema says so, so no round-trip through `--help` is needed.
    bindings = _argv(["input", "action"])

    assert bindings["action"]["kind"] == "argument"
    assert bindings["action"]["position"] == 0
    assert bindings["action"]["option"] is None
    assert "--action" not in {b["option"] for b in bindings.values()}


def test_schema_argv_distinguishes_valueless_flags_from_repeatable_options():
    # Constructing argv needs two more facts a JSON Schema cannot carry: a flag
    # takes NO value (`--released`), and a repeatable option is REPEATED per
    # value (`--modifiers shift --modifiers ctrl`).
    bindings = _argv(["input", "key"])

    assert bindings["released"]["flag"] is True
    assert bindings["released"]["multiple"] is False
    assert bindings["modifiers"]["flag"] is False
    assert bindings["modifiers"]["multiple"] is True
    assert bindings["modifiers"]["option"] == "--modifiers"


def test_schema_argv_reports_a_variadic_positional_as_multiple():
    # `script validate [PATHS]...` takes any number of positional paths (#663).
    binding = _argv(["script", "validate"])["paths"]

    assert binding["kind"] == "argument"
    assert binding["multiple"] is True


def test_schema_argv_omits_the_shared_cross_cutting_flags():
    # `argv` describes the OPERATION parameters — the same set `--params-json`
    # is mutually exclusive with (ADR-0015). The cross-cutting flags every
    # command shares are not per-command information, so they stay out.
    for command in (["scene", "create"], ["input", "key"], ["export", "run"]):
        names = set(_argv(command))
        assert names.isdisjoint(
            {"json_output", "schema", "params_json", "godot", "project"}
        )


def test_schema_argv_links_a_binding_to_the_input_property_it_fills():
    # The join that closes GDA-DF-003: an agent holding a REQUIRED input property
    # can find its CLI spelling. The link is derived (never declared), so it is
    # right even where the CLI spelling differs from the Python parameter name —
    # `node add`'s `node_type` parameter is spelled `--type` and fills `type`.
    binding = _argv(["node", "add"])["node_type"]

    assert binding["option"] == "--type"
    assert binding["input_property"] == "type"

    # …and where the OPTION renames the property, the parameter carries the
    # property's name so the link still holds: `project list --all` and
    # `skill --dir` fill `include_defaults` / `install_dir`.
    assert _argv(["project", "list"])["include_defaults"]["option"] == "--all"
    assert _argv(["project", "list"])["include_defaults"]["input_property"] == (
        "include_defaults"
    )
    assert _argv(["skill"])["install_dir"]["option"] == "--dir"
    assert _argv(["skill"])["install_dir"]["input_property"] == "install_dir"


def test_an_underivable_link_is_published_as_null_rather_than_guessed():
    # `input_property` stays nullable BY CONTRACT for a parameter whose property
    # neither its name nor its long option reveals — a wrong link would read as
    # authoritative. No command on the surface is in that state (a guard in
    # test_schema_aggregate holds that), so the rule is pinned on the derivation
    # itself rather than through a command that would then have to stay broken.
    from gda.headless import _bound_property

    properties = {"include_defaults": {"type": "boolean"}}
    assert _bound_property("all_settings", "--all", properties) is None
    # The two derivations that DO resolve: by parameter name, and by the long
    # option's spelling (`--type` fills `type` from a `node_type` parameter).
    assert _bound_property("include_defaults", "--all", properties) == (
        "include_defaults"
    )
    assert _bound_property("node_type", "--type", {"type": {}}) == "type"


def test_schema_argv_covers_every_dispatch_channel():
    # Several channels bypass the sentinel `cmd.emit` (EXPORT and LIVE by kind,
    # the daemon lifecycle and screen by recipe). The binding is read off the
    # live Click parameters, so it is present on all of them, not just the
    # sentinel path.
    assert _argv(["export", "run"])["preset"]["option"] == "--preset"
    assert _argv(["daemon", "start"])["scene"]["option"] == "--scene"
    assert _argv(["game", "get"])["node"]["kind"] == "argument"
    assert _argv(["script", "run"])["path"]["kind"] == "argument"
    # A command with no operation parameters carries an empty list, not a
    # missing key.
    result = CliRunner().invoke(app, ["info", "--schema"])
    assert json.loads(result.stdout)["argv"] == []


def test_schema_argv_reports_required_despite_the_relaxed_probe_parse():
    # The `--schema` probe parses with every parameter's `required` RELAXED so a
    # bare probe succeeds (issue #36). The published binding must report the
    # DECLARED requirement, not the relaxed one.
    assert _argv(["screen", "capture"])["output"]["required"] is True
    assert _argv(["node", "connect-signal"])["from_node"]["required"] is True


def test_the_argv_derivation_covers_every_parameter_shape_on_the_surface():
    # The projection expresses a positional, an option, a valueless flag, a
    # repeated value and a JSON-encoded value (#669). Click can spell three more
    # shapes it would report WRONGLY: a `--x/--no-x` pair (the negative spelling
    # would be dropped), an n-ary option (`nargs > 1`, which is neither single nor
    # `multiple`), and a counting option (`count=True`, not a bare flag). None
    # exists today. This guard fails the moment one is introduced, so the contract
    # is extended deliberately instead of silently emitting a binding that cannot
    # be written.
    import typer as _typer

    unsupported: list[str] = []

    def walk(command, path):
        subcommands = getattr(command, "commands", None)
        if subcommands is not None:
            for name, subcommand in subcommands.items():
                walk(subcommand, [*path, name])
            return
        for param in command.params:
            where = f"{' '.join(path)}: {param.name}"
            if getattr(param, "secondary_opts", []):
                unsupported.append(f"{where} (--x/--no-x pair)")
            if getattr(param, "nargs", 1) not in (1, -1):
                unsupported.append(f"{where} (nargs={param.nargs})")
            if getattr(param, "count", False):
                unsupported.append(f"{where} (counting option)")

    walk(_typer.main.get_command(app), [])
    assert not unsupported, "argv bindings cannot express:\n" + "\n".join(unsupported)


def test_schema_argv_marks_a_json_encoded_value():
    # `input sequence` takes an ARRAY property through a single `--events` token
    # that carries its JSON. Without this key an agent reading `input` sees an
    # array and writes one token per element, which the parser rejects — the
    # encoding half of the same argv problem (#669).
    binding = _argv(["input", "sequence"])["events"]

    assert binding["json_value"] is True
    assert binding["multiple"] is False
    assert binding["option"] == "--events"
    # A repeated option carries its values one token at a time instead, so it is
    # NOT a JSON value; nor is a plain scalar.
    assert _argv(["input", "key"])["modifiers"]["json_value"] is False
    assert _argv(["screen", "capture"])["output"]["json_value"] is False


def _is_compound(spec: dict) -> bool:
    """Whether a property schema is an array/object, INCLUDING behind an anyOf."""
    if spec.get("type") in ("array", "object"):
        return True
    branches = spec.get("anyOf") or spec.get("oneOf") or []
    return any(_is_compound(branch) for branch in branches if isinstance(branch, dict))


def test_no_parameter_needs_a_json_value_the_derivation_cannot_see():
    # `json_value` is derived from the LINKED property's schema and, since #661's
    # nullable-compound `--await-events` (`list | null`), sees a compound behind
    # an `anyOf`/`oneOf` too. This guard keeps the derivation and this detector
    # agreeing: a compound shape only one of them recognizes (e.g. behind an
    # `allOf` or a `$ref`) would silently publish `json_value: false` and send an
    # agent to write its value as a plain token — it fails the moment one
    # appears, forcing the extension rather than a wrong binding. Same guard
    # shape as the unsupported-Click-shapes test above.
    import typer as _typer

    from gda.headless import command_argv_bindings

    invisible: list[str] = []

    def walk(command, path):
        subcommands = getattr(command, "commands", None)
        if subcommands is not None:
            for name, subcommand in subcommands.items():
                walk(subcommand, [*path, name])
            return
        input_model = getattr(command, "gda_input_model", None)
        if input_model is None:
            return
        properties = input_model.model_json_schema().get("properties", {})
        for binding in command_argv_bindings(command, input_model):
            spec = properties.get(binding.input_property or "")
            if not isinstance(spec, dict) or binding.multiple or binding.json_value:
                continue
            if _is_compound(spec):
                invisible.append(f"{' '.join(path)}: {binding.name}")

    walk(_typer.main.get_command(app), [])
    assert not invisible, (
        "compound properties taking one token that json_value cannot see:\n"
        + "\n".join(invisible)
    )
    # …and the detector is not blind: it recognizes the nullable-compound shape it
    # is meant to catch, so passing above means absence, not a broken predicate.
    assert _is_compound({"anyOf": [{"type": "array"}, {"type": "null"}]})
    assert not _is_compound({"type": "string"})
