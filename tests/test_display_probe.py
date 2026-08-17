"""The host-display probe's verdict logic (#345, #667).

``gda.display`` answers ONE question with two possible refusals, and the split is
what #667 is about: "no window server was detected here" (skip rendered QA) versus
"the window-server lookup was REFUSED" (re-run outside the restriction). Reading the
second as the first is the dogfooded defect (GDA-DF-029). The second refusal claims
nothing about whether a window server exists — macOS refuses the lookup per name and
before resolving it — so a guard below pins that no branch reasserts existence.

Tiering follows from where the risk is:

- The **verdict logic** — which code, which probe name, which platform — is a pure
  function of the host answers, so it is tested by injecting those answers. UNGATED:
  it runs on every host, including a display-less CI runner, which is exactly where a
  regression would otherwise hide.
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
    _DENIAL_BLANKET,
    _DENIAL_NAME_SPECIFIC,
    _DENIAL_UNKNOWN_BREADTH,
    WindowedUnavailable,
    _linux_verdict,
    _macos_verdict,
    _macos_window_server_denial,
    windowed_unavailable,
)

# --- the verdict logic (ungated) --------------------------------------------


def test_macos_with_a_window_server_can_launch_windowed(monkeypatch):
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: True)
    # The denial probe must not even run on the success path: a healthy desktop pays
    # nothing for the #667 split.
    monkeypatch.setattr(
        "gda.display._macos_window_server_denial",
        lambda: pytest.fail("the denial probe ran on the success path"),
    )

    assert _macos_verdict() is None


def test_macos_without_a_window_server_is_the_capability_verdict(monkeypatch):
    # CGSession said NULL and nothing denied us: as far as gda can tell the host has
    # no GUI session (SSH / CI / headless). The capability code, naming CGSession as
    # the probe that decided it.
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    monkeypatch.setattr("gda.display._macos_window_server_denial", lambda: None)

    verdict = _macos_verdict()

    assert verdict is not None
    assert verdict.code == "live_windowed_unavailable"
    assert verdict.probe.name == "CGSessionCopyCurrentDictionary"
    assert verdict.probe.platform == sys.platform
    # The remaining ambiguity is disclosed rather than hidden: a sandbox that HIDES
    # the window server (rather than refusing the lookup) lands here too.
    assert "outside the sandbox" in verdict.reason
    # F5: the actionable remediation the pre-#667 message carried is still here.
    assert "Run the daemon headless" in verdict.reason


@pytest.mark.parametrize(
    ("denial", "expected_breadth"),
    [
        (_DENIAL_NAME_SPECIFIC, "specific to that service"),
        (_DENIAL_BLANKET, "broadly confined"),
        (_DENIAL_UNKNOWN_BREADTH, "stays unknown"),
    ],
)
def test_macos_denied_window_server_is_the_permission_verdict(
    monkeypatch, denial, expected_breadth
):
    # CGSession said NULL and the window-server lookup was REFUSED. Both control
    # outcomes take the permission code with the same probe name; they differ only in
    # how much confinement the probe could honestly characterise.
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    monkeypatch.setattr("gda.display._macos_window_server_denial", lambda: denial)

    verdict = _macos_verdict()

    assert verdict is not None
    assert verdict.code == "live_windowed_permission_denied"
    assert verdict.probe.name == "bootstrap_look_up(com.apple.windowserver.active)"
    assert verdict.probe.platform == sys.platform
    assert expected_breadth in verdict.reason
    assert "re-run outside the" in verdict.reason


@pytest.mark.parametrize(
    "denial", [_DENIAL_NAME_SPECIFIC, _DENIAL_BLANKET, _DENIAL_UNKNOWN_BREADTH]
)
def test_no_denial_branch_claims_the_host_has_a_window_server(monkeypatch, denial):
    # The #667-review regression guard. A refused lookup is evaluated per name and
    # BEFORE resolution, so it proves confinement, NOT existence — a blanket-deny
    # profile on a display-less CI Mac lands here too. Neither branch may tell the
    # caller the host HAS a window server, and both must say gda cannot tell.
    monkeypatch.setattr("gda.display._macos_has_window_server", lambda: False)
    monkeypatch.setattr("gda.display._macos_window_server_denial", lambda: denial)

    verdict = _macos_verdict()
    assert verdict is not None
    reason = verdict.reason

    # The claim is explicitly negated: gda says it CANNOT tell.
    assert (
        "cannot tell from a refused lookup whether this host HAS a window server"
        in reason
    )
    # And none of the affirmative phrasings — including the exact sentence the
    # original implementation shipped — may reappear.
    for forbidden in (
        "The host itself HAS a window server",
        "is a permission boundary, not a missing display",
        "HAS a window server, so",
    ):
        assert forbidden not in reason


@pytest.mark.parametrize(
    ("target", "control", "expected"),
    [
        # The window server refused, a name nobody registers resolved normally: the
        # denial is specific to that service — the sandbox-profile signature.
        (1100, 1102, _DENIAL_NAME_SPECIFIC),
        # BOTH refused. Seatbelt evaluates the deny per name and before resolution,
        # so this is a broadly-confined process and the probe learned only that.
        (1100, 1100, _DENIAL_BLANKET),
        # Control answered something we have no reading for. Only a REFUSED control
        # licenses the blanket reading, so these must NOT be folded into it — that
        # would invent a fact about the confinement from an unreadable result.
        (1100, 0, _DENIAL_UNKNOWN_BREADTH),  # the control name somehow resolved
        (1100, 5, _DENIAL_UNKNOWN_BREADTH),  # an arbitrary unrelated error
        # Not refused at all -> no denial evidence, whatever the control says.
        (1102, 1102, None),
        (0, 1102, None),
    ],
)
def test_the_control_lookup_characterises_the_denial(target, control, expected):
    # Ungated: the status -> breadth mapping is handed a fake lookup, so it runs on
    # any host including a Linux CI runner with no libSystem.
    from gda.display import _CONTROL_SERVICE, _WINDOW_SERVER_SERVICE, _classify_denial

    statuses = {_WINDOW_SERVER_SERVICE: target, _CONTROL_SERVICE: control}

    assert _classify_denial(lambda name: statuses[name]) is expected


def test_the_control_lookup_is_skipped_when_the_target_was_not_refused():
    # The control costs a second mach round-trip, so it must only run once the
    # target has actually been refused.
    from gda.display import _WINDOW_SERVER_SERVICE, _classify_denial

    asked: list[bytes] = []

    def _lookup(name: bytes) -> int:
        asked.append(name)
        return 0

    assert _classify_denial(_lookup) is None
    assert asked == [_WINDOW_SERVER_SERVICE]


def test_the_denial_probe_falls_back_when_it_cannot_run(monkeypatch):
    # The denial probe is best-effort private-ish plumbing (a libSystem symbol). If it
    # cannot run at all — a future macOS drops the symbol, ctypes misbehaves — the
    # refusal must behave exactly as it did before the probe existed, never crash a
    # `daemon start`.
    def _explode():
        raise OSError("no libSystem here")

    monkeypatch.setattr("gda.display.ctypes.CDLL", lambda _path: _explode())
    assert _macos_window_server_denial() is None

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

# Denies ONLY the window-server name: everything else, including an unregistered
# control name, still resolves. The sandbox-profile signature.
_NAME_SPECIFIC_PROFILE = (
    "(version 1)\n"
    "(allow default)\n"
    '(deny mach-lookup (global-name "com.apple.windowserver.active"))\n'
)

# Denies every mach-lookup. The case that falsified the original spike claim: the
# control name is refused too, so the refusal says nothing about what exists.
_BLANKET_PROFILE = (
    "(version 1)\n"
    "(deny default)\n"
    "(allow process*)\n"
    "(allow file*)\n"
    "(allow sysctl*)\n"
    "(allow signal)\n"
    "(allow ipc-posix-shm)\n"
)

_PROBE_SCRIPT = textwrap.dedent(
    """
    import json
    from gda.display import windowed_unavailable
    verdict = windowed_unavailable()
    from gda.display import _macos_window_server_denial
    print(json.dumps(
        None if verdict is None
        else {
            "code": verdict.code,
            "probe": verdict.probe.name,
            "denial": _macos_window_server_denial(),
            "claims_existence": "cannot tell from a refused lookup" not in verdict.reason,
        }
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


@pytest.mark.parametrize(
    ("profile_body", "expected_denial"),
    [
        (_NAME_SPECIFIC_PROFILE, _DENIAL_NAME_SPECIFIC),
        (_BLANKET_PROFILE, _DENIAL_BLANKET),
    ],
)
def test_a_real_sandbox_denial_is_classified_as_a_permission_problem(
    tmp_path, profile_body, expected_denial
):
    # The end-to-end proof against a REAL seatbelt sandbox rather than a fake: on a
    # host that HAS a desktop session, a refused window-server lookup must flip the
    # verdict to the permission code — not to live_windowed_unavailable, which is
    # what the dogfooding saw and what made automation record the machine as
    # display-less.
    #
    # Both profiles are exercised because they are the two halves of the corrected
    # finding (#667 review): the blanket one refuses the unregistered control name
    # too, which is exactly why NEITHER may claim the host has a window server.
    if not _sandbox_exec_works(tmp_path):
        pytest.skip("needs macOS with a working sandbox-exec")
    if windowed_unavailable() is not None:
        pytest.skip("needs a real on-console desktop session to deny access TO")

    profile = tmp_path / "profile.sb"
    profile.write_text(profile_body, encoding="utf-8")

    # The control: unsandboxed on this same host, a windowed session can launch.
    assert _verdict_under(None, tmp_path) is None

    denied = _verdict_under(profile, tmp_path)
    assert denied is not None

    assert denied["code"] == "live_windowed_permission_denied"
    assert denied["probe"] == "bootstrap_look_up(com.apple.windowserver.active)"
    assert denied["denial"] == expected_denial
    # Neither branch may assert the host has a window server.
    assert denied["claims_existence"] is False


def test_the_probe_returns_a_verdict_or_none_on_this_host():
    # A cheap always-on sanity check that the real probe runs without raising on
    # whatever host the suite is on, whatever it concludes.
    verdict = windowed_unavailable()
    assert verdict is None or isinstance(verdict, WindowedUnavailable)


# --- the test-side gate policy (ungated) -------------------------------------
#
# The gate helper decides whether an environment refusal SKIPS or FAILS, and the
# whole point of #667 is that those two reactions are not interchangeable. Tabled
# here so the policy itself is covered, not just the probe that feeds it.


@pytest.mark.parametrize(
    ("code", "reaction"),
    [
        ("live_windowed_unavailable", "skipped"),
        ("live_display_unavailable", "skipped"),
        ("live_windowed_permission_denied", "failed"),
        ("engine_session_not_running", "returned"),
        (None, "returned"),
    ],
)
def test_the_no_display_reaction_policy(code, reaction):
    from tests.support import handle_no_display_code

    if reaction == "returned":
        # Not a display refusal: the helper stays out of the way so the caller can
        # raise its own assertion for a genuine failure.
        handle_no_display_code(code)
        return

    with pytest.raises(BaseException) as caught:
        handle_no_display_code(code)

    outcome = type(caught.value).__name__
    if reaction == "skipped":
        assert outcome == "Skipped"
    else:
        assert outcome == "Failed"
        # The failure has to carry the remediation, or a confined CI run reads as a
        # plain breakage instead of "you are sandboxed".
        assert "Re-run outside the sandbox/restriction" in str(caught.value)
        assert "did NOT execute" in str(caught.value)


@pytest.mark.parametrize(
    ("verdict_code", "reaction"),
    [
        ("live_windowed_unavailable", "Skipped"),
        ("live_windowed_permission_denied", "Failed"),
    ],
)
def test_the_preflight_gate_applies_the_same_policy(
    monkeypatch, verdict_code, reaction
):
    # The pre-flight probe path and the post-start race path must agree — they used
    # to be written out separately at five call sites, which is how the wrong
    # reaction spread in the first place.
    from gda.models import EnvironmentProbe
    from tests.support import require_windowed_host

    monkeypatch.setattr(
        "gda.display.windowed_unavailable",
        lambda: WindowedUnavailable(
            code=verdict_code,
            reason=f"test verdict ({verdict_code})",
            probe=EnvironmentProbe(name="probe", platform="darwin"),
        ),
    )

    with pytest.raises(BaseException) as caught:
        require_windowed_host()

    assert type(caught.value).__name__ == reaction


def test_the_preflight_gate_runs_the_test_when_a_window_can_open(monkeypatch):
    from tests.support import require_windowed_host

    monkeypatch.setattr("gda.display.windowed_unavailable", lambda: None)

    require_windowed_host()  # must not raise
