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
    kernel, context, rir = independent_fold
    return _exchange_results(
        kernel,
        context,
        rir,
        _two_root_specification(rir, request.param),
        _source(),
        tmp_path_factory.mktemp("mutual-runtime"),
    )


def _exchange_results(kernel, reference_context, rir, specification, source, directory):
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

    # B computes its complete result before A executes: no A trace or payload
    # template is available to the independent Scenario driver.
    independent = reference_runtime_artifacts(reference_context, rir, specification)
    candidate = _PublicCandidate(
        directory,
        authorities=(kernel, reference_context.language_bundle),
    )
    candidate.write_source(source)
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


def test_reference_runtime_declines_unimplemented_transition_payload(independent_fold):
    from schema2_runtime_independent_support import (
        IndependentRuntimeUnsupported,
        reference_runtime_artifacts,
    )

    _, context, rir = independent_fold
    specification = _two_root_specification(rir, [1, 2, 3, 4])
    specification["scenarios"][0]["event_plan"][0]["payload"] = [
        deepcopy(specification["scenarios"][0]["assignments"][0])
    ]
    with pytest.raises(IndependentRuntimeUnsupported, match="transition payloads"):
        reference_runtime_artifacts(context, rir, specification)


@pytest.mark.parametrize(
    "payload, admitted",
    [([], True), ([1, 2, 3, 4], True), ([1, 2, 3, 4, 5], False), ([True], False)],
)
def test_independent_structured_input_uses_selected_rir_closure(
    independent_fold, payload, admitted
):
    from schema2_bootstrap_conformance_support import (
        _consumer_b_evaluate_structured_value_vector,
    )

    _, _, rir = independent_fold
    result = _consumer_b_evaluate_structured_value_vector(
        {
            "input": {
                "action": "admit",
                "key": None,
                "left": {
                    "type": {
                        "package": "standard.conformance.structured",
                        "id": "IntList4",
                    },
                    "value": payload,
                },
                "right": None,
                "limit": None,
            }
        },
        selected_semantics=rir["selected_semantics"],
        resource_limit=1024,
    )
    assert (result["outcome"] == "admitted") is admitted


@pytest.mark.parametrize("missing", ["owner", "typed-profile"])
def test_independent_selected_type_admission_rejects_incomplete_closure(
    independent_fold, missing
):
    from schema2_bootstrap_conformance_support import (
        _consumer_b_evaluate_structured_value_vector,
    )

    _, _, rir = independent_fold
    selected = deepcopy(rir["selected_semantics"])
    if missing == "owner":
        selected["nominal_types"][0]["package"] = "undeclared.owner"
    else:
        selected["literal_typing_profiles"] = [
            row
            for row in selected["literal_typing_profiles"]
            if row["definition"]["source_kind"] != "typed-envelope"
        ]
    with pytest.raises(
        AssertionError, match="nominal definition|typed-envelope authority"
    ):
        _consumer_b_evaluate_structured_value_vector(
            {
                "input": {
                    "action": "admit",
                    "key": None,
                    "left": {
                        "type": {
                            "package": "standard.conformance.structured",
                            "id": "IntList4",
                        },
                        "value": [],
                    },
                    "right": None,
                    "limit": None,
                }
            },
            selected_semantics=selected,
            resource_limit=1024,
        )


@pytest.fixture(
    scope="module", params=[False, True], ids=["priority", "single-counter"]
)
def priority_mutual_results(tmp_path_factory, request):
    from priority_protocol_support import authorities, source, specification

    kernel, language, turn = authorities()
    authored = source(turn)
    context = _reference_check_source(authored, kernel, language)
    assert not isinstance(context, tuple), context
    rir = _reference_semantic_artifacts(context)["rir-semantic-payload"]
    return _exchange_results(
        kernel,
        context,
        rir,
        specification(rir, request.param),
        authored,
        tmp_path_factory.mktemp("priority-mutual"),
    )


def test_priority_six_members_cross_the_actual_runtime_boundary(
    priority_mutual_results,
):
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from schema2_runtime_independent_support import reference_admits_runtime_artifacts

    context, rir, specification, independent, production, checked = (
        priority_mutual_results
    )
    assert len(independent) == 6
    assert validate_experiment_artifact_set(checked, independent)
    assert reference_admits_runtime_artifacts(context, rir, specification, production)
    for name in independent:
        if name != "evaluator-capability-manifest":
            assert independent[name] == production[name], name
    expected = specification["metrics"][0]["target"]["minimum"]
    assert independent["metric-dataset"]["samples"][0]["value"] == expected
    assert expected in (0, 7)
    events = independent["event-trace"]["events"]
    roots = specification["scenarios"][0]["event_plan"]
    assert [
        event["root_event_ref"] for event in events if "root_event_ref" in event
    ] == [event["root_event_ref"] for event in roots]
    schedules = [row for event in events for row in event["schedules"]]
    assert len(schedules) == 1
    scheduled = next(event for event in events if "parent_event_id" in event)
    assert scheduled["event_id"] == schedules[0]["event_id"]
    assert scheduled["ordering_key"]["logical_time"] == 7
    captured = {row["name"]: row["value"] for row in schedules[0]["arguments"]}
    assert captured["status"]["value"] == "pending"
    assert len(captured["counters"]["value"]) == (2 if expected == 7 else 1)
    assert (
        independent["evaluator-capability-manifest"]["evaluator_build_identity"]
        != production["evaluator-capability-manifest"]["evaluator_build_identity"]
    )


