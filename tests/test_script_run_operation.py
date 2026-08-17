"""Direct tests for the ScriptRun operation (issue #343, ADR-0031, #675).

``script run`` is the third execution shape: a user-script passthrough run whose
recipe — accept either script-path form + require a resolved project, then launch
``godot --headless --path <project> --script <res://…>`` and BIFURCATE by whose
failure it is — lives in :func:`gda.commands.script.run_script_run_operation`, a PURE
function that RETURNS the outcome (never emits/exits).

These tests drive that function directly with the injected launch seam (a
``FakeLaunch`` returning a canned :class:`~gda.runner.RunResult`), so the whole
bifurcation is asserted without a real engine and without CliRunner:

- a clean engine exit (``exit_code >= 0``) — INCLUDING a non-zero ``quit(1)`` —
  is a SUCCESS ``ScriptRunResult`` with the script's output passed through;
- a launch failure / signal death is a gda-level Error envelope, classified by
  the SAME shared ``classify_launch_or_crash`` the export channel uses;
- the two pre-run ABI edges (an ABSOLUTE path, no resolved project) are structured
  failures decided BEFORE any launch;
- both accepted path forms — project-relative and ``res://`` (#675) — reach the
  SAME canonical address, so the argv, the entry-load verdict and the reported
  ``path`` cannot diverge by input spelling.

They are the recipe's own test surface, complementary to the e2e round-trip in
``tests/test_e2e_script_run.py`` (real Godot).
"""

from pathlib import Path

import pytest

from gda.commands.script import (  # the single fully-bound descriptor (ADR-0023)
    SCRIPT_RUN_COMMAND,
    ScriptRunResult,
    run_script_run_operation,
)
from gda.errors import Failure
from gda.execution import ExecutionKind
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.runner import LaunchFailure, RunResult

PROJECT = Path("/tmp/project")


class FakeLaunch:
    """A fakeable :func:`gda.runner.launch` that records its call and returns a canned run.

    Satisfies the ``LaunchFn`` seam so the operation's launch/crash bifurcation is
    exercised without a real engine — the ``script run`` twin of ``FakeRunner`` /
    ``FakeExportRunner``. Records the ``(binary, args, cwd, timeout, timeout_label)``
    it was called with so argv-tail construction (and ``cwd=None``) can be asserted.
    """

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = "Godot",
    ) -> RunResult:
        self.calls.append((binary, args, cwd, timeout, timeout_label))
        return self.result


def _run(
    result: RunResult,
    *,
    script: str = "res://tests/logic.gd",
    project: Path | None = PROJECT,
    godot: str | None = "/tmp/Godot",
    strict: bool = False,
) -> tuple[ScriptRunResult | Failure, FakeLaunch]:
    """Invoke the operation with the launch seam pinned to a ``FakeLaunch``."""
    launch = FakeLaunch(result)
    outcome = run_script_run_operation(
        script=script,
        godot=godot,
        project=project,
        strict=strict,
        make_launch=launch,
    )
    return outcome, launch


def test_script_run_command_is_the_passthrough_channel():
    # `script run` is the fourth execution shape — a user-script passthrough that
    # emits no ADR-0002 sentinel — so it carries the SCRIPT_RUN kind and routes by
    # its recipe (ADR-0031 / ADR-0023), never `cmd.emit`.
    assert SCRIPT_RUN_COMMAND.kind is ExecutionKind.SCRIPT_RUN
    assert SCRIPT_RUN_COMMAND.recipe is not None


