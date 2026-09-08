"""Independent Runtime execution consumes selected RIR before sharing results."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_operation_execution_independent_support import (
    ReferenceEventFrame,
    reference_execute_event,
)
from test_bounded_fold_public import _source, _specification
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)


@pytest.fixture(scope="module")
def independent_fold():
    kernel, language = mutable_authorities()
    assert _consumer_b(kernel, language)["admitted"]
    checked = _reference_check_source(_source(), kernel, language)
    assert not isinstance(checked, tuple), checked
    artifacts = _reference_semantic_artifacts(checked)
    return kernel, checked, artifacts["rir-semantic-payload"]


def _fold_frame(rir, specification):
    scenario = specification["scenarios"][0]
    values = {
        tuple(
            row["target"][member] for member in ("model", "module", "name")
        ): deepcopy(row["value"])
        for row in scenario["assignments"]
    }
    return ReferenceEventFrame(
        values=values,
        rng_states={},
        rng_indices={},
        node_steps=0,
        ordering_key={
            "logical_time": 0,
            "phase": "transition",
            "priority": 0,
            "enqueue_sequence": 0,
        },
    )


def _fold_event(kernel, rir, specification, frame):
    entrypoint = rir["entrypoints"][0]
    operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    coordinate = (entrypoint["operation"]["package"], entrypoint["operation"]["id"])
    return reference_execute_event(
        kernel,
        operations[coordinate],
        operations,
        specification["scenarios"][0],
        seed=specification["seed"]["value"],
        resolved_entrypoint=entrypoint,
        resolved_declarations=rir["declarations"],
        resolved_call_sites=rir["call_sites"],
        root_operation_coordinate=coordinate,
        selected_semantics=rir["selected_semantics"],
        include_execution_evidence=True,
        frame=frame,
    )


@pytest.mark.parametrize("items,ordered", [([1, 2, 3, 4], 1234), ([4, 3, 2, 1], 4321)])
def test_independent_events_use_native_nominal_rir_and_committed_frames(
    independent_fold, items, ordered
):
    kernel, _, rir = independent_fold
    specification = _specification(rir, items)
    first = _fold_event(kernel, rir, specification, _fold_frame(rir, specification))
    assert "refusal" not in first
    after = {row["name"]: row["value"] for row in first["state_after"]}
    assert after["selected_items"]["value"] == [value for value in items if value < 3]
    assert after["selected_count"] == 2
    assert after["ordered_value"] == ordered
    continuation = first["continuation"]
    assert continuation.node_steps == 46
    second = _fold_event(kernel, rir, specification, continuation)
    assert second["state_before"] == first["state_after"]
    assert second["state_after"] == first["state_after"]
    assert second["continuation"].node_steps == 92
    assert first["execution_evidence"]["resource_charge"] == 46
    assert second["execution_evidence"]["resource_charge"] == 46


def test_independent_nominal_support_does_not_default_missing_quantity_bounds(
    independent_fold,
):
    kernel, _, original = independent_fold
    rir = deepcopy(original)
    declaration = next(
        row for row in rir["declarations"] if row["symbol"] == "ordered_value"
    )
    del declaration["domain_kind"]
    specification = _specification(rir, [1, 2, 3, 4])
    with pytest.raises(KeyError, match="domain_kind"):
        _fold_event(kernel, rir, specification, _fold_frame(rir, specification))


def _two_root_specification(rir, items):
    specification = _specification(rir, items)
    scenario = specification["scenarios"][0]
    root = scenario["event_plan"][0]
    scenario["event_plan"] = [
        {**deepcopy(root), "root_event_ref": "late", "logical_time": 1},
        {**deepcopy(root), "root_event_ref": "early", "logical_time": 0},
    ]
    scenario["terminal_condition"]["maximum"] = 2
    ordered = sum(
        item * 10 ** (len(items) - index - 1) for index, item in enumerate(items)
    )
    metric = next(
        row for row in specification["metrics"] if row["id"] == "ordered_value"
    )
    metric["target"] = {"minimum": ordered, "maximum": ordered}
    return specification


@pytest.fixture(
    scope="module", params=[[1, 2, 3, 4], [4, 3, 2, 1]], ids=["forward", "reverse"]
)
def mutual_results(independent_fold, tmp_path_factory, request):
    from pathlib import Path
    import json

    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.model import AdmittedRir, admit_rir
    from schema2_runtime_independent_support import reference_runtime_artifacts
    from test_current_namespace_public import _PublicCandidate, _members

    kernel, reference_context, rir = independent_fold
    specification = _two_root_specification(rir, request.param)
    # B computes its complete result before A executes: no A trace or payload
    # template is available to the independent Scenario driver.
    independent = reference_runtime_artifacts(reference_context, rir, specification)
    candidate = _PublicCandidate(
        tmp_path_factory.mktemp("mutual-runtime"),
        authorities=(kernel, reference_context.language_bundle),
    )
    candidate.write_source(_source())
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "55" * 32,
    )
    assert _members(build)["rir-semantic-payload"] == rir
    rir_path = candidate.directory / "independent-rir.json"
    rir_path.write_text(json.dumps(rir))
    path = candidate.directory / "experiment.json"
    path.write_text(json.dumps(specification))
    candidate.cli("experiment", "check", str(path), "--rir", str(rir_path))
    run = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        str(rir_path),
        "--out",
        str(candidate.directory / "run"),
        "--invocation-key",
        "56" * 32,
    )
    production = _members(run)
    context = admit_authority_context(kernel, reference_context.language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    Path(candidate.directory / "independent-artifacts.json").write_text(
        json.dumps(independent)
    )
    return reference_context, rir, specification, independent, production, checked


def test_both_consumers_admit_the_other_runtime_result(mutual_results):
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from schema2_runtime_independent_support import reference_admits_runtime_artifacts

    context, rir, specification, independent, production, checked = mutual_results
    assert set(independent) == {
        "evaluation-run",
        "event-trace",
        "snapshot-series",
        "metric-dataset",
        "resolved-runtime-profile",
        "evaluator-capability-manifest",
    }
    assert validate_experiment_artifact_set(checked, independent)
    assert reference_admits_runtime_artifacts(context, rir, specification, production)
    assert all(
        independent[name] == production[name]
        for name in independent
        if name != "evaluator-capability-manifest"
    )
    first_manifest = independent["evaluator-capability-manifest"]
    second_manifest = production["evaluator-capability-manifest"]
    assert first_manifest["implementation"] != second_manifest["implementation"]
    assert (
        first_manifest["evaluator_build_identity"]
        != second_manifest["evaluator_build_identity"]
    )
    assert set(first_manifest["effects"]) == {
        "event.commit",
        "snapshot.commit",
        "metric.observe",
    }
    events = independent["event-trace"]["events"]
    assert [
        event["root_event_ref"] for event in events if "root_event_ref" in event
    ] == ["early", "late"]
    assert [
        row["continuation"]["resource_ledger"]["node_steps"]
        for row in independent["snapshot-series"]["snapshots"]
    ] == [0, 46, 92, 92, 92]
    # Read authored list by resolved target instead of relying on assignment order.
    items = next(
        row["value"]["value"]
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "items"
    )
    ordered = sum(
        item * 10 ** (len(items) - index - 1) for index, item in enumerate(items)
    )
    observations = {
        sample["metric"]: sample["value"]
        for sample in independent["metric-dataset"]["samples"]
    }
    assert observations == {"ordered_value": ordered, "selected_count": 2}


@pytest.mark.parametrize(
    "mutation", ["state-value", "node-counter", "metric-value", "missing-capability"]
)
def test_independent_consumer_rejects_identity_valid_result_mutations(
    mutual_results, mutation
):
    from schema2_runtime_independent_support import reference_admits_runtime_artifacts
    from test_schema2_model_lowerer_conformance import _reference_artifact

    context, rir, specification, _, original, _ = mutual_results
    changed = deepcopy(original)
    if mutation == "state-value":
        changed["event-trace"]["events"][0]["state_after"][0]["value"] += 1
        name = "event-trace"
    elif mutation == "node-counter":
        changed["snapshot-series"]["snapshots"][1]["continuation"]["resource_ledger"][
            "node_steps"
        ] += 1
        name = "snapshot-series"
    elif mutation == "metric-value":
        changed["metric-dataset"]["samples"][0]["value"] += 1
        name = "metric-dataset"
    else:
        changed["evaluator-capability-manifest"]["instruction_nodes"].remove("fold")
        name = "evaluator-capability-manifest"
    changed[name] = _reference_artifact(
        context,
        name,
        {
            key: value
            for key, value in changed[name].items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        },
    )
    assert changed[name]["content_identity"] != original[name]["content_identity"]
    assert not reference_admits_runtime_artifacts(context, rir, specification, changed)


def test_reference_runtime_declines_unimplemented_input_phase(independent_fold):
    from schema2_runtime_independent_support import (
        IndependentRuntimeUnsupported,
        reference_runtime_artifacts,
    )

    _, context, rir = independent_fold
    specification = _two_root_specification(rir, [1, 2, 3, 4])
    root = specification["scenarios"][0]["event_plan"][0]
    root.clear()
    root.update(
        {
            "kind": "external-input",
            "root_event_ref": "authored-input",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + "b" * 64,
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.bounded-fold",
                        "module": "fold",
                        "name": "items",
                    },
                    "value": {
                        "type": {
                            "package": "standard.conformance.structured",
                            "id": "IntList4",
                        },
                        "value": [1, 2, 3, 4],
                    },
                }
            ],
        }
    )
    with pytest.raises(IndependentRuntimeUnsupported, match="only transition roots"):
        reference_runtime_artifacts(context, rir, specification)
