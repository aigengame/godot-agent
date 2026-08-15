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
from pathlib import Path
from typing import Callable, Optional

import typer
from pydantic import BaseModel, Field

from gda import dispatch
from gda.dispatch import dispatch_recipe
from gda.errors import Failure, classify_live
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


class ScreenCaptureResult(BaseModel):
    """The result of ``gda screen capture``: a written PNG frame (#222).

    The default return: the ``path`` the decoded PNG was written to, its ``width`` /
    ``height`` in pixels, the on-disk ``bytes``, and the ``format`` (``png``).
    ``inline`` carries the base64 PNG only when ``--inline`` was passed (otherwise
    null) — a single capture may be embedded for an in-context preview, but it is
    opt-in so the default reply stays small.
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


class ScreenFramesResult(BaseModel):
    """The result of ``gda screen frames``: the written PNG sequence (#222).

    Carries the ``count`` of frames captured and the per-frame ``frames`` list, each
    a written PNG path (path-only, ADR-0019 distinct output schema from the single
    ``screen capture``). The window collects one frame per frame boundary over the
    requested count (ADR-0020 multi-frame).
    """

    count: int = Field(description="The number of frames captured over the window.")
    frames: list[ScreenFrame] = Field(
        description="The captured frames, in window order, each a written PNG path."
    )


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


class _CaptureReply(BaseModel):
    width: int
    height: int
    format: str = Field(default="png")
    bytes: int
    png_base64: str


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


def _write_png(png_base64: str, destination: Path) -> int:
    """Decode a base64 PNG and write it to ``destination``; return the byte length."""
    raw = base64.b64decode(png_base64)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return len(raw)


def run_screen_capture_operation(
    project: Optional[Path],
    output: Path,
    *,
    inline: bool = False,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "ScreenCaptureResult | Failure":
    """Capture one viewport frame, write it to ``output``, return the typed result.

    The single-frame recipe: run the ``screen-capture`` live op, surface any LIVE
    failure via ``classify_live`` (so ``daemon_not_running`` /
    ``live_display_unavailable`` ride the registered-code pipeline), then decode the
    base64 PNG and write it to ``output``. ``--inline`` additionally embeds the
    base64 in the result; the default reply is path + dims + bytes + format.
    """
    runner = (make_runner or _default_runner)(None, project)
    result = runner.run("screen-capture", {})
    reply = classify_live(result, None, _CaptureReply)
    if isinstance(reply, Failure):
        return reply
    written = _write_png(reply.png_base64, output)
    return ScreenCaptureResult(
        path=str(output),
        width=reply.width,
        height=reply.height,
        bytes=written,
        format=reply.format,
        inline=reply.png_base64 if inline else None,
    )


def run_screen_frames_operation(
    project: Optional[Path],
    frames: int,
    output_dir: Path,
    *,
    make_runner: Optional[LiveRunnerFactory] = None,
) -> "ScreenFramesResult | Failure":
    """Capture a window of ``frames`` viewport frames, write each PNG, return paths.

    The multi-frame recipe (the harness's time-windowed base, #223): run the
    ``screen-frames`` live op, surface any LIVE failure via ``classify_live``, then
    write one PNG per captured frame into ``output_dir`` (``frame_0000.png`` …) and
    return the path-only sequence — no base64, which would blow the agent's context.
    """
    runner = (make_runner or _default_runner)(None, project)
    result = runner.run("screen-frames", {"frames": frames})
    reply = classify_live(result, None, _FramesReply)
    if isinstance(reply, Failure):
        return reply
    written: list[ScreenFrame] = []
    for index, frame in enumerate(reply.frames):
        path = output_dir / f"frame_{index:04d}.png"
        size = _write_png(frame.png_base64, path)
        written.append(
            ScreenFrame(
                path=str(path),
                width=frame.width,
                height=frame.height,
                bytes=size,
                format=frame.format,
            )
        )
    return ScreenFramesResult(count=reply.count, frames=written)


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
        Path(params.output),
        inline=params.inline,
        make_runner=dispatch.make_live_runner,
    )


def _screen_frames_recipe(params, *, project, godot):
    return run_screen_frames_operation(
        project,
        params.frames,
        Path(params.output_dir),
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
    dispatch_recipe(
        SCREEN_CAPTURE_COMMAND,
        ScreenCaptureParams(output=str(output), inline=inline),
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
    dispatch_recipe(
        SCREEN_FRAMES_COMMAND,
        ScreenFramesParams(frames=frames, output_dir=str(output_dir)),
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