def test_clean_zero_exit_passes_the_run_through():
    # The happy path: the engine exits 0, so the operation RETURNS the typed
    # ScriptRunResult carrying the script's own stdout/stderr verbatim.
    outcome, launch = _run(RunResult(stdout="hello\n", stderr="warn\n", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0
    assert outcome.stdout == "hello\n"
    assert outcome.stderr == "warn\n"
    # The argv tail is `--path <project> --script <res path>`, launched with cwd=None
    # (mirroring the sentinel runner, NOT the export channel's cwd=project).
    (binary, args, cwd, _timeout, label) = launch.calls[0]
    assert args == ["--path", str(PROJECT), "--script", "res://tests/logic.gd"]
    assert cwd is None
    assert label == "Godot script"


def test_non_zero_script_exit_is_a_success_not_a_failure():
    # THE CRUX (ADR-0031): a deliberate quit(1) is a clean engine exit, so it is a
    # SUCCESS result carrying exit_status=1 — gda does not interpret the script's
    # semantics. This is the one command whose success result can be non-zero.
    outcome, _ = _run(RunResult(stdout="assert failed\n", stderr="", exit_code=1))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 1
    assert outcome.stdout == "assert failed\n"


def test_binary_not_found_is_the_shared_classifier_failure():
    # A synthesized NOT_FOUND launch failure → binary_not_found, via the SAME
    # classify_launch_or_crash the export channel uses (no GDScript-mirrored code).
    outcome, _ = _run(
        RunResult(
            stdout="",
            stderr="gda: Godot binary could not be launched\n",
            exit_code=EXIT_NOT_FOUND,
            launch_failure=LaunchFailure.NOT_FOUND,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "binary_not_found"
    assert outcome.exit_code == EXIT_NOT_FOUND


def test_launch_timeout_is_the_shared_classifier_failure():
    # A synthesized TIMEOUT launch failure → launch_timeout.
    outcome, _ = _run(
        RunResult(
            stdout="",
            stderr="gda: Godot script timed out after 120.0s\n",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        )
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert outcome.exit_code == EXIT_TIMEOUT


def test_signal_death_is_engine_crashed():
    # A negative exit_code is a signal death (e.g. SIGSEGV) → engine_crashed, an
    # operation-category gda failure — never a raw negative exit leaking out.
    outcome, _ = _run(RunResult(stdout="", stderr="", exit_code=-11))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "engine_crashed"
    assert outcome.exit_code == EXIT_OPERATION
    assert "11" in outcome.error.message


@pytest.mark.parametrize(
    "script",
    [
        "res://tests/logic.gd",
        "tests/logic.gd",
        # The project-relative form is lifted onto res:// and then canonicalized by
        # the SAME shared helper, so its `./` and `..` noise collapses too.
        "./tests/logic.gd",
        "tests/sub/../logic.gd",
        "tests//logic.gd",
    ],
)
def test_both_path_forms_reach_one_canonical_address(script):
    # #675: `script run` accepts the project-relative form the rest of the script
    # group accepts, beside res://. Every accepted spelling must converge on ONE
    # address — the argv handed to the engine AND the path the result reports — or
    # the entry-load verdict (which matches on it) would depend on how the caller
    # happened to type the path.
    outcome, launch = _run(
        RunResult(stdout="ok\n", stderr="", exit_code=0), script=script
    )

    assert isinstance(outcome, ScriptRunResult), getattr(outcome, "error", None)
    (_binary, args, _cwd, _timeout, _label) = launch.calls[0]
    assert args == ["--path", str(PROJECT), "--script", "res://tests/logic.gd"]
    assert outcome.path == "res://tests/logic.gd"


@pytest.mark.parametrize(
    "script",
    [
        # Absolute: outside the --project context (#675 keeps this refusal).
        "/abs/logic.gd",
        # Another engine scheme: lifting one would splice a second scheme into a
        # res:// address (`res://user:/x.gd`) and hunt a path nobody typed.
        "user://x.gd",
        "uid://cabc123",
        # Collapses to the project ROOT — a directory, not a script. The empty string
        # is the real-world shape: an unset `gda script run "$SCRIPT"`.
        "",
        ".",
        "./",
        "sub/..",
        "res://",
        "res://.",
        # Escapes ABOVE the root, in both spellings. `..` phantom-succeeded (the
        # engine's `Can't load script: res://..` parses back as `res://.`), and
        # `../outside.gd` actually EXECUTED a script outside the project.
        "..",
        "sub/../..",
        "../outside.gd",
        "res://..",
        "res://../outside.gd",
        "../../etc/passwd",
        # A leading `~` is a HOME reference — a filesystem address form. It reaches
        # the operation unexpanded only when the shared normalizer could not resolve
        # the user (#699); a resolvable `~/x.gd` arrives already expanded to an
        # absolute path, refused above. Both tilde outcomes end on ONE refusal.
        "~nosuchuser/x.gd",
        "~/x.gd",
    ],
)
def test_a_non_project_scoped_path_is_invalid_path_before_any_launch(script):
    # The path ABI edge (ADR-0031, narrowed by #675): accepting the project-relative
    # form must not accept everything ELSE that is merely non-absolute. The root and
    # escape cases are load-bearing — the engine answers `Can't load script: res://.`
    # / `res://..`, whose address the parser reads back with the sentence period
    # stripped, so it never matches the entry and the run reported a PHANTOM SUCCESS
    # (exit 0). A resolvable escape is worse: `../outside.gd` RAN a script outside the
    # project, which is exactly the ADR-0009 widening the amendment cites as its
    # reason for refusing absolute paths.
    outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), script=script)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "invalid_path"
    assert not launch.calls, "no engine launch on an invalid path"
    # The message quotes what the user typed and names the ACCEPTED forms, so one
    # wording serves every refused shape and tells the caller what to pass instead.
    assert repr(script) in outcome.error.message
    assert "project-relative" in outcome.error.message
    assert "res://" in outcome.error.message


def test_no_resolved_project_is_project_not_found_before_any_launch():
    # No resolved project → structured project_not_found, before any launch
    # (the other ABI edge, ADR-0031).
    outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), project=None)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "project_not_found"
    assert not launch.calls


def test_empty_godot_is_a_structured_binary_failure_not_a_traceback():
    # An empty `--godot ""` makes binary resolution raise before any launch; it is
    # mapped to the structured binary_not_found envelope, never a raw traceback.
    outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), godot="")

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "binary_not_found"
    assert not launch.calls


