"""`gda resource import` — the scoped import surface, engine-free (#668).

The cache-verdict logic is pure Python (sidecar + dest-file checks), so the
dry-run and all-cached paths run with NO fake at all against a real temp
project tree. The engine pass is exercised through the launch seam
(``gda.commands.resource.launch``, the scene/script channels' pattern): a fake
launch simulates the pass's file effects, so the re-verdict, the before/after
accounting, and the classification are covered without an engine. The real
engine round trip (GDA-DF-010's preload failure healed by the import) is the
e2e in ``test_e2e_resource_import``.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult

runner_cli = CliRunner()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG fake bytes")
    return tmp_path


def _sidecar(project: Path, asset: str, dest_rel: str | None) -> None:
    lines = ['[remap]\n\nimporter="texture"\n']
    if dest_rel is not None:
        lines.append(f'\n[deps]\n\ndest_files=["res://{dest_rel}"]\n')
    (project / f"{asset}.import").write_text("".join(lines), encoding="utf-8")


def _run(project: Path, *args: str):
    return runner_cli.invoke(
        app,
        ["resource", "import", *args, "--project", str(project), "--json"],
    )


def _tree(project: Path) -> set[str]:
    return {
        p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()
    }


# --- dry run and the pure-Python verdicts (no engine, no fake) -----------------


def test_dry_run_reports_missing_and_predictions_and_writes_nothing(tmp_path):
    project = _project(tmp_path)
    before = _tree(project)

    result = _run(project, "res://icon.png", "--dry-run")

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["dry_run"] is True
    assert data["engine_pass"] is True  # a real run WOULD run the pass
    assert data["assets"] == [
        {
            "path": "res://icon.png",
            "status": "missing",
            "sidecar": None,
            "dest_files": [],
        }
    ]
    assert data["predicted_source_adjacent"] == ["res://icon.png.import"]
    assert data["created"] == []
    assert data["summary"]["missing"] == 1
    assert data["cache_root"] == "res://.godot"
    # The AC: a dry run writes nothing at all.
    assert _tree(project) == before


def test_dry_run_cached_when_sidecar_dest_files_exist(tmp_path):
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-abc.ctex"
    (project / ".godot/imported").mkdir(parents=True)
    (project / dest).write_bytes(b"ctex")
    _sidecar(project, "icon.png", dest)

    result = _run(project, "res://icon.png", "--dry-run")

    data = json.loads(result.stdout)
    assert data["assets"][0]["status"] == "cached"
    assert data["assets"][0]["sidecar"] == "res://icon.png.import"
    assert data["assets"][0]["dest_files"] == [f"res://{dest}"]
    assert data["engine_pass"] is False
    assert data["predicted_source_adjacent"] == []


def test_dry_run_missing_when_a_dest_file_is_absent(tmp_path):
    project = _project(tmp_path)
    _sidecar(project, "icon.png", ".godot/imported/icon.png-abc.ctex")

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "missing"
    # It HAS a sidecar, so no sidecar-creation prediction for it.
    assert data["predicted_source_adjacent"] == []
    assert data["engine_pass"] is True


def test_dry_run_keep_importer_sidecar_counts_as_cached(tmp_path):
    project = _project(tmp_path)
    _sidecar(project, "icon.png", None)  # no dest_files line: importer=keep style

    data = json.loads(_run(project, "res://icon.png", "--dry-run").stdout)

    assert data["assets"][0]["status"] == "cached"
    assert data["engine_pass"] is False


# --- the engine pass, through the launch seam ---------------------------------


def _fake_pass(project: Path, effects):
    """A fake launch that simulates the engine pass's file effects."""
    calls = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        calls.append((binary, args, cwd, timeout))
        effects(project)
        return RunResult(stdout="", stderr="", exit_code=0)

    return calls, fake_launch


