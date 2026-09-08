"""Complete result admission derives Metrics from committed observation evidence."""

from copy import deepcopy

import pytest

from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from test_bounded_fold_public import _source, _specification


@pytest.fixture(scope="module")
def metric_runs():
    model = check_model_source_value(_source())
    assert isinstance(model, CheckedModel), model
    rir = compile_checked_model(model)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=model.authority_context)
    cases = {}
    for source in ("snapshot", "event"):
        for accepted in (True, False):
            specification = _specification(rir, [1, 2, 3, 4])
            first = specification["scenarios"][0]
            first["id"] = "forward"
            second = deepcopy(first)
            second["id"] = "reverse"
            next(
                row for row in second["assignments"] if row["target"]["name"] == "items"
            )["value"]["value"] = [4, 3, 2, 1]
            specification["scenarios"] = [first, second]
            metric = specification["metrics"][1]
            metric["observation"].update(
                source=source,
                name="terminal" if source == "snapshot" else "folded",
                member="ordered_value" if source == "snapshot" else "fold_result",
            )
            minimum, maximum = 1234, 4321
            metric["target"] = {
                "minimum": minimum,
                "maximum": maximum if accepted else minimum,
            }
            specification["metrics"] = [metric]
            checked = check_experiment_value(
                specification, program, authority_context=model.authority_context
            )
            assert isinstance(checked, CheckedExperiment), checked
            outcome = evaluate_experiment(checked)
            assert isinstance(outcome, EvaluationArtifacts), outcome
            assert outcome.accepted is accepted
            members = {
                name: deepcopy(member.value) for name, member in outcome.members.items()
            }
            # The authored fold forms 1234/4321. Its result fact exists only in
            # Event evidence; the Snapshot instead exposes ordered_value state.
            assert [row["value"] for row in members["metric-dataset"]["samples"]] == [
                minimum,
                maximum,
            ]
            cases[source, accepted] = checked, members
    return cases


def _reseal(checked, members, name):
    members[name] = checked.output_contracts[name].identify(
        {
            key: value
            for key, value in members[name].items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
    )


def _reseal_result(checked, members):
    _reseal(checked, members, "metric-dataset")
    primary_name = (
        "evaluation-run" if "evaluation-run" in members else "experiment-verdict"
    )
    members[primary_name]["metric_dataset_identity"] = members["metric-dataset"][
        "content_identity"
    ]
    _reseal(checked, members, primary_name)
    assert all(
        validate_experiment_member(checked, name, value)
        for name, value in members.items()
    )


@pytest.mark.parametrize("source", ["snapshot", "event"])
@pytest.mark.parametrize("accepted", [True, False], ids=["accepted", "verdict"])
def test_metric_admission_preserves_real_observations_and_business_verdict(
    metric_runs, source, accepted
):
    checked, members = metric_runs[source, accepted]
    assert validate_experiment_artifact_set(checked, members)


def test_metric_admission_preserves_a_scenario_scoped_snapshot_selector(metric_runs):
    original, _members = metric_runs["snapshot", True]
    specification = deepcopy(original.value)
    specification["metrics"][0]["observation"]["name"] = "forward:terminal"
    checked = check_experiment_value(
        specification,
        admit_rir(original.rir, authority_context=original.authority_context),
        authority_context=original.authority_context,
    )
    assert isinstance(checked, CheckedExperiment), checked
    outcome = evaluate_experiment(checked)
    assert isinstance(outcome, EvaluationArtifacts), outcome
    members = {name: deepcopy(member.value) for name, member in outcome.members.items()}
    assert [
        (row["scenario"], row["value"]) for row in members["metric-dataset"]["samples"]
    ] == [("forward", 1234)]
    assert validate_experiment_artifact_set(checked, members)


@pytest.mark.parametrize("source", ["snapshot", "event"])
@pytest.mark.parametrize(
    "mutation",
    [
        "value",
        "missing",
        "duplicate",
        "cross-scenario",
        "metadata",
        "order",
        "target-flag",
    ],
)
def test_metric_admission_rejects_resealed_sample_forgery(
    metric_runs, source, mutation
):
    checked, original = metric_runs[source, True]
    assert validate_experiment_artifact_set(checked, original)
    members = deepcopy(original)
    samples = members["metric-dataset"]["samples"]
    if mutation == "value":
        samples[0]["value"] += 1
    elif mutation == "missing":
        samples.pop()
    elif mutation == "duplicate":
        samples.insert(1, deepcopy(samples[0]))
    elif mutation == "cross-scenario":
        for field in ("event_id", "snapshot_identity"):
            samples[0][field], samples[1][field] = samples[1][field], samples[0][field]
    elif mutation == "metadata":
        samples[0]["provenance"]["observation_name"] = "another-observation"
    elif mutation == "order":
        samples.reverse()
    else:
        samples[0]["within_target"] = False
        # Coordinate the claimed business verdict with the false target flag;
        # target truth still has to follow the admitted Metric and actual value.
        primary = members.pop("evaluation-run")
        primary.update(outcome="rejected", failed_metrics=[samples[0]["metric"]])
        members["experiment-verdict"] = primary
    _reseal_result(checked, members)
    assert not validate_experiment_artifact_set(checked, members)


@pytest.mark.parametrize(
    "accepted", [True, False], ids=["invented-failure", "hidden-failure"]
)
def test_metric_admission_rejects_resealed_wrong_primary_kind(metric_runs, accepted):
    checked, original = metric_runs["snapshot", accepted]
    assert validate_experiment_artifact_set(checked, original)
    members = deepcopy(original)
    if accepted:
        primary = members.pop("evaluation-run")
        primary.update(outcome="rejected", failed_metrics=["ordered_value"])
        members["experiment-verdict"] = primary
    else:
        primary = members.pop("experiment-verdict")
        primary.pop("failed_metrics")
        primary["outcome"] = "accepted"
        members["evaluation-run"] = primary
    _reseal_result(checked, members)
    assert not validate_experiment_artifact_set(checked, members)


def test_metric_admission_rejects_resealed_wrong_failed_metric(metric_runs):
    checked, original = metric_runs["snapshot", False]
    assert validate_experiment_artifact_set(checked, original)
    members = deepcopy(original)
    members["experiment-verdict"]["failed_metrics"] = ["another-metric"]
    _reseal_result(checked, members)
    assert not validate_experiment_artifact_set(checked, members)
