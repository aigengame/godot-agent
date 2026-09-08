"""Domain Comparison semantics for exact Experiment Replay."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

import gda_balancing.application.experiment_replay as replay_application
import gda_balancing.interfaces.cli.experiment_replay as replay_command
import pytest
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionSuccess,
    ExperimentExecutionVerdict,
    execute_checked_experiment,
)
from gda_balancing.domain.artifacts import identified_artifact
from gda_balancing.domain.comparison import (
    EXACT_REPLAY_COMPARISON_IMPLEMENTATION,
    compare_exact_replay,
    select_exact_replay_contract,
    exact_replay_runtime_profile_refusal,
    validate_exact_replay_comparison,
    validate_published_exact_replay_comparison,
)
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.application.experiment_inputs import check_experiment_inputs
from gda_balancing.domain.publication_types import PublicationMember
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.registry import REGISTRY


def _authority_context(checked: CheckedExperiment):
    assert checked.authority_context is not None
    return checked.authority_context


def _accepted_execution(
    root: Path,
) -> tuple[CheckedExperiment, ExperimentExecutionSuccess]:
    root.mkdir(parents=True, exist_ok=True)
    specification = root / "experiment.json"
    fixture = prepare_valid_experiment(root, 545)
    specification.write_text(fixture.specification, encoding="utf-8")
    checked = check_experiment_inputs(str(specification), fixture.rir)
    assert isinstance(checked, CheckedExperiment)
    execution = execute_checked_experiment(checked)
    assert isinstance(execution, ExperimentExecutionSuccess)
    return checked, execution


def _verdict_execution(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    specification = root / "experiment.json"
    fixture = prepare_verdict_experiment(root, 546)
    specification.write_text(fixture.specification, encoding="utf-8")
    checked = check_experiment_inputs(str(specification), fixture.rir)
    assert isinstance(checked, CheckedExperiment)
    execution = execute_checked_experiment(checked)
    return checked, execution


# These Domain rows only read the accepted members. Reuse one execution so the
# Experiment shard does not rebuild and execute the same fixture for each check.
_CACHED_ACCEPTED_EXECUTION: (
    tuple[CheckedExperiment, ExperimentExecutionSuccess] | None
) = None


@pytest.fixture
def accepted_execution(
    tmp_path: Path,
    isolated_schema2_store: None,
) -> tuple[CheckedExperiment, ExperimentExecutionSuccess]:
    del isolated_schema2_store
    global _CACHED_ACCEPTED_EXECUTION
    if _CACHED_ACCEPTED_EXECUTION is None:
        _CACHED_ACCEPTED_EXECUTION = _accepted_execution(
            tmp_path / "accepted-execution"
        )
    return _CACHED_ACCEPTED_EXECUTION


def _artifact_payload(value: dict) -> dict:
    return {
        key: deepcopy(item)
        for key, item in value.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }


def _member(checked: CheckedExperiment, kind: str, payload: dict) -> PublicationMember:
    value = identified_artifact(checked.language_bundle, kind, payload)
    return PublicationMember(
        value=value,
        artifact_kind=kind,
        wire_schema_identity=cast(str, value["wire_schema_identity"]),
        content_identity=cast(str, value["content_identity"]),
    )


def _same_execution_observation_drift(
    checked: CheckedExperiment,
    execution: ExperimentExecutionSuccess,
) -> ExperimentExecutionVerdict:
    trace_payload = _artifact_payload(execution.members["event-trace"].value)
    trace_payload["events"][0]["operation"] += ".drift"
    trace = _member(checked, "event-trace", trace_payload)

    snapshot_payload = _artifact_payload(execution.members["snapshot-series"].value)
    snapshot_payload["event_trace_identity"] = trace.content_identity
    snapshots = _member(checked, "snapshot-series", snapshot_payload)

    metric_payload = _artifact_payload(execution.members["metric-dataset"].value)
    metric_payload["samples"][0]["within_target"] = False
    metrics = _member(checked, "metric-dataset", metric_payload)
    failed_metrics = (metric_payload["samples"][0]["metric"],)

    resolved_runtime = execution.members["resolved-runtime-profile"]
    verdict = _member(
        checked,
        "experiment-verdict",
        {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "event_trace_identity": trace.content_identity,
            "snapshot_series_identity": snapshots.content_identity,
            "metric_dataset_identity": metrics.content_identity,
            "root_event_map": trace.value["root_event_map"],
            "terminal_statuses": trace.value["terminal_statuses"],
            "outcome": "rejected",
            "failed_metrics": list(failed_metrics),
        },
    )
    members = {
        **execution.members,
        "experiment-verdict": verdict,
        "event-trace": trace,
        "snapshot-series": snapshots,
        "metric-dataset": metrics,
    }
    del members["evaluation-run"]
    return ExperimentExecutionVerdict(failed_metrics=failed_metrics, members=members)


def _same_outcome_observation_drift(
    checked: CheckedExperiment,
    execution: ExperimentExecutionSuccess,
) -> ExperimentExecutionSuccess:
    metric_payload = _artifact_payload(execution.members["metric-dataset"].value)
    metric_payload["samples"][0]["value"] += 1
    metrics = _member(checked, "metric-dataset", metric_payload)

    outcome_payload = _artifact_payload(execution.members["evaluation-run"].value)
    outcome_payload["metric_dataset_identity"] = metrics.content_identity
    outcome = _member(checked, "evaluation-run", outcome_payload)
    return ExperimentExecutionSuccess(
        members={
            **execution.members,
            "evaluation-run": outcome,
            "metric-dataset": metrics,
        }
    )


def test_exact_replay_comparison_applies_admitted_ordered_policy(accepted_execution):
    checked, execution = accepted_execution

    comparison = compare_exact_replay(
        replay_contract=select_exact_replay_contract(_authority_context(checked)),
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=execution.members,
        replay_members=execution.members,
    )

    assert comparison.value["comparison_implementation_identity"] == (
        EXACT_REPLAY_COMPARISON_IMPLEMENTATION
    )
    assert comparison.value["policy"] == {
        "id": "exact-replay-v1",
        "package": "standard.experiment",
    }
    assert comparison.value["result"] == "matched"
    assert [row["key"] for row in comparison.value["checks"]] == [
        "evaluation_outcome_status",
        "event_trace_identity",
        "snapshot_series_identity",
        "metric_dataset_identity",
    ]
    assert all(row["match"] is True for row in comparison.value["checks"])
    assert validate_exact_replay_comparison(
        comparison.value,
        replay_contract=select_exact_replay_contract(_authority_context(checked)),
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=execution.members,
        replay_members=execution.members,
    )


def test_exact_replay_comparison_reports_complete_ordered_mismatch(accepted_execution):
    original_checked, original = accepted_execution
    replay = _same_execution_observation_drift(original_checked, original)

    comparison = compare_exact_replay(
        replay_contract=select_exact_replay_contract(
            _authority_context(original_checked)
        ),
        output_contracts=original_checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=original.members,
        replay_members=replay.members,
    )

    assert comparison.value["result"] == "mismatched"
    assert comparison.value["replay_outcome_kind"] == "experiment-verdict"
    assert (
        comparison.value["original_observation"]["evaluation_outcome_status"]
        == "accepted"
    )
    assert (
        comparison.value["replay_observation"]["evaluation_outcome_status"]
        == "rejected"
    )
    assert len(comparison.value["checks"]) == 4
    assert all(row["match"] is False for row in comparison.value["checks"])


def test_exact_replay_comparison_rejects_a_foreign_semantic_execution(
    tmp_path, accepted_execution
):
    original_checked, original = accepted_execution
    _replay_checked, replay = _verdict_execution(tmp_path / "verdict-execution")

    with pytest.raises(ValueError, match="semantic execution identity"):
        compare_exact_replay(
            replay_contract=select_exact_replay_contract(
                _authority_context(original_checked)
            ),
            output_contracts=original_checked.output_contracts,
            original_artifact_set_receipt_identity="sha256:original-receipt",
            original_members=original.members,
            replay_members=replay.members,
        )


def test_published_mismatch_reconstructs_the_omitted_verdict_identity(
    accepted_execution,
):
    checked, original = accepted_execution
    replay = _same_execution_observation_drift(checked, original)
    comparison = compare_exact_replay(
        replay_contract=select_exact_replay_contract(_authority_context(checked)),
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=original.members,
        replay_members=replay.members,
    )
    retained_replay_members = {
        name: member
        for name, member in replay.members.items()
        if name != "experiment-verdict"
    }

    assert validate_published_exact_replay_comparison(
        comparison.value,
        replay_contract=select_exact_replay_contract(_authority_context(checked)),
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=original.members,
        replay_members=retained_replay_members,
    )

    forged_payload = _artifact_payload(comparison.value)
    forged_payload["replay_outcome_identity"] = "sha256:forged"
    forged = identified_artifact(
        checked.language_bundle, "replay-comparison", forged_payload
    )
    assert not validate_published_exact_replay_comparison(
        forged,
        replay_contract=select_exact_replay_contract(_authority_context(checked)),
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=original.members,
        replay_members=retained_replay_members,
    )


def _published_original_run(
    tmp_path,
    run_cli,
    *,
    verdict: bool = False,
    invocation_key: str = "a" * 64,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    specification = tmp_path / "experiment.json"
    prepare = prepare_verdict_experiment if verdict else prepare_valid_experiment
    fixture = prepare(tmp_path, 547)
    specification.write_text(fixture.specification, encoding="utf-8")
    run_exit, run_stdout, run_stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--rir",
            fixture.rir,
            "--out",
            str(tmp_path / "original.json"),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert run_exit == (1 if verdict else 0)
    assert run_stderr == ""
    original_receipt = tmp_path / "original-receipt.json"
    run_result = json.loads(run_stdout)
    receipt = run_result["artifact_set"] if verdict else run_result
    original_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    return specification, original_receipt, fixture.rir


# The source publication is immutable. Each Replay row below still uses its own
# invocation key, so sharing the authenticated original cannot recover another row.
_CACHED_PUBLISHED_ORIGINAL: tuple[Path, Path, str, Path] | None = None


@pytest.fixture
def published_original(
    tmp_path,
    run_cli,
    monkeypatch,
    isolated_schema2_store: None,
) -> tuple[Path, Path, str]:
    del isolated_schema2_store
    global _CACHED_PUBLISHED_ORIGINAL
    if _CACHED_PUBLISHED_ORIGINAL is None:
        specification, receipt, rir = _published_original_run(tmp_path, run_cli)
        _CACHED_PUBLISHED_ORIGINAL = (
            specification,
            receipt,
            rir,
            tmp_path / ".gda-balancing-store-v2",
        )
    specification, receipt, rir, store = _CACHED_PUBLISHED_ORIGINAL
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))
    return specification, receipt, rir


def _replay_argv(
    specification: Path,
    original_receipt: Path,
    rir: str,
    out: Path,
    *,
    invocation_key: str = "b" * 64,
) -> list[str]:
    return [
        "experiment",
        "replay",
        str(specification),
        "--rir",
        rir,
        "--original-experiment-run-artifact-set-receipt",
        str(original_receipt),
        "--out",
        str(out),
        "--invocation-key",
        invocation_key,
    ]


def test_public_experiment_replay_runs_from_authenticated_receipt(
    tmp_path, run_cli, published_original
):
    specification, original_receipt, rir = published_original

    replay_exit, replay_stdout, replay_stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            rir,
            tmp_path / "comparison.json",
        )
    )

    assert (replay_exit, replay_stderr) == (0, ""), replay_stdout
    result = json.loads(replay_stdout)
    assert result["claim_state"] == "candidate"
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["artifact_kind"] == "replay-comparison"
    assert comparison["result"] == "matched"


def test_public_replay_schema_exposes_only_the_five_owned_inputs(run_cli):
    exit_code, stdout, stderr = run_cli(["experiment", "replay", "--schema"])

    assert (exit_code, stderr) == (0, "")
    schema = json.loads(stdout)
    assert set(schema["input"]["properties"]) == {
        "specification",
        "rir",
        "original_experiment_run_artifact_set_receipt",
        "out",
        "invocation_key",
    }
    assert set(schema["input"]["required"]) == set(schema["input"]["properties"])


def test_public_replay_refuses_a_prepared_runtime_drift_before_dispatch(
    tmp_path, run_cli, monkeypatch, published_original
):
    specification, original_receipt, rir = published_original
    prepare = replay_application.prepare_checked_experiment

    def prepare_with_runtime_drift(checked):
        prepared = prepare(checked)
        assert not isinstance(prepared, replay_application.ExperimentExecutionRefusal)
        payload = _artifact_payload(prepared.resolved_runtime.value)
        payload["rir_semantic_identity"] = "sha256:" + "7" * 64
        return replace(
            prepared,
            resolved_runtime=_member(checked, "resolved-runtime-profile", payload),
        )

    def dispatch_must_not_run(_prepared):
        raise AssertionError("semantic execution mismatch reached Event dispatch")

    monkeypatch.setattr(
        replay_application, "prepare_checked_experiment", prepare_with_runtime_drift
    )
    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        dispatch_must_not_run,
    )
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            rir,
            out,
            invocation_key="c" * 64,
        )
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.replay_reproduction_mismatch"
    ]
    assert not out.exists()


def test_runtime_profile_check_covers_each_semantic_identity(accepted_execution):
    checked, execution = accepted_execution
    original = execution.members["resolved-runtime-profile"].value
    replay_contract = select_exact_replay_contract(_authority_context(checked))
    assert (
        exact_replay_runtime_profile_refusal(
            checked, original, original, replay_contract
        )
        is None
    )
    # Authored seeds, streams, assignments and ordering are committed by the
    # Experiment identity; program semantics and the selected policy have their
    # existing identities. Producer and Build identities are no longer inputs.
    changes = (
        ("experiment_identity", "sha256:" + "1" * 64),
        ("rir_semantic_identity", "sha256:" + "2" * 64),
        ("runtime_profile_definition_identity", "sha256:" + "3" * 64),
        ("runtime_profile", {**original["runtime_profile"], "id": "changed-profile"}),
    )
    for field, replacement in changes:
        payload = _artifact_payload(original)
        payload[field] = replacement
        changed = _member(checked, "resolved-runtime-profile", payload)
        refusal = exact_replay_runtime_profile_refusal(
            checked, original, changed.value, replay_contract
        )
        assert refusal is not None, field
        assert refusal.stage == "evaluation"
        assert refusal.diagnostics[0].code == (
            "evaluation.replay_reproduction_mismatch"
        )


def test_public_replay_refuses_a_non_successful_original_run(tmp_path, run_cli):
    specification, original_receipt, rir = _published_original_run(
        tmp_path,
        run_cli,
        verdict=True,
        invocation_key="c" * 64,
    )
    out = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            rir,
            out,
            invocation_key="f" * 64,
        )
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.replay_ineligible_outcome"
    ]
    assert not out.exists()


def test_public_replay_mismatch_publishes_only_comparison_evidence(
    tmp_path, run_cli, monkeypatch, published_original
):
    specification, original_receipt, rir = published_original
    execute = replay_application.execute_prepared_experiment

    def execute_with_observation_drift(prepared):
        execution = execute(prepared)
        assert isinstance(execution, ExperimentExecutionSuccess)
        return _same_outcome_observation_drift(prepared.checked, execution)

    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        execute_with_observation_drift,
    )
    comparison_path = tmp_path / "comparison.json"

    exit_code, stdout, stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            rir,
            comparison_path,
            invocation_key="d" * 64,
        )
    )

    assert (exit_code, stderr) == (1, "")
    result = json.loads(stdout)
    assert result["outcome"] == "mismatched"
    assert result["mismatches"] == ["metric_dataset_identity"]
    logical_names = {
        row["logical_name"] for row in result["artifact_set"]["member_locators"]
    }
    assert logical_names == {
        "replay-comparison",
        "event-trace",
        "snapshot-series",
        "metric-dataset",
        "resolved-runtime-profile",
        "evaluator-capability-manifest",
    }
    assert json.loads(comparison_path.read_text())["result"] == "mismatched"


def test_public_replay_recovers_a_committed_result_without_dispatch(
    tmp_path, run_cli, monkeypatch, published_original
):
    specification, original_receipt, rir = published_original
    out = tmp_path / "recovered-comparison.json"
    argv = _replay_argv(
        specification,
        original_receipt,
        rir,
        out,
        invocation_key="e" * 64,
    )
    faulting_descriptor = replace(
        replay_command.EXPERIMENT_REPLAY,
        handler=replay_command.experiment_replay_handler(
            publication_fault="after-commit"
        ),
    )
    registry = tuple(
        faulting_descriptor if item is replay_command.EXPERIMENT_REPLAY else item
        for item in REGISTRY
    )

    first_exit, first_stdout, first_stderr = run_cli(argv, registry=registry)
    assert (first_exit, first_stdout) == (4, "")
    assert json.loads(first_stderr)["error"]["code"] == "internal_error"
    assert not out.exists()

    def dispatch_must_not_run(_prepared):
        raise AssertionError("committed Replay recovery reached Event dispatch")

    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        dispatch_must_not_run,
    )
    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["claim_state"] == "candidate"
    assert json.loads(out.read_text())["result"] == "matched"


def test_public_replay_rejects_a_changed_seed_for_a_committed_invocation_key(
    tmp_path, run_cli, monkeypatch, published_original
):
    specification, original_receipt, rir = published_original
    invocation_key = "9" * 64
    first_out = tmp_path / "original-replay-comparison.json"

    first_exit, first_stdout, first_stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            rir,
            first_out,
            invocation_key=invocation_key,
        )
    )
    assert (first_exit, first_stderr) == (0, ""), first_stdout

    changed_value = json.loads(specification.read_text(encoding="utf-8"))
    changed_value["seed"]["value"] += 1
    changed_specification = tmp_path / "changed-seed-experiment.json"
    changed_specification.write_text(json.dumps(changed_value), encoding="utf-8")

    def dispatch_must_not_run(_prepared):
        raise AssertionError("Invocation-key conflict reached Event dispatch")

    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        dispatch_must_not_run,
    )
    conflict_out = tmp_path / "conflicting-replay-comparison.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(
            changed_specification,
            original_receipt,
            rir,
            conflict_out,
            invocation_key=invocation_key,
        )
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"
    assert not conflict_out.exists()


def test_replay_consumes_detached_policy_reasons_and_output_contracts(
    accepted_execution, monkeypatch
):
    import gda_balancing.domain.artifacts as artifact_module
    import gda_balancing.domain.comparison as comparison_module

    checked, execution = accepted_execution
    selected = select_exact_replay_contract(_authority_context(checked))
    policy_source = deepcopy(selected.policy_binding)
    reason_source = cast(dict, deepcopy(selected.reasons))
    selected = replace(selected, policy_binding=policy_source, reasons=reason_source)
    policy_source["policy"]["checks"].clear()
    reason_source["evaluation.reason.replay-reproduction-mismatch"]["diagnostic"] = (
        "caller.changed-the-reason"
    )

    def ambient_lookup_forbidden(*_args, **_kwargs):
        raise AssertionError("Replay consulted an authority catalog after selection")

    monkeypatch.setattr(comparison_module, "reason_by_id", ambient_lookup_forbidden)
    monkeypatch.setattr(
        comparison_module, "select_protocol_artifact_contract", ambient_lookup_forbidden
    )
    monkeypatch.setattr(
        artifact_module, "select_artifact_contract", ambient_lookup_forbidden
    )
    comparison = compare_exact_replay(
        replay_contract=selected,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=execution.members,
        replay_members=execution.members,
    )
    assert comparison.value["result"] == "matched"
    assert len(comparison.value["checks"]) == 4
    assert validate_published_exact_replay_comparison(
        comparison.value,
        replay_contract=selected,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=execution.members,
        replay_members=execution.members,
    )
    original = execution.members["resolved-runtime-profile"].value
    payload = _artifact_payload(original)
    payload["experiment_identity"] = "sha256:" + "4" * 64
    changed = checked.output_contracts["resolved-runtime-profile"].identify(payload)
    refusal = exact_replay_runtime_profile_refusal(checked, original, changed, selected)
    assert refusal is not None
    assert refusal.diagnostics[0].code == "evaluation.replay_reproduction_mismatch"
    with pytest.raises(TypeError, match="immutable"):
        selected.policy_binding["policy"]["checks"].clear()
    with pytest.raises(TypeError, match="immutable"):
        cast(dict, selected.reasons["evaluation.reason.replay-reproduction-mismatch"])[
            "stage"
        ] = "runtime"
