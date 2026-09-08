"""Current RIR has one complete protocol owner, with public and hostile inputs."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from gda_balancing.domain.artifacts import artifacts_by_protocol_role
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.rir_projection import rir_protocol_schema
from gda_balancing.domain.authority.trace_projection import trace_protocol_schema
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.formula.types import resolve_formula_contract
from gda_balancing.domain.model import AdmittedRir, RirAdmissionError, admit_rir
from gda_balancing.domain.model._lowering import _identified_rir_artifact
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _consumer_b_rir_schema
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph, _index


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast"


def _definitions(authored, path):
    return [
        definition
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == path
        for definition in closure["definitions"]
    ]


def _renamed(authored):
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == "rir-semantic-payload"
    )
    old_schema = schema["artifact_kind"]
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == old_schema
    )
    old_kind = contract["artifact_kind"]
    schema["artifact_kind"] = "opaque.rir.schema"
    contract["schema_kind"] = schema["artifact_kind"]
    contract["artifact_kind"] = "opaque.rir.artifact"
    for package in authored["packages"]:
        for key, old, new in [
            ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
            ("artifact_contracts", old_kind, contract["artifact_kind"]),
        ]:
            package["exports"][key] = [
                new if value == old else value for value in package["exports"][key]
            ]
    counts = []
    for lowering in _definitions(authored, "language.model_lowerings"):
        projection = lowering["runtime_projection"]
        names = {
            row["id"]: "opaque.collection." + str(i)
            for i, row in enumerate(projection["collections"])
        }
        counts.append(len(names))
        reference_closure = projection["type_reference_closure"]
        for key in (
            "source_collection",
            "target_constructor_collection",
            "target_type_collection",
        ):
            reference_closure[key] = names[reference_closure[key]]
        for row in projection["collections"]:
            row["id"] = names[row["id"]]
        projection["operation_roots"]["collection"] = names[
            projection["operation_roots"]["collection"]
        ]
        for row in projection["seeds"]:
            row["collection"] = names[row["collection"]]
        for row in projection["edges"]:
            for key in ("source_collection", "target_collection"):
                row[key] = names[row[key]]
    assert counts == [16]


@pytest.fixture(
    scope="module", params=[False, True], ids=["original", "kinds-and-collections"]
)
def public_rir(request, tmp_path_factory):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    if request.param:
        _renamed(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert observation["admitted"], observation["diagnostics"]
    language = _index(kernel, graph)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    directory = tmp_path_factory.mktemp("rir-protocol-public")
    candidate = _PublicCandidate(directory, authorities=(kernel, language))
    candidate.write_source(json.loads((_EXAMPLE / "model-source.json").read_text()))
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(directory / "build"),
        "--invocation-key",
        "b4" * 32,
    )
    built = artifacts_by_protocol_role(language, _members(receipt))
    assert len(built) == 8
    rir = built["rir-semantic-payload"]
    assert rir["artifact_kind"] == (
        "opaque.rir.artifact" if request.param else "rir-semantic-payload"
    )
    expected_schema = _consumer_b_rir_schema(kernel, language, rir["artifact_kind"])
    assert canonical_bytes(expected_schema) == canonical_bytes(
        rir_protocol_schema(kernel, language, rir["artifact_kind"])
    )
    jsonschema.Draft202012Validator(expected_schema).validate(rir)
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    # Existing maintained binding detects unintended changes in executed semantics.
    specification = json.loads((_EXAMPLE / "experiment.json").read_text())
    assert specification["model"]["rir_semantic_identity"] == rir["semantic_identity"]
    path = directory / "rir.json"
    path.write_text(json.dumps(rir))
    spec_path = directory / "experiment.json"
    spec_path.write_text(json.dumps(specification))
    assert candidate.cli("experiment", "check", str(spec_path), "--rir", str(path))[
        "checked"
    ]
    run = candidate.cli(
        "experiment",
        "run",
        str(spec_path),
        "--rir",
        str(path),
        "--out",
        str(directory / "run"),
        "--invocation-key",
        "b5" * 32,
    )
    artifacts = artifacts_by_protocol_role(language, _members(run))
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, artifacts)
    assert all(row["within_target"] for row in artifacts["metric-dataset"]["samples"])
    return context, rir, expected_schema, artifacts


def test_public_current_composition_survives_kind_and_collection_names(public_rir):
    _, rir, _, artifacts = public_rir
    assert rir["initialization_programs"][0]["body"]
    assert rir["call_sites"]
    assert artifacts["event-trace"]["events"]
    assert artifacts["metric-dataset"]["samples"]


@pytest.mark.parametrize(
    "mutation", ["maximum", "expression-call", "missing-operand", "boolean-limit"]
)
def test_imported_rir_rejects_obsolete_or_malformed_nested_wire(public_rir, mutation):
    context, rir, schema, _ = public_rir
    forged = deepcopy(rir)
    if mutation == "maximum":
        instruction = forged["initialization_programs"][0]["body"][0]["instruction"]
        instruction["node"] = "maximum"
    elif mutation == "expression-call":
        operand = forged["call_sites"][0]["arguments"][0]["operand"]
        operand.clear()
        operand.update({"kind": "expression", "name": "obsolete-expression"})
    elif mutation == "missing-operand":
        del forged["call_sites"][0]["arguments"][0]["operand"]
    else:
        forged["entrypoints"][0]["resource_bounds"]["max_steps"] = True
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(forged))
    with pytest.raises(RirAdmissionError, match="admitted semantics"):
        admit_rir(forged, authority_context=context)


def test_correctly_reidentified_rir_still_requires_selected_operation_closure(
    public_rir,
):
    context, rir, schema, _ = public_rir
    payload = deepcopy(rir)
    payload["entrypoints"][0]["operation"]["id"] = "absent-operation"
    forged = _identified_rir_artifact(context.language_bundle, payload)
    jsonschema.Draft202012Validator(schema).validate(forged)
    assert forged["semantic_identity"] != rir["semantic_identity"]
    with pytest.raises(RirAdmissionError, match="admitted semantics"):
        admit_rir(forged, authority_context=context)


@pytest.mark.parametrize(
    "obsolete",
    [
        "raw-schema",
        "identity-projection",
        "declaration-output",
        "collection-output",
        "output-recipes",
    ],
)
def test_removed_ldb_structural_settings_are_refused_without_aliases(obsolete):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == "rir-semantic-payload"
    )
    lowering = _definitions(authored, "language.model_lowerings")[0]
    assert "schema" not in schema and "output_member" not in lowering
    projection = lowering["runtime_projection"]
    assert "outputs" not in projection
    assert all(
        not {"output_member", "output_shape"} & row.keys()
        for row in projection["collections"]
    )
    if obsolete == "raw-schema":
        schema["schema"] = rir_protocol_schema(kernel, ldb, "rir-semantic-payload")
    elif obsolete == "identity-projection":
        contract = next(
            row
            for row in _definitions(authored, "language.artifact_contracts")
            if row["schema_kind"] == schema["artifact_kind"]
        )
        contract["semantic_identity_projection"] = deepcopy(
            kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
                "rir_structure"
            ]["semantic_projection"]
        )
    elif obsolete == "declaration-output":
        lowering["output_member"] = "declarations"
    elif obsolete == "collection-output":
        projection["collections"][0]["output_member"] = "types"
    else:
        projection["outputs"] = []
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (obsolete, result)


def _reverse_objects(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            name: _reverse_objects(child)
            for name, child in reversed(list(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_objects(child) for child in value]
    return value


def test_independent_derived_schema_identity_ignores_object_insertion_order():
    kernel, language = mutable_authorities()
    original = rir_protocol_schema(kernel, language, "rir-semantic-payload")
    for project in (rir_protocol_schema, _consumer_b_rir_schema):
        reordered = project(
            _reverse_objects(kernel), _reverse_objects(language), "rir-semantic-payload"
        )
        assert canonical_bytes(reordered) == canonical_bytes(original)


def test_shared_formula_reference_and_fixed_alias_use_existing_owners():
    kernel, language = mutable_authorities()
    roles = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"]
    assert "formula_reference" not in roles["rir_structure"]["containers"]
    assert (
        "formula"
        not in roles["trace_structure"]["event"]["field_types"]["formula_evaluations"][
            "items"
        ]["field_types"]
    )
    schema = rir_protocol_schema(kernel, language, "rir-semantic-payload")
    trace_reference = trace_protocol_schema(kernel, "event-trace")["properties"][
        "events"
    ]["items"]["properties"]["formula_evaluations"]["items"]["properties"]["formula"]
    references = schema["properties"]["formula_bindings"]["items"]["properties"][
        "formula"
    ]
    assert canonical_bytes(references) == canonical_bytes(trace_reference)
    policy = next(
        row for row in language["language"]["resolution_profiles"] if row["default"]
    )["formula_resolution"]
    alias = policy["fixed_value_type_aliases"][0]
    fixed = deepcopy(
        kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
            alias["contract"]
        ]
    )
    source = {**fixed, "type": alias["alias"]}
    resolved = resolve_formula_contract(source, {}, kernel, policy)
    result_schema = schema["properties"]["formulas"]["items"]["properties"]["result"]
    jsonschema.Draft202012Validator(result_schema).validate(resolved)
    for unknown in ("absent-alias", "Boolean-but-unselected"):
        with pytest.raises(ValueError, match="unresolved"):
            resolve_formula_contract({**source, "type": unknown}, {}, kernel, policy)
    malformed = deepcopy(resolved)
    assert isinstance(malformed["type_identity"], dict)
    malformed["type_identity"]["id"] = "absent-fixed-type"
    assert list(jsonschema.Draft202012Validator(result_schema).iter_errors(malformed))


def test_generated_schema_sorting_keeps_const_and_enum_payload_order():
    from gda_balancing.domain.authority.contract_projection import (
        ordered_protocol_schema,
    )

    kernel, _ = mutable_authorities()
    data = {"required": ["z", "a"], "body": [2, 1]}
    original = {
        "required": ["z", "a"],
        "properties": {
            "a": {"const": data},
            "schema": data,
            "z": {"enum": [data, {"required": ["a", "z"], "body": [1, 2]}]},
        },
        "oneOf": [{"const": 1}, {"const": 1}],
    }
    result = ordered_protocol_schema(kernel, original)
    assert result["required"] == ["a", "z"]
    assert result["properties"]["a"]["const"] == data
    assert result["properties"]["schema"]["required"] == ["a", "z"]
    assert data in result["properties"]["z"]["enum"]
    assert result["oneOf"] == [{"const": 1}, {"const": 1}]
    assert original["required"] == ["z", "a"]


@pytest.mark.parametrize(
    "project",
    [rir_protocol_schema, _consumer_b_rir_schema],
    ids=["production", "independent"],
)
def test_rir_projection_follows_default_resolution_profile_without_single_row_fallback(
    project,
):
    kernel, ldb = mutable_authorities()
    baseline = project(kernel, ldb, "rir")
    candidate = deepcopy({"language": ldb["language"]})
    profile = next(
        row for row in candidate["language"]["resolution_profiles"] if row["default"]
    )
    shadow = deepcopy(
        next(
            row
            for row in candidate["language"]["model_lowerings"]
            if row["id"] == profile["model_lowering"]
        )
    )
    shadow["id"] = "unused-lowering"
    candidate["language"]["model_lowerings"].insert(0, shadow)
    assert canonical_bytes(project(kernel, candidate, "rir")) == canonical_bytes(
        baseline
    )
    # A pure projection needs the actual declared selection even with one lowering.
    candidate["language"]["model_lowerings"].remove(shadow)
    profile["default"] = False
    with pytest.raises(ValueError):
        project(kernel, candidate, "rir")
