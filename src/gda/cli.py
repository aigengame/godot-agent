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
from pydantic import ValidationError

from gda import dispatch
from gda.commands import (
    node as node_commands,
    resource as resource_commands,
    scene as scene_commands,
    script as script_commands,
    shader as shader_commands,
    theme as theme_commands,
)
from gda.daemon_ops import (
    run_daemon_start_operation,
    run_daemon_status_operation,
    run_daemon_stop_operation,
    run_daemon_uninstall_operation,
)
from gda.dispatch import _dispatch, _dispatch_meta, _dispatch_recipe
from gda.errors import (
    classify_diag_errors,
    classify_game_get,
    classify_game_rect,
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
)
from gda.execution import ExecutionKind
from gda.export_run import (
    EXPORT_GET_COMMAND,
    run_export_operation,
)
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
    schema_command_class,
    schema_option,
)
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
    GameRectParams,
    GameRectResult,
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
    SchemaAllParams,
    ScreenCaptureParams,
    ScreenCaptureResult,
    ScreenFramesParams,
    ScreenFramesResult,
    SkillParams,
    SkillResult,
    SurfaceManifest,
)
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
    render_game_rect,
    render_game_set,
    render_game_tree,
    render_input_action,
    render_input_key,
    render_input_mouse,
    render_input_sequence,
    render_logger_tail,
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
    render_screen_capture,
    render_screen_frames,
    render_skill,
)
from gda.screen_ops import (
    run_screen_capture_operation,
    run_screen_frames_operation,
)
from gda.skill_ops import build_skill_result
from gda.skill_targets import SkillProvider, SkillScope
from gda.surface import build_surface_manifest

app = typer.Typer(
    name="gda",
    help="An agent-facing Godot CLI with structured output.",
    no_args_is_help=True,
    add_completion=False,
)

# Each moved group owns its sub-app (ADR-0040) and mounts it here, at the same
# point in the sequence the old `add_typer` call occupied, so the registration
# order — and therefore `gda --help` — is unchanged.
scene_commands.register(app)
node_commands.register(app)

script_commands.register(app)

resource_commands.register(app)

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

shader_commands.register(app)

theme_commands.register(app)

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


# --- Recipe channels (ADR-0023) -----------------------------------------------
# Each recipe command (export run / the daemon lifecycle / screen) carries one of
# these on its descriptor (``recipe=``). A recipe PRODUCES the outcome — run the
# CLI-side operation over the ALREADY-resolved ``project`` (resolution happens once
# in :func:`_dispatch_recipe`, kept CLI-side per ADR-0006, so an invalid --project is
# a structured project_not_found before any recipe runs, #353) — and RETURNS the
# typed result or a Failure; emission stays the shared tail (:func:`_dispatch_recipe`
# → ``cmd.render``), so a recipe command renders exactly like a sentinel one. The
# runner seams (``dispatch._make_*``) are referenced at call time — as attributes on
# the module, never imported by name — so test monkeypatches on
# ``gda.dispatch._make_runner`` / ``_make_live_runner`` still bind. ``params`` is the
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
        make_runner=dispatch._make_live_runner,
    )


