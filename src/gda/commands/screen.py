"""The ``screen`` command group: the running game's VIEWPORT (#222).

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, the two capture operations (formerly ``gda.screen_ops``),
its human renderers, its ``HeadlessCommand`` descriptors (ADR-0023), its recipe
channels and its Typer command bodies, and mounts them on the root app through
:func:`register`. It imports the shared machinery downward — the dispatch tail
(``gda.dispatch``), the descriptor machinery (``gda.headless``), the shared
failure taxonomy (``gda.errors``, whose ``classify_live`` every live group
shares), the live runner (``gda.live_runner``) and the cross-command contract
core (``gda.models``, which keeps the multi-group ``MAX_WINDOW_FRAMES``
ceiling) — and is imported by nothing but the composition root (``gda.cli``).

The viewport is the domain object here (not under ``game``, whose object is the
runtime scene graph). Both commands are LIVE (``kind = LIVE``), routed through
``gda-daemon`` to a WINDOWED engine session (``gda daemon start --windowed``);
on a headless session a capture is the typed ``live_display_unavailable`` (#222).
"""

import base64
import hashlib
import json
from pathlib import Path
from typing import Callable, Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda import dispatch
from gda.commands.input import InputSequenceEvent
from gda.dispatch import dispatch_recipe, params_or_bad_parameter
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
from gda.models import MAX_WINDOW_FRAMES, NormalizedPath
from gda.runner import GodotRunner

# --- screen (runtime viewport capture, #222) ----------------------------------
# Capture the running game's viewport over the LIVE channel. The harness reads
# `get_viewport().get_texture().get_image()`, PNG-encodes it, and base64s the PNG
# into the ADR-0002 UTF-8 sentinel reply; the CLI decodes it and WRITES the PNG
# under the agent's control. The default return is a written file PATH + dims +
# bytes + format — a 1080p base64 inline is ~MBs of JSON and an N-frame sequence
# would blow the agent's context — so `screen capture` adds `--inline` for the
# base64 and `screen frames` is path-only. The capture needs a windowed session
# (`gda daemon start --windowed`); a headless one is `live_display_unavailable`.


# The predicate window's default frame ceiling (#661): ~1 s at 60 fps, and the
# harness applies the same default when the wire omits it. The hard ceiling is
# the shared MAX_WINDOW_FRAMES.
DEFAULT_AWAIT_FRAMES = 60


def _await_schema_extra(schema: dict) -> None:
    """Publish the await validator's cross-field rules into the schema (#743).

    ADR-0015 makes the params model the ONE authority for both runtime
    validation and the published schema, so the model validator's cross-field
    rules must be visible to a standard Draft 2020-12 validator too: supplying
    any of the trio (non-null) requires the whole trio; the ceiling and the
    events need the trio; the events are non-empty and process-clock only. The
    imported event union publishes its scalar constraints, modifier vocabulary,
    and shared total-window offset ceiling. A parity corpus
    (tests/test_screen_commands.py) keeps validator and model agreeing.
    """
    scalar = {"type": ["boolean", "integer", "number", "string"]}
    trio = {
        "properties": {
            "await_node": {"type": "string"},
            "await_property": {"type": "string"},
            "await_value": scalar,
        },
        "required": ["await_node", "await_property", "await_value"],
    }

    def given(name: str, spec: dict) -> dict:
        return {"if": {"properties": {name: spec}, "required": [name]}, "then": trio}

    schema["allOf"] = [
        given("await_node", {"type": "string"}),
        given("await_property", {"type": "string"}),
        given("await_value", scalar),
        given("await_frames", {"type": "integer"}),
        given("await_events", {"type": "array"}),
    ]
    events = schema["properties"]["await_events"]
    for branch in events.get("anyOf", []):
        if branch.get("type") == "array":
            branch["minItems"] = 1
            branch["items"] = {
                "allOf": [
                    branch["items"],
                    {
                        "not": {
                            "properties": {"physics_frame": {"type": "integer"}},
                            "required": ["physics_frame"],
                        }
                    },
                ]
            }


