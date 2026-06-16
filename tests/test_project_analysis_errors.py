"""S3: gda project static-analysis failure modes map to structured GdaErrors (issue #116).

Issue #116's acceptance: failures (missing/invalid project, bad target for
find-references) surface as structured ``GdaError``s with registered operation
codes (ADR-0002) — exit 4 for the operation category, finer stable codes so an
agent branches on the mode without parsing prose. The project group reuses
``project_not_found`` (the res:// enumeration code scene/script list already use)
and mints ``invalid_target`` for a bad find-references target.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _assert_structured_operation_error(result, code: str) -> None:
    assert result.exit_code == 4, result.stdout
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code


def test_dependencies_without_project_is_project_not_found(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(
                "project_not_found",
                "project dependencies requires a Godot project; none was resolved",
            ),
            stderr="gda: running operation: project-dependencies\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["project", "dependencies", "--json"])

    _assert_structured_operation_error(result, "project_not_found")


def test_find_unused_without_project_is_project_not_found(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("project_not_found", "no project resolved"),
            stderr="",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["project", "find-unused-resources", "--json"])

    _assert_structured_operation_error(result, "project_not_found")


def test_statistics_without_project_is_project_not_found(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("project_not_found", "no project resolved"),
            stderr="",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["project", "statistics", "--json"])

    _assert_structured_operation_error(result, "project_not_found")


def test_find_references_without_project_is_project_not_found(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout=error_sentinel("project_not_found", "no project resolved"),
            stderr="",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(
        app, ["project", "find-references", "res://hero.gd", "--json"]
    )

    _assert_structured_operation_error(result, "project_not_found")


def test_find_references_bad_target_is_invalid_target(monkeypatch):
    # A bad find-references target (empty, or not a res:// path / class_name)
    # surfaces as the registered invalid_target operation code.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(
                "invalid_target",
                "find-references target is not a res:// path or class_name: /abs/path",
            ),
            stderr="gda: running operation: project-find-references\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(
        app, ["project", "find-references", "/abs/path", "--json"]
    )

    _assert_structured_operation_error(result, "invalid_target")
