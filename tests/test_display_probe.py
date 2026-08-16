"""The host-display probe's verdict logic (#345, #667).

``gda.display`` answers ONE question with two possible refusals, and the split is
what #667 is about: "no window server on this host" (skip rendered QA) versus "this
process may not reach the one that exists" (retry outside the sandbox). Reading the
second as the first is the dogfooded defect (GDA-DF-029).

Tiering follows from where the risk is:

- The **verdict logic** — which code, which probe name, which platform — is a pure
  function of the two boolean host answers, so it is tested by injecting those
  answers. UNGATED: it runs on every host, including a display-less CI runner, which
  is exactly where a regression would otherwise hide.
- The **real macOS denial probe** needs a real sandbox to mean anything, so that one
  leg is capability-gated on macOS + a working ``sandbox-exec`` + an actual desktop
  session, and skips honestly elsewhere.
"""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from gda.display import (
    WindowedUnavailable,
    _linux_verdict,
    _macos_verdict,
    _macos_window_server_denied,
    windowed_unavailable,
)

# --- the verdict logic (ungated) --------------------------------------------


def test_macos_with_a_window_server_can_launch_windowed(monkeypatch):
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: True)
    # The denial probe must not even run on the success path: a healthy desktop pays
    # nothing for the #667 split.
    monkeypatch.setattr(
        "gda.display._macos_window_server_denied",
        lambda: pytest.fail("the denial probe ran on the success path"),
    )

    assert _macos_verdict() is None


def test_macos_without_a_window_server_is_the_capability_verdict(monkeypatch):
    # CGSession said NULL and nothing denied us: the host genuinely has no GUI
    # session (SSH / CI / headless). The capability code, naming CGSession as the
    # probe that decided it.
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    monkeypatch.setattr("gda.display._macos_window_server_denied", lambda: False)

    verdict = _macos_verdict()

    assert verdict is not None
    assert verdict.code == "live_windowed_unavailable"
    assert verdict.probe.name == "CGSessionCopyCurrentDictionary"
    assert verdict.probe.platform == sys.platform
    # The remaining ambiguity is disclosed rather than hidden: a sandbox that HIDES
    # the window server (rather than refusing the lookup) lands here too.
    assert "outside the sandbox" in verdict.reason


def test_macos_denied_window_server_is_the_permission_verdict(monkeypatch):
    # CGSession said NULL, but the window-server lookup was REFUSED: the host has a
    # window server we are not allowed to reach. A different code and a different
    # probe name, so an agent branches on data.
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    monkeypatch.setattr("gda.display._macos_window_server_denied", lambda: True)

    verdict = _macos_verdict()

    assert verdict is not None
    assert verdict.code == "live_windowed_permission_denied"
    assert verdict.probe.name == "bootstrap_look_up(com.apple.windowserver.active)"
    assert verdict.probe.platform == sys.platform
    assert "re-run outside the sandbox" in verdict.reason


def test_the_denial_probe_failing_falls_back_to_the_capability_verdict(monkeypatch):
    # The denial probe is best-effort private-ish plumbing (a libSystem symbol). If it
    # cannot run at all — a future macOS drops the symbol, ctypes misbehaves — the
    # refusal must behave exactly as it did before the probe existed, never crash a
    # `daemon start`.
    def _explode():
        raise OSError("no libSystem here")

    monkeypatch.setattr("gda.display.ctypes.CDLL", lambda _path: _explode())
    assert _macos_window_server_denied() is False

    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    fallback = _macos_verdict()
    assert fallback is not None
    assert fallback.code == "live_windowed_unavailable"


@pytest.mark.parametrize("variable", ["DISPLAY", "WAYLAND_DISPLAY"])
def test_linux_with_a_display_can_launch_windowed(monkeypatch, variable):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv(variable, ":0")

    assert _linux_verdict() is None


def test_linux_without_a_display_is_the_capability_verdict(monkeypatch):
    # No permission split on Linux: the environment variables are readable under any
    # confinement, so an unset pair always means "no display to reach".
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    verdict = _linux_verdict()

    assert verdict is not None
    assert verdict.code == "live_windowed_unavailable"
    assert verdict.probe.name == "$DISPLAY / $WAYLAND_DISPLAY"


def test_the_verdict_carries_a_registered_error_code():
    # Whatever the probe decides must be a code the failure builder accepts — the
    # refusal sites pass `verdict.code` straight into `make_failure`.
    from gda.error_codes import ERROR_CODE_BY_CODE

    for code in ("live_windowed_unavailable", "live_windowed_permission_denied"):
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.category.value == "environment"
        assert spec.exit_code == 127


# --- the real macOS denial probe (capability-gated) --------------------------

_SANDBOX_PROFILE = '(version 1)\n(allow default)\n(deny mach-lookup (global-name "com.apple.windowserver.active"))\n'

_PROBE_SCRIPT = textwrap.dedent(
    """
    import json
    from gda.display import windowed_unavailable
    verdict = windowed_unavailable()
    print(json.dumps(
        None if verdict is None
        else {"code": verdict.code, "probe": verdict.probe.name}
    ))
    """
)


def _sandbox_exec_works(tmp_path: Path) -> bool:
    """Can this host actually run a seatbelt profile? (else the leg is meaningless)"""
    if sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
        return False
    profile = tmp_path / "preflight.sb"
    profile.write_text("(version 1)\n(allow default)\n", encoding="utf-8")
    try:
        probe = subprocess.run(
            ["sandbox-exec", "-f", str(profile), "/usr/bin/true"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _verdict_under(profile: Path | None, tmp_path: Path) -> dict | None:
    script = tmp_path / "probe.py"
    script.write_text(_PROBE_SCRIPT, encoding="utf-8")
    argv = [sys.executable, str(script)]
    if profile is not None:
        argv = ["sandbox-exec", "-f", str(profile), *argv]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f"probe failed: {run.stderr}"
    return json.loads(run.stdout.strip())


def test_a_real_sandbox_denial_is_classified_as_a_permission_problem(tmp_path):
    # The end-to-end proof of the #667 spike finding, against a REAL seatbelt sandbox
    # rather than a fake: on a host that HAS a desktop session, denying only the
    # window-server mach lookup must flip the verdict to the permission code — not to
    # live_windowed_unavailable, which is what the dogfooding saw and what made
    # automation record the machine as display-less.
    if not _sandbox_exec_works(tmp_path):
        pytest.skip("needs macOS with a working sandbox-exec")
    if windowed_unavailable() is not None:
        pytest.skip("needs a real on-console desktop session to deny access TO")

    profile = tmp_path / "deny-windowserver.sb"
    profile.write_text(_SANDBOX_PROFILE, encoding="utf-8")

    # The control: unsandboxed on this same host, a windowed session can launch.
    assert _verdict_under(None, tmp_path) is None

    denied = _verdict_under(profile, tmp_path)

    assert denied == {
        "code": "live_windowed_permission_denied",
        "probe": "bootstrap_look_up(com.apple.windowserver.active)",
    }


def test_the_probe_returns_a_verdict_or_none_on_this_host():
    # A cheap always-on sanity check that the real probe runs without raising on
    # whatever host the suite is on, whatever it concludes.
    verdict = windowed_unavailable()
    assert verdict is None or isinstance(verdict, WindowedUnavailable)
