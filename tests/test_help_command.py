"""`gda help [COMMAND…]`: the meta command ADR-0005 names (#670).

ADR-0005 lists `gda help` among the top-level meta commands; it had never been
implemented, and the dogfooding record shows agents typing `gda help X` and being
refused (GDA-DF-032). It takes the optional command path — the `git help <command>` /
`docker help <command>` shape — so `gda help scene get` answers the question
`gda scene get --help` answers, from the argv form an agent already reached for.

It is a pure emitter like `gda skill` (ADR-0024): no Godot, no project. `--json`
returns the same text as a field rather than a second rendering of it, so the ONE rule
an agent follows ("always pass `--json`") holds on the discovery surface too; the
`--help` FLAG stays text-only, unchanged (#671).
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.surface import build_surface_manifest
from tests.support import plain_text


def _text(result) -> str:
    return plain_text(json.loads(result.stdout)["text"])


def test_bare_help_is_the_root_help():
    result = CliRunner().invoke(app, ["help"])

    assert result.exit_code == 0, result.stdout
    text = plain_text(result.stdout)
    assert "Usage: gda [OPTIONS] COMMAND" in text
    # The groups an agent is looking for are in it.
    assert "scene" in text and "daemon" in text


def test_it_answers_for_a_command_the_way_the_help_flag_does():
    # GDA-DF-032: the two forms must not diverge — the same help, reached two ways.
    through_command = CliRunner().invoke(app, ["help", "scene", "get"])
    through_flag = CliRunner().invoke(app, ["scene", "get", "--help"])

    assert through_command.exit_code == 0, through_command.stdout
    assert plain_text(through_command.stdout) == plain_text(through_flag.stdout)
    assert "Usage: gda scene get" in plain_text(through_command.stdout)


def test_it_answers_for_a_group():
    result = CliRunner().invoke(app, ["help", "scene"])

    assert result.exit_code == 0, result.stdout
    text = plain_text(result.stdout)
    assert "Usage: gda scene [OPTIONS] COMMAND" in text
    assert "get-exports" in text


def test_json_carries_the_named_command_and_its_text():
    result = CliRunner().invoke(app, ["help", "scene", "get", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "gda scene get"
    assert "Usage: gda scene get" in plain_text(payload["text"])


def test_json_for_the_bare_form_names_the_cli_itself():
    result = CliRunner().invoke(app, ["help", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "gda"
    assert "Usage: gda [OPTIONS] COMMAND" in plain_text(payload["text"])


def test_an_unknown_target_is_the_same_structured_refusal_with_the_same_hint():
    # `gda help` resolves a command path, so it can fail the same way the parser does
    # — and it answers with the SAME curated table (gda.hints), not a second one.
    result = CliRunner().invoke(app, ["help", "scene", "inspect", "--json"])

    assert result.exit_code == 2, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "unknown_command"
    assert error["hint"] == "gda scene get"


def test_an_unknown_target_without_a_hint_still_names_discovery():
    result = CliRunner().invoke(app, ["help", "frobnicate", "--json"])

    assert result.exit_code == 2, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "unknown_command"
    assert "hint" not in error
    assert "gda schema" in error["message"]


def test_a_command_path_that_runs_past_a_leaf_is_refused():
    # `scene get` is a leaf, so `gda help scene get extra` names nothing.
    result = CliRunner().invoke(app, ["help", "scene", "get", "extra", "--json"])

    assert result.exit_code == 2, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "unknown_command"


def test_it_is_self_describing_and_on_the_surface():
    schema = CliRunner().invoke(app, ["help", "--schema"])

    assert schema.exit_code == 0, schema.stdout
    assert set(json.loads(schema.stdout)) >= {"input", "output", "error"}

    entry = next(
        command
        for command in build_surface_manifest(app).model_dump()["commands"]
        if command["name"] == "help"
    )
    assert entry["kind"] == "headless"
    assert set(entry["output"]["properties"]) == {"command", "text"}


def test_the_params_json_path_takes_the_same_command_path():
    # ADR-0015: the argv and JSON-object forms build the one params model, so they
    # cannot diverge — this is the form gda-mcp dispatches.
    result = CliRunner().invoke(
        app, ["help", "--params-json", '{"command": ["scene", "get"]}', "--json"]
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["command"] == "gda scene get"


def test_it_never_launches_the_engine(monkeypatch):
    monkeypatch.setenv("GDA_GODOT", "/nonexistent/godot")

    result = CliRunner().invoke(app, ["help", "scene", "get"])

    assert result.exit_code == 0, result.stdout
