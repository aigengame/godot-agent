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

All commands are LIVE (``kind = LIVE``), served through ``gda-daemon`` against
the engine session it holds: ``perf monitors`` snapshots the engine's
``Performance`` counters in one frame; ``perf monitor`` collects a per-frame
property/signal timeline for ONE NODE over N frames (the time-windowed
multi-frame harness base, ADR-0020); ``perf sample`` (#662) collects the ENGINE
monitors per frame over a bounded window and adds aggregate statistics — and,
with a budget file, per-monitor pass/fail verdicts. ``perf sample`` runs a
CLI-side recipe (ADR-0023, the ``screen`` pattern): the harness returns only the
raw timestamped samples; the statistics and budget verdicts are computed here,
where their numeric semantics are unit-testable without an engine.
"""

import json
import math
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from gda import dispatch
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import Failure, classify_live, make_failure
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.live_runner import make_daemon_runner
from gda.models import MAX_WINDOW_FRAMES, RUNTIME_NODE_DESC
from gda.render import format_value
from gda.runner import GodotRunner


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


# --- perf sample (windowed engine-monitor sampling, #662) ----------------------

# The engine performance monitors the gda harness exposes, by public name — the
# CLI-side mirror of the harness's ``_perf_monitors`` table (gda-owned constants,
# not engine-queried), so ``perf sample --monitor`` validates model-side
# (ADR-0015) and an unknown name never costs a live round trip. A sync test
# (tests/test_error_registry.py) parses the harness table and holds the two
# identical, the same way MAX_WINDOW_FRAMES is mirrored.
PERF_MONITOR_NAMES: tuple[str, ...] = (
    "fps",
    "process_time",
    "physics_process_time",
    "static_memory",
    "static_memory_max",
    "object_count",
    "node_count",
    "orphan_node_count",
    "resource_count",
    "draw_calls",
    "objects_in_frame",
    "primitives_in_frame",
    "video_memory",
    "physics_2d_active_objects",
    "physics_3d_active_objects",
    "navigation_active_maps",
)

# The statistics a budget rule may gate on — the aggregate set minus ``count``,
# which counts frames rather than measuring the monitor.
BudgetStat = Literal["min", "max", "mean", "p50", "p95"]

_FRAMES_DESC = (
    f"The number of frames to sample over, 1..{MAX_WINDOW_FRAMES} (the gda "
    "harness's per-window ceiling). An over-range value is rejected, not clamped."
)


class PerfSampleParams(BaseModel):
    """The params of ``gda perf sample``: sample engine monitors over a window (#662).

    The windowed counterpart of the one-frame ``perf monitors`` snapshot (which
    stays as it is): the gda harness reads every selected monitor once per frame
    over ``frames`` frames (frame-coherent, ADR-0020) and returns the raw
    timestamped samples in one blocking payload; the CLI computes the aggregate
    statistics and, when ``budget`` is supplied, the per-monitor pass/fail
    verdicts. An empty ``monitors`` selection samples ALL monitors. Monitor
    names and the ``frames`` bound are enforced model-side (ADR-0015).
    """

    frames: int = Field(
        default=60, ge=1, le=MAX_WINDOW_FRAMES, description=_FRAMES_DESC
    )
    monitors: list[str] = Field(
        default_factory=list,
        description=(
            "The performance monitors to sample (repeatable); empty samples ALL "
            f"monitors. Known names: {', '.join(PERF_MONITOR_NAMES)}."
        ),
    )
    budget: Optional[str] = Field(
        default=None,
        description=(
            "Path to a JSON budget file: an object of {monitor: {stat, min?, "
            "max?}} entries, where stat is one of min, max, mean, p50, p95 and "
            "at least one bound is set. Each budgeted monitor gets a pass/fail "
            "verdict against the chosen statistic; the verdict is data (the "
            "command still exits 0)."
        ),
    )

    @model_validator(mode="after")
    def _known_monitors(self) -> "PerfSampleParams":
        unknown = [name for name in self.monitors if name not in PERF_MONITOR_NAMES]
        if unknown:
            raise ValueError(
                f"unknown performance monitor(s) {unknown}; known: "
                f"{list(PERF_MONITOR_NAMES)}."
            )
        # A repeated name is idempotent (the same counter read once per frame),
        # so it is normalized away rather than refused.
        self.monitors = list(dict.fromkeys(self.monitors))
        return self


class PerfBudget(BaseModel):
    """One monitor's budget rule: gate a statistic with a min and/or max bound.

    ``stat`` is REQUIRED — a defaulted statistic would let a release gate pass
    against a number nobody chose. The rule passes when the statistic is >= the
    ``min`` bound (if set) and <= the ``max`` bound (if set).
    """

    model_config = ConfigDict(extra="forbid")

    stat: BudgetStat
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> "PerfBudget":
        if self.min is None and self.max is None:
            raise ValueError("a budget entry needs 'min' and/or 'max'.")
        return self


class PerfSampleStats(BaseModel):
    """Aggregate statistics for one monitor over the sampled window (#662).

    Percentiles use the nearest-rank method on the sorted samples: pNN is the
    value at index ``ceil(NN/100 * count) - 1``.
    """

    count: int = Field(description="The number of samples (one per frame).")
    min: float = Field(description="The smallest sampled value.")
    max: float = Field(description="The largest sampled value.")
    mean: float = Field(description="The arithmetic mean of the samples.")
    p50: float = Field(description="The 50th percentile (nearest-rank).")
    p95: float = Field(description="The 95th percentile (nearest-rank).")


class PerfSampleFrame(BaseModel):
    """One per-frame row of a ``perf sample`` window: every selected monitor at one frame."""

    frame: int = Field(ge=0, description="The 0-based frame index within the window.")
    timestamp: int = Field(description="Engine time the row was sampled (ms).")
    values: dict[str, float] = Field(
        description="The selected monitors' values at that frame, keyed by name."
    )


class PerfBudgetVerdict(BaseModel):
    """One monitor's budget verdict: the gated statistic against its bounds (#662)."""

    stat: BudgetStat = Field(description="The statistic the budget gated.")
    value: float = Field(description="That statistic's value over the window.")
    min: float | None = Field(
        default=None, description="The lower bound, when the rule set one."
    )
    max: float | None = Field(
        default=None, description="The upper bound, when the rule set one."
    )
    passed: bool = Field(description="Whether the value satisfied both bounds.")


class PerfSampleResult(BaseModel):
    """The result of ``gda perf sample``: window statistics, raw samples, verdicts (#662).

    ``monitors`` carries the per-monitor aggregate statistics; ``samples`` the
    raw timestamped per-frame rows the statistics were computed from. With a
    budget file, ``budget`` carries one verdict per budgeted monitor and
    ``passed`` whether ALL of them passed; both are null otherwise. ``max_frames``
    echoes the per-window ceiling the ``frames`` bound inherits.
    """

    frames: int = Field(description="The number of frames the window sampled.")
    max_frames: int = Field(
        description=(
            "The per-window ceiling the frames bound inherits (the gda "
            "harness's MAX_WINDOW_FRAMES)."
        )
    )
    monitors: dict[str, PerfSampleStats] = Field(
        description="Aggregate statistics per sampled monitor, keyed by name."
    )
    samples: list[PerfSampleFrame] = Field(
        description="The raw timestamped per-frame samples."
    )
    budget: dict[str, PerfBudgetVerdict] | None = Field(
        default=None,
        description="Per-monitor budget verdicts; null when no budget was supplied.",
    )
    passed: bool | None = Field(
        default=None,
        description=(
            "Whether every budget verdict passed; null when no budget was "
            "supplied. A failed budget is data — the command still exits 0."
        ),
    )


# The LIVE runner factory seam, the same shape ``gda.dispatch.make_live_runner``
# has (the ``screen`` pattern), so a test's ``inject_live_runner`` binds without
# a second injection point; ``binary`` is unused on the live channel.
LiveRunnerFactory = Callable[[Optional[Path], Optional[Path]], GodotRunner]


class _SampleReply(BaseModel):
    """The wire shape ``perf-sample`` returns: the raw samples, pre-statistics.

    Not the public result — that is :class:`PerfSampleResult`, assembled
    CLI-side. The reply's coherence is VALIDATED (the #732 lesson): the declared
    window length matches the rows, and every row carries exactly the declared
    monitors, so a drifted harness classifies as ``contract_violation`` instead
    of producing statistics over partial data.
    """

    kind: Literal["sample"]
    frames: int = Field(ge=1)
    monitors: list[str] = Field(min_length=1)
    samples: list[PerfSampleFrame]

    @model_validator(mode="after")
    def _coherent(self) -> "_SampleReply":
        if self.frames != len(self.samples):
            raise ValueError("frames must equal the number of sample rows.")
        declared = set(self.monitors)
        for sample in self.samples:
            if set(sample.values) != declared:
                raise ValueError(
                    "every sample row carries exactly the declared monitors."
                )
        return self


def _default_runner(binary: Optional[Path], project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory."""
    return make_daemon_runner(project)


def _nearest_rank(ordered: list[float], percentile: float) -> float:
    """The nearest-rank percentile of an already-sorted, non-empty series."""
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _stats_over(values: list[float]) -> PerfSampleStats:
    """Aggregate one monitor's non-empty per-frame series (#662)."""
    ordered = sorted(values)
    return PerfSampleStats(
        count=len(ordered),
        min=ordered[0],
        max=ordered[-1],
        mean=sum(ordered) / len(ordered),
        p50=_nearest_rank(ordered, 0.50),
        p95=_nearest_rank(ordered, 0.95),
    )


def _load_budgets(path: Path) -> "dict[str, PerfBudget] | Failure":
    """Read and validate a budget file, or the structured ``invalid_params``.

    The file is read here — in the recipe, shared by the argv and
    ``--params-json`` paths — so a missing, unreadable, or malformed budget is
    the same structured error on both (ADR-0015's intent for a file-borne input).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return make_failure(
            "invalid_params", f"cannot read the budget file {path}: {exc}", ""
        )
    except json.JSONDecodeError as exc:
        return make_failure(
            "invalid_params", f"the budget file {path} is not valid JSON: {exc}", ""
        )
    if not isinstance(raw, dict) or not raw:
        return make_failure(
            "invalid_params",
            f"the budget file {path} must be a non-empty JSON object of "
            "{monitor: {stat, min?, max?}} entries.",
            "",
        )
    budgets: dict[str, PerfBudget] = {}
    for name, entry in raw.items():
        if name not in PERF_MONITOR_NAMES:
            return make_failure(
                "invalid_params",
                f"the budget file names an unknown performance monitor: {name!r}; "
                f"known: {list(PERF_MONITOR_NAMES)}.",
                "",
            )
        try:
            budgets[name] = PerfBudget.model_validate(entry)
        except ValidationError as exc:
            return make_failure(
                "invalid_params", f"budget entry {name!r} is invalid: {exc}", ""
            )
    return budgets


def _evaluate_budgets(
    budgets: dict[str, PerfBudget], stats: dict[str, PerfSampleStats]
) -> tuple[dict[str, PerfBudgetVerdict], bool]:
    """Gate each budgeted monitor's chosen statistic against its bounds."""
    verdicts: dict[str, PerfBudgetVerdict] = {}
    for name, rule in budgets.items():
        value = getattr(stats[name], rule.stat)
        passed = (rule.min is None or value >= rule.min) and (
            rule.max is None or value <= rule.max
        )
        verdicts[name] = PerfBudgetVerdict(
            stat=rule.stat, value=value, min=rule.min, max=rule.max, passed=passed
        )
    return verdicts, all(verdict.passed for verdict in verdicts.values())


def run_perf_sample_operation(
    project: Optional[Path],
    params: PerfSampleParams,
    *,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "PerfSampleResult | Failure":
    """Sample the engine monitors over a window; aggregate and gate CLI-side (#662).

    The recipe: validate the budget FIRST (a bad budget must not cost a live
    window), run the ``perf-sample`` live op, surface any LIVE failure via
    ``classify_live``, then compute the statistics from the raw samples and
    evaluate the budget against them.
    """
    budgets: dict[str, PerfBudget] | None = None
    if params.budget is not None:
        loaded = _load_budgets(Path(params.budget))
        if isinstance(loaded, Failure):
            return loaded
        budgets = loaded
        selection = params.monitors or list(PERF_MONITOR_NAMES)
        outside = [name for name in budgets if name not in selection]
        if outside:
            return make_failure(
                "invalid_params",
                f"the budget names monitors outside the sampled selection: "
                f"{outside}; add them to --monitor or drop them from the budget.",
                "",
            )
    runner = (make_runner or _default_runner)(None, project)
    result = runner.run(
        "perf-sample", {"frames": params.frames, "monitors": params.monitors}
    )
    reply = classify_live(result, None, _SampleReply)
    if isinstance(reply, Failure):
        return reply
    stats = {
        name: _stats_over([sample.values[name] for sample in reply.samples])
        for name in reply.monitors
    }
    budget_verdicts: dict[str, PerfBudgetVerdict] | None = None
    passed: bool | None = None
    if budgets is not None:
        missing = [name for name in budgets if name not in stats]
        if missing:
            return make_failure(
                "contract_violation",
                f"the harness reply omitted budgeted monitor(s): {missing}.",
                "",
            )
        budget_verdicts, passed = _evaluate_budgets(budgets, stats)
    return PerfSampleResult(
        frames=reply.frames,
        max_frames=MAX_WINDOW_FRAMES,
        monitors=stats,
        samples=reply.samples,
        budget=budget_verdicts,
        passed=passed,
    )


def _perf_sample_recipe(params, *, project, godot):
    return run_perf_sample_operation(
        project, params, make_runner=dispatch.make_live_runner
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


def render_perf_sample(sampled: "PerfSampleResult") -> str:
    """Render a sampled window as one stats line per monitor, plus the verdicts (#662)."""
    header = (
        f"perf sample: {sampled.frames} frames, {len(sampled.monitors)} monitors "
        f"(ceiling {sampled.max_frames})"
    )
    lines = [
        f"  {name}: mean {format_value(stats.mean)}, p50 {format_value(stats.p50)}, "
        f"p95 {format_value(stats.p95)}, min {format_value(stats.min)}, "
        f"max {format_value(stats.max)} ({stats.count} samples)"
        for name, stats in sorted(sampled.monitors.items())
    ]
    if sampled.budget is not None:
        lines.append(f"  budget: {'PASS' if sampled.passed else 'FAIL'}")
        for name, verdict in sorted(sampled.budget.items()):
            bounds = "".join(
                f" {label} {format_value(bound)}"
                for label, bound in (("min", verdict.min), ("max", verdict.max))
                if bound is not None
            )
            lines.append(
                f"    {'PASS' if verdict.passed else 'FAIL'} {name} "
                f"{verdict.stat} {format_value(verdict.value)} (bounds:{bounds})"
            )
    return "\n".join([header, *lines])


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


# `perf sample` is LIVE but runs a CLI-side recipe (the `screen` pattern,
# ADR-0023): the harness returns only the raw per-frame samples, and the CLI
# computes the statistics and budget verdicts before it has the public result.
# `kind = LIVE` stays a descriptor fact so "kind":"live" appears in --schema.
PERF_SAMPLE_COMMAND: HeadlessCommand[PerfSampleResult] = HeadlessCommand(
    operation="perf-sample",
    input_model=PerfSampleParams,
    output_model=PerfSampleResult,
    render=render_perf_sample,
    kind=ExecutionKind.LIVE,
    recipe=_perf_sample_recipe,
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


@_app.command(name="sample", cls=PERF_SAMPLE_COMMAND.command_class())
def perf_sample(
    frames: int = typer.Option(
        60,
        "--frames",
        min=1,
        max=MAX_WINDOW_FRAMES,
        help=(
            f"The number of frames to sample over, 1..{MAX_WINDOW_FRAMES} (the "
            "gda harness's per-window ceiling)."
        ),
    ),
    monitors: list[str] = typer.Option(
        [],
        "--monitor",
        help=(
            "A performance monitor to sample (repeatable); omit to sample ALL "
            "monitors. Unknown names are rejected before dispatch."
        ),
    ),
    budget: Optional[str] = typer.Option(
        None,
        "--budget",
        help=(
            "Path to a JSON budget file: {monitor: {stat, min?, max?}}, stat "
            "one of min, max, mean, p50, p95. Adds per-monitor pass/fail "
            "verdicts; a failed budget is data (exit stays 0)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PERF_SAMPLE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Sample engine performance monitors over a frame window, with statistics (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017): the
    gda harness reads every selected monitor once per frame over `--frames`
    frames (up to the per-window ceiling stated above) and returns the raw
    timestamped samples; the CLI computes count, min, max, mean, p50, and p95
    per monitor (percentiles are nearest-rank) and, with `--budget`, a
    per-monitor pass/fail verdict plus an overall `passed`. The one-frame
    snapshot stays `perf monitors`; the per-node timeline stays `perf monitor`.
    With no daemon it reports `daemon_not_running`.
    """
    params = params_or_bad_parameter(
        PerfSampleParams, frames=frames, monitors=monitors, budget=budget
    )
    dispatch_recipe(
        PERF_SAMPLE_COMMAND,
        params,
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
