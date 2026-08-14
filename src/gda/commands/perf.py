"""The ``perf`` command group: the running game's runtime performance (#223).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its human renderers, its ``HeadlessCommand`` descriptors
(ADR-0023) and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``, which defaults a
LIVE descriptor's classifier to the shared ``classify_live``), the
cross-command contract core (``gda.models``, which keeps the multi-group
``MAX_WINDOW_FRAMES`` ceiling and the runtime-node-address description) and the
shared render helper (``gda.render``) — and is imported by nothing but the
composition root (``gda.cli``).

Both commands are LIVE (``kind = LIVE``), served through ``gda-daemon`` against
the engine session it holds: ``perf monitors`` snapshots the engine's
``Performance`` counters in one frame; ``perf monitor`` collects a per-frame
property/signal timeline over N frames (the time-windowed multi-frame harness
base, ADR-0020).
"""

from typing import Any, Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda.dispatch import dispatch_domain
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import MAX_WINDOW_FRAMES, RUNTIME_NODE_DESC
from gda.render import format_value


class PerfMonitor(BaseModel):
    """One performance monitor as ``gda perf monitors`` snapshots it (Phase 2, #223).

    A single counter from the running game's ``Performance`` singleton: its public
    ``name`` (e.g. ``fps``, ``static_memory``), the Godot ``type`` of the sampled
    value (``float``, as ``Performance.get_monitor`` returns), and its ``value`` as
    JSON. Carried uniformly so an agent reads every monitor through one shape.
    """

    name: str
    type: str = Field(description="The sampled value's Godot type (e.g. float).")
    value: Any = Field(description="The monitor's value as JSON.")


class PerfMonitorsParams(BaseModel):
    """The params of ``gda perf monitors``: none — snapshot all monitors at once.

    Empty: ``perf monitors`` reads the whole instantaneous monitor set of the
    engine session held by ``gda-daemon`` in a single frame (frame-coherent,
    ADR-0020); there is nothing to select.
    """


class PerfMonitorsResult(BaseModel):
    """The result of ``gda perf monitors``: a one-frame performance snapshot (#223).

    The running game's instantaneous ``Performance`` counters — timing, memory,
    object/node counts, render stats, active physics/navigation objects — keyed by
    monitor name, plus the engine ``timestamp`` (ms since session start) the
    snapshot was taken at. Read in one frame, so the values are mutually coherent.
    """

    timestamp: int = Field(
        description="Engine time the snapshot was taken (ms, Time.get_ticks_msec)."
    )
    monitors: dict[str, PerfMonitor] = Field(
        description="The performance monitors, keyed by name."
    )


