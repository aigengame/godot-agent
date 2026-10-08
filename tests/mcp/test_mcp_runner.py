"""gda-mcp subprocess seam: launch failures are raw results, never exceptions (#193).

Reviewer-requested regression (PR #203): a gda command that cannot be launched —
e.g. a bad ``$GDA_BIN`` override pointing nowhere — must surface as a structured
non-zero :class:`~gda.mcp.runner.GdaResult` that :func:`~gda.mcp.server.dispatch`
turns into an ``is_error`` ``CallToolResult``, NOT an ``OSError`` escaping across
the MCP boundary (ADR-0011's "can't-run" edge, synthesized by gda-mcp). These are
fast: the bad binary fails to exec immediately, no Godot involved.
"""

import json
import shlex
import subprocess
import sys

from mcp.types import CallToolResult

from gda.mcp.runner import GDA_BIN_ENV, SubprocessGdaRunner
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


def test_command_override_preserves_native_arguments(monkeypatch, tmp_path):
    entry = tmp_path / "command with spaces" / "echo argv.py"
    entry.parent.mkdir()
    entry.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8"
    )
    prefix = [
        sys.executable,
        str(entry),
        r"C:\Games\My Game",
        'a "quoted" name',
        "C:\\trailing space\\",
        "",
        "'literal single quotes'",
        "%GDA_GODOT%",
    ]
    command_line = (
        subprocess.list2cmdline(prefix)
        if sys.platform == "win32"
        else shlex.join(prefix)
    )
    monkeypatch.setenv(GDA_BIN_ENV, command_line)

    result = SubprocessGdaRunner.default().run(["ordered", "tail"])

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        r"C:\Games\My Game",
        'a "quoted" name',
        "C:\\trailing space\\",
        "",
        "'literal single quotes'",
        "%GDA_GODOT%",
        "ordered",
        "tail",
    ]