def test_result_is_the_thin_promotion_dropping_launch_failure():
    # The success DTO is the thin boundary promotion of the internal Raw run: it
    # drops `launch_failure` and renames exit_code→exit_status, adding only the
    # #651 diagnostics channel. (A clean exit never has a launch_failure set anyway.)
    outcome, _ = _run(RunResult(stdout="out", stderr="err", exit_code=7))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.model_dump() == {
        # gda's own field, not the run's: the canonical address both input forms
        # converge on (#675).
        "path": "res://tests/logic.gd",
        "exit_status": 7,
        "stdout": "out",
        "stderr": "err",
        "diagnostics": [],
    }


# --- The #651 verdict: gda decides whether the engine ran what it was asked to.
#
# Godot exits 0 for a missing entry script, for one that fails to parse, AND for one
# that is not a SceneTree/MainLoop, so the passthrough reported a phantom success for
# all three. These drive the operation with stderr captured VERBATIM from a real
# engine run (the same captures the parser's own tests use, see
# tests/test_script_error_parser.py) so the fixtures cannot drift into something the
# engine never prints.

MISSING_STDERR = """\
ERROR: Attempt to open script 'res://tests/logic.gd' resulted in error 'File not found'.
   at: load_source_code (modules/gdscript/gdscript.cpp:1127)
ERROR: Failed loading resource: res://tests/logic.gd.
   at: _load (core/io/resource_loader.cpp:343)
ERROR: Can't load script: res://tests/logic.gd
   at: start (main/main.cpp:4271)
"""

PARSE_ERROR_STDERR = """\
SCRIPT ERROR: Parse Error: Expected end of statement after expression, found "Identifier" instead.
          at: GDScript::reload (res://tests/logic.gd:4)
ERROR: Failed to load script "res://tests/logic.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2907)
"""

