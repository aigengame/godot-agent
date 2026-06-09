"""S1 (e2e): gda info --json against the real Godot engine.

Spawns the installed `gda` console script as a subprocess against the real
Godot binary (path per RULES.md), asserts stdout is a single valid JSON object
carrying the engine version, and that the version satisfies the minimum
supported version (>= 4.4) per ADR-0003.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()

requires_godot = pytest.mark.skipif(
    not GODOT.exists(), reason=f"real Godot binary not found at {GODOT}"
)


@pytest.mark.e2e
@requires_godot
def test_gda_info_json_against_real_godot():
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    proc = subprocess.run(
        [gda_bin, "info", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    # stdout is a single valid JSON object.
    data = json.loads(proc.stdout)
    # It carries the engine version info.
    assert data["major"] == 4
    assert isinstance(data["string"], str)
    # The reported version satisfies the minimum supported version (ADR-0003).
    assert (data["major"], data["minor"]) >= (4, 4)
