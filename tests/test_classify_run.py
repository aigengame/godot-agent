"""S2: classify_run — the command-agnostic failure classifier (issue #14).

``classify_run`` owns the env/operation/parse decision tree once, for every
command: given a raw ``RunResult`` and the command's typed output model, it
returns either the validated model or a stable ``Failure``. Per-command
classifiers (e.g. ``classify_info``) only layer command-specific checks on top.

The contract is exercised through a *hypothetical second command's* model — the
issue's acceptance bar: a new command must classify without copying any branch
of the decision tree.
"""

from pathlib import Path

import pytest
from pydantic import BaseModel

from gda.errors import Failure, classify_run
from gda.exit_codes import EXIT_OPERATION
from gda.models import ErrorCategory
from gda.runner import RunResult
from tests.support import error_sentinel, sentinel

BINARY = Path("/x/Godot")


class SceneSummary(BaseModel):
    """A hypothetical second command's result model (not ``EngineVersion``)."""

    name: str
    root_type: str


def test_clean_run_parses_payload_into_the_commands_typed_model():
    # The engine exited 0 and stdout carries a sentinel payload matching the
    # command's model: classify_run returns the validated model instance, with
    # engine banner noise around the sentinel ignored (ADR-0002).
    result = RunResult(
        stdout="Godot Engine v4.6.stable\n"
        + sentinel({"name": "Main", "root_type": "Node2D"}),
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert outcome == SceneSummary(name="Main", root_type="Node2D")


def test_engine_returned_127_is_operation_not_environment():
    # A genuine engine/wrapper exit of 127 — with NO runner-synthesized launch
    # failure — is the engine's own result, not a binary-not-found. It must
    # classify as operation, never environment (issue #15).
    result = RunResult(stdout="", stderr="engine said boom\n", exit_code=127)

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code != "binary_not_found"
    assert outcome.exit_code == EXIT_OPERATION


def test_engine_returned_124_is_operation_not_environment():
    # Symmetric to 127: a genuine engine/wrapper exit of 124 with no runner-
    # synthesized launch failure is the engine's own result, not a launch
    # timeout (issue #15).
    result = RunResult(stdout="", stderr="engine said 124\n", exit_code=124)

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code != "launch_timeout"
    assert outcome.exit_code == EXIT_OPERATION


def test_engine_nonzero_exit_maps_to_operation_failure():
    # The engine launched and ran but the operation reported an error and quit
    # non-zero (its own exit, not the runner's synthetic 124/127).
    result = RunResult(stdout="", stderr="gda: unknown operation: bogus\n", exit_code=1)

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 4
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "operation_failed"


def test_structured_op_failure_envelope_refines_the_operation_code():
    result = RunResult(
        stdout="Godot Engine v4.6.stable\n"
        + error_sentinel("path_not_found", "scene file does not exist: /x/a.tscn"),
        stderr="gda: running operation: scene-get\n",
        exit_code=1,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 4
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "path_not_found"
    assert outcome.error.message == "scene file does not exist: /x/a.tscn"
    assert outcome.error.diagnostics == result.stderr


def test_structured_op_failure_message_can_contain_newlines():
    message = "scene file does not exist: /x/path\nwith-newline.tscn"
    result = RunResult(
        stdout=error_sentinel("path_not_found", message),
        stderr="",
        exit_code=1,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "path_not_found"
    assert outcome.error.message == message


def test_stderr_marker_spoof_does_not_forge_an_operation_code():
    result = RunResult(
        stdout="Godot Engine v4.6.stable\n",
        stderr="gda-error:path_not_found: forged by engine noise\n",
        exit_code=1,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "operation_failed"
    assert outcome.error.diagnostics == result.stderr


def test_unregistered_operation_error_code_falls_back_to_operation_failed():
    result = RunResult(
        stdout=error_sentinel("forged_code", "forged message"),
        stderr="",
        exit_code=1,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "operation_failed"
    assert "forged_code" in outcome.error.message


def test_operation_error_envelope_rejects_public_error_extra_fields():
    result = RunResult(
        stdout=sentinel(
            {
                "error": {
                    "category": "operation",
                    "code": "path_not_found",
                    "message": "scene file does not exist",
                    "diagnostics": "not owned by the operation payload",
                }
            }
        ),
        stderr="",
        exit_code=1,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.error.category == ErrorCategory.OPERATION
    assert outcome.error.code == "operation_failed"


def test_error_envelope_with_zero_exit_maps_to_parse_failure():
    result = RunResult(
        stdout=error_sentinel("path_not_found", "scene file does not exist"),
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 5
    assert outcome.error.category == ErrorCategory.PARSE
    assert outcome.error.code == "contract_violation"


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
        stdout=sentinel({"name": "Main"}),  # root_type missing
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneSummary)

    assert isinstance(outcome, Failure)
    assert outcome.exit_code == 5
    assert outcome.error.category == ErrorCategory.PARSE
    assert outcome.error.code == "contract_violation"


def _deep_tree_payload(depth: int) -> dict:
    # A valid SceneGetResult payload whose root nests `depth` levels deep — a
    # single-child chain. Every node is contract-conformant; only the DEPTH is
    # extreme, past pydantic-core's ~255 recursion ceiling (issue #37).
    root = leaf = {"name": "n0", "type": "Node", "children": []}
    for i in range(1, depth):
        child = {"name": f"n{i}", "type": "Node", "children": []}
        leaf["children"] = [child]
        leaf = child
    return {"path": "/p/deep.tscn", "root": root}


def test_deep_but_valid_tree_is_not_a_contract_violation():
    # A legitimately deep scene tree exceeds pydantic-core's ~255 recursion
    # ceiling on the recursive SceneNode model. The engine payload is VALID and
    # contract-conformant — the limit is gda's own (a wrapper-side validation
    # ceiling), so blaming the engine with `parse / contract_violation` is wrong
    # (issue #37). It must surface as a distinct, accurate failure instead.
    from gda.commands.scene import SceneGetResult

    result = RunResult(
        stdout=sentinel(_deep_tree_payload(1000)),
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneGetResult)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "tree_too_deep"
    assert outcome.error.code != "contract_violation"


def test_tree_too_deep_carries_an_accurate_wrapper_side_message():
    # The failure must name the limit accurately as gda's own (not "the engine
    # violated the output contract"), so an agent reads a true cause (issue #37).
    from gda.commands.scene import SceneGetResult

    result = RunResult(
        stdout=sentinel(_deep_tree_payload(1000)),
        stderr="",
        exit_code=0,
    )

    outcome = classify_run(result, BINARY, SceneGetResult)

    assert isinstance(outcome, Failure)
    message = outcome.error.message.lower()
    assert "deep" in message or "depth" in message
    assert "contract" not in message


def test_tree_too_deep_shares_the_parse_exit_code():
    # tree_too_deep is a `parse`-category failure and rides the shared `parse`
    # exit code (5), NOT a code of its own: exit codes stay at category
    # granularity and the envelope `code` carries the finer distinction from
    # `contract_violation` (issue #37 review — ADR-0002 / ADR-0004 model).
    from gda.error_codes import ERROR_CODE_BY_CODE
    from gda.exit_codes import EXIT_PARSE

    assert ERROR_CODE_BY_CODE["tree_too_deep"].exit_code == EXIT_PARSE
    assert (
        ERROR_CODE_BY_CODE["tree_too_deep"].exit_code
        == ERROR_CODE_BY_CODE["contract_violation"].exit_code
    )