RUNTIME_ERROR_STDERR = """\
SCRIPT ERROR: Invalid call. Nonexistent function 'missing_method' in base 'Nil'.
          at: _boom (res://tests/logic.gd:10)
          GDScript backtrace (most recent call first):
              [0] _boom (res://tests/logic.gd:10)
              [1] _initialize (res://tests/logic.gd:4)
"""

NOT_A_MAIN_LOOP_STDERR = """\
ERROR: Can't load the script "res://tests/logic.gd" as it doesn't inherit from SceneTree or MainLoop.
   at: start (main/main.cpp:4286)
"""


def test_missing_entry_script_is_a_failure_despite_the_zero_exit():
    # GDA-DF-032: the engine exits 0 for a script that does not exist. The verdict
    # comes from the stderr evidence, never from the exit code.
    outcome, _ = _run(RunResult(stdout="", stderr=MISSING_STDERR, exit_code=0))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_not_found"
    assert outcome.exit_code == EXIT_OPERATION
    assert "res://tests/logic.gd" in outcome.error.message
    # The raw stderr is preserved as secondary evidence on the envelope.
    assert outcome.error.diagnostics == MISSING_STDERR


def test_entry_parse_error_is_a_failure_despite_the_zero_exit():
    # GDA-DF-007: a non-compiling entry script also leaves exit 0 behind. The
    # engine's own sentence is carried in the message so the reason is readable
    # without parsing `diagnostics`.
    outcome, _ = _run(RunResult(stdout="", stderr=PARSE_ERROR_STDERR, exit_code=0))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_compile_failed"
    assert outcome.exit_code == EXIT_OPERATION
    assert "Parse error" in outcome.error.message


def test_a_load_error_for_another_script_stays_a_success():
    # The false-positive guard at the operation level: a script that RAN and itself
    # failed to load some OTHER resource must stay a passthrough success.
    outcome, _ = _run(
        RunResult(stdout="done\n", stderr=MISSING_STDERR, exit_code=0),
        script="res://tests/other.gd",
    )

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0


def test_runtime_script_error_is_surfaced_as_a_diagnostic_not_a_failure():
    # GDA-DF-007's third shape: the script ran, hit a GDScript error, survived it and
    # quit(0). ADR-0031 still governs — the run completed — but the error is no longer
    # buried in stderr prose: it is a classified diagnostic on the success result.
    outcome, _ = _run(
        RunResult(stdout="ok\n", stderr=RUNTIME_ERROR_STDERR, exit_code=0)
    )

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0
    assert [d.kind.value for d in outcome.diagnostics] == ["runtime_error"]
    assert outcome.diagnostics[0].path == "res://tests/logic.gd"
    assert outcome.diagnostics[0].line == 10
    # The verbatim stream is still there — the diagnostics are additive.
    assert outcome.stderr == RUNTIME_ERROR_STDERR


