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
