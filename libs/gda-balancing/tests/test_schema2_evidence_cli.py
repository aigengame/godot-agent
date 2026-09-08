"""Public Evidence verification CLI contract."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.interfaces.cli.evidence_verify import EVIDENCE_VERIFY
from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN
from gda_balancing.interfaces.cli.surface import surface_manifest


def test_descriptor_owns_the_exact_artifact_set_inputs() -> None:
    inputs = {
        item.receipt_field: item.producer
        for item in EVIDENCE_VERIFY.input_artifact_sets
    }

    assert inputs == {
        "experiment_run_artifact_set_receipt": EXPERIMENT_RUN,
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
    assert [
        [member["logical_name"] for member in artifact_set]
        for artifact_set in projected["experiment_run_artifact_set_receipt"][
            "artifact_sets"
        ]
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
        "rir_semantic_identity",
        "experiment_identity",
        "resolved_runtime_profile_identity",
        "evaluator_capability_manifest_identity",
        "experiment_run_artifact_set_receipt_identity",
    }
    assert all(
        value.startswith("sha256:")
        for name, value in result.items()
        if name.endswith("_identity")
    )


def test_public_cli_supports_params_json_with_the_same_four_inputs(
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


def test_public_cli_reports_an_unreadable_input_before_an_unknown_claim_kind(
    run_cli, invocation, tmp_path: Path
) -> None:
    argv = list(invocation(EVIDENCE_VERIFY, refusing=True))
    for option in (
        "--specification",
        "--rir",
        "--experiment-run-artifact-set-receipt",
    ):
        argv[argv.index(option) + 1] = str(
            tmp_path / f"missing-{option.removeprefix('--')}.json"
        )

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "unreadable_input"


def test_public_schema_and_help_expose_only_explicit_option_inputs(run_cli) -> None:
    schema_exit, schema_stdout, schema_stderr = run_cli(
        ["evidence", "verify", "--schema"]
    )
    help_exit, help_stdout, help_stderr = run_cli(["evidence", "verify", "--help"])

    assert (schema_exit, schema_stderr) == (0, "")
    schema = json.loads(schema_stdout)
    assert schema["input"]["required"] == [
        "claim_kind",
        "rir",
        "specification",
        "experiment_run_artifact_set_receipt",
    ]
    success_properties = schema["success"]["properties"]
    assert success_properties["claim_kind"] == {"title": "Claim Kind", "type": "string"}
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
        "--rir",
        "--specification",
        "--experiment-run-artifact-set-receipt",
    ):
        assert option in help_stdout
    assert "<document>" not in help_stdout
    assert "--source" not in help_stdout
    assert "--model-build-artifact-set-receipt" not in help_stdout


def test_public_cli_maps_missing_inputs_to_usage_exit_three(run_cli) -> None:
    exit_code, stdout, stderr = run_cli(["evidence", "verify"])

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize(
    ("changed_input", "stage", "code"),
    (
        ("receipt", "ingress", "kernel.identity_mismatch"),
        ("experiment", "evaluation", "evaluation.evaluable_mismatched_prerequisite"),
    ),
)
def test_public_cli_refuses_corrupt_or_mismatched_run_inputs(
    run_cli, invocation, changed_input: str, stage: str, code: str
) -> None:
    argv = invocation(EVIDENCE_VERIFY)
    option = (
        "--experiment-run-artifact-set-receipt"
        if changed_input == "receipt"
        else "--specification"
    )
    path = Path(argv[argv.index(option) + 1])
    value = json.loads(path.read_text(encoding="utf-8"))
    if changed_input == "receipt":
        value["content_identity"] = "sha256:" + "0" * 64
    else:
        value["metrics"][0]["target"]["maximum"] = 999
    path.write_text(json.dumps(value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == stage
    assert {row["code"] for row in error["diagnostics"]} == {code}
    assert all(row["primary"]["kind"] == "artifact" for row in error["diagnostics"])
