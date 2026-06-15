"""S1 (e2e): the headless op dispatcher always exits, structured (issue #31).

These drive operations.gd below the CLI/pydantic layer (which would reject the
inputs first), proving the GDScript dispatch itself never hangs and reports a
stable code: a malformed param that once crashed a typed assignment and left
the main loop spinning is now a prompt operation failure, and dispatcher-level
errors (unknown operation, non-JSON params) carry their own stable codes rather
than the generic operation_failed.
"""

import shutil
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
        [str(GODOT), "--headless", "--script", str(OPERATIONS_GD), "--", "info", "{not json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = RunResult(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)

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
