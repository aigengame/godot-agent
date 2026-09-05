"""`--json` is accepted on the discovery surfaces too (issues #671, #683).

The bundled Skill teaches ONE rule — "always pass `--json`" — so a client that
follows it must never be answered with a usage error (exit 2). Discovery used to
break that rule at **three different parser sites**, which is why a root-only fix
would be incomplete:

- the ROOT parser (`gda --json --help`, `gda --json <command>`): the root callback
  declared only `--version`, so the flag died before any subcommand was resolved;
- the `schema` SUBCOMMAND parser (`gda schema --json`): it declared only
  `--schema`, so the whole-surface JSON manifest rejected the JSON flag;
- every mounted GROUP's parser (`gda scene --json get …`, #683): a group declared no
  options at all, so the flag written between the group and the command exited 2.

Accepting an outer flag is not enough on its own: a `--json` that parsed but did
nothing would hand human text to a caller that asked for JSON — worse than the loud
`No such option` it replaced. So an ancestor's flag is INHERITED by the invoked
command (`gda.headless._inherit_ancestor_json`), and the tests below pin that
equivalence, not just the exit code.

The root itself later grew one payload of its own — `--version` (#659) — so the
final section here pins that both argv orders reach it; its shape is pinned in
`tests/meta/test_version_provenance.py`.

These are fast tests: nothing here spawns Godot.
"""

import json
import subprocess
from importlib.metadata import version

