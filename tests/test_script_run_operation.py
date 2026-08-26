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
  ``path`` cannot diverge by input spelling;
- a run GDA ENDED — at the caller's ``--timeout``, or early because a declared
  ``--completion-marker`` never appeared — is an Error envelope carrying the run's
  EVIDENCE (#655): the captured partial output under fixed labels, the elapsed
  clock, an enumerated termination phase, and the recognized script errors. The
  capture MECHANISM that produces those results is asserted against real pipes in
  ``tests/test_launch.py``; what is asserted here is the classification.

They are the recipe's own test surface, complementary to the e2e round-trip in
``tests/test_e2e_script_run.py`` (real Godot).
"""

from pathlib import Path

import pytest

from gda.commands.script import (  # the single fully-bound descriptor (ADR-0023)
    DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
    SCRIPT_RUN_ABORT_SILENCE_SECONDS,
    SCRIPT_RUN_COMMAND,
    SCRIPT_STDOUT_CAP,
    ScriptRunResult,
    TerminationPhase,
    _CompletionMarkerWatch,
    run_script_run_operation,
)
from gda.errors import (
    SCRIPT_OUTPUT_STDERR_HEADER,
    SCRIPT_OUTPUT_STDOUT_HEADER,
    SCRIPT_OUTPUT_TAIL_CAP_BYTES,
    Failure,
)
from gda.execution import ExecutionKind
from gda.exit_codes import EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_TIMEOUT
from gda.runner import LaunchFailure, LaunchWatch, RunResult

PROJECT = Path("/tmp/project")
# The canonical entry the ABORTED_STDERR fixture names, so attribution matches.
ENTRY = "res://tests/logic.gd"


class FakeLaunch:
    """A fakeable :func:`gda.runner.launch` that records its call and returns a canned run.

    Satisfies the ``LaunchFn`` seam so the operation's launch/crash bifurcation is
    exercised without a real engine — the ``script run`` twin of ``FakeRunner`` /
    ``FakeExportRunner``. Records the
    ``(binary, args, cwd, timeout, timeout_label, watch)`` it was called with so
    argv-tail construction (and ``cwd=None``) can be asserted — and, since #655, so
    can the ``timeout`` the caller chose and the ``watch`` that selects the
    streaming capture.
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
        watch: LaunchWatch | None = None,
    ) -> RunResult:
        self.calls.append((binary, args, cwd, timeout, timeout_label, watch))
        return self.result


def _run(
    result: RunResult,
    *,
    script: str = "res://tests/logic.gd",
    project: Path | None = PROJECT,
    godot: str | None = "/tmp/Godot",
    strict: bool = False,
    timeout: float = DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
    completion_marker: str | None = None,
) -> tuple[ScriptRunResult | Failure, FakeLaunch]:
    """Invoke the operation with the launch seam pinned to a ``FakeLaunch``."""
    launch = FakeLaunch(result)
    outcome = run_script_run_operation(
        script=script,
        godot=godot,
        project=project,
        strict=strict,
        make_launch=launch,
        timeout=timeout,
        completion_marker=completion_marker,
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
    (binary, args, cwd, _timeout, label, watch) = launch.calls[0]
    assert args == ["--path", str(PROJECT), "--script", "res://tests/logic.gd"]
    assert cwd is None
    assert label == "Godot script"
    # A watch is ALWAYS passed (#655): it is what selects the shared primitive's
    # streaming capture, so partial output survives a timeout even for a caller who
    # declared no completion marker.
    assert watch is not None


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


def test_launch_timeout_keeps_its_registered_code_and_exit():
    # A synthesized TIMEOUT launch failure → launch_timeout. Since #655 this channel
    # classifies it ITSELF (to attach the captured evidence) rather than through the
    # shared classify_launch_or_crash prefix, so the code and exit are pinned here:
    # the richer envelope must not have quietly become a different failure.
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
    (_binary, args, _cwd, _timeout, _label, _watch) = launch.calls[0]
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
        "stdout_bytes": 3,
        "stdout_truncated": False,
        "stdout_file": None,
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
    (_binary, args, _cwd, _timeout, _label, _watch) = launch.calls[0]
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
    (_binary, args, _cwd, _timeout, _label, _watch) = launch.calls[0]
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


# --- #655: the two envelopes for a run GDA ENDED, and the watch rule behind the abort.
#
# The launch seam is fed a hand-built RunResult in the shape the streaming capture
# really produces (partial output preserved, launch_failure set, elapsed measured),
# so the CLASSIFICATION is asserted here while the capture MECHANISM that produces
# that shape is asserted against real pipes in ``tests/test_launch.py``.

# The verbatim stderr of a run whose entry script died before its own quit() —
# captured from Godot 4.6.3 during this issue. The engine stays alive afterwards,
# which is the whole defect (GDA-DF-012).
ABORTED_STDERR = (
    "SCRIPT ERROR: Invalid call. Nonexistent function 'missing_method' in base 'Nil'.\n"
    "          at: _initialize (res://tests/logic.gd:6)\n"
    "          GDScript backtrace (most recent call first):\n"
    "              [0] _initialize (res://tests/logic.gd:6)\n"
)


def _timed_out(stdout: str = "", stderr: str = "", elapsed: float = 120.4) -> RunResult:
    """The RunResult shape the STREAMING capture returns for a timed-out run."""
    return RunResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=EXIT_TIMEOUT,
        launch_failure=LaunchFailure.TIMEOUT,
        elapsed_seconds=elapsed,
    )


