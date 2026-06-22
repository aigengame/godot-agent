"""Human-readable rendering for ``gda`` results — the presentation layer.

The result models (``gda.models``) are pure ``--schema`` / ``--json`` data
contracts (ADR-0004); presentation does not live in them. This module owns the
human-readable text path: one renderer per result type, selected by result type
via :func:`render`, plus the typed helpers that keep the presentation layer from
reaching into a model's value shape or across a union of result types.

Two seams are deliberately funnelled through one place here:

- **Value-to-text.** A node property's ``value`` is arbitrary JSON (every Godot
  type carried uniformly, :class:`~gda.models.NodeProperty`). :func:`format_value`
  owns the JSON projection so no renderer reaches into ``.value`` with a raw
  ``json.dumps``.
- **Script metadata.** Five script result types share the same human-facing
  ``path``/``class_name``/``extends`` surface. :class:`ScriptMetadata` is the
  structural interface the metadata renderer reads, so the renderer types against
  one surface rather than a five-way union.
"""

import json
from typing import Any, Protocol, runtime_checkable

from gda.models import (
    DaemonStartResult,
    DaemonStatusResult,
    DaemonStopResult,
    DiagErrorsResult,
    DiagLogResult,
    EngineVersion,
    ExportGetResult,
    ExportListResult,
    ExportRunResult,
    GameGetResult,
    GameSetResult,
    GameTreeResult,
    InputActionResult,
    InputKeyResult,
    InputMouseResult,
    InputSequenceResult,
    NodeAddResult,
    NodeConnectSignalResult,
    NodeDisconnectSignalResult,
    NodeDuplicateResult,
    NodeGetResult,
    NodeListResult,
    NodeMoveResult,
    NodeRemoveResult,
    NodeSetResult,
    PerfMonitorResult,
    PerfMonitorsResult,
    ProjectAddAutoloadResult,
    ProjectGetResult,
    ProjectInfoResult,
    ProjectRemoveAutoloadResult,
    ProjectSetResult,
    ResourceCreateResult,
    ResourceDeleteResult,
    ResourceGetResult,
    ResourceSetResult,
    ResourceUidResult,
    SceneCreateResult,
    SceneDeleteResult,
    SceneGetExportsResult,
    SceneGetResult,
    SceneListResult,
    SceneNode,
    ScriptAttachResult,
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptListResult,
    ScriptSetResult,
    ScriptValidateResult,
    ShaderCreateResult,
    ShaderGetResult,
    ShaderSetResult,
    ThemeCreateResult,
    ProjectDependenciesResult,
    ProjectFindReferencesResult,
    ProjectFindUnusedResourcesResult,
    ProjectStatisticsResult,
)


@runtime_checkable
class ScriptMetadata(Protocol):
    """The shared human-facing surface of every script result type.

    A structural (typing-only) interface — fields, no methods — over the
    ``path``/``class_name``/``extends`` that :class:`~gda.models.ScriptCreateResult`,
    :class:`~gda.models.ScriptGetResult`, :class:`~gda.models.ListedScript`,
    :class:`~gda.models.ScriptDeleteResult` and :class:`~gda.models.ScriptSetResult`
    all carry. The metadata renderer types against this surface, so adding a
    script result type that carries the same fields needs no renderer change and
    the renderer never reads across a union. It is a ``Protocol`` rather than a
    shared base model so it imposes nothing on the models' JSON Schema or field
    order (the ``--schema`` contract stays byte-for-byte unchanged).
    """

    path: str
    class_name: str | None
    extends: str | None


def format_value(value: Any) -> str:
    """Render a node property value (arbitrary JSON) as text.

    The one place value-to-text formatting lives, so no renderer reaches into a
    model's ``.value`` with a raw ``json.dumps``: a node property's value is the
    JSON projection of a Godot type (a scalar stays a scalar, a Vector2 becomes
    ``[x, y]``), and this owns that projection for the human path.
    """
    return json.dumps(value)


