"""S3: gda resource failure modes map to structured JSON errors + stable exit codes.

Issue #112's acceptance: resource-command failures surface as structured
``GdaError``s with registered operation codes (ADR-0002) — exit 4 for the
operation category, finer stable codes so an agent can branch on the mode
without parsing prose:

- path collision on create → ``already_exists`` (reused, like scene/script create)
- resource not found on get → ``path_not_found`` (reused)
- non-.tres target path → ``invalid_path`` (reused)
- invalid/unknown resource type on create → ``invalid_resource_type`` (NEW, #112)
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import error_sentinel, inject_runner


def _invoke_resource_create(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: resource-create\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(
        app, ["resource", "create", "/x/palette.tres", "--type", "Gradient", "--json"]
    )


def _invoke_resource_get(monkeypatch, code: str, message: str):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n"
            + error_sentinel(code, message),
            stderr="gda: running operation: resource-get\n",
            exit_code=1,
        ),
    )
    return CliRunner().invoke(app, ["resource", "get", "/x/palette.tres", "--json"])


def test_resource_create_collision_reuses_stable_already_exists_code(monkeypatch):
    # No-clobber: a create whose target already exists reuses the registered
    # already_exists code (the same one scene/script create use), leaving the
    # file untouched — the resource group mints no parallel collision code.
    result = _invoke_resource_create(
        monkeypatch, "already_exists", "resource target already exists: /x/palette.tres"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "already_exists"
    assert "/x/palette.tres" in err["message"]
    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert err["diagnostics"] == "gda: running operation: resource-create\n"


def test_resource_create_invalid_type_yields_invalid_resource_type(monkeypatch):
    # An unknown or non-Resource type cannot be saved as a .tres, so create
    # refuses it with the resource group's own invalid_resource_type code —
    # parallel to scene create's invalid_root_type and node add's
    # invalid_node_type, but for the Resource hierarchy.
    result = _invoke_resource_create(
        monkeypatch,
        "invalid_resource_type",
        "not an instantiable Resource class: Bogus",
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_resource_type"
    assert "Bogus" in err["message"]


def test_resource_create_non_tres_path_yields_invalid_path(monkeypatch):
    result = _invoke_resource_create(
        monkeypatch, "invalid_path", "resource path must end in .tres: /x/palette.txt"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"


def test_resource_get_missing_yields_path_not_found(monkeypatch):
    # A get on a path with no resource file reuses the registered path_not_found
    # code (the same one scene/script get use for a missing file).
    result = _invoke_resource_get(
        monkeypatch, "path_not_found", "resource file does not exist: /x/palette.tres"
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/palette.tres" in err["message"]