def test_the_caller_timeout_is_what_reaches_the_launch():
    # AC: --timeout is HONORED. The value the caller chose is the one the shared
    # primitive is given, not the default the module happens to define.
    _outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0), timeout=7.5)

    (_binary, _args, _cwd, timeout, _label, _watch) = launch.calls[0]
    assert timeout == 7.5


def test_the_default_timeout_is_still_the_documented_ceiling():
    # The knob is a DEFAULT now, not a replacement: an invocation that states nothing
    # keeps the ceiling that bounds a hung engine (ADR-0031).
    _outcome, launch = _run(RunResult(stdout="", stderr="", exit_code=0))

    (_binary, _args, _cwd, timeout, _label, _watch) = launch.calls[0]
    assert timeout == DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS == 120.0


def test_a_timeout_reflects_the_timeout_elapsed_and_phase_in_the_message():
    # AC: a run exceeding --timeout reports the ceiling it reached, the elapsed wall
    # clock, and ONE enumerated termination phase. All prose — promoting them to
    # envelope fields would change ADR-0004's failure ABI, which #687 owns.
    outcome, _ = _run(
        _timed_out(stdout="Godot Engine v4.6.3\nSUITE START\n", elapsed=30.25),
        timeout=30.0,
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "launch_timeout"
    assert outcome.exit_code == EXIT_TIMEOUT
    assert "--timeout of 30.0s" in outcome.error.message
    assert "elapsed 30.25s" in outcome.error.message
    assert TerminationPhase.OUTPUT_SEEN.value in outcome.error.message
    # The cap is STATED, so a reader knows the output was truncated and by how much.
    assert str(SCRIPT_OUTPUT_TAIL_CAP_BYTES) in outcome.error.message


def test_a_timeout_carries_the_captured_partial_output_as_diagnostics():
    # THE #655 DEFECT (GDA-DF-012): the timeout envelope used to hold only the timeout
    # message, discarding the output the engine had already written. Both streams now
    # come back under the SAME fixed labels --strict uses, so one consumer split reads
    # every script run failure.
    outcome, _ = _run(
        _timed_out(stdout="SUITE START\n7 of 40 tests\n", stderr=ABORTED_STDERR),
        timeout=30.0,
    )

    assert isinstance(outcome, Failure)
    diagnostics = outcome.error.diagnostics
    assert SCRIPT_OUTPUT_STDOUT_HEADER in diagnostics
    assert SCRIPT_OUTPUT_STDERR_HEADER in diagnostics
    assert "7 of 40 tests" in diagnostics
    # And the script error the engine had ALREADY printed is surfaced as a classified
    # line, read by the SAME parser stack a completed run's diagnostics use (#651).
    assert "runtime_error: res://tests/logic.gd:6" in diagnostics
    assert "Nonexistent function 'missing_method'" in diagnostics


def test_a_timeout_with_no_output_reports_the_narrower_phase():
    # The distinction the phase exists for: an engine that never wrote a byte did not
    # even reach its own startup banner, which is a different problem from a run that
    # was alive and did not finish.
    outcome, _ = _run(_timed_out(), timeout=30.0)

    assert isinstance(outcome, Failure)
    assert TerminationPhase.LAUNCHED.value in outcome.error.message
    # A clean error stream is itself the diagnosis — an unfinished run, not a broken
    # script — so the absence is stated rather than left as an empty section.
    assert "no recognized script errors" in outcome.error.diagnostics


def test_a_timeout_truncates_each_stream_to_the_stated_tail():
    # The cap is fixed and bounds what a two-minute run can put into an inline JSON
    # result. The TAIL is kept, not the head: where a run that did not finish got to
    # is the interesting part.
    outcome, _ = _run(
        _timed_out(stdout="x" * 50_000 + "LAST LINE\n", stderr="y" * 50_000),
        timeout=30.0,
    )

    assert isinstance(outcome, Failure)
    diagnostics = outcome.error.diagnostics
    assert "LAST LINE" in diagnostics
    assert diagnostics.count("x") == SCRIPT_OUTPUT_TAIL_CAP_BYTES - len("LAST LINE\n")
    assert diagnostics.count("y") == SCRIPT_OUTPUT_TAIL_CAP_BYTES


def test_an_aborted_run_is_the_registered_early_termination_verdict():
    # AC: a script whose runtime error prevents quit() returns the captured error
    # within a STATED bound in seconds, not the full timeout, when a marker is
    # declared. It is its own registered code: gda did not wait out the timeout, it
    # decided not to — reporting launch_timeout would be untrue.
    outcome, _ = _run(
        RunResult(
            stdout="SUITE START\n",
            stderr=ABORTED_STDERR,
            exit_code=EXIT_OPERATION,
            launch_failure=LaunchFailure.ABORTED,
            elapsed_seconds=3.4,
        ),
        timeout=120.0,
        completion_marker="SUITE DONE",
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "script_aborted"
    assert outcome.exit_code == EXIT_OPERATION
    # The message names WHY gda stopped: the declared marker, the silence window, and
    # the ceiling that was NOT reached — so the bound reads as a bound.
    assert "'SUITE DONE'" in outcome.error.message
    assert f"{SCRIPT_RUN_ABORT_SILENCE_SECONDS}s" in outcome.error.message
    assert "3.40s" in outcome.error.message
    assert "120.0s was not reached" in outcome.error.message
    assert TerminationPhase.ABORTED_ON_ERROR.value in outcome.error.message
    # And it carries the same evidence a timeout does.
    assert "runtime_error: res://tests/logic.gd:6" in outcome.error.diagnostics
    assert "SUITE START" in outcome.error.diagnostics


def _drive(watch, steps):
    """Feed ``(stdout, stderr, elapsed)`` steps to a watch; return each verdict.

    The watch is a pure function of the observed text and the clock — deliberately
    its ONLY inputs. An earlier version also read the child's CPU time as idleness
    evidence, and review falsified it in both directions (a run blocked in a wait
    consumes no CPU while alive; a host that cannot read CPU time lost the abort
    entirely), so these tests need no process, no probe, and no platform.
    """
    return [watch.observe(stdout=out, stderr=err, elapsed=at) for out, err, at in steps]


def test_the_declared_marker_reaches_the_watch_and_absence_leaves_it_inert():
    # The marker is CALLER-DECLARED (ADR-0031 rejected imposing a gda-owned sentinel
    # on a user script), so with none declared the watch must never abort — the launch
    # gains its captured output and nothing else.
    inert = _CompletionMarkerWatch(None, entry=ENTRY)
    verdicts = _drive(
        inert,
        [("", ABORTED_STDERR, 0.5), ("", "", 600.0), ("", "", 900.0)],
    )
    assert verdicts == [False, False, False]


def test_a_blank_marker_is_treated_as_undeclared():
    # Whole-line equality means a whitespace-only marker would equal every blank line
    # the run prints and arm the abort on nothing. The params model and the argv guard
    # both refuse one; the watch refuses it too so no third call site can reintroduce
    # the hazard.
    watch = _CompletionMarkerWatch("   ", entry=ENTRY, silence=3.0)
    verdicts = _drive(
        watch,
        [("\n", ABORTED_STDERR, 0.5), ("", "", 3.6), ("", "", 7.0)],
    )
    assert verdicts == [False, False, False]


def test_the_watch_aborts_only_after_the_error_and_a_full_silence_window():
    # The three-part rule. Each step below is a part that must NOT be enough alone.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    # (1) an entry error, but output is still arriving: the run is talking.
    assert not watch.observe(stdout="SUITE START\n", stderr=ABORTED_STDERR, elapsed=0.5)
    # (3) a short silence is not the window (2.4s since the last output).
    assert not watch.observe(stdout="", stderr="", elapsed=2.9)
    # The full window since the last output is the contract's bound: the caller
    # declared the script keeps printing until the marker, so this silence IS the
    # run being dead — by declaration, on every platform alike.
    assert watch.observe(stdout="", stderr="", elapsed=3.6)


def test_a_silent_survivor_is_ended_by_the_declared_contract():
    # THE CONTRACT'S PRICE, stated rather than hidden: a script that survives an
    # entry-attributable error and then works past the bound in TOTAL silence is
    # ended even though it would have finished. Review proved every observational
    # rescue of such a run wrong in both directions — a CPU probe cannot tell a
    # blocked-but-alive wait (no CPU while alive) from a corpse, and a host that
    # cannot read CPU time lost the abort entirely. Declaring the marker is what
    # asserts the script does not do this; the compliant alternatives are pinned by
    # the test below and the e2e pair.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [("SUITE START\n", ABORTED_STDERR, 0.5), ("", "", 2.9), ("", "", 3.6)],
    )

    assert verdicts == [False, False, True]


def test_a_survivor_that_prints_progress_is_never_aborted():
    # The compliant escape hatch the contract names: ANY output line resets the
    # window, so a script that survives a recoverable entry error and keeps saying
    # so — however slowly it works — is never ended, and its marker finally
    # disarms the watch for good.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [
            ("SUITE START\n", ABORTED_STDERR, 0.5),
            ("still checking...\n", "", 2.8),
            ("", "", 5.0),
            ("still checking...\n", "", 5.5),
            ("", "", 8.0),
            ("SUITE DONE\n", "", 8.2),
            ("", "", 60.0),
        ],
    )

    assert verdicts == [False] * 7


