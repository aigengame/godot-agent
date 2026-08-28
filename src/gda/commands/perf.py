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
the engine session it holds. ``perf monitors`` has two modes on one surface
(#662's triage decision — no third command): with no ``--frames`` it snapshots
the engine's ``Performance`` counters in one frame; with ``--frames N`` it
samples the selected monitors once per frame over a bounded window, and the
CLI computes aggregate statistics plus — with a budget file — per-monitor
pass/fail verdicts. That window mode runs as a CLI-side recipe (ADR-0023, the
``screen`` pattern): the harness returns only the raw timestamped samples, and
the numeric semantics stay unit-testable without an engine. ``perf monitor``
collects a per-frame property/signal timeline for ONE NODE over N frames (the
time-windowed multi-frame harness base, ADR-0020).
"""

import json
import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Optional

import typer
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

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
from gda.models import MAX_WINDOW_FRAMES, RUNTIME_NODE_DESC, NormalizedPath
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


# `perf monitors`' params and result live BELOW the windowed-mode models they
# reference (#662): one command carries both the one-frame snapshot and the
# bounded window, per the issue's triage decision (no third command).


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


# --- perf monitors --frames (windowed engine-monitor sampling, #662) -----------


# The engine performance monitors the gda harness exposes, by public name — the
# CLI-side mirror of the harness's ``_perf_monitors`` table (gda-owned constants,
# not engine-queried), so ``perf monitors --monitor`` validates model-side
# (ADR-0015) and an unknown name never costs a live round trip. A sync test
# (tests/test_error_registry.py) parses the harness table and holds the two
# identical, the same way MAX_WINDOW_FRAMES is mirrored.
class PerfMonitorName(StrEnum):
    """The engine performance monitors the gda harness exposes, by public name.

    The ONE authority for the vocabulary (#735 recheck 2): the params type the
    schema enumerates, the mirrored tuple below, and the harness sync test all
    derive from these members, so an unknown name fails the published input
    contract exactly as ``--params-json`` refuses it.
    """

    fps = "fps"
    process_time = "process_time"
    physics_process_time = "physics_process_time"
    static_memory = "static_memory"
    static_memory_max = "static_memory_max"
    object_count = "object_count"
    node_count = "node_count"
    orphan_node_count = "orphan_node_count"
    resource_count = "resource_count"
    draw_calls = "draw_calls"
    objects_in_frame = "objects_in_frame"
    primitives_in_frame = "primitives_in_frame"
    video_memory = "video_memory"
    physics_2d_active_objects = "physics_2d_active_objects"
    physics_3d_active_objects = "physics_3d_active_objects"
    navigation_active_maps = "navigation_active_maps"


PERF_MONITOR_NAMES: tuple[str, ...] = tuple(member.value for member in PerfMonitorName)


def _json_integer(value: object) -> object:
    """Admit exactly what JSON Schema's ``integer`` admits (#735 recheck 2).

    Pydantic's lax ``int`` coerces ``"5"`` and ``true`` — objects the emitted
    schema rejects — while its STRICT ``int`` refuses ``5.0``, which JSON
    Schema's ``integer`` accepts (any number with a zero fractional part). The
    published contract and the verbatim ``--params-json`` ABI must admit the
    SAME objects (ADR-0015), so this validator implements the schema's
    semantics: integers and integral floats pass, booleans and strings do not.
    """
    if isinstance(value, bool):
        raise ValueError("must be a JSON integer, not a boolean")
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError("must be a JSON integer (no fractional part)")
    if value is None or isinstance(value, int):
        return value
    raise ValueError("must be a JSON integer")


# The window's frame count as ONE annotated type: the range markers come
# BEFORE the validator in the metadata, which is the ordering pydantic can
# translate into standard JSON Schema `minimum`/`maximum` keywords — with the
# validator first, the emitted schema carries raw `ge`/`le` keys that standard
# validators ignore, silently dropping the published range (#735 recheck 3).
# At runtime the BeforeValidator still runs first, so the range applies to the
# already-normalized integer.
FrameWindow = Annotated[
    int, Field(ge=1, le=MAX_WINDOW_FRAMES), BeforeValidator(_json_integer)
]

# The statistics a budget rule may gate on — the aggregate set minus ``count``,
# which counts frames rather than measuring the monitor.
BudgetStat = Literal["min", "max", "mean", "p50", "p95"]

_FRAMES_DESC = (
    f"The number of frames to sample over, 1..{MAX_WINDOW_FRAMES} (the gda "
    "harness's per-window ceiling). An over-range value is rejected, not clamped."
)


# The params' mode rules, stated as JSON-Schema conditionals so a client can
# CHECK them rather than read them (the #669 mouse-button-phase pattern): a
# non-empty selection or a budget requires an integer `frames`. They mirror
# `_check_modes` below, which stays the enforcing authority; a parity test runs
# one corpus through the emitted schema and the model and requires the same
# verdict, so the two cannot drift (ADR-0015: the published input contract must
# not be wider than the ABI --params-json actually accepts).
_PERF_MONITORS_MODE_SCHEMA: dict[str, Any] = {
    "allOf": [
        {
            "if": {
                "required": ["monitors"],
                "properties": {"monitors": {"minItems": 1}},
            },
            "then": {
                "required": ["frames"],
                "properties": {"frames": {"type": "integer"}},
            },
        },
        {
            "if": {
                "required": ["budget"],
                "properties": {"budget": {"type": "string"}},
            },
            "then": {
                "required": ["frames"],
                "properties": {"frames": {"type": "integer"}},
            },
        },
    ]
}


class PerfMonitorsParams(BaseModel):
    """The params of ``gda perf monitors``: a snapshot, or a bounded window (#223, #662).

    One command, two modes, per #662's triage decision (no third command; the
    snapshot is the degenerate one-sample window). With no ``frames``, the
    original behavior: the whole instantaneous monitor set, read in a single
    frame (frame-coherent, ADR-0020). With ``frames``, the WINDOW mode: the gda
    harness reads every selected monitor once per frame over the window and
    returns the raw timestamped samples; the CLI computes the aggregate
    statistics and, when ``budget`` is supplied, the per-monitor pass/fail
    verdicts. An empty ``monitors`` selection samples ALL monitors;
    ``monitors`` and ``budget`` require ``frames`` (refused by name otherwise —
    a silently inert selection would be worse; the rule is also PUBLISHED as
    schema conditionals, so a client validating against ``--schema`` reaches
    the same verdict). Monitor names and the ``frames`` bound are enforced
    model-side (ADR-0015).
    """

    model_config = ConfigDict(json_schema_extra=_PERF_MONITORS_MODE_SCHEMA)

    frames: Optional[FrameWindow] = Field(default=None, description=_FRAMES_DESC)
    monitors: list[PerfMonitorName] = Field(
        default_factory=list,
        description=(
            "The performance monitors to sample (repeatable; window mode only); "
            f"empty samples ALL monitors. Known names: {', '.join(PERF_MONITOR_NAMES)}."
        ),
    )
    budget: Optional[NormalizedPath] = Field(
        default=None,
        description=(
            "Path to a JSON budget file (window mode only): an object of "
            "{monitor: {stat, min?, max?}} entries, where stat is one of min, "
            "max, mean, p50, p95, at least one bound is set, keys are unique, "
            "and bounds are finite numbers. Each budgeted monitor gets a "
            "pass/fail verdict against the chosen statistic; the verdict is "
            "data (the command still exits 0)."
        ),
    )

    @model_validator(mode="after")
    def _check_modes(self) -> "PerfMonitorsParams":
        if self.frames is None and self.monitors:
            raise ValueError(
                "'monitors' selects what a WINDOW samples; pass 'frames' to "
                "open one (a snapshot always reads all monitors)."
            )
        if self.frames is None and self.budget is not None:
            raise ValueError(
                "'budget' gates a WINDOW's statistics; pass 'frames' to open one."
            )
        # An unknown name is refused by the PerfMonitorName enum itself (one
        # schema-derived authority), so no name check is repeated here.
        # A repeated name is idempotent (the same counter read once per frame),
        # so it is normalized away rather than refused.
        self.monitors = list(dict.fromkeys(self.monitors))
        return self


class PerfBudget(BaseModel):
    """One monitor's budget rule: gate a statistic with a min and/or max bound.

    ``stat`` is REQUIRED — a defaulted statistic would let a release gate pass
    against a number nobody chose. The rule passes when the statistic is >= the
    ``min`` bound (if set) and <= the ``max`` bound (if set). Bounds must be
    JSON NUMBERS (integer or fractional; STRICT — a quoted ``"10"`` or a
    boolean is refused, never coerced into a gate nobody wrote), must be
    FINITE (an infinity — a JSON ``Infinity`` literal or an exponent-overflow
    like ``1e999`` — or a ``NaN`` is not a representable gate, and the public
    result could not even serialize it), and must form a POSSIBLE interval
    (``min <= max`` when both are set — a gate no observation can satisfy is a
    misconfiguration, not a performance failure).
    """

    model_config = ConfigDict(extra="forbid")

    stat: BudgetStat
    min: float | None = Field(default=None, strict=True)
    max: float | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def _bounds_are_usable(self) -> "PerfBudget":
        if self.min is None and self.max is None:
            raise ValueError("a budget entry needs 'min' and/or 'max'.")
        for label, bound in (("min", self.min), ("max", self.max)):
            if bound is not None and not math.isfinite(bound):
                raise ValueError(
                    f"budget bound '{label}' must be a finite number, not {bound!r}."
                )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(
                f"budget bounds form an impossible interval: min {self.min} > "
                f"max {self.max}."
            )
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
    """One per-frame row of a ``perf monitors --frames`` window: every selected monitor at one frame."""

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


# The result's mode split, stated as JSON Schema so a client — and gda-mcp,
# whose wire schemas derive from this model (ADR-0004) — cannot accept a shape
# the runtime would refuse: each mode requires its own fields and pins the
# other's to null, and a window's budget/passed travel together. Mirrors
# `_mode_fields` below (the enforcing authority); the parity test holds the
# two to the same verdict.
_PERF_MONITORS_RESULT_MODE_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "required": ["kind", "timestamp", "monitors"],
            "properties": {
                "kind": {"const": "snapshot"},
                "timestamp": {"type": "integer"},
                "monitors": {"type": "object"},
                "frames": {"type": "null"},
                "max_frames": {"type": "null"},
                "stats": {"type": "null"},
                "samples": {"type": "null"},
                "budget": {"type": "null"},
                "passed": {"type": "null"},
            },
        },
        {
            "required": ["kind", "frames", "max_frames", "stats", "samples"],
            "properties": {
                "kind": {"const": "window"},
                "timestamp": {"type": "null"},
                "monitors": {"type": "null"},
                "frames": {"type": "integer"},
                "max_frames": {"type": "integer"},
                "stats": {"type": "object"},
                "samples": {"type": "array"},
            },
            "allOf": [
                {
                    "if": {
                        "required": ["budget"],
                        "properties": {"budget": {"type": "object"}},
                    },
                    "then": {
                        "required": ["passed"],
                        "properties": {"passed": {"type": "boolean"}},
                    },
                },
                {
                    "if": {
                        "required": ["passed"],
                        "properties": {"passed": {"type": "boolean"}},
                    },
                    "then": {
                        "required": ["budget"],
                        "properties": {"budget": {"type": "object"}},
                    },
                },
            ],
        },
    ]
}


class PerfMonitorsResult(BaseModel):
    """The result of ``gda perf monitors``: a snapshot, or a window's statistics (#223, #662).

    ``kind`` names the mode. A ``snapshot`` (no ``--frames``) carries
    ``timestamp`` + ``monitors`` — the original one-frame shape, values mutually
    coherent. A ``window`` carries ``frames`` (sampled), ``max_frames`` (the
    per-window ceiling the bound inherits), ``stats`` (aggregates per monitor),
    ``samples`` (the raw timestamped rows the aggregates were computed from),
    and — with a budget — ``budget`` verdicts plus the overall ``passed``. Each
    mode's field set is VALIDATED, not merely described — a payload mixing the
    modes fails output validation rather than passing through — and the same
    split is PUBLISHED as schema, so a client checking ``--schema`` (or the
    gda-mcp wire schema derived from it) reaches the verdict the runtime does.
    """

    model_config = ConfigDict(json_schema_extra=_PERF_MONITORS_RESULT_MODE_SCHEMA)

    kind: Literal["snapshot", "window"] = Field(
        description="The mode: 'snapshot' (one frame) or 'window' (a bounded window)."
    )
    timestamp: int | None = Field(
        default=None,
        description=(
            "Engine time the snapshot was taken (ms, Time.get_ticks_msec); "
            "null in window mode."
        ),
    )
    monitors: dict[str, PerfMonitor] | None = Field(
        default=None,
        description=(
            "The snapshot's performance monitors, keyed by name; null in window mode."
        ),
    )
    frames: int | None = Field(
        default=None,
        description="The number of frames the window sampled; null in snapshot mode.",
    )
    max_frames: int | None = Field(
        default=None,
        description=(
            "The per-window ceiling the frames bound inherits (the gda "
            "harness's MAX_WINDOW_FRAMES); null in snapshot mode."
        ),
    )
    stats: dict[str, PerfSampleStats] | None = Field(
        default=None,
        description=(
            "Aggregate statistics per sampled monitor, keyed by name; null in "
            "snapshot mode."
        ),
    )
    samples: list[PerfSampleFrame] | None = Field(
        default=None,
        description=("The raw timestamped per-frame samples; null in snapshot mode."),
    )
    budget: dict[str, PerfBudgetVerdict] | None = Field(
        default=None,
        description=(
            "Per-monitor budget verdicts; null when no budget was supplied "
            "(and always null in snapshot mode)."
        ),
    )
    passed: bool | None = Field(
        default=None,
        description=(
            "Whether every budget verdict passed; null when no budget was "
            "supplied. A failed budget is data — the command still exits 0."
        ),
    )

    @model_validator(mode="after")
    def _mode_fields(self) -> "PerfMonitorsResult":
        snapshot_fields = (self.timestamp, self.monitors)
        window_fields = (self.frames, self.max_frames, self.stats, self.samples)
        if self.kind == "snapshot":
            if any(field is None for field in snapshot_fields):
                raise ValueError("a snapshot carries 'timestamp' and 'monitors'.")
            if any(field is not None for field in window_fields) or (
                self.budget is not None or self.passed is not None
            ):
                raise ValueError("a snapshot carries no window fields.")
        else:
            if any(field is None for field in window_fields):
                raise ValueError(
                    "a window carries 'frames', 'max_frames', 'stats', and 'samples'."
                )
            if any(field is not None for field in snapshot_fields):
                raise ValueError("a window carries no snapshot fields.")
            if (self.budget is None) != (self.passed is None):
                raise ValueError(
                    "'budget' and 'passed' are set together or not at all."
                )
        return self


# The wire op the window mode dispatches (#662). Named once: the recipe sends
# it, and tests/test_live_contract_guards.py counts it into the relayed-op
# mirror — `perf monitors`' descriptor operation is the snapshot op, so this is
# the one harness op a recipe reaches beside its descriptor's own.
PERF_SAMPLE_OP = "perf-sample"

# The LIVE runner factory seam, the same shape ``gda.dispatch.make_live_runner``
# has (the ``screen`` pattern), so a test's ``inject_live_runner`` binds without
# a second injection point; ``binary`` is unused on the live channel.
LiveRunnerFactory = Callable[[Optional[Path], Optional[Path]], GodotRunner]


class _SnapshotReply(BaseModel):
    """The wire shape ``perf-monitors`` returns: the original one-frame snapshot.

    Not the public result — the recipe wraps it into the two-mode
    :class:`PerfMonitorsResult` with ``kind: "snapshot"``.
    """

    timestamp: int
    monitors: dict[str, PerfMonitor]


class _SampleReply(BaseModel):
    """The wire shape ``perf-sample`` returns: the raw samples, pre-statistics.

    Not the public result — the recipe assembles :class:`PerfMonitorsResult`
    CLI-side. The reply's SELF-consistency is validated here (the #732 lesson):
    the declared window length matches the rows, the rows are exactly frames
    0..N-1 in order, the declared monitors are unique, and every row carries
    exactly them — so a drifted harness classifies as ``contract_violation``
    instead of producing statistics over partial data. Correlation with the
    REQUEST (the frame count and selection actually asked for) is the recipe's
    check, since only it holds the params.
    """

    kind: Literal["sample"]
    frames: int = Field(ge=1)
    monitors: list[str] = Field(min_length=1)
    samples: list[PerfSampleFrame]

    @model_validator(mode="after")
    def _coherent(self) -> "_SampleReply":
        if self.frames != len(self.samples):
            raise ValueError("frames must equal the number of sample rows.")
        if [sample.frame for sample in self.samples] != list(range(self.frames)):
            raise ValueError("sample rows must be exactly frames 0..N-1, in order.")
        if len(set(self.monitors)) != len(self.monitors):
            raise ValueError("the declared monitors must be unique.")
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


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse a JSON object with a repeated key, at any nesting depth.

    ``json.loads`` silently resolves duplicates last-key-wins, which would let a
    budget file that first sets a real bound and then repeats the key with a
    vacuous one pass a release gate nobody wrote. Applied via
    ``object_pairs_hook``, so nested objects (a budget entry) are covered too.
    """
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key {key!r} in a JSON object")
        obj[key] = value
    return obj


def _reject_json_constants(constant: str) -> float:
    """Refuse the JSON-extension constants ``Infinity`` / ``-Infinity`` / ``NaN``.

    They are not JSON, and a non-finite bound is not a representable gate; the
    finite-bound rule itself lives on :class:`PerfBudget` (which also catches an
    exponent-overflow like ``1e999`` that arrives as an ordinary float).
    """
    raise ValueError(f"non-finite JSON constant {constant!r} is not allowed")


def _load_budgets(path: Path) -> "dict[str, PerfBudget] | Failure":
    """Read and validate a budget file, or the structured ``invalid_params``.

    The file is read here — in the recipe, shared by the argv and
    ``--params-json`` paths — so a missing, unreadable, mis-encoded, or
    malformed budget is the same structured error on both (ADR-0015's intent
    for a file-borne input). Admission is strict: UTF-8 only, unique keys at
    every depth, no non-finite numbers.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        return make_failure(
            "invalid_params", f"cannot read the budget file {path}: {exc}", ""
        )
    except UnicodeDecodeError as exc:
        return make_failure(
            "invalid_params",
            f"the budget file {path} is not valid UTF-8: {exc}",
            "",
        )
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constants,
        )
    except ValueError as exc:
        # JSONDecodeError and the two admission hooks above all raise ValueError.
        return make_failure(
            "invalid_params", f"the budget file {path} is not valid JSON: {exc}", ""
        )
    except RecursionError:
        # A pathologically nested document blows the decoder's stack, which is
        # not a ValueError — without this arm it would escape the structured
        # failure contract as a raw traceback.
        return make_failure(
            "invalid_params",
            f"the budget file {path} nests too deeply to be a budget.",
            "",
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


def run_perf_monitors_operation(
    project: Optional[Path],
    params: PerfMonitorsParams,
    *,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "PerfMonitorsResult | Failure":
    """Snapshot the monitors, or sample them over a window with statistics (#223, #662).

    The recipe behind ``perf monitors``' two modes. No ``frames``: run the
    original ``perf-monitors`` snapshot op and wrap it. With ``frames``:
    validate the budget FIRST (a bad budget must not cost a live window), run
    the ``perf-sample`` window op, CORRELATE the reply with the request (a
    self-consistent reply for a different request is still a
    ``contract_violation``), then compute the statistics from the raw samples
    and evaluate the budget against them.
    """
    runner = (make_runner or _default_runner)(None, project)
    if params.frames is None:
        result = runner.run("perf-monitors", {})
        snapshot = classify_live(result, None, _SnapshotReply)
        if isinstance(snapshot, Failure):
            return snapshot
        return PerfMonitorsResult(
            kind="snapshot",
            timestamp=snapshot.timestamp,
            monitors=snapshot.monitors,
        )

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
    result = runner.run(
        PERF_SAMPLE_OP, {"frames": params.frames, "monitors": params.monitors}
    )
    reply = classify_live(result, None, _SampleReply)
    if isinstance(reply, Failure):
        return reply
    # Correlate the (self-consistent) reply with THIS request: the harness must
    # have sampled the asked-for window over the asked-for selection. Only the
    # recipe holds the params, so this check cannot live on the reply model.
    if reply.frames != params.frames:
        return make_failure(
            "contract_violation",
            f"the harness sampled {reply.frames} frames for a "
            f"{params.frames}-frame request.",
            "",
        )
    expected = [str(name) for name in params.monitors] or list(PERF_MONITOR_NAMES)
    if reply.monitors != expected:
        return make_failure(
            "contract_violation",
            f"the harness sampled monitors {reply.monitors} for a request "
            f"selecting {expected}.",
            "",
        )
    stats = {
        name: _stats_over([sample.values[name] for sample in reply.samples])
        for name in reply.monitors
    }
    budget_verdicts: dict[str, PerfBudgetVerdict] | None = None
    passed: bool | None = None
    if budgets is not None:
        budget_verdicts, passed = _evaluate_budgets(budgets, stats)
    return PerfMonitorsResult(
        kind="window",
        frames=reply.frames,
        max_frames=MAX_WINDOW_FRAMES,
        stats=stats,
        samples=reply.samples,
        budget=budget_verdicts,
        passed=passed,
    )


def _perf_monitors_recipe(params, *, project, godot):
    return run_perf_monitors_operation(
        project, params, make_runner=dispatch.make_live_runner
    )


def render_perf_monitors(outcome: "PerfMonitorsResult") -> str:
    """Render a snapshot as ``name = value`` lines, or a window as its statistics.

    Snapshot mode (#223): a flat list of the running game's monitors, sorted by
    name, headed by the snapshot timestamp. Window mode (#662): one statistics
    line per monitor, plus the budget verdicts when a budget was supplied.
    """
    if outcome.kind == "snapshot":
        assert outcome.monitors is not None  # the mode validator guarantees it
        header = f"perf @ {outcome.timestamp}ms"
        lines = [
            f"  {name} = {format_value(monitor.value)}"
            for name, monitor in sorted(outcome.monitors.items())
        ]
        return "\n".join([header, *lines])
    assert outcome.stats is not None  # the mode validator guarantees it
    header = (
        f"perf window: {outcome.frames} frames, {len(outcome.stats)} monitors "
        f"(ceiling {outcome.max_frames})"
    )
    lines = [
        f"  {name}: mean {format_value(stats.mean)}, p50 {format_value(stats.p50)}, "
        f"p95 {format_value(stats.p95)}, min {format_value(stats.min)}, "
        f"max {format_value(stats.max)} ({stats.count} samples)"
        for name, stats in sorted(outcome.stats.items())
    ]
    if outcome.budget is not None:
        lines.append(f"  budget: {'PASS' if outcome.passed else 'FAIL'}")
        for name, verdict in sorted(outcome.budget.items()):
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


# `perf monitors` is LIVE but runs a CLI-side recipe (the `screen` pattern,
# ADR-0023): one command carries both modes (#662's triage decision — no third
# command), and the window mode's statistics and budget verdicts are computed
# CLI-side, so the public result is assembled here rather than relayed
# verbatim. The recipe still runs the sentinel ops (`perf-monitors` /
# `perf-sample`), like `script validate` does. `kind = LIVE` stays a
# descriptor fact so "kind":"live" appears in --schema.
PERF_MONITORS_COMMAND: HeadlessCommand[PerfMonitorsResult] = HeadlessCommand(
    operation="perf-monitors",
    input_model=PerfMonitorsParams,
    output_model=PerfMonitorsResult,
    render=render_perf_monitors,
    kind=ExecutionKind.LIVE,
    recipe=_perf_monitors_recipe,
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
    frames: Optional[int] = typer.Option(
        None,
        "--frames",
        min=1,
        max=MAX_WINDOW_FRAMES,
        help=(
            f"Sample over a window of this many frames, 1..{MAX_WINDOW_FRAMES} "
            "(the gda harness's per-window ceiling); omit for the one-frame "
            "snapshot."
        ),
    ),
    monitors: list[str] = typer.Option(
        [],
        "--monitor",
        help=(
            "A performance monitor to sample (repeatable; window mode only); "
            "omit to sample ALL monitors. Unknown names are rejected before "
            "dispatch."
        ),
    ),
    budget: Optional[str] = typer.Option(
        None,
        "--budget",
        help=(
            "Path to a JSON budget file (window mode only): {monitor: {stat, "
            "min?, max?}}, stat one of min, max, mean, p50, p95; unique keys, "
            "finite bounds. Adds per-monitor pass/fail verdicts; a failed "
            "budget is data (exit stays 0)."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = PERF_MONITORS_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Snapshot the performance monitors, or sample them over a frame window (live).

    Routes through gda-daemon to the engine session (kind = LIVE, ADR-0017).
    Without `--frames`: the original snapshot — the instantaneous Performance
    counters (fps, frame timing, memory, object/node counts, render stats,
    active physics/navigation objects) read in one frame, mutually coherent
    (ADR-0020). With `--frames N`: the WINDOW mode (#662) — the gda harness
    reads every selected monitor once per frame over the window (up to the
    per-window ceiling stated above) and the CLI computes count, min, max,
    mean, p50, and p95 per monitor (percentiles are nearest-rank), plus — with
    `--budget` — a per-monitor pass/fail verdict and an overall `passed`.
    `--monitor` and `--budget` require `--frames`. Live ops need a running
    daemon: with none, it reports `daemon_not_running`.

    Monitor readings cross the live wire at full binary64 precision — the reply is
    serialized with Godot's full-precision JSON writer, so a small or many-digit
    value reads back exactly (#752). The one residual: a NEGATIVE ZERO reads back
    as 0.0, which the engine's writer decides before gda sees the value.
    """
    params = params_or_bad_parameter(
        PerfMonitorsParams, frames=frames, monitors=monitors, budget=budget
    )
    dispatch_recipe(
        PERF_MONITORS_COMMAND,
        params,
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

    Recorded values cross the live wire at full binary64 precision — the reply is
    serialized with Godot's full-precision JSON writer, so a small or many-digit
    value reads back exactly (#752). The one residual: a NEGATIVE ZERO reads back
    as 0.0, which the engine's writer decides before gda sees the value.
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
