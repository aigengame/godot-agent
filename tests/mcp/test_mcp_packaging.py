"""S4 (fast): gda-mcp packaging guard + lean core (issue #193, ADR-0013).

The ``gda-mcp`` console script is declared in every install, but the ``mcp`` SDK
only ships with the ``gda[mcp]`` extra. Without it, ``gda-mcp`` must fail with an
actionable "install ``gda[mcp]``" message and a non-zero exit — not an opaque
ImportError (AC1). And gda *core* must never import ``mcp``, so a plain ``gda``
install stays lean. These are fast (no Godot, no MCP session).
"""

import subprocess
import sys

import gda.mcp


def test_missing_mcp_extra_fails_with_actionable_message(monkeypatch, capsys):
    # Simulate the extra being absent: a ``None`` entry in sys.modules makes
    # ``import mcp`` raise ImportError, exactly as a missing install would.
    monkeypatch.setitem(sys.modules, "mcp", None)

    rc = gda.mcp.main()

    assert rc != 0  # non-zero exit (AC1)
    err = capsys.readouterr().err
    assert "gda[mcp]" in err  # names the fix
    assert "mcp" in err


def test_present_mcp_hands_off_to_the_server(monkeypatch):
    # With the extra present, main() guards successfully and hands off to the
    # server's run loop (stubbed here so no real stdio server starts).
    calls = []
    monkeypatch.setattr("gda.mcp.server.run_stdio", lambda: calls.append(True))

    rc = gda.mcp.main()

    assert rc == 0
    assert calls == [True]


def test_gda_core_does_not_import_mcp():
    # ADR-0013: gda core never imports the MCP SDK, so a CLI-only install pays no
    # MCP cost. Checked in a fresh interpreter (this test process already has mcp
    # loaded from the fast tier) that imports the whole CLI surface.
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import gda.cli, gda.__main__, sys; "
            "assert 'mcp' not in sys.modules, sorted(m for m in sys.modules if 'mcp' in m)",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
