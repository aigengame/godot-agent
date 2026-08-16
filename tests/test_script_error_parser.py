"""The engine-stderr script-error classifier (#651).

:mod:`gda.script_errors` is a pure function of an engine stderr capture, so these
tests drive it with stderr recorded VERBATIM from a real ``godot --headless
--script`` run (Godot 4.6.3, macOS) rather than with invented lines — the parser's
whole value is that it recognizes what the engine actually prints, and an invented
fixture would only pin what we imagined it prints.

Each capture below is a failure mode from the #651 dogfooding reports: a missing
entry script (GDA-DF-032), an entry parse error and a dependency parse error
(GDA-DF-007), and a runtime GDScript error the script survived (GDA-DF-007). Note
the exit status recorded in each docstring: the engine exits **0** for every one of
them, which is exactly why the verdict has to come from here.
"""

import pytest

from gda.script_errors import (
    ScriptErrorKind,
    canonical_res_path,
    entry_load_failure,
    parse_script_errors,
)

# `godot --headless --path <proj> --script res://nope.gd`, exit status 0.
MISSING_STDERR = """\
ERROR: Attempt to open script 'res://nope.gd' resulted in error 'File not found'.
   at: load_source_code (modules/gdscript/gdscript.cpp:1127)
ERROR: Failed loading resource: res://nope.gd.
   at: _load (core/io/resource_loader.cpp:343)
ERROR: Can't load script: res://nope.gd
   at: start (main/main.cpp:4271)
"""

# `--script res://parse_error.gd`, whose line 4 is not valid GDScript. Exit status 0.
PARSE_ERROR_STDERR = """\
SCRIPT ERROR: Parse Error: Expected end of statement after expression, found "Identifier" instead.
          at: GDScript::reload (res://parse_error.gd:4)
ERROR: Failed to load script "res://parse_error.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2907)
"""

# `--script res://bad_dep.gd`, which preloads a non-compiling res://broken_dep.gd.
# Exit status 0. The engine names the ENTRY script in the load failure, and the
# entry's own preload line in the reload frames — the dependency appears only
# inside the message text.
BAD_DEPENDENCY_STDERR = """\
SCRIPT ERROR: Parse Error: Could not preload resource script "res://broken_dep.gd".
          at: GDScript::reload (res://bad_dep.gd:3)
SCRIPT ERROR: Parse Error: Could not resolve script "res://broken_dep.gd".
          at: GDScript::reload (res://bad_dep.gd:3)
SCRIPT ERROR: Parse Error: Cannot infer the type of "Broken" constant because the value doesn't have a set type.
          at: GDScript::reload (res://bad_dep.gd:3)
ERROR: Failed to load script "res://bad_dep.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2907)
"""

# `--script res://runtime_error.gd`, which calls a method on null then keeps going
# and quit(0)s. Exit status 0 — the script RAN; only the diagnostics reveal the bug.
RUNTIME_ERROR_STDERR = """\
SCRIPT ERROR: Invalid call. Nonexistent function 'missing_method' in base 'Nil'.
          at: _boom (res://runtime_error.gd:10)
          GDScript backtrace (most recent call first):
              [0] _boom (res://runtime_error.gd:10)
              [1] _initialize (res://runtime_error.gd:4)
"""

# `--script res://plain.gd`, a valid script that extends RefCounted. Exit status 0.
NOT_A_MAIN_LOOP_STDERR = """\
ERROR: Can't load the script "res://plain.gd" as it doesn't inherit from SceneTree or MainLoop.
   at: start (main/main.cpp:4286)
"""


def test_missing_script_is_classified_and_located():
    errors = parse_script_errors(MISSING_STDERR)

    kinds = [(e.kind, e.path) for e in errors]
    # All three sentences the engine emits for one missing entry, in emission
    # order: the definitive File-not-found one, the resource layer's generic
    # report, and main.cpp's give-up line. The trailing period of "Failed loading
    # resource: <path>." is sentence punctuation and is not part of the address.
    assert kinds == [
        (ScriptErrorKind.SCRIPT_MISSING, "res://nope.gd"),
        (ScriptErrorKind.RESOURCE_LOAD_FAILED, "res://nope.gd"),
        (ScriptErrorKind.LOAD_FAILED, "res://nope.gd"),
    ]
    # An engine-side load error carries no script line (the at: frame names the
    # engine's own C++ source, which is meaningless to an agent).
    assert all(e.line is None for e in errors)


