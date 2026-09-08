"""Concept-reference workflows use the typed asset-pipeline surface."""

import json
from typing import get_args

import jsonschema
import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.mcp.server import build_server
from gda_assets.api import ConceptConsumer, PromptOptionKey
from tests.mcp_support import FakeGdaRunner, gda_result, list_tools, schema_then


@pytest.mark.parametrize(
    ("command", "tool_name", "definition"),
    [
        ("concept-prepare", "asset_pipeline_concept_prepare", "ConceptPreparation"),
        ("concept-select", "asset_pipeline_concept_select", "ConceptSelection"),
        ("concept-author", "asset_pipeline_concept_author", "ConceptAuthoringResult"),
    ],
)
def test_concept_commands_publish_matching_projectless_composite_schemas(
    command, tool_name, definition
):
    result = CliRunner().invoke(app, ["asset-pipeline", command, "--schema"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert schema["kind"] == "composite"
    assert schema["input"]["additionalProperties"] is False
    assert definition in schema["output"]["$defs"]

    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == tool_name)
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]


def test_concept_nested_inputs_publish_real_bounds_and_literals():
    runner = CliRunner()
    prepare = json.loads(
        runner.invoke(app, ["asset-pipeline", "concept-prepare", "--schema"]).stdout
    )
    select = json.loads(
        runner.invoke(app, ["asset-pipeline", "concept-select", "--schema"]).stdout
    )
    author = json.loads(
        runner.invoke(app, ["asset-pipeline", "concept-author", "--schema"]).stdout
    )

    assert set(
        prepare["input"]["properties"]["requested_options"]["propertyNames"]["enum"]
    ) == set(get_args(PromptOptionKey))
    assert select["input"]["properties"]["candidates"]["maxItems"] == 8
    consumer = author["input"]["properties"]["consumer"]
    assert set(consumer["enum"]) == set(get_args(ConceptConsumer))
    layout = author["input"]["$defs"]["SpriteSheetLayoutInput"]
    assert layout["additionalProperties"] is False
    assert layout["properties"]["frames"]["maximum"] == 64

    validator = jsonschema.Draft202012Validator(select["input"])
    base = {"brief_record": "/tmp/record", "handoff": "/tmp/handoff"}
    assert list(validator.iter_errors({**base, "candidates": []}))
    assert list(
        validator.iter_errors(
            {
                **base,
                "candidates": [
                    {"record": f"/tmp/r{i}", "output": "image.png"} for i in range(9)
                ],
            }
        )
    )


def test_concept_prepare_argv_and_structured_params_preserve_plain_handoff(tmp_path):
    brief = tmp_path / "brief.json"
    brief.write_text(
        json.dumps(
            {
                "use": "model",
                "subject": "Mossy stone arch",
                "style": "painted low poly",
                "views": ["front", "side"],
                "poses": [],
                "instructions": "Readable at game camera distance.",
            }
        )
    )
    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "asset-pipeline",
            "concept-prepare",
            "--brief",
            str(brief),
            "--record",
            str(tmp_path / "attempt-a"),
            "--producer",
            "external-tool",
            "--requested-options",
            '{"size":"1024x1024"}',
            "--json",
        ],
    )
    second = runner.invoke(
        app,
        [
            "asset-pipeline",
            "concept-prepare",
            "--params-json",
            json.dumps(
                {
                    "brief": str(brief),
                    "record": str(tmp_path / "attempt-b"),
                    "producer": "external-tool",
                    "requested_options": {"size": "1024x1024"},
                }
            ),
            "--json",
        ],
    )

    assert first.exit_code == second.exit_code == 0, first.output + second.output
    left, right = (
        json.loads(first.stdout)["preparation"],
        json.loads(second.stdout)["preparation"],
    )
    assert left["brief"] == right["brief"]
    assert (
        left["prompt"]["record"]["resolved_prompt"]
        == right["prompt"]["record"]["resolved_prompt"]
    )
    assert left["prompt"]["record"]["generation_status"] == "unknown"
    assert left["prompt"]["handoff"]["action"] == "external_generation_required"


def test_concept_failure_is_structured_and_does_not_require_a_project(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "concept-author",
            "--handoff",
            str(tmp_path / "missing"),
            "--consumer",
            "sprite-sheet-reference",
            "--output",
            str(tmp_path / "out"),
            "--sprite-layout",
            '{"width":64,"height":64,"cell_width":32,"cell_height":32,"frames":4}',
            "--json",
        ],
    )

    assert result.exit_code != 0
    error = json.loads(result.stdout)["error"]
    assert error["category"] == "operation"
    assert error["code"] == "invalid_params"
    assert "handoff" in error["message"].lower()
    assert not (tmp_path / "out").exists()
