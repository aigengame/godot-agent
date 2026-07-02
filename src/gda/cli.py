"""The ``gda`` CLI entrypoint.

Meta commands (about ``gda`` or the engine itself) sit at the top level;
domain commands are grouped under their Godot domain object (ADR-0005).
``gda info`` is the Phase-1 tracer bullet; the ``scene`` group is the first
domain group (issue #18). Every command drives the same headless pipeline:
binary resolution → runner → sentinel parse → typed model → JSON.
"""

# Typer attaches same-named subcommands (create/get/...) to different sub-apps,
# so reusing the function name is intentional — the descriptor-driven command
# surface (ADR-0023). pyright's reportRedeclaration is a false positive for that
# idiom (the type-checker analogue of the ruff F811 per-file ignore for this
# module), so it is suppressed file-wide here.
# pyright: reportRedeclaration=false

import json
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Optional

import typer
from pydantic import BaseModel, ValidationError

from gda.daemon_ops import (
    run_daemon_start_operation,
    run_daemon_status_operation,
    run_daemon_stop_operation,
    run_daemon_uninstall_operation,
)
from gda.errors import (
    Failure,
    classify_diag_errors,
    classify_game_get,
    classify_game_set,
    classify_game_tree,
    classify_info,
    classify_input_action,
    classify_input_key,
    classify_input_mouse,
    classify_input_sequence,
    classify_logger_tail,
    classify_perf_monitor,
    classify_perf_monitors,
    classify_script_validate,
    invalid_project_failure,
)
from gda.execution import ExecutionKind
from gda.export_run import (
    EXPORT_GET_COMMAND,
    run_export_operation,
)
from gda.export_runner import ExportRunner, make_subprocess_export_runner
from gda.headless import (
    HeadlessCommand,
    M,
    emit_failure,
    emit_result,
    godot_option,
    json_option,
    make_subprocess_runner,
    params_json_option,
    project_option,
    register_params_json_dispatch,
    schema_command_class,
    schema_option,
)
from gda.live_runner import make_daemon_runner
from gda.models import (
    DaemonStartParams,
    DaemonStartResult,
    DaemonStatusParams,
    DaemonStatusResult,
    DaemonStopParams,
    DaemonStopResult,
    DaemonUninstallParams,
    DaemonUninstallResult,
    DiagErrorsParams,
    DiagErrorsResult,
    EngineVersion,
    ExportGetParams,
    ExportListParams,
    ExportListResult,
    ExportRunMode,
    ExportRunParams,
    ExportRunResult,
    GameGetParams,
    GameGetResult,
    GameSetParams,
    GameSetResult,
    GameTreeParams,
    GameTreeResult,
    InfoParams,
    InputActionParams,
    InputActionResult,
    InputKeyParams,
    InputKeyResult,
    InputMouseClickParams,
    InputMouseMoveParams,
    InputMouseResult,
    InputSequenceParams,
    InputSequenceResult,
    LogLevel,
    LoggerTailParams,
    LoggerTailResult,
    MAX_WINDOW_FRAMES,
    MouseButton,
    PerfMonitorParams,
    PerfMonitorResult,
    PerfMonitorsParams,
    PerfMonitorsResult,
    ProjectDependenciesParams,
    ProjectDependenciesResult,
    ProjectFindReferencesParams,
    ProjectFindReferencesResult,
    ProjectFindUnusedResourcesParams,
    ProjectFindUnusedResourcesResult,
    ProjectStatisticsParams,
    ProjectStatisticsResult,
    NodeAddParams,
    NodeAddResult,
    NodeConnectSignalParams,
    NodeConnectSignalResult,
    NodeDisconnectSignalParams,
    NodeDisconnectSignalResult,
    NodeDuplicateParams,
    NodeDuplicateResult,
    NodeGetParams,
    NodeGetResult,
    NodeListParams,
    NodeListResult,
    NodeMoveParams,
    NodeMoveResult,
    NodeRemoveParams,
    NodeRemoveResult,
    NodeSetParams,
    NodeSetResult,
    ProjectAddAutoloadParams,
    ProjectAddAutoloadResult,
    ProjectAddInputActionParams,
    ProjectAddInputActionResult,
    ProjectGetParams,
    ProjectGetResult,
    ProjectInfoParams,
    ProjectInfoResult,
    ProjectListParams,
    ProjectListResult,
    ProjectRemoveAutoloadParams,
    ProjectRemoveAutoloadResult,
    ProjectRemoveInputActionParams,
    ProjectRemoveInputActionResult,
    ProjectSetParams,
    ProjectSetResult,
    ResourceCreateParams,
    ResourceCreateResult,
    ResourceDeleteParams,
    ResourceDeleteResult,
    ResourceGetParams,
    ResourceGetResult,
    ResourceSetParams,
    ResourceSetResult,
    ResourceUidParams,
    ResourceUidResult,
    SchemaAllParams,
    ScreenCaptureParams,
    ScreenCaptureResult,
    ScreenFramesParams,
    ScreenFramesResult,
    SceneCreateParams,
    SceneCreateResult,
    SceneDeleteParams,
    SceneDeleteResult,
    SceneGetExportsParams,
    SceneGetExportsResult,
    SceneGetParams,
    SceneGetResult,
    SceneListParams,
    SceneListResult,
    ScriptAttachParams,
    ScriptAttachResult,
    ScriptCreateParams,
    ScriptCreateResult,
    ScriptDeleteParams,
    ScriptDeleteResult,
    ScriptGetParams,
    ScriptGetResult,
    ScriptListParams,
    ScriptListResult,
    ScriptRunParams,
    ScriptRunResult,
    ScriptSetMode,
    ScriptSetParams,
    ScriptSetResult,
    ScriptValidateParams,
    ScriptValidateResult,
    ShaderCreateParams,
    ShaderCreateResult,
    ShaderGetParams,
    ShaderGetResult,
    ShaderSetParams,
    ShaderSetResult,
    SkillParams,
    SkillResult,
    SurfaceManifest,
    ThemeCreateParams,
    ThemeCreateResult,
    resolve_set_mode,
)
from gda.project import resolve_project_dir
from gda.render import (
    render_daemon_start,
    render_daemon_status,
    render_daemon_stop,
    render_daemon_uninstall,
    render_diag_errors,
    render_engine_version,
    render_export_list,
    render_export_run,
    render_game_get,
    render_game_set,
    render_game_tree,
    render_input_action,
    render_input_key,
    render_input_mouse,
    render_input_sequence,
    render_logger_tail,
    render_node_add,
    render_node_connect_signal,
    render_node_disconnect_signal,
    render_node_duplicate,
    render_node_list,
    render_node_move,
    render_node_properties,
    render_node_remove,
    render_node_set,
    render_perf_monitor,
    render_perf_monitors,
    render_project_add_autoload,
    render_project_add_input_action,
    render_project_dependencies,
    render_project_find_references,
    render_project_find_unused_resources,
    render_project_get,
    render_project_info,
    render_project_list,
    render_project_remove_autoload,
    render_project_remove_input_action,
    render_project_set,
    render_project_statistics,
    render_resource_create,
    render_resource_delete,
    render_resource_properties,
    render_resource_set,
    render_resource_uid,
    render_scene_delete,
    render_scene_exports,
    render_scene_list,
    render_scene_metadata,
    render_scene_tree,
    render_screen_capture,
    render_screen_frames,
    render_script_attach,
    render_script_create,
    render_script_delete,
    render_script_get,
    render_script_list,
    render_script_run,
    render_script_set,
    render_script_validate,
    render_shader_create,
    render_shader_get,
    render_shader_set,
    render_skill,
    render_theme_create,
)
from gda.runner import GodotRunner
from gda.screen_ops import (
    run_screen_capture_operation,
    run_screen_frames_operation,
)
from gda.script_run import run_script_run_operation
from gda.skill_ops import build_skill_result
from gda.skill_targets import SkillProvider, SkillScope
from gda.surface import build_surface_manifest

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)

# The first domain command group (ADR-0005): commands acting on scene files.
scene_app = typer.Typer(help="Act on Godot scene files (.tscn).", no_args_is_help=True)
app.add_typer(scene_app, name="scene")

# The node command group (issue #53): commands acting on nodes WITHIN a scene
# file (load → locate → mutate → pack → save), so they stay headless.
node_app = typer.Typer(
    help="Act on nodes within a scene file (.tscn).", no_args_is_help=True
)
app.add_typer(node_app, name="node")

# The script command group (issue #110): commands acting on .gd script files on
# disk (write text / read text back), so they stay headless. C# (.cs) is out of
# scope for now — it needs the .NET build of Godot (ADR-0003 targets the standard
# build) and a dedicated decision.
script_app = typer.Typer(help="Act on script files (.gd).", no_args_is_help=True)
app.add_typer(script_app, name="script")

# The resource command group (issue #112): commands acting on .tres resource
# files on disk (load/save plumbing), so they stay headless. The group is a
# .tres tracer; the binary .res form is out of scope for this slice.
resource_app = typer.Typer(help="Act on resource files (.tres).", no_args_is_help=True)
app.add_typer(resource_app, name="resource")

# The export command group (issue #114): read-only discovery of the project's
# export presets (from export_presets.cfg) and export-template readiness. These
# stay headless — they parse a config file and check the filesystem, never
# running an actual export (that is a later slice, issue #121).
export_app = typer.Typer(
    help="Discover export presets and export-template status.", no_args_is_help=True
)
app.add_typer(export_app, name="export")

# The project command group: commands acting on the Godot project as a whole.
# The project-settings read/write commands (info/get/set, issue #111) read and
# write the resolved project's project.godot / ProjectSettings headlessly. Issue
# #116 adds the read-only, project-wide static-analysis reads (find-references,
# dependencies, find-unused-resources, statistics), all backed by a single static
# project scan that parses files as text — never instantiating a scene or loading
# a script (issue #30). Every project command runs against an explicit project
# context (--project), so — like any --project op — it runs the project's
# autoloads at engine startup (#61, ADR-0009).
project_app = typer.Typer(
    help="Act on the Godot project as a whole.", no_args_is_help=True
)
app.add_typer(project_app, name="project")

# The asset-file groups (issue #115): headless authoring of the asset-file types.
# A .gdshader is plain shader source authored as text (create / get / set author
# the file directly and never load or compile the shader at the operation level),
# while theme create produces a loadable .tres Theme resource (engine-backed) —
# the same file-level vs engine-backed split the script group draws between
# create/get/set and attach/validate. This bounds the operation, not the run:
# every command still goes through the headless runner, so resolving --project
# still constructs the project's autoloads at engine startup (ADR-0009).
shader_app = typer.Typer(help="Act on shader files (.gdshader).", no_args_is_help=True)
app.add_typer(shader_app, name="shader")

theme_app = typer.Typer(
    help="Act on theme resource files (.tres).", no_args_is_help=True
)
app.add_typer(theme_app, name="theme")

# The game command group (Phase 2, ADR-0019): the RUNNING game's runtime scene
# graph, served LIVE through gda-daemon (`kind = LIVE`). `game tree` reads the
# runtime SceneTree after _ready; the on-disk counterparts stay under `scene` /
# `node`. It is a domain-object group named after the running game, not a phase
# group — the headless/live split is carried by `kind`, never by the tree.
game_app = typer.Typer(
    help="Act on the running game (live; needs `gda daemon start`).",
    no_args_is_help=True,
)
app.add_typer(game_app, name="game")