def test_missing_script_is_the_entry_verdict():
    errors = parse_script_errors(MISSING_STDERR)
    verdict = entry_load_failure(errors, "res://nope.gd")

    # SCRIPT_MISSING wins over the LOAD_FAILED emitted beside it: "the file does
    # not exist" is the better explanation than "the engine gave up".
    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.SCRIPT_MISSING


def test_entry_parse_error_carries_the_source_line():
    errors = parse_script_errors(PARSE_ERROR_STDERR)

    assert [e.kind for e in errors] == [
        ScriptErrorKind.PARSE_ERROR,
        ScriptErrorKind.COMPILE_FAILED,
    ]
    parse_error = errors[0]
    assert parse_error.path == "res://parse_error.gd"
    assert parse_error.line == 4
    assert "Expected end of statement" in parse_error.message
    assert entry_load_failure(errors, "res://parse_error.gd") is errors[1]


def test_dependency_parse_error_fails_the_entry_script():
    # The dependency is named only inside the message; the engine reports the
    # unresolvable preload as a load failure of the ENTRY script, which is what
    # makes the verdict work without walking the dependency graph.
    errors = parse_script_errors(BAD_DEPENDENCY_STDERR)
    verdict = entry_load_failure(errors, "res://bad_dep.gd")

    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.COMPILE_FAILED
    assert "broken_dep.gd" in errors[0].message
    assert errors[0].path == "res://bad_dep.gd"


def test_runtime_error_is_not_an_entry_failure():
    # The script RAN — a runtime error says nothing about whether it loaded, so it
    # must not flip the verdict (ADR-0031 still governs a completed run).
    errors = parse_script_errors(RUNTIME_ERROR_STDERR)

    assert [e.kind for e in errors] == [ScriptErrorKind.RUNTIME_ERROR]
    assert errors[0].path == "res://runtime_error.gd"
    assert errors[0].line == 10
    assert entry_load_failure(errors, "res://runtime_error.gd") is None


def test_not_a_main_loop_is_an_entry_failure():
    # The script exists and compiles; it just cannot BE the entry point — so it never
    # ran, which is the whole criterion. Exactly the GDA-DF-032 phantom-success shape
    # in a different disguise, so it fails like the others.
    errors = parse_script_errors(NOT_A_MAIN_LOOP_STDERR)

    assert [e.kind for e in errors] == [ScriptErrorKind.NOT_A_MAIN_LOOP]
    assert errors[0].path == "res://plain.gd"
    verdict = entry_load_failure(errors, "res://plain.gd")
    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.NOT_A_MAIN_LOOP


def test_a_parse_error_alone_still_fails_the_entry():
    # Robustness arm: on this engine a parse error always arrives WITH the "Failed to
    # load script" conclusion, and that conclusion is what normally decides the
    # verdict. Should a build ever emit the diagnostic without the conclusion, the
    # entry still did not compile, so it must still fail.
    only_the_diagnostic = PARSE_ERROR_STDERR.split("ERROR: Failed to load")[0]
    errors = parse_script_errors(only_the_diagnostic)

    assert [e.kind for e in errors] == [ScriptErrorKind.PARSE_ERROR]
    verdict = entry_load_failure(errors, "res://parse_error.gd")
    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.PARSE_ERROR


def test_every_never_ran_kind_is_an_entry_failure_candidate():
    # The enum's published description promises that five of the six kinds mean the
    # script never ran. `entry_load_failure` is what acts on that promise, so the two
    # must not drift: exactly `runtime_error` is excluded.
    from gda.script_errors import _ENTRY_FAILURE_PRECEDENCE

    assert set(ScriptErrorKind) - set(_ENTRY_FAILURE_PRECEDENCE) == {
        ScriptErrorKind.RUNTIME_ERROR
    }


