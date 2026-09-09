"""Supported import-option changes are proved against real Godot results."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands import resource

from tests.support import Gda

pytestmark = pytest.mark.e2e


@pytest.fixture
def imported_options_model(godot_project, monkeypatch):
    # Keep per-invocation engine data writable and outside the target snapshot.
    monkeypatch.setenv(
        "GDA_USER_DATA_ROOT", str(godot_project.with_name(godot_project.name + "-data"))
    )
    generator = Path(__file__).parent / "fixtures" / "model_inspection.gd"
    (godot_project / "generate.gd").write_bytes(generator.read_bytes())
    run = Gda(godot_project, json_output=True)
    assert (
        run.json("script", "run", "res://generate.gd", "--strict")["exit_status"] == 0
    )
    run.json("resource", "import", "res://model.glb")
    # A metadata query must not start target-project constructors. Native import
    # does not start them either; add this after generating the fixture.
    with (godot_project / "project.godot").open("a") as project:
        project.write('\n[autoload]\nQueryTripwire="*res://tripwire.gd"\n')
    (godot_project / "tripwire.gd").write_text(
        "extends Node\nfunc _init():\n"
        '\tFileAccess.open("res://query-side-effect.txt", FileAccess.WRITE).store_string("ran")\n'
    )
    return godot_project


def test_query_reports_configured_options_without_target_project_execution(
    imported_options_model,
):
    project = imported_options_model
    before = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    }
    result = Gda(project, json_output=True).json(
        "resource", "import-options", "res://model.glb"
    )
    assert result["path"] == "res://model.glb"
    assert result["importer"] == "scene"
    assert result["resource_type"] == "PackedScene"
    assert result["engine_version"]["major"] == 4
    options = {o["name"]: o for o in result["configured_options"]}
    assert options["nodes/root_scale"]["value"] == 1.0
    assert options["nodes/root_scale"]["value_type"] == "float"
    assert result["default_metadata_available"] is False
    assert result["metadata_limitations"]
    assert result["supported_updates"] == [
        {
            "name": "nodes/root_scale",
            "value_type": "float",
            "minimum": 0.001,
            "maximum": 1000.0,
        }
    ]
    assert {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    } == before


def test_root_scale_patch_dry_run_validates_without_writing_or_importing(
    imported_options_model,
):
    project = imported_options_model
    before = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    }
    result = Gda(project, json_output=True).json(
        "resource",
        "reimport",
        "res://model.glb",
        "--updates-json",
        json.dumps({"nodes/root_scale": 2.0}),
        "--dry-run",
    )
    assert result["dry_run"] is True
    assert result["status"] == "checked"
    assert result["changes"] == [
        {"name": "nodes/root_scale", "before": 1.0, "requested": 2.0}
    ]
    assert result["sidecar_changed"] is False
    assert result["import_result"] is None
    assert result["verification"] is None
    assert {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    } == before


@pytest.mark.parametrize("apply_root_scale", [True, False])
def test_option_only_edit_reimports_and_proves_scaled_geometry(
    imported_options_model, apply_root_scale
):
    project = imported_options_model
    run = Gda(project, json_output=True)
    if not apply_root_scale:
        sidecar = project / "model.glb.import"
        sidecar.write_text(
            sidecar.read_text().replace(
                "nodes/apply_root_scale=true", "nodes/apply_root_scale=false"
            )
        )
    source = (project / "model.glb").read_bytes()
    wrapper = '[gd_scene format=3]\n[node name="Authored" type="Node3D"]\n'
    (project / "authored.tscn").write_text(wrapper)
    before = run.json("resource", "import-options", "res://model.glb")
    result = run.json(
        "resource",
        "reimport",
        "res://model.glb",
        "--updates-json",
        json.dumps({"nodes/root_scale": 2.0}),
    )
    assert result["status"] == "applied"
    assert result["sidecar_changed"] is True
    assert result["import_result"]["engine_pass"] is True
    assert result["import_result"]["assets"][0]["status"] == "imported"
    verification = result["verification"]
    assert verification["matched"] is True
    assert verification["scale_ratio"] == 2.0
    assert verification["before"]["size"][:2] == pytest.approx([100, 5])
    assert verification["after"]["size"][:2] == pytest.approx([200, 10])
    after = run.json("resource", "import-options", "res://model.glb")
    prior = {o["name"]: o for o in before["configured_options"]}
    current = {o["name"]: o for o in after["configured_options"]}
    assert current["nodes/root_scale"]["value"] == 2.0
    assert {k: v for k, v in prior.items() if k != "nodes/root_scale"} == {
        k: v for k, v in current.items() if k != "nodes/root_scale"
    }
    assert (project / "model.glb").read_bytes() == source
    assert (project / "authored.tscn").read_text() == wrapper


@pytest.mark.parametrize("diagnostic_mode", ["silent", "short", "long"])
def test_failed_native_reimport_reports_retained_configuration(
    imported_options_model, monkeypatch, diagnostic_mode
):
    project = imported_options_model
    diagnostic = "res://model.glb: deliberate post-import rejection"
    prefix = '"界".repeat(6000) + ' if diagnostic_mode == "long" else ""
    hook_log = (
        f'\tpush_error({prefix}"{diagnostic}")\n' if diagnostic_mode != "silent" else ""
    )
    (project / "reject.gd").write_text(
        "@tool\nextends EditorScenePostImport\n"
        "func _post_import(scene):\n" + hook_log + "\tscene.free()\n\treturn null\n"
    )
    sidecar = project / "model.glb.import"
    sidecar.write_text(
        sidecar.read_text().replace(
            'import_script/path=""', 'import_script/path="res://reject.gd"'
        )
    )
    cache = project / ".godot" / "imported"
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in cache.iterdir()
        if p.is_file()
    }
    source = (project / "model.glb").read_bytes()
    passes = []
    original_launch = resource.launch

    def observe_pass(*args, **kwargs):
        raw = original_launch(*args, **kwargs)
        passes.append(raw)
        return raw

    monkeypatch.setattr(resource, "launch", observe_pass)
    response = CliRunner().invoke(
        app,
        [
            "resource",
            "reimport",
            "res://model.glb",
            "--updates-json",
            '{"nodes/root_scale":2}',
            "--project",
            str(project),
            "--json",
        ],
    )
    assert response.exit_code == 4, response.stdout + response.stderr
    error = json.loads(response.stdout)["error"]
    assert error["code"] == "operation_failed"
    assert len(passes) == 1
    assert passes[0].exit_code == 0
    assert "Godot Engine" in passes[0].stdout
    if diagnostic_mode != "silent":
        assert diagnostic in passes[0].stderr
        assert diagnostic in error["diagnostics"]
        assert "project-wide import stderr" in error["message"]
        if diagnostic_mode == "long":
            assert len(passes[0].stderr.encode("utf-8")) > 16384
            assert len(error["diagnostics"].encode("utf-8")) <= 16384
            assert passes[0].stderr.endswith(error["diagnostics"])
        else:
            assert error["diagnostics"] == passes[0].stderr
    else:
        assert passes[0].stderr == error["diagnostics"] == ""
        assert "No stderr was captured" in error["message"]
    assert "1 imported asset(s)" in error["message"]
    assert "does not prove adoption" in error["message"]
    assert "no rollback was attempted" in error["message"]
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in cache.iterdir()
        if p.is_file()
    } == before
    assert (project / "model.glb").read_bytes() == source
    partial = error["partial_result"]
    assert partial["status"] == "failed"
    assert partial["sidecar_changed"] is True
    assert partial["engine_pass_attempted"] is True
    # Godot retains the old cache after this failure. Existing import evidence
    # can still classify it as imported (#952); dimensions must reject that
    # stale result instead of treating the import summary as adoption proof.
    assert partial["import_result"]["assets"][0]["status"] == "imported"
    assert partial["import_result"]["summary"]["failed"] == 0
    assert partial["import_result"]["engine_pass"] is True
    assert partial["verification"]["matched"] is False
    assert partial["verification"]["after"]["size"][:2] == pytest.approx([100, 5])
    assert "nodes/root_scale=2.0" in sidecar.read_text()
    assert 'import_script/path="res://reject.gd"' in sidecar.read_text()


def test_noop_and_invalid_updates_do_not_touch_the_target(imported_options_model):
    project = imported_options_model
    before = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    }
    run = Gda(project, json_output=True)
    imported = run.json("resource", "import", "res://model.glb")
    assert imported["engine_pass"] is False
    assert imported["assets"][0]["status"] == "cached"
    result = run.json(
        "resource",
        "reimport",
        "res://model.glb",
        "--updates-json",
        '{"nodes/root_scale":1}',
    )
    assert result["status"] == "unchanged"
    assert result["changes"] == []
    assert result["sidecar_changed"] is False
    assert result["engine_pass_attempted"] is False
    assert result["import_result"] is None
    assert result["verification"] is None
    for updates in (
        {"bogus": 2},
        {"nodes/root_scale": "2"},
        {"nodes/root_scale": True},
        {"nodes/root_scale": 0},
        {"nodes/root_scale": 1001},
    ):
        invalid = run(
            "resource",
            "reimport",
            "--params-json",
            json.dumps(
                {"path": "res://model.glb", "updates": updates, "dry_run": True}
            ),
        )
        assert invalid.returncode != 0
        assert json.loads(invalid.stdout)["error"]["code"] == "invalid_params"
    assert {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    } == before


def test_subtolerance_scale_change_cannot_report_adoption(imported_options_model):
    project = imported_options_model
    sidecar = project / "model.glb.import"
    original = sidecar.read_bytes()
    error = Gda(project, json_output=True).error(
        "resource",
        "reimport",
        "res://model.glb",
        "--updates-json",
        '{"nodes/root_scale":1.000001}',
        code="invalid_params",
    )
    assert "tolerance" in error["message"]
    assert sidecar.read_bytes() == original
