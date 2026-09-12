"""Experiment input composes existing owners and selects explicit judgments."""

from copy import deepcopy

import pytest
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.experiment_projection import experiment_input_schema
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from gda_balancing.domain.runtime.projections import resolved_runtime_profile
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_experiment_input_schema,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_runtime_independent_support import (
    IndependentRuntimeUnsupported,
    reference_admits_runtime_artifacts,
    reference_runtime_artifacts,
)
from test_bounded_fold_public import _build, _check, _run, _source, _specification
from test_current_namespace_public import _members, _PublicCandidate
from test_schema2_model_lowerer_conformance import _reference_check_source
from test_trace_protocol_structure import _authored, _graph, _index


def _spec(rir, *, order=1234):
    value = deepcopy(_specification(rir, [1, 2, 3, 4], order=order))
    return value


def test_experiment_input_has_no_authored_schema():
    _, ldb = mutable_authorities()
    definition = next(
        row
        for package in _authored(ldb)["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_wire_schemas"
        for row in closure["definitions"]
        if row.get("protocol_role") == "experiment-specification"
    )
    assert "schema" not in definition


def test_public_experiment_derives_requirements(tmp_path):
    candidate = _PublicCandidate(tmp_path)
    rir_path, rir = _build(candidate)
    path, _ = _check(candidate, rir_path, _spec(rir))
    _run(candidate, rir_path, path)


@pytest.fixture(scope="module")
def program_data(tmp_path_factory):
    kernel, language = mutable_authorities()
    graph = _graph(kernel, _authored(language))
    candidate = _PublicCandidate(
        tmp_path_factory.mktemp("experiment-owner"), authorities=(kernel, graph)
    )
    _, rir = _build(candidate)
    return kernel, _authored(language), rir


def _checked(kernel, authored, rir, value):
    graph = _graph(kernel, deepcopy(authored))
    for consumer in (_consumer_a, _consumer_b):
        admitted = consumer(kernel, graph)
        assert admitted["admitted"], admitted
    language = _index(kernel, graph)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    return (
        check_experiment_value(value, program, authority_context=context),
        graph,
        language,
    )


def _definitions(authored, collection):
    return [
        row
        for package in authored["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language." + collection
        for row in entry["definitions"]
    ]


@pytest.mark.parametrize(
    "field",
    ["schema_version", "required_evaluator", "named_streams", "scenario_streams"],
)
def test_deleted_input_fact_is_rejected_without_fallback(program_data, field):
    kernel, authored, rir = program_data
    specification = _spec(rir)
    if field == "schema_version":
        specification[field] = "2.0.0"
    elif field == "scenario_streams":
        specification[field] = {}
    elif field == "required_evaluator":
        specification["runtime"][field] = {}
    else:
        specification["scenarios"][0][field] = []
    checked, _, _ = _checked(kernel, authored, rir, specification)
    assert not isinstance(checked, CheckedExperiment)
    assert checked.stage == "static"


@pytest.mark.parametrize(
    "path",
    [
        ("kind",),
        ("aggregation",),
        ("replication", "unit"),
        ("missing",),
        ("censoring",),
        ("window", "kind"),
        ("observation", "source"),
    ],
)
def test_unimplemented_metric_discriminator_does_not_silently_execute(
    program_data, path
):
    kernel, authored, rir = program_data
    specification = _spec(rir)
    value = specification["metrics"][0]
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = "unimplemented"
    checked, _, _ = _checked(kernel, authored, rir, specification)
    assert not isinstance(checked, CheckedExperiment)
    assert checked.stage == "resolution"


@pytest.mark.parametrize("mutation", ["missing", "unknown"])
def test_acceptance_is_explicit_and_resolves_a_unique_judgment(program_data, mutation):
    kernel, authored, rir = program_data
    specification = _spec(rir)
    if mutation == "missing":
        del specification["acceptance"]
    else:
        specification["acceptance"]["policy"] = "unimplemented"
    checked, _, _ = _checked(kernel, authored, rir, specification)
    assert not isinstance(checked, CheckedExperiment)


@pytest.mark.parametrize("renamed", [False, True])
def test_authority_cannot_override_experiment_wire_even_with_equal_schema(
    program_data, renamed
):
    kernel, source, _ = program_data
    authored = deepcopy(source)
    definition = next(
        row
        for row in _definitions(authored, "artifact_wire_schemas")
        if row.get("protocol_role") == "experiment-specification"
    )
    schema = experiment_input_schema(kernel)
    if renamed:
        schema["properties"]["renamed_scenarios"] = schema["properties"].pop(
            "scenarios"
        )
        schema["required"] = [
            "renamed_scenarios" if value == "scenarios" else value
            for value in schema["required"]
        ]
    definition["schema"] = schema
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, graph)["admitted"]


@pytest.mark.parametrize("mutation", ["operator", "sample-member", "result-role"])
def test_acceptance_record_has_closed_machine_meaning(program_data, mutation):
    kernel, source, _ = program_data
    authored = deepcopy(source)
    judgment = _definitions(authored, "experiment_acceptance_judgments")[0]
    if mutation == "operator":
        judgment["operator"] = "any"
    elif mutation == "sample-member":
        judgment["sample_member"] = "value"
    else:
        judgment["outcomes"] = {"true": "evaluation-run", "false": "experiment-verdict"}
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, graph)["admitted"]


