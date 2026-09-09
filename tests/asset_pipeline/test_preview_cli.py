"""One typed CLI/MCP surface for isolated model preview."""

import json
import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.asset_pipeline import AssetPipelinePreviewParams, run_asset_preview
from gda.errors import Failure, make_failure
from gda.mcp.server import build_server
from gda_assets.api import PipelineFailure, PreviewRequest, PreviewResult
from tests.mcp_support import FakeGdaRunner, gda_result, list_tools, schema_then
from tests.support import minimal_project


def test_preview_timeout_help_does_not_advertise_the_refused_zero_boundary():
    result = CliRunner().invoke(app, ["asset-pipeline", "preview", "--help"])
    assert result.exit_code == 0
    assert "0<=x<=50" not in result.output
    assert "positive" in result.output.lower()


def test_preview_human_result_reports_comparison_and_diagnostic_coverage(tmp_path):
    from gda.commands.asset_pipeline import (
        AssetPipelinePreviewResult,
        render_asset_preview,
    )
    from gda_assets.domain.preview_result import PreviewComparison, PreviewDiagnostics

    preview = PreviewResult(
        request=PreviewRequest(tmp_path / "model.glb", tmp_path / "out"),
        comparison=PreviewComparison("non_comparable", ("preview_setup_mismatch",)),
        diagnostics=PreviewDiagnostics((), True),
    )
    rendered = render_asset_preview(AssetPipelinePreviewResult(preview=preview))
    assert "non_comparable" in rendered and "preview_setup_mismatch" in rendered
    assert "diagnostics" in rendered and "truncated=True" in rendered
    assert "startup" in rendered and "stabilized performance" in rendered


def test_preview_schema_and_mcp_publish_bounded_typed_contract():
    result = CliRunner().invoke(app, ["asset-pipeline", "preview", "--schema"])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)

    assert schema["kind"] == "composite"
    assert schema["input"]["additionalProperties"] is False
    assert schema["input"]["properties"]["frames"]["maximum"] == 120
    assert schema["input"]["properties"]["warmup_seconds"]["maximum"] == 10
    assert schema["input"]["properties"]["warmup_seconds"]["minimum"] == 0
    assert schema["input"]["properties"]["warmup_seconds"]["default"] == 0
    assert schema["input"]["properties"]["max_nodes"]["maximum"] == 4096
    assert schema["input"]["properties"]["settings"]["anyOf"][0]["type"] == "string"
    assert "PreviewResult" in schema["output"]["$defs"]
    bindings = {item["input_property"]: item for item in schema["argv"]}
    assert bindings["settings"]["option"] == "--settings"
    assert bindings["warmup_seconds"]["option"] == "--warmup-seconds"
    assert bindings["settings"]["json_value"] is False
    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == "asset_pipeline_preview")
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]


def test_preview_argv_and_params_json_resolve_the_same_request(monkeypatch, tmp_path):
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF")
    calls = []

    def preview(request, *, host):
        calls.append((request, host))
        return PreviewResult(request=request, completed=["prepare"])

    monkeypatch.setattr("gda.commands.asset_pipeline.preview_asset", preview)
    settings = {"width": 800, "height": 450, "padding": 1.25}
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(settings))
    common = {
        "path": str(source),
        "output_dir": str(tmp_path / "captures"),
        "settings": str(settings_file),
        "frames": 5,
        "warmup_seconds": 2.5,
        "timeout": 4.5,
        "max_nodes": 10,
    }
    runner = CliRunner()
    results = []
    for args in (
        [
            "--path",
            common["path"],
            "--output-dir",
            common["output_dir"],
            "--settings",
            str(settings_file),
            "--frames",
            "5",
            "--warmup-seconds",
            "2.5",
            "--timeout",
            "4.5",
            "--max-nodes",
            "10",
        ],
        ["--params-json", json.dumps(common)],
    ):
        outcome = runner.invoke(app, ["asset-pipeline", "preview", *args, "--json"])
        assert outcome.exit_code == 0, outcome.output
        results.append(json.loads(outcome.stdout))

    assert results[0] == results[1]
    assert calls[0][0] == calls[1][0]
    assert calls[0][0].source == source
    assert calls[0][0].output_dir == (tmp_path / "captures").resolve()
    assert calls[0][0].settings.width == 800
    assert calls[0][0].warmup_seconds == 2.5


