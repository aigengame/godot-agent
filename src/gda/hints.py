"""Curated near-miss hints, and the structured refusal of an unknown invocation (#670).

Dogfooding produced a list of *near misses* — `scene inspect` for `scene get`,
`script check` for `script validate`, `gda --schema` for `gda schema` — each of
which died as prose on stderr: nothing to branch on, and no pointer at the working
sibling (GDA-DF-024/025/032/033/041). Typer's own did-you-mean is not that pointer.
It is a difflib guess rendered into the human message, so it stays unparseable, it
is silent whenever the typo is not string-similar (`inspect` is nothing like `get`),
and similarity is not intent: the nearest *string* can be a different — even
opposite — operation. So the mapping here is CURATED: one row per spelling the
record actually showed, each naming the supported invocation.

This module owns two things, which are the two halves of one job:

- :data:`NEAR_MISSES`, the single authority for what gda recommends. One table, not
  per-group fragments: three of its rows belong to no group at all (a root option, a
  top-level verb), and a per-group registry that the interception then has to collect
  would be exactly the parallel registry ADR-0023/0040 keep out of this codebase. A
  test re-resolves every hint against the LIVE Typer tree instead, so the table
  cannot outlive a rename.
- :class:`GdaGroup`, the click group the composition root mounts everywhere, which
  turns an unrecognized command or option into gda's ordinary ``{"error": {...}}``
  envelope.

**Where the interception sits.** A Typer parser reports these two failures at three
places, and this class covers all of them because ``gda.cli`` gives every group the
class: an unknown COMMAND is decided in :meth:`GdaGroup.resolve_command` (the group
it was typed under); an unknown OPTION on the root or on a group surfaces from that
parser's own :meth:`GdaGroup.parse_args`; and an unknown option on a LEAF command
surfaces from the leaf's parser, which runs inside its parent group's
:meth:`GdaGroup.invoke`. So no command module — and no leaf command class — carries
a line of this.

**Which channel answers.** With ``--json`` in effect the refusal is the structured
envelope on stdout; otherwise it is the human usage error, carrying the same
correction in its message. Both exit ``2``, the code a usage error already exited
with, so nothing that keyed on the exit changes.
"""

from dataclasses import dataclass
from typing import Optional

import typer
from typer.core import TyperGroup

# Typer 0.26 VENDORS click (``typer._click``), so a Typer parser raises
# ``typer._click.exceptions.*`` — NOT the identically named classes in the top-level
# ``click`` package, which are a DIFFERENT class object. Catching click's would leave
# every interception below silently dead, so the vendored classes are what is
# imported here. ``typer`` re-exports only ``BadParameter`` from that hierarchy, and
# a test pins that these classes are the ones it is built on, so a future Typer that
# moves them fails loudly instead of quietly disabling the refusal.
from typer._click import Context as ClickContext
from typer._click.exceptions import NoSuchOption, UsageError

from gda.errors import make_failure
from gda.headless import emit_failure, root_json

# The two registered codes this module reports (ADR-0002, the `usage` category).
UNKNOWN_COMMAND = "unknown_command"
UNKNOWN_OPTION = "unknown_option"

# Where the whole surface is enumerated — named in every hintless refusal, so a
# caller that gda cannot advise is still pointed somewhere useful.
DISCOVERY = "`gda schema` lists every command; `gda --help` lists the groups"


@dataclass(frozen=True)
class NearMiss:
    """One curated near miss: the invocation to run instead, and why it differs.

    ``use`` is a complete command line (it starts with ``gda``) because that is what
    the caller retypes, and it is what rides the envelope's machine-readable ``hint``.
    ``because`` is one clause for the human message — the difference, not a
    restatement of the correction.
    """

    use: str
    because: str