def render_node_tree(node: "SceneNode", depth: int = 0) -> str:
    """Render a node tree as an indented ``name (Type)`` outline for humans.

    Types against ``SceneNode`` alone: ``ListedNode`` is a ``SceneNode`` subclass
    (one tree shape), so node list's tree flows through here without naming a
    union — the renderer reads only ``name``/``type``/``children``, which every
    node in the tree carries.

    Iterative on purpose (issue #37): a legitimately deep scene tree can nest far
    past Python's recursion limit, so this walks the tree with an explicit stack
    (pre-order, children left-to-right — the same outline a recursive walk would
    produce) rather than recursing per level and raising an unstructured
    ``RecursionError`` on a deep-but-valid tree.
    """
    lines: list[str] = []
    # Stack of (node, depth); pushing children in reverse so the leftmost child
    # is popped first preserves the recursive pre-order, in-order traversal.
    stack: list[tuple["SceneNode", int]] = [(node, depth)]
    while stack:
        current, current_depth = stack.pop()
        lines.append(f"{'  ' * current_depth}{current.name} ({current.type})")
        for child in reversed(current.children):
            stack.append((child, current_depth + 1))
    return "\n".join(lines)


def render_scene_metadata(scene: "SceneCreateResult") -> str:
    """Render a created scene as ``created <path> (root <type>)``."""
    return f"created {scene.path} (root {scene.root_type})"


def render_scene_tree(scene: "SceneGetResult") -> str:
    """Render a read scene's node tree."""
    return render_node_tree(scene.root)


def render_game_tree(game: "GameTreeResult") -> str:
    """Render the running game's runtime scene tree (ADR-0019).

    The runtime counterpart of ``render_scene_tree``: ``render_node_tree`` reads
    only ``name``/``type``/``children``, which a ``GameNode`` carries, so the
    runtime tree flows through the same indented outline as the on-disk scene.
    """
    return render_node_tree(game.root)


def render_game_get(got: "GameGetResult") -> str:
    """Render a running node's runtime properties (the live `render_node_properties`).

    The runtime counterpart of ``render_node_properties``: same ``path (Type)``
    header + ``name (Type) = value`` lines, addressed by the runtime path.
    """
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_game_set(was_set: "GameSetResult") -> str:
    """Render a set runtime property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


def render_diag_errors(diag: "DiagErrorsResult") -> str:
    """Render the running game's runtime errors as `LEVEL: message (at: loc)` lines (#224).

    One line per error/warning; the location is appended when known (a bare error
    omits it). An empty read renders a short `no runtime errors` note rather than
    a blank string, so the human output is never ambiguous.
    """
    if not diag.errors:
        return "no runtime errors"
    lines = []
    for err in diag.errors:
        line = f"{err.level.upper()}: {err.message}"
        if err.file is not None:
            loc = f"{err.file}:{err.line}" if err.line is not None else err.file
            at = f" (at: {err.function} {loc})" if err.function else f" (at: {loc})"
            line += at
        lines.append(line)
    return "\n".join(lines)


def render_diag_log(diag: "DiagLogResult") -> str:
    """Render the running game's raw output log — its lines verbatim, one per line (#224)."""
    if not diag.lines:
        return "no output"
    return "\n".join(diag.lines)


def render_perf_monitors(snapshot: "PerfMonitorsResult") -> str:
    """Render a performance-monitor snapshot as one ``name = value`` line each (#223).

    A flat list of the running game's monitors, sorted by name for a stable
    human-facing order, headed by the snapshot timestamp.
    """
    header = f"perf @ {snapshot.timestamp}ms"
    lines = [
        f"  {name} = {format_value(monitor.value)}"
        for name, monitor in sorted(snapshot.monitors.items())
    ]
    return "\n".join([header, *lines])


def render_perf_monitor(timeline: "PerfMonitorResult") -> str:
    """Render a per-frame timeline (#223): a value line per frame, or an emission per row.

    A property watch lists ``frame: value`` per sample; a signal watch lists
    ``frame: args`` per recorded emission. Headed by the watched node and target.
    """
    if timeline.kind == "signal":
        header = f"{timeline.node} signal {timeline.signal} ({timeline.frames} frames)"
        rows = [
            f"  frame {e.frame}: {format_value(e.args)}" for e in timeline.emissions
        ]
        return "\n".join([header, *rows])
    header = f"{timeline.node} property {timeline.property} ({timeline.frames} frames)"
    rows = [
        f"  frame {s.frame}: {format_value(s.value)}" for s in timeline.samples
    ]
    return "\n".join([header, *rows])


def render_input_key(injected: "InputKeyResult") -> str:
    """Render an injected key event as ``key <name> [+ mods] <pressed|released>`` (#221)."""
    mods = ("+" + "+".join(injected.modifiers)) if injected.modifiers else ""
    state = "pressed" if injected.pressed else "released"
    return f"key {injected.key}{mods} {state} (keycode {injected.keycode})"


