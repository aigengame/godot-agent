"""S3: gda shader/theme failure modes map to structured JSON errors + exit codes.

Issue #115's acceptance: asset-file failures (path collision on create, file not
found on get/set, bad edit range / no search-replace match, wrong extension)
surface as structured ``GdaError``s with registered operation codes (ADR-0002) —
exit 4 for the operation category, finer stable codes so an agent can branch on
the mode without parsing prose. The asset-file groups REUSE the existing
file-level codes (already_exists / path_not_found / invalid_path / save_failed /
no_search_match / invalid_line_range) rather than minting parallel ones, exactly
as the script group did.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke(monkeypatch, argv, code, message, op):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n" + error_sentinel(code, message),
            stderr=f"gda: running operation: {op}\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, argv)


def _create_argv():
    return ["shader", "create", "/x/wave.gdshader", "--json"]


def _get_argv():
    return ["shader", "get", "/x/wave.gdshader", "--json"]


def _set_argv():
    return ["shader", "set", "/x/wave.gdshader", "--search", "a", "--replace", "b", "--json"]


def _theme_argv():
    return ["theme", "create", "/x/ui.tres", "--json"]


# --- shader create: path collision (no-clobber) + wrong extension ----------


def test_shader_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene/script create use), leaving the
    # file untouched — the shader group mints no parallel collision code.
    result = _invoke(
        monkeypatch, _create_argv(), "already_exists",
        "shader target already exists: /x/wave.gdshader", "shader-create",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"
    assert "/x/wave.gdshader" in err["message"]
    assert err["diagnostics"] == "gda: running operation: shader-create\n"


def test_shader_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke(
        monkeypatch, _create_argv(), "invalid_path",
        "shader path must end in .gdshader: /x/wave.txt", "shader-create",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert ".gdshader" in err["message"]


def test_shader_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _invoke(
        monkeypatch, _create_argv(), "save_failed",
        "failed to save shader to /x/wave.gdshader", "shader-create",
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "save_failed"


# --- shader get/set: file not found + wrong extension ----------------------


def test_shader_get_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    result = _invoke(
        monkeypatch, _get_argv(), "path_not_found",
        "shader file does not exist: /x/wave.gdshader", "shader-get",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/wave.gdshader" in err["message"]


def test_shader_get_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke(
        monkeypatch, _get_argv(), "invalid_path",
        "shader path must end in .gdshader: /x/notes.txt", "shader-get",
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "invalid_path"


def test_shader_set_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # set edits an existing shader; a missing target is path_not_found, never a
    # silent create (the same rule as script set).
    result = _invoke(
        monkeypatch, _set_argv(), "path_not_found",
        "shader file does not exist: /x/wave.gdshader", "shader-set",
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "path_not_found"


# --- shader set: bad edit range / no search-replace match (reused codes) ----


def test_shader_set_no_search_match_maps_to_stable_no_search_match_code(monkeypatch):
    # search-replace mode: a search string the source does not contain is the
    # registered no_search_match code (reused from script set), so an agent
    # learns the edit landed nowhere rather than parsing prose.
    result = _invoke(
        monkeypatch, _set_argv(), "no_search_match",
        'search string not found in shader: "xyzzy"', "shader-set",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "no_search_match"
    assert "xyzzy" in err["message"]


def test_shader_set_invalid_line_range_maps_to_stable_invalid_line_range_code(monkeypatch):
    result = _invoke(
        monkeypatch, _set_argv(), "invalid_line_range",
        "line range 5..9 is outside the shader's bounds (1..3) or ends before it starts",
        "shader-set",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_line_range"
    assert "1..3" in err["message"]


# --- theme create: path collision + wrong extension ------------------------


def test_theme_create_collision_reuses_stable_already_exists_code(monkeypatch):
    result = _invoke(
        monkeypatch, _theme_argv(), "already_exists",
        "theme target already exists: /x/ui.tres", "theme-create",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"
    assert "/x/ui.tres" in err["message"]


def test_theme_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _invoke(
        monkeypatch, _theme_argv(), "invalid_path",
        "theme path must end in .tres: /x/ui.txt", "theme-create",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert ".tres" in err["message"]


def test_theme_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _invoke(
        monkeypatch, _theme_argv(), "save_failed",
        "failed to save theme to /x/ui.tres", "theme-create",
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "save_failed"
