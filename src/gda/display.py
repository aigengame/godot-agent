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

- nothing refused us and there is no session — ``live_windowed_unavailable``: as far
  as gda can tell this machine cannot do rendered QA, so skip it;
- the window-server lookup was REFUSED — ``live_windowed_permission_denied``: this
  process may not even ask, so re-run outside the restriction. Reading this as the
  first cause is exactly the dogfooded defect (GDA-DF-029): a sandboxed run was
  recorded as a machine-capability gap and rendered QA was silently skipped.

The second verdict deliberately claims only that the LOOKUP was denied — never that
a window server exists. Seatbelt evaluates a mach-lookup deny per name and before
resolution, so a blanket-deny profile refuses an unregistered name too; inferring
existence from the refusal would tell a display-less confined CI Mac that its host
has a window server (#667 review).

Platform-dispatched (live is UNIX-only via ``live_unsupported_platform``, ADR-0021,
so Windows is a documented, unreachable-today stub seam — a single clean slot, not a
refactor):

- **macOS**: ``CGSessionCopyCurrentDictionary`` (CoreGraphics via ``ctypes`` — no
  extra dependency) returns a non-NULL session dict only for an on-console GUI
  session; it is NULL over SSH and in headless / sandbox sessions **even when**
  ``launchctl managername`` reports "Aqua". So we deliberately do NOT use
  ``launchctl`` or ``$DISPLAY`` on macOS — that NULL is exactly what predicts a
  windowed Godot will abort during window-server registration. The API reports NULL
  with no error code, so the NULL alone cannot say WHY;
  :func:`_macos_window_server_denial` answers the one further question that IS
  answerable — was the lookup refused, and how broadly.
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
from collections.abc import Callable
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

# A name nothing registers, used as the CONTROL lookup (#667 review). Its whole job
# is to reveal how broad the confinement is — see _macos_window_server_denial.
_CONTROL_SERVICE = b"com.gda.probe.control.unregistered"

# bootstrap_look_up statuses, from bootstrap.h.
#
# What these DO and DO NOT prove (#667 review corrected the original claim):
# seatbelt evaluates a mach-lookup deny rule PER NAME and BEFORE the name is
# resolved, so a blanket-deny profile returns NOT_PRIVILEGED for a name nobody
# registered just as readily as for a real one. NOT_PRIVILEGED therefore proves
# exactly one thing — "the policy refused THIS lookup" — and carries NO information
# about whether a window server exists on the host. Claiming existence from it was
# the falsified inference: a display-less CI Mac under a broad-deny profile would be
# told the host HAS a window server.
#
# UNKNOWN_SERVICE is the not-registered answer, and is only meaningful when the
# lookup was allowed to resolve at all.
_BOOTSTRAP_NOT_PRIVILEGED = 1100
_BOOTSTRAP_UNKNOWN_SERVICE = 1102

# How broad a denial the control lookup revealed. Both mean "denied", so both take
# the permission verdict; they differ only in what the probe can honestly say about
# the confinement, never about whether a window server exists.
_DENIAL_NAME_SPECIFIC = "name-specific"
_DENIAL_BLANKET = "blanket"


@dataclass(frozen=True)
class WindowedUnavailable:
    """Why a windowed live session cannot come up on THIS host (#345, #667).

    ``code`` is the registered ``Gda error code`` the refusal must report —
    ``live_windowed_unavailable`` (nothing refused us and no session is reachable) or
    ``live_windowed_permission_denied`` (the lookup itself was refused, so whether a
    window server exists is unknown).
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
    denial = _macos_window_server_denial()
    if denial is not None:
        breadth = (
            "the denial is specific to that service (a control lookup of an "
            "unregistered name still resolved normally), which is the signature of "
            "a sandbox profile that gates the window server"
            if denial is _DENIAL_NAME_SPECIFIC
            else "a control lookup of an unregistered name was refused too, so this "
            "process is broadly confined and the probe learned only that much"
        )
        return WindowedUnavailable(
            code="live_windowed_permission_denied",
            reason=(
                "this process is denied the macOS window-server lookup "
                "(bootstrap_look_up of com.apple.windowserver.active returned "
                f"BOOTSTRAP_NOT_PRIVILEGED — e.g. a sandbox); {breadth}. gda cannot "
                "tell from a refused lookup whether this host HAS a window server, "
                "only that this process may not ask: re-run outside the "
                "sandbox/restriction to find out — if a windowed session comes up "
                "there, this was a permission boundary; if it fails the same way, "
                "the host genuinely has none"
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
            "session cannot register with the window server here. Run the daemon "
            "headless instead, or start it on a host with an on-console GUI session. "
            "No permission denial was detected, so this reads as an absent GUI "
            "session; if the run IS confined, a sandbox that hides the window server "
            "rather than refusing it is indistinguishable from an absent one here — "
            "re-run outside the sandbox to tell them apart"
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


def _macos_window_server_denial() -> str | None:
    """Was this process DENIED the window-server lookup, and how broadly? (#667)

    ``CGSessionCopyCurrentDictionary`` returns NULL with no error code, so it cannot
    say whether the window server is absent or merely out of reach. Asking the
    bootstrap namespace directly answers a NARROWER question that is still worth
    asking: was the lookup *refused*? ``BOOTSTRAP_NOT_PRIVILEGED`` means the policy
    said no — which an absent service never produces on its own, so it is real
    evidence of confinement.

    What it is NOT evidence of is that a window server exists. Seatbelt evaluates a
    mach-lookup deny PER NAME and BEFORE resolving it, so a blanket-deny profile
    refuses an unregistered name just as readily (verified). That is why the CONTROL
    lookup exists: a name nothing registers is looked up too, and its answer says how
    broad the confinement is —

    - control ``UNKNOWN_SERVICE`` + target refused → the denial is **name-specific**:
      lookups do resolve here, and this one name is gated. The sandbox signature.
    - control refused as well → **blanket** confinement; the probe learned only that
      this process is confined.

    Neither branch licenses a claim about the host's display: both report the same
    permission verdict, and the caller's wording says so. Returns ``None`` when there
    is no denial evidence at all, including any failure to run the probe (symbol gone
    on a future macOS, unexpected ``ctypes`` state) — so the refusal then behaves
    exactly as it did before this probe existed.
    """
    try:
        lookup = _bootstrap_lookup()
    except Exception:
        return None
    return _classify_denial(lookup)


def _classify_denial(lookup: "Callable[[bytes], int]") -> str | None:
    """Map the target + control lookup statuses onto a denial breadth (#667).

    Split from the ``ctypes`` wiring so the decision — the part with the actual
    reasoning in it — is exercised by handing it a fake ``lookup`` on ANY host,
    including a Linux CI runner with no libSystem at all.
    """
    if lookup(_WINDOW_SERVER_SERVICE) != _BOOTSTRAP_NOT_PRIVILEGED:
        return None
    if lookup(_CONTROL_SERVICE) == _BOOTSTRAP_UNKNOWN_SERVICE:
        return _DENIAL_NAME_SPECIFIC
    return _DENIAL_BLANKET


def _bootstrap_lookup() -> "Callable[[bytes], int]":
    """Bind ``bootstrap_look_up`` and return a name → status callable.

    Raises if the symbol or the bootstrap port cannot be bound, which the caller
    treats as "no denial evidence".
    """
    libsystem = ctypes.CDLL(_LIBSYSTEM)
    bootstrap_port = ctypes.c_uint32.in_dll(libsystem, "bootstrap_port")
    libsystem.bootstrap_look_up.restype = ctypes.c_int32
    libsystem.bootstrap_look_up.argtypes = [
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]

    def _lookup(name: bytes) -> int:
        service_port = ctypes.c_uint32(0)
        status = libsystem.bootstrap_look_up(
            bootstrap_port.value, name, ctypes.byref(service_port)
        )
        if status == 0 and service_port.value:
            # The lookup handed back a send right; drop it — this probe wants the
            # STATUS, not the port, and leaking a right per failed start would be a
            # slow leak in a long-lived daemon.
            _release_mach_port(libsystem, service_port.value)
        return status

    return _lookup


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
