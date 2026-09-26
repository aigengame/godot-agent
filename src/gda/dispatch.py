"""The CLI-layer dispatch entry and runner seams.

This module owns the one dispatch entry (``dispatch_command``) with its
``cmd.emit`` tail (``_emit``) and its ``--params-json`` hook
(``_run_params_json``), the argv params-building rule
(``params_or_bad_parameter``) and the runner seams
(``make_runner`` / ``make_export_runner`` / ``make_live_runner``)
shared by every command module. The descriptor machinery itself stays in
``gda.headless``, which holds no CLI import (ADR-0015); this module sits between
the two — below the command modules that call the entry, above ``headless``.
Extracted from ``gda.cli`` per ADR-0040.
"""

from pathlib import Path
from typing import Any, Optional, TypeVar

import typer
from pydantic import BaseModel, ValidationError

from gda.errors import (
    Failure,
    classify_live,
    invalid_project_failure,
    validation_error_message,
)
from gda.execution import ExecutionKind
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.headless import (
    HeadlessCommand,
    M,
    emit_failure,
    emit_result,
    forward_child_stderr,
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

    A custom ``BaseModel.__init__`` can raise a raw ``ValueError`` before
    pydantic's validation machinery wraps it; its ``str()`` is already the plain
    refusal sentence, so it passes through as-is. Field/model validators and
    ``model_post_init`` instead arrive as a pydantic ``ValidationError``, rendered
    through :func:`~gda.errors.validation_error_message` instead of its own
    ``str()`` — which dumps the model's class name, a ``[type=...,
    input_value=..., input_type=...]`` tag PER ERROR, and a pydantic.dev URL, and
    can echo back an arbitrary caller value (including a large or sensitive one)
    inside ``input_value=`` (#713 review). That renderer is shared with
    ``--params-json``'s OWN model-construction failure (:mod:`gda.headless`), so
    the two input channels report the identical sentence for the identical
    refusal (#713 review, round 3) — not just the same error class.
    """
    try:
        return model_cls(**kwargs)
    except ValidationError as exc:
        raise typer.BadParameter(validation_error_message(exc)) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


def run_live_exchange(
    operation: str,
    wire_params: dict[str, Any],
    reply_model: type[M],
    *,
    project: Optional[Path],
) -> M | Failure:
    """Send ONE live request to the daemon and return its classified reply.

    The live exchange of a recipe that builds its own request (#1013). The
    ``screen`` and ``perf monitors`` recipes send wire params that are not their
    descriptor's ``params.model_dump()``, classify against an intermediate reply
    model, and (``perf monitors --frames``) name a wire op that is not the
    descriptor's, so they cannot run through
    :meth:`~gda.headless.HeadlessCommand.execute`. The exchange gives them the
    same pipeline: the :func:`make_live_runner` seam, referenced here at call
    time so a test monkeypatch on ``gda.dispatch.make_live_runner`` still binds;
    :func:`~gda.errors.classify_live` against ``reply_model``; and
    :func:`~gda.headless.forward_child_stderr`, the one implementation of
    ADR-0002's #803 rule that ``execute`` also calls.

    A request/reply correlation check stays with the recipe, which alone knows the
    request; its refusal is :func:`~gda.errors.reply_correlation_failure`.
    """
    result = make_live_runner(None, project).run(operation, wire_params)
    return forward_child_stderr(result, classify_live(result, None, reply_model))


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
    ``gda.dispatch.make_live_runner`` still binds. The ``cmd.emit`` arm of
    :func:`dispatch_command` (every command without a ``recipe``) funnels through
    here.
    """
    runner_factory = make_live_runner if cmd.kind is ExecutionKind.LIVE else make_runner
    cmd.emit(
        params,
        godot=godot,
        project=project,
        json_output=json_output,
        make_runner=runner_factory,
    )


def _resolve_project_or_fail(
    project: Optional[str], *, json_output: bool
) -> Optional[Path]:
    """Resolve ``--project`` (ADR-0006), or emit a structured ``project_not_found``
    and exit — never leak the raise as a traceback (#353).

    ``resolve_project_dir`` raises ``ValueError`` for an explicit ``--project`` or
    ``$GDA_PROJECT`` that is empty or is not a Godot project. This is the ONE shared
    project-resolution point on the CLI dispatch path, so converting the raise here
    gives both arms of :func:`dispatch_command` — ``cmd.emit`` and recipe — the
    structured envelope in a single place.

    ``json_output`` is the caller's channel, carried down from the dispatch entry that
    already holds it (#685): this refusal happens BEFORE any command runs, so there is
    nothing else here to read it off.
    """
    try:
        return resolve_project_dir(project)
    except ValueError as exc:
        emit_failure(invalid_project_failure(str(exc)), json_output=json_output)


def _project_context(
    cmd: HeadlessCommand[M], project: Optional[str], *, json_output: bool
) -> Optional[Path]:
    """The project ``cmd`` runs against, resolved once per dispatch (ADR-0006).

    One rule, shared by both dispatch arms. A command with ``inherits_project=False``
    (a meta command, or ``export smoke``, which acts on a caller-selected path)
    never INHERITS a project context ($GDA_PROJECT, then the cwd): it is about
    ``gda`` or the engine itself, or about an operand gda cannot tie to a project,
    so an inherited invalid ``$GDA_PROJECT`` must not make it fail (#357,
    ADR-0042). It still VALIDATES an EXPLICIT
    ``--project`` when it takes one and one is given (``gda info --project``, #670)
    — naming a project is a deliberate choice, so a bad one is a structured refusal
    rather than something quietly ignored.
    """
    if not cmd.inherits_project and project is None:
        return None
    return _resolve_project_or_fail(project, json_output=json_output)


def dispatch_command(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
    project: Optional[str],
) -> None:
    """Run one command through the shared CLI tail — the one dispatch entry.

    Every argv body and the ``--params-json`` path call this, so the channel is
    read off the descriptor in ONE place (ADR-0023) and the two input forms are
    indistinguishable downstream (ADR-0015). Each command keeps its own Typer
    signature, params construction, and pre-dispatch validation; only this tail is
    shared.

    Project resolution stays CLI-side (ADR-0006) and happens HERE, once, through
    :func:`_project_context` — so an invalid ``--project`` is the structured
    ``project_not_found`` on either arm and no recipe re-resolves (#353), while a
    command that inherits no project (``inherits_project=False``) is not handed an
    inherited one (#357).

    A command with a ``recipe`` (``export run``, the ``daemon`` lifecycle,
    ``screen``, ``gda skill``, …) is fulfilled by it: the recipe PRODUCES the
    outcome, and emission is the SAME shared tail every command uses —
    :func:`emit_result` with the command's own ``cmd.render`` — so a recipe command
    renders identically to a sentinel one. Every other command runs through the
    sentinel ``cmd.emit`` with its ``kind``-selected runner (:func:`_emit`), whose
    renderer is also ``cmd.render``, so none is threaded here.
    """
    resolved = _project_context(cmd, project, json_output=json_output)
    if cmd.recipe is None:
        _emit(cmd, params, json_output=json_output, godot=godot, project=resolved)
        return
    outcome = cmd.recipe(params, project=resolved, godot=godot)
    if isinstance(outcome, Failure):
        emit_failure(outcome, json_output=json_output)
    emit_result(outcome, json_output, cmd.render)


def _run_params_json(
    cmd: HeadlessCommand[M], params: BaseModel, ctx: typer.Context
) -> None:
    """Dispatch a ``--params-json`` invocation through the dispatch entry (ADR-0015).

    Registered with :func:`gda.headless.register_params_json_dispatch`. The model
    is already built from the JSON object by the command class; this only routes
    it through :func:`dispatch_command`, the entry every argv body calls, so the
    two input paths are indistinguishable downstream. The global
    ``--json`` / ``--godot`` / ``--project`` options parsed alongside
    ``--params-json`` are honored.
    """
    options = ctx.params
    dispatch_command(
        cmd,
        params,
        json_output=bool(options.get("json_output", False)),
        godot=options.get("godot"),
        project=options.get("project"),
    )


register_params_json_dispatch(_run_params_json)
