"""Prompt records share the typed asset-pipeline CLI and MCP surface."""

import json

import jsonschema
import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.mcp.server import build_server
from gda_assets.api import PromptDeclarationKey, PromptOptionKey
from typing import get_args
from tests.mcp_support import FakeGdaRunner, gda_result, list_tools, schema_then


def test_prompt_prepare_is_a_projectless_typed_composite_command():
    result = CliRunner().invoke(app, ["asset-pipeline", "prompt-prepare", "--schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert schema["kind"] == "composite"
    assert schema["input"]["additionalProperties"] is False
    assert set(schema["input"]["properties"]) == {
        "record",
        "text",
        "template",
        "style",
        "variables",
        "references",
        "producer",
        "requested_options",
    }
    assert "PromptPreparation" in schema["output"]["$defs"]
    reference = next(item for item in schema["argv"] if item["option"] == "--reference")
    assert reference["input_property"] == "references"
    assert reference["multiple"] is True
    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == "asset_pipeline_prompt_prepare")
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]


def test_prompt_map_keys_and_prompt_source_are_enforced_by_cli_and_mcp_schema():
    runner = CliRunner()
    prepare = json.loads(
        runner.invoke(app, ["asset-pipeline", "prompt-prepare", "--schema"]).stdout
    )
    register = json.loads(
        runner.invoke(
            app, ["asset-pipeline", "prompt-register-output", "--schema"]
        ).stdout
    )
    option_keys = set(get_args(PromptOptionKey))
    declaration_keys = set(get_args(PromptDeclarationKey))
    assert (
        set(
            prepare["input"]["properties"]["requested_options"]["propertyNames"]["enum"]
        )
        == option_keys
    )
    assert (
        set(
            register["input"]["properties"]["caller_declarations"]["propertyNames"][
                "enum"
            ]
        )
        == declaration_keys
    )
    validator = jsonschema.Draft202012Validator(prepare["input"])
    valid = {"record": "/tmp/record", "text": "hello"}
    assert not list(validator.iter_errors(valid))
    for invalid in (
        {"record": "/tmp/record"},
        {"record": "/tmp/record", "text": None},
        {**valid, "requested_options": {"unknown": "value"}},
    ):
        assert list(validator.iter_errors(invalid))

    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == "asset_pipeline_prompt_prepare")
    assert tool.input_schema == prepare["input"]


def test_prompt_prepare_and_inspect_public_json_do_not_claim_generation(tmp_path):
    record = tmp_path / "attempt"
    runner = CliRunner()
    prepared = runner.invoke(
        app,
        [
            "asset-pipeline",
            "prompt-prepare",
            "--record",
            str(record),
            "--text",
            "A mossy stone arch",
            "--producer",
            "external-tool",
            "--requested-options",
            '{"size":"1024x1024"}',
            "--json",
        ],
    )
    inspected = runner.invoke(
        app,
        [
            "asset-pipeline",
            "prompt-inspect",
            "--params-json",
            json.dumps({"record": str(record)}),
            "--json",
        ],
    )

    assert prepared.exit_code == inspected.exit_code == 0
    first, second = json.loads(prepared.stdout), json.loads(inspected.stdout)
    assert first == second
    assert first["preparation"]["record"]["generation_status"] == "unknown"
    assert first["preparation"]["handoff"]["action"] == "external_generation_required"
    assert first["preparation"]["record"]["requested_options"] == {"size": "1024x1024"}


@pytest.mark.parametrize(
    ("command", "tool_name", "definition"),
    [
        ("prompt-inspect", "asset_pipeline_prompt_inspect", "PromptPreparation"),
        ("prompt-revise", "asset_pipeline_prompt_revise", "PromptRevision"),
        (
            "prompt-register-output",
            "asset_pipeline_prompt_register_output",
            "PromptRecord",
        ),
    ],
)
def test_each_prompt_command_has_matching_cli_and_mcp_result_schema(
    command, tool_name, definition
):
    result = CliRunner().invoke(app, ["asset-pipeline", command, "--schema"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert schema["kind"] == "composite"
    assert definition in schema["output"]["$defs"]
    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == tool_name)
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]
