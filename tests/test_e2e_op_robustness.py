"""S1 (e2e): the headless op dispatcher always exits, structured (issue #31).

These drive operations.gd below the CLI/pydantic layer (which would reject the
inputs first), proving the GDScript dispatch itself never hangs and reports a
stable code: a malformed param that once crashed a typed assignment and left
the main loop spinning is now a prompt operation failure, and dispatcher-level
errors (unknown operation, non-JSON params) carry their own stable codes rather
than the generic operation_failed.
"""

import subprocess
import time

import pytest

from gda.binary import resolve_godot_binary
from gda.errors import Failure, classify_run
from gda.models import EngineVersion
from gda.parser import parse_result
from gda.runner import OPERATIONS_GD, RunResult, SubprocessGodotRunner

GODOT = resolve_godot_binary()


@pytest.mark.e2e
def test_malformed_param_fails_promptly_not_as_timeout():
    # A non-string path is the input that previously crashed the GDScript's
    # typed assignment and hung the process until the 60s runner timeout, then
    # was misclassified as environment/launch_timeout (exit 124). It must now
    # be a prompt, structured operation failure.
    runner = SubprocessGodotRunner(GODOT)
    start = time.monotonic()
    result = runner.run("scene-get", {"path": 123})
    elapsed = time.monotonic() - start

    assert elapsed < 30, "the op hung instead of exiting promptly"
    outcome = classify_run(result, GODOT, EngineVersion)
    assert isinstance(outcome, Failure)
    assert outcome.error.category.value == "operation"
    assert outcome.exit_code != 124  # never the launch_timeout misclassification


@pytest.mark.e2e
def test_unknown_operation_yields_stable_code():
    runner = SubprocessGodotRunner(GODOT)
    result = runner.run("bogus-op", {})

    outcome = classify_run(result, GODOT, EngineVersion)
    assert isinstance(outcome, Failure)
    assert outcome.error.category.value == "operation"
    assert outcome.error.code == "unknown_operation"


@pytest.mark.e2e
def test_non_json_params_yield_stable_code():
    # Bypass the runner (which json.dumps its params) to hand the op a
    # syntactically invalid params payload directly.
    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--script",
            str(OPERATIONS_GD),
            "--",
            "info",
            "{not json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = RunResult(
        stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode
    )

    outcome = classify_run(result, GODOT, EngineVersion)
    assert isinstance(outcome, Failure)
    assert outcome.error.category.value == "operation"
    assert outcome.error.code == "invalid_params"


@pytest.mark.e2e
def test_script_set_dispatches_on_the_explicit_mode_not_param_presence(tmp_path):
    # script-set is decided once at the CLI and the op dispatches on the explicit
    # `mode` discriminator, NOT by re-inferring from which params are present
    # (issue #133). Hand the op a params dict the CLI's mutual exclusion would
    # never produce: mode=full but with start_line ALSO set. Honoring `mode`
    # overwrites the whole file with `content`; the obsolete presence-inference
    # (search → line-range → full) would instead apply a line-range edit. The two
    # produce observably different files, so this pins the dispatch on `mode`.
    script = tmp_path / "hero.gd"
    script.write_text("extends Node\nvar a := 1\nvar b := 2\n", encoding="utf-8")

    runner = SubprocessGodotRunner(GODOT)
    result = runner.run(
        "script-set",
        {
            "path": str(script),
            "mode": "full",
            "search": None,
            "replace": None,
            "start_line": 1,  # presence-inference would mis-select line_range
            "end_line": None,
            "content": "class_name Hero\nextends Node2D\n",
        },
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = parse_result(result.stdout)
    assert payload["class_name"] == "Hero"
    assert payload["extends"] == "Node2D"
    # The file was fully overwritten (full mode honored), not line-range edited.
    assert script.read_text(encoding="utf-8") == "class_name Hero\nextends Node2D\n"


# --- script-validate's selector contract, below the CLI (#663) ---
#
# gda's own CLI refuses these selections before the engine is reached (the params
# model owns the rule, ADR-0015), so these arms drive `operations.gd` directly —
# which is what this module is for. The op is a contract in its own right
# (ADR-0002): another caller of the payload must get the same refusal gda's CLI
# gives, and with the same code, or the two sides of the wire disagree about what
# a selection means.


def _validate_failure(params: dict) -> Failure:
    from gda.commands.script import ScriptValidateResult

    result = SubprocessGodotRunner(GODOT).run("script-validate", params)
    outcome = classify_run(result, GODOT, ScriptValidateResult)
    assert isinstance(outcome, Failure), outcome
    assert outcome.error.category.value == "operation"
    return outcome


@pytest.mark.e2e
def test_script_validate_refuses_both_selectors_at_the_op():
    # "Both" is a contradiction, not a precedence question: all_scripts already
    # covers every script, so silently letting it win would report a verdict for a
    # set the caller did not ask for while discarding the one they named.
    outcome = _validate_failure({"paths": ["res://a.gd"], "all_scripts": True})

    assert outcome.error.code == "invalid_params"
    assert "mutually exclusive" in outcome.error.message


@pytest.mark.e2e
def test_script_validate_refuses_an_empty_selection_at_the_op():
    # The same failure the params model reports for the same selection, under the
    # same code — one condition, one code, on both sides of the wire.
    outcome = _validate_failure({"paths": [], "all_scripts": False})

    assert outcome.error.code == "invalid_params"


@pytest.mark.e2e
@pytest.mark.parametrize("all_scripts", [None, "yes", [], {}, 1])
def test_script_validate_refuses_a_non_boolean_all_scripts_at_the_op(all_scripts):
    # GDScript's `bool(value)` is not total: a null, a String, an Array or a
    # Dictionary makes it RAISE, which aborts _initialize before any sentinel is
    # printed — so the caller got the generic operation_failed instead of a
    # structured refusal naming the shape. The op type-checks the raw Variant
    # first, exactly as it does for `paths`. (`1` is included because an int IS
    # coercible: it must still be refused, since accepting one spelling of a
    # boolean and not another is the kind of drift the wire contract exists to
    # prevent.)
    outcome = _validate_failure({"paths": [], "all_scripts": all_scripts})

    assert outcome.error.code == "invalid_params"
    assert "all_scripts" in outcome.error.message


@pytest.mark.e2e
def test_script_validate_separates_a_bad_params_shape_from_a_bad_path_value():
    # The split the codes carry: a non-string entry is a params SHAPE problem
    # (invalid_params, which is also what pydantic reports for it), while an empty
    # string is a well-typed path VALUE that names nothing (invalid_path, like
    # every other unusable path).
    shape = _validate_failure({"paths": [123]})
    value = _validate_failure({"paths": [""]})

    assert shape.error.code == "invalid_params"
    assert value.error.code == "invalid_path"
