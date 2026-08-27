"""The CLI-layer dispatch tails and runner seams.

This module owns the dispatch tails (``_emit`` / ``dispatch_domain`` /
``dispatch_meta`` / ``dispatch_recipe`` / ``_run_params_json``), the argv
params-building rule (``params_or_bad_parameter``) and the runner seams
(``make_runner`` / ``make_export_runner`` / ``make_live_runner``)
shared by every command module. The descriptor machinery itself stays in
``gda.headless``, which holds no CLI import (ADR-0015); this module sits between
the two — below the command modules that call the tails, above ``headless``.
Extracted from ``gda.cli`` per ADR-0040.
"""

from pathlib import Path
from typing import Any, Optional, TypeVar

import typer
from pydantic import BaseModel, ValidationError

from gda.errors import (
    Failure,
    invalid_project_failure,
)
from gda.execution import ExecutionKind
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.headless import (
    HeadlessCommand,
    M,
    emit_failure,
    emit_result,
    make_subprocess_runner,
    register_params_json_dispatch,
)
from gda.live_runner import make_daemon_runner
from gda.project import resolve_project_dir
from gda.runner import GodotRunner

P = TypeVar("P", bound=BaseModel)


def params_or_bad_parameter(model_cls: type[P], /, **kwargs: Any) -> P:
    """Build a command's params model from argv, or raise the Click usage error.

    The one rule for the argv path: a model-construction failure is a CLI usage
    error. The model is the single source of truth for a request's shape
    (ADR-0015), so the argv body builds it and translates its ``ValueError`` /
    ``ValidationError`` into ``typer.BadParameter`` (exit 2), keeping the argv
    usage-error ergonomics — while ``--params-json``, which builds the SAME model
    in the command class, surfaces the same rule as a structured
    ``invalid_params``. Stated here once so no argv body restates it.

    A raw ``ValueError``'s ``str()`` is already the plain sentence a validator
    wrote, so it passes through as-is. A pydantic ``ValidationError`` is
    rendered through :func:`_validation_message` instead of its own ``str()`` —
    which dumps the model's class name, a ``[type=..., input_value=...,
    input_type=...]`` tag PER ERROR, and a pydantic.dev URL, and can echo back
    an arbitrary caller value (including a large or sensitive one) inside
    ``input_value=`` (#713 review).
    """
    try:
        return model_cls(**kwargs)
    except ValidationError as exc:
        raise typer.BadParameter(_validation_message(exc)) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _validation_message(exc: ValidationError) -> str:
    """Render a ``ValidationError`` as the sentence(s) its checks actually wrote.

    Reads each error's own ``msg`` — already the clean, human-readable text for
    a built-in pydantic check (a type mismatch, a missing field, an out-of-range
    value) — rather than ``str(exc)``, which additionally dumps the model class
    name and a ``[type=..., input_value=..., input_type=...]`` tag per error
    (the defect: ``input_value`` echoes the caller's raw field value, which can
    be large or sensitive, e.g. a ``script set --content`` payload).

    For a model or field validator's raised ``ValueError`` (pydantic's
    ``"value_error"`` type, e.g. :func:`~gda.commands.script.resolve_set_mode`),
    ``msg`` is pydantic's OWN ``"Value error, "``-prefixed rendering of it; this
    reads the original exception back out of ``ctx['error']`` instead, so the
    message is exactly the sentence the validator wrote, unprefixed.

    Each message is tagged with its field path (``loc``, dotted) when the error
    is field-scoped; a model-level validator's error (``loc == ()``, e.g.
    ``resolve_set_mode``'s mode-selection rule, which has no single field to
    name) carries no tag. Multiple errors join on ``"; "`` — a command usually
    raises exactly one, but pydantic can report several at once (e.g. two
    independently-invalid fields), and nothing here assumes otherwise.
    """
    parts: list[str] = []
    for err in exc.errors():
        ctx = err.get("ctx")
        if err["type"] == "value_error" and isinstance(ctx, dict) and "error" in ctx:
            message = str(ctx["error"])
        else:
            message = err["msg"]
        loc = err.get("loc") or ()
        if loc:
            field = ".".join(str(part) for part in loc)
            parts.append(f"{field}: {message}")
        else:
            parts.append(message)
    return "; ".join(parts)