class ScreenCaptureParams(BaseModel):
    """The params of ``gda screen capture``: where to write one viewport frame (#222).

    Captures the running game's current viewport in one frame (frame-coherent,
    ADR-0020). ``output`` is part of the public input contract (ADR-0004) and the
    single source of truth for both the emitted ``input`` schema and ``--params-json``
    parsing (ADR-0015): the CLI decodes the harness's encoded pixels and writes them
    there. It is ``~``-normalized once at the boundary (ADR-0006). The harness op
    itself carries none of these fields — the recipe writes the file CLI-side.
    """

    output: NormalizedPath = Field(
        description="The filesystem path to write the captured PNG frame to."
    )
    inline: bool = Field(
        default=False,
        description="Also embed the base64-encoded PNG in the result (default: path only).",
    )
    await_node: str | None = Field(
        default=None,
        description=(
            "Predicate node: the ABSOLUTE runtime path (e.g. /root/Main/Player) "
            "whose property gates the capture (#661). Needs await_property and "
            "await_value with it."
        ),
    )
    await_property: str | None = Field(
        default=None,
        description=(
            "Predicate property on the await_node — a storage property or an "
            "explicit script variable, exactly what `game get` can read."
        ),
    )
    await_value: "bool | int | float | str | None" = Field(
        default=None,
        description=(
            "Predicate value, a JSON scalar: the capture fires on the first frame "
            "boundary where the property equals it (numbers compare numerically, "
            "strings against the String rendering; null is not supported). The "
            "property and the pixels are read at the SAME boundary — both belong "
            "to the frame that just completed; a game that updates a visual one "
            "frame after the property it gates on trails by that game-side frame, "
            "so gate on the visual's own property when exact pixels matter."
        ),
    )
    await_frames: int | None = Field(
        default=None,
        ge=1,
        le=MAX_WINDOW_FRAMES,
        strict=True,
        description=(
            "The predicate window's frame CEILING (default 60): a predicate that "
            "never holds within it is the typed live_predicate_unmet. Needs the "
            "await predicate."
        ),
    )
    await_events: "list[InputSequenceEvent] | None" = Field(
        default=None,
        description=(
            "The atomic input-and-capture form (#661): input-sequence events "
            "applied inside the SAME predicate window at their process-clock "
            "'frame' offsets, so a 3-8 frame transient triggered by the input "
            "cannot be missed by a second round trip. An event's effect is "
            "observable from the NEXT frame boundary, so leave at least one "
            "frame between the last state-changing event and the ceiling; an "
            "offset at or beyond the predicate ceiling still fires (the reply "
            "waits for every declared event) but can no longer satisfy the "
            f"predicate. Every offset remains at most {MAX_WINDOW_FRAMES - 1}, "
            f"so the total drain stays within the shared {MAX_WINDOW_FRAMES}-frame "
            "live-window ceiling. A declared event that fails makes the whole "
            "capture that typed failure. Physics-clock offsets are not accepted. "
            "Needs the await predicate."
        ),
    )

    model_config = {"json_schema_extra": lambda schema: _await_schema_extra(schema)}

    @model_validator(mode="after")
    def _check_await_group(self) -> "ScreenCaptureParams":
        # Model-side (ADR-0015): argv and --params-json reject identically.
        trio = [
            self.await_node is not None,
            self.await_property is not None,
            self.await_value is not None,
        ]
        if any(trio) and not all(trio):
            raise ValueError(
                "an await predicate needs 'await_node', 'await_property', and "
                "'await_value' together (a JSON null value is not supported)."
            )
        has_await = all(trio)
        if self.await_frames is not None and not has_await:
            raise ValueError(
                "'await_frames' needs the await predicate "
                "(await_node / await_property / await_value)."
            )
        if self.await_events is not None:
            if not has_await:
                raise ValueError(
                    "'await_events' needs the await predicate — without one, "
                    "inject input with `gda input ...` and capture separately."
                )
            if not self.await_events:
                raise ValueError(
                    "'await_events' must be a non-empty list when supplied."
                )
            for event in self.await_events:
                if event.physics_frame is not None:
                    raise ValueError(
                        "a predicate capture applies its events on the process "
                        "clock; 'physics_frame' offsets are not accepted."
                    )
        return self


class ScreenCaptureResult(BaseModel):
    """The result of ``gda screen capture``: a written PNG frame (#222).

    The default return: the ``path`` the decoded PNG was written to, its ``width`` /
    ``height`` in pixels, the on-disk ``bytes``, and the ``format`` (``png``).
    ``inline`` carries the base64 PNG only when ``--inline`` was passed (otherwise
    null) — a single capture may be embedded for an in-context preview, but it is
    opt-in so the default reply stays small. ``receipt`` (#660) is always present:
    the evidence binding this image to the session, scene, frame, and output hash.
    """

    path: str = Field(description="The filesystem path the PNG frame was written to.")
    width: int = Field(description="The captured frame's width in pixels.")
    height: int = Field(description="The captured frame's height in pixels.")
    bytes: int = Field(description="The written PNG's size in bytes.")
    format: str = Field(default="png", description="The image format (png).")
    inline: str | None = Field(
        default=None,
        description="The base64-encoded PNG, present only when --inline was passed.",
    )
    predicate: "CapturePredicateReport | None" = Field(
        default=None,
        description=(
            "The predicate report, present only when --await-* gated this "
            "capture (#661): what held, when, and what was observed."
        ),
    )
    receipt: "CaptureReceipt" = Field(
        description=(
            "The evidence-grade receipt (#660): the identity facts binding THIS "
            "image to the engine session, scene, and frame it came from, plus "
            "the written file's SHA-256 — always present."
        ),
    )


