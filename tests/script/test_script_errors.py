"""S3: gda script failure modes map to structured JSON errors + stable exit codes.

Issue #110's acceptance: script-command failures (path collision on create,
script not found on get, invalid target path / wrong extension) surface as
structured ``GdaError``s with registered operation codes (ADR-0002) — exit 4
for the operation category, finer stable codes so an agent can branch on the
mode without parsing prose. The script group reuses the existing file-level
codes rather than minting parallel ones.
"""

from tests.support import assert_operation_error, operation_error_invoker


_script_create = operation_error_invoker(
    ["script", "create", "/x/hero.gd", "--json"],
    "script-create",
)


_script_get = operation_error_invoker(
    ["script", "get", "/x/hero.gd", "--json"],
    "script-get",
)


_script_list = operation_error_invoker(
    ["script", "list", "--json"],
    "script-list",
)


_script_delete = operation_error_invoker(
    ["script", "delete", "/x/hero.gd", "--json"],
    "script-delete",
)


def test_script_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene create uses), leaving the file
    # untouched — the script group mints no parallel collision code.
    result = _script_create(
        monkeypatch, "already_exists", "script target already exists: /x/hero.gd"
    )

    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert_operation_error(
        result,
        "already_exists",
        "/x/hero.gd",
        diagnostics="gda: running operation: script-create\n",
    )


def test_script_create_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    # A target that is not a .gd script is an invalid path param — reuse the
    # registered invalid_path code rather than a focused per-group code.
    result = _script_create(
        monkeypatch,
        "invalid_path",
        "script path must end in .gd: /x/hero.txt",
    )

    assert_operation_error(result, "invalid_path", ".gd")


def test_script_create_missing_path_reuses_stable_invalid_path_code(monkeypatch):
    result = _script_create(monkeypatch, "invalid_path", "missing required param: path")

    assert_operation_error(result, "invalid_path")


def test_script_create_unwritable_target_reuses_stable_save_failed_code(monkeypatch):
    result = _script_create(
        monkeypatch, "save_failed", "failed to save script to /x/hero.gd"
    )

    assert_operation_error(result, "save_failed", "/x/hero.gd")


