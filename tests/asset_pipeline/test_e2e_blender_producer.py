"""Saved Blender production reaches the same public Godot handoff path."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.support import Gda

pytestmark = pytest.mark.e2e


@pytest.fixture
def saved_blender_source(tmp_path_factory, request):
    executable = os.environ.get("GDA_BLENDER") or shutil.which("blender")
    if executable is None:
        pytest.fail("Blender producer E2E requires GDA_BLENDER or blender on PATH")
    source = tmp_path_factory.mktemp("blender-source") / "source.blend"
    fixture = Path(__file__).parent / "fixtures" / "blender_source.py"
    built = subprocess.run(
        [
            executable,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(fixture),
            "--",
            str(source),
            getattr(request, "param", "static"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return source, executable


@pytest.mark.parametrize("scale", [1, 2])
def test_saved_root_production_preserves_source_and_loads_scaled_model(
    godot_project,
    saved_blender_source,
    monkeypatch,
    scale,
):
    source, executable = saved_blender_source
    original = source.read_bytes()
    monkeypatch.setenv(
        "GDA_USER_DATA_ROOT", str(godot_project.with_name(godot_project.name + "-data"))
    )
    run = Gda(godot_project, json_output=True)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "AssetRoot",
            "uniform_scale": scale,
            "executable": executable,
        },
    }
    result = run.json("asset-pipeline", "run", "--production", json.dumps(production))[
        "pipeline"
    ]
    assert result["observations"][0]["resource_type"] == "PackedScene"
    assert result["outputs"][0]["target"] == "res://models/asset.glb"
    facts = run.json("resource", "inspect-model", "res://models/asset.glb")
    assert sorted(facts["bounds"]["size"]) == pytest.approx(
        [4 * scale, 5 * scale, 6 * scale]
    )
    assert all("UnrelatedStudio" not in node["path"] for node in facts["nodes"])
    assert any("HiddenDetail" in node["path"] for node in facts["nodes"])
    assert source.read_bytes() == original


@pytest.mark.parametrize("saved_blender_source", ["animated"], indirect=True)
def test_animated_root_scale_refuses_before_export(godot_project, saved_blender_source):
    source, executable = saved_blender_source
    original = source.read_bytes()
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "AssetRoot",
            "uniform_scale": 2,
            "export": {"animations": True},
            "executable": executable,
        },
    }
    error = Gda(godot_project, json_output=True).error(
        "asset-pipeline",
        "run",
        "--production",
        json.dumps(production),
        code="operation_failed",
    )
    partial = error["partial_result"]
    assert partial["failure"]["cause"]["stage"] == "prepare"
    assert "animated or driven root" in error["message"]
    assert partial["outputs"] == []
    assert partial["cleanup"]["workspace_removed"] is True
    assert not (godot_project / "models").exists()
    assert source.read_bytes() == original


def test_missing_root_refuses_installation_and_reports_cleanup(
    godot_project,
    saved_blender_source,
):
    source, executable = saved_blender_source
    original = source.read_bytes()
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "MissingRoot",
            "executable": executable,
        },
    }
    error = Gda(godot_project, json_output=True).error(
        "asset-pipeline",
        "run",
        "--production",
        json.dumps(production),
        code="operation_failed",
    )
    partial = error["partial_result"]
    assert partial["failure"]["stage"] == "produce"
    assert partial["failure"]["cause"]["stage"] == "inspect"
    assert partial["outputs"] == []
    assert partial["cleanup"]["workspace_removed"] is True
    assert not (godot_project / "models").exists()
    assert source.read_bytes() == original


def test_native_export_failure_is_separate_from_preparation(
    godot_project,
    saved_blender_source,
    monkeypatch,
):
    from typer.testing import CliRunner
    from gda.cli import app

    source, executable = saved_blender_source
    original = source.read_bytes()
    real_run = subprocess.run

    def reject_output(argv, **kwargs):
        if argv[0] == executable:
            request = json.loads(Path(argv[-1]).read_text())
            # Inject a filesystem fault at the native export boundary: Blender
            # must actually attempt and fail to write to this directory.
            Path(request["output"]).mkdir()
        return real_run(argv, **kwargs)

    monkeypatch.setattr("gda_assets.adapters.blender.subprocess.run", reject_output)
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "AssetRoot",
            "executable": executable,
        },
    }
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--production",
            json.dumps(production),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    assert result.exit_code == 4, result.output
    partial = json.loads(result.stdout)["error"]["partial_result"]
    cause = partial["failure"]["cause"]
    assert cause["stage"] == "export"
    assert cause["completed"] == ["inspect", "prepare"]
    assert partial["outputs"] == []
    assert partial["cleanup"]["workspace_removed"] is True
    assert source.read_bytes() == original


def test_real_import_failure_retains_export_without_repeating_blender(
    godot_project,
    saved_blender_source,
    monkeypatch,
):
    from typer.testing import CliRunner
    from gda.cli import app

    source, executable = saved_blender_source
    original = source.read_bytes()
    monkeypatch.setenv(
        "GDA_USER_DATA_ROOT", str(godot_project.with_name(godot_project.name + "-data"))
    )
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "AssetRoot",
            "executable": executable,
        },
    }
    Gda(godot_project, json_output=True).json(
        "asset-pipeline", "run", "--production", json.dumps(production)
    )
    sidecar = godot_project / "models/asset.glb.import"
    sidecar.write_text(
        sidecar.read_text().replace(
            'import_script/path=""', 'import_script/path="res://reject.gd"'
        )
    )
    (godot_project / "reject.gd").write_text(
        "@tool\nextends EditorScenePostImport\nfunc _post_import(scene):\n\tscene.free()\n\treturn null\n"
    )
    shutil.rmtree(godot_project / ".godot")
    real_run = subprocess.run
    native_calls = []

    def count_native(argv, **kwargs):
        if argv[0] == executable:
            native_calls.append(argv)
        return real_run(argv, **kwargs)

    monkeypatch.setattr("gda_assets.adapters.blender.subprocess.run", count_native)
    production["options"]["uniform_scale"] = 2
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps({"production": production, "overwrite": True}),
            "--project",
            str(godot_project),
            "--json",
        ],
    )
    assert result.exit_code == 4, result.output
    partial = json.loads(result.stdout)["error"]["partial_result"]
    assert partial["failure"]["stage"] == "import"
    assert partial["completed"] == ["produce", "validate", "stage", "install"]
    assert partial["outputs"][0]["state"] == "installed"
    assert len(native_calls) == 1
    assert partial["cleanup"]["workspace_removed"] is True
    assert (godot_project / "models/asset.glb").is_file()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "saved_blender_source, message",
    [
        ("empty", "no finite evaluated mesh bounds"),
        ("ambiguous", "absent or ambiguous"),
    ],
    indirect=["saved_blender_source"],
)
def test_unavailable_or_ambiguous_selection_is_not_an_observation(
    godot_project,
    saved_blender_source,
    message,
):
    source, executable = saved_blender_source
    original = source.read_bytes()
    production = {
        "kind": "blender_saved",
        "outputs": [{"role": "model", "target": "res://models/asset.glb"}],
        "options": {
            "source": str(source),
            "scene": "AssetScene",
            "root": "AssetRoot",
            "executable": executable,
        },
    }
    error = Gda(godot_project, json_output=True).error(
        "asset-pipeline",
        "run",
        "--production",
        json.dumps(production),
        code="operation_failed",
    )
    assert message in error["message"]
    partial = error["partial_result"]
    assert partial["failure"]["cause"]["stage"] == "inspect"
    assert partial["outputs"] == []
    assert partial["cleanup"]["workspace_removed"] is True
    assert source.read_bytes() == original