class CaptureReceipt(BaseModel):
    """The capture's evidence receipt (#660, GDA-DF-026/GDA-DF-031).

    Binds one captured image to the capture event in a single result, so a
    downstream consumer can verify the join without hashing files itself: the
    ``session_id`` correlates with ``gda daemon status`` (stable for one
    `Engine session`, minted anew per relaunch — a receipt from a stale
    session is detectable by the mismatch); ``scene_path``/``scene_uid`` are
    the LAUNCHED scene's identity (#660); ``engine_frame`` is the frame the
    pixels belong to; ``sha256`` is the hash of the bytes gda wrote to
    ``path``. For a gated capture the receipt also echoes the predicate's
    ``observed`` value at that same frame; the full predicate evidence (node,
    property, expected) lives in the sibling ``predicate`` report, so a gated
    capture's complete evidence is the pair, receipt + predicate report.
    Every key is always present (required-but-nullable where null is a value).
    """

    session_id: str = Field(
        min_length=1,
        description=(
            "The engine session's identity: minted by gda-daemon at session "
            "launch, stable for the session's lifetime, and readable on "
            "`gda daemon status` for correlation. A relaunch mints a new one."
        ),
    )
    scene_path: str = Field(
        description=(
            "The res:// path of the scene the session LAUNCHED — the same "
            "value the daemon verified at the session handshake (a launch "
            "fact, not a per-frame claim: a game that switches scenes "
            "mid-session still receipts under its launched scene). Empty for "
            "a session that loaded no scene."
        ),
    )
    scene_uid: str | None = Field(
        description=(
            "The launched scene FILE's own uid:// identity, as its header "
            "declares it; null for a scene without a uid header — "
            "gda-authored scenes carry none (ADR-0036). Always present."
        ),
    )
    engine_frame: int = Field(
        ge=0,
        description=(
            "The engine's absolute process-frame counter at the capture "
            "boundary — the frame the image presents. For a gated capture this "
            "is also the predicate's evaluation frame."
        ),
    )
    observed: "bool | int | float | str | None" = Field(
        description=(
            "The predicate echo for a gated capture: the observed value the "
            "predicate matched, evaluated at engine_frame (identical to "
            "predicate.observed). Null on a plain capture. Always present."
        ),
    )
    sha256: str = Field(
        min_length=64,
        max_length=64,
        description=(
            "The SHA-256 hex digest of the PNG bytes gda wrote to `path`, "
            "computed CLI-side over exactly the written bytes."
        ),
    )


class CapturePredicateReport(BaseModel):
    """What a ``--await-*`` predicate observed when the capture fired (#661).

    The synchronization evidence: the frame the predicate held (``engine_frame``
    is the engine's absolute process-frame counter; ``frames_waited`` is the
    window-relative wait), and the property's ``observed`` value at that frame —
    the fields #660's capture receipt echoes onward.
    """

    node: str = Field(description="The awaited node's absolute runtime path.")
    property: str = Field(description="The awaited property's name.")
    expected: "bool | int | float | str" = Field(
        description="The declared predicate value."
    )
    observed: "bool | int | float | str" = Field(
        description=(
            "The property's value on the frame the predicate held (scalars "
            "verbatim; anything else its diagnostic String form). Read at the "
            "same frame boundary as the captured pixels."
        ),
    )
    engine_frame: int = Field(
        ge=0, description="The engine's absolute process-frame counter at capture."
    )
    frames_waited: int = Field(
        ge=0, description="How many window frames passed before the predicate held."
    )


class ScreenFramesParams(BaseModel):
    """The params of ``gda screen frames``: capture a window of viewport frames (#222).

    Time-windowed (the gda harness's multi-frame base, #223): one viewport frame is
    captured at each of ``frames`` frame boundaries and the whole sequence returns
    as one blocking payload (ADR-0017 one-shot RPC, ADR-0020 multi-frame).
    ``frames`` is bounded to ``MAX_WINDOW_FRAMES`` model-side (ADR-0015) — the same
    per-window ceiling ``perf monitor`` enforces — so an over-range request is a
    structured ``invalid_params`` on both the argv and ``--params-json`` paths, never
    a request the harness must clamp.
    """

    frames: int = Field(
        default=2,
        ge=1,
        le=MAX_WINDOW_FRAMES,
        description=(
            "The number of viewport frames to capture, 1.."
            f"{MAX_WINDOW_FRAMES} (the gda harness's per-window ceiling). An "
            "over-range value is rejected, not clamped."
        ),
    )
    output_dir: NormalizedPath = Field(
        description=(
            "The directory to write the captured PNG frames into (frame_NNNN.png). "
            "Part of the input contract (ADR-0004/ADR-0015), ~-normalized (ADR-0006)."
        )
    )
    summary: bool = Field(
        default=False,
        description=(
            "Return the COMPACT completion envelope (#665): every frame is "
            "still captured and written, but the result carries an aggregate "
            "'summary' (directory, filename pattern, frame size, total bytes) "
            "instead of the per-frame 'frames' list — so the envelope does not "
            "grow with the frame count. Default false returns the full list."
        ),
    )


