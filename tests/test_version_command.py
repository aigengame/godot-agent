"""`gda version`: the meta command ADR-0005 names, over the #659 provenance (#670).

ADR-0005 lists `gda version` among the top-level meta commands, and the dogfooding
record shows agents typing it (GDA-DF-032) — it simply had never been implemented, so
the documented surface and the shipped one disagreed. It is the COMMAND spelling of
the root `--version` flag, and it must not become a second answer to the same
question: both render the same one-line text and the same structured payload, built by
the one `gda.provenance` builder.

Nothing here spawns Godot — that is the point of the payload (#659), so it is pinned
against a deliberately bogus engine path.
"""

import json
from importlib.metadata import version as package_version

from typer.testing import CliRunner

from gda.cli import app
from gda.surface import build_surface_manifest


def test_it_prints_the_same_line_as_the_root_flag():
    command = CliRunner().invoke(app, ["version"])
    flag = CliRunner().invoke(app, ["--version"])

    assert command.exit_code == 0, command.stdout
    assert command.stdout == f"gda {package_version('gda')}\n"
    assert command.stdout == flag.stdout


def test_it_emits_the_same_provenance_payload_as_the_root_flag():
    # One question, one answer: the command and the flag both render
    # `build_version_provenance()`, so an agent that discovered `version` through
    # `gda schema` reads exactly what the flag reports.
    command = CliRunner().invoke(app, ["version", "--json"])
    flag = CliRunner().invoke(app, ["--version", "--json"])

    assert command.exit_code == 0, command.stdout
    payload = json.loads(command.stdout)
    assert payload == json.loads(flag.stdout)
    assert payload["gda_version"] == package_version("gda")
    assert payload["install_kind"] in {"wheel", "editable", "unknown"}


def test_a_root_json_reaches_it_too():
    root_spelling = CliRunner().invoke(app, ["--json", "version"])
    command_spelling = CliRunner().invoke(app, ["version", "--json"])

    assert root_spelling.exit_code == 0, root_spelling.stdout
    assert root_spelling.stdout == command_spelling.stdout


def test_it_never_launches_the_engine(monkeypatch):
    # The motivating case (#659) is an environment where an engine spawn fails, which
    # is exactly when provenance matters. An unlaunchable binary must not stop it: the
    # engine is REPORTED, never run.
    monkeypatch.setenv("GDA_GODOT", "/nonexistent/godot")

    result = CliRunner().invoke(app, ["version", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["godot"]["binary"] == "/nonexistent/godot"


def test_it_is_self_describing_and_on_the_surface():
    # The ADR-0004 hard gate, and the ADR-0012 manifest gda-mcp generates from.
    schema = CliRunner().invoke(app, ["version", "--schema"])

    assert schema.exit_code == 0, schema.stdout
    assert set(json.loads(schema.stdout)) >= {"input", "output", "error"}

    entry = next(
        command
        for command in build_surface_manifest(app).model_dump()["commands"]
        if command["name"] == "version"
    )
    assert entry["kind"] == "headless"
    assert "gda_version" in entry["output"]["properties"]


def test_the_human_line_comes_from_the_payload_it_built(monkeypatch):
    # The "one answer" property must rest on ONE value, not on two independent reads
    # of the package metadata agreeing. Rendering a payload whose version differs from
    # the installed distribution's proves the command renders what it was handed.
    from gda.commands.meta import render_version
    from gda.provenance import build_version_provenance

    payload = build_version_provenance().model_copy(update={"gda_version": "9.9.9"})

    assert render_version(payload) == "gda 9.9.9"