def test_script_get_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # A script that does not exist reuses the registered path_not_found code
    # (now generalized in the registry from scene-specific to any file), so an
    # agent branches on the missing-file mode without a new code.
    result = _script_get(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert_operation_error(result, "path_not_found", "/x/hero.gd")


def test_script_get_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _script_get(
        monkeypatch,
        "invalid_path",
        "script path must end in .gd: /x/notes.txt",
    )

    assert_operation_error(result, "invalid_path", ".gd")


def test_script_list_without_project_reuses_stable_project_not_found_code(monkeypatch):
    # script list enumerates res:// in a project, so it cannot run projectless
    # (issue #117): with no resolvable project, the operation reuses the
    # registered project_not_found code (the same one scene list uses) so an
    # agent knows to pass --project rather than retry.
    result = _script_list(
        monkeypatch,
        "project_not_found",
        "script list requires a Godot project; none was resolved — pass --project",
    )

    assert_operation_error(result, "project_not_found", "--project")


def test_script_delete_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # A script that does not exist reuses the registered path_not_found code (the
    # same one script get uses), so an agent branches on the missing-file mode
    # without a new code.
    result = _script_delete(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert_operation_error(result, "path_not_found", "/x/hero.gd")


def test_script_delete_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    # delete only removes a .gd script, so a non-.gd target is refused with the
    # registered invalid_path code — the same addressing boundary create/get use.
    result = _script_delete(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert_operation_error(result, "invalid_path", ".gd")


def test_script_delete_unlink_failure_reuses_stable_delete_failed_code(monkeypatch):
    # The op found the script but the underlying unlink/remove failed (a
    # read-only filesystem, a permission boundary): this maps to the stable
    # delete_failed code (the same one scene delete uses) so an agent can tell
    # "deletion was blocked" apart from other failures.
    result = _script_delete(
        monkeypatch,
        "delete_failed",
        "failed to delete script /x/hero.gd: Permission denied",
    )

    assert_operation_error(result, "delete_failed", "/x/hero.gd")


_script_set = operation_error_invoker(
    ["script", "set", "/x/hero.gd", "--search", "a", "--replace", "b", "--json"],
    "script-set",
)


def test_script_set_no_search_match_maps_to_stable_no_search_match_code(monkeypatch):
    # search-replace mode (issue #118): a search string the source does not
    # contain is a new no_search_match code, so an agent learns the edit landed
    # nowhere (and the file was left untouched) rather than parsing prose.
    result = _script_set(
        monkeypatch, "no_search_match", 'search string not found in script: "xyzzy"'
    )

    assert_operation_error(
        result,
        "no_search_match",
        "xyzzy",
        diagnostics="gda: running operation: script-set\n",
    )


def test_script_set_invalid_line_range_maps_to_stable_invalid_line_range_code(
    monkeypatch,
):
    # line-range mode: a range outside the script's bounds (or end before start)
    # is a new invalid_line_range code, distinct from no_search_match, so an
    # agent knows the line numbers — not the search string — are the problem.
    result = _script_set(
        monkeypatch,
        "invalid_line_range",
        "line range 5..9 is outside the script's bounds (1..3) or ends before it starts",
    )

    assert_operation_error(result, "invalid_line_range", "1..3")


def test_script_set_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # set edits an existing script; a missing target is path_not_found (the same
    # one get/delete use), never a silent create.
    result = _script_set(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert_operation_error(result, "path_not_found", "/x/hero.gd")


def test_script_set_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _script_set(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert_operation_error(result, "invalid_path", ".gd")


_script_attach = operation_error_invoker(
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
    "script-attach",
)


def test_script_attach_missing_script_reuses_stable_path_not_found_code(monkeypatch):
    # attach binds an existing script; a missing .gd is path_not_found (the same
    # one script get uses) so an agent knows the script file, not the scene, is
    # the thing that's missing.
    result = _script_attach(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert_operation_error(
        result,
        "path_not_found",
        "/x/hero.gd",
        diagnostics="gda: running operation: script-attach\n",
    )


def test_script_attach_wrong_script_extension_reuses_stable_invalid_path_code(
    monkeypatch,
):
    # A non-.gd script target is refused with invalid_path — the same addressing
    # boundary the rest of the script group uses.
    result = _script_attach(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert_operation_error(result, "invalid_path", ".gd")


def test_script_attach_missing_node_reuses_stable_node_not_found_code(monkeypatch):
    # The scene loaded but the node path resolves to nothing — node_not_found
    # (the same one node get/set use), distinct from the file-level path_not_found.
    result = _script_attach(
        monkeypatch, "node_not_found", "node not found in scene: Hero"
    )

    assert_operation_error(result, "node_not_found", "Hero")


def test_script_attach_missing_scene_reuses_stable_path_not_found_code(monkeypatch):
    # The scene-file-level failure reuses the registered scene code; attach
    # introduces no parallel code for the same mode.
    result = _script_attach(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert_operation_error(result, "path_not_found", "/x/main.tscn")


def test_script_attach_unloadable_resource_reuses_stable_invalid_path_code(monkeypatch):
    # A .gd that cannot even be loaded AS A RESOURCE (a genuine load failure, not
    # a compile error — load returns non-null for a non-compiling script) is the
    # defensive invalid_path branch, naming the path.
    result = _script_attach(
        monkeypatch,
        "invalid_path",
        "file could not be loaded as a GDScript resource: /x/hero.gd",
    )

    assert_operation_error(result, "invalid_path", "/x/hero.gd")


def test_script_attach_non_compiling_script_uses_script_compile_failed_code(
    monkeypatch,
):
    # A .gd that loads but does not COMPILE cannot be bound: the headless engine
    # silently rejects it from set_script, so attach refuses with the focused
    # script_compile_failed code rather than report a phantom success over a
    # scene with nothing attached.
    result = _script_attach(
        monkeypatch,
        "script_compile_failed",
        "script does not compile, so it cannot be attached: /x/hero.gd",
    )

    assert_operation_error(result, "script_compile_failed", "/x/hero.gd")


def test_script_attach_incompatible_type_uses_incompatible_script_type_code(
    monkeypatch,
):
    # A script that COMPILES but whose native base is incompatible with the node
    # (e.g. an `extends Node3D` script onto a Node2D) is bounced by set_script for
    # a different reason than a compile error — attach reports the distinct
    # incompatible_script_type code so the agent fixes the node/script pairing
    # rather than chasing a non-existent syntax error.
    result = _script_attach(
        monkeypatch,
        "incompatible_script_type",
        "script extends Node3D, which is incompatible with node Hero of type Node2D",
    )

    err = assert_operation_error(result, "incompatible_script_type", "Node3D")
    assert "Node2D" in err["message"]


_script_validate = operation_error_invoker(
    ["script", "validate", "/x/hero.gd", "--json"],
    "script-validate",
)


def test_script_validate_missing_file_reuses_stable_path_not_found_code(monkeypatch):
    # validate only op-fails (non-zero) for op errors. A missing file is
    # path_not_found (the same one get/set use); an INVALID script is NOT a
    # failure — it is a successful op reporting valid=false (covered in S3 success).
    result = _script_validate(
        monkeypatch, "path_not_found", "script file does not exist: /x/hero.gd"
    )

    assert_operation_error(
        result,
        "path_not_found",
        "/x/hero.gd",
        diagnostics="gda: running operation: script-validate\n",
    )


def test_script_validate_wrong_extension_reuses_stable_invalid_path_code(monkeypatch):
    result = _script_validate(
        monkeypatch, "invalid_path", "script path must end in .gd: /x/notes.txt"
    )

    assert_operation_error(result, "invalid_path", ".gd")