class ScreenFrame(BaseModel):
    """One captured frame in a ``gda screen frames`` sequence (#222).

    The path-only per-frame projection: the ``path`` the decoded PNG was written
    to, its ``width`` / ``height``, on-disk ``bytes``, and ``format``. No base64 —
    an N-frame sequence is path-only so it never blows the agent's context.
    """

    path: str = Field(
        description="The filesystem path this frame's PNG was written to."
    )
    width: int = Field(description="The frame's width in pixels.")
    height: int = Field(description="The frame's height in pixels.")
    bytes: int = Field(description="The written PNG's size in bytes.")
    format: str = Field(default="png", description="The image format (png).")


class ScreenFramesSummary(BaseModel):
    """The compact aggregate of a ``--summary`` frames capture (#665).

    Everything an agent needs to consume the written sequence without a
    per-frame list: where the files are, how each is named, the sequence's
    frame size, and the total bytes on disk. The per-frame ``count`` stays on
    the result itself.
    """

    output_dir: str = Field(
        description="The directory every frame's PNG was written into."
    )
    pattern: str = Field(
        description=(
            "The per-frame filename pattern inside output_dir "
            "(printf-style index, e.g. frame_%04d.png for indices 0..count-1)."
        )
    )
    width: int = Field(
        ge=0, description="The sequence's frame width in pixels (uniform per session)."
    )
    height: int = Field(
        ge=0, description="The sequence's frame height in pixels (uniform per session)."
    )
    total_bytes: int = Field(
        ge=0, description="The written sequence's total size in bytes on disk."
    )


class ScreenFramesResult(BaseModel):
    """The result of ``gda screen frames``: the written PNG sequence (#222).

    Carries the ``count`` of frames captured and — by default — the per-frame
    ``frames`` list, each a written PNG path (path-only, ADR-0019 distinct
    output schema from the single ``screen capture``). With ``--summary``
    (#665) the per-frame list is replaced by the compact aggregate ``summary``,
    so the completion envelope does not grow with the frame count; every frame
    is still captured and written either way. Exactly one of ``frames`` /
    ``summary`` is non-null (both required-but-nullable). The window collects
    one frame per frame boundary over the requested count (ADR-0020
    multi-frame).
    """

    count: int = Field(description="The number of frames captured over the window.")
    frames: "list[ScreenFrame] | None" = Field(
        description=(
            "The captured frames, in window order, each a written PNG path; "
            "null with --summary, whose aggregate replaces the list (#665). "
            "Always present (required-but-nullable)."
        )
    )
    summary: "ScreenFramesSummary | None" = Field(
        description=(
            "The compact aggregate, present only with --summary (#665); null "
            "on the default full-list form. Always present "
            "(required-but-nullable)."
        )
    )

    @model_validator(mode="after")
    def _exactly_one_projection(self) -> "ScreenFramesResult":
        if (self.frames is None) == (self.summary is None):
            raise ValueError(
                "a frames result carries exactly one projection: the per-frame "
                "'frames' list, or the --summary aggregate."
            )
        return self


# --- the capture operations (formerly ``gda.screen_ops``) ---------------------
#
# ``screen capture`` / ``screen frames`` are LIVE ops, but unlike the other live
# commands they cannot go straight through ``HeadlessCommand.emit``: the gda harness
# returns the PNG as base64 in the ADR-0002 sentinel, and the CLI must DECODE it and
# WRITE a file before it has the path-based public result. So each is a recipe that
# RETURNS its typed outcome (never emits/exits) and the CLI owns emission — the same
# shape ``export run`` and the ``daemon`` lifecycle commands use.
#
# The operation runs the shared LIVE runner (the daemon IPC client), classifies the
# raw result against an INTERMEDIATE harness-reply model via ``classify_live`` so
# every LIVE failure (``daemon_not_running``, ``engine_disconnected``,
# ``live_display_unavailable``, …) flows through the one registered-code pipeline,
# then decodes the base64 PNG(s) and writes them under the agent's chosen path. A
# failed capture writes nothing.

# The LIVE runner factory seam, the SAME shape gda.dispatch.make_live_runner has —
# ``(binary, project) -> GodotRunner`` — so the CLI threads its own seam in and a
# test's ``inject_live_runner`` (which patches ``gda.dispatch.make_live_runner``) binds
# without a second injection point. ``binary`` is unused (a live op reaches the
# daemon, not a fresh engine), matching the live channel.
LiveRunnerFactory = Callable[[Optional[Path], Optional[Path]], GodotRunner]