def test_metric_matching_refuses_two_interpretations(program_data):
    kernel, source, rir = program_data
    authored = deepcopy(source)
    for package in authored["packages"]:
        entry = next(
            row
            for row in package["semantic_closure"]
            if row["authority_path"] == "language.experiment_metric_judgments"
        )
        if entry["definitions"]:
            duplicate = deepcopy(
                next(
                    row
                    for row in entry["definitions"]
                    if row["operator"] == "single-terminal-integer"
                )
            )
            duplicate["id"] = "another-selected-meaning"
            entry["definitions"].append(duplicate)
            package["exports"]["experiment_metric_judgments"].append(duplicate["id"])
    checked, _, language = _checked(kernel, authored, rir, _spec(rir))
    assert not isinstance(checked, CheckedExperiment)
    reference = _reference_check_source(_source(), kernel, language)
    assert not isinstance(reference, tuple)
    with pytest.raises(ValueError, match="selection is not unique"):
        reference_runtime_artifacts(reference, rir, _spec(rir))


@pytest.mark.parametrize("order", [1234, 1235])
def test_actual_accepted_and_rejected_results_use_selected_judgments(
    program_data, order
):
    kernel, authored, rir = program_data
    specification = _spec(rir, order=order)
    checked, _, language = _checked(kernel, authored, rir, specification)
    assert isinstance(checked, CheckedExperiment)
    result = evaluate_experiment(checked)
    assert isinstance(result, EvaluationArtifacts)
    assert result.accepted is (order == 1234)
    artifacts = {name: dict(member.value) for name, member in result.members.items()}
    assert validate_experiment_artifact_set(checked, artifacts)
    reference = _reference_check_source(_source(), kernel, language)
    assert not isinstance(reference, tuple)
    assert reference_admits_runtime_artifacts(reference, rir, specification, artifacts)
    independent = reference_runtime_artifacts(reference, rir, specification)
    assert validate_experiment_artifact_set(checked, independent)
    assert (
        resolved_runtime_profile(checked).value["experiment_judgments"]
        == checked.experiment_judgments
    )


def test_changed_metric_operator_changes_existing_profile_and_refuses_old_evidence(
    program_data,
):
    kernel, source, rir = program_data
    specification = _spec(rir)
    original, _, _ = _checked(kernel, source, rir, specification)
    assert isinstance(original, CheckedExperiment)
    result = evaluate_experiment(original)
    assert isinstance(result, EvaluationArtifacts)
    authored = deepcopy(source)
    selected = next(
        row
        for row in _definitions(authored, "experiment_metric_judgments")
        if row["operator"] == "single-terminal-integer"
    )
    selected["operator"] = "single-event-integer"
    changed, _, language = _checked(kernel, authored, rir, specification)
    assert isinstance(changed, CheckedExperiment)
    assert changed.content_identity == original.content_identity
    assert changed.rir == original.rir
    assert (
        resolved_runtime_profile(changed).content_identity
        != resolved_runtime_profile(original).content_identity
    )
    assert not validate_experiment_artifact_set(
        changed, {name: dict(member.value) for name, member in result.members.items()}
    )
    refused = evaluate_experiment(changed)
    assert isinstance(refused, Schema2RefusalReport)
    assert refused.stage == "evaluation"
    reference = _reference_check_source(_source(), kernel, language)
    assert not isinstance(reference, tuple)
    with pytest.raises(IndependentRuntimeUnsupported, match="Metric projection"):
        reference_runtime_artifacts(reference, rir, specification)


def test_public_judgment_and_discriminator_renaming_preserves_real_meaning(
    program_data, tmp_path
):
    kernel, source, rir = program_data
    authored = deepcopy(source)
    specification = _spec(rir)
    for package in authored["packages"]:
        for entry in package["semantic_closure"]:
            collection = entry["authority_path"].removeprefix("language.")
            if collection not in {
                "experiment_metric_judgments",
                "experiment_acceptance_judgments",
            }:
                continue
            for judgment in entry["definitions"]:
                old = judgment["id"]
                judgment["id"] = "renamed." + old
                package["exports"][collection] = [
                    judgment["id"] if value == old else value
                    for value in package["exports"][collection]
                ]
                if collection == "experiment_acceptance_judgments":
                    specification["acceptance"]["policy"] = judgment["id"]
                else:
                    for path in [
                        ("kind",),
                        ("aggregation",),
                        ("replication", "unit"),
                        ("missing",),
                        ("censoring",),
                        ("window", "kind"),
                        ("observation", "source"),
                    ]:
                        value = judgment["selector"]
                        for key in path[:-1]:
                            value = value[key]
                        value[path[-1]] = "renamed." + value[path[-1]]
    for metric in specification["metrics"]:
        for path in [
            ("kind",),
            ("aggregation",),
            ("replication", "unit"),
            ("missing",),
            ("censoring",),
            ("window", "kind"),
            ("observation", "source"),
        ]:
            value = metric
            for key in path[:-1]:
                value = value[key]
            value[path[-1]] = "renamed." + value[path[-1]]
    checked, graph, language = _checked(kernel, authored, rir, specification)
    assert isinstance(checked, CheckedExperiment)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    rir_path, rebuilt = _build(candidate)
    assert rebuilt == rir
    path, _ = _check(candidate, rir_path, specification)
    receipt = _run(candidate, rir_path, path)
    reference = _reference_check_source(_source(), kernel, language)
    assert not isinstance(reference, tuple)
    assert reference_admits_runtime_artifacts(
        reference, rir, specification, _members(receipt)
    )


def test_independent_input_projection_does_not_use_production_oracle(
    program_data, monkeypatch
):
    kernel, authored, _ = program_data
    expected = experiment_input_schema(kernel)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B used production Experiment projection")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.experiment_projection.experiment_input_schema",
        unavailable,
    )
    assert _consumer_b_experiment_input_schema(kernel) == expected
    assert _consumer_b(kernel, _graph(kernel, deepcopy(authored)))["admitted"]
