"""S3: gda project static-analysis failure modes map to structured GdaErrors (issue #116).

Issue #116's acceptance: failures (missing/invalid project, bad target for
find-references) surface as structured ``GdaError``s with registered operation
codes (ADR-0002) — exit 4 for the operation category, finer stable codes so an
agent branches on the mode without parsing prose. The project group reuses
``project_not_found`` (the res:// enumeration code scene/script list already use)
and mints ``invalid_target`` for a bad find-references target.
"""

from tests.support import assert_operation_error, invoke_operation_error


def test_dependencies_without_project_is_project_not_found(monkeypatch):
    result = invoke_operation_error(
        monkeypatch,
        ["project", "dependencies", "--json"],
        "project_not_found",
        "project dependencies requires a Godot project; none was resolved",
        "project-dependencies",
    )

    assert_operation_error(result, "project_not_found")


def test_find_unused_without_project_is_project_not_found(monkeypatch):
    result = invoke_operation_error(
        monkeypatch,
        ["project", "find-unused-resources", "--json"],
        "project_not_found",
        "no project resolved",
        "project-find-unused-resources",
    )

    assert_operation_error(result, "project_not_found")


def test_statistics_without_project_is_project_not_found(monkeypatch):
    result = invoke_operation_error(
        monkeypatch,
        ["project", "statistics", "--json"],
        "project_not_found",
        "no project resolved",
        "project-statistics",
    )

    assert_operation_error(result, "project_not_found")


def test_find_references_without_project_is_project_not_found(monkeypatch):
    result = invoke_operation_error(
        monkeypatch,
        ["project", "find-references", "res://hero.gd", "--json"],
        "project_not_found",
        "no project resolved",
        "project-find-references",
    )

    assert_operation_error(result, "project_not_found")


def test_find_references_bad_target_is_invalid_target(monkeypatch):
    # A bad find-references target (empty, or not a res:// path / class_name)
    # surfaces as the registered invalid_target operation code.
    result = invoke_operation_error(
        monkeypatch,
        ["project", "find-references", "/abs/path", "--json"],
        "invalid_target",
        "find-references target is not a res:// path or class_name: /abs/path",
        "project-find-references",
    )

    assert_operation_error(result, "invalid_target")
