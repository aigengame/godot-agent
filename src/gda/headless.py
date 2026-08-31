"""Headless command execution for ``gda``.

A headless command declares the small interface that varies per command:
operation name, input model, output model, and human rendering.
This module owns the shared implementation behind that interface: schema
emission, Godot binary resolution, runner construction, diagnostics forwarding,
classification, failure output, and JSON rendering.
"""

import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, NoReturn, Optional, TypeVar

import typer
from pydantic import BaseModel, ValidationError
from typer._click import Context as ClickContext
from typer.core import TyperCommand
from typer.models import TyperInfo

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_live,
    classify_run,
    conflicting_params_input_failure,
    invalid_params_json_failure,
    unresolvable_binary_failure,
    validation_error_message,
)
from gda.execution import ExecutionKind, live_stack_constraints
from gda.models import (
    ArgvBinding,
    ArgvKind,
    CommandSchema,
    GdaErrorEnvelope,
    LiveStackConstraints,
)
from gda.render import render_failure
from gda.runner import GodotRunner, RunResult, SubprocessGodotRunner

M = TypeVar("M", bound=BaseModel)

Classifier = Callable[[RunResult, Path], M | Failure]
# A command's human renderer: its result model -> text. Carried on the descriptor
# (ADR-0023) so a command renders through its own registration, not a central
# type-keyed table.
Renderer = Callable[[M], str]
# A recipe command's CLI-side execution channel (ADR-0023): given the built params
# model and the CLI context, it PRODUCES the outcome (resolve + run), returning the
# result model or a Failure. Carried on the descriptor so a command with a recipe
# is fulfilled by it instead of the sentinel `emit`; emission stays the shared tail
# (the descriptor's `render`), so a recipe command renders identically to a
# sentinel one. ``export run`` / the ``daemon`` lifecycle / ``screen`` are recipes.
# Not parameterized over ``M``: the recipe's keyword-only context means an Ellipsis
# parameter spec (``Callable[..., …]``), which is not a subscriptable generic alias.
Recipe = Callable[..., "BaseModel | Failure"]
RunnerFactory = Callable[[Path, Optional[Path]], GodotRunner]


def make_subprocess_runner(binary: Path, project: Optional[Path] = None) -> GodotRunner:
    """Build the default real Godot runner for ``binary`` and ``project``."""
    return SubprocessGodotRunner(binary, project=project)