class PerfMonitorParams(BaseModel):
    """The params of ``gda perf monitor``: watch one node over a frame window (#223).

    Time-windowed: the gda harness collects a per-frame timeline over ``frames``
    frames and returns it as one blocking payload (ADR-0017 one-shot RPC, ADR-0020
    multi-frame). Exactly one of ``property`` / ``signal`` selects what to watch:
    ``property`` records the property's value each frame; ``signal`` records the
    signal's emissions over the window. The node is addressed by its runtime
    (absolute) path, as ``game tree`` reports it.

    The selector rule and the ``frames`` bound are enforced model-side
    (ADR-0015) so BOTH the argv path and ``--params-json`` reject a malformed
    request with the structured ``invalid_params`` error rather than the harness
    silently preferring one selector or clamping an over-range ``frames``.
    """

    node: str = Field(description=RUNTIME_NODE_DESC)
    property: str | None = Field(
        default=None,
        description="The property to sample each frame (mutually exclusive with --signal).",
    )
    signal: str | None = Field(
        default=None,
        description="The signal whose emissions to record over the window (mutually exclusive with --property).",
    )
    frames: int = Field(
        default=60,
        ge=1,
        le=MAX_WINDOW_FRAMES,
        description=(
            "The number of frames to collect over, 1.."
            f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). An "
            "over-range value is rejected, not clamped."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> "PerfMonitorParams":
        # Exactly one of property/signal selects what to watch. Enforced model-side
        # (ADR-0015) so the argv and --params-json paths agree and the harness is
        # never handed an ambiguous request (it would otherwise silently prefer the
        # signal). Neither set or both set is a usage/invalid-params error.
        if self.property is None and self.signal is None:
            raise ValueError(
                "perf monitor needs exactly one of --property or --signal "
                "(neither was given)."
            )
        if self.property is not None and self.signal is not None:
            raise ValueError(
                "--property and --signal are mutually exclusive; pass exactly one."
            )
        return self


class PerfPropertySample(BaseModel):
    """One per-frame sample of a watched property (``gda perf monitor --property``, #223)."""

    frame: int = Field(description="The 0-based frame index within the window.")
    timestamp: int = Field(description="Engine time the sample was taken (ms).")
    value: Any = Field(description="The property's value as JSON at that frame.")


class PerfSignalEmission(BaseModel):
    """One recorded emission of a watched signal (``gda perf monitor --signal``, #223)."""

    frame: int = Field(description="The frame index the emission landed in.")
    timestamp: int = Field(description="Engine time the emission was recorded (ms).")
    args: list[Any] = Field(
        default_factory=list, description="The emission's arguments as JSON."
    )


class PerfMonitorResult(BaseModel):
    """The result of ``gda perf monitor``: a collected per-frame timeline (#223).

    Carries the watched ``node`` (runtime path), the ``kind`` of timeline
    (``property`` or ``signal``), and the number of ``frames`` collected. For a
    property watch, ``samples`` is the per-frame value timeline and ``emissions``
    is empty; for a signal watch, ``emissions`` is the recorded emissions over the
    window and ``samples`` is empty. The harness reports exactly one of the two.
    """

    node: str = Field(description="The watched node's runtime (absolute) path.")
    kind: str = Field(description="The timeline kind: 'property' or 'signal'.")
    frames: int = Field(description="The number of frames the window collected over.")
    property: str | None = Field(
        default=None, description="The watched property (a property watch only)."
    )
    signal: str | None = Field(
        default=None, description="The watched signal (a signal watch only)."
    )
    samples: list[PerfPropertySample] = Field(
        default_factory=list,
        description="The per-frame property timeline (a property watch only).",
    )
    emissions: list[PerfSignalEmission] = Field(
        default_factory=list,
        description="The recorded signal emissions over the window (a signal watch only).",
    )


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


PERF_MONITORS_COMMAND: HeadlessCommand[PerfMonitorsResult] = HeadlessCommand(
    operation="perf-monitors",
    input_model=PerfMonitorsParams,
    output_model=PerfMonitorsResult,
    render=render_perf_monitors,
    kind=ExecutionKind.LIVE,
)


PERF_MONITOR_COMMAND: HeadlessCommand[PerfMonitorResult] = HeadlessCommand(
    operation="perf-monitor",
    input_model=PerfMonitorParams,
    output_model=PerfMonitorResult,
    render=render_perf_monitor,
    kind=ExecutionKind.LIVE,
)


# The perf command group (Phase 2, ADR-0019, #223): runtime performance monitoring
# of the RUNNING game, served LIVE through gda-daemon (`kind = LIVE`). `perf
# monitors` snapshots the engine's Performance counters in one frame; `perf monitor`
# collects a per-frame property/signal timeline over N frames (the time-windowed
# multi-frame harness base). Like `game`, a domain-object group marked live by
# `kind`, not by the tree (ADR-0019).
_app = typer.Typer(
    help="Monitor the running game's runtime performance (live).",
    no_args_is_help=True,
)


@_app.command(name="monitors", cls=PERF_MONITORS_COMMAND.command_class())
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
    dispatch_domain(
        PERF_MONITORS_COMMAND,
        PerfMonitorsParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="monitor", cls=PERF_MONITOR_COMMAND.command_class())
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
    dispatch_domain(
        PERF_MONITOR_COMMAND,
        PerfMonitorParams(node=node, property=property, signal=signal, frames=frames),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``perf`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="perf")
