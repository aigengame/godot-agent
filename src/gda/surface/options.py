"""The options every ``gda`` command shares (ADR-0045 §2).

Split out of the headless descriptor module: the option factories, the names of
the global options, and the propagation of a ``--json`` given above the invoked
command to that command.
"""

from collections.abc import Iterator
from typing import Optional

import typer
from typer._click import Context as ClickContext
from typer.models import TyperInfo


# The context-meta key a ``--json`` given ABOVE the invoked command is recorded
# under (#671, #683). ``ctx.meta`` is ONE dict shared by every context in the tree
# (click nests it from the parent), so what an ancestor parser records — the root
# callback, or a group's — is readable from the invoked command's context. Dotted
# and package-scoped, per click's documented convention for the namespace.
ANCESTOR_JSON_META_KEY = "gda.ancestor_json"


def set_ancestor_json(ctx: typer.Context, value: bool) -> None:
    """Record a ``--json`` an ANCESTOR parser bound, for the command it invokes.

    The write half of the contract, owned HERE next to the options that read it
    (:func:`_inherit_ancestor_json`, :func:`ancestor_json`), so the knowledge runs
    downward: the CLI composition root CALLS this to hand its root flag over,
    instead of this module reaching up into that module's private parameter names.
    A group hands its own flag over the same way (:func:`adopt_group_json`), which
    is what makes the three parser sites one contract rather than three.
    """
    ctx.meta[ANCESTOR_JSON_META_KEY] = bool(value)


def ancestor_json(ctx: ClickContext) -> bool:
    """Whether a ``--json`` above the invoked command was recorded (#659, #683).

    The read half of the same contract, for the readers that are not a command: the
    root's own ``--version``, which renders either a human line or the structured
    provenance payload and so must ask the same question a command's inherited flag
    asks; and the unknown-invocation refusal (``gda.surface.hints``, #670), which must
    answer in the channel the caller asked for. Neither re-derives where the answer is
    kept.

    ``ctx`` is typed as the click ``Context`` Typer builds on, not ``typer.Context``,
    because the refusal is decided inside the click group class and holds that one;
    ``typer.Context`` is a subclass, so every existing caller still fits, and this
    function only ever reads ``ctx.meta``.
    """
    return bool(ctx.meta.get(ANCESTOR_JSON_META_KEY, False))


# The context-meta key the root parser records its raw argv under. ``ctx.meta`` is one
# dict shared by every context in the tree, so what the root records is readable from
# wherever the channel is finally decided — including a leaf command's parser, whose
# own tokens are a slice of it.
RAW_ARGV_META_KEY = "gda.raw_argv"


def remember_argv(ctx: ClickContext, args: list[str]) -> None:
    """Record the tokens the ROOT parser was handed (first writer wins).

    The write half of the third reading :func:`json_in_effect` makes. Called from the
    group class the composition root mounts (``gda.surface.hints.GdaGroup``), which is
    where the root's first parse happens.
    """
    ctx.meta.setdefault(RAW_ARGV_META_KEY, list(args))


def json_in_effect(ctx: ClickContext) -> bool:
    """Whether this invocation asked for JSON, in three ordered readings.

    1. The command's OWN resolved flag, when the question is asked after its parse —
       the case for a dispatched command and for ``gda help <unknown>``. It already
       carries an inherited ancestor ``--json`` (:func:`_inherit_ancestor_json`), so
       it answers for every spelling wherever it exists.
    2. The ancestor ``--json``, recorded when the root callback (#671) or a group's
       (#683) bound it — the reading available at parse time, before any command's
       params exist.
    3. The literal token in the recorded argv. A ``--json`` written AFTER an
       offending token never parses, because the command or option it would have
       belonged to does not exist, so the token itself is the only evidence of the
       intent — and it is read as exactly that. The Skill teaches the trailing
       spelling, so leaving this reading out would answer most agents in prose.

    It lives HERE, beside :func:`ancestor_json` and the option that inherits it, rather
    than with the near-miss refusal that introduced it (``gda.surface.hints``, #670).
    :func:`~gda.surface.descriptor.emit_failure` does NOT ask it — it takes
    ``json_output`` as a required keyword and never reads a context; the askers in
    ``gda.surface.descriptor`` are the two ``--params-json`` refusals in
    ``_SchemaCommand.invoke``, which hold a click context and no flag. What settles the
    direction is the import: ``gda.surface.hints`` already depends on
    ``gda.surface.descriptor`` for the failure channel, so a channel question owned by
    ``hints`` would need that import to run backwards (#685).
    """
    if bool(ctx.params.get("json_output")):
        return True
    if ancestor_json(ctx):
        return True
    return "--json" in ctx.meta.get(RAW_ARGV_META_KEY, ())