def command_constraints(
    command: "Optional[HeadlessCommand]",
) -> Optional[LiveStackConstraints]:
    """Wrap a command's live-stack constraint into the model, or ``None``.

    The one place the leaf :func:`gda.execution.live_stack_constraints`
    predicate's primitives are lifted into the :class:`LiveStackConstraints`
    model, shared by the per-command ``--schema`` path here and the aggregate
    manifest builder (``gda.surface``) so the two forms cannot drift (issue
    #233). ``None`` for a command with no backing descriptor (the bare ``gda
    schema`` meta command) and for any command the predicate reports no live-stack
    dependence for.
    """
    if command is None:
        return None
    constraint = live_stack_constraints(command.kind, command.operation)
    if constraint is None:
        return None
    platforms, min_godot_version = constraint
    return LiveStackConstraints(
        platforms=platforms, min_godot_version=min_godot_version
    )


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
    asks; and the unknown-invocation refusal (``gda.hints``, #670), which must answer
    in the channel the caller asked for. Neither re-derives where the answer is kept.

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

    The write half of the third reading :func:`json_in_effect` makes. Called from
    the group class the composition root mounts (``gda.hints.GdaGroup``), which is
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

    It lives HERE, beside :func:`ancestor_json` and the option that inherits it,
    rather than with the near-miss refusal that introduced it (``gda.hints``, #670).
    :func:`emit_failure` does NOT ask it — it takes ``json_output`` as a required
    keyword and never reads a context; the askers in this module are the two
    ``--params-json`` refusals in ``_SchemaCommand.invoke``, which hold a click
    context and no flag. What settles the direction is the import: ``gda.hints``
    already depends on this module for the failure channel, so a channel question
    owned by ``hints`` would need that import to run backwards (#685).
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
    the refusal class (``gda.hints.adopt``). It walks the REGISTRATION-time tree — the
    ``TyperInfo`` records ``add_typer`` leaves behind — because that is the only
    representation that exists before Typer builds the click tree, and so the only one
    a composition-time adopter can install anything onto. The BUILT click tree is a
    different walk for a different purpose — reading a finished surface
    (``gda.surface``).

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
    for group in app.registered_groups:
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
    AFTER every group has mounted itself, for the reason ``gda.hints.adopt`` is: it
    is one property of the WHOLE surface, so a group added later inherits the option
    by being mounted rather than by remembering to declare it. Reaching a sub-group of
    a group — which would otherwise be missed silently — is the shared walk's job
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
                "gda.headless.adopt_group_json replace it."
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

    Emission is owned by the command class (:func:`schema_command_class`), not an
    eager callback: a bare ``bool`` binds ``False`` when absent (not ``None``)
    and yields to an eager ``--help`` (issue #36).
    """
    return typer.Option(
        False,
        "--schema",
        help="Emit this command's input/output/error JSON Schemas; no Godot is spawned.",
    )


def params_json_option() -> Optional[str]:
    """A ``--params-json`` option: supply the command's params as one JSON object.

    The value is a JSON object of the command's params, or ``-`` to read the
    object from stdin (ADR-0015). It is mutually exclusive with the individual
    arguments; the command class (:func:`schema_command_class`) intercepts it,
    builds the input model from the JSON, and dispatches through the same
    execution tail the argv path uses, so ``gda-mcp`` can forward an MCP tool's
    input object verbatim without reconstructing argv.
    """
    return typer.Option(
        None,
        "--params-json",
        help="Supply params as one JSON object (or '-' to read it from stdin); "
        "mutually exclusive with the individual arguments.",
    )


# A hook registered by gda.dispatch that runs a command from a params model built
# off ``--params-json``, through the same project-resolution + runner seam the argv
# path uses. Held as a hook so this module need not import the CLI layer (ADR-0015).
ParamsJsonDispatch = Callable[["HeadlessCommand", BaseModel, "typer.Context"], None]
_params_json_dispatch: Optional[ParamsJsonDispatch] = None


def register_params_json_dispatch(dispatch: ParamsJsonDispatch) -> None:
    """Register the CLI-layer dispatcher used by the ``--params-json`` path."""
    global _params_json_dispatch
    _params_json_dispatch = dispatch


# The cross-cutting options every command shares; they compose with
# ``--params-json`` rather than counting as the individual operation arguments it
# is mutually exclusive with (ADR-0015).
_GLOBAL_OPTION_NAMES = frozenset(
    {"json_output", "schema", "params_json", "godot", "project"}
)


def _from_command_line(ctx: typer.Context, name: str) -> bool:
    """True when ``name`` was supplied on the command line, not left at default.

    Compares the Click ``ParameterSource`` by member name so this module need
    not import Click (a transitive dependency through Typer).
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


def command_argv_bindings(
    command: object, input_model: type[BaseModel]
) -> list[ArgvBinding]:
    """Project ``command``'s live Click parameters into their CLI spelling (#669).

    The one place a command's argv form is derived, shared by the per-command
    ``--schema`` here and the aggregate manifest builder (``gda.surface``) so the
    two forms cannot drift — the same shape :func:`command_constraints` gives the
    live-stack precondition. The rationale, the boundaries and the case inventory
    live in the ADR-0004 amendment (#669); this is the derivation.

    Which parameters are operational reuses a rule this module already owns:
    :data:`_GLOBAL_OPTION_NAMES`, the same set ``--params-json`` treats as
    cross-cutting (ADR-0015). The ``expose_value`` arm has no case on today's
    surface — Click appends its own ``--help`` in ``get_params``, not here — and
    guards a future unexposed parameter, which by definition reaches no params
    model.

    Click is duck-typed through ``getattr``, as the surface walker does: it is a
    transitive dependency through Typer, not a direct one.
    """
    properties = input_model.model_json_schema().get("properties", {})
    bindings: list[ArgvBinding] = []
    position = 0
    for param in getattr(command, "params", []):
        if not getattr(param, "expose_value", True):
            continue
        name = getattr(param, "name", None)
        if not isinstance(name, str) or name in _GLOBAL_OPTION_NAMES:
            continue
        opts = [str(opt) for opt in getattr(param, "opts", [])]
        is_argument = getattr(param, "param_type_name", "") == "argument"
        long_opts = [opt for opt in opts if opt.startswith("--")]
        option = None if is_argument else next(iter(long_opts or opts), None)
        # A variadic positional (``nargs=-1``) is repeated the same way a
        # repeatable option is, so both report ``multiple``: Click spells the
        # two differently, an argv author writes both by repeating.
        nargs = getattr(param, "nargs", 1)
        multiple = bool(getattr(param, "multiple", False)) or nargs == -1
        bound = _bound_property(name, option, properties)
        bindings.append(
            ArgvBinding(
                name=name,
                input_property=bound,
                kind=ArgvKind.ARGUMENT if is_argument else ArgvKind.OPTION,
                option=option,
                position=position if is_argument else None,
                required=bool(getattr(param, "required", False)),
                flag=bool(getattr(param, "is_flag", False)),
                multiple=multiple,
                json_value=_takes_a_json_value(bound, properties, multiple),
            )
        )
        if is_argument:
            position += 1
    return bindings


def _bound_property(
    name: str, option: Optional[str], properties: "dict[str, Any]"
) -> Optional[str]:
    """The ``input`` property this parameter fills, or ``None`` if undecidable."""
    if name in properties:
        return name
    if option is not None:
        spelled = option.lstrip("-").replace("-", "_")
        if spelled in properties:
            return spelled
    return None


def _takes_a_json_value(
    bound: Optional[str], properties: "dict[str, Any]", multiple: bool
) -> bool:
    """Whether the parameter's one token is the property's JSON encoding (#669).

    A compound property reaches argv as a REPEATED token, which ``multiple``
    already reports, or as a single token carrying its JSON. ``False`` without a
    property link: unknown, and a wrong ``true`` would send a caller to encode a
    plain string. Sees a declared ``type`` and a compound behind an ``anyOf`` /
    ``oneOf`` — the nullable-compound shape (``list | null``) that
    ``--await-events`` introduced (#661); a registration test keeps this
    detector and the published bindings agreeing
    (``tests/test_schema_command.py``).
    """
    spec = properties.get(bound or "")
    if not isinstance(spec, dict) or multiple:
        return False
    return _is_compound_spec(spec)


def _is_compound_spec(spec: "dict[str, Any]") -> bool:
    """Whether a property schema is an array/object, INCLUDING behind an anyOf."""
    if spec.get("type") in ("array", "object"):
        return True
    branches = spec.get("anyOf") or spec.get("oneOf") or []
    return any(
        _is_compound_spec(branch) for branch in branches if isinstance(branch, dict)
    )


def schema_command_class(
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    command: "Optional[HeadlessCommand]" = None,
) -> type[TyperCommand]:
    """A Typer command that owns ``--schema`` handling (ADR-0004).

    ``--schema`` is an introspection probe: it emits the command's
    ``{input, output, error}`` contract without spawning Godot and without
    requiring the command's operational arguments. ``error`` is the uniform
    failure envelope shared by every command (#43). It must still surface a
    structurally invalid command line — unknown options or extra positional
    args — as a usage error, and must always yield to ``--help`` (issue #36).
    """

    class _SchemaCommand(TyperCommand):
        # Expose the command's models so the aggregate-schema walker
        # (gda.surface) can reuse CommandSchema.of per command when it walks the
        # live Typer tree, instead of re-deriving the contract a second way
        # (ADR-0012). The closure above keeps them for `--schema`; these make
        # the same single source readable off the registered command object.
        # ``gda_command`` carries the full HeadlessCommand so the ``--params-json``
        # path can dispatch the operation (ADR-0015); None for the bare ``gda
        # schema`` meta command, which has no operation to run.
        gda_input_model = input_model
        gda_output_model = output_model
        gda_command = command

        def _parse_relaxed(self, ctx: typer.Context, args: list[str]) -> list[str]:
            # Parse with required args relaxed, so a probe that omits the
            # individual operation args still succeeds, while Click still rejects
            # unknown options / extra positionals and an eager ``--help`` still
            # wins. Restore afterwards: Typer reuses the command object across
            # invocations. Shared by the ``--schema`` and ``--params-json`` paths.
            relaxed = [(param, param.required) for param in self.params]
            try:
                for param, _ in relaxed:
                    param.required = False
                return super().parse_args(ctx, list(args))
            finally:
                for param, required in relaxed:
                    param.required = required

        def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
            if "--schema" in args:
                self._parse_relaxed(ctx, args)
                # Carry the command's static execution channel (ADR-0017) from
                # the one source of truth — the backing ``HeadlessCommand.kind``
                # — into the self-description (issue #230). ``ExecutionKind``
                # subclasses ``str``, so it serializes as the lowercase value
                # ("headless"/"export"/"live"). ``None`` for the bare ``gda
                # schema`` meta command, which has no backing command to run.
                kind = command.kind if command is not None else None
                # The live-stack constraint (issue #233) comes from the same one
                # source of truth — the predicate keyed on the backing command's
                # ``kind`` + ``operation`` — wrapped into the model here so the
                # per-command ``--schema`` and the aggregate manifest agree.
                constraints = command_constraints(command)
                # The CLI spelling of this command's parameters (#669), read off
                # THIS command object's live Click parameters — the same single
                # derivation the aggregate manifest uses. Taken after the relaxed
                # parse above has restored each parameter's declared ``required``,
                # so the published binding reports the real requirement rather
                # than the probe's relaxation (issue #36).
                argv = command_argv_bindings(self, input_model)
                typer.echo(
                    CommandSchema.of(
                        input_model,
                        output_model,
                        kind=kind,
                        constraints=constraints,
                        argv=argv,
                    ).model_dump_json()
                )
                raise typer.Exit()
            if command is not None and "--params-json" in args:
                # The individual operation args are absent — supplied by the JSON
                # object instead; ``invoke`` builds the model and dispatches.
                return self._parse_relaxed(ctx, args)
            return super().parse_args(ctx, args)

        def invoke(self, ctx: typer.Context):
            if command is not None and ctx.params.get("params_json") is not None:
                # --params-json supplies ALL operation params, so no individual
                # operation argument may also be given on the command line; the
                # global flags (--json/--godot/--project/--schema) still compose.
                if any(
                    name not in _GLOBAL_OPTION_NAMES and _from_command_line(ctx, name)
                    for name in ctx.params
                ):
                    emit_failure(
                        conflicting_params_input_failure(),
                        json_output=json_in_effect(ctx),
                    )
                raw = ctx.params["params_json"]
                # ``-`` reads the object from stdin so large payloads avoid OS
                # argv length limits and process-listing leakage (ADR-0015).
                text = sys.stdin.read() if raw == "-" else raw
                try:
                    model = command.input_model.model_validate_json(text)
                except ValidationError as exc:
                    # The same clean-sentence extractor the argv path's
                    # params_or_bad_parameter uses (gda.errors.validation_error_message,
                    # #713 review round 3), so both input channels report the identical
                    # refusal for the identical violation — not str(exc)'s dump of the
                    # model class name, a [type=..., input_value=..., input_type=...]
                    # tag per error, and a pydantic.dev URL, which used to echo the
                    # caller's OTHER field values (e.g. a large --content payload) back
                    # into the structured envelope's message.
                    emit_failure(
                        invalid_params_json_failure(validation_error_message(exc)),
                        json_output=json_in_effect(ctx),
                    )
                if _params_json_dispatch is None:  # pragma: no cover - misconfig
                    raise RuntimeError(
                        "no --params-json dispatcher registered; gda.dispatch must call "
                        "register_params_json_dispatch()"
                    )
                _params_json_dispatch(command, model, ctx)
                return None
            return super().invoke(ctx)

    return _SchemaCommand


def emit_failure(failure: Failure, *, json_output: bool) -> NoReturn:
    """Emit a failure on the channel the caller asked for, and exit non-zero.

    The single home for the public failure channel (ADR-0002), and — like
    :func:`emit_result` for the success channel — TWO renderings of one outcome: a
    ``Failure`` becomes the ``{"error": {...}}`` envelope under ``--json``, else the
    human lines of :func:`gda.render.render_failure`. Either way it selects the
    process exit code, which is the same on both channels. Shared by the
    sentinel-pipeline commands (via :meth:`HeadlessCommand.run`), the native-export
    command (``export run``), the CLI dispatch tails, and the near-miss refusal
    (``gda.hints``).

    ``json_output`` is REQUIRED and keyword-only: until #685 this function had no
    channel to choose, so every call site emitted JSON whether or not the caller had
    asked for it, and a human read a labelled ``script run --strict`` capture as one
    escaped line. Making it explicit is what keeps that from silently returning: a
    new call site cannot default its way back into the wrong channel. Where the
    caller holds a click context rather than the flag, :func:`json_in_effect`
    answers it.

    ``exclude_none`` keeps the envelope's OPTIONAL context keys out of the JSON
    entirely when a failure has none, rather than emitting them as ``null``. So
    adding such a key leaves every failure that does not set it byte-identical —
    the property that makes the optional-context axis additive for existing
    consumers. Three keys ride it now, one per ADR-0004 amendment: ``probe``
    (#667), ``hint`` (#670) and ``evidence`` (#687). The required keys
    (``category`` / ``code`` / ``message`` / ``diagnostics``) are never ``None``,
    so none of them can be dropped by this.

    The filter RECURSES, which is what lets ``evidence`` carry one fixed shape
    whose unset fields cost nothing. It stops at one boundary: a model nested
    inside ``evidence`` that is ALSO published on a success result keeps its full
    key set, so a record does not read differently depending on which half of the
    contract carried it (:class:`gda.models.FailureEvidence`).

    The child run's stderr (``failure.child_stderr``, attached by
    :meth:`HeadlessCommand.execute`) is forwarded to this process's stderr here,
    where the channel is known — EXCEPT when the human channel is about to print
    the very same bytes as ``diagnostics``, which would say one stream twice
    across two streams (#798 review). Byte identity decides, not the error code:
    a curated or capped ``diagnostics`` (the labeled ``--strict`` sections, a
    timeout's tail-capped captures) differs from the raw stream, so its tee — the
    only copy that is complete — survives. Under ``--json`` the tee is
    unconditional, keeping that channel's bytes exactly as they were.
    """
    if failure.child_stderr and (
        json_output or failure.error.diagnostics != failure.child_stderr
    ):
        print(failure.child_stderr, end="", file=sys.stderr)
    if json_output:
        typer.echo(
            GdaErrorEnvelope(error=failure.error).model_dump_json(exclude_none=True)
        )
    else:
        typer.echo(render_failure(failure.error))
    raise typer.Exit(code=failure.exit_code)


def emit_result(
    result: BaseModel, json_output: bool, render: "Callable[[Any], str]"
) -> None:
    """Emit a typed success result as JSON or human-readable text.

    The single home for the public success channel: a result model becomes its
    ``--json`` serialization when ``json_output``, else the human text produced by
    the command's own ``render`` (its descriptor's renderer, ADR-0023). Shared by
    the sentinel-pipeline commands (via :meth:`HeadlessCommand.emit`) and the
    recipe commands (``export run``, the ``daemon`` lifecycle, ``screen``), which
    pass their descriptor's renderer so every command renders success identically.

    ``render`` is always present: it is a required descriptor field (ADR-0023), and
    both ``emit`` and the recipe dispatch pass ``cmd.render``.
    """
    if json_output:
        typer.echo(result.model_dump_json())
    else:
        typer.echo(render(result))


@dataclass(frozen=True)
class HeadlessCommand(Generic[M]):
    """A deep module for one Phase-1 headless operation.

    The interface is intentionally small: command modules supply the pieces that
    are actually command-specific, while this implementation preserves the
    shared ADR-0001/0002/0004 execution contract in one place.
    """

    operation: str
    input_model: type[BaseModel]
    output_model: type[M]
    # The command's human renderer — its result model -> text (ADR-0023). A command
    # renders through its own descriptor, so there is no central type-keyed table to
    # keep in sync. REQUIRED (no default): every command renders, so the type system
    # carries the guarantee; the registration invariant test also enforces it on the
    # live command tree.
    render: Renderer[M]
    # The command's own failure classifier, for the operations that need one (the
    # export recipe, ``gda info``'s version fallback, …). ``None`` (the default)
    # selects the classifier from ``kind``: ``classify_run`` for the headless
    # kinds, ``classify_live`` for LIVE — which is exactly ``classify_run`` plus
    # the LIVE error envelope, the reuse ADR-0017 intended. So a live command
    # declares its channel once, in ``kind``, and needs no per-command classifier.
    classify: Classifier[M] | None = None
    # The static execution channel this command is fulfilled through (ADR-0017).
    # Defaults to HEADLESS — the sentinel ``operations.gd`` pipeline — so every
    # existing command keeps its channel without restating it; EXPORT and LIVE
    # commands declare their channel explicitly.
    kind: ExecutionKind = ExecutionKind.HEADLESS
    # The command's CLI-side execution channel (ADR-0023). When set, the command is a
    # recipe (``export run`` / ``daemon`` lifecycle / ``screen``): dispatch runs this
    # to produce the outcome instead of the sentinel ``emit``. ``None`` (the default)
    # means the command runs through ``emit`` with its ``kind``-selected runner — so a
    # single ``recipe is None`` test selects the channel, no identity table.
    recipe: "Recipe | None" = None
    # Whether the command INHERITS a project context ($GDA_PROJECT, then the cwd)
    # when no explicit ``--project`` is given. This field decides inheritance and
    # NOTHING else. A meta command (ADR-0005/0024 — ``skill``, ``version``,
    # ``help``, ``info``) sets it ``False``: it is about ``gda`` or the engine
    # itself, so an inherited value that is not a project must not break the
    # commands an agent reaches for FIRST when something is wrong (#353/#357).
    # Whether a command ACCEPTS an explicit ``--project`` is its CLI signature's
    # decision, not this field's: ``gda info`` declares the option for uniform
    # orchestration argv and has it validated like anywhere else (#670), while
    # ``skill``/``version``/``help`` declare none, so a passed ``--project`` is
    # the usual unknown-option refusal there. Project-using commands leave this
    # ``True`` and receive the fully resolved project (or a structured
    # ``project_not_found``). Read by every dispatch tail
    # (``gda.dispatch._project_context``), so it applies to the sentinel channel
    # as much as to a recipe.
    inherits_project: bool = True

    def schema_option(self) -> bool:
        """Return the Typer ``--schema`` flag for this command."""
        return schema_option()

    def command_class(self) -> type[TyperCommand]:
        """Return the Typer command class owning ``--schema`` and ``--params-json``."""
        return schema_command_class(self.input_model, self.output_model, command=self)

    def execute(
        self,
        params: BaseModel,
        *,
        godot: Optional[str],
        project: Optional[Path] = None,
        make_runner: RunnerFactory = make_subprocess_runner,
    ) -> M | Failure:
        """Run the command and RETURN its typed success model or a ``Failure``.

        The outcome step: it resolves the binary, runs the operation, forwards
        engine diagnostics to stderr, and classifies the raw result — but it
        never emits the public result/error envelope or exits. (Forwarding the
        engine's stderr is its one side effect; the public emit and the process
        exit are deferred to :meth:`run`.) A failure is *returned* as a
        :class:`Failure`, so a caller composing a multi-phase recipe
        (``export run``) can branch on it. :meth:`run` adds the
        emit-and-exit-on-failure behavior on top.
        """
        if self.kind is ExecutionKind.LIVE:
            # A live op reaches the running daemon, not a fresh engine, so it
            # needs no Godot binary — the daemon owns the engine session
            # (ADR-0017). Skip resolution so `gda game tree` with no daemon
            # reports daemon_not_running, not a spurious binary_not_found.
            binary: Optional[Path] = None
        else:
            try:
                binary = resolve_godot_binary(godot)
            except ValueError as exc:
                # An empty ``--godot ""`` (a natural $GDA_GODOT mistake) makes
                # resolution raise *before* a runner exists — there is no binary to
                # launch, the same environment failure as a missing one. Map it to
                # the structured ``binary_not_found`` envelope so it never escapes as
                # a raw traceback (issue #33), mirroring the runner's NOT_FOUND path.
                return unresolvable_binary_failure(str(exc))
        # ``binary`` is ``None`` only on the LIVE branch above, where the injected
        # runner (`make_live_runner`) and classifier ignore it — a live op reaches
        # the daemon, not a fresh engine (ADR-0017); the headless path always passes
        # a resolved ``Path``. The RunnerFactory/Classifier seam is shared across
        # both kinds and can't express that per-kind invariant, so the two
        # None-for-live calls are suppressed (classify_run itself accepts None).
        runner = make_runner(binary, project)  # pyright: ignore[reportArgumentType]
        result = runner.run(self.operation, params.model_dump())

        if self.classify is not None:
            outcome = self.classify(result, binary)  # pyright: ignore[reportArgumentType]
        # No declared classifier: the channel picks it. LIVE gets ``classify_live``
        # — ``classify_run`` plus the LIVE error envelope (ADR-0017's reuse) — so a
        # live command declares its channel once, in ``kind``.
        elif self.kind is ExecutionKind.LIVE:
            outcome = classify_live(result, binary, self.output_model)
        else:
            outcome = classify_run(result, binary, self.output_model)

        # The child's stderr is teed AFTER classification, because on a failure it
        # rides the ``Failure`` to the emission point instead: whether printing it
        # here would repeat the bytes ``diagnostics`` is about to carry depends on
        # the caller's channel, which this method does not know (#798 review). A
        # success has no diagnostics to duplicate, so its tee stays immediate.
        if isinstance(outcome, Failure):
            outcome.child_stderr = result.stderr
            return outcome
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return outcome

    def run(
        self,
        params: BaseModel,
        *,
        godot: Optional[str],
        json_output: bool,
        project: Optional[Path] = None,
        make_runner: RunnerFactory = make_subprocess_runner,
    ) -> M:
        """Run the command and return its typed success model.

        Diagnostics are forwarded to stderr. Failures are emitted on the caller's
        channel — the structured envelope under ``--json``, else the rendered lines —
        and terminate via Typer's exit path. The outcome is produced by
        :meth:`execute`; this method adds the emit-and-exit-on-failure behavior
        shared by every CLI command.

        It therefore takes ``json_output`` for the same reason :meth:`emit` does:
        emitting is a PUBLIC-channel act, and since #685 there are two channels.
        A caller that wants the outcome rather than the emission calls
        :meth:`execute`, which chooses nothing and returns the ``Failure``.
        """
        outcome = self.execute(
            params, godot=godot, project=project, make_runner=make_runner
        )
        if isinstance(outcome, Failure):
            emit_failure(outcome, json_output=json_output)
        return outcome

    def emit(
        self,
        params: BaseModel,
        *,
        godot: Optional[str],
        project: Optional[Path] = None,
        json_output: bool,
        make_runner: RunnerFactory = make_subprocess_runner,
    ) -> None:
        """Run the command and emit either JSON or human-readable output.

        Human output is rendered by the command's own ``render`` (its descriptor's
        renderer, ADR-0023) — the descriptor is in hand here, so there is no
        type-keyed table to consult.
        """
        result = self.run(
            params,
            godot=godot,
            project=project,
            json_output=json_output,
            make_runner=make_runner,
        )
        emit_result(result, json_output, self.render)