def test_bad_settings_file_stops_before_preview_service(monkeypatch, tmp_path):
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF")

    def preview(*args, **kwargs):
        raise AssertionError("invalid settings must not reach preview service")

    monkeypatch.setattr("gda.commands.asset_pipeline.preview_asset", preview)
    runner = CliRunner()
    for settings in (tmp_path / "missing.json", tmp_path / "broken.json"):
        if settings.name == "broken.json":
            settings.write_text("{")
        result = runner.invoke(
            app,
            [
                "asset-pipeline",
                "preview",
                "--path",
                str(source),
                "--output-dir",
                str(tmp_path / settings.stem),
                "--settings",
                str(settings),
            ],
        )
        assert result.exit_code == 4


def test_domain_failure_is_not_replaced_by_later_cleanup_native_failure(
    monkeypatch, tmp_path
):
    cleanup_failure = make_failure("daemon_not_running", "cleanup failed", "stderr")

    class Host:
        last_failure = cleanup_failure

        def __call__(self, project):
            return self

    monkeypatch.setattr(
        "gda.commands.asset_pipeline.GdaPreviewHost", lambda godot: Host()
    )
    monkeypatch.setattr(
        "gda.commands.asset_pipeline.preview_asset",
        lambda request, *, host: PreviewResult(
            request=PreviewRequest(request.source, request.output_dir),
            failure=PipelineFailure(
                "inspect", "preview_incomplete", "model bounds are incomplete"
            ),
        ),
    )

    result = run_asset_preview(
        AssetPipelinePreviewParams(
            path=str(tmp_path / "model.glb"), output_dir=tmp_path / "out"
        ),
        project=None,
        godot=None,
    )

    assert isinstance(result, Failure)
    assert result.error.code == "operation_failed"
    assert result.error.message == (
        "asset preview failed during inspect: model bounds are incomplete"
    )
    assert result.error.diagnostics == ""


def test_absolute_preview_is_projectless_but_res_path_requires_project(
    monkeypatch, tmp_path
):
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF")
    monkeypatch.setattr(
        "gda.commands.asset_pipeline.preview_asset",
        lambda request, *, host: PreviewResult(request=request),
    )
    runner = CliRunner()

    absolute = runner.invoke(
        app,
        [
            "asset-pipeline",
            "preview",
            "--path",
            str(source),
            "--output-dir",
            str(tmp_path / "out"),
            "--json",
        ],
    )
    resource = runner.invoke(
        app,
        [
            "asset-pipeline",
            "preview",
            "--path",
            "res://model.glb",
            "--output-dir",
            str(tmp_path / "out2"),
            "--json",
        ],
    )

    assert absolute.exit_code == 0, absolute.output
    assert resource.exit_code != 0
    error = json.loads(resource.stdout)["error"]
    assert error["code"] == "project_not_found"


def test_res_path_resolves_inside_the_selected_project(monkeypatch, tmp_path):
    project = minimal_project(tmp_path / "project")
    source = project / "art" / "model.glb"
    source.parent.mkdir()
    source.write_bytes(b"glTF")
    requests = []

    def preview(request, *, host):
        requests.append(request)
        return PreviewResult(request=request)

    monkeypatch.setattr("gda.commands.asset_pipeline.preview_asset", preview)
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "preview",
            "--path",
            "res://art/model.glb",
            "--output-dir",
            str(tmp_path / "out"),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert requests[0].source == source.resolve()


@pytest.mark.parametrize("value", [-0.1, 10.1, float("nan"), float("inf"), True, "2.5"])
def test_invalid_warmup_params_json_never_reaches_workflow(
    monkeypatch, tmp_path, value
):
    def refuse(*args, **kwargs):
        raise AssertionError("invalid warmup reached workflow")

    monkeypatch.setattr("gda.commands.asset_pipeline.preview_asset", refuse)
    outcome = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "preview",
            "--params-json",
            json.dumps(
                {
                    "path": str(tmp_path / "a.glb"),
                    "output_dir": str(tmp_path / "out"),
                    "warmup_seconds": value,
                }
            ),
            "--json",
        ],
    )
    assert outcome.exit_code == 4
    assert json.loads(outcome.stdout)["error"]["code"] == "invalid_params"
    assert not (tmp_path / "out").exists()