def _inherit_ancestor_json(
    ctx: typer.Context, param: typer.CallbackParam, value: bool
) -> bool:
    """Let a ``--json`` written above the command stand for the command's own.

    The Skill teaches ONE rule — "always pass ``--json``" — and an agent may spell
    it at the root (``gda --json node get …``), between the group and the command
    (``gda node --json get …``, #683), or after the command
    (``gda node get … --json``). All three must MEAN the same thing, or accepting
    the outer ones would be worse than rejecting them: a silently inert flag returns
    human text to a caller that asked for JSON, where the old ``No such option`` at
    least failed loudly.

    A command's own flag wins when given; otherwise the value an ancestor recorded
    through :func:`set_ancestor_json` applies — click binds a parser's own options
    before it parses the subcommand, so the record is already in place. Living on
    the shared :func:`json_option` means every call site inherits it with no
    per-command wiring, including the ``--params-json`` dispatch path, which reads
    ``ctx.params`` after this callback has run.
    """
    return bool(value) or ancestor_json(ctx)


def json_option() -> bool:
    return typer.Option(
        False,
        "--json",
        callback=_inherit_ancestor_json,
        help="Emit the result as a single JSON object.",
    )


def _record_group_json(
    ctx: typer.Context, param: typer.CallbackParam, value: bool
) -> bool:
    """Hand a GROUP's ``--json`` down to the command that group is about to run.

    Bound from the option's OWN callback rather than from the group callback's body,
    so the record is in place before click parses the subcommand no matter what the
    group body later grows — the shape the root already uses (``gda.cli``).

    Only a GIVEN flag is recorded: the option's ``False`` default must not erase a
    root ``--json`` the outer parser recorded, or the outer spelling would depend on
    the inner one.
    """
    if value:
        set_ancestor_json(ctx, True)
    return value


def _group_json(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        callback=_record_group_json,
        help="Emit the invoked command's result as JSON — the same as passing "
        "--json after the command.",
    ),
) -> None:
    """The callback every command group is given, so ``--json`` parses there too.

    One function shared by all of them: the flag means the same thing under every
    group, and the same rule written once per group would be that many chances to
    drift. Its body has nothing to do — the option's own callback did the work — but
    the function must exist, because a group's options ARE its callback's parameters.
    """


def walk_mounted_groups(app: typer.Typer) -> Iterator[TyperInfo]:
    """Every command group mounted below ``app``, at any depth (#788).

    The ONE walk over the mounted-group tree, so a cross-cutting group behavior is
    written as a visitor over this rather than as another copy of the recursion. Two
    visitors today: the shared ``--json`` option (:func:`adopt_group_json`, below) and
    the refusal class (``gda.surface.hints.adopt``). It walks the REGISTRATION-time tree
    — the ``TyperInfo`` records ``add_typer`` leaves behind — because that is the only
    representation that exists before Typer builds the click tree, and so the only one a
    composition-time adopter can install anything onto. The BUILT click tree is a
    different walk for a different purpose — reading a finished surface
    (``gda.surface.manifest``).

    **The ordering precondition, stated here once for every visitor:** the walk reports
    what is mounted AT THE MOMENT IT RUNS, so the composition root (``gda.cli``) mounts
    the whole tree first and adopts afterwards. A group mounted after an adoption is
    never visited by it and silently keeps none of what it installs.

    What is yielded is the registration record, not the sub-app: it is the wider handle
    — the group's ``name`` and ``cls`` as well as its ``typer_instance`` — and one
    visitor writes to the record itself. Typer types that instance as optional, so the
    RECURSION skips a group without one: it carries no groups to descend into, and
    Typer refuses to build such a group into a command at all. A visitor that needs the
    instance says so itself; the walk does not decide that for it.
    """
    # Snapshot, so the docstring's "what is mounted at the moment it runs" is
    # literally true: a visitor that mounts a group MID-WALK is excluded rather
    # than lazily swept in (#792 review P3-2 — no visitor does this today; the
    # snapshot makes the documented boundary the actual one).
    for group in list(app.registered_groups):
        yield group
        instance = group.typer_instance
        if instance is not None:
            yield from walk_mounted_groups(instance)


