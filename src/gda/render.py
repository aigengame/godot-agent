"""Human-readable rendering for ``gda`` results — the presentation layer.

The result models (``gda.models``) are pure ``--schema`` / ``--json`` data
contracts (ADR-0004); presentation does not live in them. This module owns the
human-readable text path: one renderer per result type, plus the typed helpers
that keep the presentation layer from reaching into a model's value shape or
across a union of result types. A command binds its renderer on its own
``HeadlessCommand`` descriptor (``render=``, ADR-0023) — there is no central
type-keyed dispatch table here; emission calls the descriptor's renderer.

Since ADR-0040 a group's own renderers live in its ``gda.commands.<group>``
module, beside the descriptors that bind them; what stays here are the renderers
of groups not yet moved plus the helpers shared ACROSS groups. One such seam is
deliberately funnelled through one place here:

- **Value-to-text.** A node property's ``value`` is arbitrary JSON (every Godot
  type carried uniformly, :class:`~gda.models.NodeProperty`). :func:`format_value`
  owns the JSON projection so no renderer reaches into ``.value`` with a raw
  ``json.dumps``.
"""

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # The result models are referenced only in string annotations on the renderers
    # below; since ADR-0023 removed the type-keyed dispatch table, nothing here
    # needs them at runtime. Keep them import-time only for type-checkers.
    #
    # ``SceneNode`` now lives with its own group module (ADR-0040); annotating
    # against it here is a TYPE_CHECKING-only reference, so the runtime
    # dependency direction (``commands`` → ``render``) is not inverted.
    from gda.commands.scene import SceneNode
    from gda.models import (
        DaemonStartResult,
        DaemonStatusResult,
        DaemonStopResult,
        DaemonUninstallResult,
        DiagErrorsResult,
        GameGetResult,
        GameNode,
        GameRectResult,
        GameSetResult,
        GameTreeResult,
        InputActionResult,
        InputKeyResult,
        InputMouseResult,
        InputSequenceResult,
        LoggerTailResult,
        PerfMonitorResult,
        PerfMonitorsResult,
        ScreenCaptureResult,
        ScreenFramesResult,
    )


def format_value(value: Any) -> str:
    """Render a node property value (arbitrary JSON) as text.

    The one place value-to-text formatting lives, so no renderer reaches into a
    model's ``.value`` with a raw ``json.dumps``: a node property's value is the
    JSON projection of a Godot type (a scalar stays a scalar, a Vector2 becomes
    ``[x, y]``), and this owns that projection for the human path.
    """
    return json.dumps(value)


def render_node_tree(node: "SceneNode | GameNode", depth: int = 0) -> str:
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
    stack: list[tuple["SceneNode | GameNode", int]] = [(node, depth)]
    while stack:
        current, current_depth = stack.pop()
        lines.append(f"{'  ' * current_depth}{current.name} ({current.type})")
        for child in reversed(current.children):
            stack.append((child, current_depth + 1))
    return "\n".join(lines)


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


def render_game_rect(rect: "GameRectResult") -> str:
    """Render a Control's runtime rendered rect as one viewport-space line."""
    return (
        f"{rect.path} ({rect.type}) "
        f"position={format_value(rect.position)} size={format_value(rect.size)}"
    )


def render_game_set(was_set: "GameSetResult") -> str:
    """Render a set runtime property as ``set <path>.<prop> (<type>) = <value>``."""
    return (
        f"set {was_set.path}.{was_set.property} ({was_set.type}) = "
        f"{format_value(was_set.value)} verified={format_value(was_set.verified)}"
    )


def render_diag_errors(diag: "DiagErrorsResult") -> str:
    """Render the running game's runtime errors as `LEVEL: message (at: loc)` lines (#224).

    One line per error/warning; the location is appended when known (a bare error
    omits it). A runtime GDScript error's ordered ``callstack`` (#283) renders as
    indented ``function (file:line)`` frame lines below the headline (most-recent-
    first); a bare error with no backtrace shows just its one line. An empty read
    renders a short `no runtime errors` note rather than a blank string, so the
    human output is never ambiguous.
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
        for frame in err.callstack:
            loc = f"{frame.file}:{frame.line}" if frame.line is not None else frame.file
            where = f"({loc})" if loc is not None else ""
            lines.append(f"  {frame.function or '<unknown>'} {where}".rstrip())
    return "\n".join(lines)


def render_logger_tail(tail: "LoggerTailResult") -> str:
    """Render the running game's structured runtime log (#281, ADR-0026).

    One ``LEVEL: message (at: loc)`` line per record, the location appended when
    known (a plain info line omits it). Under ``--raw`` records are unclassified
    ``info`` lines carrying verbatim text, so they render as the message alone (the
    superseded ``diag log`` view). An empty read renders a short note rather than a
    blank string, so the human output is never ambiguous.
    """
    if not tail.records:
        return "no log records"
    lines = []
    for rec in tail.records:
        line = f"{rec.level.value.upper()}: {rec.message}"
        if rec.source is not None and rec.source.file is not None:
            loc = (
                f"{rec.source.file}:{rec.source.line}"
                if rec.source.line is not None
                else rec.source.file
            )
            at = (
                f" (at: {rec.source.function} {loc})"
                if rec.source.function
                else f" (at: {loc})"
            )
            line += at
        lines.append(line)
    return "\n".join(lines)


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
    rows = [f"  frame {s.frame}: {format_value(s.value)}" for s in timeline.samples]
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
    if started.harness_synced:
        harness = f" (synced harness to v{started.harness_version})"
    elif started.installed_harness:
        harness = " (installed harness)"
    else:
        harness = ""
    # The session's display mode is part of the live context the start brought up
    # (#222) — note it only when windowed, since headless is the default.
    mode = " [windowed]" if started.windowed else ""
    return f"daemon {state}: pid {started.pid} on {started.socket_path}{mode}{harness}"


def render_screen_capture(captured: "ScreenCaptureResult") -> str:
    """Render a captured viewport frame as ``captured WxH -> path`` (#222)."""
    inline = " (+inline)" if captured.inline else ""
    return (
        f"captured {captured.width}x{captured.height} "
        f"({captured.bytes} bytes) -> {captured.path}{inline}"
    )


def render_screen_frames(captured: "ScreenFramesResult") -> str:
    """Render a captured frame sequence: a header + one ``WxH -> path`` per frame (#222)."""
    header = f"captured {captured.count} frames"
    rows = [
        f"  {frame.width}x{frame.height} -> {frame.path}" for frame in captured.frames
    ]
    return "\n".join([header, *rows])


def render_daemon_stop(stopped: "DaemonStopResult") -> str:
    """Render a `gda daemon stop` outcome for humans."""
    if stopped.stopped:
        return f"daemon stopped (pid {stopped.pid})"
    return "no daemon was running"


def render_daemon_status(status: "DaemonStatusResult") -> str:
    """Render a `gda daemon status` outcome for humans."""
    if status.running:
        # Mirror `daemon start`: note the display mode only when windowed (#251),
        # since headless is the default and an unknown mode (null) has nothing to say.
        mode = " [windowed]" if status.windowed else ""
        return f"daemon running: pid {status.pid} on {status.socket_path}{mode}"
    return "daemon not running"


def render_daemon_uninstall(uninstalled: "DaemonUninstallResult") -> str:
    """Render a `gda daemon uninstall` outcome for humans."""
    if uninstalled.removed:
        return "harness uninstalled"
    return "no harness was installed"
