"""Headless command execution for ``gda``.

A headless command declares the small interface that varies per command:
operation name, input model, output model, and human rendering.
This module owns the shared implementation behind that interface: schema
emission, Godot binary resolution, runner construction, diagnostics forwarding,
classification, failure output, and JSON rendering.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, NoReturn, Optional, TypeVar

import typer
from pydantic import BaseModel, ValidationError
from typer.core import TyperCommand

from gda.core.failure.catalog import (
    Failure,
    conflicting_params_input_failure,
    invalid_params_json_failure,
    validation_error_message,
)
from gda.core.failure.child_stderr import forward_child_stderr
from gda.core.failure.classify import (
    classify_live,
    classify_run,
    resolve_godot_binary_or_failure,
)
from gda.core.engine.execution import ExecutionKind, live_stack_constraints
from gda.core.contract.envelope import GdaErrorEnvelope, LiveStackConstraints
from gda.core.contract.schema import CommandSchema
from gda.core.contract.render import render_failure
from gda.core.engine.launch import GodotRunner, RunResult
from gda.core.engine.sentinel import SubprocessGodotRunner
from gda.surface.bindings import command_argv_bindings
from gda.surface.options import _GLOBAL_OPTION_NAMES, json_in_effect, schema_option

M = TypeVar("M", bound=BaseModel)

Classifier = Callable[[RunResult, Path], M | Failure]
# A command's human renderer: its result model -> text. Carried on the descriptor
# (ADR-0023) so a command renders through its own registration, not a central
# type-keyed table.
Renderer = Callable[[M], str]
# A recipe command's CLI-side execution channel (ADR-0023): given the built params
# model and the CLI context, it PRODUCES the outcome (resolve + run), returning the
# result model or a Failure. Carried on the descriptor so a command with a recipe
# is fulfilled by it instead of the sentinel `execute`; emission stays the shared tail
# (the descriptor's `render`), so a recipe command renders identically to a
# sentinel one. ``export run`` / the ``daemon`` lifecycle / ``screen`` are recipes.
# Not parameterized over ``M``: the recipe's keyword-only context means an Ellipsis
# parameter spec (``Callable[..., …]``), which is not a subscriptable generic alias.
Recipe = Callable[..., "BaseModel | Failure"]
RunnerFactory = Callable[[Path, Optional[Path]], GodotRunner]


def make_subprocess_runner(
    binary: Path, project: Optional[Path] = None, *, ignore_cwd: bool = False
) -> GodotRunner:
    """Build the default real Godot runner for ``binary`` and ``project``.

    ``ignore_cwd`` makes a run without a project load none from the invoker's
    working directory either (#1035; see :class:`~gda.core.engine.sentinel.SubprocessGodotRunner`).
    """
    return SubprocessGodotRunner(binary, project=project, ignore_cwd=ignore_cwd)


def command_constraints(
    command: "Optional[HeadlessCommand]",
) -> Optional[LiveStackConstraints]:
    """Wrap a command's live-stack constraint into the model, or ``None``.

    The one place the leaf :func:`gda.core.engine.execution.live_stack_constraints`
    predicate's primitives are lifted into the :class:`LiveStackConstraints`
    model, shared by the per-command ``--schema`` path here and the aggregate
    manifest builder (``gda.surface.manifest``) so the two forms cannot drift (issue
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


# A hook registered by gda.surface.dispatch that runs a command from a params model
# built off ``--params-json``, through the same project-resolution + runner seam the
# argv path uses. Held as a hook so this module need not import the CLI layer
# (ADR-0015).
ParamsJsonDispatch = Callable[["HeadlessCommand", BaseModel, "typer.Context"], None]
_params_json_dispatch: Optional[ParamsJsonDispatch] = None


def register_params_json_dispatch(dispatch: ParamsJsonDispatch) -> None:
    """Register the CLI-layer dispatcher used by the ``--params-json`` path."""
    global _params_json_dispatch
    _params_json_dispatch = dispatch


def _from_command_line(ctx: typer.Context, name: str) -> bool:
    """True when ``name`` was supplied on the command line, not left at default.

    Compares the Click ``ParameterSource`` by member name so this module need
    not import Click (a transitive dependency through Typer).
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


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
        # (gda.surface.manifest) can reuse CommandSchema.of per command when it walks
        # the live Typer tree, instead of re-deriving the contract a second way
        # (ADR-0012). The closure above keeps them for `--schema`; these make the same
        # single source readable off the registered command object. ``gda_command``
        # carries the full HeadlessCommand so the ``--params-json`` path can dispatch
        # the operation (ADR-0015); None for the bare ``gda schema`` meta command, which
        # has no operation to run.
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
                    # params_or_bad_parameter uses
                    # (gda.core.failure.catalog.validation_error_message, #713 review
                    # round 3), so both input channels report the identical refusal for
                    # the identical violation — not str(exc)'s dump of the model class
                    # name, a [type=..., input_value=..., input_type=...] tag per error,
                    # and a pydantic.dev URL, which used to echo the caller's OTHER
                    # field values (e.g. a large --content payload) back into the
                    # structured envelope's message.
                    emit_failure(
                        invalid_params_json_failure(validation_error_message(exc)),
                        json_output=json_in_effect(ctx),
                    )
                if _params_json_dispatch is None:  # pragma: no cover - misconfig
                    raise RuntimeError(
                        "no --params-json dispatcher registered; "
                        "gda.surface.dispatch must call register_params_json_dispatch()"
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
    human lines of :func:`gda.core.contract.render.render_failure`. Either way it
    selects the process exit code, which is the same on both channels. Shared by the
    sentinel-pipeline and recipe commands (via the CLI dispatch entry), the
    native-export command (``export run``), and the near-miss refusal
    (``gda.surface.hints``).

    ``json_output`` is REQUIRED and keyword-only: until #685 this function had no
    channel to choose, so every call site emitted JSON whether or not the caller had
    asked for it, and a human read a labelled ``script run --strict`` capture as one
    escaped line. Making it explicit is what keeps that from silently returning: a new
    call site cannot default its way back into the wrong channel. Where the caller holds
    a click context rather than the flag, :func:`~gda.surface.options.json_in_effect`
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
    contract carried it (:class:`gda.core.contract.envelope.FailureEvidence`).

    The child run's stderr (``failure.child_stderr``) is forwarded to this
    process's stderr here, where the channel is known — except when the human
    channel is about to print the very same bytes as ``diagnostics``, which would
    say one stream twice across two streams (#798 review). Byte identity decides,
    not the error code: a curated or capped ``diagnostics`` (the labeled
    ``--strict`` sections, a timeout's tail-capped captures) differs from the raw
    stream, so its tee — the only copy that is complete — survives. Under
    ``--json`` the tee is unconditional, keeping that channel's bytes exactly as
    they were.

    That is this function's whole part in the child-stderr rule. The rule itself —
    the success half, the producer roster, and the ``gda script run`` exception —
    is recorded once, in ADR-0002's #803 outcome note; the producers state their
    own halves locally and reference it (#806 review).
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
    the sentinel-pipeline commands and the recipe commands (``export run``, the
    ``daemon`` lifecycle, ``screen``) through the dispatch entry's one tail, which
    passes the descriptor's renderer so every command renders success identically.

    ``render`` is always present: it is a required descriptor field (ADR-0023), and
    the dispatch entry passes ``cmd.render`` for both arms.
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
    # to produce the outcome instead of the sentinel ``execute``. ``None`` (the default)
    # means the command runs through ``execute`` with its ``kind``-selected runner — so a
    # single ``recipe is None`` test selects the channel, no identity table.
    recipe: "Recipe | None" = None
    # Whether the command INHERITS a project context ($GDA_PROJECT, then the cwd)
    # when no explicit ``--project`` is given. This field decides inheritance and
    # NOTHING else. A meta command (ADR-0005/0024 — ``skill``, ``version``,
    # ``help``, ``info``) sets it ``False``: it is about ``gda`` or the engine
    # itself, so an inherited value that is not a project must not break the
    # commands an agent reaches for FIRST when something is wrong (#353/#357).
    # Two DOMAIN commands set it ``False`` too. ``export smoke`` (ADR-0042): its
    # operand is a caller-selected artifact path that gda has no fact tying to any
    # project. ``project create`` (#1027): its destination is an operation input;
    # the project it makes does not exist yet. Neither has a project to inherit —
    # which is why this field is not a synonym for "meta command".
    # Whether a command ACCEPTS an explicit ``--project`` is its CLI signature's
    # decision, not this field's: ``gda info`` declares the option for uniform
    # orchestration argv and has it validated like anywhere else (#670), while
    # ``skill``/``version``/``help`` declare none, so a passed ``--project`` is
    # the usual unknown-option refusal there. Project-using commands leave this
    # ``True`` and receive the fully resolved project (or a structured
    # ``project_not_found``). Read only by ``gda.surface.dispatch._project_context``,
    # which the one dispatch entry calls, so it applies to the sentinel channel
    # as much as to a recipe. On the sentinel channel the engine inherits nothing
    # either: a ``False`` command given no ``--project`` runs the engine where it
    # can load no project, whatever the invoker's working directory holds (#1035).
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

        The outcome step: it resolves the binary, runs the operation, forwards engine
        diagnostics to stderr, and classifies the raw result — but it never emits the
        public result/error envelope or exits. (Forwarding the engine's stderr is its
        one side effect; the public emit and the process exit are the dispatch entry's
        shared tail, ``gda.surface.dispatch``.) A failure is *returned* as a
        :class:`Failure`, so a caller composing a multi-phase recipe (``export run``)
        can branch on it.
        """
        if self.kind is ExecutionKind.LIVE:
            # A live op reaches the running daemon, not a fresh engine, so it
            # needs no Godot binary — the daemon owns the engine session
            # (ADR-0017). Skip resolution so `gda game tree` with no daemon
            # reports daemon_not_running, not a spurious binary_not_found.
            binary: Optional[Path] = None
        else:
            # Resolution runs *before* a runner exists. An empty ``--godot ""``
            # cannot be resolved, and the shared step returns the structured
            # ``binary_not_found`` failure for it, so it never escapes as a raw
            # traceback (issue #33), mirroring the runner's NOT_FOUND path.
            resolved = resolve_godot_binary_or_failure(godot)
            if isinstance(resolved, Failure):
                return resolved
            binary = resolved
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

        # The child's stderr is forwarded AFTER classification, because on a
        # failure it rides the ``Failure`` to the emission point instead.
        return forward_child_stderr(result, outcome)