def render_input_mouse(injected: "InputMouseResult") -> str:
    """Render an injected mouse event as a click or a move at its position (#221)."""
    x, y = injected.position
    if injected.kind == "mouse_click":
        double = " double" if injected.double else ""
        return f"{injected.button} click{double} at ({x}, {y})"
    return f"mouse move to ({x}, {y})"


def render_input_action(injected: "InputActionResult") -> str:
    """Render an injected action event as ``action <name> <pressed|released>`` (#221)."""
    if injected.pressed:
        return f"action {injected.action} pressed (strength {injected.strength})"
    return f"action {injected.action} released"


def render_input_sequence(injected: "InputSequenceResult") -> str:
    """Render an injected sequence as ``sequence: N events over M frames`` (#221)."""
    return f"sequence: {injected.events} events over {injected.frames} frames"


def render_daemon_start(started: "DaemonStartResult") -> str:
    """Render a `gda daemon start` outcome for humans."""
    state = "already running" if started.already_running else "started"
    harness = " (installed harness)" if started.installed_harness else ""
    return f"daemon {state}: pid {started.pid} on {started.socket_path}{harness}"


def render_daemon_stop(stopped: "DaemonStopResult") -> str:
    """Render a `gda daemon stop` outcome for humans."""
    if stopped.stopped:
        return f"daemon stopped (pid {stopped.pid})"
    return "no daemon was running"


def render_daemon_status(status: "DaemonStatusResult") -> str:
    """Render a `gda daemon status` outcome for humans."""
    if status.running:
        return f"daemon running: pid {status.pid} on {status.socket_path}"
    return "daemon not running"


def render_scene_exports(scene: "SceneGetExportsResult") -> str:
    """Render a scene's per-node @export properties for humans.

    One ``path (Type)`` header per node that declares exports, then a
    ``name (Type) = value`` line per export — reusing :func:`format_value` for
    the value, the same projection ``node get`` renders. An empty listing (no
    exported variables anywhere) reads as ``(no exports)``.
    """
    if not scene.nodes:
        return "(no exports)"
    lines = []
    for node in scene.nodes:
        lines.append(f"{node.path} ({node.type})")
        for export in node.exports:
            lines.append(
                f"  {export.name} ({export.type}) = {format_value(export.value)}"
            )
    return "\n".join(lines)


def render_scene_list(listed: "SceneListResult") -> str:
    """Render the enumerated scenes as ``path (root_name: root_type)`` lines."""
    if not listed.scenes:
        return "(no scenes)"
    lines = []
    for scene in listed.scenes:
        if scene.root_name is not None and scene.root_type is not None:
            lines.append(f"{scene.path} ({scene.root_name}: {scene.root_type})")
        else:
            lines.append(f"{scene.path} (unreadable)")
    return "\n".join(lines)


def render_scene_delete(removed: "SceneDeleteResult") -> str:
    """Render a deleted scene as ``deleted <path> (root <name>: <type>)``."""
    return f"deleted {removed.path} (root {removed.root_name}: {removed.root_type})"


def render_node_add(added: "NodeAddResult") -> str:
    """Render an added node as ``added <path> (<type>) to <scene>``."""
    return f"added {added.path} ({added.type}) to {added.scene_path}"


def render_node_list(listed: "NodeListResult") -> str:
    """Render a listed scene's node tree (with node paths)."""
    return render_node_tree(listed.root)