# --- intermediate harness-reply models (the wire shape, decoded CLI-side) -----
# These match exactly what the harness emits in the sentinel: the PNG base64 plus
# the frame's dims/format. They are NOT the public result (the public result is the
# WRITTEN-file projection above); they exist only so the success payload validates
# through classify_live just like any live op, surfacing LIVE errors uniformly.


class _PredicateReply(BaseModel):
    node: str
    property: str
    expected: "bool | int | float | str"
    observed: "bool | int | float | str"
    engine_frame: int = Field(ge=0)
    frames_waited: int = Field(ge=0)


class _ReceiptReply(BaseModel):
    # The harness-side half of the receipt (#660); the CLI adds sha256 after
    # writing the file. `session_id` is required non-empty: every daemon-launched
    # session has one, so a reply without it is a version-skewed or drifted
    # harness — a contract violation, not a capture to trust. The nullable keys
    # are REQUIRED too (the harness always sends them), mirroring the public
    # model's required-but-nullable contract (#746 review).
    session_id: str = Field(min_length=1)
    scene_path: str
    scene_uid: "str | None"
    engine_frame: int = Field(ge=0)
    observed: "bool | int | float | str | None"


class _CaptureReply(BaseModel):
    width: int
    height: int
    format: str = Field(default="png")
    bytes: int
    png_base64: str
    predicate: "_PredicateReply | None" = None
    # Required (#660): a capture reply without the receipt is an old or drifted
    # harness, surfaced as the typed contract_violation by classify_live.
    receipt: "_ReceiptReply"


class _FrameReply(BaseModel):
    width: int
    height: int
    format: str = Field(default="png")
    bytes: int
    png_base64: str


class _FramesReply(BaseModel):
    count: int
    frames: list[_FrameReply]


def _default_runner(binary: Optional[Path], project: Optional[Path]) -> GodotRunner:
    """Build the LIVE runner for ``project`` — the daemon-channel runner factory.

    Matches the ``(binary, project)`` factory shape so the CLI's
    ``make_live_runner`` is a drop-in; ``binary`` is unused (the daemon owns the
    engine session).
    """
    return make_daemon_runner(project)


def _write_png(png_base64: str, destination: Path) -> "tuple[int, str]":
    """Decode a base64 PNG, write it to ``destination``; return (length, sha256 hex).

    The hash is computed over EXACTLY the bytes written (#660): the one writer is
    the one hasher, so the receipt's ``sha256`` can never drift from the file.
    """
    raw = base64.b64decode(png_base64)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _scalars_match(observed: object, expected: object) -> bool:
    """The predicate's JSON-scalar equality, mirrored CLI-side (#661).

    The same rule the harness applies: bools strictly, numbers numerically,
    strings exactly; a null or cross-type pair never matches.
    """
    if isinstance(expected, bool) or isinstance(observed, bool):
        return (
            isinstance(expected, bool)
            and isinstance(observed, bool)
            and (observed is expected)
        )
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        return float(observed) == float(expected)
    if isinstance(expected, str) and isinstance(observed, str):
        return observed == expected
    return False


def _predicate_correlation_error(
    params: "ScreenCaptureParams", predicate: "_PredicateReply | None"
) -> "str | None":
    """Why the reply's predicate report does not answer this request, or None.

    A gated request's success MUST carry the evidence the request asked for
    (#743 review): the report present, naming this node/property/value, with an
    observed value that actually satisfies the declared predicate and a wait
    inside the declared window. A plain request must carry none. Anything else
    is a harness contract violation, refused BEFORE the output file is written.
    """
    if params.await_node is None:
        if predicate is not None:
            return (
                "the harness reply carries a predicate report for a request "
                "that declared no --await predicate"
            )
        return None
    if predicate is None:
        return (
            "the harness reply carries no predicate report for a request "
            "gated on --await-node/--await-property/--await-value"
        )
    bound = (
        params.await_frames if params.await_frames is not None else DEFAULT_AWAIT_FRAMES
    )
    if (
        predicate.node != params.await_node
        or predicate.property != params.await_property
        or not _scalars_match(predicate.expected, params.await_value)
    ):
        return (
            "the harness reply's predicate report does not name the requested "
            f"predicate ({params.await_node}.{params.await_property} == "
            f"{params.await_value!r})"
        )
    if not _scalars_match(predicate.observed, predicate.expected):
        return (
            "the harness reply's predicate report observed "
            f"{predicate.observed!r}, which does not satisfy the declared "
            f"predicate value {predicate.expected!r}"
        )
    if predicate.frames_waited >= bound:
        return (
            f"the harness reply waited {predicate.frames_waited} frames, "
            f"outside the declared window of {bound}"
        )
    return None


