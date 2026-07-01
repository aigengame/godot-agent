"""S1 (e2e): script run against the real Godot engine (issue #343, ADR-0031).

``gda script run res://path.gd`` runs the user's OWN script as a one-shot
``godot --headless --path <project> --script <res://…>`` and passes its result
through. These tests exercise that REAL path — the real deep-module
``gda.runner.launch`` spawning the real Godot, classified by the real shared
``classify_launch_or_crash`` — against a throwaway project, proving the round trip
ADR-0031 specifies:

- a script that ``quit(0)`` → SUCCESS ``{exit_status: 0, stdout, stderr}`` with the
  script's printed output read back from ``stdout``;
- a script that ``quit(1)`` → still a **SUCCESS** carrying ``exit_status != 0`` and
  a **zero** gda process exit (the crux: gda does not interpret the script's
  semantics, so a deliberate non-zero quit is data, not a gda failure);
- the pre-run ABI edges — a non-``res://`` path and no resolved project — are
  structured ``invalid_path`` / ``project_not_found`` failures decided before any
  launch;
- an unlaunchable binary is the shared classifier's ``binary_not_found``.

The launch-timeout and signal-crash arms of the shared classifier are covered by
``tests/test_script_run_operation.py`` and ``tests/test_classify_launch_or_crash.py``
(forcing them live is flaky and needs no ``script run``-specific wiring — the
classifier is the same one ``export run`` uses).

The standalone entry script uses the ``extends SceneTree`` + ``_initialize`` +
``quit(<code>)`` pattern (the same one ``operations.gd`` runs on), which is how a
headless one-shot script controls its own exit code.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# A standalone headless script: do work in _initialize, then quit with a chosen
# code. `extends SceneTree` makes the script the main loop, the pattern a
# one-shot `--script` run uses to control its exit code (cf. operations.gd).
HELLO_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("hello from script run")
\tquit(0)
"""

FAIL_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("assertion failed: expected 5 got 4")
\tquit(1)
"""


def _run_gda(*args: str, retry: bool = False) -> subprocess.CompletedProcess:
    """Invoke ``gda <args>`` as a subprocess (this checkout's editable gda, ADR-0011).

    ``retry`` re-runs once on a transient ``engine_crashed`` — a shared-``user://``
    log race under parallel e2e, not a gda bug (see the memory note) — so a happy
    path does not flake.
    """
    for attempt in range(2 if retry else 1):
        proc = subprocess.run([*GDA_CMD, *args], capture_output=True, text=True)
        if not retry or proc.returncode == 0:
            return proc
        try:
            code = json.loads(proc.stdout)["error"]["code"]
        except (ValueError, KeyError, TypeError):
            return proc
        if code != "engine_crashed":
            return proc
    return proc


@pytest.mark.e2e
def test_script_run_passes_a_clean_run_through(godot_project):
    # Happy path: a script that quit(0) → SUCCESS carrying exit_status 0 and the
    # script's printed line read back from stdout.
    (godot_project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://hello.gd",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
        retry=True,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["exit_status"] == 0
    assert "hello from script run" in data["stdout"]
    assert "error" not in data


@pytest.mark.e2e
def test_script_run_non_zero_quit_is_success_not_a_gda_failure(godot_project):
    # THE CRUX (ADR-0031): a deliberate quit(1) — e.g. an assertion-failed logic-seam
    # test — is a clean engine exit, so it is a SUCCESS result carrying exit_status=1,
    # and the gda PROCESS still exits 0. gda does not interpret the script's semantics:
    # the non-zero code and the message are DATA the agent reads, not a gda error.
    (godot_project / "fail.gd").write_text(FAIL_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://fail.gd",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
        retry=True,
    )

    assert run.returncode == 0, run.stdout + run.stderr  # a SUCCESS, not an envelope
    data = json.loads(run.stdout)
    assert "error" not in data
    assert data["exit_status"] == 1
    assert "assertion failed" in data["stdout"]


@pytest.mark.e2e
def test_script_run_non_res_path_is_invalid_path(godot_project):
    # A non-res:// path is a structured invalid_path decided BEFORE any launch — an
    # explicit ABI edge (ADR-0031), never a crash or raw engine failure.
    run = _run_gda(
        "script",
        "run",
        "hello.gd",  # not res://
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert err["category"] == "operation"


@pytest.mark.e2e
def test_script_run_without_a_project_is_project_not_found(tmp_path):
    # No resolved project (no --project, no $GDA_PROJECT, cwd is projectless) →
    # structured project_not_found before any launch (the other ABI edge, ADR-0031).
    projectless = tmp_path / "empty"
    projectless.mkdir()

    run = subprocess.run(
        [*GDA_CMD, "script", "run", "res://hello.gd", "--godot", str(GODOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(projectless),
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "project_not_found"
    assert err["category"] == "operation"


@pytest.mark.e2e
def test_script_run_unlaunchable_binary_is_binary_not_found(godot_project):
    # An unlaunchable --godot binary is the SAME shared classifier's binary_not_found
    # (the launch-failure family), exactly as export run classifies it — no
    # GDScript-mirrored code.
    (godot_project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://hello.gd",
        "--project",
        str(godot_project),
        "--godot",
        str(godot_project / "no-such-godot"),
        "--json",
    )

    assert run.returncode == 127, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "binary_not_found"
    assert err["category"] == "environment"
