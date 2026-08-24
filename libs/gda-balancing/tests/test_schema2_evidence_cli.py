"""Public Evidence verification CLI contract."""

import json
from typing import Any, cast

from gda_balancing.interfaces.cli.evidence_verify import EVIDENCE_VERIFY
from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN
from gda_balancing.interfaces.cli.model_build import MODEL_BUILD
from gda_balancing.interfaces.cli.surface import descriptor_identity, surface_manifest


def test_descriptor_owns_the_exact_artifact_set_inputs() -> None:
    inputs = {
        item.receipt_field: item.producer
        for item in EVIDENCE_VERIFY.input_artifact_sets
    }

    assert inputs == {
        "model_build_receipt": MODEL_BUILD,
        "experiment_outcome_receipt": EXPERIMENT_RUN,
    }
    rows = cast(
        list[dict[str, Any]],
        surface_manifest((EVIDENCE_VERIFY,))["commands"],
    )
    row = rows[0]
    projected = {
        item["receipt_field"]: item
        for item in cast(list[dict[str, Any]], row["input_artifact_sets"])
    }
    assert projected["model_build_receipt"]["producer_descriptor_identity"] == (
        descriptor_identity(MODEL_BUILD)
    )
    assert [
        member["logical_name"]
        for member in projected["model_build_receipt"]["artifact_sets"][0]
    ] == [member.logical_name for member in MODEL_BUILD.artifact_set]
    assert [
        [member["logical_name"] for member in artifact_set]
        for artifact_set in projected["experiment_outcome_receipt"]["artifact_sets"]
    ] == [
        [member.logical_name for member in EXPERIMENT_RUN.artifact_set],
        [member.logical_name for member in EXPERIMENT_RUN.verdict_artifact_set],
        [
            member.logical_name
            for member in EXPERIMENT_RUN.refusal_artifact_sets[0].members
        ],
    ]


def test_public_cli_returns_one_open_evaluable_candidate(run_cli, invocation) -> None:
    exit_code, stdout, stderr = run_cli(invocation(EVIDENCE_VERIFY))

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["claim_kind"] == "evaluable"
    assert result["claim_state"] == "candidate"
    assert result["producing_outcome"] == "success"
    assert set(result) == {
        "claim_kind",
        "claim_state",
        "producing_outcome",
        "kernel_identity",
        "language_bundle_identity",
        "model_source_identity",
        "resolved_model_identity",
        "experiment_identity",
        "resolved_runtime_profile_identity",
        "evaluator_capability_manifest_identity",
        "model_build_receipt_identity",
        "experiment_outcome_receipt_identity",
    }
    assert all(
        value.startswith("sha256:")
        for name, value in result.items()
        if name.endswith("_identity")
    )


def test_public_cli_supports_params_json_with_the_same_five_inputs(
    run_cli, invocation
) -> None:
    argv = invocation(EVIDENCE_VERIFY)
    params = {
        argv[index][2:].replace("-", "_"): argv[index + 1]
        for index in range(2, len(argv), 2)
    }

    direct = run_cli(argv)
    structured = run_cli(["evidence", "verify", "--params-json", json.dumps(params)])

    assert structured == direct


def test_public_cli_refuses_an_unknown_claim_kind(run_cli, invocation) -> None:
    exit_code, stdout, stderr = run_cli(invocation(EVIDENCE_VERIFY, refusing=True))

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.unknown_evidence_claim_kind"
    ]


def test_public_schema_and_help_expose_only_explicit_option_inputs(run_cli) -> None:
    schema_exit, schema_stdout, schema_stderr = run_cli(
        ["evidence", "verify", "--schema"]
    )
    help_exit, help_stdout, help_stderr = run_cli(["evidence", "verify", "--help"])

    assert (schema_exit, schema_stderr) == (0, "")
    schema = json.loads(schema_stdout)
    assert schema["input"]["required"] == [
        "claim_kind",
        "source",
        "specification",
        "model_build_receipt",
        "experiment_outcome_receipt",
    ]
    success_properties = schema["success"]["properties"]
    assert success_properties["claim_kind"]["const"] == "evaluable"
    assert success_properties["claim_state"]["const"] == "candidate"
    assert success_properties["producing_outcome"]["enum"] == [
        "success",
        "verdict",
        "runtime-refusal",
    ]
    assert "verdict" not in schema
    assert (help_exit, help_stderr) == (0, "")
    for option in (
        "--claim-kind",
        "--source",
        "--specification",
        "--model-build-receipt",
        "--experiment-outcome-receipt",
    ):
        assert option in help_stdout
    assert "<document>" not in help_stdout


def test_public_cli_maps_missing_inputs_to_usage_exit_three(run_cli) -> None:
    exit_code, stdout, stderr = run_cli(["evidence", "verify"])

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"
