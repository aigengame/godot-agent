"""S2: classify_run — the command-agnostic failure classifier (issue #14).

``classify_run`` owns the env/operation/parse decision tree once, for every
command: given a raw ``RunResult`` and the command's typed output model, it
returns either the validated model or a stable ``Failure``. Per-command
classifiers (e.g. ``classify_info``) only layer command-specific checks on top.

The contract is exercised through a *hypothetical second command's* model — the
issue's acceptance bar: a new command must classify without copying any branch
of the decision tree.
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from gda.errors import Failure, classify_run
from gda.models import ErrorCategory
from gda.runner import RunResult

BINARY = Path("/x/Godot")


class SceneSummary(BaseModel):
    """A hypothetical second command's result model (not ``EngineVersion``)."""

    name: str
    root_type: str


def _sentinel(payload: dict) -> str:
    return f"<<<GDA:RESULT>>>{json.dumps(payload)}<<<GDA:END>>>\n"


def test_clean_run_parses_payload_into_the_commands_typed_model():
    # The engine exited 0 and stdout carries a sentinel payload matching the
    # command's model: classify_run returns the validated model instance, with
    # engine banner noise around the sentinel ignored (ADR-0002).
    result = RunResult(
        stdout="Godot Engine v4.6.stable\n"
        + _sentinel({"name": "Main", "root_type": "Node2D"}),
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert outcome == SceneSummary(name="Main", root_type="Node2D")


def test_synthesized_not_found_maps_to_environment_failure():
    # The runner synthesizes exit 127 + a not-found diagnostic when the binary
    # is missing (#2 convention) — an environment failure naming the binary.
    result = RunResult(
        stdout="", stderr="gda: Godot binary not found: /x/Godot\n", exit_code=127
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 127
    assert outcome.error.category == ErrorCategory.ENVIRONMENT
    assert outcome.error.code == "binary_not_found"
    assert str(BINARY) in outcome.error.message
    # Engine/script stderr is carried as diagnostics (ADR-0002).
    assert outcome.error.diagnostics == result.stderr


def test_synthesized_timeout_maps_to_environment_failure_distinct_from_not_found():
    # A launched-but-hung engine is bounded by the runner's timeout: exit 124
    # (#2). Still environment, but distinguishable from binary-not-found.
    result = RunResult(
        stdout="", stderr="gda: Godot timed out after 60.0s\n", exit_code=124
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 124
    assert outcome.error.category == ErrorCategory.ENVIRONMENT
    assert outcome.error.code == "launch_timeout"


def test_signal_death_maps_to_operation_failure_naming_the_signal():
    # subprocess reports a signal death as a negative return code: the engine
    # ran but was killed (e.g. SIGSEGV) — an operation failure, never a raw
    # negative exit code leaking out.
    result = RunResult(stdout="", stderr="", exit_code=-11)

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 4
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "engine_crashed"
    assert "11" in outcome.error.message


def test_engine_nonzero_exit_maps_to_operation_failure():
    # The engine launched and ran but the operation reported an error and quit
    # non-zero (its own exit, not the runner's synthetic 124/127).
    result = RunResult(
        stdout="", stderr="gda: unknown operation: bogus\n", exit_code=1
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 4
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "operation_failed"


@pytest.mark.parametrize(
    "stdout",
    [
        "Godot Engine v4.6.stable\nno sentinel here\n",
        "<<<GDA:RESULT>>>{not valid json}<<<GDA:END>>>\n",
    ],
    ids=["missing_sentinel", "malformed_json"],
)
def test_broken_sentinel_contract_maps_to_parse_failure(stdout):
    # The engine exited 0 but stdout violates the structured-output contract
    # (ADR-0002): no sentinel, or non-JSON between the sentinels. Must surface
    # as a structured parse failure, not escape as a traceback.
    result = RunResult(stdout=stdout, stderr="engine noise\n", exit_code=0)

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 5
    assert outcome.error.category == ErrorCategory.PARSE
    assert outcome.error.code == "contract_violation"


def test_wrong_shape_payload_maps_to_parse_failure():
    # Sentinels present, payload is valid JSON, but it does not match the
    # command's model — still a contract violation, surfaced as a structured
    # parse failure, NOT an unhandled pydantic ValidationError.
    result = RunResult(
        stdout=_sentinel({"name": "Main"}),  # root_type missing
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 5
    assert outcome.error.category == ErrorCategory.PARSE
    assert outcome.error.code == "contract_violation"
