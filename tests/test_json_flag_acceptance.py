"""`--json` is accepted on the discovery surfaces too (issue #671).

The bundled Skill teaches ONE rule — "always pass `--json`" — so a client that
follows it must never be answered with a usage error (exit 2). Discovery used to
break that rule at **two different parser sites**, which is why a root-only fix
would be incomplete:

- the ROOT parser (`gda --json --help`): the root callback declared only
  `--version`, so the flag died before any subcommand was even resolved;
- the `schema` SUBCOMMAND parser (`gda schema --json`): it declared only
  `--schema`, so the whole-surface JSON manifest rejected the JSON flag.

These tests pin the accepted invocations at both sites. `--json` is idempotent on
both: `gda schema` already emits JSON, and the root has no payload of its own
(root `--help` stays text — the Skill lists it as the explicit exception). They
are fast: nothing here spawns Godot.
"""

import json
import subprocess

import typer
from typer.testing import CliRunner

from gda.cli import app
from tests.support import GDA_CMD


# --- the `schema` subcommand parser site -------------------------------------


def test_schema_accepts_json_and_emits_the_manifest():
    # The dogfooding report (GDA-DF-022): `gda schema --json` exited 2 with "No
    # such option: --json" although `schema` IS the whole-surface JSON manifest.
    result = CliRunner().invoke(app, ["schema", "--json"])

    assert result.exit_code == 0, result.stdout
    doc = json.loads(result.stdout)
    assert isinstance(doc["commands"], list) and doc["commands"]


def test_schema_json_is_idempotent():
    # `gda schema`'s human rendering IS its JSON (the manifest), so the flag
    # changes nothing — accepting it is the whole point. Byte-for-byte equal, so
    # a client may pass `--json` uniformly without a second output shape.
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
    # subcommands. Help output stays TEXT — the root has no result to serialize —
    # so this pins acceptance, not a structured help payload.
    result = CliRunner().invoke(app, ["--json", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage: gda" in result.stdout


def test_root_help_advertises_the_json_option():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--json" in result.stdout


def test_root_json_composes_with_a_subcommand():
    # The root flag is positional-order tolerant with respect to the subcommand:
    # `gda --json <command>` parses, and the subcommand emits its own result.
    result = CliRunner().invoke(app, ["--json", "schema"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["commands"]


def test_root_json_is_bound_into_the_root_context():
    # The root `--json` is EAGER, so it is bound before the other eager root
    # options run their callbacks. A root option that later renders a JSON
    # payload (`--version --json`, #659) can therefore read the flag off the root
    # context instead of re-parsing argv. Asserted through the live Typer tree so
    # the guarantee is checked where a consumer would read it.
    root = typer.main.get_command(app)
    json_param = next(p for p in root.params if "--json" in getattr(p, "opts", []))
    assert json_param.is_eager


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
    assert "[OPTIONS] COMMAND" in root_help.stdout
