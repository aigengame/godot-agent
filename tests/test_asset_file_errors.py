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

from tests.support import assert_operation_error, operation_error_invoker

_shader_create = operation_error_invoker(
    ["shader", "create", "/x/wave.gdshader", "--json"], "shader-create"
)

_shader_get = operation_error_invoker(
    ["shader", "get", "/x/wave.gdshader", "--json"], "shader-get"
)

_shader_set = operation_error_invoker(
    ["shader", "set", "/x/wave.gdshader", "--search", "a", "--replace", "b", "--json"],
    "shader-set",
)

_theme_create = operation_error_invoker(
    ["theme", "create", "/x/ui.tres", "--json"], "theme-create"
)


# --- shader create: path collision (no-clobber) + wrong extension ----------


def test_shader_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene/script create use), leaving the
    # file untouched — the shader group mints no parallel collision code.
    result = _shader_create(
        monkeypatch, "already_exists", "shader target already exists: /x/wave.gdshader"
    )

    assert_operation_error(
        result,
        "already_exists",
        "/x/wave.gdshader",
        diagnostics="gda: running operation: shader-create\n",
    )


def test_shader_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _shader_create(
        monkeypatch, "invalid_path", "shader path must end in .gdshader: /x/wave.txt"
    )

    assert_operation_error(result, "invalid_path", ".gdshader")


def test_shader_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _shader_create(
        monkeypatch, "save_failed", "failed to save shader to /x/wave.gdshader"
    )

    assert_operation_error(result, "save_failed")


# --- shader get/set: file not found + wrong extension ----------------------


def test_shader_get_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    result = _shader_get(
        monkeypatch, "path_not_found", "shader file does not exist: /x/wave.gdshader"
    )

    assert_operation_error(result, "path_not_found", "/x/wave.gdshader")


def test_shader_get_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _shader_get(
        monkeypatch, "invalid_path", "shader path must end in .gdshader: /x/notes.txt"
    )

    assert_operation_error(result, "invalid_path")


def test_shader_set_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # set edits an existing shader; a missing target is path_not_found, never a
    # silent create (the same rule as script set).
    result = _shader_set(
        monkeypatch, "path_not_found", "shader file does not exist: /x/wave.gdshader"
    )

    assert_operation_error(result, "path_not_found")


# --- shader set: bad edit range / no search-replace match (reused codes) ----


def test_shader_set_no_search_match_maps_to_stable_no_search_match_code(monkeypatch):
    # search-replace mode: a search string the source does not contain is the
    # registered no_search_match code (reused from script set), so an agent
    # learns the edit landed nowhere rather than parsing prose.
    result = _shader_set(
        monkeypatch, "no_search_match", 'search string not found in shader: "xyzzy"'
    )

    assert_operation_error(result, "no_search_match", "xyzzy")


def test_shader_set_invalid_line_range_maps_to_stable_invalid_line_range_code(
    monkeypatch,
):
    result = _shader_set(
        monkeypatch,
        "invalid_line_range",
        "line range 5..9 is outside the shader's bounds (1..3) or ends before it starts",
    )

    assert_operation_error(result, "invalid_line_range", "1..3")


# --- theme create: path collision + wrong extension ------------------------


def test_theme_create_collision_reuses_stable_already_exists_code(monkeypatch):
    result = _theme_create(
        monkeypatch, "already_exists", "theme target already exists: /x/ui.tres"
    )

    assert_operation_error(result, "already_exists", "/x/ui.tres")


def test_theme_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _theme_create(
        monkeypatch, "invalid_path", "theme path must end in .tres: /x/ui.txt"
    )

    assert_operation_error(result, "invalid_path", ".tres")


def test_theme_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _theme_create(
        monkeypatch, "save_failed", "failed to save theme to /x/ui.tres"
    )

    assert_operation_error(result, "save_failed")
