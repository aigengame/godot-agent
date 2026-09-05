"""S3: gda resource failure modes map to structured JSON errors + stable exit codes (issues #112, #113).

Issue #112's acceptance: resource-command failures surface as structured
``GdaError``s with registered operation codes (ADR-0002) — exit 4 for the
operation category, finer stable codes so an agent can branch on the mode
without parsing prose:

- path collision on create → ``already_exists`` (reused, like scene/script create)
- resource not found on get → ``path_not_found`` (reused)
- non-.tres target path → ``invalid_path`` (reused)
- invalid/unknown resource type on create → ``invalid_resource_type`` (NEW, #112)

Issue #113's acceptance: the ``resource uid`` UID-resolution failure modes — an
unknown UID, a path not found, and a path that exists but has no assigned UID —
surface the same way (exit 4, registered operation codes). A syntactically
malformed ``uid://`` adds ``invalid_uid``, and a projectless run reuses the
shared ``project_not_found``.
"""

from tests.support import assert_operation_error, operation_error_invoker


_resource_create = operation_error_invoker(
    ["resource", "create", "/x/palette.tres", "--type", "Gradient", "--json"],
    "resource-create",
)


_resource_get = operation_error_invoker(
    ["resource", "get", "/x/palette.tres", "--json"],
    "resource-get",
)


def test_resource_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene/script create use), leaving the
    # file untouched — the resource group mints no parallel collision code.
    result = _resource_create(
        monkeypatch, "already_exists", "resource target already exists: /x/palette.tres"
    )

    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert_operation_error(
        result,
        "already_exists",
        "/x/palette.tres",
        diagnostics="gda: running operation: resource-create\n",
    )


def test_resource_create_invalid_type_yields_invalid_resource_type(monkeypatch):
    # An unknown or non-Resource type cannot be saved as a .tres, so create
    # refuses it with the resource group's own invalid_resource_type code —
    # parallel to scene create's invalid_root_type and node add's
    # invalid_node_type, but for the Resource hierarchy.
    result = _resource_create(
        monkeypatch,
        "invalid_resource_type",
        "not an instantiable Resource class: Bogus",
    )

    assert_operation_error(result, "invalid_resource_type", "Bogus")


def test_resource_create_non_tres_path_yields_invalid_path(monkeypatch):
    result = _resource_create(
        monkeypatch, "invalid_path", "resource path must end in .tres: /x/palette.txt"
    )

    assert_operation_error(result, "invalid_path")


def test_resource_get_missing_yields_path_not_found(monkeypatch):
    # A get on a path with no resource file reuses the registered path_not_found
    # code (the same one scene/script get use for a missing file).
    result = _resource_get(
        monkeypatch, "path_not_found", "resource file does not exist: /x/palette.tres"
    )

    assert_operation_error(result, "path_not_found", "/x/palette.tres")


_resource_set = operation_error_invoker(
    [
        "resource",
        "set",
        "/x/palette.tres",
        "--property",
        "interpolation_mode",
        "--value",
        "1",
        "--json",
    ],
    "resource-set",
)


_resource_delete = operation_error_invoker(
    ["resource", "delete", "/x/palette.tres", "--json"],
    "resource-delete",
)


def test_resource_set_unknown_property_yields_unknown_property(monkeypatch):
    # set edits an existing property; an unknown property is unknown_property
    # (the same #55 code node set uses), never a silent create.
    result = _resource_set(
        monkeypatch,
        "unknown_property",
        "resource /x/palette.tres has no settable property: bogus",
    )

    assert_operation_error(
        result,
        "unknown_property",
        "bogus",
        diagnostics="gda: running operation: resource-set\n",
    )


def test_resource_set_uncoercible_value_yields_uncoercible_value(monkeypatch):
    # A value that cannot be coerced to the property's declared type reuses the
    # node-set #55 code: uncoercible_value (exit 4, the .tres untouched).
    result = _resource_set(
        monkeypatch,
        "uncoercible_value",
        "cannot coerce value not-a-number to int for property "
        "interpolation_mode on resource /x/palette.tres",
    )

    assert_operation_error(result, "uncoercible_value", "not-a-number")