# The curated table. The key is the command path the token was rejected under —
# empty for the root — plus the token itself, so the same word can mean different
# things in different groups. One row per spelling the dogfooding record showed.
NEAR_MISSES: dict[tuple[str, ...], NearMiss] = {
    # GDA-DF-025: `inspect` is not a gda verb; the read verb is `get` in every group.
    ("scene", "inspect"): NearMiss(
        "gda scene get",
        "`get` is the read verb in every group (ADR-0005); it reports the scene's "
        "structured node tree",
    ),
    # GDA-DF-033 (script naming): the syntax/compile check is `validate`.
    ("script", "check"): NearMiss(
        "gda script validate",
        "`validate` syntax/compile-checks scripts — pass several paths for one "
        "batched engine launch, or `--all` for the whole project",
    ),
    # GDA-DF-032: the live read verb is `get`, like everywhere else; the property is
    # named by an option, not by the command.
    ("game", "get-property"): NearMiss(
        "gda game get",
        "the live read verb is `get` too; name the property with `--property`",
    ),
    # GDA-DF-041: what an agent means by "analyze" is gda's static analysis of the
    # project's scripts, which is `script validate` over the whole project (#663).
    ("analyze",): NearMiss(
        "gda script validate --all",
        "gda's static analysis is `script validate`; `--all` covers every script in "
        "the resolved project in one engine launch",
    ),
    # GDA-DF-041: "doctor" asks whether the toolchain is usable. The engine half is
    # `gda info`; the message also names the gda half, which spawns nothing.
    ("doctor",): NearMiss(
        "gda info",
        "`info` reports the engine gda would run; `gda --version --json` reports "
        "which gda is installed and where from, without spawning Godot",
    ),
    # GDA-DF-032: `--schema` is a per-COMMAND introspection flag; the whole-surface
    # manifest is its own command.
    ("--schema",): NearMiss(
        "gda schema",
        "`--schema` is a per-command flag; the whole-surface manifest is the "
        "`gda schema` command",
    ),
    # GDA-DF-032: `script run` takes its script positionally (ADR-0031), in either
    # portable form.
    ("script", "run", "--script"): NearMiss(
        "gda script run <path>",
        "`script run` takes the script as its positional argument, "
        "project-relative or `res://`",
    ),
}


def near_miss(
    path: tuple[str, ...], token: str, *, on_group: bool
) -> Optional[NearMiss]:
    """The curated correction for ``token`` under ``path``, or ``None``.

    The table is consulted first. The one rule that is NOT a spelling row follows: a
    ``--json`` rejected by a GROUP's own parser. Its correction depends on which group
    was addressed rather than on the group's name, and every group (including any
    added later) has it, so it is keyed on that SHAPE instead of on fifteen identical
    rows. It is also the spelling the bundled Skill documents as a usage error, which
    is how an agent that reads the guidance still ends up here.
    """
    hit = NEAR_MISSES.get((*path, token))
    if hit is not None:
        return hit
    if on_group and token == "--json" and path:
        return NearMiss(
            f"gda {' '.join(path)} <command> --json",
            "a group's own parser takes only `--help`; `--json` belongs to the "
            "command, or to the root before it",
        )
    return None


def _context_path(ctx: ClickContext) -> tuple[str, ...]:
    """The command path of ``ctx``, EXCLUDING the program name.

    Walked through the context parents rather than split out of
    ``ctx.command_path``: the root's own name is whatever the process was started as
    — ``python -m gda`` under the module entry point — so splitting that string on
    spaces would mis-key the table.
    """
    names: list[str] = []
    node: Optional[ClickContext] = ctx
    while node is not None and node.parent is not None:
        if node.info_name is not None:
            names.append(node.info_name)
        node = node.parent
    return tuple(reversed(names))


# The context-meta key the root parser records its raw argv under. ``ctx.meta`` is one
# dict shared by every context in the tree, so what the root records is readable from
# wherever the refusal is finally decided — including a leaf command's parser, whose
# own tokens are a slice of it.
RAW_ARGV_META_KEY = "gda.raw_argv"


def _remember_argv(ctx: ClickContext, args: list[str]) -> None:
    """Record the tokens the ROOT parser was handed (first writer wins)."""
    ctx.meta.setdefault(RAW_ARGV_META_KEY, list(args))


def _json_in_effect(ctx: ClickContext) -> bool:
    """Whether this invocation asked for JSON, by either spelling.

    A root ``--json`` is a parsed option and travels the ordinary way (#671). A
    ``--json`` written AFTER the offending token never parses — the command or option
    it would have belonged to does not exist — so the literal token in the recorded
    argv is the only evidence of the intent, and it is read as exactly that. The Skill
    teaches the trailing spelling, so leaving it out would answer most agents in
    prose.
    """
    if root_json(ctx):
        return True
    return "--json" in ctx.meta.get(RAW_ARGV_META_KEY, ())


def _sentence(message: str, hit: Optional[NearMiss], fallback: str) -> str:
    """The refusal's message: what was wrong, then what to do about it."""
    if hit is None:
        return f"{message}; {fallback}"
    return f"{message}. Use `{hit.use}` instead: {hit.because}"


