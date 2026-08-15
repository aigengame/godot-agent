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

from gda.script_errors import (
    ScriptErrorKind,
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
    # The definitive File-not-found sentence and main.cpp's give-up line are both
    # recognized; the generic "Failed loading resource" line is not one of the
    # closed set and is deliberately skipped rather than guessed at.
    assert kinds == [
        (ScriptErrorKind.SCRIPT_MISSING, "res://nope.gd"),
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


def test_not_a_main_loop_is_recognized_but_is_not_a_load_verdict():
    # The script compiles and exists; it just cannot BE the entry point. It is
    # surfaced as a diagnostic, and mapping it to a verdict is left to a decision
    # of its own rather than folded into the #651 load-failure codes.
    errors = parse_script_errors(NOT_A_MAIN_LOOP_STDERR)

    assert [e.kind for e in errors] == [ScriptErrorKind.NOT_A_MAIN_LOOP]
    assert errors[0].path == "res://plain.gd"
    assert entry_load_failure(errors, "res://plain.gd") is None


def test_a_failure_naming_another_script_is_not_the_entry_verdict():
    # THE false-positive guard: a script that RAN and itself load()ed a missing
    # resource produces the identical engine sentence for a DIFFERENT path. Keying
    # the verdict on the entry path is what keeps that a success.
    errors = parse_script_errors(MISSING_STDERR)

    assert entry_load_failure(errors, "res://entry.gd") is None


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
