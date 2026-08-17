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
import time

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
    # Absolute stays refused (#675) even for a script that EXISTS in the project: the
    # engine would report its errors under the res:// spelling, which would break the
    # canonical-identity match the never-ran verdict depends on. A structured
    # invalid_path decided BEFORE any launch — an explicit ABI edge (ADR-0031).
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
@pytest.mark.parametrize(
    "script",
    [
        "",
        ".",
        "sub/..",
        "user://x.gd",
        "uid://cabc123",
        # Escapes above the project root, in both spellings.
        "..",
        "sub/../..",
        "../outside.gd",
        "res://..",
        "res://../outside.gd",
    ],
)
def test_script_run_non_project_scoped_paths_are_refused_before_launch(
    godot_project, script
):
    # Accepting the project-relative form must not accept everything merely
    # non-absolute. Against the REAL engine, because these are exactly the cases where
    # the engine's own report defeats the verdict: `gda script run ""` normalized to
    # `res://.`, launched, and the engine's `Can't load script: res://.` parsed back
    # as `res://` — no match, so a run that never happened reported exit 0 SUCCESS.
    # `..` did the same one level up. The other-scheme cases spawned the engine
    # against `res://user:/x.gd`, an address the caller never typed. And a RESOLVABLE
    # escape (`../outside.gd`) actually executed a script outside the project — the
    # ADR-0009 widening the amendment cites as its reason for refusing absolute paths,
    # so it must not be reachable by the relative spelling either.
    run = _run_gda(
        "script",
        "run",
        script,
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 4, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert "exit_status" not in data, "a refused path must never report a run"
    err = data["error"]
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


# --- #655: the three arms only a real engine can prove. Each keeps its wall clock to
# a few seconds by choosing a small `--timeout`, never the 120s default.
#
# What a fixture-driven test could NOT establish, and these do: that Godot really
# keeps running after a script error aborts `_initialize` before its `quit()` (so the
# run really does hang rather than fail); that its stdout and stderr really arrive
# incrementally rather than at process exit (so the capture really is preserved and
# the error really is visible before the ceiling); and that gda's own `--log-file`
# injection does not divert the error stream it reads.

# A script whose entry point dies before its own quit(): the runtime error aborts
# `_initialize`, so `quit()` is never reached and the engine falls through to its
# main loop and idles forever. The marker is what it WOULD have printed.
ABORTS_BEFORE_QUIT_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("SUITE START")
\tvar d = null
\td.missing_method()
\tprint("SUITE DONE")
\tquit(0)
"""

# A healthy suite that simply takes longer than the ceiling it is given. It prints
# as it goes, which is what makes its partial output worth preserving.
SLOW_BUT_HEALTHY_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("SUITE START")
\tvar t := Time.get_ticks_msec()
\twhile Time.get_ticks_msec() - t < 30000:
\t\tpass
\tprint("SUITE DONE")
\tquit(0)
"""


@pytest.mark.e2e
def test_script_run_returns_the_captured_error_of_an_aborted_run(godot_project):
    # THE #655 AC (GDA-DF-012): a script whose runtime error prevents quit() returns
    # the captured script error within a stated bound in SECONDS, not the full
    # timeout, when a completion marker is declared. The generous --timeout is the
    # point: the run must be ended by the marker rule, so a pass proves the abort
    # fired rather than the ceiling.
    (godot_project / "aborts.gd").write_text(ABORTS_BEFORE_QUIT_GD, encoding="utf-8")

    started = time.monotonic()
    run = _run_gda(
        "script",
        "run",
        "res://aborts.gd",
        "--completion-marker",
        "SUITE DONE",
        "--timeout",
        "60",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )
    elapsed = time.monotonic() - started

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "script_aborted"
    assert err["category"] == "operation"
    # In seconds, and nowhere near the ceiling it was given.
    assert elapsed < 30.0, f"the abort took {elapsed:.1f}s"
    assert "60.0s was not reached" in err["message"]
    # The engine's own error — the thing the old envelope discarded — is back, both as
    # the classified line and verbatim in the labelled stderr section.
    assert "Nonexistent function 'missing_method'" in err["diagnostics"]
    assert "runtime_error: res://aborts.gd:6" in err["diagnostics"]
    # And so is the output the run produced before it died.
    assert "SUITE START" in err["diagnostics"]


@pytest.mark.e2e
def test_script_run_timeout_returns_partial_output_elapsed_and_a_phase(godot_project):
    # THE #655 AC (GDA-DF-032): a run exceeding --timeout returns the captured partial
    # output with the cap stated, the elapsed seconds, and one enumerated termination
    # phase — so a suite that is merely slow is no longer indistinguishable from a
    # hang. No marker is declared here, so this is the plain timeout path.
    (godot_project / "slow.gd").write_text(SLOW_BUT_HEALTHY_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://slow.gd",
        "--timeout",
        "4",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    assert run.returncode == 124, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "launch_timeout"
    assert err["category"] == "environment"
    # The ceiling that was reached, the wall clock, and the phase — all in the message.
    assert "--timeout of 4.0s" in err["message"]
    assert "elapsed 4." in err["message"]
    assert "termination phase 'output_seen'" in err["message"]
    assert "16384 UTF-8 bytes (16 KiB)" in err["message"]
    # The partial output the engine had already written, which the buffered capture
    # used to discard. It got as far as SUITE START and no further.
    assert "SUITE START" in err["diagnostics"]
    assert "SUITE DONE" not in err["diagnostics"]
    # A healthy suite has a clean error stream, and saying so is the diagnosis.
    assert "no recognized script errors" in err["diagnostics"]


@pytest.mark.e2e
def test_script_run_without_a_marker_waits_out_the_timeout_but_still_captures(
    godot_project,
):
    # The marker is OPT-IN (ADR-0031 rejected imposing a gda-owned sentinel on a user
    # script), so the SAME aborting script with no marker declared must run to the
    # ceiling — never ended early on gda's own initiative. It still comes back with
    # the captured error, which is the half of the fix that needs no opt-in at all.
    (godot_project / "aborts.gd").write_text(ABORTS_BEFORE_QUIT_GD, encoding="utf-8")

    started = time.monotonic()
    run = _run_gda(
        "script",
        "run",
        "res://aborts.gd",
        "--timeout",
        "5",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )
    elapsed = time.monotonic() - started

    assert run.returncode == 124, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "launch_timeout"
    # It waited: the ceiling, not the ~3s the marker rule would have taken.
    assert elapsed >= 5.0, f"the run ended early at {elapsed:.1f}s without a marker"
    # And the error Godot printed at ~0.5s is in the envelope regardless.
    assert "runtime_error: res://aborts.gd:6" in err["diagnostics"]
    assert "SUITE START" in err["diagnostics"]


# A script that survives a RECOVERABLE runtime error and then works QUIETLY before
# printing its marker. The error aborts only `_recoverable`, so `_initialize` carries
# on — and it prints nothing for well over the abort's silence window, which is
# exactly the shape that made an earlier silence-only rule kill a healthy run.
QUIET_SURVIVOR_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("SUITE START")
\t_recoverable()
\tvar acc := 0.0
\tvar t := Time.get_ticks_msec()
\twhile Time.get_ticks_msec() - t < 10000:
\t\tacc += sqrt(float(Time.get_ticks_usec() % 977))
\tprint("SUITE DONE acc=", acc)
\tquit(0)

func _recoverable() -> void:
\tvar d = null
\td.missing_method()
"""


@pytest.mark.e2e
def test_script_run_never_aborts_a_quiet_but_still_working_run(godot_project):
    # THE REVIEWED DEFECT, against the real engine. An earlier rule armed on any parsed
    # diagnostic plus silence, which killed this run at ~3s even though it goes on to
    # finish: a GDScript runtime error aborts only the function that raised it, and a
    # surviving script may then compute for a long time WITHOUT printing. Only the
    # engine can prove that the error really is survivable here and that the process
    # really does keep burning CPU while quiet, which is what now spares it.
    (godot_project / "survivor.gd").write_text(QUIET_SURVIVOR_GD, encoding="utf-8")

    run = _run_gda(
        "script",
        "run",
        "res://survivor.gd",
        "--completion-marker",
        "SUITE DONE",
        "--timeout",
        "60",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )

    # A SUCCESS: the marker was reached, so there was never an abort to report.
    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert "error" not in data
    assert data["exit_status"] == 0
    assert "SUITE DONE" in data["stdout"]
    # The survived error is still surfaced — as a classified diagnostic on a
    # successful run, which is where a recoverable failure belongs (#651).
    assert any(d["kind"] == "runtime_error" for d in data["diagnostics"])


@pytest.mark.e2e
def test_script_run_abort_still_lands_within_its_stated_bound(godot_project):
    # The other side of the same trade: buying that safety with a CPU-idleness check
    # must not cost the GDA-DF-012 case its speed. The engine really does go idle when
    # the entry dies, so the abort must still land in seconds — around two silence
    # windows plus startup — nowhere near the ceiling it was given.
    (godot_project / "aborts.gd").write_text(ABORTS_BEFORE_QUIT_GD, encoding="utf-8")

    started = time.monotonic()
    run = _run_gda(
        "script",
        "run",
        "res://aborts.gd",
        "--completion-marker",
        "SUITE DONE",
        "--timeout",
        "120",
        "--project",
        str(godot_project),
        "--godot",
        str(GODOT),
        "--json",
    )
    elapsed = time.monotonic() - started

    assert run.returncode == 4, run.stdout + run.stderr
    assert json.loads(run.stdout)["error"]["code"] == "script_aborted"
    assert elapsed < 20.0, f"the abort took {elapsed:.1f}s against a 120s ceiling"