import pytest
import typer
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.meta import read_skill_text
from gda.headless import adopt_group_json
from tests.support import (
    SCENE_GET_RESULT,
    GDA_CMD,
    invoke_cli,
    panel_text,
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
    root_spelling, _ = invoke_cli(
        monkeypatch,
        ["--json", "scene", "get", "/tmp/x.tscn"],
        stdout=sentinel(SCENE_GET_RESULT),
    )

    command_spelling, _ = invoke_cli(
        monkeypatch,
        ["scene", "get", "/tmp/x.tscn", "--json"],
        stdout=sentinel(SCENE_GET_RESULT),
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


# --- the GROUP parser site (issue #683) ---------------------------------------


def _scene_get(monkeypatch, args: list[str]):
    """Invoke ``args`` with the runner seam faked, so no Godot is spawned.

    ``scene get`` is the probe for this site because it renders HUMAN text by
    default: a flag that parsed but did not reach the command would show up here as
    that text, which is the failure mode acceptance alone would hide.
    """
    return invoke_cli(monkeypatch, args, stdout=sentinel(SCENE_GET_RESULT))[0]


def test_group_json_is_equivalent_to_the_commands_own_json(monkeypatch):
    # The third parser site: a `--json` between the group and the command used to
    # die with `No such option`, so the one rule the Skill teaches broke on a line
    # an agent composes naturally. All three spellings must agree byte for byte.
    group_spelling = _scene_get(monkeypatch, ["scene", "--json", "get", "/tmp/x.tscn"])
    command_spelling = _scene_get(
        monkeypatch, ["scene", "get", "/tmp/x.tscn", "--json"]
    )
    root_spelling = _scene_get(monkeypatch, ["--json", "scene", "get", "/tmp/x.tscn"])
    no_flag = _scene_get(monkeypatch, ["scene", "get", "/tmp/x.tscn"])

    assert group_spelling.exit_code == 0, group_spelling.stdout
    assert group_spelling.stdout == command_spelling.stdout == root_spelling.stdout
    assert json.loads(group_spelling.stdout)
    # …and the default is unchanged: no flag still means human text.
    assert no_flag.exit_code == 0
    assert not no_flag.stdout.startswith("{")


def test_the_three_spellings_stack_without_conflicting(monkeypatch):
    # Belt and braces: a client that writes the flag everywhere gets one answer,
    # not a second output shape to handle.
    everywhere = _scene_get(
        monkeypatch, ["--json", "scene", "--json", "get", "/tmp/x.tscn", "--json"]
    )
    command_only = _scene_get(monkeypatch, ["scene", "get", "/tmp/x.tscn", "--json"])

    assert everywhere.exit_code == 0, everywhere.stdout
    assert everywhere.stdout == command_only.stdout


def test_group_json_reaches_the_params_json_dispatch_path(monkeypatch):
    # `--params-json` is intercepted by the command class and dispatched through its
    # own tail (ADR-0015), which reads `ctx.params` — i.e. after the inherit
    # callback has run, so a group flag is honored there too.
    result = _scene_get(
        monkeypatch,
        ["scene", "--json", "get", "--params-json", '{"path": "/tmp/x.tscn"}'],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["path"]


def test_group_json_without_a_command_is_still_a_usage_error():
    # Acceptance moved the failure to the honest one; it did not invent a payload.
    # `gda <group> --json` says what a bare `gda --json` says, at the same exit code.
    result = CliRunner().invoke(app, ["scene", "--json"])
    bare_root = CliRunner().invoke(app, ["--json"])

    assert result.exit_code == 2
    assert bare_root.exit_code == 2
    assert "Missing command." in panel_text(result.stderr)
    assert "Missing command." in panel_text(bare_root.stderr)


def test_every_group_advertises_the_json_option_in_its_help():
    # The option is installed onto every MOUNTED group at composition
    # (`gda.headless.adopt_group_json`), so the check walks the live tree rather than
    # naming the groups: one added later is covered by being mounted. A group is the
    # node with a `commands` mapping — the duck-type `gda.surface` walks with too.
    root: object = typer.main.get_command(app)
    groups = [
        name
        for name, command in getattr(root, "commands", {}).items()
        if getattr(command, "commands", None) is not None
    ]

    assert groups, "the live tree reported no command groups"
    for name in groups:
        rendered = CliRunner().invoke(app, [name, "--help"])

        assert rendered.exit_code == 0, rendered.stdout
        assert "--json" in plain_text(rendered.stdout), name


def test_the_walker_refuses_to_replace_a_groups_own_callback():
    # Installing the option means installing the callback that carries it. No group
    # declares one today; one that grows a callback must declare the shared option
    # on it, so the walker says so instead of dropping that callback silently.
    root = typer.Typer()
    group = typer.Typer()

    @group.callback()
    def _own(ctx: typer.Context) -> None:
        """A group with business of its own."""

    root.add_typer(group, name="own")

    with pytest.raises(RuntimeError, match="own"):
        adopt_group_json(root)


def test_the_json_adoption_reaches_a_nested_sub_group():
    # The negative sentinel for the walk itself: a group mounted on a GROUP — not on
    # the root — is the shape a flat adoption would miss. The live tree is two levels
    # deep, so every group-`--json` test above exercises a FIRST-level group and the
    # walk's recursion rode along unproven: deleting it passed the whole suite (#788).
    # So the recursion is proven on a tree built here, rather than left until someone
    # mounts a sub-group and finds the flag dead under it. The twin on the refusal side
    # is tests/cli/test_unknown_invocation.py::test_the_adoption_reaches_a_nested_sub_group.
    inner = typer.Typer()

    @inner.command("leaf")
    def _leaf() -> None:
        """A leaf."""

    middle = typer.Typer()
    middle.add_typer(inner, name="inner")
    root = typer.Typer()
    root.add_typer(middle, name="middle")

    adopt_group_json(root)

    # The acceptance the first level already has, one level down: the flag parses
    # between the nested group and the command it runs.
    accepted = CliRunner().invoke(root, ["middle", "inner", "--json", "leaf"])

    assert accepted.exit_code == 0, accepted.stdout + accepted.stderr
    rendered = CliRunner().invoke(root, ["middle", "inner", "--help"])

    assert rendered.exit_code == 0, rendered.stdout
    assert "--json" in plain_text(rendered.stdout)


# --- the shipped guidance states the same contract ----------------------------


def test_skill_documents_the_json_placement_contract():
    # The Skill is the guidance an agent actually reads, so the placement rule has
    # to ship WITH the behavior, not only in a PR description. Token-level checks:
    # the three equivalent spellings are named, and so are the two that still exit 2
    # (either flavour of "the flag, but no command"). Prose is free to be reworded;
    # these tokens are the contract.
    text = read_skill_text()

    assert "`gda --json <group> <command>`" in text
    assert "`gda <group> --json <command>`" in text
    assert "`gda <group> <command> --json`" in text
    assert "`gda schema --json`" in text
    assert "`gda --json --help`" in text
    # …and the two rejected spellings, with their exit code.
    assert "`gda <group> --json`" in text
    assert "a bare `gda --json` with no command" in text
    assert "exit `2`" in text


# --- the root flag now carries a payload of its own (#659) --------------------


def test_root_version_is_structured_in_both_json_orders():
    # #671 delivered flag ACCEPTANCE at the root and recorded, as a test, that the
    # root itself still had no JSON payload. #659 delivers that payload, so this
    # is the flipped expectation: BOTH argv orders return it — which only holds
    # because `--version` stopped being an eager option (click processes eager
    # parameters in argv order). The payload's own contract is pinned in
    # tests/meta/test_version_provenance.py; here only the equivalence matters.
    payloads = []
    for args in (["--json", "--version"], ["--version", "--json"]):
        result = CliRunner().invoke(app, args)

        assert result.exit_code == 0, result.stdout
        payloads.append(json.loads(result.stdout))

    assert payloads[0] == payloads[1]
    assert payloads[0]["gda_version"] == version("gda")


def test_root_version_without_the_flag_stays_text():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"gda {version('gda')}\n"


# --- the real out-of-process CLI ---------------------------------------------


def test_real_out_of_process_cli_accepts_json_at_every_site():
    # Every fix through a REAL process (`python -m gda`, the same `app` the
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

    # The group site needs a command that spawns nothing: `--schema` answers from
    # the command's own models, so it proves the flag PARSED between the group and
    # the command without reaching for an engine.
    on_a_group = subprocess.run(
        [*GDA_CMD, "scene", "--json", "get", "--schema"], capture_output=True, text=True
    )
    assert on_a_group.returncode == 0, on_a_group.stderr
    assert set(json.loads(on_a_group.stdout)) >= {"input", "output", "error"}