# The diag command group (Phase 2, ADR-0019, #224): the RUNNING game's runtime
# diagnostics — its errors and its output log — served LIVE (`kind = LIVE`).
# Unlike `game`, diag is daemon-served: the daemon reads the Session log it
# launched the engine with (`--log-file`) rather than relaying to the harness,
# and serves it even after the session process has died, so a crash stays
# diagnosable. From the CLI's side it routes like any live command (kind = LIVE
# -> the daemon socket); the daemon recognizes the diag op names.
diag_app = typer.Typer(
    help="Read the running game's runtime diagnostics (live; needs `gda daemon start`).",
    no_args_is_help=True,
)
app.add_typer(diag_app, name="diag")

# The logger command group (Phase 2, ADR-0019, ADR-0026, #281): the running game's
# STRUCTURED runtime-log stream as a domain object, marked LIVE by `kind`. Like
# `diag`, it is daemon-served — the daemon parses the Session log it owns
# (`--log-file`) into typed `LogRecord`s rather than relaying to the harness, so a
# crash stays diagnosable. `logger tail` is the passive, non-invasive floor of the
# structured-log protocol; the raw `diag log` is superseded by `logger tail --raw`.
logger_app = typer.Typer(
    help="Read the running game's structured runtime log (live; needs `gda daemon start`).",
    no_args_is_help=True,
)
app.add_typer(logger_app, name="logger")

# The perf command group (Phase 2, ADR-0019, #223): runtime performance monitoring
# of the RUNNING game, served LIVE through gda-daemon (`kind = LIVE`). `perf
# monitors` snapshots the engine's Performance counters in one frame; `perf monitor`
# collects a per-frame property/signal timeline over N frames (the time-windowed
# multi-frame harness base). Like `game`, a domain-object group marked live by
# `kind`, not by the tree (ADR-0019).
perf_app = typer.Typer(
    help="Monitor the running game's runtime performance (live).",
    no_args_is_help=True,
)
app.add_typer(perf_app, name="perf")

# The input command group (Phase 2, ADR-0019, #221): runtime input simulation into
# the RUNNING game, served LIVE through gda-daemon (`kind = LIVE`). Single-frame
# ops (`input key`, `input mouse-click/mouse-move`, `input action`) inject one event
# at a frame boundary; `input sequence` reuses #223's time-windowed multi-frame base
# to apply events across frames in one blocking call. Like `game` / `perf`, a domain-
# object group marked live by `kind`, not by the tree (ADR-0019). The mouse ops are
# flat two-token commands (`mouse-click` / `mouse-move`) directly under `input`, not a
# nested `mouse` sub-group: a 3-token name would break the mechanical
# `gda <group> <command>` → `<group>_<command>` dispatch + gda-mcp tool-name mapping
# (ADR-0005/0011/0012).
input_app = typer.Typer(
    help="Inject input into the running game (live).",
    no_args_is_help=True,
)
app.add_typer(input_app, name="input")

# The screen command group (Phase 2, ADR-0019): the running game's VIEWPORT is the
# domain object (not under `game`, whose object is the runtime scene graph). Both
# commands are LIVE (kind = LIVE), routed through gda-daemon to a WINDOWED engine
# session (`gda daemon start --windowed`); on a headless session a capture is the
# typed `live_display_unavailable` (#222).
screen_app = typer.Typer(
    help="Capture the running game's viewport (live; macOS/Linux only, windowed session).",
    no_args_is_help=True,
)
app.add_typer(screen_app, name="screen")

# The daemon command group (Phase 2, ADR-0017): gda's own per-project daemon
# lifecycle — a deliberate extension of ADR-0005's domain-object grouping to an
# infrastructure object (gda-daemon), not a top-level meta singleton. start /
# stop / status manage the daemon PROCESS, so — like `export run` — they run a
# recipe (gda.daemon_ops) rather than the sentinel pipeline.
daemon_app = typer.Typer(
    help="Manage the per-project gda-daemon (live ops).",
    no_args_is_help=True,
)
app.add_typer(daemon_app, name="daemon")


def _version_callback(value: Optional[bool]) -> None:
    if value:
        typer.echo(f"gda {package_version('gda')}")
        raise typer.Exit()


@app.callback()
def main(
    show_version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed gda version and exit.",
    ),
) -> None:
    """An agent-facing Godot CLI with structured output."""
    # A no-op callback keeps gda a command *group* so meta commands like
    # `gda info` stay named subcommands (ADR-0005) rather than collapsing to
    # the top level, as Typer does for a single-command app.


def _make_runner(binary: Path, project: Optional[Path]) -> GodotRunner:
    """Build the default (real) Godot runner for ``binary`` and ``project``.

    A seam tests override (via monkeypatch) to inject a fake runner.
    """
    return make_subprocess_runner(binary, project)


def _make_export_runner(binary: Path, project: Optional[Path]) -> ExportRunner:
    """Build the default (real) native-export runner for ``binary`` and ``project``.

    The ``export run``-only twin of :func:`_make_runner`: a seam tests override
    to inject a fake export runner, since ``export run`` spawns Godot with native
    ``--export-<mode>`` flags rather than the ``operations.gd`` payload.
    """
    return make_subprocess_export_runner(binary, project)