def test_an_error_about_another_resource_never_arms_the_abort():
    # Attribution (1): a RUNNING script that merely load()s a missing .tres — or whose
    # helper script fails — produces the same engine sentences for a DIFFERENT path.
    # The e2e suite pins such runs as SUCCESSES, so they must not arm the abort even
    # when the run then goes idle and quiet.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)
    other = (
        "ERROR: Cannot open file 'res://missing.tres'.\n"
        "   at: _load (core/io/resource_loader.cpp:343)\n"
        "ERROR: Failed loading resource: res://missing.tres.\n"
        "   at: _load (core/io/resource_loader.cpp:343)\n"
    )

    verdicts = _drive(
        watch,
        [("", other, 0.5), ("", "", 3.6), ("", "", 6.7), ("", "", 60.0)],
    )

    assert verdicts == [False] * 4


def test_a_runtime_error_in_a_helper_script_never_arms_the_abort():
    # The same attribution rule for the runtime kind: an error raised inside a helper
    # the entry called is reported against the HELPER's res:// path, and says nothing
    # about whether the entry can finish.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)
    helper = (
        "SCRIPT ERROR: Invalid call. Nonexistent function 'x' in base 'Nil'.\n"
        "          at: run (res://tests/helper.gd:12)\n"
    )

    verdicts = _drive(
        watch,
        [("", helper, 0.5), ("", "", 3.6), ("", "", 6.7), ("", "", 60.0)],
    )

    assert verdicts == [False] * 4


