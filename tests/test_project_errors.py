"""S3: gda project failure modes map to structured JSON errors + stable exit codes.

Issue #111's acceptance: project-command failures (missing/invalid project,
unknown setting key, uncoercible value) surface as structured ``GdaError``s with
registered operation codes (ADR-0002) — exit 4 for the operation category, finer
stable codes so an agent branches on the mode without parsing prose.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke(monkeypatch, args, code, message, stderr="gda: running operation\n"):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr=stderr,
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, args)


def test_project_info_without_project_maps_to_project_not_found(monkeypatch):
    # project info reads ProjectSettings, so a projectless run would report only
    # the engine's bare defaults — refused with project_not_found instead.
    result = _invoke(
        monkeypatch,
        ["project", "info", "--json"],
        "project_not_found",
        "project info requires a Godot project; none was resolved",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "project_not_found"
    assert "Godot project" in err["message"]
    assert err["diagnostics"] == "gda: running operation\n"


def test_project_get_unknown_setting_maps_to_stable_unknown_setting_code(monkeypatch):
    # A typo'd / absent setting key is unknown_setting, distinct from a setting
    # genuinely holding null — the agent fixes the key, not the value.
    result = _invoke(
        monkeypatch,
        ["project", "get", "application/bogus/key", "--json"],
        "unknown_setting",
        "project setting not found: application/bogus/key",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "unknown_setting"
    assert "application/bogus/key" in err["message"]


def test_project_set_unknown_setting_maps_to_stable_unknown_setting_code(monkeypatch):
    # set edits an existing setting; an unknown key is unknown_setting, never a
    # silent create.
    result = _invoke(
        monkeypatch,
        ["project", "set", "application/bogus/key", "--value", "1", "--json"],
        "unknown_setting",
        "project setting not found: application/bogus/key — project set edits an "
        "existing setting; it never creates one",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "unknown_setting"
    assert "never creates" in err["message"]


def test_project_set_uncoercible_value_maps_to_stable_uncoercible_value_code(
    monkeypatch,
):
    # A value that cannot be coerced to the setting's declared type reuses the
    # node-set #55 code: uncoercible_value (exit 4, project.godot untouched).
    result = _invoke(
        monkeypatch,
        [
            "project",
            "set",
            "display/window/size/viewport_width",
            "--value",
            "not-a-number",
            "--json",
        ],
        "uncoercible_value",
        "cannot coerce value not-a-number to int for project setting "
        "display/window/size/viewport_width",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "uncoercible_value"
    assert "not-a-number" in err["message"]
