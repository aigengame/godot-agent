"""Host DisplayServer probe for windowed live sessions (#345, #667).

A windowed [Engine session](../../CONTEXT.md) (``gda daemon start --windowed``)
needs a usable host ``DisplayServer`` to bring up a real viewport; on a host with
none, Godot aborts during ``DisplayServer`` / AppKit registration BEFORE its file
logger is installed, so the failure is otherwise only a generic
``engine_session_not_running`` with an empty log tail (#345 Part A). This module
answers, PRE-LAUNCH, whether THIS host can show a window, so ``gda daemon start
--windowed`` can refuse fast with a typed ENVIRONMENT failure (exit 127) instead
of spawning a doomed engine.

It answers with a *verdict*, not a bare boolean, because "no window here" has two
causes that need OPPOSITE reactions from an agent (#667):

- the host genuinely has no window server (SSH, CI, a headless box) —
  ``live_windowed_unavailable``: this machine cannot do rendered QA, skip it;
- the host HAS one but THIS PROCESS is denied access to it (a sandbox) —
  ``live_windowed_permission_denied``: retry outside the restriction. Reading this
  as the first cause is exactly the dogfooded defect (GDA-DF-029): a sandboxed run
  was recorded as a machine-capability gap and rendered QA was silently skipped.

Platform-dispatched (live is UNIX-only via ``live_unsupported_platform``, ADR-0021,
so Windows is a documented, unreachable-today stub seam — a single clean slot, not a
refactor):

- **macOS**: ``CGSessionCopyCurrentDictionary`` (CoreGraphics via ``ctypes`` — no
  extra dependency) returns a non-NULL session dict only for an on-console GUI
  session; it is NULL over SSH and in headless / sandbox sessions **even when**
  ``launchctl managername`` reports "Aqua". So we deliberately do NOT use
  ``launchctl`` or ``$DISPLAY`` on macOS — that NULL is exactly what predicts a
  windowed Godot will abort during window-server registration. The API reports NULL
  with no error code, so the NULL alone cannot say WHY; :func:`_macos_window_server_denied`
  answers that second question.
- **Linux**: a non-empty ``$DISPLAY`` (X11) or ``$WAYLAND_DISPLAY`` (Wayland), so a
  run under ``xvfb-run`` (which sets ``DISPLAY``) passes. No permission split: the
  variables are readable regardless of confinement, so a Linux verdict is always the
  capability one.
- **Windows**: unreachable today; the stub reports "usable" so it never spuriously
  gates on a path live never reaches.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass

from gda.models import EnvironmentProbe

_CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_LIBSYSTEM = "/usr/lib/libSystem.B.dylib"

# The mach service a process must reach to talk to the macOS window server. It is
# the name sandbox profiles gate (`(allow mach-lookup (global-name …))`), and the
# one CGSessionCopyCurrentDictionary itself needs — denying it is what makes that
# API return NULL (verified: a seatbelt profile denying ONLY this name flips the
# CoreGraphics probe to NULL while the rest of the host is untouched).
_WINDOW_SERVER_SERVICE = b"com.apple.windowserver.active"

# bootstrap_look_up's "the policy refused this lookup" status, from bootstrap.h.
# The signal #667's spike was looking for: it is returned ONLY for a DENIED lookup.
# A service that is merely not registered — the state a host with no window-server
# session is in — returns BOOTSTRAP_UNKNOWN_SERVICE (1102) instead. So this code
# cannot be produced by an absent session, which is what makes it safe to classify
# on: false negatives (a sandbox that hides the service as "unknown" instead)
# degrade to the capability verdict, but a display-less host can never be
# mis-reported as a permission problem.
_BOOTSTRAP_NOT_PRIVILEGED = 1100


@dataclass(frozen=True)
class WindowedUnavailable:
    """Why a windowed live session cannot come up on THIS host (#345, #667).

    ``code`` is the registered ``Gda error code`` the refusal must report —
    ``live_windowed_unavailable`` (no window server here) or
    ``live_windowed_permission_denied`` (there is one; we are not allowed in).
    ``reason`` is the prose for the message/diagnostics, and ``probe`` is the
    machine-readable :class:`~gda.models.EnvironmentProbe` naming the OS call that
    decided this verdict, so an agent branches on data rather than on the sentence.
    """

    code: str
    reason: str
    probe: EnvironmentProbe


def windowed_unavailable() -> WindowedUnavailable | None:
    """The windowed-session verdict for THIS host, or ``None`` if one can launch.

    The single decision point both the ``gda daemon start --windowed`` precondition
    (``gda.commands.daemon``), the daemon's authoritative launch-boundary guard
    (``gda.daemon.server``) and the windowed e2e gates key on, so they agree:
    ``None`` means "a windowed session can launch here", a verdict is the
    skip/refusal.
    """
    if sys.platform == "darwin":
        return _macos_verdict()
    if sys.platform.startswith("linux"):
        return _linux_verdict()
    return _other_platform_verdict()


def _macos_verdict() -> WindowedUnavailable | None:
    """The macOS verdict: an on-console GUI session, else WHY not.

    ``CGSessionCopyCurrentDictionary`` decides the capability question; when it says
    NULL, the window-server mach lookup decides the permission question. Ordering
    matters — the denial probe runs ONLY on the failure path, so a healthy desktop
    pays nothing for it.
    """
    if _macos_has_window_server():
        return None
    if _macos_window_server_denied():
        return WindowedUnavailable(
            code="live_windowed_permission_denied",
            reason=(
                "this process is denied access to the macOS window server "
                "(bootstrap_look_up of com.apple.windowserver.active returned "
                "BOOTSTRAP_NOT_PRIVILEGED — e.g. a sandbox that does not allow "
                "mach-lookup to it). The host itself HAS a window server, so this "
                "is a permission boundary, not a missing display: re-run outside "
                "the sandbox/restriction rather than treating this machine as "
                "unable to show a window"
            ),
            probe=EnvironmentProbe(
                name="bootstrap_look_up(com.apple.windowserver.active)",
                platform=sys.platform,
            ),
        )
    return WindowedUnavailable(
        code="live_windowed_unavailable",
        reason=(
            "no usable macOS window-server session (CGSessionCopyCurrentDictionary "
            "returned NULL — e.g. SSH / CI / a headless host); a windowed Godot "
            "session cannot register with the window server here. No permission "
            "denial was detected, so this reads as an absent GUI session; if the "
            "run IS confined, a sandbox that hides the window server rather than "
            "refusing it is indistinguishable from an absent one here — re-run "
            "outside the sandbox to tell them apart"
        ),
        probe=EnvironmentProbe(
            name="CGSessionCopyCurrentDictionary", platform=sys.platform
        ),
    )


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
        cg = ctypes.cdll.LoadLibrary(_CORE_GRAPHICS)
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        session = cg.CGSessionCopyCurrentDictionary()
    except Exception:
        return True
    if not session:
        return False
    try:  # release the copied CFDictionary to avoid a leak
        cf = ctypes.cdll.LoadLibrary(_CORE_FOUNDATION)
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease(ctypes.c_void_p(session))
    except Exception:
        pass
    return True


def _macos_window_server_denied() -> bool:
    """Is this process DENIED the window-server mach service? (#667)

    ``CGSessionCopyCurrentDictionary`` returns NULL with no error code, so it cannot
    say whether the window server is absent or merely out of reach. Asking the
    bootstrap namespace for the service directly does distinguish the two, because
    ``bootstrap_look_up`` reports the two states with DIFFERENT statuses:
    ``BOOTSTRAP_NOT_PRIVILEGED`` (1100) for a lookup the policy refused, and
    ``BOOTSTRAP_UNKNOWN_SERVICE`` (1102) for a name nobody registered.

    Only the refusal is claimed here. That direction is the safe one: a lookup that
    was NOT denied cannot return 1100, so a genuinely display-less host can never be
    mis-classified as a permission problem, while a sandbox this probe fails to
    recognize simply falls back to the existing capability verdict.

    Any failure to run the probe at all (symbol gone on a future macOS, unexpected
    ``ctypes`` state) returns ``False`` — "no denial evidence" — so the refusal
    behaves exactly as it did before this probe existed.
    """
    try:
        libsystem = ctypes.CDLL(_LIBSYSTEM)
        bootstrap_port = ctypes.c_uint32.in_dll(libsystem, "bootstrap_port")
        libsystem.bootstrap_look_up.restype = ctypes.c_int32
        libsystem.bootstrap_look_up.argtypes = [
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        service_port = ctypes.c_uint32(0)
        status = libsystem.bootstrap_look_up(
            bootstrap_port.value, _WINDOW_SERVER_SERVICE, ctypes.byref(service_port)
        )
    except Exception:
        return False
    if status == 0 and service_port.value:
        # The lookup handed back a send right; drop it — this probe wants the
        # STATUS, not the port, and leaking a right per failed start would be a
        # slow leak in a long-lived daemon.
        _release_mach_port(libsystem, service_port.value)
    return status == _BOOTSTRAP_NOT_PRIVILEGED


def _release_mach_port(libsystem: ctypes.CDLL, port: int) -> None:
    """Best-effort deallocation of a send right the denial probe received."""
    try:
        libsystem.mach_task_self.restype = ctypes.c_uint32
        libsystem.mach_port_deallocate.restype = ctypes.c_int32
        libsystem.mach_port_deallocate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        libsystem.mach_port_deallocate(libsystem.mach_task_self(), port)
    except Exception:
        pass


def _linux_verdict() -> WindowedUnavailable | None:
    """A non-empty ``$DISPLAY`` (X11) or ``$WAYLAND_DISPLAY`` (Wayland) — so xvfb-run passes.

    Environment variables are readable under any confinement, so an unset pair means
    there is no display to reach — never "a display we are not allowed to reach".
    Linux therefore has no permission verdict.
    """
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return None
    return WindowedUnavailable(
        code="live_windowed_unavailable",
        reason=(
            "headless Linux has no DisplayServer ($DISPLAY / $WAYLAND_DISPLAY unset); "
            "run under a virtual framebuffer such as xvfb-run, which sets DISPLAY"
        ),
        probe=EnvironmentProbe(
            name="$DISPLAY / $WAYLAND_DISPLAY", platform=sys.platform
        ),
    )


def _other_platform_verdict() -> WindowedUnavailable | None:
    """Windows stub seam — unreachable today (live is UNIX-only, ADR-0021).

    Live operations gate on a UNIX platform (``live_unsupported_platform``) long
    before this is reached, so a windowed session never launches on Windows. Left as
    a single clean slot to fill when/if a native Windows display probe (e.g.
    ``GetSystemMetrics(SM_CMONITORS)``) is ever wired in; reports "usable" so it never
    spuriously gates on an unreachable path.
    """
    return None