def test_an_entry_load_failure_arms_the_abort_too():
    # Attribution reuses the EXISTING classification, so every kind that proves the
    # entry never ran arms the abort as well — not just the runtime kind. This is the
    # shape ADR-0031 records as otherwise reaching a failure only "by another route"
    # (the engine idles instead of exiting), and the marker now cuts that short.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)
    not_a_main_loop = (
        "ERROR: Can't load the script \"res://tests/logic.gd\" as it doesn't "
        "inherit from SceneTree or MainLoop.\n"
        "   at: start (main/main.cpp:4286)\n"
    )

    verdicts = _drive(
        watch,
        [("", not_a_main_loop, 0.5), ("", "", 2.9), ("", "", 3.6)],
    )

    assert verdicts == [False, False, True]


def test_output_after_the_error_resets_the_silence_window():
    # A run that keeps working keeps printing, and any output must restart the wait
    # from scratch: under the declared contract, output is itself the liveness the
    # caller promised, so the window measures from the LAST line, not the error.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    assert not watch.observe(stdout="", stderr=ABORTED_STDERR, elapsed=0.5)
    # A hair under the window since the error: nothing fires...
    assert not watch.observe(stdout="test 8 ok\n", stderr="", elapsed=3.4)
    # ...and that line restarted the wait: 4.5s after the error is only 1.1s after
    # the output, so nothing may fire yet.
    assert not watch.observe(stdout="", stderr="", elapsed=4.5)
    assert not watch.observe(stdout="", stderr="", elapsed=6.3)
    # The full window since the LAST output is what fires.
    assert watch.observe(stdout="", stderr="", elapsed=6.5)


