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
from typing import NoReturn, Optional

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
from typer._click.globals import get_current_context

from gda.errors import Failure, make_failure
from gda.headless import emit_failure, json_in_effect, remember_argv

# The two registered codes this module reports (ADR-0002, the `usage` category).
UNKNOWN_COMMAND = "unknown_command"
UNKNOWN_OPTION = "unknown_option"

# Where the whole surface is enumerated — named in every hintless refusal, so a
# caller that gda cannot advise is still pointed somewhere useful.
DISCOVERY = "`gda schema` lists every command; `gda --help` lists the groups"

# The name gda addresses ITSELF by, in a refusal's sentence and in the help text
# `gda help` renders. Fixed rather than read from the process, so the two arms that
# can refuse the same mistake produce the same sentence, and so a `python -m gda`
# invocation still names the command line a caller should type.
CLI_NAME = "gda"


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


def near_miss(path: tuple[str, ...], token: str) -> Optional[NearMiss]:
    """The curated correction for ``token`` under ``path``, or ``None``.

    Table lookups only. A group's ``--json`` was once corrected here by a rule keyed
    on the tree SHAPE rather than on a spelling; #683 gave every group the option, so
    the rule went with it — a hint pointing away from an invocation that now works
    would be worse than none.
    """
    return NEAR_MISSES.get((*path, token))


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


def _sentence(message: str, hit: Optional[NearMiss], fallback: str) -> str:
    """The refusal's message: what was wrong, then what to do about it."""
    if hit is None:
        return f"{message}; {fallback}"
    return f"{message}. Use `{hit.use}` instead: {hit.because}"


@dataclass(frozen=True)
class Refusal:
    """One built refusal: its registered code, its sentence, and its optional hint.

    Built ONCE per mistake — by :func:`unknown_command` or :func:`unknown_option` —
    and then answered in whichever channel the caller asked for. That split is what
    lets the two arms which can meet the SAME mistake (this module's group class, and
    ``gda help``'s path walk) answer it identically instead of each re-typing the
    sentence.
    """

    code: str
    message: str
    hint: Optional[str]

    def failure(self) -> Failure:
        """This refusal as the ADR-0002 structured failure."""
        return make_failure(self.code, self.message, "", hint=self.hint)


def unknown_command(path: tuple[str, ...], token: str) -> Refusal:
    """The refusal for ``token`` naming no command under ``path``.

    The invocation is spelled with the canonical ``gda`` rather than with the running
    program name: the sentence names the command line the caller should type, and the
    two arms agree verbatim even under ``python -m gda``, whose own name is
    ``python -m gda``.
    """
    hit = near_miss(path, token)
    named = " ".join([CLI_NAME, *path, token])
    return Refusal(
        UNKNOWN_COMMAND,
        _sentence(f"`{named}` is not a gda command", hit, DISCOVERY),
        hit.use if hit is not None else None,
    )


def unknown_option(path: tuple[str, ...], token: str, *, on_group: bool) -> Refusal:
    """The refusal for option ``token`` on the command ``path`` names.

    ``on_group`` picks the remedy, not the wording: a GROUP is read with ``--help``
    alone, while a leaf command also has ``--schema`` — its machine-readable input
    contract, which is what an agent should read next.
    """
    hit = near_miss(path, token)
    named = " ".join([CLI_NAME, *path])
    fallback = f"run `{named} --help` for the options it takes"
    if not on_group:
        fallback += f", or `{named} --schema` for its input contract"
    return Refusal(
        UNKNOWN_OPTION,
        _sentence(f"`{named}` has no option `{token}`", hit, fallback),
        hit.use if hit is not None else None,
    )


def _answer(ctx: ClickContext, refusal: Refusal) -> NoReturn:
    """Answer ``refusal`` in the channel the caller asked for. Never returns.

    The ONE answering path, so the JSON and human channels stay two renderings of one
    refusal: with ``--json`` in effect it is the ADR-0002 envelope through
    :func:`gda.headless.emit_failure` (the single public failure channel), otherwise
    the usage error click renders — carrying the same sentence, at the same exit code.
    """
    if json_in_effect(ctx):
        # ``json_output=True`` by construction: the branch IS the channel question,
        # asked here rather than inside the emitter because the human answer is not a
        # rendered envelope at all — it is click's own usage error, which carries the
        # same sentence and the same exit code (#685).
        emit_failure(refusal.failure(), json_output=True)
    raise UsageError(refusal.message, ctx)