def test_missing_asset_runs_the_pass_and_reports_created_classified(
    monkeypatch, tmp_path
):
    project = _project(tmp_path)

    def effects(p: Path) -> None:
        dest = ".godot/imported/icon.png-abc.ctex"
        (p / ".godot/imported").mkdir(parents=True)
        (p / dest).write_bytes(b"ctex")
        _sidecar(p, "icon.png", dest)
        (p / "tool.gd.uid").write_text("uid://x", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    result = _run(project, "res://icon.png")

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["dry_run"] is False
    assert data["engine_pass"] is True
    assert data["assets"][0]["status"] == "imported"
    created = {f["path"]: f["classification"] for f in data["created"]}
    assert created["res://.godot/imported/icon.png-abc.ctex"] == "cache_owned"
    assert created["res://icon.png.import"] == "source_adjacent"
    assert created["res://tool.gd.uid"] == "source_adjacent"
    assert data["summary"]["imported"] == 1
    assert data["summary"]["created_cache_owned"] == 1
    assert data["summary"]["created_source_adjacent"] == 2
    # The pass argv: the engine's project-wide --import, nothing else.
    (binary, args, cwd, timeout) = calls[0]
    assert args == ["--path", str(project), "--import"]
    assert timeout == 300.0


def test_all_cached_runs_no_pass(monkeypatch, tmp_path):
    project = _project(tmp_path)
    dest = ".godot/imported/icon.png-abc.ctex"
    (project / ".godot/imported").mkdir(parents=True)
    (project / dest).write_bytes(b"ctex")
    _sidecar(project, "icon.png", dest)

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["engine_pass"] is False
    assert data["assets"][0]["status"] == "cached"
    assert data["created"] == []
    assert calls == []  # the AC's spirit: no needless pass, ever


def test_pass_that_settles_no_sidecar_is_not_importable(monkeypatch, tmp_path):
    project = _project(tmp_path)
    (project / "script.gd").write_text("extends Node\n", encoding="utf-8")

    calls, fake_launch = _fake_pass(project, lambda p: None)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://script.gd").stdout)

    assert data["assets"][0]["status"] == "not_importable"
    assert data["summary"]["not_importable"] == 1


def test_pass_that_leaves_dest_missing_is_failed(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def effects(p: Path) -> None:
        _sidecar(p, "icon.png", ".godot/imported/never-written.ctex")

    calls, fake_launch = _fake_pass(project, effects)
    monkeypatch.setattr("gda.commands.resource.launch", fake_launch)

    data = json.loads(_run(project, "res://icon.png").stdout)

    assert data["assets"][0]["status"] == "failed"
    assert data["summary"]["failed"] == 1


def test_launch_failures_classify_through_the_shared_prefix(monkeypatch, tmp_path):
    project = _project(tmp_path)

    def timed_out(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        return RunResult(
            stdout="",
            stderr="took too long",
            exit_code=124,
            launch_failure=LaunchFailure.TIMEOUT,
        )

    monkeypatch.setattr("gda.commands.resource.launch", timed_out)
    timed = json.loads(_run(project, "res://icon.png").stdout)
    assert timed["error"]["code"] == "launch_timeout"

    def engine_failed(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        return RunResult(stdout="", stderr="importer exploded", exit_code=1)

    monkeypatch.setattr("gda.commands.resource.launch", engine_failed)
    failed = json.loads(_run(project, "res://icon.png").stdout)
    assert failed["error"]["code"] == "operation_failed"
    assert "importer exploded" in failed["error"]["diagnostics"]


# --- request validation --------------------------------------------------------


def test_asset_outside_the_project_is_invalid_params(tmp_path):
    project = _project(tmp_path)
    outside = tmp_path.parent / "elsewhere.png"

    data = json.loads(_run(project, str(outside)).stdout)

    assert data["error"]["code"] == "invalid_params"
    assert "outside the project" in data["error"]["message"]


def test_absent_asset_is_invalid_params(tmp_path):
    project = _project(tmp_path)

    data = json.loads(_run(project, "res://nope.png").stdout)

    assert data["error"]["code"] == "invalid_params"
    assert "does not exist" in data["error"]["message"]


def test_relative_filesystem_path_is_project_relative(tmp_path):
    project = _project(tmp_path)

    data = json.loads(_run(project, "icon.png", "--dry-run").stdout)

    assert data["assets"][0]["path"] == "res://icon.png"


def test_no_assets_is_a_usage_error(tmp_path):
    project = _project(tmp_path)

    result = _run(project)

    assert result.exit_code == 2, result.stdout + result.stderr
    from tests.support import plain_text

    assert "ASSETS" in plain_text(result.stderr)


def test_schema_is_self_describing():
    result = runner_cli.invoke(app, ["resource", "import", "--schema"])

    assert result.exit_code == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)
    assert "input" in schema and "output" in schema
    assert schema["kind"] == "headless"


def test_result_model_validates_its_mode_fields():
    # The #732 lesson, applied at birth: a payload mixing the modes fails.
    import pydantic

    from gda.commands.resource import ResourceImportResult

    base = {
        "dry_run": True,
        "cache_root": "res://.godot",
        "engine_pass": False,
        "assets": [],
        "summary": {
            "requested": 0,
            "cached": 0,
            "missing": 0,
            "imported": 0,
            "not_importable": 0,
            "failed": 0,
            "created_cache_owned": 0,
            "created_source_adjacent": 0,
        },
    }
    ResourceImportResult.model_validate(base)  # a coherent dry run passes
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate(
            {
                **base,
                "created": [{"path": "res://x", "classification": "cache_owned"}],
            }
        )
    with pytest.raises(pydantic.ValidationError):
        ResourceImportResult.model_validate(
            {**base, "summary": {**base["summary"], "requested": 5}}
        )
