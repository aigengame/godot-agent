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


@pytest.mark.e2e
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


@pytest.mark.e2e
def test_gda_info_missing_binary_yields_structured_error_end_to_end():
    # The failure path through the whole stack (issue #3): a real subprocess
    # against a binary that cannot launch. No installed engine required — the
    # point is that the path does NOT exist. The runner synthesizes exit 127,
    # the CLI emits a structured JSON error on stdout.
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    proc = subprocess.run(
        [gda_bin, "info", "--godot", "/nonexistent/Godot"],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 127
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
    # Engine/script diagnostics are surfaced on stderr (ADR-0002).
    assert "/nonexistent/Godot" in proc.stderr