def test_the_marker_appearing_disarms_the_abort_for_good():
    # Once the caller's own definition of "finished" has been printed, the run is not
    # an aborted one, whatever else its stderr says — so gda waits out --timeout
    # rather than reporting a failure the caller did not ask for.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [("SUITE DONE\n", ABORTED_STDERR, 0.5), ("", "", 60.0), ("", "", 120.0)],
    )

    assert verdicts == [False, False, False]


def test_a_line_merely_containing_the_marker_does_not_disarm_the_abort():
    # THE REVIEWED DEFECT: substring matching made "NOT DONE YET" count as the marker
    # "DONE", silently disarming the abort for a run that had in fact died. The marker
    # is defined as a LINE the script prints, so the comparison is whole-line equality
    # and this run is still correctly ended.
    watch = _CompletionMarkerWatch("DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [("NOT DONE YET\n", ABORTED_STDERR, 0.5), ("", "", 2.9), ("", "", 3.6)],
    )

    assert verdicts == [False, False, True]


def test_the_marker_matches_its_line_ignoring_surrounding_whitespace():
    # print() output can carry indentation; the marker names the line's CONTENT, so
    # both sides are stripped before comparison.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [("  SUITE DONE  \n", ABORTED_STDERR, 0.5), ("", "", 3.6), ("", "", 6.7)],
    )

    assert verdicts == [False, False, False]


def test_the_marker_is_matched_across_a_chunk_boundary():
    # The capture hands over whatever a read syscall returned, so a marker can arrive
    # split. Buffering to complete lines is what makes the match whole while still
    # seeing every byte exactly once.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [("SUITE ", ABORTED_STDERR, 0.1), ("DONE\n", "", 0.2), ("", "", 6.7)],
    )

    assert verdicts == [False, False, False]


def test_an_error_record_split_across_reads_is_still_attributed():
    # The mirror case for stderr, and why the watch re-parses a bounded WINDOW of
    # trailing lines rather than each batch alone: Godot writes an error as a header
    # then an `at:` frame, and only the frame carries the res:// path the attribution
    # needs. Parsing the batches independently dropped it, so a genuinely dead run
    # would never arm.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [
            ("", "SCRIPT ERROR: Invalid call. Nonexistent function 'q'.\n", 0.1),
            ("", "          at: _initialize (res://tests/logic.gd:6)\n", 0.2),
            ("", "", 2.9),
            ("", "", 3.6),
        ],
    )

    assert verdicts == [False, False, False, True]


def test_a_warning_is_not_a_script_error_for_the_abort():
    # Recognition is the shared parser's, which skips warnings — so a chatty run that
    # only warns is never ended early, however long it then goes quiet.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [
            ("", "WARNING: odd\n   at: f (res://tests/logic.gd:2)\n", 0.1),
            ("", "", 3.6),
            ("", "", 6.7),
        ],
    )

    assert verdicts == [False, False, False]


def test_an_error_on_stdout_alone_does_not_arm_the_abort():
    # Godot reports errors on stderr; a script that PRINTS the words "SCRIPT ERROR"
    # to stdout (a test runner echoing a failure) has not failed the run.
    watch = _CompletionMarkerWatch("SUITE DONE", entry=ENTRY, silence=3.0)

    verdicts = _drive(
        watch,
        [(ABORTED_STDERR, "", 0.1), ("", "", 3.6), ("", "", 6.7)],
    )

    assert verdicts == [False, False, False]


