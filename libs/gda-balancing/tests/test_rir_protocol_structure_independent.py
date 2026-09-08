"""Independent RIR grammar consumes raw owners and never A's generated view."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from gda_balancing.domain.artifacts import artifacts_by_protocol_role
from gda_balancing.domain.authority.graph import LanguageBundleGraph
from gda_balancing.domain.canonical import content_identity
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_order_derived_schema,
    _consumer_b_project_rir_schema,
    _consumer_b_rir_schema,
    _encoded,
    _identity,
)
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_rir_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph, _index


def _raw_language(ldb):
    language = {}
    for package in ldb.package_releases:
        for closure in package["semantic_closure"]:
            route = closure["authority_path"].split(".")
            if route[0] != "language":
                continue
            target = language
            for member in route[1:-1]:
                target = target.setdefault(member, {})
            target.setdefault(route[-1], []).extend(deepcopy(closure["definitions"]))
    return language


def _bindings(language):
    schema = next(
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == "rir-semantic-payload"
    )
    contract = next(
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def _runtime_projection(authored):
    profile = next(
        row
        for row in _definitions(authored, "language.resolution_profiles")
        if row["default"]
    )
    return next(
        row["runtime_projection"]
        for row in _definitions(authored, "language.model_lowerings")
        if row["id"] == profile["model_lowering"]
    )


@pytest.mark.parametrize(
    "excluded",
    [
        [],
        ["standard.formula-notation"],
        ["standard.formula-slots"],
        ["standard.formula-notation", "standard.formula-slots"],
    ],
    ids=["empty", "notation", "slots", "notation-and-slots"],
)
def test_independent_packages_refuse_retired_extension_exclusion_inventory(excluded):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    package = next(row for row in authored["packages"] if row["id"] == "game.build")
    package["runtime_semantic_excluded_extensions"] = excluded
    graph = _graph(kernel, authored)
    observations = {
        consumer.__name__: consumer(kernel, graph)
        for consumer in (_consumer_a, _consumer_b)
    }
    assert all(not result["admitted"] for result in observations.values()), observations


def test_independent_rir_admission_derives_raw_graph_without_production_schema(
    monkeypatch,
):
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    schema, binding = _bindings(language)
    assert "schema" not in schema
    assert "semantic_identity_projection" not in binding
    generated_b = _consumer_b_rir_schema(
        kernel, {"language": language}, binding["artifact_kind"]
    )
    generated_a = next(
        row["schema"]
        for row in ldb["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == "rir-semantic-payload"
    )
    assert _encoded(generated_b) == _encoded(generated_a)
    assert _identity(
        binding["wire_schema_identity_domain"], generated_b
    ) == content_identity(binding["wire_schema_identity_domain"], generated_a)
    raw = LanguageBundleGraph(
        root=ldb.root,
        package_releases=ldb.package_releases,
        package_conformance_vector_sets=ldb.package_conformance_vector_sets,
        root_byte_size=ldb.root_byte_size,
        package_byte_sizes=list(ldb.package_byte_sizes),
        vector_set_byte_sizes=list(ldb.vector_set_byte_sizes),
    )

    def unavailable(*_args, **_kwargs):
        raise AssertionError("Consumer B called A's derived Schema")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.rir_projection.rir_protocol_schema", unavailable
    )
    monkeypatch.setattr(
        "gda_balancing.domain.authority.trace_projection.trace_protocol_schema",
        unavailable,
    )
    observation = _consumer_b(kernel, raw)
    assert observation["admitted"], observation["diagnostics"]
    assert "schema" not in schema
    assert "semantic_identity_projection" not in binding


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "schema", "projection"])
def test_independent_rir_projection_refuses_missing_or_reauthored_binding(mutation):
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    schema, binding = _bindings(language)
    if mutation == "missing":
        language["artifact_contracts"].remove(binding)
    elif mutation == "duplicate":
        language["artifact_contracts"].append(deepcopy(binding))
    elif mutation == "schema":
        schema["schema"] = _consumer_b_rir_schema(
            kernel, {"language": language}, binding["artifact_kind"]
        )
    else:
        binding["semantic_identity_projection"] = deepcopy(
            kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
                "rir_structure"
            ]["semantic_projection"]
        )
    with pytest.raises(ValueError):
        _consumer_b_project_rir_schema(kernel, language)


def test_independent_rir_uses_actual_distinct_producer_kind_and_detaches_schema():
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    schema, binding = _bindings(language)
    schema["artifact_kind"] = binding["schema_kind"] = "candidate.rir.schema"
    binding["artifact_kind"] = "candidate.rir.output"
    before_kernel = _encoded(kernel)
    before_language = _encoded(language)
    projected = _consumer_b_rir_schema(
        kernel, {"language": language}, binding["artifact_kind"]
    )
    assert projected["properties"]["artifact_kind"] == {"const": "candidate.rir.output"}
    reordered_kernel = json.loads(json.dumps(kernel, sort_keys=True))
    reordered_language = json.loads(json.dumps(language, sort_keys=True))
    assert _encoded(
        _consumer_b_rir_schema(
            reordered_kernel,
            {"language": reordered_language},
            binding["artifact_kind"],
        )
    ) == _encoded(projected)
    projected["required"].append("caller-mutation")
    projected["properties"]["selected_semantics"]["properties"]["execution_laws"][
        "properties"
    ]["runtime_program"]["properties"]["nodes"]["items"]["enum"][0][
        "id"
    ] = "caller-mutation"
    assert _encoded(kernel) == before_kernel
    assert _encoded(language) == before_language


def test_independent_schema_order_preserves_opaque_law_arrays_and_duplicate_variants():
    kernel, _ = mutable_authorities()
    value = {
        "type": "object",
        "required": ["z", "a"],
        "properties": {
            "z": {"enum": [{"body": [2, 1]}, {"body": [1, 2]}]},
            "a": {"oneOf": [{"const": {"body": [2, 1]}}, {"const": 1}, {"const": 1}]},
        },
    }
    original = deepcopy(value)
    actual = _consumer_b_order_derived_schema(kernel, value)
    assert actual["required"] == ["a", "z"]
    assert actual["properties"]["z"]["enum"] == [{"body": [1, 2]}, {"body": [2, 1]}]
    assert actual["properties"]["a"]["oneOf"].count({"const": 1}) == 2
    assert {"const": {"body": [2, 1]}} in actual["properties"]["a"]["oneOf"]
    reordered = {
        "properties": dict(reversed(list(value["properties"].items()))),
        "required": ["a", "z"],
        "type": "object",
    }
    assert _encoded(_consumer_b_order_derived_schema(kernel, reordered)) == _encoded(
        actual
    )
    assert value == original
    shared = {"type": "object", "required": ["z", "a"]}
    aliased = {"properties": {"schema": shared, "payload": {"const": shared}}}
    detached = _consumer_b_order_derived_schema(kernel, aliased)
    assert detached["properties"]["schema"]["required"] == ["a", "z"]
    assert detached["properties"]["payload"]["const"]["required"] == ["z", "a"]
    assert shared["required"] == ["z", "a"]


def test_independent_rir_terminal_contract_equality_keeps_boolean_and_integer_distinct():
    kernel, ldb = mutable_authorities()
    field_contracts = kernel["meta_format"]["fact"]["field_contracts"]
    field_contracts["quantity-symbol"]["resolved_symbol"]["field_types"]["module"] = {
        "const": True
    }
    field_contracts["structured-symbol"]["resolved_symbol"]["field_types"]["module"] = {
        "const": 1
    }
    assert (
        field_contracts["quantity-symbol"]["resolved_symbol"]
        == field_contracts["structured-symbol"]["resolved_symbol"]
    )
    # This is a pure projection refusal, not support for an altered Kernel build.
    with pytest.raises(ValueError, match="terminal coordinate contracts disagree"):
        _consumer_b_rir_schema(kernel, {"language": _raw_language(ldb)}, "rir")


def test_public_required_external_cardinality_follows_the_actual_assignment_owner(
    tmp_path,
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    profiles = ldb["language"]["resolution_profiles"]
    selected = next(row for row in profiles if row["default"])
    lowering = next(
        row
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_lowerings"
        for row in closure["definitions"]
        if row["id"] == selected["model_lowering"]
    )
    mode = next(
        mode
        for role in lowering["assignment_policy"]["roles"]
        if role["role"] == "input"
        for mode in role["modes"]
        if mode["id"] == "experiment-required"
    )
    assert mode["external_fact_cardinality"] == "optional"
    mode["external_fact_cardinality"] = "required"
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert observation["admitted"], observation["diagnostics"]
    language = _index(kernel, graph)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    source_path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    candidate.write_source(json.loads(source_path.read_text()))
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "d9" * 32,
    )
    artifacts = artifacts_by_protocol_role(language, _members(receipt))
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    schema = _consumer_b_rir_schema(
        kernel, {"language": _raw_language(graph)}, rir["artifact_kind"]
    )
    validator = Draft202012Validator(schema)
    validator.validate(rir)
    entry = next(
        row for row in rir["entrypoints"] if row["id"] == "combat.player-attacks-enemy"
    )
    targets = entry["external_fact_contract"]["targets"]
    assert {row["target"]["name"]: row["cardinality"] for row in targets} == {
        "enemy_defense": "required"
    }
    # Forbidden excludes the carrier; it is not a legal emitted cardinality.
    targets[0]["cardinality"] = "forbidden"
    assert not validator.is_valid(rir)


@pytest.mark.parametrize(
    ("field", "excluded"),
    [
        ("excluded_members", "id"),
        ("excluded_members", "body"),
        ("excluded_members", "inputs"),
        ("excluded_members", "resource_bounds"),
        ("excluded_members", "vectors"),
        ("excluded_extension_members", "standard.formula-notation"),
    ],
)
def test_independent_rir_refuses_retired_authored_exclusion_controls(field, excluded):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    operations = next(
        row
        for row in _runtime_projection(authored)["collections"]
        if row["source"]
        == {"kind": "semantic-closure", "authority_path": "language.operations"}
    )
    operations[field] = [excluded]
    graph = _graph(kernel, authored)
    observations = {}
    for label, consumer in (("A", _consumer_a), ("B", _consumer_b)):
        observation = consumer(kernel, graph)
        observations[label] = (observation["admitted"], observation["diagnostics"])
    assert all(not admitted for admitted, _ in observations.values()), observations
    assert all(
        diagnostics == [("static", "kernel.vector_mismatch", "language.definitions")]
        for _, diagnostics in observations.values()
    ), observations


def test_public_nominal_collection_rename_keeps_fixed_execution_field_ownership(
    tmp_path,
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    projection = _runtime_projection(authored)
    nominal = next(
        row
        for row in projection["collections"]
        if row["source"]
        == {"kind": "semantic-closure", "authority_path": "language.nominal_types"}
    )
    old, new = nominal["id"], "opaque.nominal.collection"
    nominal["id"] = new
    for member, value in projection["type_reference_closure"].items():
        if value == old:
            projection["type_reference_closure"][member] = new
    for seed in projection["seeds"]:
        if seed["collection"] == old:
            seed["collection"] = new
    for edge in projection["edges"]:
        for member in ("source_collection", "target_collection"):
            if edge[member] == old:
                edge[member] = new
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert observation["admitted"], observation["diagnostics"]
    language = _index(kernel, graph)
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    source = (
        Path(__file__).parents[1] / "examples/schema2/bounded-fold/model-source.json"
    )
    candidate.write_source(json.loads(source.read_text()))
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "c9" * 32,
    )
    artifacts = artifacts_by_protocol_role(language, _members(receipt))
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    selected = rir["selected_semantics"]
    assert selected["nominal_types"]
    operations = [row["definition"] for row in selected["operations"]]
    closures = [
        definition
        for package in selected["package_semantic_closures"]
        for closure in package["definitions"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
    ]
    assert operations and closures
    for definition in [*operations, *closures]:
        assert "vectors" not in definition
        assert {"id", "body", "inputs", "resource_bounds"} <= definition.keys()
    Draft202012Validator(
        _consumer_b_rir_schema(
            kernel, {"language": _raw_language(graph)}, rir["artifact_kind"]
        )
    ).validate(rir)