def test_a_non_canonical_entry_spelling_still_reaches_the_verdict():
    # #651 review claim 1, at the operation level: the engine reports the CANONICAL
    # address it resolved, so an entry invoked as `res://sub/../logic.gd` came back
    # named `res://tests/logic.gd`... never matching, and the failed run reported
    # success. The operation now fixes one canonical identity before it launches.
    outcome, launch = _run(
        RunResult(stdout="", stderr=PARSE_ERROR_STDERR, exit_code=0),
        script="res://tests/sub/../logic.gd",
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_compile_failed"
    # The canonical identity is what the engine is asked to run, too, so both sides
    # of every later comparison agree.
    (_binary, args, _cwd, _timeout, _label) = launch.calls[0]
    assert args[-1] == "res://tests/logic.gd"
    # ...and what the failure message names, so the agent sees one spelling.
    assert "res://tests/logic.gd" in outcome.error.message


def test_a_non_canonical_missing_entry_keeps_the_specific_code():
    # The misrouting half of claim 1: with a raw comparison the only line matching
    # the caller's spelling was main.cpp's echo, which maps to script_compile_failed.
    # Canonicalizing restores script_not_found.
    outcome, _ = _run(
        RunResult(stdout="", stderr=MISSING_STDERR, exit_code=0),
        script="res://tests/./logic.gd",
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_not_found"


@pytest.mark.parametrize(
    ("script", "stderr", "code"),
    [
        ("tests/logic.gd", MISSING_STDERR, "script_not_found"),
        ("tests/logic.gd", PARSE_ERROR_STDERR, "script_compile_failed"),
        ("tests/logic.gd", NOT_A_MAIN_LOOP_STDERR, "incompatible_script_type"),
        # The non-canonical project-relative spellings must land on the verdict too:
        # the lift happens BEFORE canonicalization, so `..`/`.` inside a relative
        # path still collapses onto the address the engine reports back.
        ("tests/sub/../logic.gd", MISSING_STDERR, "script_not_found"),
        ("./tests/logic.gd", PARSE_ERROR_STDERR, "script_compile_failed"),
    ],
)
def test_a_project_relative_entry_still_reaches_the_verdict(script, stderr, code):
    # The #675 × #651 interaction, and the reason the new form MUST flow through the
    # same normalization chain: the entry-load verdict matches the engine's reported
    # (canonical, res://) address against the caller's. A project-relative path that
    # skipped the lift would never match, and every never-ran shape would silently
    # regress to the phantom success #651 removed.
    outcome, launch = _run(
        RunResult(stdout="", stderr=stderr, exit_code=0), script=script
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == code
    assert outcome.exit_code == EXIT_OPERATION
    # One spelling on every side: the argv, and the message the agent reads.
    (_binary, args, _cwd, _timeout, _label) = launch.calls[0]
    assert args[-1] == "res://tests/logic.gd"
    assert "res://tests/logic.gd" in outcome.error.message


@pytest.mark.parametrize("script", ["..foo.gd", "res://..foo.gd", "sub/..foo.gd"])
def test_a_leading_dot_dot_FILENAME_is_still_accepted(script):
    # The escape refusal keys on the canonical remainder's first SEGMENT, not on a
    # string prefix. A file whose NAME merely starts with two dots is legal and must
    # still run — a naive `startswith("..")` would refuse it.
    outcome, launch = _run(
        RunResult(stdout="ok\n", stderr="", exit_code=0), script=script
    )

    assert isinstance(outcome, ScriptRunResult), getattr(outcome, "error", None)
    assert outcome.path.endswith("..foo.gd")
    assert launch.calls, "an accepted path must reach the engine"


def test_a_project_relative_load_error_for_another_script_stays_a_success():
    # The false-positive guard survives the new form: lifting a project-relative path
    # must not widen what counts as the ENTRY. A script addressed `tests/other.gd`
    # that itself failed to load `res://tests/logic.gd` is still a passthrough
    # success — the lift changes the spelling, never the identity being matched.
    outcome, _ = _run(
        RunResult(stdout="done\n", stderr=MISSING_STDERR, exit_code=0),
        script="tests/other.gd",
    )

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0
    assert outcome.path == "res://tests/other.gd"


def test_a_runtime_resource_load_failure_stays_a_success():
    # #651 review claim 4: a script that RAN and failed to load a resource is still
    # a successful run — the failure names a resource, not the entry — but the
    # engine's report is now visible as a classified diagnostic instead of prose.
    stderr = (
        "ERROR: Cannot open file 'res://missing.tres'.\n"
        "   at: load (scene/resources/resource_format_text.cpp:1430)\n"
        "ERROR: Failed loading resource: res://missing.tres.\n"
        "   at: _load (core/io/resource_loader.cpp:343)\n"
    )
    outcome, _ = _run(RunResult(stdout="loaded=<null>\n", stderr=stderr, exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0
    assert [d.kind.value for d in outcome.diagnostics] == [
        "resource_load_failed",
        "resource_load_failed",
    ]
    assert outcome.diagnostics[0].path == "res://missing.tres"


def test_not_a_main_loop_entry_is_a_failure_despite_the_zero_exit():
    # The third never-ran shape: the script exists and compiles, but cannot BE the
    # entry point, so the engine refuses it and exits 0. It reuses the registered
    # `incompatible_script_type` — the same condition `script attach` names for a
    # base type that is wrong for the requested use.
    outcome, _ = _run(RunResult(stdout="", stderr=NOT_A_MAIN_LOOP_STDERR, exit_code=0))

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "incompatible_script_type"
    assert outcome.exit_code == EXIT_OPERATION
    assert "SceneTree" in outcome.error.message


def test_every_entry_failure_kind_has_a_verdict_code():
    # A kind in the precedence list with no row in the code map would be a KeyError
    # on a real failure path — the one way this pair can break. Pin them in lockstep,
    # and pin that every code they name is actually registered.
    from gda.commands.script import _ENTRY_FAILURE_CODES
    from gda.error_codes import ERROR_CODE_BY_CODE
    from gda.script_errors import _ENTRY_FAILURE_PRECEDENCE

    assert set(_ENTRY_FAILURE_CODES) == set(_ENTRY_FAILURE_PRECEDENCE)
    for code in _ENTRY_FAILURE_CODES.values():
        assert code in ERROR_CODE_BY_CODE


def test_strict_maps_a_non_zero_exit_onto_the_registered_failure():
    # GDA-DF-017, opted in: a test that quit(1) becomes the script_failed envelope so
    # a shell `&&` chain stops. The gda exit is the REGISTERED operation code, never
    # the child's own status — a script's quit(3) must not alias EXIT_VERSION.
    outcome, _ = _run(
        RunResult(stdout="1 test failed\n", stderr="boom\n", exit_code=3), strict=True
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_failed"
    assert outcome.exit_code == EXIT_OPERATION
    assert "status 3" in outcome.error.message


def test_strict_carries_both_script_streams_as_evidence():
    # THE point of the flag: a GDScript test runner reports through print(), i.e.
    # STDOUT. An envelope carrying only stderr would hand a CI caller a failure with
    # no content, so diagnostics carries both streams under fixed labels.
    outcome, _ = _run(
        RunResult(
            stdout="FAIL test_damage: expected 5 got 4\n",
            stderr="engine warning\n",
            exit_code=1,
        ),
        strict=True,
    )

    assert isinstance(outcome, Failure)
    diagnostics = outcome.error.diagnostics
    assert "FAIL test_damage: expected 5 got 4" in diagnostics
    assert "engine warning" in diagnostics
    assert diagnostics == (
        "--- script stdout ---\n"
        "FAIL test_damage: expected 5 got 4\n"
        "--- script stderr ---\n"
        "engine warning\n"
    )


def test_strict_evidence_layout_is_stable_when_a_stream_is_empty():
    # Both sections are ALWAYS present — an empty stream yields an empty section, not
    # a missing one — so a consumer can split on the labels without first discovering
    # which streams the script happened to write to.
    outcome, _ = _run(
        RunResult(stdout="", stderr="only stderr\n", exit_code=1), strict=True
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.diagnostics == (
        "--- script stdout ---\n--- script stderr ---\nonly stderr\n"
    )


def test_strict_leaves_a_zero_exit_a_success():
    outcome, _ = _run(
        RunResult(stdout="all green\n", stderr="", exit_code=0), strict=True
    )

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 0


def test_the_default_still_passes_a_non_zero_exit_through():
    # The contract ADR-0031 recorded is unchanged without --strict: this is the guard
    # that the #651 opt-in did not quietly flip the default.
    outcome, _ = _run(RunResult(stdout="1 test failed\n", stderr="", exit_code=1))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 1


def test_strict_does_not_shadow_the_never_ran_verdict():
    # A missing script under --strict must still be script_not_found: "the script
    # chose to fail" and "the script never ran" are different answers, and the
    # engine's exit 0 would make strict alone report success.
    outcome, _ = _run(
        RunResult(stdout="", stderr=MISSING_STDERR, exit_code=0), strict=True
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_not_found"