def test_the_earliest_stage_cause_wins_when_several_are_reported():
    # The engine reports the whole cascade; only the first cause explains the rest.
    # A missing file outranks the generic "can't load" emitted beside it (asserted
    # above), and a compile failure outranks the parse diagnostic that caused it.
    errors = parse_script_errors(PARSE_ERROR_STDERR)
    verdict = entry_load_failure(errors, "res://parse_error.gd")

    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.COMPILE_FAILED


def test_a_failure_naming_another_script_is_not_the_entry_verdict():
    # THE false-positive guard: a script that RAN and itself load()ed a missing
    # resource produces the identical engine sentence for a DIFFERENT path. Keying
    # the verdict on the entry path is what keeps that a success.
    errors = parse_script_errors(MISSING_STDERR)

    assert entry_load_failure(errors, "res://entry.gd") is None


# --- Canonical resource identity (#651 review claim 1) ------------------------
#
# Godot canonicalizes a res:// address before naming it in an error, so the entry
# spelling the caller used and the spelling the engine reports back can differ.
# These captures are from real runs invoked with non-canonical spellings; note the
# engine reports `res://bad.gd` for a `res://sub/../bad.gd` invocation.

ALIASED_COMPILE_STDERR = """\
SCRIPT ERROR: Parse Error: Expected annotation identifier after "@".
          at: GDScript::reload (res://bad.gd:4)
ERROR: Failed to load script "res://bad.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2907)
"""

# The missing-entry case mixes the two spellings in ONE capture: the resource
# layer reports the canonical address, while main.cpp echoes the raw argv.
ALIASED_MISSING_STDERR = """\
ERROR: Attempt to open script 'res://gone.gd' resulted in error 'File not found'.
   at: load_source_code (modules/gdscript/gdscript.cpp:1127)
ERROR: Failed loading resource: res://gone.gd.
   at: _load (core/io/resource_loader.cpp:343)
ERROR: Can't load script: res://sub//..//gone.gd
   at: start (main/main.cpp:4271)
"""


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("res://bad.gd", "res://bad.gd"),
        ("res://sub/../bad.gd", "res://bad.gd"),
        ("res://./bad.gd", "res://bad.gd"),
        ("res://a//b.gd", "res://a/b.gd"),
        ("res://sub//..//bad.gd", "res://bad.gd"),
        ("res:///bad.gd", "res://bad.gd"),
        ("res://a/./b/../c.gd", "res://a/c.gd"),
        # Degenerate but well-defined: the bare scheme, and a path that cannot be
        # collapsed further without escaping the project root.
        ("res://", "res://"),
        ("res://../outside.gd", "res://../outside.gd"),
        # Not a res:// address: normalizing an address is not validating one.
        ("/abs/path.gd", "/abs/path.gd"),
        ("relative.gd", "relative.gd"),
    ],
)
def test_canonical_res_path_collapses_lexically(spelling, canonical):
    assert canonical_res_path(spelling) == canonical
    # Idempotent: canonicalizing a canonical address changes nothing, which is what
    # lets both the parser and entry_load_failure apply it without coordinating.
    assert canonical_res_path(canonical) == canonical


@pytest.mark.parametrize(
    "spelling",
    ["res://bad.gd", "res://sub/../bad.gd", "res://./bad.gd", "res://sub//..//bad.gd"],
)
def test_a_compile_failure_matches_every_spelling_of_the_entry(spelling):
    # THE claim-1 defect: the engine names `res://bad.gd` whatever spelling it was
    # invoked with, so a raw-string comparison missed the match and the failed run
    # reported success.
    errors = parse_script_errors(ALIASED_COMPILE_STDERR)
    verdict = entry_load_failure(errors, spelling)

    assert verdict is not None, f"{spelling} must resolve to the entry's failure"
    assert verdict.kind is ScriptErrorKind.COMPILE_FAILED


@pytest.mark.parametrize(
    "spelling",
    [
        "res://gone.gd",
        "res://sub/../gone.gd",
        "res://./gone.gd",
        "res://sub//..//gone.gd",
    ],
)
def test_a_missing_entry_matches_every_spelling_and_keeps_its_code(spelling):
    # The second half of claim 1: aliasing also MISROUTED the verdict. The raw
    # spelling matched only main.cpp's echoed "Can't load script:" line
    # (LOAD_FAILED -> script_compile_failed), never the File-not-found sentence.
    # Canonicalizing both sides restores the correct, more specific verdict.
    errors = parse_script_errors(ALIASED_MISSING_STDERR)
    verdict = entry_load_failure(errors, spelling)

    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.SCRIPT_MISSING


