"""S1 (e2e): gda info --json against the real Godot engine.

Spawns the `gda` CLI (`python -m gda`) as a subprocess against the real
Godot binary (path per RULES.md), asserts stdout is a single valid JSON object
carrying the engine version, and that the version satisfies the minimum
supported version (>= 4.4) per ADR-0003.
"""

import json

import pytest

from tests.support import Gda

from tests.conftest import project_godot

gda = Gda()


@pytest.mark.e2e
def test_gda_info_json_against_real_godot():
    proc = gda("info", "--json")

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
    proc = Gda(godot="/nonexistent/Godot")("info", "--json")

    assert proc.returncode == 127
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
    # Engine/script diagnostics are surfaced on stderr (ADR-0002).
    assert "/nonexistent/Godot" in proc.stderr


@pytest.mark.e2e
def test_gda_info_accepts_a_project_and_still_reports_the_engine(tmp_path):
    # #670: an orchestrator passes one `--project` argv to every command, so `info`
    # must take it — and taking it means the engine really runs against that project
    # (ADR-0006), not that the flag is parsed and dropped. Against a REAL engine: the
    # version comes back unchanged, so the uniform argv costs nothing.
    (tmp_path / "project.godot").write_text(
        project_godot(name="probe"), encoding="utf-8"
    )

    proc = Gda(tmp_path)("info", "--json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert (data["major"], data["minor"]) >= (4, 4)

    # And it is the SAME answer as the projectless probe — the project does not
    # change what `info` reports.
    projectless = gda("info", "--json")
    assert json.loads(projectless.stdout) == data


@pytest.mark.e2e
def test_gda_info_refuses_a_project_that_is_not_one(tmp_path):
    # Validated, not merely accepted — through the real CLI, before any engine runs.
    proc = Gda(tmp_path)("info", "--json")

    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["error"]["code"] == "project_not_found"