def _refuse(ctx: ClickContext, refusal: Refusal) -> None:
    """Answer ``refusal`` at the PARSER, or return so the caller falls through.

    Adds the two rules that belong to the parser arm alone:

    - Under ``resilient_parsing`` it returns untouched — click's own guard for these
      same failures. That mode parses an INCOMPLETE command line (shell completion),
      where an unrecognized token is expected and an error envelope would be printed
      into the completion stream.
    - When gda has no advice AND no JSON was asked for, it returns so Typer's own
      message — its did-you-mean guess included — is left exactly as it was. gda
      speaks up only where it has something to add.
    """
    if ctx.resilient_parsing:
        return
    if refusal.hint is None and not json_in_effect(ctx):
        return
    _answer(ctx, refusal)


def refuse_unknown_command(path: tuple[str, ...], token: str) -> NoReturn:
    """Refuse a command path that names nothing, from OUTSIDE the parser.

    ``gda help scene inspect`` is the same mistake as ``gda scene inspect``, so it is
    answered by the same :class:`Refusal` in the same channel — the shared
    construction is the whole point, since a second hand-written sentence would drift
    from the first. Unlike the parser arm there is nothing to fall through TO (Typer
    never saw this token), so it always answers.

    The context is taken from click's ambient stack because a descriptor recipe is
    handed its params, not its context (ADR-0023) — and the channel question
    (:func:`gda.headless.json_in_effect`) is a property of the invocation, which is
    exactly what that stack holds.
    """
    _answer(get_current_context(), unknown_command(path, token))


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
        remember_argv(ctx, args)
        try:
            return super().parse_args(ctx, args)
        except NoSuchOption as exc:
            _refuse_option(ctx, exc, on_group=True)
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
            _refuse_option(ctx, exc, on_group=False)
            raise

    def resolve_command(self, ctx: ClickContext, args: list[str]):
        """Resolve the next command word; refuse a name this group does not have.

        Checked BEFORE ``super()`` so a curated hint replaces Typer's difflib guess
        rather than arriving alongside it. An option-shaped token is left to
        ``super()``, which routes it back through this group's own parser — where it
        is an unknown OPTION, the failure it actually is.
        """
        if args and not _is_option(args[0]) and self.get_command(ctx, args[0]) is None:
            _refuse(ctx, unknown_command(_context_path(ctx), args[0]))
        return super().resolve_command(ctx, args)


def _refuse_option(ctx: ClickContext, exc: NoSuchOption, *, on_group: bool) -> None:
    """The shared arm behind both places a ``NoSuchOption`` reaches this class.

    They differ only in WHOSE option it was: a group's own parser raises against the
    context it was handed, while a LEAF command's parser raises inside the parent
    group's ``invoke`` and carries the leaf's context on the exception. Resolving that
    one difference here keeps the two arms a single line each.
    """
    target = ctx if on_group or exc.ctx is None else exc.ctx
    _refuse(
        target,
        unknown_option(_context_path(target), exc.option_name, on_group=on_group),
    )


def adopt(app: typer.Typer) -> None:
    """Give ``app`` and every group mounted BELOW it the gda group class.

    Applied once, in the composition root, AFTER every group has mounted itself — so a
    group module declares no dispatch behaviour and a group added later inherits the
    refusal by being mounted, which is the registration ADR-0040 already relies on.
    The walk RECURSES rather than reading only the root's own groups: gda's tree is two
    levels deep today, and a sub-group mounted on a sub-app would otherwise escape the
    interception silently. A test walks the live tree, recursively, to pin it.
    """
    app.info.cls = GdaGroup
    _adopt_groups(app)


def _adopt_groups(app: typer.Typer) -> None:
    """Set the class on every group of ``app``, and on their groups in turn."""
    for group in app.registered_groups:
        group.cls = GdaGroup
        if group.typer_instance is not None:
            _adopt_groups(group.typer_instance)