def test_a_completed_run_is_unaffected_by_a_declared_marker():
    # The marker changes nothing about a run that finished: gda still passes the
    # script's own status through (the ADR-0031 crux), marker or no marker.
    outcome, _ = _run(
        RunResult(stdout="SUITE DONE\n", stderr="", exit_code=1, elapsed_seconds=0.4),
        completion_marker="SUITE DONE",
    )

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.exit_status == 1


def test_a_timeout_does_not_shadow_the_shared_env_and_crash_classifier():
    # The channel classifies only the runs GDA ended; everything else still goes
    # through the SAME shared prefix the export channel uses, so the two stay
    # identical on a missing binary, an unusable placement and a signal death.
    for failure, code in (
        (LaunchFailure.NOT_FOUND, "binary_not_found"),
        (LaunchFailure.USER_DATA_UNWRITABLE, "user_data_unwritable"),
    ):
        outcome, _ = _run(
            RunResult(stdout="", stderr="why\n", exit_code=127, launch_failure=failure),
            completion_marker="SUITE DONE",
        )
        assert isinstance(outcome, Failure)
        assert outcome.error.code == code


def test_an_unmeasured_run_falls_back_to_its_rule_s_lower_bound():
    # The streaming capture always measures the clock, so `elapsed_seconds` is None
    # only for a hand-built RunResult (this suite's injected seam). Reporting 0.00s
    # there would read as "ended instantly" — a claim about the run — so each envelope
    # falls back to the truthful LOWER BOUND its own rule guarantees: a timeout ran at
    # least as long as the ceiling it reached, and an abort waited out at least the
    # silence window that triggered it.
    timed_out, _ = _run(
        RunResult(
            stdout="",
            stderr="",
            exit_code=EXIT_TIMEOUT,
            launch_failure=LaunchFailure.TIMEOUT,
        ),
        timeout=45.0,
    )
    assert isinstance(timed_out, Failure)
    assert "elapsed 45.00s" in timed_out.error.message

    aborted, _ = _run(
        RunResult(
            stdout="",
            stderr=ABORTED_STDERR,
            exit_code=0,
            launch_failure=LaunchFailure.ABORTED,
        ),
        timeout=120.0,
        completion_marker="SUITE DONE",
    )
    assert isinstance(aborted, Failure)
    # The abort's guaranteed lower bound is one full silence window: it cannot have
    # fired sooner than the contract's own bound.
    assert (
        f"ended after {SCRIPT_RUN_ABORT_SILENCE_SECONDS:.2f}s" in aborted.error.message
    )


def test_the_abort_envelope_names_the_condition_without_a_marker_string():
    # The abort is unreachable without a declared marker, so this state cannot occur —
    # which is exactly why it must not be an `assert`: that would crash the command on
    # a boundary value, and vanish under `-O`. The builder degrades to naming the
    # condition instead, so an impossible input yields a vaguer report, not a traceback.
    from gda.errors import script_run_aborted_failure

    failure = script_run_aborted_failure(
        "res://tests/logic.gd",
        marker=None,
        timeout=120.0,
        elapsed=3.4,
        silence=SCRIPT_RUN_ABORT_SILENCE_SECONDS,
        phase=TerminationPhase.ABORTED_ON_ERROR.value,
        script_errors="",
        stdout="",
        stderr="",
    )

    assert failure.error.code == "script_aborted"
    assert "the declared completion marker did not" in failure.error.message
    assert "None" not in failure.error.message


