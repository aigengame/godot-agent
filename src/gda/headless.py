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
from typing import Generic, NoReturn, Optional, TypeVar

import typer
from pydantic import BaseModel
from typer.core import TyperCommand

from gda.binary import resolve_godot_binary
from gda.errors import Failure, classify_run
from gda.models import CommandSchema, GdaErrorEnvelope
from gda.runner import GodotRunner, RunResult, SubprocessGodotRunner

M = TypeVar("M", bound=BaseModel)

Classifier = Callable[[RunResult, Path], M | Failure]
RunnerFactory = Callable[[Path, Optional[Path]], GodotRunner]
HumanRenderer = Callable[[M], str]


def make_subprocess_runner(binary: Path, project: Optional[Path] = None) -> GodotRunner:
    """Build the default real Godot runner for ``binary`` and ``project``."""
    return SubprocessGodotRunner(binary, project=project)


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
        help="Emit this command's input/output JSON Schemas; no Godot is spawned.",
    )


def schema_command_class(
    input_model: type[BaseModel], output_model: type[BaseModel]
) -> type[TyperCommand]:
    """A Typer command that owns ``--schema`` handling (ADR-0004).

    ``--schema`` is an introspection probe: it emits the command's
    ``{input, output}`` contract without spawning Godot and without requiring the
    command's operational arguments. It must still surface a structurally invalid
    command line — unknown options or extra positional args — as a usage error,
    and must always yield to ``--help`` (issue #36).
    """

    class _SchemaCommand(TyperCommand):
        def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
            if "--schema" not in args:
                return super().parse_args(ctx, args)

            # Relax required args so a bare ``--schema`` probe succeeds, while
            # Click still rejects unknown options / extra positional args and an
            # eager ``--help`` still wins. Restore afterwards: Typer reuses the
            # command object across invocations.
            relaxed = [(param, param.required) for param in self.params]
            try:
                for param, _ in relaxed:
                    param.required = False
                super().parse_args(ctx, list(args))
            finally:
                for param, required in relaxed:
                    param.required = required

            typer.echo(CommandSchema.of(input_model, output_model).model_dump_json())
            raise typer.Exit()

    return _SchemaCommand


def _fail(failure: Failure) -> NoReturn:
    """Emit a structured error to stdout and exit non-zero."""
    typer.echo(GdaErrorEnvelope(error=failure.error).model_dump_json())
    raise typer.Exit(code=failure.exit_code)


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
    classify: Classifier[M] | None = None

    def schema_option(self) -> bool:
        """Return the Typer ``--schema`` flag for this command."""
        return schema_option()

    def command_class(self) -> type[TyperCommand]:
        """Return the Typer command class that owns this command's ``--schema``."""
        return schema_command_class(self.input_model, self.output_model)

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
        structured error envelope and terminate via Typer's exit path.
        """
        binary = resolve_godot_binary(godot)
        runner = make_runner(binary, project)
        result = runner.run(self.operation, params.model_dump())

        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)

        outcome = (
            self.classify(result, binary)
            if self.classify is not None
            else classify_run(result, binary, self.output_model)
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
        render_text: HumanRenderer[M],
        make_runner: RunnerFactory = make_subprocess_runner,
    ) -> None:
        """Run the command and emit either JSON or human-readable output."""
        result = self.run(
            params, godot=godot, project=project, make_runner=make_runner
        )
        if json_output:
            typer.echo(result.model_dump_json())
        else:
            typer.echo(render_text(result))
