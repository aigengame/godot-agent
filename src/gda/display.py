"""Host DisplayServer probe for windowed live sessions (#345).

A windowed [Engine session](../../CONTEXT.md) (``gda daemon start --windowed``)
needs a usable host ``DisplayServer`` to bring up a real viewport; on a host with
none, Godot aborts during ``DisplayServer`` / AppKit registration BEFORE its file
logger is installed, so the failure is otherwise only a generic
``engine_session_not_running`` with an empty log tail (#345 Part A). This module
answers, PRE-LAUNCH, whether THIS host can show a window, so ``gda daemon start
--windowed`` can refuse fast with the typed ``live_windowed_unavailable``
(ENVIRONMENT / exit 127) instead of spawning a doomed engine.

Platform-dispatched (live is UNIX-only via ``live_unsupported_platform``, ADR-0021,
so Windows is a documented, unreachable-today stub seam — a single clean slot, not a
refactor):

- **macOS**: ``CGSessionCopyCurrentDictionary`` (CoreGraphics via ``ctypes`` — no
  extra dependency) returns a non-NULL session dict only for an on-console GUI
  session; it is NULL over SSH and in headless / sandbox sessions **even when**
  ``launchctl managername`` reports "Aqua". So we deliberately do NOT use
  ``launchctl`` or ``$DISPLAY`` on macOS — that NULL is exactly what predicts a
  windowed Godot will abort during window-server registration.
- **Linux**: a non-empty ``$DISPLAY`` (X11) or ``$WAYLAND_DISPLAY`` (Wayland), so a
  run under ``xvfb-run`` (which sets ``DISPLAY``) passes.
- **Windows**: unreachable today; the stub reports "usable" so it never spuriously
  gates on a path live never reaches.
"""

from __future__ import annotations

import ctypes
import os
import sys


def has_usable_display() -> bool:
    """Whether THIS host has a usable ``DisplayServer`` for a windowed session (#345)."""
    if sys.platform == "darwin":
        return _macos_has_window_server()
    if sys.platform.startswith("linux"):
        return _linux_has_display()
    return _other_platform_has_display()


def windowed_unavailable_reason() -> str | None:
    """Why a windowed live session can't come up on THIS host, or ``None`` if it can.

    The single decision point both the ``gda daemon start --windowed`` precondition
    (``daemon_ops``) and the windowed e2e gates key on, so they agree: ``None`` means
    "a windowed session can launch here", a string is the skip/refusal reason.
    """
    if has_usable_display():
        return None
    if sys.platform == "darwin":
        return (
            "no usable macOS window-server session (CGSessionCopyCurrentDictionary "
            "returned NULL — e.g. SSH / CI / sandbox); a windowed Godot session cannot "
            "register with the window server here"
        )
    if sys.platform.startswith("linux"):
        return (
            "headless Linux has no DisplayServer ($DISPLAY / $WAYLAND_DISPLAY unset); "
            "run under a virtual framebuffer such as xvfb-run, which sets DISPLAY"
        )
    return "this host has no usable DisplayServer for a windowed session"


def _macos_has_window_server() -> bool:
    """An on-console macOS GUI session probe via CoreGraphics (no extra dependency).

    ``CGSessionCopyCurrentDictionary`` returns a non-NULL dict only when the calling
    process is attached to an active window-server session; it is NULL over SSH and
    in headless / sandbox sessions even when ``launchctl managername`` reports "Aqua".
    Returns ``True`` on that non-NULL dict (and releases it), ``False`` on NULL. If the
    probe itself cannot run, err towards ``True`` so a real desktop is never falsely
    gated out — the pre-launch check stays advisory, and #345 Part A still catches a
    genuine no-display abort at the session-launch site.
    """
    try:
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        session = cg.CGSessionCopyCurrentDictionary()
    except Exception:
        return True
    if not session:
        return False
    try:  # release the copied CFDictionary to avoid a leak
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease(ctypes.c_void_p(session))
    except Exception:
        pass
    return True


def _linux_has_display() -> bool:
    """A non-empty ``$DISPLAY`` (X11) or ``$WAYLAND_DISPLAY`` (Wayland) — so xvfb-run passes."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _other_platform_has_display() -> bool:
    """Windows stub seam — unreachable today (live is UNIX-only, ADR-0021).

    Live operations gate on a UNIX platform (``live_unsupported_platform``) long
    before this is reached, so a windowed session never launches on Windows. Left as
    a single clean slot to fill when/if a native Windows display probe (e.g.
    ``GetSystemMetrics(SM_CMONITORS)``) is ever wired in; reports "usable" so it never
    spuriously gates on an unreachable path.
    """
    return True
