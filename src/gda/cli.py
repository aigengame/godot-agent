"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level;
domain commands are grouped under their Godot domain object (ADR-0005).
``gda info`` is the Phase-1 tracer bullet; the ``scene`` group is the first
domain group (issue #18). Every command drives the same headless pipeline:
binary resolution → runner → sentinel parse → typed model → JSON.
"""

import sys
from pathlib import Path
from typing import Callable, NoReturn, Optional, TypeVar

import typer
from pydantic import BaseModel

from gda.binary import resolve_godot_binary
from gda.errors import Failure, classify_info, classify_run
from gda.project import resolve_project_dir
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
from gda.runner import GodotRunner, RunResult, SubprocessGodotRunner

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


def _make_runner(binary: Path, project: Optional[Path]) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary`` and ``project``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return SubprocessGodotRunner(binary, project=project)


def _json_option() -> bool:
    return typer.Option(
        False, "--json", help="Emit the result as a single JSON object."
    )


def _godot_option() -> Optional[str]:
    return typer.Option(
        None,
        "--godot",
        help="Path to the Godot binary (overrides $GDA_GODOT and the default).",
    )


def _project_option() -> Optional[str]:
    return typer.Option(
        None,
        "--project",
        help="Godot project directory for res:// resolution "
        "(overrides $GDA_PROJECT; defaults to the current directory if it is a project).",
    )


def _normalize_path(path: str) -> str:
    """Normalize a path argument at the CLI layer (issue #32).

    Engine-resolved virtual paths (``res://``, ``user://``, ``uid://``) pass
    through untouched — the engine resolves them against the project. A
    filesystem path gets ``~`` expanded so a literal ``~`` works without a shell.
    """
    if "://" in path:
        return path
    return str(Path(path).expanduser())


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


M = TypeVar("M", bound=BaseModel)


def _run_classified(
    operation: str,
    params: BaseModel,
    classify: Callable[[RunResult, Path], M | Failure],
    godot: Optional[str],
    project: Optional[Path] = None,
) -> M:
    """Drive the shared headless pipeline to a typed success model.

    Resolve the binary, run ``operation`` with the typed params against the
    resolved ``project`` (``None`` runs projectless), surface engine/script
    diagnostics on stderr (ADR-0002), classify the raw result, and on failure
    emit the structured error and exit — so each command body is reduced to its
    params, its classifier, and its output rendering.
    """
    binary = resolve_godot_binary(godot)
    runner = _make_runner(binary, project)
    result = runner.run(operation, params.model_dump())

    # stdout carries only the result payload; engine/script diagnostics are
    # surfaced on stderr (ADR-0002).
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    outcome = classify(result, binary)
    if isinstance(outcome, Failure):
        _fail(outcome)
    return outcome


def _render_tree(node: SceneNode, depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans."""
    lines = [f"{'  ' * depth}{node.name} ({node.type})"]
    lines += (_render_tree(child, depth + 1) for child in node.children)
    return "\n".join(lines)


@scene_app.command()
def create(
    path: str = typer.Argument(..., help="Target .tscn path to write."),
    root_type: str = typer.Option(
        ...,
        "--root-type",
        help="Godot node class of the new scene's root (e.g. Node2D).",
    ),
    json_output: bool = _json_option(),
    schema: bool = _schema_option(SceneCreateParams, SceneCreateResult),
    godot: Optional[str] = _godot_option(),
    project: Optional[str] = _project_option(),
) -> None:
    """Create a new .tscn scene file with the given root node type."""
    created = _run_classified(
        "scene-create",
        SceneCreateParams(path=_normalize_path(path), root_type=root_type),
        lambda result, binary: classify_run(result, binary, SceneCreateResult),
        godot,
        resolve_project_dir(project),
    )

    if json_output:
        typer.echo(created.model_dump_json())
    else:
        typer.echo(f"created {created.path} (root {created.root_type})")


@scene_app.command()
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = _json_option(),
    schema: bool = _schema_option(SceneGetParams, SceneGetResult),
    godot: Optional[str] = _godot_option(),
    project: Optional[str] = _project_option(),
) -> None:
    """Read a scene file and report its structured node tree."""
    scene = _run_classified(
        "scene-get",
        SceneGetParams(path=_normalize_path(path)),
        lambda result, binary: classify_run(result, binary, SceneGetResult),
        godot,
        resolve_project_dir(project),
    )

    if json_output:
        typer.echo(scene.model_dump_json())
    else:
        typer.echo(_render_tree(scene.root))


@app.command()
def info(
    json_output: bool = _json_option(),
    schema: bool = _schema_option(InfoParams, EngineVersion),
    godot: Optional[str] = _godot_option(),
) -> None:
    """Report the Godot engine version info."""
    version = _run_classified("info", InfoParams(), classify_info, godot)

    if json_output:
        typer.echo(version.model_dump_json())
    else:
        typer.echo(version.string)
