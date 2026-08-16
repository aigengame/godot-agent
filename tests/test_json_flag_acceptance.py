"""`--json` is accepted on the discovery surfaces too (issue #671).

The bundled Skill teaches ONE rule — "always pass `--json`" — so a client that
follows it must never be answered with a usage error (exit 2). Discovery used to
break that rule at **two different parser sites**, which is why a root-only fix
would be incomplete:

- the ROOT parser (`gda --json --help`, `gda --json <command>`): the root callback
  declared only `--version`, so the flag died before any subcommand was resolved;
- the `schema` SUBCOMMAND parser (`gda schema --json`): it declared only
  `--schema`, so the whole-surface JSON manifest rejected the JSON flag.

Accepting the root flag is not enough on its own: a root `--json` that parsed but
did nothing would hand human text to a caller that asked for JSON — worse than the
loud `No such option` it replaced. So the root flag is INHERITED by the invoked
command (`gda.headless._inherit_root_json`), and the tests below pin that
equivalence, not just the exit code.

These are fast tests: nothing here spawns Godot.
"""

import json
import subprocess
from importlib.metadata import version

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.meta import read_skill_text
from gda.runner import RunResult
from tests.support import (
    SCENE_GET_RESULT,
    GDA_CMD,
    inject_runner,
    plain_text,
    sentinel,
)


# --- the `schema` subcommand parser site -------------------------------------


def test_schema_accepts_json_and_emits_the_manifest():
    # The dogfooding report (GDA-DF-022): `gda schema --json` exited 2 with "No
    # such option: --json" although `schema` IS the whole-surface JSON manifest.
    result = CliRunner().invoke(app, ["schema", "--json"])

    assert result.exit_code == 0, result.stdout
    doc = json.loads(result.stdout)
    assert isinstance(doc["commands"], list) and doc["commands"]


def test_schema_json_is_idempotent():
    # `gda schema`'s only output IS the JSON manifest, so the flag cannot change
    # it — accepting it is the whole point. Byte-for-byte equal, so a client may
    # pass `--json` uniformly without a second output shape to handle.
    plain = CliRunner().invoke(app, ["schema"])
    with_json = CliRunner().invoke(app, ["schema", "--json"])

    assert plain.exit_code == 0 and with_json.exit_code == 0
    assert plain.stdout == with_json.stdout


def test_schema_json_does_not_disturb_the_self_description():
    # `--schema` still wins over `--json` on this command, as on every other
    # (ADR-0004): the introspection probe emits the command's own contract.
    result = CliRunner().invoke(app, ["schema", "--json", "--schema"])

    assert result.exit_code == 0, result.stdout
    assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


# --- the ROOT parser site ----------------------------------------------------


def test_root_accepts_json_before_help():
    # The dogfooding report (GDA-DF-018, root-help part): a machine client had to
    # special-case exactly the discovery surface before it could discover the
    # subcommands. Help output stays TEXT — there is no result to serialize — so
    # this pins acceptance, not a structured help payload: the same help comes
    # back, flag or no flag.
    result = CliRunner().invoke(app, ["--json", "--help"])
    without_flag = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage: gda" in plain_text(result.stdout)
    assert result.stdout == without_flag.stdout


def test_root_help_advertises_the_json_option():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--json" in plain_text(result.stdout)


# --- the root flag MEANS the command's own flag -------------------------------


def test_root_json_is_equivalent_to_the_commands_own_json():
    # The two spellings an agent may produce from the one Skill rule must agree.
    # `gda skill` defaults to TEXT (it prints the manifest verbatim), so this
    # command actually distinguishes an inherited flag from an inert one.
    root_spelling = CliRunner().invoke(app, ["--json", "skill"])
    command_spelling = CliRunner().invoke(app, ["skill", "--json"])
    no_flag = CliRunner().invoke(app, ["skill"])

    assert root_spelling.exit_code == 0, root_spelling.stdout
    assert command_spelling.exit_code == 0, command_spelling.stdout
    assert root_spelling.stdout == command_spelling.stdout
    assert json.loads(root_spelling.stdout)["name"] == "gda"
    # …and the default is unchanged: no flag still means human text.
    assert no_flag.exit_code == 0
    assert not no_flag.stdout.startswith("{")


