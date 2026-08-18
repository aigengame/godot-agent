"""An unrecognized command or option is refused structurally, with a curated hint (#670).

The dogfooding record (GDA-DF-024/025/032/033/041) is a list of *near misses*: an
agent typed `scene inspect` for `scene get`, `script check` for `script validate`,
`gda --schema` for `gda schema`. Each one exited 2 with prose on stderr — no
structured envelope to branch on, and no pointer at the working sibling. Typer's own
did-you-mean is not that pointer: it is a difflib guess rendered into the human error,
so it stays unparseable and it can name a *different* operation than the one meant.

These tests pin the two halves of the fix:

- the CHANNEL — with `--json` in effect the refusal is gda's ordinary
  `{"error": {...}}` envelope on stdout, at the same exit 2 the usage error already
  used, so nothing that keyed on the exit code changes;
- the CONTENT — a curated near-miss carries the supported invocation in a
  machine-readable `hint`, so an agent re-issues the corrected command without
  parsing a sentence.

Nothing here spawns Godot.
"""

import json
import subprocess

import pytest
import typer
from typer.testing import CliRunner

from gda.cli import app
from gda.error_codes import ERROR_CODE_BY_CODE
from gda.exit_codes import EXIT_USAGE
from gda.hints import NEAR_MISSES, UNKNOWN_COMMAND, UNKNOWN_OPTION
from tests.support import GDA_CMD, plain_text


def _envelope(result) -> dict:
    """The `{"error": {...}}` payload a refusal put on stdout."""
    assert result.stdout.startswith("{"), result.stdout
    return json.loads(result.stdout)["error"]


# --- the channel: --json in effect makes the refusal structured ----------------


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["scene", "inspect", "--json"], id="flag-after-the-command"),
        pytest.param(["--json", "scene", "inspect"], id="root-flag"),
    ],
)
def test_an_unknown_group_command_is_a_structured_refusal(args):
    # Both `--json` spellings the Skill teaches reach the refusal. The root one is
    # the parsed option (#671); the trailing one is unparseable at this point — the
    # command it would have belonged to does not exist — so the literal token in the
    # argv is what says "answer me in JSON".
    result = CliRunner().invoke(app, args)

    error = _envelope(result)
    assert error["code"] == UNKNOWN_COMMAND
    assert error["hint"] == "gda scene get"
    assert result.exit_code == EXIT_USAGE


def test_an_unknown_command_without_json_stays_a_human_usage_error():
    # The default channel is unchanged: no `--json`, no envelope — the hint rides the
    # human error instead, on stderr, at the same exit code.
    result = CliRunner().invoke(app, ["scene", "inspect"])

    assert result.exit_code == EXIT_USAGE
    assert not result.stdout.startswith("{")
    assert "gda scene get" in plain_text(result.output)


def test_an_uncurated_unknown_command_is_still_structured_but_hintless():
    # `--json` selects the CHANNEL; the curated table only decides whether gda has
    # advice. A spelling nothing recognizes still gets the envelope — with the `hint`
    # key OMITTED, never a guessed value — and is pointed at discovery.
    result = CliRunner().invoke(app, ["frobnicate", "--json"])

    error = _envelope(result)
    assert error["code"] == UNKNOWN_COMMAND
    assert "hint" not in error
    assert "gda schema" in error["message"]
    assert result.exit_code == EXIT_USAGE


def test_an_uncurated_unknown_command_keeps_typers_own_error():
    # Where gda has nothing to add and no JSON was asked for, the existing behaviour
    # is left exactly as it was — including Typer's own did-you-mean guess.
    result = CliRunner().invoke(app, ["scen"])

    assert result.exit_code == EXIT_USAGE
    text = plain_text(result.output)
    assert "No such command" in text
    assert "scene" in text


# --- the content: one curated row per dogfooded near miss ---------------------


@pytest.mark.parametrize(
    "args, hint",
    [
        pytest.param(["scene", "inspect"], "gda scene get", id="scene-inspect"),
        pytest.param(
            ["script", "check", "a.gd"], "gda script validate", id="script-check"
        ),
        pytest.param(["game", "get-property"], "gda game get", id="game-get-property"),
        pytest.param(["analyze"], "gda script validate --all", id="analyze"),
        pytest.param(["doctor"], "gda info", id="doctor"),
    ],
)
def test_each_dogfooded_command_spelling_names_its_real_sibling(args, hint):
    result = CliRunner().invoke(app, [*args, "--json"])

    error = _envelope(result)
    assert error["code"] == UNKNOWN_COMMAND
    assert error["hint"] == hint


