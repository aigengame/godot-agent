"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level
(ADR-0005). ``gda info`` is the first such command and the Phase-1 tracer
bullet: it runs the headless ``info`` operation and reports the engine version.
"""

import sys
from pathlib import Path
from typing import NoReturn, Optional

import typer
from pydantic import BaseModel

from gda.binary import resolve_godot_binary
from gda.errors import Failure, classify_info, classify_run
from gda.models import (
    CommandSchema,
    EngineVersion,
    GdaErrorEnvelope,
    InfoParams,
    SceneCreateParams,
    SceneCreateResult,
    SceneGetParams,
    SceneGetResult,
    SceneNode,
)
from gda.runner import GodotRunner, SubprocessGodotRunner

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)

# The first domain command group (ADR-0005): commands acting on scene files.
scene_app = typer.Typer(
    help="Act on Godot scene files (.tscn).", no_args_is_help=True
)
app.add_typer(scene_app, name="scene")


@app.callback()
def main() -> None:
    """An agent-facing Godot CLI with structured output."""
    # A no-op callback keeps gda a command *group* so meta commands like
    # `gda info` stay named subcommands (ADR-0005) rather than collapsing to
    # the top level, as Typer does for a single-command app.


def _make_runner(binary: Path) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return SubprocessGodotRunner(binary)


def _schema_option(
    input_model: type[BaseModel], output_model: type[BaseModel]
) -> bool:
    """A ``--schema`` flag wired to its own emission (ADR-0004, issue #18).

    Declaring the flag IS the implementation: an eager callback emits the
    command's model-derived ``{input, output}`` contract and exits before any
    other parameter — required arguments included — is validated, and before
    any engine path (binary resolution, runner) is touched. One declaration
    per command replaces the per-command ``if schema:`` block, so a command
    cannot ship the flag without its mandated behavior.
    """

    def emit(value: bool) -> None:
        if value:
            typer.echo(CommandSchema.of(input_model, output_model).model_dump_json())
            raise typer.Exit()

    return typer.Option(
        False,
        "--schema",
        help="Emit this command's input/output JSON Schemas; no Godot is spawned.",
        callback=emit,
        is_eager=True,
    )


def _fail(failure: Failure) -> NoReturn:
    """Emit a structured error to stdout and exit non-zero (issue #3).

    The error JSON is the stdout contract for the failure path (always emitted,
    independent of ``--json``); the process exit code distinguishes categories.
    ``NoReturn`` lets the type checker prove the caller's fallthrough narrows
    the classification to the success model.
    """
    typer.echo(GdaErrorEnvelope(error=failure.error).model_dump_json())
    raise typer.Exit(code=failure.exit_code)


@scene_app.command()
def create(
    path: str = typer.Argument(..., help="Target .tscn path to write."),
    root_type: str = typer.Option(
        ...,
        "--root-type",
        help="Godot node class of the new scene's root (e.g. Node2D).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    ),
    schema: bool = _schema_option(SceneCreateParams, SceneCreateResult),
    godot: Optional[str] = typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    ),
) -> None:
    """Create a new .tscn scene file with the given root node type."""
    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary)
    params = SceneCreateParams(path=path, root_type=root_type)
    result = runner.run("scene-create", params.model_dump())

    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    outcome = classify_run(result, binary, SceneCreateResult)
    if isinstance(outcome, Failure):
        _fail(outcome)
    created = outcome

    if json_output:
        typer.echo(created.model_dump_json())
    else:
        typer.echo(f"created {created.path} (root {created.root_type})")


def _render_tree(node: SceneNode, depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans."""
    lines = [f"{'  ' * depth}{node.name} ({node.type})"]
    lines += (_render_tree(child, depth + 1) for child in node.children)
    return "\n".join(lines)


@scene_app.command()
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    ),
    schema: bool = _schema_option(SceneGetParams, SceneGetResult),
    godot: Optional[str] = typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    ),
) -> None:
    """Read a scene file and report its structured node tree."""
    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary)
    params = SceneGetParams(path=path)
    result = runner.run("scene-get", params.model_dump())

    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    outcome = classify_run(result, binary, SceneGetResult)
    if isinstance(outcome, Failure):
        _fail(outcome)
    scene = outcome

    if json_output:
        typer.echo(scene.model_dump_json())
    else:
        typer.echo(_render_tree(scene.root))


@app.command()
def info(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    ),
    schema: bool = _schema_option(InfoParams, EngineVersion),
    godot: Optional[str] = typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    ),
) -> None:
    """Report the Godot engine version info."""
    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary)
    result = runner.run("info", {})

    # stdout carries only the result payload; engine/script diagnostics are
    # surfaced on stderr (ADR-0002).
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    outcome = classify_info(result, binary)
    if isinstance(outcome, Failure):
        _fail(outcome)
    version = outcome

    if json_output:
        typer.echo(version.model_dump_json())
    else:
        typer.echo(version.string)
