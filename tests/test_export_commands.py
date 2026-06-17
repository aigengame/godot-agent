"""S3: gda export list / export get success paths against a fake runner (issue #114).

The export command group is read-only discovery: ``export list`` enumerates the
project's export presets (from export_presets.cfg) and ``export get`` reports one
preset's details plus export-template install status. These tests drive the same
proven pipeline as the scene/node/script groups — Typer → binary resolution →
runner → sentinel parse → typed model → JSON — with canned engine output, no
real Godot. This slice never runs an actual export (that is issue #121).
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import (
    EXPORT_GET_RESULT as GET_RESULT,
    EXPORT_LIST_RESULT as LIST_RESULT,
    FakeRunner,
    inject_runner,
    sentinel,
)


def test_export_list_json_enumerates_presets_and_exit_zero(monkeypatch, tmp_path):
    # export list enumerates the resolved project's export presets (issue #114):
    # each entry carries its index, name, platform, and runnable flag, read
    # cheaply from export_presets.cfg.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(LIST_RESULT)
    fake = inject_runner(
        monkeypatch, RunResult(stdout=stdout, stderr="engine diagnostic\n", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["export", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [p["name"] for p in data["presets"]] == ["Linux/X11", "Web"]
    assert data["presets"][0]["platform"] == "Linux/X11"
    assert data["presets"][0]["runnable"] is True
    assert data["presets"][1]["index"] == 1
    assert data["presets"][1]["runnable"] is False
    # export list takes no operation params: the project is process context.
    assert fake.calls == [("export-list", {})]
    assert "engine diagnostic" in result.stderr


def test_export_list_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # export list reads export_presets.cfg in the resolved project, so --project
    # must reach the runner (which hands it to the engine as --path, issue #32).
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    seen: dict = {}

    def record(binary, project):
        seen["project"] = project
        return FakeRunner(RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0))

    monkeypatch.setattr("gda.cli._make_runner", record)

    result = CliRunner().invoke(
        app, ["export", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert seen["project"] == tmp_path


def test_export_get_json_reports_preset_details_and_template_status(monkeypatch):
    # export get reports a named preset's details plus export-template readiness
    # (issue #114): the preset is addressed by --preset (its display name), and
    # the result carries templates_installed/templates_version so an agent can
    # check readiness before an export run.
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(GET_RESULT)
    fake = inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(
        app, ["export", "get", "--preset", "Web", "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "Web"
    assert data["platform"] == "Web"
    assert data["export_path"] == "build/index.html"
    assert data["templates_installed"] is True
    assert data["templates_version"] == "4.6.3.stable"
    # The preset name rides through as the typed param.
    assert fake.calls == [("export-get", {"preset": "Web"})]


def test_export_get_missing_preset_flag_is_a_usage_error(monkeypatch):
    # --preset is required: export get always needs a preset to address. Its
    # absence is a usage error (exit 2) that fires before any dispatch.
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(GET_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(app, ["export", "get", "--json"])

    assert result.exit_code == 2
    assert fake.calls == []


def test_export_get_templates_missing_rides_through_false(monkeypatch):
    # When the running engine version's templates are not installed,
    # templates_installed=false rides through to the result so the agent knows it
    # must install templates before an export run.
    payload = {**GET_RESULT, "templates_installed": False, "export_path": ""}
    stdout = "Godot Engine v4.6.3.stable.official\n" + sentinel(payload)
    inject_runner(monkeypatch, RunResult(stdout=stdout, stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["export", "get", "--preset", "Web", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["templates_installed"] is False
    assert data["templates_version"] == "4.6.3.stable"
