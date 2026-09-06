"""An unrecognized command or option is refused structurally, with a curated hint (#670).

The dogfooding record (GDA-DF-024/025/032/033/041) is a list of *near misses*: an
agent typed `scene inspect` for `scene get`, `script check` for `script validate`,
`gda --schema` for `gda schema`. Each one exited 2 with prose on stderr — no
structured envelope to branch on, and no pointer at the working sibling. Typer's own
did-you-mean is not that pointer: it is a difflib guess rendered into the human error,
so it stays unparseable and it can name a *different* operation than the one meant.

These tests pin the two halves of the fix:

- the CHANNEL — the refusal is answered by gda's one public failure channel, as the
  `{"error": {...}}` envelope with `--json` in effect and as the same failure's human
  lines without it (#685), at the same exit 2 the usage error already used, so
  nothing that keyed on the exit code changes;
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
from gda.hints import CLI_NAME, NEAR_MISSES, UNKNOWN_COMMAND, UNKNOWN_OPTION
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


def test_an_unknown_command_without_json_is_the_human_rendering_of_the_envelope():
    # No `--json`, no envelope — the same refusal rendered as lines by the shared
    # failure renderer, at the same exit code. Its layout is pinned in
    # `test_human_failure_output.py`; what this pins is that the refusal reaches that
    # renderer at all, rather than click's own usage error (#798 review).
    result = CliRunner().invoke(app, ["scene", "inspect"])

    assert result.exit_code == EXIT_USAGE
    assert not result.stdout.startswith("{")
    assert result.stdout.startswith(f"error: {UNKNOWN_COMMAND} (usage)\n")
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


@pytest.mark.parametrize(
    "args, hint",
    [
        pytest.param(
            ["script", "run", "--script", "logic.gd"],
            "gda script run <path>",
            id="script-run--script",
        ),
        pytest.param(
            ["script", "run", "--path", "logic.gd"],
            "gda script run <path>",
            id="script-run--path",
        ),
        pytest.param(
            ["script", "validate", "--path", "logic.gd"],
            "gda script validate <path>",
            id="script-validate--path",
        ),
        pytest.param(
            ["script", "validate", "--strict", "logic.gd"],
            "gda script validate <path>",
            id="script-validate--strict",
        ),
    ],
)
def test_each_dogfooded_option_spelling_names_the_positional_form(args, hint):
    # GDA-DF-032/069 and PIPE-DF-165: both `script` commands take their script as a
    # positional argument, and `--strict` is `script run`'s gate alone. The refusal is
    # raised by the LEAF command's parser, which is the third interception site (after
    # the root's own parser and a group's). The two `script run` rows are a deliberate
    # duplicate: the table keys on the SPELLING typed. `--script` is the recorded one
    # (GDA-DF-032); `--path` is curated beside it, because GDA-DF-069 recorded that
    # spelling on `validate` and the same caller slip reaches both commands.
    result = CliRunner().invoke(app, [*args, "--json"])

    error = _envelope(result)
    assert error["code"] == UNKNOWN_OPTION
    assert error["hint"] == hint


# The clause the `--strict` refusal must carry: `hint` is the corrected invocation
# and nothing else, so the difference between the two `--strict`s is stated in the
# MESSAGE, which both renderings carry. Pinned in two halves, since the message the
# caller reads must both name what to gate on and place the flag they typed.
STRICT_VERDICT = "exits 0 either way, so gate on `valid`"
STRICT_FLAG = "`--strict` belongs to `script run`"


def test_the_strict_near_miss_states_the_contract_in_both_renderings():
    # PIPE-DF-165: the caller carried `--strict` over from `script run`, so naming the
    # positional form is not enough — the message says what `validate` reports instead
    # (a `valid` verdict, at exit 0 whichever way it goes) and what the flag they typed
    # really gates: `script run`'s own non-zero exit status (ADR-0031), a different
    # question. Under `--json` that rides the envelope's message beside the
    # machine-readable `hint`; without it, the same failure renders as lines with its
    # own `hint:` line.
    structured = CliRunner().invoke(
        app, ["script", "validate", "--strict", "logic.gd", "--json"]
    )
    human = CliRunner().invoke(app, ["script", "validate", "--strict", "logic.gd"])

    error = _envelope(structured)
    assert error["hint"] == "gda script validate <path>"
    assert STRICT_VERDICT in error["message"]
    assert STRICT_FLAG in error["message"]

    assert human.exit_code == EXIT_USAGE
    assert not human.stdout.startswith("{")
    text = plain_text(human.output)
    assert text.startswith(f"error: {UNKNOWN_OPTION} (usage)\n")
    assert "hint: gda script validate <path>" in text
    assert STRICT_VERDICT in text
    assert STRICT_FLAG in text


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
        assert words[0] == CLI_NAME, (
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
    # tree. Walked from the live tree, the same authority `gda schema` projects from,
    # and walked RECURSIVELY: gda's tree is two levels deep today, so a check that
    # read only the root's own groups would pass while a nested sub-group escaped the
    # interception entirely.
    from gda.hints import GdaGroup

    def plain_groups(command, path):
        subcommands = getattr(command, "commands", None)
        if subcommands is None:
            return []
        found = [] if isinstance(command, GdaGroup) or not path else [" ".join(path)]
        for name, sub in subcommands.items():
            found.extend(plain_groups(sub, [*path, name]))
        return found

    root = typer.main.get_command(app)
    assert isinstance(root, GdaGroup), type(root)
    plain = plain_groups(root, [])
    assert not plain, f"groups mounted without the gda group class: {plain}"


def test_the_adoption_reaches_a_nested_sub_group():
    # The negative sentinel for the walk above: a group mounted on a GROUP (not on the
    # root) is the shape a flat adoption would miss, and the tree has none today — so
    # the guard is proven on a tree built here rather than left untested until someone
    # adds one.
    from gda.hints import GdaGroup, adopt

    inner = typer.Typer(name="inner")

    @inner.command("leaf")
    def _leaf() -> None:  # pragma: no cover - never invoked
        """A leaf."""

    middle = typer.Typer(name="middle")
    middle.add_typer(inner, name="inner")
    root = typer.Typer(name="root")
    root.add_typer(middle, name="middle")

    adopt(root)

    built = typer.main.get_command(root)
    assert isinstance(built, GdaGroup)
    assert isinstance(built.commands["middle"], GdaGroup)
    assert isinstance(built.commands["middle"].commands["inner"], GdaGroup)


def test_both_refusal_codes_are_registered_at_the_usage_exit():
    for code in (UNKNOWN_COMMAND, UNKNOWN_OPTION):
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.exit_code == EXIT_USAGE
        assert spec.category.value == "usage"


def test_the_intercepted_exception_is_the_one_typer_raises():
    # Typer 0.26 VENDORS click, so `typer._click.exceptions.NoSuchOption` and the
    # identically named class in the top-level `click` package are DIFFERENT types:
    # catching the wrong one leaves the interception silently dead. `typer.BadParameter`
    # is public and is built on the vendored hierarchy, so this pins that the class gda
    # holds is in the one a Typer parser actually raises from.
    from typer._click.exceptions import UsageError

    from gda.hints import NoSuchOption

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


def test_an_incomplete_command_line_is_not_refused():
    # Click parses an INCOMPLETE command line under `resilient_parsing` (shell
    # completion), where an unrecognized token is expected — and where an error
    # envelope printed to stdout would land in the completion stream. gda's refusal
    # keeps click's own guard for exactly that mode.
    import typer._click as _click

    from gda.hints import GdaGroup

    root = typer.main.get_command(app)
    assert isinstance(root, GdaGroup)
    ctx = _click.Context(root, info_name="gda", resilient_parsing=True)

    name, command, rest = root.resolve_command(ctx, ["inspect", "--json"])

    assert command is None and name is None


# --- the two arms that can meet the same mistake answer it identically ---------


def _arms(mistake: list[str], *, json: bool) -> tuple:
    """The same wrong command through the parser and through `gda help`."""
    flag = ["--json"] if json else []
    return (
        CliRunner().invoke(app, [*mistake, *flag]),
        CliRunner().invoke(app, ["help", *mistake, *flag]),
    )


def test_the_parser_and_help_arms_return_the_same_envelope():
    # `gda help scene inspect` IS `gda scene inspect` — the same mistake, reached two
    # ways — so the two must not describe it differently. They share one Refusal
    # construction (`gda.hints.unknown_command`), which is what makes this hold
    # verbatim rather than by two prose strings happening to agree.
    parser, through_help = _arms(["scene", "inspect"], json=True)

    assert parser.exit_code == through_help.exit_code == EXIT_USAGE
    assert json.loads(parser.stdout) == json.loads(through_help.stdout)
    assert json.loads(parser.stdout)["error"]["hint"] == "gda scene get"


def test_the_parser_and_help_arms_share_the_human_channel_too():
    # The CHANNEL must match as well as the words: without `--json` neither arm may
    # print an envelope — an agent that asked for text gets text — and both go
    # through the one human failure renderer, so the two arms agree byte for byte
    # rather than by two layouts happening to say the same thing.
    parser, through_help = _arms(["scene", "inspect"], json=False)

    assert parser.exit_code == through_help.exit_code == EXIT_USAGE
    assert parser.stdout == through_help.stdout
    for result in (parser, through_help):
        assert not result.stdout.startswith("{"), result.stdout
        assert result.stdout.startswith(f"error: {UNKNOWN_COMMAND} (usage)\n")
        assert "gda scene get" in plain_text(result.output)