def test_the_output_cap_bounds_utf8_BYTES_not_characters():
    # The cap exists to keep an inline JSON payload small, and a CHARACTER cap of the
    # same number did not: non-ASCII output encodes to up to 3-4 bytes each, so 16Ki
    # characters of CJK text was ~48KiB — three times the intended bound. Counting
    # bytes makes the stated figure mean one thing to a reader measuring the result.
    wide = "界" * 20_000  # 3 bytes each => 60 KiB, well past the cap

    outcome, _ = _run(_timed_out(stdout=wide, stderr=wide), timeout=30.0)

    assert isinstance(outcome, Failure)
    diagnostics = outcome.error.diagnostics
    # 16384 bytes / 3 bytes per character = 5461 whole characters, and the byte slice
    # lands mid-character: the leading partial byte is DROPPED rather than becoming a
    # replacement character, since the truncation is gda's own and inventing a U+FFFD
    # would misreport the engine's output as malformed.
    per_stream = SCRIPT_OUTPUT_TAIL_CAP_BYTES // len("界".encode())
    assert diagnostics.count("界") == per_stream * 2
    assert "�" not in diagnostics
    # And the payload really is bounded in the unit the message names.
    assert len(diagnostics.encode("utf-8")) <= 2 * SCRIPT_OUTPUT_TAIL_CAP_BYTES + 512
    assert "UTF-8 bytes (16 KiB)" in outcome.error.message


def test_output_within_the_cap_is_never_re_encoded():
    # The common case must pass through untouched: a stream under the cap is returned
    # as-is, so nothing can be lost to a boundary trim that was not needed.
    outcome, _ = _run(_timed_out(stdout="界 ok\n", stderr="Ω done\n"), timeout=30.0)

    assert isinstance(outcome, Failure)
    assert "界 ok" in outcome.error.diagnostics
    assert "Ω done" in outcome.error.diagnostics


# --- the bounded stdout (#665, GDA-DF-036) -------------------------------------
# The one qualification of the verbatim passthrough: a SUCCESS result's stdout
# above SCRIPT_STDOUT_CAP returns as the stream's leading cap bytes while the
# COMPLETE stream spills to a named file; the full byte count is always present.


def test_stdout_at_the_cap_returns_verbatim():
    exactly_cap = "x" * SCRIPT_STDOUT_CAP
    outcome, _ = _run(RunResult(stdout=exactly_cap, stderr="", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.stdout == exactly_cap
    assert outcome.stdout_bytes == SCRIPT_STDOUT_CAP
    assert outcome.stdout_truncated is False
    assert outcome.stdout_file is None


def test_stdout_above_the_cap_is_truncated_and_spilled():
    head = "h" * SCRIPT_STDOUT_CAP
    tail = "TAIL-MARKER-" + "t" * 100
    outcome, _ = _run(RunResult(stdout=head + tail, stderr="", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    # The returned stdout is the stream's leading cap bytes; the tail is not in it.
    assert outcome.stdout == head
    assert "TAIL-MARKER" not in outcome.stdout
    assert outcome.stdout_truncated is True
    assert outcome.stdout_bytes == len((head + tail).encode("utf-8"))
    # The COMPLETE stream — head and tail — is in the named spill file.
    assert outcome.stdout_file is not None
    spilled = Path(outcome.stdout_file)
    try:
        assert spilled.read_text(encoding="utf-8") == head + tail
    finally:
        spilled.unlink()


def test_cap_cut_lands_on_a_utf8_boundary():
    # A multi-byte character straddling the cap is dropped, never mangled: the
    # returned head decodes cleanly and stays within the cap.
    stream = "汉" * (SCRIPT_STDOUT_CAP // 3 + 100)  # 3 UTF-8 bytes each
    outcome, _ = _run(RunResult(stdout=stream, stderr="", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.stdout_truncated is True
    assert "�" not in outcome.stdout
    assert set(outcome.stdout) == {"汉"}
    assert len(outcome.stdout.encode("utf-8")) <= SCRIPT_STDOUT_CAP
    assert outcome.stdout_file is not None
    Path(outcome.stdout_file).unlink()


def test_spill_failure_returns_the_full_stream_untruncated(monkeypatch):
    # The cap is a bounding convenience and must never cost data: when the spill
    # file cannot be written, the FULL stream returns untruncated.
    import tempfile

    def _refuse(*args, **kwargs):
        raise OSError("no temp space")

    monkeypatch.setattr(tempfile, "mkstemp", _refuse)
    big = "y" * (SCRIPT_STDOUT_CAP + 5)
    outcome, _ = _run(RunResult(stdout=big, stderr="", exit_code=0))

    assert isinstance(outcome, ScriptRunResult)
    assert outcome.stdout == big
    assert outcome.stdout_truncated is False
    assert outcome.stdout_file is None
    assert outcome.stdout_bytes == len(big)
