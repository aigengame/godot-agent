"""Metric wire derives from fixed owners; complete evidence determines outcomes."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest
from jsonschema import Draft202012Validator

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.metric_projection import metric_outcome_schema
from gda_balancing.domain.authority.replay_projection import replay_comparison_schema
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from schema2_authority_support import (
    mutable_authorities,
    refresh_package_semantic_closures,
)
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_metric_outcome_schema,
    _encoded,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from schema2_runtime_independent_support import (
    reference_admits_runtime_artifacts,
    reference_runtime_artifacts,
)
from test_bounded_fold_public import _source, _specification
from test_current_namespace_public import _PublicCandidate, _members
from test_receipt_protocol_structure import _definitions
from test_rir_protocol_structure_independent import _raw_language
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _authored, _graph, _index


_ROLES = ("metric-dataset", "evaluation-run", "experiment-verdict")


def _rows(authored, role):
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == role
    )
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def _rename(authored):
    for index, role in enumerate(_ROLES):
        schema, contract = _rows(authored, role)
        old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
        schema["artifact_kind"] = contract["schema_kind"] = f"metric.schema.{index}"
        contract["artifact_kind"] = f"metric.result.{index}"
        for package in authored["packages"]:
            for collection, old, new in (
                ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
                ("artifact_contracts", old_kind, contract["artifact_kind"]),
            ):
                package["exports"][collection] = [
                    new if value == old else value
                    for value in package["exports"][collection]
                ]


@pytest.mark.parametrize("role", _ROLES)
def test_metric_outcome_wire_has_no_independent_authored_schema(role):
    _, language = mutable_authorities()
    assert set(_rows(_authored(language), role)[0]) == {
        "artifact_kind",
        "protocol_role",
    }


@pytest.mark.parametrize("role", _ROLES)
@pytest.mark.parametrize("rename", [False, True], ids=["same-schema", "renamed-field"])
def test_metric_outcome_schema_override_is_not_erased_or_admitted(role, rename):
    kernel, ldb = mutable_authorities()
    definition = next(
        row
        for row in ldb["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == role
    )
    if rename:
        field = "samples" if role == "metric-dataset" else "outcome"
        schema = definition["schema"]
        schema["properties"]["forged_field"] = schema["properties"].pop(field)
        schema["required"] = [
            "forged_field" if name == field else name for name in schema["required"]
        ]
        # Fixture transport may strip only exact legal projections, never this
        # coherently changed schema merely because its protocol role is known.
    refresh_package_semantic_closures(ldb, kernel)
    authored = _authored(ldb)
    # refresh updates the derived index's selected package closures. Graph
    # resealing below transports those edits into the attached physical graph.
    authored["packages"] = deepcopy(ldb["language"]["packages"])
    if rename:
        assert _rows(authored, role)[0]["schema"] == definition["schema"]
    else:
        assert "schema" not in _rows(authored, role)[0]
        _rows(authored, role)[0]["schema"] = deepcopy(definition["schema"])
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


@pytest.mark.parametrize("role", _ROLES)
def test_metric_outcome_schemas_are_independent_and_detached(role, monkeypatch):
    kernel, ldb = mutable_authorities()
    raw = _raw_language(ldb)
    before = _encoded([kernel, raw])
    actual = metric_outcome_schema(kernel, raw, role, "actual.result")
    expected = _consumer_b_metric_outcome_schema(kernel, raw, role, "actual.result")
    assert _encoded(actual) == _encoded(expected)
    actual["required"].clear()
    if role == "metric-dataset":
        actual["properties"]["samples"]["items"]["properties"]["value"]["type"] = (
            "string"
        )
    else:
        actual["properties"]["terminal_statuses"]["items"]["required"].clear()
    assert _encoded([kernel, raw]) == before

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B called the production Metric projection")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.metric_projection.metric_outcome_schema",
        unavailable,
    )
    assert _encoded(
        _consumer_b_metric_outcome_schema(kernel, raw, role, "actual.result")
    ) == _encoded(expected)
    assert _consumer_b(kernel, _graph(kernel, _authored(ldb)))["admitted"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-field",
        "duplicate-required",
        "duplicate-binding",
        "duplicate-observation",
        "duplicate-terminal",
        "duplicate-role",
        "missing-trace",
    ],
)
def test_metric_projection_refuses_incomplete_or_duplicate_owners(mutation):
    kernel, ldb = mutable_authorities()
    raw = _raw_language(ldb)
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "metric_outcome_structure"
    ]
    role = "metric-dataset"
    if mutation == "missing-field":
        del law["dataset"]["field_types"]["partition"]
    elif mutation == "duplicate-required":
        law["dataset"]["required_members"].append("samples")
    elif mutation == "duplicate-binding":
        law["bindings"]["samples"] = {"type": "list"}
    elif mutation == "duplicate-observation":
        law["sample"]["field_types"]["value"] = {"type": "integer"}
    elif mutation == "duplicate-terminal":
        role = "evaluation-run"
        law["primary"]["field_types"]["terminal_statuses"] = {"type": "list"}
    else:
        trace = next(
            row
            for row in raw["artifact_wire_schemas"]
            if row.get("protocol_role") == "event-trace"
        )
        if mutation == "duplicate-role":
            raw["artifact_wire_schemas"].append(deepcopy(trace))
        else:
            raw["artifact_wire_schemas"].remove(trace)
    for projector in (metric_outcome_schema, _consumer_b_metric_outcome_schema):
        with pytest.raises(ValueError):
            projector(kernel, raw, role, "actual.result")


def test_metric_inventory_retains_variable_bindings_without_ghost_schema_coverage():
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _rename(authored)
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    for index, role in enumerate(_ROLES):
        token = AuthorityToken(
            "language.artifact_wire_schemas", (), f"metric.schema.{index}"
        )
        assert token in inventory.tokens - inventory.reserved
        occurrence = next(
            o
            for o in inventory.occurrences
            if o.token == token and o.use == "declaration"
        )
        pointer = occurrence.pointer.removesuffix("/artifact_kind")
        assert not any(g.pointer == pointer for g in inventory.uncovered)
        assert not any(
            o.pointer.startswith(pointer + "/schema/") for o in inventory.occurrences
        )
        link = next(
            o
            for o in inventory.occurrences
            if o.token == token and o.pointer.endswith("/schema_kind")
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(
                kernel,
                authored,
                replace(
                    inventory,
                    occurrences=tuple(o for o in inventory.occurrences if o != link),
                ),
            )
    assert inventory.uncovered  # This slice does not close other artifact owners.


@pytest.fixture(
    scope="module", params=[True, False], ids=["accepted", "business-rejected"]
)
def metric_exchange(request):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _rename(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    source = _source()
    index = _index(kernel, graph)
    reference = _reference_check_source(source, kernel, index)
    assert not isinstance(reference, tuple), reference
    rir = _reference_semantic_artifacts(reference)["rir-semantic-payload"]
    specification = _specification(rir, [1, 2, 3, 4])
    if not request.param:
        specification["metrics"][1]["target"] = {"minimum": 0, "maximum": 0}
    independent = reference_runtime_artifacts(reference, rir, specification)
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext), context
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    outcome = evaluate_experiment(checked)
    assert isinstance(outcome, EvaluationArtifacts), outcome
    assert outcome.accepted is request.param
    production = {
        name: deepcopy(member.value) for name, member in outcome.members.items()
    }
    return kernel, graph, reference, checked, independent, production, request.param


def test_both_metric_outcomes_mutually_admit_real_execution(metric_exchange):
    kernel, _graph_value, reference, checked, independent, production, accepted = (
        metric_exchange
    )
    assert validate_experiment_artifact_set(checked, independent)
    assert validate_experiment_artifact_set(checked, production)
    assert reference_admits_runtime_artifacts(
        reference, checked.rir, checked.value, production
    )
    assert all(
        independent[name] == production[name]
        for name in independent
        if name != "evaluator-capability-manifest"
    )
    primary = "evaluation-run" if accepted else "experiment-verdict"
    assert production[primary]["outcome"] == ("accepted" if accepted else "rejected")
    assert ("failed_metrics" in production[primary]) is (not accepted)
    comparison = replay_comparison_schema(
        kernel, reference.language_bundle["language"], "actual.comparison"
    )
    assert comparison["properties"]["replay_outcome_kind"]["enum"] == [
        "metric.result.1",
        "metric.result.2",
    ]
    assert comparison["properties"]["original_observation"]["properties"][
        "evaluation_outcome_status"
    ]["enum"] == ["accepted", "rejected"]
    for role in ("metric-dataset", primary):
        Draft202012Validator(
            _consumer_b_metric_outcome_schema(
                kernel,
                reference.language_bundle["language"],
                role,
                production[role]["artifact_kind"],
            )
        ).validate(production[role])


def _raw_reseal(checked, members, name):
    value = members[name]
    definition = checked.output_contracts[name].definition
    excluded = set(definition["identity_excluded_members"]) | {"content_identity"}
    value["content_identity"] = content_identity(
        definition["identity_domain"],
        {k: v for k, v in value.items() if k not in excluded},
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "data_version",
        "partition",
        "ordering",
        "ingestion_transformation_identity",
        "value",
        "provenance",
        "target",
        "primary",
    ],
)
def test_coordinated_reseal_does_not_replace_metric_evidence(metric_exchange, mutation):
    _kernel, _graph_value, reference, checked, _independent, production, accepted = (
        metric_exchange
    )
    changed = deepcopy(production)
    dataset = changed["metric-dataset"]
    primary = "evaluation-run" if accepted else "experiment-verdict"
    if mutation in {
        "data_version",
        "partition",
        "ordering",
        "ingestion_transformation_identity",
    }:
        dataset[mutation] = "other-version" if mutation == "data_version" else "forged"
    elif mutation == "value":
        dataset["samples"][0]["value"] += 1
    elif mutation == "provenance":
        dataset["samples"][0]["provenance"]["observation_name"] = "forged"
    elif mutation == "target":
        dataset["samples"][0]["within_target"] = not dataset["samples"][0][
            "within_target"
        ]
    else:
        if accepted:
            wrong = changed.pop(primary)
            primary = "experiment-verdict"
            wrong.update(
                outcome="rejected", failed_metrics=[dataset["samples"][0]["metric"]]
            )
        else:
            wrong = changed.pop(primary)
            primary = "evaluation-run"
            wrong.update(outcome="accepted")
            del wrong["failed_metrics"]
        wrong["artifact_kind"] = checked.output_contracts[primary].definition[
            "artifact_kind"
        ]
        wrong["wire_schema_identity"] = checked.output_contracts[
            primary
        ].wire_schema_identity
        changed[primary] = wrong
    _raw_reseal(checked, changed, "metric-dataset")
    changed[primary]["metric_dataset_identity"] = dataset["content_identity"]
    _raw_reseal(checked, changed, primary)
    if mutation in {"value", "provenance", "target", "primary"}:
        assert all(
            checked.output_contracts[role].verify(value)
            for role, value in changed.items()
        )
    # All content identities have been coherently rebuilt from the actual
    # selected contracts. Member checks alone cannot establish Metric truth.
    assert not validate_experiment_artifact_set(checked, changed)
    assert not reference_admits_runtime_artifacts(
        reference, checked.rir, checked.value, changed
    )


def test_public_metric_outcomes_and_authenticated_replay_keep_distinct_kinds(
    metric_exchange, tmp_path
):
    kernel, graph, _reference, checked, _independent, production, accepted = (
        metric_exchange
    )
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(_source())
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "c1" * 32,
    )
    assert _members(build)["rir-semantic-payload"] == checked.rir
    rir_path = tmp_path / "rir.json"
    rir_path.write_bytes(canonical_bytes(checked.rir))
    spec_path = tmp_path / "experiment.json"
    spec_path.write_bytes(canonical_bytes(checked.value))
    candidate.cli("experiment", "check", str(spec_path), "--rir", str(rir_path))
    run = candidate.cli(
        "experiment",
        "run",
        str(spec_path),
        "--rir",
        str(rir_path),
        "--out",
        str(tmp_path / "run.json"),
        "--invocation-key",
        "c2" * 32,
        success=accepted,
    )
    receipt = run if accepted else run["artifact_set"]
    actual = _members(receipt)
    assert validate_experiment_artifact_set(checked, actual)
    assert actual["metric-dataset"] == production["metric-dataset"]
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    result = candidate.cli(
        "experiment",
        "replay",
        str(spec_path),
        "--rir",
        str(rir_path),
        "--original-experiment-run-artifact-set-receipt",
        str(receipt_path),
        "--out",
        str(tmp_path / "replay.json"),
        "--invocation-key",
        "c3" * 32,
        success=accepted,
    )
    if not accepted:
        assert candidate.receipts[-1]["returncode"] == 2
        assert [row["code"] for row in result["error"]["diagnostics"]] == [
            "evaluation.replay_ineligible_outcome"
        ]
        assert not (tmp_path / "replay.json").exists()
        return
    replay = json.loads((tmp_path / "replay.json").read_bytes())
    assert replay["result"] == "matched"
    assert (
        replay["replay_outcome_kind"]
        == production["evaluation-run" if accepted else "experiment-verdict"][
            "artifact_kind"
        ]
    )