def test_published_paths_are_canonical():
    # The addresses gda hands an agent are canonical too, not just the ones it
    # compares internally — one resource identity everywhere.
    errors = parse_script_errors(ALIASED_MISSING_STDERR)

    assert {e.path for e in errors} == {"res://gone.gd"}


# --- Resource load failures (#651 review claim 4) -----------------------------

# A script that RAN and called load("res://missing.tres"). Exit status 0, and the
# script is fine — the resource is not. Two sentences from two engine layers.
RUNTIME_RESOURCE_LOAD_STDERR = """\
ERROR: Cannot open file 'res://missing.tres'.
   at: load (scene/resources/resource_format_text.cpp:1430)
   GDScript backtrace (most recent call first):
       [0] _initialize (res://runtime_load.gd:4)
ERROR: Failed loading resource: res://missing.tres.
   at: _load (core/io/resource_loader.cpp:343)
   GDScript backtrace (most recent call first):
       [0] _initialize (res://runtime_load.gd:4)
"""

# An entry script whose preload() names a missing .tres. The engine reports it as a
# PARSE error of the entry and a load failure of the entry — the resource itself is
# named only inside the message.
ENTRY_PRELOAD_MISSING_STDERR = """\
SCRIPT ERROR: Parse Error: Preload file "res://missing.tres" does not exist.
          at: GDScript::reload (res://preload_missing.gd:3)
SCRIPT ERROR: Parse Error: Cannot infer the type of "R" constant because the value doesn't have a set type.
          at: GDScript::reload (res://preload_missing.gd:3)
ERROR: Failed to load script "res://preload_missing.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2907)
"""


def test_runtime_resource_load_failure_is_a_diagnostic_not_a_verdict():
    # Issue #651 names resource load failures among the lines to surface. The script
    # ran, so this must NOT flip the verdict — it names a resource, not the entry.
    errors = parse_script_errors(RUNTIME_RESOURCE_LOAD_STDERR)

    assert [(e.kind, e.path) for e in errors] == [
        (ScriptErrorKind.RESOURCE_LOAD_FAILED, "res://missing.tres"),
        (ScriptErrorKind.RESOURCE_LOAD_FAILED, "res://missing.tres"),
    ]
    assert entry_load_failure(errors, "res://runtime_load.gd") is None


def test_a_resource_load_failure_naming_the_entry_is_a_verdict():
    # The same sentence DOES end the run when the address it names is the entry —
    # the identity match is the whole discriminator.
    errors = parse_script_errors(
        "ERROR: Failed loading resource: res://entry.gd.\n"
        "   at: _load (core/io/resource_loader.cpp:343)\n"
    )
    verdict = entry_load_failure(errors, "res://entry.gd")

    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.RESOURCE_LOAD_FAILED


def test_entry_preload_of_a_missing_resource_fails_the_entry():
    # The entry-preload case: the engine blames the ENTRY (a parse error plus its
    # load failure) and names the missing resource only in the message text, so the
    # verdict is the entry's compile failure — no dependency walk needed.
    errors = parse_script_errors(ENTRY_PRELOAD_MISSING_STDERR)
    verdict = entry_load_failure(errors, "res://preload_missing.gd")

    assert verdict is not None
    assert verdict.kind is ScriptErrorKind.COMPILE_FAILED
    assert "res://missing.tres" in errors[0].message
    assert errors[0].path == "res://preload_missing.gd"


def test_clean_and_unrecognized_stderr_yield_no_diagnostics():
    assert parse_script_errors("") == []
    assert parse_script_errors("just some printed output\n") == []
    # A warning says nothing about a script's fate, and an ERROR the closed set
    # does not recognize is skipped rather than guessed at.
    assert (
        parse_script_errors(
            "WARNING: something advisory.\n"
            "   at: whatever (core/x.cpp:1)\n"
            "ERROR: An engine error with no known script sentence.\n"
            "   at: whatever (core/x.cpp:2)\n"
        )
        == []
    )