def _screen_frames_recipe(params, *, project, godot):
    return run_screen_frames_operation(
        project,
        params.frames,
        Path(params.output_dir),
        make_runner=dispatch._make_live_runner,
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
        make_runner=dispatch._make_runner,
        make_export_runner=dispatch._make_export_runner,
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
        help=(
            "If set, read only this property: storage first, then an attached "
            "script variable. Without it, list only the storage surface."
        ),
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
    `live_unknown_property`. A named plain script variable on the node's attached
    script is addressable explicitly after storage properties are checked; unfiltered
    reads keep the storage-property listing and do not dump script variables.
    """
    _dispatch(
        GAME_GET_COMMAND,
        GameGetParams(node=node, property=property),
        json_output=json_output,
        godot=godot,
        project=project,
    )


GAME_RECT_COMMAND: HeadlessCommand[GameRectResult] = HeadlessCommand(
    operation="game-rect",
    input_model=GameRectParams,
    output_model=GameRectResult,
    render=render_game_rect,
    classify=classify_game_rect,
    kind=ExecutionKind.LIVE,
)


@game_app.command(name="rect", cls=GAME_RECT_COMMAND.command_class())
def game_rect(
    node: str = typer.Argument(
        ...,
        help="Runtime Control path as `game tree` reports it (absolute, e.g. /root/Main/HUD).",
    ),
    json_output: bool = json_option(),
    schema: bool = GAME_RECT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a running Control's rendered viewport rect (live).

    Routes through gda-daemon to the engine session's runtime SceneTree
    (kind = LIVE, ADR-0017), addressed by the runtime node path `game tree`
    reports. The returned rect is Control.get_global_rect(): viewport-space
    top-left position and laid-out size. With no daemon it reports
    `daemon_not_running`; a path that resolves to no running node is
    `live_node_not_found`; a non-Control node is `live_not_control`.
    """
    _dispatch(
        GAME_RECT_COMMAND,
        GameRectParams(node=node),
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
        ...,
        "--property",
        help=(
            "The property to set (e.g. position, visible): storage first, then an "
            "attached script variable."
        ),
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "The value to set, as a string. Coerced to the property's declared "
            "or inferred target Godot type (the same coercion `node set` uses, "
            "including JSON objects for Dictionary and JSON arrays for Array); "
            "an uncoercible value is a clean error."
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
    The gda harness coerces `--value` to the property's declared or inferred target
    Godot type — the SAME coercion table `node set` uses — and applies it at a frame
    boundary (ADR-0020); the mutation is bound to the session, not persisted to disk.
    A named plain script variable on the node's attached script is settable explicitly
    after storage properties are checked. The success result includes `verified`:
    true when the observed read-back value equals the coerced requested value,
    false when the set completed but the observed value differs (for example a
    getter-only/no-op variable or an edge-triggered variable). With no daemon it
    reports `daemon_not_running`; an absent node is `live_node_not_found`, an absent
    property `live_unknown_property`, an uncoercible input value `live_uncoercible_value`.
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
    game's root viewport. Read the injected coordinate from the mouse event's
    position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. With no daemon it
    reports `daemon_not_running`.
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
    game's root viewport. Read the injected coordinate from the mouse event's
    position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. With no daemon it
    reports `daemon_not_running`.
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
            "'type' (key/mouse_click/mouse_button/mouse_move/action), either a relative "
            "'frame' harness/process-frame offset or a 'physics_frame' physics-clock "
            "offset, and the type's fields (e.g. "
            '\'[{"type":"mouse_button","x":10,"y":10,"pressed":true},'
            '{"type":"mouse_move","x":40,"y":20,"frame":1},'
            '{"type":"mouse_button","x":40,"y":20,"release":true,"frame":2}]\').'
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
    applies the `--events` across one selected clock, returned as one blocking
    result (reuses #223's time-windowed multi-frame base). Existing `frame` offsets
    are harness/process-frame ticks from the `_process` loop, not Godot physics
    frames. Use `physics_frame` offsets instead when a press/release window must map
    deterministically to physics simulation ticks, e.g. press an action at
    `physics_frame: 0` and release it at `physics_frame: 30` for a 30-physics-frame
    hold. A `mouse_button` press followed by `mouse_move` events and a matching
    `mouse_button` release carries the held-button mask on the motion events for
    drag handlers. For sequence mouse events, read the injected coordinate from the
    mouse event's position; Godot may leave Viewport.get_mouse_position() /
    Node2D.get_global_mouse_position() stale in daemon sessions. A malformed
    `--events` (not a JSON array, an empty list, an
    ill-formed event, or mixed `frame`/`physics_frame` clocks) is a usage error; with
    no daemon it reports `daemon_not_running`. An event's action absent from the
    InputMap is `live_unknown_action`, an unresolvable key `live_invalid_key`.
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
    # --output (#170/#403): override the preset's configured export_path. A
    # filesystem path is normalized ONCE at the params-model layer: ~ expands and
    # relative paths resolve against the invoker's cwd before the native export
    # runner changes cwd to the project.
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help=(
            "Override the preset's configured export_path; relative filesystem "
            "paths resolve against the invoker's current working directory."
        ),
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

    ``--mode`` selects the export flavor (release/debug/pack; default release).
    ``--output`` overrides the preset's configured ``export_path`` and resolves a
    relative filesystem path against the invoker's current working directory;
    preset ``export_path`` values keep Godot's project-relative convention. The
    reported ``output_path`` is the resolved artifact path, and missing output
    parent directories are created and reported in ``created_dirs`` (#402/#403).
    """
    # Build the params model from the argv options (the single source of truth,
    # ADR-0015): ExportRunParams.output is an ExportOutputPath, so argv and
    # --params-json normalize identically. Dispatch through the descriptor's
    # recipe (ADR-0023), exactly like every other recipe command.
    _dispatch_recipe(
        EXPORT_RUN_COMMAND,
        ExportRunParams(preset=preset, mode=mode, output=output),
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