def adopt_group_json(app: typer.Typer) -> None:
    """Give every group mounted below ``app`` the shared ``--json`` option (#683).

    The third parser site. ``gda --json <group> <command>`` and
    ``gda <group> <command> --json`` already meant the same thing; the spelling in
    between died with ``No such option``, so the one rule the Skill teaches broke on
    a line an agent composes naturally. Applied once from the composition root,
    AFTER every group has mounted itself, for the reason ``gda.surface.hints.adopt`` is:
    it is one property of the WHOLE surface, so a group added later inherits the option
    by being mounted rather than by remembering to declare it. Reaching a sub-group of a
    group — which would otherwise be missed silently — is the shared walk's job
    (:func:`walk_mounted_groups`), including the ordering precondition it states.

    Installing the option means installing the callback that carries it, so a group
    that declares a callback of its own is refused rather than silently replaced:
    such a group must declare the shared option on that callback itself. That refusal
    stays a property of THIS visitor, not of the walk it rides: it guards the one slot
    this adoption writes, and the other visitor overwrites no such slot.
    """
    for group in walk_mounted_groups(app):
        instance = group.typer_instance
        # A group registered without a sub-app has no callback to carry the option;
        # the walk's own contract leaves that reading to each visitor.
        if instance is None:
            continue
        if instance.registered_callback is not None:
            raise RuntimeError(
                f"command group {group.name!r} declares its own callback; declare "
                "the shared --json option on it instead of letting "
                "gda.surface.options.adopt_group_json replace it."
            )
        instance.callback()(_group_json)


def godot_option() -> Optional[str]:
    return typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    )


def project_option() -> Optional[str]:
    return typer.Option(
        None,
        "--project",
        help="Godot project directory for res:// resolution "
        "(overrides $GDA_PROJECT; defaults to the current directory if it is a project).",
    )


def schema_option() -> bool:
    """A plain ``--schema`` boolean flag.

    Emission is owned by the command class
    (:func:`~gda.surface.descriptor.schema_command_class`), not an eager callback: a
    bare ``bool`` binds ``False`` when absent (not ``None``) and yields to an eager
    ``--help`` (issue #36).
    """
    return typer.Option(
        False,
        "--schema",
        help="Emit this command's input/output/error JSON Schemas; no Godot is spawned.",
    )


def params_json_option() -> Optional[str]:
    """A ``--params-json`` option: supply the command's params as one JSON object.

    The value is a JSON object of the command's params, or ``-`` to read the object from
    stdin (ADR-0015). It is mutually exclusive with the individual arguments; the
    command class (:func:`~gda.surface.descriptor.schema_command_class`) intercepts it,
    builds the input model from the JSON, and dispatches through the same execution tail
    the argv path uses, so ``gda-mcp`` can forward an MCP tool's input object verbatim
    without reconstructing argv.
    """
    return typer.Option(
        None,
        "--params-json",
        help="Supply params as one JSON object (or '-' to read it from stdin); "
        "mutually exclusive with the individual arguments.",
    )


# The cross-cutting options every command shares; they compose with
# ``--params-json`` rather than counting as the individual operation arguments it
# is mutually exclusive with (ADR-0015).
_GLOBAL_OPTION_NAMES = frozenset(
    {"json_output", "schema", "params_json", "godot", "project"}
)