def render_node_properties(got: "NodeGetResult") -> str:
    """Render a node's properties as ``name (Type) = value`` lines for humans."""
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_node_set(was_set: "NodeSetResult") -> str:
    """Render a set property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


def render_node_remove(removed: "NodeRemoveResult") -> str:
    """Render a removed node as ``removed <path> (<type>) from <scene>``."""
    return f"removed {removed.path} ({removed.type}) from {removed.scene_path}"


def render_node_duplicate(duplicated: "NodeDuplicateResult") -> str:
    """Render a duplicated node as ``duplicated <source> to <path> (<type>)``."""
    return (
        f"duplicated {duplicated.source_path} to {duplicated.path} "
        f"({duplicated.type})"
    )


def render_node_move(moved: "NodeMoveResult") -> str:
    """Render a moved node as ``moved <source> to <path> (<type>)``."""
    return f"moved {moved.source_path} to {moved.path} ({moved.type})"


def render_node_connect_signal(connected: "NodeConnectSignalResult") -> str:
    """Render a wired connection as ``connected <from>.<signal> -> <to>.<method>``."""
    return (
        f"connected {connected.from_node}.{connected.signal} -> "
        f"{connected.to}.{connected.method}"
    )


def render_node_disconnect_signal(disconnected: "NodeDisconnectSignalResult") -> str:
    """Render an unwired connection as ``disconnected <from>.<signal> -> <to>.<method>``."""
    return (
        f"disconnected {disconnected.from_node}.{disconnected.signal} -> "
        f"{disconnected.to}.{disconnected.method}"
    )


def render_script_metadata(script: ScriptMetadata) -> str:
    """Render a script's path plus its class_name/extends for humans.

    Reads the shared :class:`ScriptMetadata` surface, so it serves every script
    result type without naming the union.
    """
    meta = []
    if script.extends is not None:
        meta.append(f"extends {script.extends}")
    if script.class_name is not None:
        meta.append(f"class_name {script.class_name}")
    if not meta:
        return script.path
    return f"{script.path} ({', '.join(meta)})"


def render_script_create(created: "ScriptCreateResult") -> str:
    """Render a created script as ``created <metadata>``."""
    return f"created {render_script_metadata(created)}"


def render_script_get(got: "ScriptGetResult") -> str:
    """Render a read script as its metadata line followed by its source."""
    return "\n".join([render_script_metadata(got), got.source])


def render_script_list(listed: "ScriptListResult") -> str:
    """Render the enumerated scripts as ``path (extends X, class_name Y)`` lines."""
    if not listed.scripts:
        return "(no scripts)"
    return "\n".join(render_script_metadata(script) for script in listed.scripts)


def render_script_delete(removed: "ScriptDeleteResult") -> str:
    """Render a deleted script as ``deleted <metadata>``."""
    return f"deleted {render_script_metadata(removed)}"


def render_script_set(edited: "ScriptSetResult") -> str:
    """Render an edited script as ``set <metadata>``."""
    return f"set {render_script_metadata(edited)}"


def render_script_attach(attached: "ScriptAttachResult") -> str:
    """Render an attached script as ``attached <script> to <node> in <scene>``."""
    return (
        f"attached {attached.script} to {attached.node} in {attached.scene_path}"
    )


def render_script_validate(validated: "ScriptValidateResult") -> str:
    """Render a validate result: valid/invalid plus best-effort diagnostics."""
    if validated.valid:
        return f"valid {validated.path}"
    lines = [f"invalid {validated.path}"]
    if validated.error_string is not None:
        lines.append(f"  {validated.error_string}")
    for diag in validated.diagnostics:
        location = f"line {diag.line}" if diag.line is not None else "unknown line"
        lines.append(f"  {location}: {diag.message}")
    return "\n".join(lines)


def render_resource_create(created: "ResourceCreateResult") -> str:
    """Render a created resource as ``created <path> (<type>)``."""
    return f"created {created.path} ({created.type})"


def render_resource_properties(got: "ResourceGetResult") -> str:
    """Render a resource's properties as ``name (Type) = value`` lines for humans.

    Mirrors :func:`render_node_properties`: a header naming the resource and its
    type, then one typed line per storage property — the same human surface a
    node's properties get, since both read the shared :class:`NodeProperty`.
    """
    header = f"{got.path} ({got.type})"
    lines = [
        f"  {prop.name} ({prop.type}) = {format_value(prop.value)}"
        for prop in got.properties
    ]
    return "\n".join([header, *lines])


def render_resource_set(was_set: "ResourceSetResult") -> str:
    """Render a set property as ``set <path>.<property> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)}"
    )


def render_resource_delete(removed: "ResourceDeleteResult") -> str:
    """Render a deleted resource as ``deleted <path> (<type>)``."""
    return f"deleted {removed.path} ({removed.type})"


def render_export_list(listed: "ExportListResult") -> str:
    """Render the enumerated presets as ``name (platform) [runnable]`` lines."""
    if not listed.presets:
        return "(no presets)"
    lines = []
    for preset in listed.presets:
        runnable = " [runnable]" if preset.runnable else ""
        lines.append(f"{preset.name} ({preset.platform}){runnable}")
    return "\n".join(lines)


def render_export_get(got: "ExportGetResult") -> str:
    """Render one preset's details plus its export-template readiness."""
    runnable = " [runnable]" if got.runnable else ""
    header = f"{got.name} ({got.platform}){runnable}"
    templates = (
        f"templates installed ({got.templates_version})"
        if got.templates_installed
        else f"templates missing ({got.templates_version})"
    )
    return "\n".join([header, f"  export_path: {got.export_path}", f"  {templates}"])


