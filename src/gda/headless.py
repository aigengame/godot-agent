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

from gda.binary import resolve_godot_binary
from gda.errors import (
    Failure,
    classify_live,
    classify_run,
    conflicting_params_input_failure,
    invalid_params_json_failure,
    unresolvable_binary_failure,
)
from gda.execution import ExecutionKind, live_stack_constraints
from gda.models import CommandSchema, GdaErrorEnvelope, LiveStackConstraints
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


def json_option() -> bool:
    return typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    )


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
                typer.echo(
                    CommandSchema.of(
                        input_model,
                        output_model,
                        kind=kind,
                        constraints=constraints,
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
                    emit_failure(conflicting_params_input_failure())
                raw = ctx.params["params_json"]
                # ``-`` reads the object from stdin so large payloads avoid OS
                # argv length limits and process-listing leakage (ADR-0015).
                text = sys.stdin.read() if raw == "-" else raw
                try:
                    model = command.input_model.model_validate_json(text)
                except ValidationError as exc:
                    emit_failure(invalid_params_json_failure(str(exc)))
                if _params_json_dispatch is None:  # pragma: no cover - misconfig
                    raise RuntimeError(
                        "no --params-json dispatcher registered; gda.cli must call "
                        "register_params_json_dispatch()"
                    )
                _params_json_dispatch(command, model, ctx)
                return None
            return super().invoke(ctx)

    return _SchemaCommand


def emit_failure(failure: Failure) -> NoReturn:
    """Emit a structured error envelope to stdout and exit non-zero.

    The single home for the public failure channel (ADR-0002): a ``Failure``
    becomes the ``{"error": {...}}`` envelope on stdout and selects the process
    exit code. Shared by the sentinel-pipeline commands (via :meth:`HeadlessCommand.run`)
    and the native-export command (``export run``), which classifies its own
    subprocess outcome but emits failures through this same channel.
    """
    typer.echo(GdaErrorEnvelope(error=failure.error).model_dump_json())
    raise typer.Exit(code=failure.exit_code)


# Backwards-compatible private alias for in-module call sites.
_fail = emit_failure


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
    # A projectless recipe is a pure meta emitter (ADR-0024/0005, e.g. ``gda skill``):
    # it takes no ``--project`` and resolves none, so the recipe dispatcher must NOT
    # resolve a project for it — otherwise an inherited ``$GDA_PROJECT`` that is not a
    # project would make a projectless meta command fail (#353/#357). Project-using
    # recipes leave this ``False`` and receive a resolved project (or a structured
    # ``project_not_found``). Meaningless for the sentinel channel (``recipe is None``).
    projectless: bool = False

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
        # runner (`_make_live_runner`) and classifier ignore it — a live op reaches
        # the daemon, not a fresh engine (ADR-0017); the headless path always passes
        # a resolved ``Path``. The RunnerFactory/Classifier seam is shared across
        # both kinds and can't express that per-kind invariant, so the two
        # None-for-live calls are suppressed (classify_run itself accepts None).
        runner = make_runner(binary, project)  # pyright: ignore[reportArgumentType]
        result = runner.run(self.operation, params.model_dump())

        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)

        if self.classify is not None:
            return self.classify(result, binary)  # pyright: ignore[reportArgumentType]
        # No declared classifier: the channel picks it. LIVE gets ``classify_live``
        # — ``classify_run`` plus the LIVE error envelope (ADR-0017's reuse) — so a
        # live command declares its channel once, in ``kind``.
        if self.kind is ExecutionKind.LIVE:
            return classify_live(result, binary, self.output_model)
        return classify_run(result, binary, self.output_model)

    def run(
        self,
        params: BaseModel,
        *,
        godot: Optional[str],
        project: Optional[Path] = None,
        make_runner: RunnerFactory = make_subprocess_runner,
    ) -> M:
        """Run the command and return its typed success model.

        Diagnostics are forwarded to stderr. Failures are emitted as the public
        structured error envelope and terminate via Typer's exit path. The
        outcome is produced by :meth:`execute`; this method adds the
        emit-and-exit-on-failure behavior shared by every CLI command.
        """
        outcome = self.execute(
            params, godot=godot, project=project, make_runner=make_runner
        )
        if isinstance(outcome, Failure):
            _fail(outcome)
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
        result = self.run(params, godot=godot, project=project, make_runner=make_runner)
        emit_result(result, json_output, self.render)
