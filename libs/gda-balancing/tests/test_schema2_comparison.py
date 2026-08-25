"""Domain Comparison semantics for exact Experiment Replay."""

import json
from dataclasses import replace
from pathlib import Path

import gda_balancing.application.experiment_replay as replay_application
import gda_balancing.interfaces.cli.experiment_replay as replay_command
from gda_balancing.application.experiment_execution import (
    ExperimentExecutionSuccess,
    execute_checked_experiment,
)
from gda_balancing.domain.comparison import (
    EXACT_REPLAY_COMPARISON_IMPLEMENTATION,
    compare_exact_replay,
    validate_exact_replay_comparison,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment
from gda_balancing.interfaces.cli.experiment_fixtures import (
    prepare_valid_experiment,
    prepare_verdict_experiment,
)
from gda_balancing.interfaces.cli.registry import REGISTRY


def _accepted_execution(
    root: Path,
) -> tuple[CheckedExperiment, ExperimentExecutionSuccess]:
    root.mkdir(parents=True, exist_ok=True)
    specification = root / "experiment.json"
    specification.write_text(
        prepare_valid_experiment(root, 545),
        encoding="utf-8",
    )
    checked = check_experiment(str(specification))
    assert isinstance(checked, CheckedExperiment)
    execution = execute_checked_experiment(checked)
    assert isinstance(execution, ExperimentExecutionSuccess)
    return checked, execution


def _verdict_execution(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    specification = root / "experiment.json"
    specification.write_text(
        prepare_verdict_experiment(root, 546),
        encoding="utf-8",
    )
    checked = check_experiment(str(specification))
    assert isinstance(checked, CheckedExperiment)
    execution = execute_checked_experiment(checked)
    return checked, execution


def test_exact_replay_comparison_applies_admitted_ordered_policy(tmp_path):
    checked, execution = _accepted_execution(tmp_path)

    comparison = compare_exact_replay(
        language_bundle=checked.language_bundle,
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
        "package_version": "1.1.0",
        "version": "1.0.0",
    }
    assert comparison.value["result"] == "matched"
    assert [row["key"] for row in comparison.value["checks"]] == [
        "evaluation-outcome-status",
        "event-trace-identity",
        "snapshot-series-identity",
        "metric-dataset-identity",
    ]
    assert all(row["match"] is True for row in comparison.value["checks"])
    assert validate_exact_replay_comparison(
        comparison.value,
        language_bundle=checked.language_bundle,
        original_artifact_set_receipt_identity="sha256:original-receipt",
        original_members=execution.members,
        replay_members=execution.members,
    )


def test_exact_replay_comparison_reports_complete_ordered_mismatch(tmp_path):
    original_checked, original = _accepted_execution(tmp_path / "original")
    _replay_checked, replay = _verdict_execution(tmp_path / "replay")

    comparison = compare_exact_replay(
        language_bundle=original_checked.language_bundle,
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


def _published_original_run(tmp_path, run_cli, *, verdict: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    specification = tmp_path / "experiment.json"
    prepare = prepare_verdict_experiment if verdict else prepare_valid_experiment
    specification.write_text(prepare(tmp_path, 547), encoding="utf-8")
    run_exit, run_stdout, run_stderr = run_cli(
        [
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "original.json"),
            "--invocation-key",
            "a" * 64,
        ]
    )
    assert run_exit == (1 if verdict else 0)
    assert run_stderr == ""
    original_receipt = tmp_path / "original-receipt.json"
    run_result = json.loads(run_stdout)
    receipt = run_result["artifact_set"] if verdict else run_result
    original_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    return specification, original_receipt


def _replay_argv(
    specification: Path,
    original_receipt: Path,
    out: Path,
    *,
    invocation_key: str = "b" * 64,
) -> list[str]:
    return [
        "experiment",
        "replay",
        str(specification),
        "--original-experiment-run-artifact-set-receipt",
        str(original_receipt),
        "--out",
        str(out),
        "--invocation-key",
        invocation_key,
    ]


def test_public_experiment_replay_runs_from_authenticated_receipt(tmp_path, run_cli):
    specification, original_receipt = _published_original_run(tmp_path, run_cli)

    replay_exit, replay_stdout, replay_stderr = run_cli(
        _replay_argv(
            specification,
            original_receipt,
            tmp_path / "comparison.json",
        )
    )

    assert (replay_exit, replay_stderr) == (0, ""), replay_stdout
    result = json.loads(replay_stdout)
    assert result["claim_state"] == "candidate"
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["artifact_kind"] == "replay-comparison"
    assert comparison["result"] == "matched"


def test_public_replay_schema_exposes_only_the_four_owned_inputs(run_cli):
    exit_code, stdout, stderr = run_cli(["experiment", "replay", "--schema"])

    assert (exit_code, stderr) == (0, "")
    schema = json.loads(stdout)
    assert set(schema["input"]["properties"]) == {
        "specification",
        "original_experiment_run_artifact_set_receipt",
        "out",
        "invocation_key",
    }


def test_public_replay_refuses_a_different_reproduction_before_dispatch(
    tmp_path, run_cli, monkeypatch
):
    specification, original_receipt = _published_original_run(tmp_path, run_cli)
    changed = json.loads(specification.read_text(encoding="utf-8"))
    changed["seed"]["value"] += 1
    specification.write_text(json.dumps(changed), encoding="utf-8")

    def dispatch_must_not_run(_prepared):
        raise AssertionError("reproduction mismatch reached Event dispatch")

    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        dispatch_must_not_run,
    )
    out = tmp_path / "must-not-exist.json"
    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, original_receipt, out)
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.replay_reproduction_mismatch"
    ]
    assert not out.exists()


def test_public_replay_refuses_a_non_successful_original_run(tmp_path, run_cli):
    specification, original_receipt = _published_original_run(
        tmp_path, run_cli, verdict=True
    )
    out = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, original_receipt, out)
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [row["code"] for row in error["diagnostics"]] == [
        "evaluation.replay_ineligible_outcome"
    ]
    assert not out.exists()


def test_public_replay_mismatch_publishes_only_comparison_evidence(
    tmp_path, run_cli, monkeypatch
):
    specification, original_receipt = _published_original_run(
        tmp_path / "original", run_cli
    )
    _checked, replay_verdict = _verdict_execution(tmp_path / "changed-runtime")
    monkeypatch.setattr(
        replay_application,
        "execute_prepared_experiment",
        lambda _prepared: replay_verdict,
    )
    comparison_path = tmp_path / "comparison.json"

    exit_code, stdout, stderr = run_cli(
        _replay_argv(specification, original_receipt, comparison_path)
    )

    assert (exit_code, stderr) == (1, "")
    result = json.loads(stdout)
    assert result["outcome"] == "mismatched"
    assert result["mismatches"] == [
        "evaluation-outcome-status",
        "event-trace-identity",
        "snapshot-series-identity",
        "metric-dataset-identity",
    ]
    logical_names = {
        row["logical_name"] for row in result["artifact_set"]["member_locators"]
    }
    assert logical_names == {
        "replay-comparison",
        "event-trace",
        "snapshot-series",
        "metric-dataset",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "evaluator-capability-manifest",
    }
    assert json.loads(comparison_path.read_text())["result"] == "mismatched"


def test_public_replay_recovers_a_committed_result_without_dispatch(
    tmp_path, run_cli, monkeypatch
):
    specification, original_receipt = _published_original_run(tmp_path, run_cli)
    out = tmp_path / "recovered-comparison.json"
    argv = _replay_argv(specification, original_receipt, out)
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
