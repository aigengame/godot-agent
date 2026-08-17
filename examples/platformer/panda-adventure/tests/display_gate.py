"""The windowed-display gate for the game's visual tiers (#345, #667).

One owner for the reaction policy in THIS context. The game's tests are a separate
pytest root and cannot import the toolkit's own test-support package, so the policy
is restated here rather than shared; it must stay in step with the toolkit's copy.
"""

from __future__ import annotations

import pytest

# The reaction is NOT uniform, and treating it as uniform is the bug this replaces:
#
# - CAPABILITY (`live_windowed_unavailable`, `live_display_unavailable`) — the host
#   cannot show a window. Nothing to run, so SKIP (visible under `-rs`).
# - PERMISSION (`live_windowed_permission_denied`) — the host may well be able to;
#   this RUN is confined. Skipping would green the visual tier with the rendered
#   acceptance unexecuted, which is exactly the defect #667 exists to stop, so FAIL
#   with the remediation. This matches the engine gate in ``conftest.py``, which also
#   fails loudly rather than skipping when the environment cannot deliver what the
#   tier needs.
WINDOWED_CAPABILITY_CODES = frozenset(
    {"live_windowed_unavailable", "live_display_unavailable"}
)
WINDOWED_PERMISSION_DENIED_CODE = "live_windowed_permission_denied"

_CONFINED_REMEDIATION = (
    "the windowed session was refused because this RUN is confined ({detail}). "
    "Rendered acceptance did NOT execute; this is a loud failure rather than a skip "
    "so a sandboxed run cannot green the visual tier with it unexecuted (#667). "
    "Re-run outside the sandbox/restriction."
)


def handle_no_display_code(code, detail: str = "") -> None:
    """Skip on a capability refusal, FAIL on a permission refusal, else return."""
    if code == WINDOWED_PERMISSION_DENIED_CODE:
        pytest.fail(_CONFINED_REMEDIATION.format(detail=detail or code))
    if code in WINDOWED_CAPABILITY_CODES:
        pytest.skip(f"windowed session unavailable ({code})")


def require_windowed_host() -> None:
    """Pre-flight gda's host display probe with the same reaction policy."""
    from gda.display import windowed_unavailable

    verdict = windowed_unavailable()
    if verdict is None:
        return
    # ONE cascade owner per root: delegate to handle_no_display_code so the
    # cross-root parity test covers the preflight too (PR #702 recheck). The
    # trailing skip is the conservative fallback for a verdict code the handler
    # does not classify — a non-None verdict must never proceed to a spawn.
    handle_no_display_code(verdict.code, verdict.reason)
    pytest.skip(verdict.reason)
