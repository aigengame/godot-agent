import json

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.asset_pipeline import (
    AssetFileInput,
    AssetPipelineRunParams,
    run_asset_pipeline,
)
from gda.errors import Failure
from gda_assets.api import (
    ImportOutcome,
    InstalledFile,
    LoadObservation,
    PipelineFailure,
    PipelineResult,
)
from gda.errors import make_failure
from tests.support import minimal_project


def test_asset_pipeline_run_is_discoverable_with_typed_file_input():
    result = CliRunner().invoke(app, ["asset-pipeline", "run", "--schema"])

    assert result.exit_code == 0, result.stdout
    schema = json.loads(result.stdout)
    assert schema["kind"] == "composite"
    assert schema["input"]["properties"]["files"]["type"] == "array"
    bindings = {item["input_property"]: item for item in schema["argv"]}
    assert bindings["files"]["option"] == "--files"
    assert bindings["files"]["json_value"] is True
    assert bindings["source_root"]["option"] == "--source-root"
    assert bindings["overwrite"]["option"] == "--overwrite"
    assert bindings["source_mode"]["option"] == "--source-mode"
    assert bindings["provenance"]["option"] == "--provenance"


def test_no_resolved_project_is_a_structured_failure_on_both_input_paths(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    files = [{"source": "missing.png", "target": "res://icon.png"}]
    runner = CliRunner()

    argv = runner.invoke(
        app,
        ["asset-pipeline", "run", "--files", json.dumps(files), "--json"],
    )
    structured = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps({"files": files}),
            "--json",
        ],
    )

    assert argv.exit_code == structured.exit_code == 4
    assert argv.exception is not None and not isinstance(argv.exception, AssertionError)
    assert structured.exception is not None and not isinstance(
        structured.exception, AssertionError
    )
    assert json.loads(argv.stdout) == json.loads(structured.stdout)
    error = json.loads(argv.stdout)["error"]
    assert error["code"] == "project_not_found"
    assert error["partial_result"]["completed"] == []
    assert error["partial_result"]["failure"]["stage"] == "validate"


def test_argv_and_params_json_build_the_same_recipe(monkeypatch, tmp_path):
    project = minimal_project(tmp_path / "project")
    source_root = tmp_path / "source"
    source_root.mkdir()
    calls = []

    def fake_run(recipe, *, source_root, project_root, godot):
        calls.append((recipe, source_root, project_root))
        return PipelineResult(
            completed=["validate", "stage", "install", "import", "load"],
            outputs=[InstalledFile("icon.png", "res://art/icon.png", "installed")],
            import_result=ImportOutcome({"engine_pass": True}),
            observations=[
                LoadObservation("res://art/icon.png", "CompressedTexture2D", (16, 8))
            ],
            source_mode=recipe.source_mode,
            caller_declared_provenance=recipe.provenance,
        )

    monkeypatch.setattr("gda.commands.asset_pipeline.run_pipeline", fake_run)
    files = [
        {
            "source": "icon.png",
            "target": "res://art/icon.png",
            "resize": {"width": 16, "height": 8},
            "references": [],
        }
    ]
    params = {
        "files": files,
        "source_root": str(source_root),
        "overwrite": True,
        "source_mode": "imagegen",
        "provenance": {"generator": "declared"},
    }
    runner = CliRunner()

    argv = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(files),
            "--source-root",
            str(source_root),
            "--overwrite",
            "--source-mode",
            "imagegen",
            "--provenance",
            json.dumps(params["provenance"]),
            "--project",
            str(project),
            "--json",
        ],
    )
    structured = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps(params),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert argv.exit_code == structured.exit_code == 0, (
        argv.stdout + argv.stderr + structured.stdout + structured.stderr
    )
    assert json.loads(argv.stdout) == json.loads(structured.stdout)
    assert calls[0][0] == calls[1][0]
    assert calls[0][1:] == calls[1][1:] == (source_root.resolve(), project)
    assert json.loads(argv.stdout)["pipeline"]["caller_declared_provenance"] == {
        "generator": "declared"
    }


def test_fractional_or_boolean_resize_dimensions_are_rejected_before_dispatch(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    monkeypatch.setattr(
        "gda.commands.asset_pipeline.run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not dispatch")
        ),
    )

    for width in (True, 1.5, "8"):
        params = {
            "files": [
                {
                    "source": "icon.png",
                    "target": "res://icon.png",
                    "resize": {"width": width, "height": 8},
                }
            ]
        }
        result = CliRunner().invoke(
            app,
            [
                "asset-pipeline",
                "run",
                "--params-json",
                json.dumps(params),
                "--project",
                str(project),
                "--json",
            ],
        )
        assert result.exit_code != 0
        assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_failure_is_nonzero_preserves_child_error_and_carries_partial_result(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    underlying = make_failure(
        "operation_failed", "engine import failed", "engine stderr\n"
    )
    underlying.child_stderr = "engine stderr\n"

    class Port:
        last_failure = underlying

    monkeypatch.setattr(
        "gda.commands.asset_pipeline.GdaGodotAssetPort", lambda *args: Port()
    )
    monkeypatch.setattr(
        "gda.commands.asset_pipeline.run_pipeline",
        lambda *args, **kwargs: PipelineResult(
            completed=["validate", "stage", "install"],
            outputs=[InstalledFile("icon.png", "res://icon.png", "installed")],
            failure=PipelineFailure(
                "import", "operation_failed", "engine import failed"
            ),
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--files",
            '[{"source":"icon.png","target":"res://icon.png"}]',
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert result.stderr == "engine stderr\n"
    error = json.loads(result.stdout)["error"]
    assert error["category"] == "operation"
    assert error["code"] == "operation_failed"
    assert error["diagnostics"] == "engine stderr\n"
    assert "during import" in error["message"]
    assert "res://icon.png (installed)" in error["message"]
    assert error["partial_result"]["completed"] == ["validate", "stage", "install"]


def test_nested_project_target_is_rejected_before_pipeline_install(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    nested = project / "vendor"
    nested.mkdir()
    (nested / "project.godot").write_text("[application]\n", encoding="utf-8")
    monkeypatch.setattr(
        "gda.commands.asset_pipeline.run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must reject before install")
        ),
    )

    outcome = run_asset_pipeline(
        AssetPipelineRunParams(
            files=[AssetFileInput(source="model.glb", target="res://vendor/model.glb")]
        ),
        project=project,
        godot=None,
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "target_outside_project"
    assert outcome.error.evidence is not None
    assert outcome.error.evidence.owning_project == str(nested.resolve())
    assert outcome.error.partial_result is not None
    assert outcome.error.partial_result["completed"] == []