def make_runner(binary: Path, project: Optional[Path]) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary`` and ``project``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return make_subprocess_runner(binary, project)


def make_export_runner(binary: Path, project: Optional[Path]) -> ExportRunner:
    """Build the default (real) native-export runner for ``binary`` and ``project``.

    The ``export run``-only twin of :func:`make_runner`: a seam tests override
    to inject a fake export runner, since ``export run`` spawns Godot with native
    ``--export-<mode>`` flags rather than the ``operations.gd`` payload.
    """
    return make_subprocess_export_runner(binary, project)


def make_live_runner(binary: Optional[Path], project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner — the per-project gda-daemon IPC client (ADR-0017).

    The ``kind = LIVE`` twin of :func:`make_runner`, a seam tests override to
    inject a fake daemon runner. ``binary`` is unused: a live op reaches the
    running daemon, not a fresh engine, so the daemon (not the CLI) owns the
    engine session.
    """
    return make_daemon_runner(project)


def _emit(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[Path],
) -> None:
    """Drive ``cmd.emit`` with the shared CLI execution tail.

    Selects the runner seam by the command's execution channel ``kind`` (ADR-0017):
    a ``LIVE`` command goes through :func:`make_live_runner` (the daemon IPC
    client), every other through :func:`make_runner`. Both seams are referenced
    here at call time, so a test monkeypatch on ``gda.dispatch.make_runner`` /
    ``gda.dispatch.make_live_runner`` still binds. Both the domain dispatch
    (:func:`dispatch_domain`) and the meta dispatch (:func:`dispatch_meta`) funnel
    through here; they differ only in how ``project`` is obtained.
    """
    runner_factory = make_live_runner if cmd.kind is ExecutionKind.LIVE else make_runner
    cmd.emit(
        params,
        godot=godot,
        project=project,
        json_output=json_output,
        make_runner=runner_factory,
    )


def _resolve_project_or_fail(project: Optional[str]) -> Optional[Path]:
    """Resolve ``--project`` (ADR-0006), or emit a structured ``project_not_found``
    and exit — never leak the raise as a traceback (#353).

    ``resolve_project_dir`` raises ``ValueError`` for an explicit ``--project`` or
    ``$GDA_PROJECT`` that is empty or is not a Godot project. This is the ONE shared
    project-resolution point on the CLI dispatch path, so converting the raise here
    gives every channel — sentinel (:func:`dispatch_domain`) and recipe
    (:func:`dispatch_recipe`) — the structured envelope in a single place.
    """
    try:
        return resolve_project_dir(project)
    except ValueError as exc:
        emit_failure(invalid_project_failure(str(exc)))


def _project_context(cmd: HeadlessCommand[M], project: Optional[str]) -> Optional[Path]:
    """The project ``cmd`` runs against, resolved once per dispatch (ADR-0006).

    One rule, shared by all three tails. A command with ``inherits_project=False``
    (a meta command) never INHERITS a project context ($GDA_PROJECT, then the cwd):
    it is about ``gda`` or the engine itself, so an inherited invalid
    ``$GDA_PROJECT`` must not make it fail (#357). It still VALIDATES an EXPLICIT
    ``--project`` when it takes one and one is given (``gda info --project``, #670)
    — naming a project is a deliberate choice, so a bad one is a structured refusal
    rather than something quietly ignored.
    """
    if not cmd.inherits_project and project is None:
        return None
    return _resolve_project_or_fail(project)


def dispatch_domain(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[str],
) -> None:
    """Run a domain command through the shared CLI execution tail.

    Owns the per-command-repeated wiring: project resolution
    (``resolve_project_dir``, kept at the CLI layer per ADR-0006), the runner
    seam, the ``json_output`` pass-through, and the JSON-vs-text branch. Each
    command keeps its own Typer signature, params construction, and
    pre-dispatch validation; only this execution tail is shared. Human
    rendering is done by the command's own renderer (``cmd.render``, ADR-0023)
    inside ``cmd.emit``, so no renderer is threaded here.
    """
    _emit(
        cmd,
        params,
        json_output=json_output,
        godot=godot,
        project=_project_context(cmd, project),
    )


def dispatch_meta(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[str] = None,
) -> None:
    """Run a meta command (ADR-0005) through the shared tail.

    A meta command is about ``gda``/the engine itself, so it acquires no project
    context of its own — the difference from :func:`dispatch_domain` is that
    ``project`` here is the EXPLICIT flag only, never the ``$GDA_PROJECT``/cwd
    fallback (:func:`_project_context`). ``gda info`` takes one so an orchestrator can
    pass the same argv to every command (#670); it is validated like anywhere else.
    """
    _emit(
        cmd,
        params,
        json_output=json_output,
        godot=godot,
        project=_project_context(cmd, project),
    )


def dispatch_recipe(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[str],
) -> None:
    """Run a recipe command through its descriptor's ``recipe``, then emit (ADR-0023).

    A recipe command (``export run`` / the ``daemon`` lifecycle / ``screen``) is
    fulfilled by a CLI-side recipe that PRODUCES the outcome, not the sentinel
    ``cmd.emit``. Emission is the SAME shared tail every command uses —
    :func:`emit_result` with the command's own ``cmd.render`` — so a recipe command
    renders identically to a sentinel one; only outcome production differs. Shared by
    the argv bodies and the ``--params-json`` path, so the two forms are
    indistinguishable downstream (ADR-0015). Project resolution stays CLI-side
    (ADR-0006) and happens HERE, once, for every PROJECT-USING recipe — so an
    invalid ``--project`` yields the structured ``project_not_found`` envelope on
    this channel exactly as on the sentinel one, and no recipe re-resolves (#353).
    A non-inheriting recipe (a pure meta emitter like ``gda skill``, ADR-0024) is
    NOT resolved: it takes no project, so an inherited invalid ``$GDA_PROJECT``
    must not make it fail (#357).
    """
    # A recipe command always carries a recipe channel — that is what routes it
    # here rather than to the sentinel ``cmd.emit`` path (ADR-0023). A project-using
    # recipe receives the ALREADY-resolved project (or a structured project_not_found
    # is emitted before it runs); a non-inheriting meta recipe receives None and
    # never touches ``resolve_project_dir``.
    assert cmd.recipe is not None
    outcome = cmd.recipe(params, project=_project_context(cmd, project), godot=godot)
    if isinstance(outcome, Failure):
        emit_failure(outcome)
    emit_result(outcome, json_output, cmd.render)


def _run_params_json(
    cmd: HeadlessCommand[M], params: BaseModel, ctx: typer.Context
) -> None:
    """Dispatch a ``--params-json`` invocation through the shared CLI tail (ADR-0015).

    Registered with :func:`gda.headless.register_params_json_dispatch`. The model
    is already built from the JSON object by the command class; this only routes
    it through the *same* project resolution + runner seam the argv path uses, so
    the two input paths are indistinguishable downstream. The global
    ``--json`` / ``--godot`` / ``--project`` options parsed alongside
    ``--params-json`` are honored; a non-inheriting (meta) command dispatches
    through :func:`dispatch_meta`, which validates an explicit ``--project`` but
    inherits none.
    """
    options = ctx.params
    json_output = bool(options.get("json_output", False))
    godot = options.get("godot")
    if cmd.recipe is not None:
        # A recipe command (export run / daemon lifecycle / screen) is fulfilled by
        # its descriptor's recipe, not the sentinel cmd.emit — ONE descriptor-driven
        # branch, no kind/identity selection (ADR-0023). The recipe reads everything
        # from the built params model (windowed/output/…), so --params-json drives the
        # SAME path as the argv body.
        dispatch_recipe(
            cmd,
            params,
            json_output=json_output,
            godot=godot,
            project=options.get("project"),
        )
        return
    # Read off the DESCRIPTOR (ADR-0023), not off whether a `project` key happens to be
    # in `ctx.params`: since `gda info` takes an explicit `--project` (#670), the
    # PRESENCE of the option no longer tells a meta command from a domain one — what a
    # command may INHERIT does, which is what `inherits_project` records.
    if not cmd.inherits_project:
        dispatch_meta(
            cmd,
            params,
            json_output=json_output,
            godot=godot,
            project=options.get("project"),
        )
    else:
        dispatch_domain(
            cmd,
            params,
            json_output=json_output,
            godot=godot,
            project=options.get("project"),
        )


register_params_json_dispatch(_run_params_json)
