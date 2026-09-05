"""gda-mcp subprocess seam: launch failures are raw results, never exceptions (#193).

Reviewer-requested regression (PR #203): a gda command that cannot be launched —
e.g. a bad ``$GDA_BIN`` override pointing nowhere — must surface as a structured
non-zero :class:`~gda.mcp.runner.GdaResult` that :func:`~gda.mcp.server.dispatch`
turns into an ``is_error`` ``CallToolResult``, NOT an ``OSError`` escaping across
the MCP boundary (ADR-0011's "can't-run" edge, synthesized by gda-mcp). These are
fast: the bad binary fails to exec immediately, no Godot involved.
"""

import json

from mcp.types import CallToolResult

from gda.mcp.runner import SubprocessGdaRunner
from gda.mcp.server import dispatch

from tests.mcp_support import tool_text

# A command that cannot be exec'd at all — the unlaunchable-binary case a bad
# GDA_BIN override produces.
_UNLAUNCHABLE = SubprocessGdaRunner(command=["/does/not/exist/gda"])


def test_unlaunchable_command_returns_a_failure_result_not_an_exception():
    # The seam catches the OSError and reports it as a non-zero raw result,
    # naming the offending command in diagnostics — it never raises.
    result = _UNLAUNCHABLE.run(["info"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "/does/not/exist/gda" in result.stderr


def test_dispatch_synthesizes_is_error_for_a_launch_failure():
    # End to end through the real seam: an unlaunchable gda becomes gda-mcp's own
    # structured is_error (the can't-run edge), with the launch diagnostics
    # preserved — not a traceback.
    outcome = dispatch(_UNLAUNCHABLE, ["info"], {})

    # A CallToolResult (failure channel), not a raised exception or a result dict.
    assert isinstance(outcome, CallToolResult)
    assert outcome.is_error is True
    assert outcome.structured_content is None
    body = json.loads(tool_text(outcome))
    assert body["error"]["category"] == "adapter"  # gda-mcp's own synthesized error
    assert "/does/not/exist/gda" in body["error"]["diagnostics"]