def _refuse(
    ctx: ClickContext,
    *,
    code: str,
    message: str,
    fallback: str,
    hit: Optional[NearMiss],
) -> None:
    """Refuse the invocation, or return so the caller falls through to Typer.

    Never returns when it has answered: the JSON channel exits through
    :func:`gda.headless.emit_failure` (the one public failure channel, ADR-0002), and
    the human channel raises the usage error click renders. It DOES return when gda
    has nothing to add and no JSON was asked for — leaving Typer's own message, its
    did-you-mean guess included, exactly as it was.

    It also returns untouched under ``resilient_parsing``, click's own guard for the
    same failures: that mode parses an INCOMPLETE command line (shell completion), so
    an unrecognized token is expected there, and answering it would print an error
    envelope into the completion stream.
    """
    if ctx.resilient_parsing:
        return
    if _json_in_effect(ctx):
        emit_failure(
            make_failure(
                code,
                _sentence(message, hit, fallback),
                "",
                hint=hit.use if hit is not None else None,
            )
        )
    if hit is not None:
        raise UsageError(_sentence(message, hit, fallback), ctx)


def _is_option(token: str) -> bool:
    """Whether ``token`` is an option rather than a command name."""
    return token.startswith("-") and token != "-"


class GdaGroup(TyperGroup):
    """The click group gda mounts at every level, so a wrong invocation is reported.

    Mounted by the composition root onto the root app AND every group (``gda.cli``),
    which is what makes the three interception points below cover the whole tree.
    Everything it does is refusal-shaped: a resolvable command line reaches
    ``super()`` untouched.
    """

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        """Parse this group's own arguments; refuse an option it does not have."""
        # The ROOT's call is the first parse of the invocation, so this is where the
        # whole argv is recorded for every later refusal to read.
        _remember_argv(ctx, args)
        try:
            return super().parse_args(ctx, args)
        except NoSuchOption as exc:
            path = _context_path(ctx)
            _refuse(
                ctx,
                code=UNKNOWN_OPTION,
                message=f"`{ctx.command_path}` has no option `{exc.option_name}`",
                fallback=f"run `{ctx.command_path} --help` for the options it takes",
                hit=near_miss(path, exc.option_name, on_group=True),
            )
            raise

    def invoke(self, ctx: ClickContext):
        """Invoke the resolved subcommand; refuse an option ITS parser rejects.

        A leaf command's parse happens inside this call, so a leaf's unknown option
        surfaces here — the reason no leaf command class needs to know about hints.
        The exception carries the leaf's own context, which is what names the command
        and keys the table.
        """
        try:
            return super().invoke(ctx)
        except NoSuchOption as exc:
            leaf = exc.ctx if exc.ctx is not None else ctx
            _refuse(
                leaf,
                code=UNKNOWN_OPTION,
                message=f"`{leaf.command_path}` has no option `{exc.option_name}`",
                fallback=(
                    f"run `{leaf.command_path} --help` for the options it takes, or "
                    f"`{leaf.command_path} --schema` for its input contract"
                ),
                hit=near_miss(_context_path(leaf), exc.option_name, on_group=False),
            )
            raise

    def resolve_command(self, ctx: ClickContext, args: list[str]):
        """Resolve the next command word; refuse a name this group does not have.

        Checked BEFORE ``super()`` so a curated hint replaces Typer's difflib guess
        rather than arriving alongside it. An option-shaped token is left to
        ``super()``, which routes it back through this group's own parser — where it
        is an unknown OPTION, the failure it actually is.
        """
        if args and not _is_option(args[0]) and self.get_command(ctx, args[0]) is None:
            token = args[0]
            _refuse(
                ctx,
                code=UNKNOWN_COMMAND,
                message=f"`{ctx.command_path} {token}` is not a gda command",
                fallback=DISCOVERY,
                hit=near_miss(_context_path(ctx), token, on_group=False),
            )
        return super().resolve_command(ctx, args)


def adopt(app: typer.Typer) -> None:
    """Give ``app`` and every group mounted on it the gda group class.

    Applied once, in the composition root, AFTER every group has mounted itself — so
    a group module declares no dispatch behaviour and a group added later inherits
    the refusal by being mounted, which is the registration ADR-0040 already relies
    on. A test walks the live tree to pin that every group really has it.
    """
    app.info.cls = GdaGroup
    for group in app.registered_groups:
        group.cls = GdaGroup
