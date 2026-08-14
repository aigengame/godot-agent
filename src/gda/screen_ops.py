"""The ``gda screen`` capture recipe (#222), parallel to ``daemon_ops`` / ``export_run``.

``screen capture`` / ``screen frames`` are LIVE ops, but unlike the other live
commands they cannot go straight through ``HeadlessCommand.emit``: the gda harness
returns the PNG as base64 in the ADR-0002 sentinel, and the CLI must DECODE it and
WRITE a file before it has the path-based public result. So each is a recipe that
RETURNS its typed outcome (never emits/exits) and the CLI owns emission — the same
shape ``export run`` and the ``daemon`` lifecycle commands use.

The recipe runs the shared LIVE runner (the daemon IPC client), classifies the raw
result against an INTERMEDIATE harness-reply model via ``classify_live`` so every
LIVE failure (``daemon_not_running``, ``engine_disconnected``,
``live_display_unavailable``, …) flows through the one registered-code pipeline,
then decodes the base64 PNG(s) and writes them under the agent's chosen path. A
failed capture writes nothing.
"""

import base64
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from gda.errors import Failure, classify_live
from gda.live_runner import make_daemon_runner
from gda.models import (
    ScreenCaptureResult,
    ScreenFrame,
    ScreenFramesResult,
)
from gda.runner import GodotRunner

# The LIVE runner factory seam, the SAME shape gda.dispatch._make_live_runner has —
# ``(binary, project) -> GodotRunner`` — so the CLI threads its own seam in and a
# test's ``inject_live_runner`` (which patches ``gda.dispatch._make_live_runner``) binds
# without a second injection point. ``binary`` is unused (a live op reaches the
# daemon, not a fresh engine), matching the live channel.
LiveRunnerFactory = Callable[[Optional[Path], Optional[Path]], GodotRunner]


# --- intermediate harness-reply models (the wire shape, decoded CLI-side) -----
# These match exactly what the harness emits in the sentinel: the PNG base64 plus
# the frame's dims/format. They are NOT the public result (the public result is the
# WRITTEN-file projection below); they exist only so the success payload validates
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
    ``_make_live_runner`` is a drop-in; ``binary`` is unused (the daemon owns the
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