def _receipt_correlation_error(
    predicate: "_PredicateReply | None", receipt: "_ReceiptReply"
) -> "str | None":
    """Why the reply's receipt does not answer this request, or None (#660).

    The receipt's predicate echo must agree with the predicate report it rides
    beside — same observed value, same frame — because both claim to describe
    the ONE capture boundary; a reply where they disagree is describing two
    different events and cannot be evidence for either. A plain capture must
    echo nothing (mirroring the unsolicited-predicate refusal). Checked BEFORE
    the output file is written, like the predicate gate.
    """
    if predicate is None:
        if receipt.observed is not None:
            return (
                "the harness reply's receipt echoes a predicate observation "
                f"({receipt.observed!r}) for a request that declared no "
                "--await predicate"
            )
        return None
    if receipt.observed is None or not _scalars_match(
        receipt.observed, predicate.observed
    ):
        return (
            f"the harness reply's receipt echoes {receipt.observed!r}, which "
            f"does not match the predicate report's observed value "
            f"{predicate.observed!r}"
        )
    if receipt.engine_frame != predicate.engine_frame:
        return (
            f"the harness reply's receipt names engine frame "
            f"{receipt.engine_frame}, but the predicate report was evaluated "
            f"at frame {predicate.engine_frame}"
        )
    return None


