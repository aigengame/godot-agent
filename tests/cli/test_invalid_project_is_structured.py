"""An invalid ``--project`` yields a structured GdaError across every channel (#353).

``resolve_project_dir`` RAISES ``ValueError`` for an explicit ``--project`` (or
``$GDA_PROJECT``) that is empty or is not a Godot project. gda must convert that
raise into a structured ``project_not_found`` envelope at the shared dispatch
layer — never let it escape as a Rich/Python traceback — for BOTH the sentinel
channel (``dispatch_domain``) and the recipe channel (``dispatch_recipe``), honoring
the ADR-0002 structured-output contract. This is the general, cross-cutting form
of the per-command handling ``script run`` already had (#343), now folded into
one place.
"""

import json

from typer.testing import CliRunner

from gda.cli import app


def test_sentinel_command_with_invalid_project_is_structured(tmp_path):
    # A SENTINEL command (`scene list` → dispatch_domain) with an explicit --project that
    # is not a Godot project must surface a structured project_not_found envelope,
    # not the raw ValueError traceback the un-guarded dispatch_domain would leak.
    not_a_project = tmp_path / "not-a-godot-project"
    not_a_project.mkdir()  # exists, but has no project.godot

    result = CliRunner().invoke(
        app, ["scene", "list", "--project", str(not_a_project), "--json"]
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"


def test_empty_project_is_structured():
    # An explicit but EMPTY --project is a deliberate mistake resolve_project_dir
    # raises on ("explicit project path is empty") — it, too, must be structured.
    result = CliRunner().invoke(app, ["scene", "list", "--project", "", "--json"])

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"


def test_bad_gda_project_env_is_structured(tmp_path, monkeypatch):
    # The same raise via $GDA_PROJECT precedence (no --project flag), on the recipe
    # channel: an env pointing at a non-project must also be structured.
    not_a_project = tmp_path / "env-not-a-project"
    not_a_project.mkdir()
    monkeypatch.setenv("GDA_PROJECT", str(not_a_project))

    result = CliRunner().invoke(
        app, ["export", "run", "--preset", "Linux/X11", "--mode", "pack", "--json"]
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"


def test_recipe_command_with_invalid_project_is_structured(tmp_path):
    # A RECIPE command (`export run` → dispatch_recipe) with an invalid --project
    # must also surface the structured envelope, not the raw ValueError the recipe's
    # own resolve_project_dir would leak.
    not_a_project = tmp_path / "not-a-godot-project"
    not_a_project.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--mode",
            "pack",
            "--project",
            str(not_a_project),
            "--json",
        ],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"
