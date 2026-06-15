"""S3: gda export failure modes map to structured JSON errors + stable exit codes.

Issue #114's acceptance: export-command failures (no export_presets.cfg, unknown
preset, no resolvable project) surface as structured ``GdaError``s with
registered operation codes (ADR-0002) — exit 4 for the operation category, finer
stable codes so an agent can branch on the mode without parsing prose. The export
group mints two new codes for the modes that had no existing code
(``export_presets_not_found``, ``export_preset_not_found``) and reuses the shared
``project_not_found`` for the projectless mode.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke_export_list(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: export-list\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["export", "list", "--json"])


def _invoke_export_get(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: export-get\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["export", "get", "--preset", "Web", "--json"])


def test_export_list_no_export_presets_maps_to_export_presets_not_found(monkeypatch):
    # A project that has never configured an export has no export_presets.cfg:
    # this is the new export_presets_not_found code (distinct from a generic
    # missing-path), so an agent knows the project defines no presets rather than
    # mistaking it for an empty listing.
    result = _invoke_export_list(
        monkeypatch,
        "export_presets_not_found",
        "project has no export_presets.cfg; no export presets are defined",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "export_presets_not_found"
    assert "export_presets.cfg" in err["message"]
    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert err["diagnostics"] == "gda: running operation: export-list\n"


def test_export_list_without_project_reuses_stable_project_not_found_code(monkeypatch):
    # export list reads export_presets.cfg in a project, so it cannot run
    # projectless: with no resolvable project, the operation reuses the registered
    # project_not_found code (the same one scene/script list use) so an agent
    # knows to pass --project rather than retry.
    result = _invoke_export_list(
        monkeypatch,
        "project_not_found",
        "export list requires a Godot project; none was resolved — pass --project",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "project_not_found"
    assert "--project" in err["message"]


def test_export_get_unknown_preset_maps_to_export_preset_not_found(monkeypatch):
    # A preset name not present in export_presets.cfg is the new
    # export_preset_not_found code, so an agent branches on the unknown-preset
    # mode (and re-lists to find the real names) without parsing prose.
    result = _invoke_export_get(
        monkeypatch, "export_preset_not_found", "no export preset named: Web"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "export_preset_not_found"
    assert "Web" in err["message"]
    assert err["diagnostics"] == "gda: running operation: export-get\n"


def test_export_get_no_export_presets_maps_to_export_presets_not_found(monkeypatch):
    # export get over a project with no export_presets.cfg reports the same
    # export_presets_not_found mode as export list — there is nothing to address.
    result = _invoke_export_get(
        monkeypatch,
        "export_presets_not_found",
        "project has no export_presets.cfg; no export presets are defined",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "export_presets_not_found"


def test_export_get_without_project_reuses_stable_project_not_found_code(monkeypatch):
    result = _invoke_export_get(
        monkeypatch,
        "project_not_found",
        "export get requires a Godot project; none was resolved — pass --project",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "project_not_found"
    assert "--project" in err["message"]
