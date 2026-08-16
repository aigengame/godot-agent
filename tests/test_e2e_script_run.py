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
- both accepted script-path forms — project-relative and ``res://`` (#675) — run
  the same script and report the same canonical ``res://`` ``path``;
- the pre-run ABI edges — an ABSOLUTE path and no resolved project — are
  structured ``invalid_path`` / ``project_not_found`` failures decided before any
  launch;
- an unlaunchable binary is the shared classifier's ``binary_not_found``.

The #651 verdict arms are here for a reason the unit tests cannot cover: they
assert that the ENGINE really does exit ``0`` for a script that never ran, and
that gda's stderr classification really does fire on what this Godot build
prints. A fixture-driven test would only prove the parser matches our fixtures.

- a missing ``res://`` entry script → ``script_not_found`` (GDA-DF-032);
- an entry script whose preloaded dependency does not compile →
  ``script_compile_failed`` (GDA-DF-007);
- a runtime GDScript error the script survived → still a SUCCESS, with the error
  surfaced as a classified diagnostic (GDA-DF-007);
- a deliberate ``quit(1)`` under ``--strict`` → the ``script_failed`` envelope and
  a non-zero gda process exit (GDA-DF-017), carrying the suite's own printed
  output as evidence, while the default arm above is unchanged.

**No e2e arm for the not-a-main-loop shape, deliberately.** An entry script that
compiles but does not extend ``SceneTree``/``MainLoop`` also never runs, and gda
now classifies it as ``incompatible_script_type`` — but the engine has **two**
behaviours for it and only one is a phantom success:

- it errors (``Can't load the script … as it doesn't inherit from SceneTree or
  MainLoop``) and exits ``0`` — the phantom success this classification fixes.
  Observed on a real run and pinned by ``tests/test_script_error_parser.py`` /
  ``tests/test_script_run_operation.py`` against that verbatim stderr;
- it errors and then **keeps running** — the engine falls through to the project's
  normal main loop, which idles forever headless. This is what a clean fixture
  project does here (reproduced repeatedly; not caused by the import cache or by
  other non-compiling scripts in the project, both refuted by probe).

