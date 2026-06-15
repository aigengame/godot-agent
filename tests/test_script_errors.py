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


def _invoke_script_set(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-set\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(
        app,
        ["script", "set", "/x/hero.gd", "--search", "a", "--replace", "b", "--json"],
    )


def test_script_set_no_search_match_maps_to_stable_no_search_match_code(monkeypatch):
    # search-replace mode (issue #118): a search string the source does not
    # contain is a new no_search_match code, so an agent learns the edit landed
    # nowhere (and the file was left untouched) rather than parsing prose.
    result = _invoke_script_set(
        monkeypatch, "no_search_match", "search string not found in script: \"xyzzy\""
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "no_search_match"
    assert "xyzzy" in err["message"]
    assert err["diagnostics"] == "gda: running operation: script-set\n"


def test_script_set_invalid_line_range_maps_to_stable_invalid_line_range_code(
    monkeypatch,
):
    # line-range mode: a range outside the script's bounds (or end before start)
    # is a new invalid_line_range code, distinct from no_search_match, so an
    # agent knows the line numbers — not the search string — are the problem.
    result = _invoke_script_set(
        monkeypatch,
        "invalid_line_range",
        "line range 5..9 is outside the script's bounds (1..3) or ends before it starts",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_line_range"
    assert "1..3" in err["message"]


def test_script_set_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # set edits an existing script; a missing target is path_not_found (the same
    # one get/delete use), never a silent create.
    result = _invoke_script_set(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/hero.gd" in err["message"]


def test_script_set_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke_script_set(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]


def _invoke_script_attach(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-attach\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(
        app,
        [
            "script",
            "attach",
            "/x/main.tscn",
            "--node",
            "Hero",
            "--script",
            "/x/hero.gd",
            "--json",
        ],
    )


def test_script_attach_missing_script_reuses_stable_path_not_found_code(monkeypatch):
    # attach binds an existing script; a missing .gd is path_not_found (the same
    # one script get uses) so an agent knows the script file, not the scene, is
    # the thing that's missing.
    result = _invoke_script_attach(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/hero.gd" in err["message"]
    assert err["diagnostics"] == "gda: running operation: script-attach\n"


def test_script_attach_wrong_script_extension_reuses_stable_invalid_path_code(
    monkeypatch,
):
    # A non-.gd script target is refused with invalid_path — the same addressing
    # boundary the rest of the script group uses.
    result = _invoke_script_attach(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]


def test_script_attach_missing_node_reuses_stable_node_not_found_code(monkeypatch):
    # The scene loaded but the node path resolves to nothing — node_not_found
    # (the same one node get/set use), distinct from the file-level path_not_found.
    result = _invoke_script_attach(
        monkeypatch, "node_not_found", "node not found in scene: Hero"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "node_not_found"
    assert "Hero" in err["message"]


def test_script_attach_missing_scene_reuses_stable_path_not_found_code(monkeypatch):
    # The scene-file-level failure reuses the registered scene code; attach
    # introduces no parallel code for the same mode.
    result = _invoke_script_attach(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/main.tscn" in err["message"]


def test_script_attach_unloadable_resource_reuses_stable_invalid_path_code(monkeypatch):
    # A .gd that cannot even be loaded AS A RESOURCE (a genuine load failure, not
    # a compile error — load returns non-null for a non-compiling script) is the
    # defensive invalid_path branch, naming the path.
    result = _invoke_script_attach(
        monkeypatch,
        "invalid_path",
        "file could not be loaded as a GDScript resource: /x/hero.gd",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert "/x/hero.gd" in err["message"]


def test_script_attach_non_compiling_script_uses_script_compile_failed_code(monkeypatch):
    # A .gd that loads but does not COMPILE cannot be bound: the headless engine
    # silently rejects it from set_script, so attach refuses with the focused
    # script_compile_failed code rather than report a phantom success over a
    # scene with nothing attached.
    result = _invoke_script_attach(
        monkeypatch,
        "script_compile_failed",
        "script does not compile, so it cannot be attached: /x/hero.gd",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "script_compile_failed"
    assert "/x/hero.gd" in err["message"]


def test_script_attach_incompatible_type_uses_incompatible_script_type_code(monkeypatch):
    # A script that COMPILES but whose native base is incompatible with the node
    # (e.g. an `extends Node3D` script onto a Node2D) is bounced by set_script for
    # a different reason than a compile error — attach reports the distinct
    # incompatible_script_type code so the agent fixes the node/script pairing
    # rather than chasing a non-existent syntax error.
    result = _invoke_script_attach(
        monkeypatch,
        "incompatible_script_type",
        "script extends Node3D, which is incompatible with node Hero of type Node2D",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "incompatible_script_type"
    assert "Node3D" in err["message"]
    assert "Node2D" in err["message"]


def _invoke_script_validate(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: script-validate\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["script", "validate", "/x/hero.gd", "--json"])


def test_script_validate_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # validate only op-fails (non-zero) for op errors. A missing file is
    # path_not_found (the same one get/set use); an INVALID script is NOT a
    # failure — it is a successful op reporting valid=false (covered in S3 success).
    result = _invoke_script_validate(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/hero.gd" in err["message"]
    assert err["diagnostics"] == "gda: running operation: script-validate\n"


def test_script_validate_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke_script_validate(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_path"
    assert ".gd" in err["message"]
