"""Domain Comparison semantics for exact Experiment Replay."""

from pathlib import Path

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
    assert any(row["match"] is False for row in comparison.value["checks"])