The second is already a failure by a different route (``launch_timeout``, the
#655 path), so gda never reports success either way. Reproducing the first
on demand is not possible from project contents, and asserting only the weak
"never a success" invariant would cost a 120s timeout per run for no added
signal — so this shape stays unit-covered, with real captured stderr.

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

# --- The #651 fixtures: three shapes the engine reports on stderr while exiting 0.

# An entry script whose dependency does not compile. The engine reports the
# unresolvable preload as a load failure of THIS script and never runs it — the
# print below is what a passthrough-only channel wrongly reported success for.
BAD_DEPENDENCY_GD = """\
extends SceneTree

const Broken := preload("res://broken_dep.gd")

func _initialize() -> void:
\tprint("completed: true")
\tquit(0)
"""

BROKEN_DEP_GD = """\
extends RefCounted

func oops() -> void:
\t@@@ not valid @@@
"""

# A script that hits a runtime GDScript error, SURVIVES it (the failing call only
# aborts its own function) and quit(0)s. It really did run, so it stays a success —
# the error is what the classified diagnostics exist to surface.
RUNTIME_ERROR_GD = """\
extends SceneTree

func _initialize() -> void:
\t_boom()
\tprint("still alive")
\tquit(0)

func _boom() -> void:
\tvar d = null
\td.missing_method()
"""

# A script that RAN and tried to load a resource that is not there. It survives the
# failed load and quit(0)s, so the run is a success — the resource-load errors are
# diagnostics, not a verdict (#651 review claim 4).
RUNTIME_RESOURCE_LOAD_GD = """\
extends SceneTree

func _initialize() -> void:
\tvar r = load("res://missing.tres")
\tprint("loaded=", r)
\tquit(0)
"""

# A failing suite that reports the way a real GDScript test runner does — through
# print(), i.e. STDOUT. It is the fixture for the --strict evidence assertion:
# an envelope carrying only stderr would hold none of these lines.
FAILING_SUITE_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("FAIL test_damage: expected 5 got 4")
\tprint("1 of 3 tests failed")
\tquit(1)
"""


def _run_gda(*args: str, retry: bool = False) -> subprocess.CompletedProcess:
    """Invoke ``gda <args>`` as a subprocess (this checkout's editable gda, ADR-0011).

    ``retry`` re-runs once on a transient ``engine_crashed`` — a shared-``user://``
    log race under parallel e2e (not a gda bug; the race was fixed in #180) — so a
    happy path does not flake.
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
@pytest.mark.parametrize("form", ["hello.gd", "res://hello.gd"])
def test_script_run_accepts_both_path_forms(godot_project, form):
    # The #675 AC against the real engine: the project-relative form the rest of the
    # script group accepts now runs here too, and both forms report back the ONE
    # canonical res:// address — so a caller need not rewrite a path between
    # `script validate` and `script run`.
    (godot_project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        form,
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
        retry=True,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["path"] == "res://hello.gd"
    assert data["exit_status"] == 0
    assert "hello from script run" in data["stdout"]


@pytest.mark.e2e
def test_script_run_absolute_path_is_invalid_path(godot_project):
    # The one path form still refused (#675): an absolute path is a structured
    # invalid_path decided BEFORE any launch — an explicit ABI edge (ADR-0031),
    # never a crash or raw engine failure.
    (godot_project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        str(godot_project / "hello.gd"),  # absolute, even though it EXISTS
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
def test_script_run_missing_script_is_script_not_found(godot_project):
    # GDA-DF-032 against the REAL engine: Godot exits 0 for a res:// script that does
    # not exist, printing the load errors to stderr only. The verdict must come from
    # that stderr — a structured failure, never {"exit_status": 0}.
    run = _run_gda(
        "script",
        "run",
        "res://no-such-script.gd",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_not_found"
    assert err["category"] == "operation"
    assert "res://no-such-script.gd" in err["message"]


@pytest.mark.e2e
def test_script_run_parse_error_dependency_is_script_compile_failed(godot_project):
    # GDA-DF-007 against the REAL engine: the entry script compiles only if its
    # preloaded dependency does. It does not, so the entry never runs — yet Godot
    # exits 0 and the script's own "completed: true" line is never printed.
    (godot_project / "suite.gd").write_text(BAD_DEPENDENCY_GD, encoding="utf-8")
    (godot_project / "broken_dep.gd").write_text(BROKEN_DEP_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://suite.gd",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_compile_failed"
    assert err["category"] == "operation"
    # The engine's stderr is preserved as secondary evidence, naming the dependency
    # the entry script could not preload.
    assert "broken_dep.gd" in err["diagnostics"]


@pytest.mark.e2e
def test_script_run_runtime_error_is_a_success_carrying_diagnostics(godot_project):
    # The third GDA-DF-007 shape: the script RAN, raised, survived and quit(0). ADR-0031
    # still governs — a completed run is a success — but the error is no longer buried
    # in stderr prose: it is a classified diagnostic an agent can branch on.
    (godot_project / "runtime_error.gd").write_text(RUNTIME_ERROR_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://runtime_error.gd",
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
    assert "still alive" in data["stdout"]
    kinds = [d["kind"] for d in data["diagnostics"]]
    assert "runtime_error" in kinds
    runtime = next(d for d in data["diagnostics"] if d["kind"] == "runtime_error")
    assert runtime["path"] == "res://runtime_error.gd"
    assert runtime["line"] is not None


@pytest.mark.e2e
@pytest.mark.parametrize(
    "spelling",
    [
        "res://sub/../no-such-script.gd",
        "res://./no-such-script.gd",
        "res://sub//..//no-such-script.gd",
        # #675: the project-relative form is lifted onto res:// BEFORE the same
        # canonicalization runs, so its aliases must reach the verdict identically.
        "no-such-script.gd",
        "sub/../no-such-script.gd",
        "./no-such-script.gd",
    ],
)
def test_script_run_missing_entry_verdict_survives_path_aliasing(
    godot_project, spelling
):
    # #651 review claim 1, against the REAL engine: Godot resolves the address
    # before naming it, so these spellings all come back as `res://no-such-script.gd`.
    # Comparing the engine's spelling with the caller's raw one used to MISROUTE this
    # to script_compile_failed (only main.cpp's echoed argv matched). One canonical
    # identity restores the specific verdict for every spelling.
    (godot_project / "sub").mkdir(exist_ok=True)

    run = _run_gda(
        "script",
        "run",
        spelling,
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_not_found"


@pytest.mark.e2e
@pytest.mark.parametrize(
    "spelling",
    [
        "res://sub/../suite.gd",
        "res://./suite.gd",
        "res://sub//..//suite.gd",
        # #675: the same guard for the newly accepted form. A broken entry addressed
        # project-relatively must still classify script_compile_failed — if the lift
        # bypassed the canonical identity, this would regress to a phantom success.
        "suite.gd",
        "sub/../suite.gd",
        "./suite.gd",
    ],
)
def test_script_run_compile_failed_verdict_survives_path_aliasing(
    godot_project, spelling
):
    # The other half of claim 1, and the one that reported outright success before:
    # a non-compiling entry invoked by a non-canonical spelling never matched the
    # engine's canonical report, so gda passed the engine's exit 0 straight through.
    (godot_project / "sub").mkdir(exist_ok=True)
    (godot_project / "suite.gd").write_text(BAD_DEPENDENCY_GD, encoding="utf-8")
    (godot_project / "broken_dep.gd").write_text(BROKEN_DEP_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        spelling,
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_compile_failed"


@pytest.mark.e2e
def test_script_run_runtime_resource_load_failure_is_a_success_with_diagnostics(
    godot_project,
):
    # #651 review claim 4, against the REAL engine: the script RAN and its load()
    # failed. The run is a success (it completed and chose exit 0), and the engine's
    # resource-load errors are surfaced as classified diagnostics naming the
    # RESOURCE — not the entry — so the verdict is untouched.
    (godot_project / "runtime_load.gd").write_text(
        RUNTIME_RESOURCE_LOAD_GD, encoding="utf-8"
    )

    run = _run_gda(
        "script",
        "run",
        "res://runtime_load.gd",
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
    assert "loaded=" in data["stdout"]
    resource_errors = [
        d for d in data["diagnostics"] if d["kind"] == "resource_load_failed"
    ]
    assert resource_errors, data["diagnostics"]
    assert all(d["path"] == "res://missing.tres" for d in resource_errors)


@pytest.mark.e2e
def test_script_run_strict_fails_on_an_explicit_non_zero_quit(godot_project):
    # GDA-DF-017 against the REAL engine: a failing test quit(1)s. By default that is
    # data and gda exits 0 (asserted above); with --strict the gda PROCESS exits 4, so
    # a shell `&&` chain and a conventional CI step stop on it — observable without
    # parsing the JSON.
    (godot_project / "fail.gd").write_text(FAIL_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://fail.gd",
        "--strict",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_failed"
    assert err["category"] == "operation"
    assert "status 1" in err["message"]


@pytest.mark.e2e
def test_script_run_strict_envelope_carries_the_suites_stdout(godot_project):
    # The evidence assertion, against the REAL engine: a GDScript suite reports through
    # print(), so its failure detail is on STDOUT. The --strict envelope must carry it —
    # a CI caller that only gets an exit code and an empty diagnostics learns nothing.
    (godot_project / "suite_fail.gd").write_text(FAILING_SUITE_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://suite_fail.gd",
        "--strict",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_failed"
    diagnostics = err["diagnostics"]
    # Both labelled sections are present, and the suite's own printed failure detail
    # survives into the envelope.
    assert "--- script stdout ---" in diagnostics
    assert "--- script stderr ---" in diagnostics
    assert "FAIL test_damage: expected 5 got 4" in diagnostics
    assert "1 of 3 tests failed" in diagnostics
    # The printed lines are in the stdout section, not misfiled under stderr.
    stdout_section, _, stderr_section = diagnostics.partition("--- script stderr ---")
    assert "1 of 3 tests failed" in stdout_section
    assert "1 of 3 tests failed" not in stderr_section


@pytest.mark.e2e
def test_script_run_strict_leaves_a_passing_script_a_success(godot_project):
    # --strict changes only the non-zero arm: a clean run is the same passthrough
    # success, so a CI step can pass --strict unconditionally.
    (godot_project / "hello.gd").write_text(HELLO_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://hello.gd",
        "--strict",
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
    assert data["diagnostics"] == []


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