def render_export_run(ran: "ExportRunResult") -> str:
    """Render a completed export as ``exported <preset> (<platform>, <mode>) -> <path>``.

    Echoes the artifact that was produced, then one ``warning: …`` line per
    non-fatal engine warning (a clean export prints just the header line).
    """
    header = (
        f"exported {ran.preset} ({ran.platform}, {ran.mode.value}) "
        f"-> {ran.output_path}"
    )
    if not ran.warnings:
        return header
    return "\n".join([header, *[f"  warning: {w}" for w in ran.warnings]])


def render_resource_uid(resolved: "ResourceUidResult") -> str:
    """Render a resolved UID↔path mapping as ``<uid> -> <path>`` for humans."""
    return f"{resolved.uid} -> {resolved.path}"


def render_project_info(info: "ProjectInfoResult") -> str:
    """Render project metadata as a small ``key: value`` block for humans."""
    main_scene = info.main_scene if info.main_scene else "(none)"
    return "\n".join(
        [
            f"name: {info.name}",
            f"main_scene: {main_scene}",
            f"viewport: {info.viewport_width}x{info.viewport_height}",
            f"engine: {info.engine_version.string}",
        ]
    )


def render_project_get(got: "ProjectGetResult") -> str:
    """Render a read setting as ``<setting> (<type>) = <value>``."""
    return f"{got.setting} ({got.type}) = {format_value(got.value)}"


def render_project_set(was_set: "ProjectSetResult") -> str:
    """Render a set setting as ``set <setting> (<type>) = <value>``."""
    return f"set {was_set.setting} ({was_set.type}) = {format_value(was_set.value)}"


def render_project_add_autoload(added: "ProjectAddAutoloadResult") -> str:
    """Render a registered autoload as ``added autoload <name> = <path>``."""
    return f"added autoload {added.name} = {added.path}"


def render_project_remove_autoload(removed: "ProjectRemoveAutoloadResult") -> str:
    """Render an unregistered autoload as ``removed autoload <name>``."""
    return f"removed autoload {removed.name}"


@runtime_checkable
class ShaderMetadata(Protocol):
    """The shared human-facing surface of every shader result type.

    A structural (typing-only) interface over the ``path``/``shader_type`` that
    :class:`~gda.models.ShaderCreateResult`, :class:`~gda.models.ShaderGetResult`
    and :class:`~gda.models.ShaderSetResult` all carry, so the shader-metadata
    renderer types against one surface rather than a three-way union (mirrors
    :class:`ScriptMetadata`).
    """

    path: str
    shader_type: str | None


def render_shader_metadata(shader: ShaderMetadata) -> str:
    """Render a shader's path plus its shader_type for humans.

    Reads the shared :class:`ShaderMetadata` surface, so it serves every shader
    result type without naming the union.
    """
    if shader.shader_type is not None:
        return f"{shader.path} (shader_type {shader.shader_type})"
    return shader.path


def render_shader_create(created: "ShaderCreateResult") -> str:
    """Render a created shader as ``created <metadata>``."""
    return f"created {render_shader_metadata(created)}"


def render_shader_get(got: "ShaderGetResult") -> str:
    """Render a read shader as its metadata line followed by its source."""
    return "\n".join([render_shader_metadata(got), got.source])


def render_shader_set(edited: "ShaderSetResult") -> str:
    """Render an edited shader as ``set <metadata>``."""
    return f"set {render_shader_metadata(edited)}"


def render_theme_create(created: "ThemeCreateResult") -> str:
    """Render a created theme as ``created <path> (<type>)``."""
    return f"created {created.path} ({created.type})"


def render_project_find_references(found: "ProjectFindReferencesResult") -> str:
    """Render find-references as ``<target>`` then one ``path (kind)`` line each."""
    if not found.references:
        return f"{found.target} (no references)"
    lines = [found.target]
    lines += [f"  {ref.path} ({ref.kind})" for ref in found.references]
    return "\n".join(lines)


def render_project_dependencies(deps: "ProjectDependenciesResult") -> str:
    """Render the dependency map as ``<scene>`` then indented ``-> <dep>`` lines."""
    if not deps.dependencies:
        return "(no scenes or resources)"
    lines = []
    for resource in deps.dependencies:
        lines.append(resource.path)
        lines += [f"  -> {dep.path} ({dep.kind})" for dep in resource.depends_on]
    return "\n".join(lines)


def render_project_find_unused_resources(
    unused: "ProjectFindUnusedResourcesResult",
) -> str:
    """Render the unreferenced resources, one path per line."""
    if not unused.unused:
        return "(no unused resources)"
    return "\n".join(unused.unused)