def test_resource_set_missing_yields_path_not_found(monkeypatch):
    # A set on a path with no resource file reuses the registered path_not_found
    # code (the same one resource get uses for a missing file).
    result = _resource_set(
        monkeypatch, "path_not_found", "resource file does not exist: /x/palette.tres"
    )

    assert_operation_error(result, "path_not_found", "/x/palette.tres")


def test_resource_set_non_tres_path_yields_invalid_path(monkeypatch):
    result = _resource_set(
        monkeypatch, "invalid_path", "resource path must end in .tres: /x/palette.txt"
    )

    assert_operation_error(result, "invalid_path")


def test_resource_delete_missing_yields_path_not_found(monkeypatch):
    # A delete on a path with no resource file reuses path_not_found, so the
    # lifecycle's now-not-found is the same code a fresh get would report.
    result = _resource_delete(
        monkeypatch, "path_not_found", "resource file does not exist: /x/palette.tres"
    )

    assert_operation_error(result, "path_not_found", "/x/palette.tres")


def test_resource_delete_non_tres_path_yields_invalid_path(monkeypatch):
    result = _resource_delete(
        monkeypatch, "invalid_path", "resource path must end in .tres: /x/palette.txt"
    )

    assert_operation_error(result, "invalid_path")


_resource_uid = operation_error_invoker(
    lambda target: ["resource", "uid", target, "--json"],
    "resource-uid",
)


# The raw stderr still rides along as diagnostics (ADR-0002). Every resource uid
# test checks it, so the notice is named here and passed at each call site rather
# than hidden inside a helper's default.
_UID_NOTICE = "gda: running operation: resource-uid\n"


def test_resource_uid_unknown_uid_is_structured_error(monkeypatch):
    # A well-formed uid:// absent from the project's UID cache is unknown_uid —
    # the agent learns the UID is unregistered, not that the syntax was wrong.
    result = _resource_uid(
        monkeypatch,
        "unknown_uid",
        "UID is not registered in the project's UID cache: uid://abc",
        target="uid://abc",
    )

    assert_operation_error(result, "unknown_uid", "uid://abc", diagnostics=_UID_NOTICE)


def test_resource_uid_invalid_uid_is_structured_error(monkeypatch):
    # A syntactically malformed uid:// (engine text_to_id == INVALID_ID) is
    # invalid_uid — distinct from an unknown-but-well-formed UID.
    result = _resource_uid(
        monkeypatch,
        "invalid_uid",
        "not a valid resource UID: uid://!!!",
        target="uid://!!!",
    )

    assert_operation_error(result, "invalid_uid", "uid://!!!", diagnostics=_UID_NOTICE)


def test_resource_uid_path_not_found_is_structured_error(monkeypatch):
    # A res:// path naming no resource is path_not_found — the same registered
    # code the file groups use, not a parallel resource-specific code.
    result = _resource_uid(
        monkeypatch,
        "path_not_found",
        "no resource at path: res://missing.tres",
        target="res://missing.tres",
    )

    assert_operation_error(
        result, "path_not_found", "res://missing.tres", diagnostics=_UID_NOTICE
    )


def test_resource_uid_no_uid_assigned_is_structured_error(monkeypatch):
    # A resource that exists but carries no UID in the cache is no_uid_assigned —
    # distinct from path_not_found (the file is there) and from a UID-direction
    # failure (the query was a path).
    result = _resource_uid(
        monkeypatch,
        "no_uid_assigned",
        "resource has no UID assigned in the project's UID cache: res://plain.txt",
        target="res://plain.txt",
    )

    assert_operation_error(
        result, "no_uid_assigned", "res://plain.txt", diagnostics=_UID_NOTICE
    )


def test_resource_uid_projectless_run_is_project_not_found(monkeypatch):
    # Resolution queries the project's UID cache, so a projectless run has no
    # cache to query — refused with the shared project_not_found rather than a
    # misleading "no UID" answer.
    result = _resource_uid(
        monkeypatch,
        "project_not_found",
        "resource uid requires a Godot project; none was resolved",
        target="uid://abc",
    )

    assert_operation_error(
        result, "project_not_found", "requires a Godot project", diagnostics=_UID_NOTICE
    )
