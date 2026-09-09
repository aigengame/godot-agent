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
from tests.support import minimal_project, structured_argv_error_message


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


def test_collection_is_opt_in_and_schema_describes_file_observations():
    from gda.commands.asset_pipeline import AssetPipelineRunResult

    result = CliRunner().invoke(app, ["asset-pipeline", "run", "--schema"])
    schema = json.loads(result.stdout)
    assert schema["input"]["properties"]["collect_observations"]["default"] is False
    bindings = {item["input_property"]: item for item in schema["argv"]}
    assert bindings["collect_observations"]["option"] == "--collect-observations"
    assert bindings["declared_output_sha256"]["json_value"] is True
    definitions = AssetPipelineRunResult.model_json_schema()["$defs"]
    assert definitions["FileDigest"]["properties"]["sha256"]
    assert definitions["ContentObservations"]["properties"]["status"]["enum"] == [
        "incomplete",
        "stable",
        "changed",
    ]


def test_collection_flags_and_structured_params_forward_the_same_request(
    monkeypatch, tmp_path
):
    from pathlib import Path
    from gda_assets.api import ContentObservations

    project = minimal_project(tmp_path / "project")
    calls = []

    def run(recipe, **kwargs):
        assert kwargs["import_observer"] is kwargs["godot"]
        calls.append(kwargs["collection"])
        return PipelineResult(content_observations=ContentObservations())

    monkeypatch.setattr("gda.commands.asset_pipeline.run_pipeline", run)
    files = [{"source": str(tmp_path / "icon.png"), "target": "res://icon.png"}]
    declared = {"res://icon.png": "a" * 64}
    params = {
        "files": files,
        "collect_observations": True,
        "observations_output": "observations.json",
        "declared_output_sha256": declared,
    }
    outputs = []
    for args in (
        [
            "--files",
            json.dumps(files),
            "--collect-observations",
            "--observations-output",
            "observations.json",
            "--declared-output-sha256",
            json.dumps(declared),
        ],
        ["--params-json", json.dumps(params)],
    ):
        result = CliRunner().invoke(
            app, ["asset-pipeline", "run", *args, "--project", str(project), "--json"]
        )
        assert result.exit_code == 0, result.output
        outputs.append(json.loads(result.stdout))
    assert calls[0] == calls[1]
    assert calls[0].save_to == Path("observations.json")
    assert calls[0].declared_output_sha256 == declared
    assert outputs[0] == outputs[1]


def test_no_resolved_project_is_a_structured_failure_on_both_input_paths(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    files = [{"source": str(tmp_path / "missing.png"), "target": "res://icon.png"}]
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


def test_relative_sources_need_an_explicit_base_independent_of_cwd(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path / "project")
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    source_base = tmp_path / "selected"
    for directory, content in (
        (cwd_a, b"a"),
        (cwd_b, b"b"),
        (source_base, b"selected"),
    ):
        directory.mkdir()
        (directory / "icon.png").write_bytes(content)
    calls = []

    def fake_run(
        recipe,
        *,
        source_root,
        project_root,
        godot,
        production=None,
        collection=None,
        import_observer=None,
        refresh=None,
        runtime=None,
    ):
        assert collection is None and import_observer is None
        assert refresh is None and runtime is None
        assert production is None
        calls.append((recipe.files[0].source, source_root, project_root))
        return PipelineResult(source_mode=recipe.source_mode)

    monkeypatch.setattr("gda.commands.asset_pipeline.run_pipeline", fake_run)
    files = [{"source": "icon.png", "target": "res://icon.png"}]
    runner = CliRunner()

    monkeypatch.chdir(cwd_a)
    argv_refusal = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(files),
            "--project",
            str(project),
            "--json",
        ],
    )
    monkeypatch.chdir(cwd_b)
    params_refusal = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps({"files": files}),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert argv_refusal.exit_code == 2
    assert params_refusal.exit_code == 4
    assert "source_root is required" in structured_argv_error_message(argv_refusal)
    assert "source_root is required" in params_refusal.stdout
    assert calls == []

    monkeypatch.chdir(cwd_a)
    argv = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(files),
            "--source-root",
            str(source_base),
            "--project",
            str(project),
            "--json",
        ],
    )
    monkeypatch.chdir(cwd_b)
    structured = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps({"files": files, "source_root": str(source_base)}),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert argv.exit_code == structured.exit_code == 0
    assert calls == [
        ("icon.png", source_base.resolve(), project),
        ("icon.png", source_base.resolve(), project),
    ]

    absolute = str(source_base / "icon.png")
    allowed = runner.invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps(
                {"files": [{"source": absolute, "target": "res://absolute.png"}]}
            ),
            "--project",
            str(project),
            "--json",
        ],
    )
    assert allowed.exit_code == 0
    assert calls[-1][0] == absolute
    assert calls[-1][1] == project.resolve()


def test_argv_and_params_json_build_the_same_recipe(monkeypatch, tmp_path):
    project = minimal_project(tmp_path / "project")
    source_root = tmp_path / "source"
    source_root.mkdir()
    calls = []

    def fake_run(
        recipe,
        *,
        source_root,
        project_root,
        godot,
        production=None,
        collection=None,
        import_observer=None,
        refresh=None,
        runtime=None,
    ):
        assert collection is None and import_observer is None
        assert refresh is None and runtime is None
        assert production is None
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
            "--source-root",
            str(tmp_path),
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
            files=[AssetFileInput(source="model.glb", target="res://vendor/model.glb")],
            source_root=tmp_path,
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


def test_production_binding_requires_json_and_structured_input_matches(
    monkeypatch, godot_project
):
    calls = []

    def observe(
        recipe,
        *,
        source_root,
        project_root,
        godot,
        production=None,
        collection=None,
        import_observer=None,
        refresh=None,
        runtime=None,
    ):
        assert collection is None and import_observer is None
        assert refresh is None and runtime is None
        calls.append(production)
        return PipelineResult(source_mode="blender_saved")

    monkeypatch.setattr("gda.commands.asset_pipeline.run_pipeline", observe)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://model.glb"}],
        "options": {
            "source": "/production/source.blend",
            "scene": "Scene",
            "root": "Cube",
        },
    }
    runner = CliRunner()
    for args in (
        ["--production", json.dumps(production)],
        ["--params-json", json.dumps({"production": production})],
    ):
        result = runner.invoke(
            app,
            ["asset-pipeline", "run", *args, "--project", str(godot_project), "--json"],
        )
        assert result.exit_code == 0, result.output
    assert calls[0] == calls[1]
    assert calls[0].options == production["options"]
    schema = json.loads(
        runner.invoke(app, ["asset-pipeline", "run", "--schema"]).stdout
    )
    bindings = {item["input_property"]: item for item in schema["argv"]}
    assert bindings["production"]["option"] == "--production"
    assert bindings["production"]["json_value"] is True