def test_both_spellings_together_are_not_a_conflict():
    # Passing it at BOTH levels is the natural belt-and-braces spelling; it means
    # the same thing (the command's own flag wins, the root's is the fallback).
    both = CliRunner().invoke(app, ["--json", "skill", "--json"])
    command_only = CliRunner().invoke(app, ["skill", "--json"])

    assert both.exit_code == 0, both.stdout
    assert both.stdout == command_only.stdout


def test_root_json_reaches_a_domain_command(monkeypatch):
    # Not just the meta commands: the inherited flag rides the shared sentinel
    # dispatch tail, so a domain command emits its JSON result too.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_GET_RESULT), stderr="", exit_code=0),
    )
    root_spelling = CliRunner().invoke(app, ["--json", "scene", "get", "/tmp/x.tscn"])

    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_GET_RESULT), stderr="", exit_code=0),
    )
    command_spelling = CliRunner().invoke(
        app, ["scene", "get", "/tmp/x.tscn", "--json"]
    )

    assert root_spelling.exit_code == 0, root_spelling.stdout
    assert root_spelling.stdout == command_spelling.stdout
    assert json.loads(root_spelling.stdout)


def test_root_json_reaches_the_params_json_dispatch_path():
    # `--params-json` is intercepted by the command class and dispatched through
    # its own tail (ADR-0015), which reads `ctx.params` — i.e. AFTER the inherit
    # callback has run, so the root flag is honored there as well.
    result = CliRunner().invoke(app, ["--json", "skill", "--params-json", "{}"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["name"] == "gda"


# --- the shipped guidance states the same contract ----------------------------


def test_skill_documents_the_json_placement_contract():
    # The Skill is the guidance an agent actually reads, so the placement rule has
    # to ship WITH the behavior, not only in a PR description. Token-level checks:
    # the two equivalent spellings are named, and so are the two that still exit 2
    # (a group's bare parser and a root flag with no command). Prose is free to be
    # reworded; these tokens are the contract.
    text = read_skill_text()

    assert "`gda --json <group> <command>`" in text
    assert "`gda <group> <command> --json`" in text
    assert "`gda schema --json`" in text
    assert "`gda --json --help`" in text
    # …and the two rejected spellings, with their exit code.
    assert "`gda <group> --json`" in text
    assert "a bare `gda --json` with no command" in text
    assert "exit `2`" in text


# --- what the root flag does NOT do (the honest contract for #659) ------------


def test_root_version_stays_text_in_both_json_orders():
    # #671 delivers flag ACCEPTANCE at the root; a JSON `--version` PAYLOAD is
    # #659's slice. Until then both orders print the same plain text. #659 flips
    # these expectations — that is the intended hand-off, so update this test
    # together with the payload.
    for args in (["--json", "--version"], ["--version", "--json"]):
        result = CliRunner().invoke(app, args)

        assert result.exit_code == 0, result.stdout
        assert result.stdout == f"gda {version('gda')}\n", args


# --- the real out-of-process CLI ---------------------------------------------


def test_real_out_of_process_cli_accepts_json_at_both_sites():
    # Both fixes through a REAL process (`python -m gda`, the same `app` the
    # console script wraps), not only the in-process CliRunner. Deliberately not
    # marked `e2e`: this repo's `e2e` marker means "spawns a real Godot process",
    # and nothing here does.
    manifest = subprocess.run(
        [*GDA_CMD, "schema", "--json"], capture_output=True, text=True
    )
    assert manifest.returncode == 0, manifest.stderr
    assert json.loads(manifest.stdout)["commands"]

    root_help = subprocess.run(
        [*GDA_CMD, "--json", "--help"], capture_output=True, text=True
    )
    assert root_help.returncode == 0, root_help.stderr
    # `-m gda` names itself "python -m gda" in the usage line, so match the shape
    # of the root usage rather than the program name.
    assert "[OPTIONS] COMMAND" in plain_text(root_help.stdout)

    inherited = subprocess.run(
        [*GDA_CMD, "--json", "skill"], capture_output=True, text=True
    )
    assert inherited.returncode == 0, inherited.stderr
    assert json.loads(inherited.stdout)["name"] == "gda"