def run_screen_capture_operation(
    project: Optional[Path],
    params: "ScreenCaptureParams",
    *,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "ScreenCaptureResult | Failure":
    """Capture one viewport frame, write it to ``params.output``, return the result.

    The single-frame recipe: run the ``screen-capture`` live op, surface any LIVE
    failure via ``classify_live`` (so ``daemon_not_running`` /
    ``live_display_unavailable`` — and the predicate's ``live_predicate_unmet``,
    #661 — ride the registered-code pipeline), then decode the base64 PNG and
    write it to ``params.output``. With ``--await-*`` the wire params carry the
    predicate (and the optional atomic input events); the harness holds the
    capture until the predicate's first holding frame, and the reply's
    ``predicate`` report is surfaced on the result. ``--inline`` additionally
    embeds the base64; the default reply is path + dims + bytes + format.
    """
    runner = (make_runner or _default_runner)(None, project)
    op_params: dict[str, object] = {}
    if params.await_node is not None:
        op_params["await"] = {
            "node": params.await_node,
            "property": params.await_property,
            "value": params.await_value,
            "frames": (
                params.await_frames
                if params.await_frames is not None
                else DEFAULT_AWAIT_FRAMES
            ),
        }
        if params.await_events:
            op_params["events"] = [event.model_dump() for event in params.await_events]
    result = runner.run("screen-capture", op_params)
    reply = classify_live(result, None, _CaptureReply)
    if isinstance(reply, Failure):
        return reply
    correlation = _predicate_correlation_error(
        params, reply.predicate
    ) or _receipt_correlation_error(reply.predicate, reply.receipt)
    if correlation is not None:
        return make_failure("contract_violation", correlation, result.stdout)
    output = Path(params.output)
    written, digest = _write_png(reply.png_base64, output)
    return ScreenCaptureResult(
        path=str(output),
        width=reply.width,
        height=reply.height,
        bytes=written,
        format=reply.format,
        inline=reply.png_base64 if params.inline else None,
        predicate=(
            CapturePredicateReport(**reply.predicate.model_dump())
            if reply.predicate is not None
            else None
        ),
        receipt=CaptureReceipt(**reply.receipt.model_dump(), sha256=digest),
    )


def run_screen_frames_operation(
    project: Optional[Path],
    frames: int,
    output_dir: Path,
    *,
    summary: bool = False,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "ScreenFramesResult | Failure":
    """Capture a window of ``frames`` viewport frames, write each PNG, return paths.

    The multi-frame recipe (the harness's time-windowed base, #223): run the
    ``screen-frames`` live op, surface any LIVE failure via ``classify_live``, then
    write one PNG per captured frame into ``output_dir`` (``frame_0000.png`` …) and
    return the path-only sequence — no base64, which would blow the agent's context.
    With ``summary`` (#665) the same frames are captured and written, but the
    result carries the compact aggregate instead of the per-frame list, so the
    completion envelope does not grow with the frame count.
    """
    runner = (make_runner or _default_runner)(None, project)
    result = runner.run("screen-frames", {"frames": frames})
    reply = classify_live(result, None, _FramesReply)
    if isinstance(reply, Failure):
        return reply
    written: list[ScreenFrame] = []
    for index, frame in enumerate(reply.frames):
        path = output_dir / f"frame_{index:04d}.png"
        size, _ = _write_png(frame.png_base64, path)
        written.append(
            ScreenFrame(
                path=str(path),
                width=frame.width,
                height=frame.height,
                bytes=size,
                format=frame.format,
            )
        )
    if summary:
        return ScreenFramesResult(
            count=reply.count,
            frames=None,
            summary=ScreenFramesSummary(
                output_dir=str(output_dir),
                pattern="frame_%04d.png",
                width=written[0].width if written else 0,
                height=written[0].height if written else 0,
                total_bytes=sum(frame.bytes for frame in written),
            ),
        )
    return ScreenFramesResult(count=reply.count, frames=written, summary=None)


def render_screen_capture(captured: "ScreenCaptureResult") -> str:
    """Render a captured viewport frame as ``captured WxH -> path`` (#222).

    The receipt line (#660) carries the binding evidence — session, scene,
    frame, hash — so the human read is verifiable without opening the JSON.
    """
    inline = " (+inline)" if captured.inline else ""
    head = (
        f"captured {captured.width}x{captured.height} "
        f"({captured.bytes} bytes) -> {captured.path}{inline}"
    )
    receipt = captured.receipt
    scene = receipt.scene_path or "(no scene)"
    uid = f" ({receipt.scene_uid})" if receipt.scene_uid else ""
    lines = [
        head,
        (
            f"  receipt session {receipt.session_id} scene {scene}{uid} "
            f"frame {receipt.engine_frame} sha256 {receipt.sha256}"
        ),
    ]
    if captured.predicate is not None:
        pred = captured.predicate
        lines.append(
            f"  predicate {pred.node}.{pred.property} == {pred.expected!r} held "
            f"after {pred.frames_waited} frames "
            f"(engine frame {pred.engine_frame}, observed {pred.observed!r})"
        )
    return "\n".join(lines)


def render_screen_frames(captured: "ScreenFramesResult") -> str:
    """Render a captured frame sequence: a header + one ``WxH -> path`` per frame (#222).

    The ``--summary`` form (#665) renders the aggregate on one line instead of a
    row per frame, mirroring the compact JSON envelope.
    """
    header = f"captured {captured.count} frames"
    if captured.summary is not None:
        aggregate = captured.summary
        return header + (
            f"\n  {aggregate.width}x{aggregate.height} x{captured.count} "
            f"({aggregate.total_bytes} bytes) -> "
            f"{aggregate.output_dir}/{aggregate.pattern}"
        )
    rows = [
        f"  {frame.width}x{frame.height} -> {frame.path}"
        for frame in captured.frames or []
    ]
    return "\n".join([header, *rows])


# --- Recipe channels (ADR-0023) -----------------------------------------------
# Each ``screen`` command carries one of these on its descriptor (``recipe=``). A
# recipe PRODUCES the outcome — run the CLI-side operation over the ALREADY-resolved
# ``project`` (resolution happens once in :func:`gda.dispatch.dispatch_recipe`, kept
# CLI-side per ADR-0006, so an invalid --project is a structured project_not_found
# before any recipe runs, #353) — and RETURNS the typed result or a Failure; emission
# stays the shared tail (:func:`gda.dispatch.dispatch_recipe` → ``cmd.render``), so a
# recipe command renders exactly like a sentinel one. The runner seam
# (``dispatch.make_live_runner``) is referenced at call time — as an attribute on the
# module, never imported by name — so test monkeypatches on
# ``gda.dispatch.make_live_runner`` still bind. ``params`` is the built model — the
# single source of truth (ADR-0015), identical on the argv and ``--params-json`` paths
# — so output/inline/frames are read off it, never special-cased.


def _screen_capture_recipe(params, *, project, godot):
    return run_screen_capture_operation(
        project,
        params,
        make_runner=dispatch.make_live_runner,
    )


def _screen_frames_recipe(params, *, project, godot):
    return run_screen_frames_operation(
        project,
        params.frames,
        Path(params.output_dir),
        summary=params.summary,
        make_runner=dispatch.make_live_runner,
    )


# The `screen` commands are LIVE but run a CLI-side recipe (the operations above),
# not the sentinel pipeline: the harness returns the PNG as base64 in the sentinel
# and the CLI must DECODE + WRITE a file before it has the path-based public result.
# So — like `export run` and the daemon lifecycle commands — each carries a `recipe`
# on its descriptor (ADR-0023): dispatch runs it instead of cmd.emit, selected by the
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


# The screen command group (Phase 2, ADR-0019): the running game's VIEWPORT is the
# domain object (not under `game`, whose object is the runtime scene graph). Both
# commands are LIVE (kind = LIVE), routed through gda-daemon to a WINDOWED engine
# session (`gda daemon start --windowed`); on a headless session a capture is the
# typed `live_display_unavailable` (#222).
_app = typer.Typer(
    help="Capture the running game's viewport (live; macOS/Linux only, windowed session).",
    no_args_is_help=True,
)


@_app.command(name="capture", cls=SCREEN_CAPTURE_COMMAND.command_class())
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
    await_node: Optional[str] = typer.Option(
        None,
        "--await-node",
        help=(
            "Predicate node: the absolute runtime path whose property gates the "
            "capture (#661); needs --await-property and --await-value."
        ),
    ),
    await_property: Optional[str] = typer.Option(
        None,
        "--await-property",
        help="Predicate property on the --await-node (what `game get` can read).",
    ),
    await_value: Optional[str] = typer.Option(
        None,
        "--await-value",
        help=(
            'Predicate value as a JSON scalar (3, 3.5, true, "word"); a bare '
            "word is taken as a string. Capture fires when the property equals it."
        ),
    ),
    await_frames: Optional[int] = typer.Option(
        None,
        "--await-frames",
        help=(
            f"Frame ceiling for the predicate window (default "
            f"{DEFAULT_AWAIT_FRAMES}); an unmet predicate is the typed "
            "live_predicate_unmet."
        ),
    ),
    await_events: Optional[str] = typer.Option(
        None,
        "--await-events",
        help=(
            "JSON list of input-sequence events applied INSIDE the predicate "
            "window at their process-clock 'frame' offsets — the atomic "
            "input-and-capture form (same shapes as `gda input sequence`)."
        ),
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
    + dims + bytes + format. `--inline` also embeds the base64.

    Every result carries an evidence receipt (#660) binding the image to its
    capture event: the engine session's identity (the same `session_id` that
    `gda daemon status` reports; a new session mints a new one), the LAUNCHED
    scene's path and header uid (uid null when the project provides none), the
    engine frame the pixels belong to, and the written file's SHA-256. A gated
    capture's receipt also echoes the predicate's observed value at that same
    frame; the full predicate evidence is the sibling `predicate` report.

    The `--await-*` predicate (#661) holds the capture game-side until
    `node.property == value` first holds (checked once per process frame, up to
    `--await-frames`), then captures at that SAME frame boundary — the property
    and the pixels both belong to the frame that just completed — and reports
    the predicate evidence; a predicate that never holds is the typed
    `live_predicate_unmet`. `--await-events` additionally injects input-sequence
    events inside the same window (the atomic input-and-capture form) so a short
    transient triggered by the input cannot be missed by a second round trip;
    every declared event fires before the reply, even when the predicate
    matches first, and a declared event that fails makes the whole capture that
    typed failure. Each tick evaluates BEFORE it injects, so the observed
    property and the captured pixels always belong to the same completed frame
    (state an event writes is observed one boundary later, with its
    presentation). Needs a WINDOWED
    session (`gda daemon start --windowed`); a headless one is
    `live_display_unavailable`. With no daemon it reports `daemon_not_running`.
    """
    # Build the params model from the argv options so `output` is validated and
    # ~-normalized through the SAME single source of truth the --params-json path
    # uses (ADR-0015/ADR-0006) — not a raw, un-normalized Path. The value flag is
    # a JSON scalar (a bare word falls back to a string); the events flag is a
    # JSON list — both validated by the model, so argv and --params-json reject
    # identically. Dispatch through the descriptor's recipe (ADR-0023).
    value: object = None
    if await_value is not None:
        try:
            value = json.loads(await_value)
        except ValueError:
            value = await_value
    events: object = None
    if await_events is not None:
        try:
            events = json.loads(await_events)
        except ValueError:
            events = await_events  # not JSON: the model refuses it structurally
    params = params_or_bad_parameter(
        ScreenCaptureParams,
        output=str(output),
        inline=inline,
        await_node=await_node,
        await_property=await_property,
        await_value=value,
        await_frames=await_frames,
        await_events=events,
    )
    dispatch_recipe(
        SCREEN_CAPTURE_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="frames", cls=SCREEN_FRAMES_COMMAND.command_class())
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
    summary: bool = typer.Option(
        False,
        "--summary",
        help=(
            "Return the compact completion envelope (#665): all frames are "
            "still written, but the result carries an aggregate summary "
            "instead of the per-frame list, so it does not grow with --frames."
        ),
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
    the agent's context). `--summary` (#665) keeps the completion envelope
    COMPACT for large captures: every frame is still written, and the result
    carries the aggregate (directory, filename pattern, frame size, total
    bytes) instead of the per-frame list. Needs a WINDOWED session; a headless
    one is `live_display_unavailable`. With no daemon it reports
    `daemon_not_running`.
    """
    # Same params model the --params-json path builds (ADR-0015): `output_dir` is
    # validated and ~-normalized through it, not passed as a raw Path. Dispatch
    # through the descriptor's recipe, exactly as the --params-json path (ADR-0023).
    dispatch_recipe(
        SCREEN_FRAMES_COMMAND,
        ScreenFramesParams(frames=frames, output_dir=str(output_dir), summary=summary),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``screen`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="screen")
