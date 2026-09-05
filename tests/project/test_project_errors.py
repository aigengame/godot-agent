"""S3: gda project failure modes map to structured JSON errors + stable exit codes.

Issue #111's acceptance: project-command failures (missing/invalid project,
unknown setting key, uncoercible value) surface as structured ``GdaError``s with
registered operation codes (ADR-0002) — exit 4 for the operation category, finer
stable codes so an agent branches on the mode without parsing prose.
"""

from tests.support import assert_operation_error, invoke_operation_error


def test_project_info_without_project_maps_to_project_not_found(monkeypatch):
    # project info reads ProjectSettings, so a projectless run would report only
    # the engine's bare defaults — refused with project_not_found instead.
    result = invoke_operation_error(
        monkeypatch,
        ["project", "info", "--json"],
        "project_not_found",
        "project info requires a Godot project; none was resolved",
    )

    assert_operation_error(
        result,
        "project_not_found",
        "Godot project",
        diagnostics="gda: running operation\n",
    )


def test_project_get_unknown_setting_maps_to_stable_unknown_setting_code(monkeypatch):
    # A typo'd / absent setting key is unknown_setting, distinct from a setting
    # genuinely holding null — the agent fixes the key, not the value.
    result = invoke_operation_error(
        monkeypatch,
        ["project", "get", "application/bogus/key", "--json"],
        "unknown_setting",
        "project setting not found: application/bogus/key",
    )

    assert_operation_error(result, "unknown_setting", "application/bogus/key")


def test_project_set_unknown_setting_maps_to_stable_unknown_setting_code(monkeypatch):
    # set edits an existing setting; an unknown key is unknown_setting, never a
    # silent create.
    result = invoke_operation_error(
        monkeypatch,
        ["project", "set", "application/bogus/key", "--value", "1", "--json"],
        "unknown_setting",
        "project setting not found: application/bogus/key — project set edits an "
        "existing setting; it never creates one",
    )

    assert_operation_error(result, "unknown_setting", "never creates")


def test_project_set_uncoercible_value_maps_to_stable_uncoercible_value_code(
    monkeypatch,
):
    # A value that cannot be coerced to the setting's declared type reuses the
    # node-set #55 code: uncoercible_value (exit 4, project.godot untouched).
    result = invoke_operation_error(
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

    assert_operation_error(result, "uncoercible_value", "not-a-number")
