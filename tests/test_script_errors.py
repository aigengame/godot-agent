"""S3: gda script failure modes map to structured JSON errors + stable exit codes.

Issue #110's acceptance: script-command failures (path collision on create,
script not found on get, invalid target path / wrong extension) surface as
structured ``GdaError``s with registered operation codes (ADR-0002) — exit 4
for the operation category, finer stable codes so an agent can branch on the
mode without parsing prose. The script group reuses the existing file-level
codes rather than minting parallel ones.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke_script_create(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-create\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(
        app, ["script", "create", "/x/hero.gd", "--json"]
    )


def _invoke_script_get(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-get\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["script", "get", "/x/hero.gd", "--json"])


def _invoke_script_list(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-list\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["script", "list", "--json"])


def _invoke_script_delete(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-delete\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["script", "delete", "/x/hero.gd", "--json"])


def test_script_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene create uses), leaving the file
    # untouched — the script group mints no parallel collision code.
    result = _invoke_script_create(
        monkeypatch, "already_exists", "script target already exists: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"
    assert "/x/hero.gd" in err["message"]
    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert err["diagnostics"] == "gda: running operation: script-create\n"


def test_script_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    # A target that is not a .gd script is an invalid path param — reuse the
    # registered invalid_path code rather than a focused per-group code.
    result = _invoke_script_create(
        monkeypatch,
        "invalid_path",
        "script path must end in .gd: /x/hero.txt",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]


def test_script_create_missing_path_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke_script_create(
        monkeypatch, "invalid_path", "missing required param: path"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"


def test_script_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _invoke_script_create(
        monkeypatch, "save_failed", "failed to save script to /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "save_failed"
    assert "/x/hero.gd" in err["message"]


def test_script_get_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # A script that does not exist reuses the registered path_not_found code
    # (now generalized in the registry from scene-specific to any file), so an
    # agent branches on the missing-file mode without a new code.
    result = _invoke_script_get(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/hero.gd" in err["message"]


def test_script_get_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke_script_get(
        monkeypatch,
        "invalid_path",
        "script path must end in .gd: /x/notes.txt",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]


def test_script_list_without_project_reuses_stable_project_not_found_code(monkeypatch):
    # script list enumerates res:// in a project, so it cannot run projectless
    # (issue #117): with no resolvable project, the operation reuses the
    # registered project_not_found code (the same one scene list uses) so an
    # agent knows to pass --project rather than retry.
    result = _invoke_script_list(
        monkeypatch,
        "project_not_found",
        "script list requires a Godot project; none was resolved — pass --project",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "project_not_found"
    assert "--project" in err["message"]


def test_script_delete_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # A script that does not exist reuses the registered path_not_found code (the
    # same one script get uses), so an agent branches on the missing-file mode
    # without a new code.
    result = _invoke_script_delete(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/hero.gd" in err["message"]


def test_script_delete_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    # delete only removes a .gd script, so a non-.gd target is refused with the
    # registered invalid_path code — the same addressing boundary create/get use.
    result = _invoke_script_delete(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]


def test_script_delete_unlink_failure_reuses_stable_delete_failed_code(monkeypatch):
    # The op found the script but the underlying unlink/remove failed (a
    # read-only filesystem, a permission boundary): this maps to the stable
    # delete_failed code (the same one scene delete uses) so an agent can tell
    # "deletion was blocked" apart from other failures.
    result = _invoke_script_delete(
        monkeypatch,
        "delete_failed",
        "failed to delete script /x/hero.gd: Permission denied",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "delete_failed"
    assert "/x/hero.gd" in err["message"]