def render_project_statistics(stats: "ProjectStatisticsResult") -> str:
    """Render the project statistics as a human-readable summary."""
    lines = [
        f"{stats.total_files} files, {stats.total_lines} lines",
        (
            f"  scenes: {stats.scene_count}, scripts: {stats.script_count}, "
            f"resources: {stats.resource_count}"
        ),
    ]
    for ext in stats.by_extension:
        lines.append(f"  .{ext.extension}: {ext.files} files, {ext.lines} lines")
    if stats.autoloads:
        lines.append("autoloads:")
        lines += [f"  {a.name} = {a.path}" for a in stats.autoloads]
    if stats.plugins:
        lines.append("plugins:")
        lines += [f"  {p}" for p in stats.plugins]
    return "\n".join(lines)


def render_engine_version(version: "EngineVersion") -> str:
    """Render the engine version as its one-line version string."""
    return version.string


# Renderer selection keyed by result type: each result model maps to the one
# renderer that turns it into human-readable text. :func:`render` dispatches on
# ``type(result)``, so a command sources its renderer from this module by its
# result type rather than carrying an inline closure (composes with #139's
# ``render`` dispatch parameter).
_RENDERERS = {
    SceneCreateResult: render_scene_metadata,
    SceneGetResult: render_scene_tree,
    GameTreeResult: render_game_tree,
    GameGetResult: render_game_get,
    GameSetResult: render_game_set,
    DiagErrorsResult: render_diag_errors,
    DiagLogResult: render_diag_log,
    PerfMonitorsResult: render_perf_monitors,
    PerfMonitorResult: render_perf_monitor,
    InputKeyResult: render_input_key,
    InputMouseResult: render_input_mouse,
    InputActionResult: render_input_action,
    InputSequenceResult: render_input_sequence,
    DaemonStartResult: render_daemon_start,
    DaemonStopResult: render_daemon_stop,
    DaemonStatusResult: render_daemon_status,
    SceneGetExportsResult: render_scene_exports,
    SceneListResult: render_scene_list,
    SceneDeleteResult: render_scene_delete,
    NodeAddResult: render_node_add,
    NodeListResult: render_node_list,
    NodeGetResult: render_node_properties,
    NodeSetResult: render_node_set,
    NodeRemoveResult: render_node_remove,
    NodeDuplicateResult: render_node_duplicate,
    NodeMoveResult: render_node_move,
    NodeConnectSignalResult: render_node_connect_signal,
    NodeDisconnectSignalResult: render_node_disconnect_signal,
    ScriptCreateResult: render_script_create,
    ScriptGetResult: render_script_get,
    ScriptListResult: render_script_list,
    ScriptDeleteResult: render_script_delete,
    ScriptSetResult: render_script_set,
    ScriptAttachResult: render_script_attach,
    ScriptValidateResult: render_script_validate,
    ResourceCreateResult: render_resource_create,
    ResourceGetResult: render_resource_properties,
    ResourceSetResult: render_resource_set,
    ResourceDeleteResult: render_resource_delete,
    ExportListResult: render_export_list,
    ExportGetResult: render_export_get,
    ExportRunResult: render_export_run,
    ResourceUidResult: render_resource_uid,
    ProjectInfoResult: render_project_info,
    ProjectGetResult: render_project_get,
    ProjectSetResult: render_project_set,
    ProjectAddAutoloadResult: render_project_add_autoload,
    ProjectRemoveAutoloadResult: render_project_remove_autoload,
    ShaderCreateResult: render_shader_create,
    ShaderGetResult: render_shader_get,
    ShaderSetResult: render_shader_set,
    ThemeCreateResult: render_theme_create,
    ProjectFindReferencesResult: render_project_find_references,
    ProjectDependenciesResult: render_project_dependencies,
    ProjectFindUnusedResourcesResult: render_project_find_unused_resources,
    ProjectStatisticsResult: render_project_statistics,
    EngineVersion: render_engine_version,
}


def render(result: Any) -> str:
    """Render any ``gda`` result to human-readable text, keyed by its type.

    Looks the result's concrete type up in the type → renderer table and applies
    the matching renderer. A result type with no registered renderer is a
    programming error (a new command wired without a renderer), not a runtime
    user error, so it raises rather than guessing a format.
    """
    renderer = _RENDERERS.get(type(result))
    if renderer is None:
        raise KeyError(f"no renderer registered for result type {type(result)!r}")
    return renderer(result)