def _make_live_runner(binary: Optional[Path], project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner — the per-project gda-daemon IPC client (ADR-0017).

    The ``kind = LIVE`` twin of :func:`_make_runner`, a seam tests override to
    inject a fake daemon runner. ``binary`` is unused: a live op reaches the
    running daemon, not a fresh engine, so the daemon (not the CLI) owns the
    engine session.
    """
    return make_daemon_runner(project)


# --- Recipe channels (ADR-0023) -----------------------------------------------
# Each recipe command (export run / the daemon lifecycle / screen) carries one of
# these on its descriptor (``recipe=``). A recipe PRODUCES the outcome — run the
# CLI-side operation over the ALREADY-resolved ``project`` (resolution happens once
# in :func:`_dispatch_recipe`, kept CLI-side per ADR-0006, so an invalid --project is
# a structured project_not_found before any recipe runs, #353) — and RETURNS the
# typed result or a Failure; emission stays the shared tail (:func:`_dispatch_recipe`
# → ``cmd.render``), so a recipe command renders exactly like a sentinel one. The
# runner seams (``_make_*``) are referenced at call time so test monkeypatches on
# ``gda.cli._make_runner`` / ``_make_live_runner`` still bind. ``params`` is the
# built model — the single source of truth (ADR-0015), identical on the argv and
# ``--params-json`` paths — so windowed/output/etc. are read off it, never special-cased.


def _daemon_start_recipe(params, *, project, godot):
    return run_daemon_start_operation(
        project,
        godot,
        windowed=params.windowed,
        scene=params.scene,
    )


def _daemon_stop_recipe(params, *, project, godot):
    return run_daemon_stop_operation(project)


def _daemon_status_recipe(params, *, project, godot):
    return run_daemon_status_operation(project)


def _daemon_uninstall_recipe(params, *, project, godot):
    return run_daemon_uninstall_operation(project)


def _screen_capture_recipe(params, *, project, godot):
    return run_screen_capture_operation(
        project,
        Path(params.output),
        inline=params.inline,
        make_runner=_make_live_runner,
    )


def _screen_frames_recipe(params, *, project, godot):
    return run_screen_frames_operation(
        project,
        params.frames,
        Path(params.output_dir),
        make_runner=_make_live_runner,
    )


def _skill_recipe(params, *, project, godot):
    # A pure local emitter (ADR-0024): no project, no Godot — it reads the bundled
    # SKILL.md and either returns it (version-locked) or installs it. ``project`` /
    # ``godot`` are part of the recipe contract but unused here (a meta command).
    return build_skill_result(install=params.install, install_dir=params.install_dir)


def _export_run_recipe(params, *, project, godot):
    return run_export_operation(
        preset=params.preset,
        mode=params.mode,
        output_override=params.output,
        godot=godot,
        project=project,
        make_runner=_make_runner,
        make_export_runner=_make_export_runner,
    )


# ``export-run`` does NOT route through operations.gd: the Godot export subsystem is
# editor-only C++, so the export is a native --export-<mode> invocation driven by
# ``run_export_operation`` (gda.export_run). Its descriptor is the single fully-bound
# registration (ADR-0023) and is defined HERE — not beside the operation — because its
# recipe needs cli's runner seams, and cli.py is the dispatch composition root. (Its
# sibling ``EXPORT_GET_COMMAND`` is a plain sentinel command and stays in gda.export_run,
# which consumes it directly.)
EXPORT_RUN_COMMAND: HeadlessCommand[ExportRunResult] = HeadlessCommand(
    operation="export-run",
    input_model=ExportRunParams,
    output_model=ExportRunResult,
    kind=ExecutionKind.EXPORT,
    render=render_export_run,
    recipe=_export_run_recipe,
)


def _script_run_recipe(params, *, project, godot):
    # ``project`` arrives ALREADY resolved by _dispatch_recipe — an invalid
    # --project/$GDA_PROJECT was converted to a structured project_not_found before
    # this runs, so no per-recipe ValueError handling is needed here (#353 folded in
    # script run's former try/except). A projectless None remains the op's own ABI
    # edge: run_script_run_operation returns script_run_project_not_found_failure()
    # for it (ADR-0031).
    return run_script_run_operation(
        script=params.path,
        godot=godot,
        project=project,
    )


# ``script run`` is the third execution shape (ADR-0031): a user-script passthrough
# run. Its entry script is the user's own, so it emits no ADR-0002 sentinel, and gda
# does not know the script's semantics — so it routes through the recipe channel
# (ADR-0023) like ``export run``, and carries the fourth ``SCRIPT_RUN`` kind, which is
# self-description only (ADR-0004 / ADR-0012) — dispatch is by ``recipe``, adding no
# runner-selection branch. The descriptor is defined HERE, not beside the operation
# (gda.script_run), because its recipe needs cli's project-resolution seam and cli.py
# is the dispatch composition root (ADR-0023).
SCRIPT_RUN_COMMAND: HeadlessCommand[ScriptRunResult] = HeadlessCommand(
    operation="script-run",
    input_model=ScriptRunParams,
    output_model=ScriptRunResult,
    kind=ExecutionKind.SCRIPT_RUN,
    render=render_script_run,
    recipe=_script_run_recipe,
)


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
    a ``LIVE`` command goes through :func:`_make_live_runner` (the daemon IPC
    client), every other through :func:`_make_runner`. Both seams are referenced
    here at call time, so a test monkeypatch on ``gda.cli._make_runner`` /
    ``gda.cli._make_live_runner`` still binds. Both the domain dispatch
    (:func:`_dispatch`) and the meta dispatch (:func:`_dispatch_meta`) funnel
    through here; they differ only in how ``project`` is obtained.
    """
    make_runner = _make_live_runner if cmd.kind is ExecutionKind.LIVE else _make_runner
    cmd.emit(
        params,
        godot=godot,
        project=project,
        json_output=json_output,
        make_runner=make_runner,
    )


def _resolve_project_or_fail(project: Optional[str]) -> Optional[Path]:
    """Resolve ``--project`` (ADR-0006), or emit a structured ``project_not_found``
    and exit — never leak the raise as a traceback (#353).

    ``resolve_project_dir`` raises ``ValueError`` for an explicit ``--project`` or
    ``$GDA_PROJECT`` that is empty or is not a Godot project. This is the ONE shared
    project-resolution point on the CLI dispatch path, so converting the raise here
    gives every channel — sentinel (:func:`_dispatch`) and recipe
    (:func:`_dispatch_recipe`) — the structured envelope in a single place.
    """
    try:
        return resolve_project_dir(project)
    except ValueError as exc:
        emit_failure(invalid_project_failure(str(exc)))


def _dispatch(
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
        project=_resolve_project_or_fail(project),
    )


def _dispatch_meta(
    cmd: HeadlessCommand[M],
    params: BaseModel,
    *,
    json_output: bool,
    godot: Optional[str],
) -> None:
    """Run a meta command (no ``--project``, ADR-0005) through the shared tail.

    Unlike :func:`_dispatch`, this never calls ``resolve_project_dir``: a meta
    command (``gda info``) is about ``gda``/the engine itself, so it runs
    projectless rather than resolving a project context.
    """
    _emit(
        cmd,
        params,
        json_output=json_output,
        godot=godot,
        project=None,
    )


def _dispatch_recipe(
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
    A ``projectless`` recipe (a pure meta emitter like ``gda skill``, ADR-0024) is
    NOT resolved: it takes no project, so an inherited invalid ``$GDA_PROJECT``
    must not make it fail (#357).
    """
    # A recipe command always carries a recipe channel — that is what routes it
    # here rather than to the sentinel ``cmd.emit`` path (ADR-0023). A project-using
    # recipe receives the ALREADY-resolved project (or a structured project_not_found
    # is emitted before it runs); a projectless meta recipe receives None and never
    # touches ``resolve_project_dir``.
    assert cmd.recipe is not None
    resolved = None if cmd.projectless else _resolve_project_or_fail(project)
    outcome = cmd.recipe(params, project=resolved, godot=godot)
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
    ``--params-json`` are honored; a meta command (no ``--project`` option)
    dispatches projectless, mirroring :func:`_dispatch_meta`.
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
        _dispatch_recipe(
            cmd,
            params,
            json_output=json_output,
            godot=godot,
            project=options.get("project"),
        )
        return
    if "project" in options:
        _dispatch(
            cmd,
            params,
            json_output=json_output,
            godot=godot,
            project=options.get("project"),
        )
    else:
        _dispatch_meta(cmd, params, json_output=json_output, godot=godot)


register_params_json_dispatch(_run_params_json)


INFO_COMMAND: HeadlessCommand[EngineVersion] = HeadlessCommand(
    operation="info",
    input_model=InfoParams,
    output_model=EngineVersion,
    render=render_engine_version,
    classify=classify_info,
)

# `gda skill` is a pure emitter meta command (ADR-0024): it reads the in-package
# SKILL.md and emits or installs it, spawning no Godot — so, like `export run` and
# the daemon lifecycle, it carries a `recipe` on its descriptor and dispatches
# through it (`_dispatch_recipe`) rather than the sentinel pipeline. It stays
# HEADLESS `kind` (the default) and meta (no --project), a sibling of info/schema.
SKILL_COMMAND: HeadlessCommand[SkillResult] = HeadlessCommand(
    operation="skill",
    input_model=SkillParams,
    output_model=SkillResult,
    render=render_skill,
    recipe=_skill_recipe,
    # A pure meta emitter (ADR-0024): no --project, resolves none — so the recipe
    # dispatcher must not resolve a project for it (an inherited invalid $GDA_PROJECT
    # must not make `gda skill` fail, #357).
    projectless=True,
)

GAME_TREE_COMMAND: HeadlessCommand[GameTreeResult] = HeadlessCommand(
    operation="game-tree",
    input_model=GameTreeParams,
    output_model=GameTreeResult,
    render=render_game_tree,
    classify=classify_game_tree,
    kind=ExecutionKind.LIVE,
)


@game_app.command(name="tree", cls=GAME_TREE_COMMAND.command_class())
def game_tree(
    json_output: bool = json_option(),
    schema: bool = GAME_TREE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's runtime scene tree (live).

    Routes through gda-daemon to the engine session it holds (kind = LIVE,
    ADR-0017): the runtime SceneTree after _ready and dynamic instantiation,
    distinct from the on-disk .tscn read by `scene get` (ADR-0019). Live ops need
    a running daemon: with none, it reports the typed `daemon_not_running` error
    naming the remediation (`gda daemon start`); on an unsupported platform,
    `live_unsupported_platform`. The platform/Godot-version precondition is the
    structured `constraints` field of `--schema` (ADR-0021), not restated here.
    """
    _dispatch(
        GAME_TREE_COMMAND,
        GameTreeParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


GAME_GET_COMMAND: HeadlessCommand[GameGetResult] = HeadlessCommand(
    operation="game-get",
    input_model=GameGetParams,
    output_model=GameGetResult,
    render=render_game_get,
    classify=classify_game_get,
    kind=ExecutionKind.LIVE,
)


@game_app.command(name="get", cls=GAME_GET_COMMAND.command_class())
def game_get(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player).",
    ),
    property: Optional[str] = typer.Option(
        None,
        "--property",
        help="If set, read only this one property instead of the whole storage surface.",
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a running node's runtime properties (live).

    The live counterpart of `node get`: routes through gda-daemon to the engine
    session's runtime SceneTree (kind = LIVE, ADR-0017), addressed by the runtime
    (absolute) node path `game tree` reports — not a `.tscn` file. With no daemon
    it reports `daemon_not_running`; a path that resolves to no running node is
    `live_node_not_found`; `--property` naming an absent property is
    `live_unknown_property`.
    """
    _dispatch(
        GAME_GET_COMMAND,
        GameGetParams(node=node, property=property),
        json_output=json_output,
        godot=godot,
        project=project,
    )


GAME_SET_COMMAND: HeadlessCommand[GameSetResult] = HeadlessCommand(
    operation="game-set",
    input_model=GameSetParams,
    output_model=GameSetResult,
    render=render_game_set,
    classify=classify_game_set,
    kind=ExecutionKind.LIVE,
)


@game_app.command(name="set", cls=GAME_SET_COMMAND.command_class())
def game_set(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player).",
    ),
    property: str = typer.Option(
        ..., "--property", help="The property to set (e.g. position, visible)."
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "Godot type (the same coercion `node set` uses); an uncoercible value "
            "is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a running node's runtime property, coercing the value to its type (live).

    The live counterpart of `node set`: routes through gda-daemon to the engine
    session (kind = LIVE, ADR-0017), addressed by the runtime (absolute) node path.
    The gda harness coerces `--value` to the property's declared Godot type — the
    SAME coercion table `node set` uses — and applies it at a frame boundary
    (ADR-0020); the mutation is bound to the session, not persisted to disk. With
    no daemon it reports `daemon_not_running`; an absent node is
    `live_node_not_found`, an absent property `live_unknown_property`, an
    uncoercible value `live_uncoercible_value`.
    """
    _dispatch(
        GAME_SET_COMMAND,
        GameSetParams(node=node, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def _diag_limit_option() -> Optional[int]:
    """The shared `--limit N` option for the log-reading live commands: tail N.

    Used by both ``gda diag errors`` and ``gda logger tail``. Bound to ``>= 1``
    (Click ``min``) so a zero/negative limit is a usage error on the argv path,
    mirroring the ``ge=1`` constraint on ``DiagErrorsParams`` / ``LoggerTailParams``
    that the ``--params-json`` / ``--schema`` path enforces.
    """
    return typer.Option(
        None,
        "--limit",
        min=1,
        help="If set, tail only the most recent N entries (newest last); must be >= 1.",
    )


DIAG_ERRORS_COMMAND: HeadlessCommand[DiagErrorsResult] = HeadlessCommand(
    operation="diag-errors",
    input_model=DiagErrorsParams,
    output_model=DiagErrorsResult,
    render=render_diag_errors,
    classify=classify_diag_errors,
    kind=ExecutionKind.LIVE,
)


@diag_app.command(name="errors", cls=DIAG_ERRORS_COMMAND.command_class())
def diag_errors(
    limit: Optional[int] = _diag_limit_option(),
    json_output: bool = json_option(),
    schema: bool = DIAG_ERRORS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's runtime errors as structured output (live).

    Routes through gda-daemon (kind = LIVE, ADR-0017), but is daemon-served: the
    daemon reads the Session log it launched the engine with (`--log-file`) — NOT
    the harness — so it works even after the game has crashed, keeping the crash
    diagnosable (#224). Each entry carries a normalized `level` (error / warning /
    script_error / shader_error) and, when the log recorded it, the source
    function/file/line. `--limit N` tails the most recent N. With no daemon it
    reports `daemon_not_running`; with a daemon but no session ever launched,
    `engine_session_not_running`; with a session whose log file is gone,
    `live_log_unavailable`. An empty log is an empty result, not an error.
    """
    _dispatch(
        DIAG_ERRORS_COMMAND,
        DiagErrorsParams(limit=limit),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def _logger_level_option() -> Optional[LogLevel]:
    """The `--level <min>` option for `gda logger tail`: a minimum-severity filter.

    Bound to the closed :class:`~gda.models.LogLevel` enum (Click choices), so an
    out-of-set value is a usage error on the argv path, mirroring the enum-typed
    field on ``LoggerTailParams`` that the ``--params-json`` / ``--schema`` path
    enforces. Omitting it returns all severities.
    """
    return typer.Option(
        None,
        "--level",
        help=(
            "If set, return only records at or above this minimum severity over the "
            "closed ordering debug < info < warning < error. Omit for all."
        ),
    )


def _logger_raw_option() -> bool:
    """The `--raw` flag for `gda logger tail`: verbatim lines instead of records.

    The superseded `diag log` view: with it, the result carries the verbatim
    captured lines (`lines`) and no structured records.
    """
    return typer.Option(
        False,
        "--raw",
        help="Return the verbatim captured log lines instead of structured records.",
    )


LOGGER_TAIL_COMMAND: HeadlessCommand[LoggerTailResult] = HeadlessCommand(
    operation="logger-tail",
    input_model=LoggerTailParams,
    output_model=LoggerTailResult,
    render=render_logger_tail,
    classify=classify_logger_tail,
    kind=ExecutionKind.LIVE,
)


@logger_app.command(name="tail", cls=LOGGER_TAIL_COMMAND.command_class())
def logger_tail(
    level: Optional[LogLevel] = _logger_level_option(),
    limit: Optional[int] = _diag_limit_option(),
    raw: bool = _logger_raw_option(),
    json_output: bool = json_option(),
    schema: bool = LOGGER_TAIL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read the running game's structured runtime log (live).

    The passive, non-invasive structured runtime-log channel (#281, ADR-0026): the
    daemon parses the whole daemon-owned Session log into typed `LogRecord`s —
    engine errors/warnings via the diag parser (carrying `source` + an `origin`
    sub-kind), every other line a plain `info` record. So an un-instrumented
    project gets structured logs for free. `--level <min>` filters by minimum
    severity over the closed ordering debug < info < warning < error; `--limit N`
    tails the most recent N (after the filter); `--raw` returns the verbatim lines
    instead (the superseded `diag log` view). Daemon-served like `diag`: read from
    the `--log-file` the daemon owns, so it works even after the game has crashed.
    With no daemon it reports `daemon_not_running`; with a daemon but no session
    ever launched, `engine_session_not_running`; with a session whose log file is
    gone, `live_log_unavailable`. An empty log is an empty result, not an error.
    """
    _dispatch(
        LOGGER_TAIL_COMMAND,
        LoggerTailParams(level=level, limit=limit, raw=raw),
        json_output=json_output,
        godot=godot,
        project=project,
    )


PERF_MONITORS_COMMAND: HeadlessCommand[PerfMonitorsResult] = HeadlessCommand(
    operation="perf-monitors",
    input_model=PerfMonitorsParams,
    output_model=PerfMonitorsResult,
    render=render_perf_monitors,
    classify=classify_perf_monitors,
    kind=ExecutionKind.LIVE,
)


@perf_app.command(name="monitors", cls=PERF_MONITORS_COMMAND.command_class())
def perf_monitors(
    json_output: bool = json_option(),
    schema: bool = PERF_MONITORS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Snapshot the running game's performance monitors (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017): the
    instantaneous Performance counters — fps, frame timing, memory, object/node
    counts, render stats, active physics/navigation objects — read in one frame, so
    the values are mutually coherent (ADR-0020). Live ops need a running daemon:
    with none, it reports `daemon_not_running`.
    """
    _dispatch(
        PERF_MONITORS_COMMAND,
        PerfMonitorsParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


PERF_MONITOR_COMMAND: HeadlessCommand[PerfMonitorResult] = HeadlessCommand(
    operation="perf-monitor",
    input_model=PerfMonitorParams,
    output_model=PerfMonitorResult,
    render=render_perf_monitor,
    classify=classify_perf_monitor,
    kind=ExecutionKind.LIVE,
)


@perf_app.command(name="monitor", cls=PERF_MONITOR_COMMAND.command_class())
def perf_monitor(
    node: str = typer.Argument(
        ...,
        help="Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player).",
    ),
    property: Optional[str] = typer.Option(
        None,
        "--property",
        help="The property to sample each frame (mutually exclusive with --signal).",
    ),
    signal: Optional[str] = typer.Option(
        None,
        "--signal",
        help="The signal whose emissions to record over the window (mutually exclusive with --property).",
    ),
    frames: int = typer.Option(
        60,
        "--frames",
        min=1,
        max=MAX_WINDOW_FRAMES,
        help=(
            f"The number of frames to collect over, 1..{MAX_WINDOW_FRAMES} (the "
            "gda harness's per-window ceiling)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PERF_MONITOR_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Watch one running node over a frame window (live, time-windowed).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    collects a per-frame timeline over `--frames` frames, returned as one blocking
    payload (ADR-0017 one-shot RPC, ADR-0020 multi-frame). Pass exactly one of
    `--property` (records the property's value each frame) or `--signal` (records
    the signal's emissions over the window). With no daemon it reports
    `daemon_not_running`; an absent node is `live_perf_node_not_found`, an absent
    property `live_perf_property_not_found`, an absent signal
    `live_perf_signal_not_found`.
    """
    # Exactly one of --property/--signal is required (the same rule the model
    # enforces for --params-json). On the argv path it is a usage error (exit 2),
    # keeping the argv ergonomics, mirroring `script create`'s --content/--extends
    # check; --params-json surfaces the same rule as a structured invalid_params.
    if property is not None and signal is not None:
        raise typer.BadParameter("--property and --signal are mutually exclusive.")
    if property is None and signal is None:
        raise typer.BadParameter("perf monitor needs --property or --signal.")
    _dispatch(
        PERF_MONITOR_COMMAND,
        PerfMonitorParams(node=node, property=property, signal=signal, frames=frames),
        json_output=json_output,
        godot=godot,
        project=project,
    )


INPUT_KEY_COMMAND: HeadlessCommand[InputKeyResult] = HeadlessCommand(
    operation="input-key",
    input_model=InputKeyParams,
    output_model=InputKeyResult,
    render=render_input_key,
    classify=classify_input_key,
    kind=ExecutionKind.LIVE,
)


@input_app.command(name="key", cls=INPUT_KEY_COMMAND.command_class())
def input_key(
    key: str = typer.Argument(
        ..., help="A Godot key name to inject (e.g. Right, A, Space, Escape)."
    ),
    modifiers: list[str] = typer.Option(
        [],
        "--modifiers",
        help="Modifier keys held with the key (repeatable): shift, ctrl, alt, meta.",
    ),
    released: bool = typer.Option(
        False, "--released", help="Inject a key RELEASE instead of a press."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_KEY_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject one key event into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventKey into the running game's root viewport, so it rides the
    game's real input flow. The harness resolves the key name to a keycode; an
    unresolvable name is `live_invalid_key`. With no daemon it reports
    `daemon_not_running`.
    """
    try:
        params = InputKeyParams(key=key, modifiers=modifiers, released=released)
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _dispatch(
        INPUT_KEY_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


INPUT_MOUSE_CLICK_COMMAND: HeadlessCommand[InputMouseResult] = HeadlessCommand(
    operation="input-mouse-click",
    input_model=InputMouseClickParams,
    output_model=InputMouseResult,
    render=render_input_mouse,
    classify=classify_input_mouse,
    kind=ExecutionKind.LIVE,
)


@input_app.command(name="mouse-click", cls=INPUT_MOUSE_CLICK_COMMAND.command_class())
def input_mouse_click(
    x: float = typer.Argument(..., help="The click's x position in the viewport."),
    y: float = typer.Argument(..., help="The click's y position in the viewport."),
    button: MouseButton = typer.Option(
        MouseButton.LEFT,
        "--button",
        help="Which mouse button to click: left, right, or middle.",
    ),
    double: bool = typer.Option(
        False, "--double", help="Mark the event a double click."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_MOUSE_CLICK_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a mouse button click into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventMouseButton at the viewport position into the running
    game's root viewport. With no daemon it reports `daemon_not_running`.
    """
    _dispatch(
        INPUT_MOUSE_CLICK_COMMAND,
        InputMouseClickParams(x=x, y=y, button=button, double=double),
        json_output=json_output,
        godot=godot,
        project=project,
    )


INPUT_MOUSE_MOVE_COMMAND: HeadlessCommand[InputMouseResult] = HeadlessCommand(
    operation="input-mouse-move",
    input_model=InputMouseMoveParams,
    output_model=InputMouseResult,
    render=render_input_mouse,
    classify=classify_input_mouse,
    kind=ExecutionKind.LIVE,
)


@input_app.command(name="mouse-move", cls=INPUT_MOUSE_MOVE_COMMAND.command_class())
def input_mouse_move(
    x: float = typer.Argument(
        ..., help="The motion's target x position in the viewport."
    ),
    y: float = typer.Argument(
        ..., help="The motion's target y position in the viewport."
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_MOUSE_MOVE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a mouse motion event into the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    pushes an InputEventMouseMotion to the viewport position into the running
    game's root viewport. With no daemon it reports `daemon_not_running`.
    """
    _dispatch(
        INPUT_MOUSE_MOVE_COMMAND,
        InputMouseMoveParams(x=x, y=y),
        json_output=json_output,
        godot=godot,
        project=project,
    )


INPUT_ACTION_COMMAND: HeadlessCommand[InputActionResult] = HeadlessCommand(
    operation="input-action",
    input_model=InputActionParams,
    output_model=InputActionResult,
    render=render_input_action,
    classify=classify_input_action,
    kind=ExecutionKind.LIVE,
)


@input_app.command(name="action", cls=INPUT_ACTION_COMMAND.command_class())
def input_action(
    action: str = typer.Argument(
        ..., help="The input action name (must be in the running InputMap)."
    ),
    release: bool = typer.Option(
        False, "--release", help="Release the action instead of pressing it."
    ),
    strength: float = typer.Option(
        1.0,
        "--strength",
        min=0.0,
        max=1.0,
        help="The analog press strength, 0..1 (ignored on a release).",
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Press or release a named input action in the running game (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    drives Input.action_press / action_release against the running InputMap, so the
    game observes the action exactly as a real binding would fire. An action absent
    from the InputMap is `live_unknown_action`. With no daemon it reports
    `daemon_not_running`.
    """
    try:
        params = InputActionParams(action=action, release=release, strength=strength)
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _dispatch(
        INPUT_ACTION_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


INPUT_SEQUENCE_COMMAND: HeadlessCommand[InputSequenceResult] = HeadlessCommand(
    operation="input-sequence",
    input_model=InputSequenceParams,
    output_model=InputSequenceResult,
    render=render_input_sequence,
    classify=classify_input_sequence,
    kind=ExecutionKind.LIVE,
)


@input_app.command(name="sequence", cls=INPUT_SEQUENCE_COMMAND.command_class())
def input_sequence(
    events: str = typer.Option(
        ...,
        "--events",
        help=(
            "The events to inject, as a JSON array of event objects, each with a "
            "'type' (key/mouse_click/mouse_move/action), an optional relative "
            "'frame' offset, and the type's fields (e.g. "
            '\'[{"type":"key","key":"Right","frame":0}]\').'
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = INPUT_SEQUENCE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Inject a sequence of events across frames in one blocking call (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    applies the `--events` across frames at their relative frame offsets, returned
    as one blocking result (reuses #223's time-windowed multi-frame base). A
    malformed `--events` (not a JSON array, an empty list, or an ill-formed event)
    is a usage error; with no daemon it reports `daemon_not_running`. An event's
    action absent from the InputMap is `live_unknown_action`, an unresolvable key
    `live_invalid_key`.
    """
    # --events is a JSON array on the argv path; the model is the source of truth for
    # the per-event shape (ADR-0015), so a parse or validation failure is a usage
    # error (exit 2), while --params-json surfaces the same model rule as a
    # structured invalid_params.
    try:
        decoded = json.loads(events)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--events is not valid JSON: {exc}") from exc
    try:
        params = InputSequenceParams(events=decoded)
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _dispatch(
        INPUT_SEQUENCE_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


DAEMON_START_COMMAND: HeadlessCommand[DaemonStartResult] = HeadlessCommand(
    operation="daemon-start",
    input_model=DaemonStartParams,
    output_model=DaemonStartResult,
    render=render_daemon_start,
    recipe=_daemon_start_recipe,
)

DAEMON_STOP_COMMAND: HeadlessCommand[DaemonStopResult] = HeadlessCommand(
    operation="daemon-stop",
    input_model=DaemonStopParams,
    output_model=DaemonStopResult,
    render=render_daemon_stop,
    recipe=_daemon_stop_recipe,
)

DAEMON_STATUS_COMMAND: HeadlessCommand[DaemonStatusResult] = HeadlessCommand(
    operation="daemon-status",
    input_model=DaemonStatusParams,
    output_model=DaemonStatusResult,
    render=render_daemon_status,
    recipe=_daemon_status_recipe,
)

DAEMON_UNINSTALL_COMMAND: HeadlessCommand[DaemonUninstallResult] = HeadlessCommand(
    operation="daemon-uninstall",
    input_model=DaemonUninstallParams,
    output_model=DaemonUninstallResult,
    render=render_daemon_uninstall,
    recipe=_daemon_uninstall_recipe,
)


@daemon_app.command(name="start", cls=DAEMON_START_COMMAND.command_class())
def daemon_start(
    windowed: bool = typer.Option(
        False,
        "--windowed",
        help=(
            "Launch the engine session windowed (no --headless) so `screen` capture "
            "ops have a display; default headless. Needs a display/Xvfb on a "
            "headless host (#222)."
        ),
    ),
    scene: Optional[str] = typer.Option(
        None,
        "--scene",
        help=(
            "Boot the engine session on this scene (a res:// path or uid:// value) "
            "instead of the project's main_scene; default runs main_scene. A "
            "non-existent scene is a typed `live_scene_not_found` error, never a "
            "silent fall back (#278)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = DAEMON_START_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Start the per-project gda-daemon (idempotent), installing the harness.

    Brings up the live context: a long-lived, per-project daemon, after a reported
    idempotent harness install (ADR-0018). Never auto-spawned by a live call —
    launching the engine is a deliberate, declared effect (ADR-0017). The
    platform/Godot-version precondition is the structured `constraints` field of
    `--schema` (ADR-0021), not restated here. `--windowed` is a start-time declared
    mode for the engine session a `screen` capture op needs (#222); `--scene` boots
    the session on a chosen scene instead of the project's main_scene (#278).
    """
    # Build the params model from the argv options (the single source of truth,
    # ADR-0015) so the recipe reads `windowed`/`scene` off it on BOTH the argv and
    # --params-json paths — no special-casing.
    _dispatch_recipe(
        DAEMON_START_COMMAND,
        DaemonStartParams(windowed=windowed, scene=scene),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@daemon_app.command(name="stop", cls=DAEMON_STOP_COMMAND.command_class())
def daemon_stop(
    json_output: bool = json_option(),
    schema: bool = DAEMON_STOP_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Stop the per-project gda-daemon (a no-op if none is running).

    On an unsupported platform this reports `live_unsupported_platform`; the
    platform precondition is the structured `constraints` field of `--schema`.
    """
    _dispatch_recipe(
        DAEMON_STOP_COMMAND,
        DaemonStopParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@daemon_app.command(name="status", cls=DAEMON_STATUS_COMMAND.command_class())
def daemon_status(
    json_output: bool = json_option(),
    schema: bool = DAEMON_STATUS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report whether a per-project gda-daemon is running.

    On an unsupported platform this reports `live_unsupported_platform`; the
    platform precondition is the structured `constraints` field of `--schema`.
    """
    _dispatch_recipe(
        DAEMON_STATUS_COMMAND,
        DaemonStatusParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@daemon_app.command(name="uninstall", cls=DAEMON_UNINSTALL_COMMAND.command_class())
def daemon_uninstall(
    json_output: bool = json_option(),
    schema: bool = DAEMON_UNINSTALL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Remove the gda harness autoload and files from the project (ADR-0018).

    A release-hygiene step: removal is paired and crash-safe — the [autoload] entry
    is stripped first, then the files — so a mid-failure never leaves a dangling
    autoload (which an exported game logs `ERR_CONTINUE` and skips at startup —
    error spam, not a hard crash; ADR-0028). Idempotent (a no-op if not
    installed). Refused while a daemon is running (`daemon_running`); stop it first
    with `gda daemon stop`. Live is macOS/Linux only; elsewhere reports
    `live_unsupported_platform`.
    """
    _dispatch_recipe(
        DAEMON_UNINSTALL_COMMAND,
        DaemonUninstallParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


# The `screen` commands are LIVE but run a CLI-side recipe (gda.screen_ops), not
# the sentinel pipeline: the harness returns the PNG as base64 in the sentinel and
# the CLI must DECODE + WRITE a file before it has the path-based public result. So
# — like `export run` and the daemon lifecycle commands — each carries a `recipe` on
# its descriptor (ADR-0023): dispatch runs it instead of cmd.emit, selected by the
# single `recipe is not None` test, not command identity. `kind = LIVE` is kept as a
# descriptor fact so "kind":"live" still appears in --schema (#230).
SCREEN_CAPTURE_COMMAND: HeadlessCommand[ScreenCaptureResult] = HeadlessCommand(
    operation="screen-capture",
    input_model=ScreenCaptureParams,
    output_model=ScreenCaptureResult,
    render=render_screen_capture,
    kind=ExecutionKind.LIVE,
    recipe=_screen_capture_recipe,
)

SCREEN_FRAMES_COMMAND: HeadlessCommand[ScreenFramesResult] = HeadlessCommand(
    operation="screen-frames",
    input_model=ScreenFramesParams,
    output_model=ScreenFramesResult,
    render=render_screen_frames,
    kind=ExecutionKind.LIVE,
    recipe=_screen_frames_recipe,
)


@screen_app.command(name="capture", cls=SCREEN_CAPTURE_COMMAND.command_class())
def screen_capture(
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="The file path to write the captured PNG frame to.",
    ),
    inline: bool = typer.Option(
        False,
        "--inline",
        help="Also embed the base64-encoded PNG in the result (default: path only).",
    ),
    json_output: bool = json_option(),
    schema: bool = SCREEN_CAPTURE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Capture a single frame of the running game's viewport (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017): the
    harness reads the viewport texture, PNG-encodes it, and returns it base64 in the
    sentinel; the CLI decodes it and WRITES the PNG to `--output`, returning the path
    + dims + bytes + format. `--inline` also embeds the base64. Needs a WINDOWED
    session (`gda daemon start --windowed`); a headless one is
    `live_display_unavailable`. With no daemon it reports `daemon_not_running`.
    """
    # Build the params model from the argv options so `output` is validated and
    # ~-normalized through the SAME single source of truth the --params-json path
    # uses (ADR-0015/ADR-0006) — not a raw, un-normalized Path. Dispatch through the
    # descriptor's recipe, exactly as the --params-json path does (ADR-0023).
    _dispatch_recipe(
        SCREEN_CAPTURE_COMMAND,
        ScreenCaptureParams(output=str(output), inline=inline),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@screen_app.command(name="frames", cls=SCREEN_FRAMES_COMMAND.command_class())
def screen_frames(
    frames: int = typer.Option(
        2,
        "--frames",
        min=1,
        max=MAX_WINDOW_FRAMES,
        help=(
            f"The number of viewport frames to capture, 1..{MAX_WINDOW_FRAMES} (the "
            "gda harness's per-window ceiling)."
        ),
    ),
    output_dir: Path = typer.Option(
        ...,
        "--output-dir",
        "-d",
        help="The directory to write the captured PNG frames into (frame_NNNN.png).",
    ),
    json_output: bool = json_option(),
    schema: bool = SCREEN_FRAMES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Capture a window of viewport frames in one blocking call (live, time-windowed).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017) and
    collects one frame per frame boundary over `--frames` frames, returned as one
    blocking payload (ADR-0017 one-shot RPC, ADR-0020 multi-frame). Each frame's PNG
    is written into `--output-dir` (path-only — an N-frame base64 sequence would blow
    the agent's context). Needs a WINDOWED session; a headless one is
    `live_display_unavailable`. With no daemon it reports `daemon_not_running`.
    """
    # Same params model the --params-json path builds (ADR-0015): `output_dir` is
    # validated and ~-normalized through it, not passed as a raw Path. Dispatch
    # through the descriptor's recipe, exactly as the --params-json path (ADR-0023).
    _dispatch_recipe(
        SCREEN_FRAMES_COMMAND,
        ScreenFramesParams(frames=frames, output_dir=str(output_dir)),
        json_output=json_output,
        godot=godot,
        project=project,
    )


SCENE_CREATE_COMMAND: HeadlessCommand[SceneCreateResult] = HeadlessCommand(
    operation="scene-create",
    input_model=SceneCreateParams,
    output_model=SceneCreateResult,
    render=render_scene_metadata,
)

SCENE_GET_COMMAND: HeadlessCommand[SceneGetResult] = HeadlessCommand(
    operation="scene-get",
    input_model=SceneGetParams,
    output_model=SceneGetResult,
    render=render_scene_tree,
)

SCENE_GET_EXPORTS_COMMAND: HeadlessCommand[SceneGetExportsResult] = HeadlessCommand(
    operation="scene-get-exports",
    input_model=SceneGetExportsParams,
    output_model=SceneGetExportsResult,
    render=render_scene_exports,
)

SCENE_LIST_COMMAND: HeadlessCommand[SceneListResult] = HeadlessCommand(
    operation="scene-list",
    input_model=SceneListParams,
    output_model=SceneListResult,
    render=render_scene_list,
)

SCENE_DELETE_COMMAND: HeadlessCommand[SceneDeleteResult] = HeadlessCommand(
    operation="scene-delete",
    input_model=SceneDeleteParams,
    output_model=SceneDeleteResult,
    render=render_scene_delete,
)

NODE_ADD_COMMAND: HeadlessCommand[NodeAddResult] = HeadlessCommand(
    operation="node-add",
    input_model=NodeAddParams,
    output_model=NodeAddResult,
    render=render_node_add,
)

NODE_LIST_COMMAND: HeadlessCommand[NodeListResult] = HeadlessCommand(
    operation="node-list",
    input_model=NodeListParams,
    output_model=NodeListResult,
    render=render_node_list,
)

NODE_GET_COMMAND: HeadlessCommand[NodeGetResult] = HeadlessCommand(
    operation="node-get",
    input_model=NodeGetParams,
    output_model=NodeGetResult,
    render=render_node_properties,
)

NODE_SET_COMMAND: HeadlessCommand[NodeSetResult] = HeadlessCommand(
    operation="node-set",
    input_model=NodeSetParams,
    output_model=NodeSetResult,
    render=render_node_set,
)

NODE_REMOVE_COMMAND: HeadlessCommand[NodeRemoveResult] = HeadlessCommand(
    operation="node-remove",
    input_model=NodeRemoveParams,
    output_model=NodeRemoveResult,
    render=render_node_remove,
)

NODE_DUPLICATE_COMMAND: HeadlessCommand[NodeDuplicateResult] = HeadlessCommand(
    operation="node-duplicate",
    input_model=NodeDuplicateParams,
    output_model=NodeDuplicateResult,
    render=render_node_duplicate,
)

NODE_MOVE_COMMAND: HeadlessCommand[NodeMoveResult] = HeadlessCommand(
    operation="node-move",
    input_model=NodeMoveParams,
    output_model=NodeMoveResult,
    render=render_node_move,
)

NODE_CONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeConnectSignalResult] = HeadlessCommand(
    operation="node-connect-signal",
    input_model=NodeConnectSignalParams,
    output_model=NodeConnectSignalResult,
    render=render_node_connect_signal,
)

NODE_DISCONNECT_SIGNAL_COMMAND: HeadlessCommand[NodeDisconnectSignalResult] = (
    HeadlessCommand(
        operation="node-disconnect-signal",
        input_model=NodeDisconnectSignalParams,
        output_model=NodeDisconnectSignalResult,
        render=render_node_disconnect_signal,
    )
)

SCRIPT_CREATE_COMMAND: HeadlessCommand[ScriptCreateResult] = HeadlessCommand(
    operation="script-create",
    input_model=ScriptCreateParams,
    output_model=ScriptCreateResult,
    render=render_script_create,
)

SCRIPT_GET_COMMAND: HeadlessCommand[ScriptGetResult] = HeadlessCommand(
    operation="script-get",
    input_model=ScriptGetParams,
    output_model=ScriptGetResult,
    render=render_script_get,
)

SCRIPT_LIST_COMMAND: HeadlessCommand[ScriptListResult] = HeadlessCommand(
    operation="script-list",
    input_model=ScriptListParams,
    output_model=ScriptListResult,
    render=render_script_list,
)

SCRIPT_DELETE_COMMAND: HeadlessCommand[ScriptDeleteResult] = HeadlessCommand(
    operation="script-delete",
    input_model=ScriptDeleteParams,
    output_model=ScriptDeleteResult,
    render=render_script_delete,
)

SCRIPT_SET_COMMAND: HeadlessCommand[ScriptSetResult] = HeadlessCommand(
    operation="script-set",
    input_model=ScriptSetParams,
    output_model=ScriptSetResult,
    render=render_script_set,
)

SCRIPT_ATTACH_COMMAND: HeadlessCommand[ScriptAttachResult] = HeadlessCommand(
    operation="script-attach",
    input_model=ScriptAttachParams,
    output_model=ScriptAttachResult,
    render=render_script_attach,
)

SCRIPT_VALIDATE_COMMAND: HeadlessCommand[ScriptValidateResult] = HeadlessCommand(
    operation="script-validate",
    input_model=ScriptValidateParams,
    output_model=ScriptValidateResult,
    render=render_script_validate,
    classify=classify_script_validate,
)

RESOURCE_CREATE_COMMAND: HeadlessCommand[ResourceCreateResult] = HeadlessCommand(
    operation="resource-create",
    input_model=ResourceCreateParams,
    output_model=ResourceCreateResult,
    render=render_resource_create,
)

RESOURCE_GET_COMMAND: HeadlessCommand[ResourceGetResult] = HeadlessCommand(
    operation="resource-get",
    input_model=ResourceGetParams,
    output_model=ResourceGetResult,
    render=render_resource_properties,
)

RESOURCE_SET_COMMAND: HeadlessCommand[ResourceSetResult] = HeadlessCommand(
    operation="resource-set",
    input_model=ResourceSetParams,
    output_model=ResourceSetResult,
    render=render_resource_set,
)

RESOURCE_DELETE_COMMAND: HeadlessCommand[ResourceDeleteResult] = HeadlessCommand(
    operation="resource-delete",
    input_model=ResourceDeleteParams,
    output_model=ResourceDeleteResult,
    render=render_resource_delete,
)

EXPORT_LIST_COMMAND: HeadlessCommand[ExportListResult] = HeadlessCommand(
    operation="export-list",
    input_model=ExportListParams,
    output_model=ExportListResult,
    render=render_export_list,
)

# EXPORT_GET_COMMAND lives in gda.export_run (imported above), co-located with
# run_export_operation, which drives export-get to resolve the preset without an
# export_run ↔ cli import cycle (issue #187). EXPORT_RUN_COMMAND is defined above in
# this module instead (its recipe needs cli's runner seams, ADR-0023).

RESOURCE_UID_COMMAND: HeadlessCommand[ResourceUidResult] = HeadlessCommand(
    operation="resource-uid",
    input_model=ResourceUidParams,
    output_model=ResourceUidResult,
    render=render_resource_uid,
)

PROJECT_INFO_COMMAND: HeadlessCommand[ProjectInfoResult] = HeadlessCommand(
    operation="project-info",
    input_model=ProjectInfoParams,
    output_model=ProjectInfoResult,
    render=render_project_info,
)

PROJECT_GET_COMMAND: HeadlessCommand[ProjectGetResult] = HeadlessCommand(
    operation="project-get",
    input_model=ProjectGetParams,
    output_model=ProjectGetResult,
    render=render_project_get,
)

PROJECT_LIST_COMMAND: HeadlessCommand[ProjectListResult] = HeadlessCommand(
    operation="project-list",
    input_model=ProjectListParams,
    output_model=ProjectListResult,
    render=render_project_list,
)

PROJECT_SET_COMMAND: HeadlessCommand[ProjectSetResult] = HeadlessCommand(
    operation="project-set",
    input_model=ProjectSetParams,
    output_model=ProjectSetResult,
    render=render_project_set,
)

PROJECT_ADD_AUTOLOAD_COMMAND: HeadlessCommand[ProjectAddAutoloadResult] = (
    HeadlessCommand(
        operation="project-add-autoload",
        input_model=ProjectAddAutoloadParams,
        output_model=ProjectAddAutoloadResult,
        render=render_project_add_autoload,
    )
)

PROJECT_REMOVE_AUTOLOAD_COMMAND: HeadlessCommand[ProjectRemoveAutoloadResult] = (
    HeadlessCommand(
        operation="project-remove-autoload",
        input_model=ProjectRemoveAutoloadParams,
        output_model=ProjectRemoveAutoloadResult,
        render=render_project_remove_autoload,
    )
)

PROJECT_ADD_INPUT_ACTION_COMMAND: HeadlessCommand[ProjectAddInputActionResult] = (
    HeadlessCommand(
        operation="project-add-input-action",
        input_model=ProjectAddInputActionParams,
        output_model=ProjectAddInputActionResult,
        render=render_project_add_input_action,
    )
)

PROJECT_REMOVE_INPUT_ACTION_COMMAND: HeadlessCommand[ProjectRemoveInputActionResult] = (
    HeadlessCommand(
        operation="project-remove-input-action",
        input_model=ProjectRemoveInputActionParams,
        output_model=ProjectRemoveInputActionResult,
        render=render_project_remove_input_action,
    )
)

SHADER_CREATE_COMMAND: HeadlessCommand[ShaderCreateResult] = HeadlessCommand(
    operation="shader-create",
    input_model=ShaderCreateParams,
    output_model=ShaderCreateResult,
    render=render_shader_create,
)

SHADER_GET_COMMAND: HeadlessCommand[ShaderGetResult] = HeadlessCommand(
    operation="shader-get",
    input_model=ShaderGetParams,
    output_model=ShaderGetResult,
    render=render_shader_get,
)

SHADER_SET_COMMAND: HeadlessCommand[ShaderSetResult] = HeadlessCommand(
    operation="shader-set",
    input_model=ShaderSetParams,
    output_model=ShaderSetResult,
    render=render_shader_set,
)

THEME_CREATE_COMMAND: HeadlessCommand[ThemeCreateResult] = HeadlessCommand(
    operation="theme-create",
    input_model=ThemeCreateParams,
    output_model=ThemeCreateResult,
    render=render_theme_create,
)

PROJECT_FIND_REFERENCES_COMMAND: HeadlessCommand[ProjectFindReferencesResult] = (
    HeadlessCommand(
        operation="project-find-references",
        input_model=ProjectFindReferencesParams,
        output_model=ProjectFindReferencesResult,
        render=render_project_find_references,
    )
)

PROJECT_DEPENDENCIES_COMMAND: HeadlessCommand[ProjectDependenciesResult] = (
    HeadlessCommand(
        operation="project-dependencies",
        input_model=ProjectDependenciesParams,
        output_model=ProjectDependenciesResult,
        render=render_project_dependencies,
    )
)

PROJECT_FIND_UNUSED_RESOURCES_COMMAND: HeadlessCommand[
    ProjectFindUnusedResourcesResult
] = HeadlessCommand(
    operation="project-find-unused-resources",
    input_model=ProjectFindUnusedResourcesParams,
    output_model=ProjectFindUnusedResourcesResult,
    render=render_project_find_unused_resources,
)

PROJECT_STATISTICS_COMMAND: HeadlessCommand[ProjectStatisticsResult] = HeadlessCommand(
    operation="project-statistics",
    input_model=ProjectStatisticsParams,
    output_model=ProjectStatisticsResult,
    render=render_project_statistics,
)


# Path normalization lives in the models (ADR-0015) via the NormalizedPath field
# type, the single home shared by the argv and ``--params-json`` paths — every
# command's body (``export run`` included, since ADR-0023 routed it through a built
# ``ExportRunParams``) passes its raw path straight to the params model, which
# ~-expands it. There is no CLI-layer normalization step left to share.


@scene_app.command(cls=SCENE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tscn path to write."),
    root_type: str = typer.Option(
        ...,
        "--root-type",
        help="Godot node class of the new scene's root (e.g. Node2D).",
    ),
    root_name: Optional[str] = typer.Option(
        None,
        "--root-name",
        help=(
            "Root node name to write. Defaults to the target filename without "
            "its final extension."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCENE_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tscn scene file with the given root node type."""
    # Normalization + root-name derivation live in SceneCreateParams (ADR-0015),
    # so this body is a thin argv→model adapter and the --params-json path agrees.
    _dispatch(
        SCENE_CREATE_COMMAND,
        SceneCreateParams(path=path, root_type=root_type, root_name=root_name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@scene_app.command(cls=SCENE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a scene file and report its structured node tree."""
    _dispatch(
        SCENE_GET_COMMAND,
        SceneGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@scene_app.command(name="get-exports", cls=SCENE_GET_EXPORTS_COMMAND.command_class())
def get_exports(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = SCENE_GET_EXPORTS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the @export properties a scene's nodes' scripts declare, per node path."""
    _dispatch(
        SCENE_GET_EXPORTS_COMMAND,
        SceneGetExportsParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@scene_app.command(name="list", cls=SCENE_LIST_COMMAND.command_class())
def list_scenes(
    json_output: bool = json_option(),
    schema: bool = SCENE_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .tscn scenes in the resolved project."""
    _dispatch(
        SCENE_LIST_COMMAND,
        SceneListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@scene_app.command(cls=SCENE_DELETE_COMMAND.command_class())
def delete(
    path: str = typer.Argument(..., help="The .tscn scene file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCENE_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a scene file and report what was removed."""
    _dispatch(
        SCENE_DELETE_COMMAND,
        SceneDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(cls=NODE_ADD_COMMAND.command_class())
def add(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node_type: str = typer.Option(
        ...,
        "--type",
        help=(
            "Node type to add: a Godot node class (e.g. Sprite2D), or a "
            "class_name registered in the project's global class list."
        ),
    ),
    parent: str = typer.Option(
        ".",
        "--parent",
        help=(
            "Parent node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Name for the new node. Defaults to the type name.",
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_ADD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Add a node to a scene file under the given parent node path."""
    _dispatch(
        NODE_ADD_COMMAND,
        NodeAddParams(
            path=path,
            parent=parent,
            type=node_type,
            name=name,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(name="list", cls=NODE_LIST_COMMAND.command_class())
def list_nodes(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    json_output: bool = json_option(),
    schema: bool = NODE_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List a scene's node tree with each node's path relative to the root."""
    _dispatch(
        NODE_LIST_COMMAND,
        NodeListParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(cls=NODE_GET_COMMAND.command_class())
def get(
    path: str = typer.Argument(..., help="The .tscn scene file to read."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a node's properties (by node path) as typed JSON."""
    _dispatch(
        NODE_GET_COMMAND,
        NodeGetParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(name="set", cls=NODE_SET_COMMAND.command_class())
def set_property(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    property: str = typer.Option(
        ..., "--property", help="The property to set (e.g. position, visible)."
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "Godot type: Vector2/Vector2i/Color take comma-separated components "
            '(e.g. "48,72", "0.2,0.6,1,1"), and a property expecting a Resource '
            "(sub)class takes a res:// path to an existing Resource of that class. "
            "An uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a node property, coercing the value to its declared Godot type."""
    _dispatch(
        NODE_SET_COMMAND,
        NodeSetParams(path=path, node=node, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(name="remove", cls=NODE_REMOVE_COMMAND.command_class())
def remove_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to delete, relative to the scene root: "
            "'Player/Arm' a nested node. The root ('.') cannot be removed."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_REMOVE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Remove a node (and its subtree) from a scene file by node path."""
    _dispatch(
        NODE_REMOVE_COMMAND,
        NodeRemoveParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(name="duplicate", cls=NODE_DUPLICATE_COMMAND.command_class())
def duplicate_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to copy, relative to the scene root: "
            "'Player/Arm' a nested node. The copy lands under this node's own "
            "parent with a fresh name. The root ('.') cannot be duplicated."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_DUPLICATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Duplicate a node (and its subtree) under its parent with a fresh name."""
    _dispatch(
        NODE_DUPLICATE_COMMAND,
        NodeDuplicateParams(path=path, node=node),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(name="move", cls=NODE_MOVE_COMMAND.command_class())
def move_node(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path of the node to reparent, relative to the scene root: "
            "'Player/Arm' a nested node. The root ('.') cannot be moved."
        ),
    ),
    to: str = typer.Option(
        ...,
        "--to",
        help=(
            "Node path of the new parent, relative to the scene root: '.' "
            "addresses the root itself, 'Enemies' a nested node. Must not be the "
            "moved node or one of its descendants (a cyclic target)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = NODE_MOVE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Reparent a node (and its subtree) under a new parent node path."""
    _dispatch(
        NODE_MOVE_COMMAND,
        NodeMoveParams(path=path, node=node, to=to),
        json_output=json_output,
        godot=godot,
        project=project,
    )


# The four connection flags reused by both connect-signal and disconnect-signal.
# Defined once so the source/target node-path addressing and the signal/method
# naming stay identical across the wire and unwire commands.
def _from_option() -> str:
    return typer.Option(
        ...,
        "--from",
        help=(
            "Source node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )


def _signal_option() -> str:
    return typer.Option(..., "--signal", help="The signal name on the source node.")


def _to_option() -> str:
    return typer.Option(
        ...,
        "--to",
        help=(
            "Target node path, relative to the scene root: '.' addresses the "
            "root itself, 'Player/Arm' a nested node."
        ),
    )


def _method_option() -> str:
    return typer.Option(..., "--method", help="The method name on the target node.")


@node_app.command(
    name="connect-signal", cls=NODE_CONNECT_SIGNAL_COMMAND.command_class()
)
def connect_signal(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    from_node: str = _from_option(),
    signal: str = _signal_option(),
    to: str = _to_option(),
    method: str = _method_option(),
    json_output: bool = json_option(),
    schema: bool = NODE_CONNECT_SIGNAL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Wire a source node's signal to a target node's method, persisted in the scene."""
    _dispatch(
        NODE_CONNECT_SIGNAL_COMMAND,
        NodeConnectSignalParams(
            path=path,
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@node_app.command(
    name="disconnect-signal", cls=NODE_DISCONNECT_SIGNAL_COMMAND.command_class()
)
def disconnect_signal(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    from_node: str = _from_option(),
    signal: str = _signal_option(),
    to: str = _to_option(),
    method: str = _method_option(),
    json_output: bool = json_option(),
    schema: bool = NODE_DISCONNECT_SIGNAL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unwire an existing signal→method connection; errors if it is absent."""
    _dispatch(
        NODE_DISCONNECT_SIGNAL_COMMAND,
        NodeDisconnectSignalParams(
            path=path,
            from_node=from_node,
            signal=signal,
            to=to,
            method=method,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(cls=SCRIPT_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gd script path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim script source to write. Mutually exclusive with --extends; "
            "when omitted, a minimal template extending --extends is written."
        ),
    ),
    extends_type: Optional[str] = typer.Option(
        None,
        "--extends",
        help=(
            "Base class for the built-in template's 'extends' line (e.g. Node, "
            "Node2D). Defaults to Node. Ignored — and rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gd script from a template or verbatim --content."""
    if content is not None and extends_type is not None:
        raise typer.BadParameter("--content and --extends are mutually exclusive.")
    _dispatch(
        SCRIPT_CREATE_COMMAND,
        ScriptCreateParams(
            path=path,
            content=content,
            extends_type=extends_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="get", cls=SCRIPT_GET_COMMAND.command_class())
def get_script(
    path: str = typer.Argument(..., help="The .gd script file to read."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a script's source and report its class_name/extends metadata."""
    _dispatch(
        SCRIPT_GET_COMMAND,
        ScriptGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="list", cls=SCRIPT_LIST_COMMAND.command_class())
def list_scripts(
    json_output: bool = json_option(),
    schema: bool = SCRIPT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .gd scripts in the resolved project."""
    _dispatch(
        SCRIPT_LIST_COMMAND,
        ScriptListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="delete", cls=SCRIPT_DELETE_COMMAND.command_class())
def delete_script(
    path: str = typer.Argument(..., help="The .gd script file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a script file and report what was removed."""
    _dispatch(
        SCRIPT_DELETE_COMMAND,
        ScriptDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="set", cls=SCRIPT_SET_COMMAND.command_class())
def set_script(
    path: str = typer.Argument(..., help="The .gd script file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gd script via search-replace, line-range, or full overwrite."""
    mode = _resolve_set_mode(search, replace, start_line, end_line, content)
    _dispatch(
        SCRIPT_SET_COMMAND,
        ScriptSetParams(
            path=path,
            mode=mode,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def _resolve_set_mode(
    search: Optional[str],
    replace: Optional[str],
    start_line: Optional[int],
    end_line: Optional[int],
    content: Optional[str],
) -> ScriptSetMode:
    """Resolve a set command's edit mode for the argv path (issue #133).

    The rule itself lives in :func:`gda.models.resolve_set_mode` — the single
    source shared with ``ScriptSetParams`` / ``ShaderSetParams`` (ADR-0015). This
    thin wrapper translates its ``ValueError`` into a Click usage error (exit 2)
    so the argv path keeps its usage-error ergonomics, while ``--params-json``
    surfaces the same rule as a structured ``invalid_params`` via the model.
    """
    try:
        return resolve_set_mode(search, replace, start_line, end_line, content)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@script_app.command(name="attach", cls=SCRIPT_ATTACH_COMMAND.command_class())
def attach_script(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    script: str = typer.Option(
        ..., "--script", help="The .gd script file to attach to the node."
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_ATTACH_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Attach a .gd script to a node (by node path) in a scene and save."""
    _dispatch(
        SCRIPT_ATTACH_COMMAND,
        ScriptAttachParams(
            path=path,
            node=node,
            script=script,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="validate", cls=SCRIPT_VALIDATE_COMMAND.command_class())
def validate_script(
    path: str = typer.Argument(..., help="The .gd script file to validate."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_VALIDATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Syntax/compile-check a .gd script; an invalid script is a successful op."""
    _dispatch(
        SCRIPT_VALIDATE_COMMAND,
        ScriptValidateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@script_app.command(name="run", cls=SCRIPT_RUN_COMMAND.command_class())
def run_script(
    path: str = typer.Argument(
        ...,
        help="The res:// path of the script to run (e.g. res://tests/logic.gd).",
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_RUN_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Run a user script one-shot and pass its exit_status/stdout/stderr through.

    Runs the user's own res:// script as ``godot --headless --path <project>
    --script <res://…>`` and returns its result verbatim (ADR-0031). This is the
    ONE command whose success result can carry a non-zero ``exit_status``: gda does
    not interpret the script's semantics, so a deliberate ``quit(1)`` (e.g. an
    assertion-failed logic-seam test) is data the agent reads, not a gda failure —
    read ``exit_status``, do not assume ``success == zero``. Only a gda-/engine-level
    failure (binary not launchable, timeout, or a signal crash) is an Error envelope
    (``binary_not_found`` / ``launch_timeout`` / ``engine_crashed``). A non-res://
    path or no resolved project is a structured ``invalid_path`` / ``project_not_found``.
    """
    _dispatch_recipe(
        SCRIPT_RUN_COMMAND,
        ScriptRunParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@resource_app.command(cls=RESOURCE_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .tres resource path to write."),
    resource_type: str = typer.Option(
        ...,
        "--type",
        help=(
            "Resource type of the new .tres: a built-in Resource class (e.g. "
            "Gradient, Curve) or a registered Resource class_name (a GDScript "
            "class_name Foo extends Resource)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .tres resource file of the given resource type."""
    _dispatch(
        RESOURCE_CREATE_COMMAND,
        ResourceCreateParams(path=path, type=resource_type),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(name="info", cls=PROJECT_INFO_COMMAND.command_class())
def project_info(
    json_output: bool = json_option(),
    schema: bool = PROJECT_INFO_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the resolved project's metadata (name, main scene, viewport, engine)."""
    _dispatch(
        PROJECT_INFO_COMMAND,
        ProjectInfoParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(name="get", cls=PROJECT_GET_COMMAND.command_class())
def project_get(
    setting: str = typer.Argument(
        ...,
        help="The project setting's full section/key name (e.g. application/config/name).",
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a single project setting by section/key as typed JSON."""
    _dispatch(
        PROJECT_GET_COMMAND,
        ProjectGetParams(setting=setting),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(name="list", cls=PROJECT_LIST_COMMAND.command_class())
def project_list(
    all_settings: bool = typer.Option(
        False,
        "--all",
        help=(
            "Also list the engine's built-in default settings, not just the "
            "project's customized ones."
        ),
    ),
    section: Optional[str] = typer.Option(
        None,
        "--section",
        help=(
            "Restrict to keys whose name begins with this section/ prefix "
            "(e.g. application/, display/)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """List the project's settings keys (customized only by default; --all adds defaults)."""
    _dispatch(
        PROJECT_LIST_COMMAND,
        ProjectListParams(include_defaults=all_settings, section=section),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="find-references", cls=PROJECT_FIND_REFERENCES_COMMAND.command_class()
)
def find_references(
    target: str = typer.Argument(
        ...,
        help=(
            "What to find references to: a resource's res:// path (scene, "
            "script, image, .tres, …) or a script class_name."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_REFERENCES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find every project file that references a given resource path or class_name."""
    _dispatch(
        PROJECT_FIND_REFERENCES_COMMAND,
        ProjectFindReferencesParams(target=target),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@shader_app.command(cls=SHADER_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gdshader path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim shader source to write. Mutually exclusive with "
            "--shader-type; when omitted, a minimal template declaring the "
            "--shader-type is written."
        ),
    ),
    shader_type: Optional[str] = typer.Option(
        None,
        "--shader-type",
        help=(
            "Shader type for the built-in template's 'shader_type' line (e.g. "
            "canvas_item, spatial). Defaults to canvas_item. Ignored — and "
            "rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gdshader from a template or verbatim --content."""
    if content is not None and shader_type is not None:
        raise typer.BadParameter("--content and --shader-type are mutually exclusive.")
    _dispatch(
        SHADER_CREATE_COMMAND,
        ShaderCreateParams(
            path=path,
            content=content,
            shader_type=shader_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@resource_app.command(name="get", cls=RESOURCE_GET_COMMAND.command_class())
def get_resource(
    path: str = typer.Argument(..., help="The .tres resource file to read."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a .tres resource and report its properties as typed JSON."""
    _dispatch(
        RESOURCE_GET_COMMAND,
        ResourceGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@resource_app.command(name="set", cls=RESOURCE_SET_COMMAND.command_class())
def set_resource(
    path: str = typer.Argument(..., help="The .tres resource file to mutate."),
    property: str = typer.Option(
        ...,
        "--property",
        help="The resource property to set (e.g. interpolation_mode).",
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "Godot type: Vector2/Vector2i/Color take comma-separated components "
            '(e.g. "48,72", "0.2,0.6,1,1"), and a property expecting a Resource '
            "(sub)class takes a res:// path to an existing Resource of that class. "
            "An uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a .tres property, coercing the value to its declared Godot type, then save."""
    _dispatch(
        RESOURCE_SET_COMMAND,
        ResourceSetParams(path=path, property=property, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@resource_app.command(name="delete", cls=RESOURCE_DELETE_COMMAND.command_class())
def delete_resource(
    path: str = typer.Argument(..., help="The .tres resource file to delete."),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a .tres resource file and report what was removed."""
    _dispatch(
        RESOURCE_DELETE_COMMAND,
        ResourceDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@shader_app.command(name="get", cls=SHADER_GET_COMMAND.command_class())
def get_shader(
    path: str = typer.Argument(..., help="The .gdshader file to read."),
    json_output: bool = json_option(),
    schema: bool = SHADER_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a shader's source and report its shader_type metadata."""
    _dispatch(
        SHADER_GET_COMMAND,
        ShaderGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="dependencies", cls=PROJECT_DEPENDENCIES_COMMAND.command_class()
)
def dependencies(
    json_output: bool = json_option(),
    schema: bool = PROJECT_DEPENDENCIES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Map each scene/resource in the project to the resources it references."""
    _dispatch(
        PROJECT_DEPENDENCIES_COMMAND,
        ProjectDependenciesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@export_app.command(name="list", cls=EXPORT_LIST_COMMAND.command_class())
def list_presets(
    json_output: bool = json_option(),
    schema: bool = EXPORT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the resolved project's export presets (name, platform, runnable)."""
    _dispatch(
        EXPORT_LIST_COMMAND,
        ExportListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="find-unused-resources",
    cls=PROJECT_FIND_UNUSED_RESOURCES_COMMAND.command_class(),
)
def find_unused_resources(
    json_output: bool = json_option(),
    schema: bool = PROJECT_FIND_UNUSED_RESOURCES_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Find resource files that nothing references (built on the reference graph)."""
    _dispatch(
        PROJECT_FIND_UNUSED_RESOURCES_COMMAND,
        ProjectFindUnusedResourcesParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@export_app.command(name="get", cls=EXPORT_GET_COMMAND.command_class())
def get_preset(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report one preset's details plus export-template install status."""
    _dispatch(
        EXPORT_GET_COMMAND,
        ExportGetParams(preset=preset),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@export_app.command(name="run", cls=EXPORT_RUN_COMMAND.command_class())
def run_export(
    preset: str = typer.Option(
        ...,
        "--preset",
        help="The export preset's display name, as 'gda export list' reports it.",
    ),
    # --mode (#170): select the export flavor. A closed Enum so an unrecognized
    # value is a Typer usage error (exit 2) rather than reaching the runner;
    # release is the default, preserving #121's behavior when --mode is omitted.
    mode: ExportRunMode = typer.Option(
        ExportRunMode.RELEASE,
        "--mode",
        help="The export flavor to run (release/debug/pack); default release.",
    ),
    # --output (#170): override the preset's configured export_path. A filesystem
    # path normalized ONCE at the CLI layer (ADR-0006: ~ expanded), like every
    # other path-taking command.
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help="Override the preset's configured export_path; write the artifact here instead.",
    ),
    json_output: bool = json_option(),
    schema: bool = EXPORT_RUN_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Export a named preset to a destination and report the artifact.

    Unlike every other command, the export itself is a native ``--export-<mode>``
    invocation (the export subsystem is editor-only, so it cannot run through
    operations.gd). The recipe — ``export get`` resolves the preset's platform +
    configured ``export_path`` + template readiness (reusing #114's clean
    preset/project errors), a structured preflight fails fast when templates are
    missing or there is no destination, then the native ``ExportRunner`` performs
    the export and ``classify_export_run`` synthesizes the typed result from the
    subprocess's exit code — is owned by :func:`gda.export_run.run_export_operation`
    (issue #187), so this command is the same thin shape as every other: build
    params → invoke the operation → emit.

    ``--mode`` selects the export flavor (release/debug/pack; default release) and
    ``--output`` overrides the preset's configured ``export_path``; both are
    reflected in the native invocation and the reported result (#170).
    """
    # Build the params model from the argv options (the single source of truth,
    # ADR-0015): ExportRunParams.output is a NormalizedPath, so the model ~-expands
    # it (ADR-0006) — argv and --params-json normalize identically. Dispatch through
    # the descriptor's recipe (ADR-0023), exactly like every other recipe command.
    _dispatch_recipe(
        EXPORT_RUN_COMMAND,
        ExportRunParams(preset=preset, mode=mode, output=output),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@resource_app.command(name="uid", cls=RESOURCE_UID_COMMAND.command_class())
def resolve_uid(
    target: str = typer.Argument(
        ...,
        help=(
            "A 'uid://…' value to resolve to its res:// path, or a 'res://…' / "
            "filesystem path to resolve to its 'uid://…'. The direction is chosen "
            "by whether the target begins with 'uid://'."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = RESOURCE_UID_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Resolve a resource UID to/from its res:// path via the engine's UID cache."""
    _dispatch(
        RESOURCE_UID_COMMAND,
        ResourceUidParams(target=target),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@shader_app.command(name="set", cls=SHADER_SET_COMMAND.command_class())
def set_shader(
    path: str = typer.Argument(..., help="The .gdshader file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SHADER_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gdshader via search-replace, line-range, or full overwrite."""
    # shader set reuses the script set edit-mode interface (issue #115): the same
    # mutual-exclusion resolver decides the single ScriptSetMode discriminator.
    mode = _resolve_set_mode(search, replace, start_line, end_line, content)
    _dispatch(
        SHADER_SET_COMMAND,
        ShaderSetParams(
            path=path,
            mode=mode,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(name="set", cls=PROJECT_SET_COMMAND.command_class())
def project_set(
    setting: str = typer.Argument(
        ...,
        help="The project setting's full section/key name (e.g. application/config/name).",
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the setting's declared "
            "Godot type; an uncoercible value is a clean error."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Set a project setting, coercing the value to its declared Godot type, then save."""
    _dispatch(
        PROJECT_SET_COMMAND,
        ProjectSetParams(setting=setting, value=value),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="add-autoload", cls=PROJECT_ADD_AUTOLOAD_COMMAND.command_class()
)
def project_add_autoload(
    name: str = typer.Argument(
        ..., help="The autoload singleton's global name (the autoload/<name> key)."
    ),
    path: str = typer.Argument(
        ...,
        help="The res:// path to the script or scene to autoload (e.g. res://global.gd).",
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_ADD_AUTOLOAD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Register an autoload singleton (name → script/scene path), then save project.godot."""
    _dispatch(
        PROJECT_ADD_AUTOLOAD_COMMAND,
        ProjectAddAutoloadParams(name=name, path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="remove-autoload", cls=PROJECT_REMOVE_AUTOLOAD_COMMAND.command_class()
)
def project_remove_autoload(
    name: str = typer.Argument(
        ..., help="The global name of the autoload singleton to unregister."
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_REMOVE_AUTOLOAD_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unregister an autoload singleton by name, then save project.godot."""
    _dispatch(
        PROJECT_REMOVE_AUTOLOAD_COMMAND,
        ProjectRemoveAutoloadParams(name=name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="add-input-action", cls=PROJECT_ADD_INPUT_ACTION_COMMAND.command_class()
)
def project_add_input_action(
    name: str = typer.Argument(
        ..., help="The input action's name (the input/<name> key)."
    ),
    keys: list[str] = typer.Option(
        ...,
        "--key",
        help=(
            "A key to bind (repeatable, at least one): a Godot key name "
            "(e.g. J, Space, Escape) or a base-10 keycode integer."
        ),
    ),
    deadzone: float = typer.Option(
        0.5,
        "--deadzone",
        help="The action's deadzone, 0..1 (Godot's default is 0.5).",
    ),
    physical: bool = typer.Option(
        False,
        "--physical",
        help=(
            "Bind physical keycodes (keyboard position, layout-independent) "
            "instead of layout keycodes."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PROJECT_ADD_INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Register an InputMap action bound to one or more keys, then save project.godot."""
    try:
        params = ProjectAddInputActionParams(
            name=name, keys=keys, deadzone=deadzone, physical=physical
        )
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _dispatch(
        PROJECT_ADD_INPUT_ACTION_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(
    name="remove-input-action", cls=PROJECT_REMOVE_INPUT_ACTION_COMMAND.command_class()
)
def project_remove_input_action(
    name: str = typer.Argument(..., help="The name of the input action to unregister."),
    json_output: bool = json_option(),
    schema: bool = PROJECT_REMOVE_INPUT_ACTION_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Unregister an InputMap action by name, then save project.godot."""
    _dispatch(
        PROJECT_REMOVE_INPUT_ACTION_COMMAND,
        ProjectRemoveInputActionParams(name=name),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@theme_app.command(name="create", cls=THEME_CREATE_COMMAND.command_class())
def create_theme(
    path: str = typer.Argument(..., help="Target .tres Theme path to write."),
    json_output: bool = json_option(),
    schema: bool = THEME_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new, loadable .tres Theme resource (no-clobber)."""
    _dispatch(
        THEME_CREATE_COMMAND,
        ThemeCreateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@project_app.command(name="statistics", cls=PROJECT_STATISTICS_COMMAND.command_class())
def statistics(
    json_output: bool = json_option(),
    schema: bool = PROJECT_STATISTICS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Report the project's file/line counts, autoloads and plugins."""
    _dispatch(
        PROJECT_STATISTICS_COMMAND,
        ProjectStatisticsParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@app.command(cls=INFO_COMMAND.command_class())
def info(
    json_output: bool = json_option(),
    schema: bool = INFO_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
) -> None:
    """Report the Godot engine version info."""
    _dispatch_meta(
        INFO_COMMAND,
        InfoParams(),
        json_output=json_output,
        godot=godot,
    )


@app.command(cls=SKILL_COMMAND.command_class())
def skill(
    install: bool = typer.Option(
        False,
        "--install",
        help="Write the bundled SKILL.md into the skills directory instead of printing it.",
    ),
    dir: Optional[str] = typer.Option(
        None,
        "--dir",
        help="The skills directory to install into (caller-supplied; the neutral path, "
        "no default). Implies --install. Mutually exclusive with --provider.",
    ),
    provider: Optional[SkillProvider] = typer.Option(
        None,
        "--provider",
        "-p",
        help="Install into a known agent's skills directory (claude/codex) instead of "
        "--dir, resolved with --scope (ADR-0027). Implies --install.",
    ),
    scope: SkillScope = typer.Option(
        SkillScope.USER,
        "--scope",
        help="With --provider: the agent's per-project (committed) or per-user (all "
        "projects) skills dir; default user.",
    ),
    json_output: bool = json_option(),
    schema: bool = SKILL_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Emit or install the bundled gda Agent Skill (no Godot is spawned).

    The canonical `SKILL.md` ships inside the `gda` package and is version-locked to
    the install (ADR-0024): a plain run prints it verbatim (so
    `gda skill > .../SKILL.md` drops it to disk), `--json` emits
    `{name, version, content}`, and an install writes it to a directory, creating
    parents and overwriting, then reports the path. The install target is named one
    of two ways: `--dir <path>` (the neutral path; core carries no agent-specific
    default, ADR-0024), or `--provider <agent> --scope <scope>` which resolves a known
    agent's skills directory (the opt-in convenience, ADR-0027). A sibling of
    `info`/`schema`, carrying `--schema` like them.
    """
    # The target is named by --dir OR --provider; they name the SAME thing two ways, so
    # both at once is ambiguous, and an install with neither has nowhere to write. Both
    # rules are mirrored in SkillParams (so the --params-json path enforces them too,
    # ADR-0015); resolving provider→dir also happens there. The CLI raises the friendly
    # usage errors and otherwise just forwards the raw flags.
    if dir is not None and provider is not None:
        raise typer.BadParameter(
            "`--dir` and `--provider` are mutually exclusive: name a directory OR an "
            "agent, not both"
        )
    if install and dir is None and provider is None:
        raise typer.BadParameter(
            "`--install` requires `--dir` or `--provider` (where to write the SKILL.md)"
        )
    _dispatch_recipe(
        SKILL_COMMAND,
        SkillParams(install=install, install_dir=dir, provider=provider, scope=scope),
        json_output=json_output,
        godot=None,
        project=None,
    )


@app.command(cls=schema_command_class(SchemaAllParams, SurfaceManifest))
def schema(
    schema: bool = schema_option(),
) -> None:
    """Emit the whole command surface as one JSON manifest; no Godot is spawned.

    The aggregate generalisation of per-command ``--schema`` (ADR-0004/0012):
    one entry per command in every group, each carrying
    ``{name, description, input, output, error}``. gda-mcp introspects this once
    at startup to generate its tool surface, so it stays a faithful mirror of the
    installed ``gda`` with no codegen step. As a meta command (ADR-0005) it is
    top-level and ungrouped, a sibling of ``gda info``.
    """
    typer.echo(build_surface_manifest(app).model_dump_json())