@pytest.mark.parametrize(
    "mutation", ["nominal-owner", "quantity-domain", "source-sequence"]
)
def test_independent_priority_input_admission_has_no_value_defaults(
    priority_mutual_results, mutation
):
    from schema2_runtime_independent_support import reference_runtime_artifacts

    context, rir, original, _, _, _ = priority_mutual_results
    changed = deepcopy(original)
    if mutation == "source-sequence":
        changed["scenarios"][0]["event_plan"][0]["source_sequence"] = 1
        message = "source sequence"
    else:
        fact = next(
            row
            for event in changed["scenarios"][0]["event_plan"]
            for row in event.get("facts", [])
            if row["target"]["name"]
            == ("counter" if mutation == "nominal-owner" else "actor")
        )
        if mutation == "nominal-owner":
            fact["value"]["type"]["package"] = "undeclared.owner"
            message = "nominal owner"
        else:
            fact["value"] = 2
            message = "declared domain"
    with pytest.raises(ValueError, match=message):
        reference_runtime_artifacts(context, rir, changed)


@pytest.mark.parametrize("mutation", ["captured-value", "captured-state-reference"])
def test_independent_priority_consumer_checks_actual_scheduled_captures(
    priority_mutual_results, mutation
):
    from schema2_runtime_independent_support import reference_admits_runtime_artifacts
    from test_schema2_model_lowerer_conformance import _reference_artifact

    context, rir, specification, _, production, _ = priority_mutual_results
    changed = deepcopy(production)
    trace = changed["event-trace"]
    scheduled = next(row for event in trace["events"] for row in event["schedules"])
    catalog = next(
        row["event_spec"]
        for row in changed["snapshot-series"]["event_catalog"]
        if row["event_id"] == scheduled["event_id"]
    )
    if mutation == "captured-value":
        for rows in (scheduled["arguments"], catalog["arguments"]):
            next(row for row in rows if row["name"] == "power")["value"] += 1
    else:
        for rows in (scheduled["state_references"], catalog["state_references"]):
            next(row for row in rows if row["name"] == "power")["target"]["name"] = (
                "final_power"
            )
    fields = {
        key: value
        for key, value in trace.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    changed["event-trace"] = _reference_artifact(context, "event-trace", fields)
    assert not reference_admits_runtime_artifacts(context, rir, specification, changed)


@pytest.fixture(scope="module")
def renamed_effect_context():
    from priority_protocol_support import authorities, source
    from test_schema2_model_lowerer_conformance import _reidentify_language_bundle

    kernel, language, turn = authorities()
    names = {
        "event.commit": "renamed.effect.commit",
        "event.schedule": "renamed.effect.schedule",
        "metric.observe": "renamed.effect.observe",
        "snapshot.commit": "renamed.effect.snapshot",
    }

    def replace(value):
        if isinstance(value, dict):
            for key, item in value.items():
                value[key] = replace(item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = replace(item)
        elif isinstance(value, str):
            return names.get(value, value)
        return value

    replace(language)
    _reidentify_language_bundle(language)
    assert _consumer_b(kernel, language)["admitted"]
    context = _reference_check_source(source(turn), kernel, language)
    assert not isinstance(context, tuple), context
    rir = _reference_semantic_artifacts(context)["rir-semantic-payload"]
    return context, rir, names


@pytest.mark.parametrize("variant", [False, True])
def test_independent_runtime_effect_capabilities_follow_supported_programs(
    renamed_effect_context, variant
):
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from gda_balancing.domain.model import AdmittedRir, admit_rir
    from priority_protocol_support import specification
    from schema2_runtime_independent_support import reference_runtime_artifacts

    context, rir, names = renamed_effect_context
    spec = specification(rir, variant)
    artifacts = reference_runtime_artifacts(context, rir, spec)
    assert artifacts["evaluator-capability-manifest"]["effects"] == sorted(
        names.values()
    )
    assert artifacts["metric-dataset"]["samples"][0]["value"] == (0 if variant else 7)
    assert (
        len(
            [
                row
                for event in artifacts["event-trace"]["events"]
                for row in event["schedules"]
            ]
        )
        == 1
    )
    # A consumes B's real renamed result; no A-produced trace is used to emit it.
    authority = admit_authority_context(context.kernel, context.language_bundle)
    assert isinstance(authority, AdmittedAuthorityContext), authority
    program = admit_rir(rir, authority_context=authority)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(spec, program, authority_context=authority)
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, artifacts)