def test_the_root_schema_option_points_at_the_schema_command():
    # GDA-DF-032: `--schema` is a per-COMMAND flag, so at the root it is an unknown
    # option; the whole-surface manifest is the `gda schema` command.
    result = CliRunner().invoke(app, ["--schema", "--json"])

    error = _envelope(result)
    assert error["code"] == UNKNOWN_OPTION
    assert error["hint"] == "gda schema"
    assert result.exit_code == EXIT_USAGE


def test_script_run_script_option_points_at_the_positional_form():
    # GDA-DF-032: `script run` takes the script as its positional argument. The
    # refusal is raised by the LEAF command's parser, which is the third interception
    # site (after the root's own parser and a group's).
    result = CliRunner().invoke(
        app, ["script", "run", "--script", "logic.gd", "--json"]
    )

    error = _envelope(result)
    assert error["code"] == UNKNOWN_OPTION
    assert error["hint"] == "gda script run <path>"


def test_a_groups_json_flag_points_at_the_command_that_takes_it():
    # The one refusal keyed on the tree SHAPE rather than on a spelling: a group's own
    # parser takes only `--help`, so `gda <group> --json` is rejected there — the
    # spelling the Skill already documents as a usage error. Keyed on shape, so every
    # group (and any group added later) is covered without a row each.
    result = CliRunner().invoke(app, ["scene", "--json"])

    error = _envelope(result)
    assert error["code"] == UNKNOWN_OPTION
    assert error["hint"] == "gda scene <command> --json"


# --- the table is the single authority, and it stays honest -------------------


def _resolve(tokens: list[str]):
    """Walk the live Typer tree for ``tokens``; returns the command or None."""
    command = typer.main.get_command(app)
    for token in tokens:
        subcommands = getattr(command, "commands", None)
        if subcommands is None or token not in subcommands:
            return None
        command = subcommands[token]
    return command


def test_every_curated_hint_names_a_real_invocation():
    # The guard that lets one central table stay correct without per-group ownership:
    # every hint is re-resolved against the LIVE Typer tree (the same authority
    # `gda schema` projects from), so a rename that orphans a hint fails here rather
    # than sending an agent at a command that no longer exists.
    for key, miss in NEAR_MISSES.items():
        words = miss.use.split()
        assert words[0] == "gda", (
            f"{key}: a hint spells the full invocation: {miss.use}"
        )
        path = [w for w in words[1:] if not w.startswith(("-", "<"))]
        command = _resolve(path)
        assert command is not None, f"{key}: hint names no such command: {miss.use}"
        # An option named in a hint must be a real option of that command.
        options = {opt for param in command.params for opt in param.opts}
        for word in words[1:]:
            if word.startswith("-"):
                assert word in options, f"{key}: {word} is not an option of {path}"


def test_every_group_in_the_live_tree_refuses_through_the_gda_class():
    # `adopt()` runs once in the composition root, so a group added later inherits the
    # refusal by being mounted — but only while the root really applies it to the whole
    # tree. Walked from the live tree, the same authority `gda schema` projects from.
    from gda.hints import GdaGroup

    root = typer.main.get_command(app)
    assert isinstance(root, GdaGroup), type(root)
    plain = [
        name
        for name, command in root.commands.items()
        if getattr(command, "commands", None) is not None
        and not isinstance(command, GdaGroup)
    ]
    assert not plain, f"groups mounted without the gda group class: {plain}"


def test_both_refusal_codes_are_registered_at_the_usage_exit():
    for code in (UNKNOWN_COMMAND, UNKNOWN_OPTION):
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.exit_code == EXIT_USAGE
        assert spec.category.value == "usage"


def test_the_intercepted_exception_is_the_one_typer_raises():
    # Typer 0.26 VENDORS click, so `typer._click.exceptions.UsageError` and the
    # identically named class in the top-level `click` package are DIFFERENT types:
    # catching the wrong one leaves the interception silently dead. `typer.BadParameter`
    # is public and is built on the vendored hierarchy, so this pins that the classes
    # gda catches are the ones a Typer parser actually raises.
    from gda.hints import NoSuchOption, UsageError

    assert issubclass(typer.BadParameter, UsageError)
    assert issubclass(NoSuchOption, UsageError)


def test_a_known_command_is_untouched():
    # The negative control: the interception must fire only on an unrecognized token.
    result = CliRunner().invoke(app, ["schema"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["commands"]


def test_the_real_out_of_process_cli_refuses_structurally():
    # Through a REAL process, not only the in-process CliRunner: the interception
    # lives in the click group class, which the console script builds the same way.
    done = subprocess.run(
        [*GDA_CMD, "scene", "inspect", "--json"], capture_output=True, text=True
    )

    assert done.returncode == EXIT_USAGE, done.stdout + done.stderr
    error = json.loads(done.stdout)["error"]
    assert error["code"] == UNKNOWN_COMMAND
    assert error["hint"] == "gda scene get"
