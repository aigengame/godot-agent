"""The fixed Trace grammar has one Kernel owner and two independent projections."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.artifacts import artifacts_by_protocol_role
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import (
    LanguageBundleGraph,
    derive_language_index,
)
from gda_balancing.domain.authority.trace_projection import (
    project_trace_schema,
    trace_protocol_schema,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
)
from gda_balancing.domain.model import AdmittedRir, admit_rir
from gda_balancing.domain.canonical import content_identity
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_trace_schema,
    _encoded,
    _identity,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_renaming_support import _reseal_authored_graph
from test_artifact_protocol_roles import _reseal
from test_current_namespace_public import (
    _OWNERS,
    _PublicCandidate,
    _candidate,
    _experiment,
    _members,
    _receipt,
)


def _authored(ldb):
    return deepcopy(
        {
            "packages": ldb.package_releases,
            "vector_sets": ldb.package_conformance_vector_sets,
            "ldb_root": ldb.root,
        }
    )


def _graph(kernel, authored):
    _reseal_authored_graph(kernel, authored)
    return LanguageBundleGraph(
        root=authored["ldb_root"],
        package_releases=authored["packages"],
        package_conformance_vector_sets=authored["vector_sets"],
        root_byte_size=len(_encoded(authored["ldb_root"])),
        package_byte_sizes=[len(_encoded(row)) for row in authored["packages"]],
        vector_set_byte_sizes=[len(_encoded(row)) for row in authored["vector_sets"]],
    )


def _index(kernel, graph):
    return derive_language_index(
        graph.root,
        graph.package_releases,
        graph.package_conformance_vector_sets,
        kernel["admission"]["required_language_members"],
        kernel=kernel,
        root_byte_size=graph.root_byte_size,
        package_byte_sizes=list(graph.package_byte_sizes),
        vector_set_byte_sizes=list(graph.vector_set_byte_sizes),
        descriptor_order=kernel["meta_format"]["language_bundle"]["package_descriptor"][
            "canonical_order"
        ],
    )


def _trace_definition(authored):
    return next(
        definition
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_wire_schemas"
        for definition in closure["definitions"]
        if definition.get("protocol_role") == "event-trace"
    )


def test_trace_schema_is_derived_without_an_authored_shadow_or_shared_oracle(
    monkeypatch,
):
    kernel, ldb = mutable_authorities()
    graph = _graph(kernel, _authored(ldb))
    assert "schema" not in _trace_definition(_authored(graph))
    schema_a = trace_protocol_schema(kernel, "event-trace")
    schema_b = _consumer_b_trace_schema(kernel, "event-trace")
    assert _encoded(schema_a) == _encoded(schema_b)
    wire_domain = next(
        row["wire_schema_identity_domain"]
        for row in ldb["language"]["artifact_contracts"]
        if row["artifact_kind"] == "event-trace"
    )
    assert content_identity(wire_domain, schema_a) == _identity(wire_domain, schema_b)
    assert _consumer_a(kernel, graph)["admitted"]

    def unavailable(*_args, **_kwargs):
        raise AssertionError("independent B consumed production's generated Schema")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.trace_projection.trace_protocol_schema",
        unavailable,
    )
    independent = _consumer_b(kernel, graph)
    assert independent["admitted"], independent["diagnostics"]
    assert _consumer_b_trace_schema(kernel, "event-trace") == schema_b
    assert "schema" not in _trace_definition(_authored(graph))


@pytest.mark.parametrize(
    "changed_shape", [False, True], ids=["old-placement", "trace-rows"]
)
def test_authored_trace_schema_refuses_at_both_admissions_and_public_entry(
    tmp_path, changed_shape
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema = trace_protocol_schema(kernel, "event-trace")
    if changed_shape:
        schema["properties"]["trace_rows"] = schema["properties"].pop("events")
        schema["required"][schema["required"].index("events")] = "trace_rows"
    _trace_definition(authored)["schema"] = schema
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert not observation["admitted"]
        assert (
            "static",
            "kernel.vector_mismatch",
            "language.definitions",
        ) in observation["diagnostics"]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    result = candidate.cli("model", "check", str(candidate.source), success=False)
    assert result["error"]["stage"] == "static"
    assert result["error"]["diagnostics"][0]["code"] == "kernel.vector_mismatch"
    assert not list((tmp_path / "store").rglob("artifact-set-receipt.json"))


@pytest.mark.parametrize(
    "mutation", ["nested-member", "unknown-type", "missing-field", "duplicate-owner"]
)
def test_changed_kernel_trace_law_cannot_bypass_fixed_build_support(tmp_path, mutation):
    kernel, ldb = mutable_authorities()
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "trace_structure"
    ]
    if mutation == "nested-member":
        calls = law["event"]["field_types"]["calls"]["items"]
        calls["field_types"]["renamed_site"] = calls["field_types"].pop(
            "call_site_identity"
        )
        calls["required_members"][
            calls["required_members"].index("call_site_identity")
        ] = "renamed_site"
        # A pure projection is not authority admission or evidence of host support.
        assert (
            "renamed_site"
            in trace_protocol_schema(kernel, "event-trace")["properties"]["events"][
                "items"
            ]["properties"]["calls"]["items"]["properties"]
        )
    elif mutation == "unknown-type":
        law["event"]["field_types"]["calls"]["items"]["field_types"][
            "call_site_identity"
        ] = {"type": "unsupported-structure"}
    elif mutation == "missing-field":
        del law["event"]["field_types"]["calls"]
    else:
        law["event"]["field_types"]["ordering_key"] = {"type": "object"}
    if mutation != "nested-member":
        raw_language = deepcopy(ldb["language"])
        for row in raw_language["artifact_wire_schemas"]:
            if row.get("protocol_role") == "event-trace":
                del row["schema"]
        with pytest.raises(ValueError):
            project_trace_schema(kernel, raw_language)
    kernel["content_identity"] = _identity("schema-major-kernel-v2", kernel)
    graph = _graph(kernel, _authored(ldb))
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert not observation["admitted"]
        assert ("ingress", "kernel.identity_mismatch", "kernel") in observation[
            "diagnostics"
        ]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    refusal = candidate.cli("model", "check", str(candidate.source), success=False)
    assert refusal["error"]["stage"] == "ingress"
    assert any(
        row["code"] == "kernel.identity_mismatch"
        for row in refusal["error"]["diagnostics"]
    )
    assert not list((tmp_path / "store").rglob("artifact-set-receipt.json"))


def _rename_trace_kinds(authored):
    schema = _trace_definition(authored)
    old_schema_kind = schema["artifact_kind"]
    old_artifact_kind = next(
        definition["artifact_kind"]
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_contracts"
        for definition in closure["definitions"]
        if definition["schema_kind"] == old_schema_kind
    )
    schema["artifact_kind"] = "candidate.trace.schema"
    for package in authored["packages"]:
        for closure in package["semantic_closure"]:
            if closure["authority_path"] == "language.artifact_contracts":
                for definition in closure["definitions"]:
                    if definition["schema_kind"] == old_schema_kind:
                        definition["schema_kind"] = schema["artifact_kind"]
                        definition["artifact_kind"] = "candidate.trace.artifact"
        for collection, old, new in (
            ("artifact_wire_schemas", old_schema_kind, "candidate.trace.schema"),
            ("artifact_contracts", old_artifact_kind, "candidate.trace.artifact"),
        ):
            package["exports"][collection] = [
                new if value == old else value
                for value in package["exports"][collection]
            ]


@pytest.fixture(
    scope="module", params=[False, True], ids=["original", "distinct-kinds"]
)
def public_trace(request, tmp_path_factory):
    kernel, ldb = _candidate()
    authored = _authored(ldb)
    if request.param:
        _rename_trace_kinds(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    language = _index(kernel, graph)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    directory = tmp_path_factory.mktemp("kernel-trace-public")
    candidate = _PublicCandidate(directory, authorities=(kernel, language))
    assert candidate.cli("model", "check", str(candidate.source))["checked"]
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(directory / "build"),
        "--invocation-key",
        "c1" * 32,
    )
    built = artifacts_by_protocol_role(language, _members(build))
    assert len(built) == 8
    rir = built["rir-semantic-payload"]
    rir_path = directory / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = _experiment(rir)
    experiment_path = directory / "experiment.json"
    experiment_path.write_text(json.dumps(specification))
    assert candidate.cli(
        "experiment", "check", str(experiment_path), "--rir", str(rir_path)
    )["checked"]
    run = candidate.cli(
        "experiment",
        "run",
        str(experiment_path),
        "--rir",
        str(rir_path),
        "--out",
        str(directory / "run"),
        "--invocation-key",
        "c2" * 32,
    )
    artifacts = artifacts_by_protocol_role(language, _members(run))
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    assert validate_experiment_artifact_set(checked, artifacts)
    return checked, artifacts, request.param


def test_public_trace_kind_join_and_nominal_record_data_keep_their_owners(public_trace):
    checked, artifacts, renamed = public_trace
    trace = artifacts["event-trace"]
    assert trace["artifact_kind"] == (
        "candidate.trace.artifact" if renamed else "event-trace"
    )
    assert checked.output_contracts["event-trace"].verify(trace)
    events = [event for event in trace["events"] if event["observation"] is None]
    assert [event["outcome"]["id"] for event in events] == [
        "purchase-complete",
        "rebate-complete",
    ]
    assert any(event["calls"] for event in events)
    for owner, event in zip(_OWNERS, events, strict=True):
        fact = next(
            row
            for row in event["facts"]
            if row["name"] == f"{owner.split('.')[1]}_receipt"
        )
        assert fact["value"] == _receipt(owner)
    assert artifacts["metric-dataset"]["samples"][0]["value"] == 100


def test_generated_trace_structure_does_not_replace_semantic_validation(public_trace):
    checked, artifacts, _ = public_trace
    trace = deepcopy(artifacts["event-trace"])
    event = next(row for row in trace["events"] if row["calls"])
    event["calls"][0]["call_site_identity"] = "forged-but-structurally-valid"
    forged = _reseal(checked, "event-trace", trace)
    assert checked.output_contracts["event-trace"].verify(forged)
    assert not validate_experiment_artifact_set(
        checked, {**artifacts, "event-trace": forged}
    )


def test_fixture_resealing_preserves_boolean_integer_schema_drift():
    from schema2_authority_support import refresh_package_semantic_closures

    kernel, ldb = mutable_authorities()
    trace = next(
        row
        for row in ldb["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == "event-trace"
    )
    accepted = trace["schema"]["properties"]["events"]["items"]["properties"][
        "rng_draws"
    ]["items"]["properties"]["accepted"]
    assert accepted == {"const": True}
    accepted["const"] = 1
    refresh_package_semantic_closures(ldb, kernel)
    authored = _authored(ldb)
    authored["packages"] = deepcopy(ldb["language"]["packages"])
    preserved = _trace_definition(authored)
    assert "schema" in preserved
    assert (
        type(
            preserved["schema"]["properties"]["events"]["items"]["properties"][
                "rng_draws"
            ]["items"]["properties"]["accepted"]["const"]
        )
        is int
    )
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert not observation["admitted"]
        assert (
            "static",
            "kernel.vector_mismatch",
            "language.definitions",
        ) in observation["diagnostics"]


@pytest.mark.parametrize(
    "project",
    [trace_protocol_schema, _consumer_b_trace_schema],
    ids=["production", "independent"],
)
def test_trace_projection_from_frozen_kernel_is_fully_owned_json(project):
    from gda_balancing.domain.authority.context import packaged_authority_context

    kernel = packaged_authority_context().kernel
    before = _encoded(deepcopy(kernel))
    schema = project(kernel, "event-trace")
    event = schema["properties"]["events"]["items"]
    schema["properties"]["terminal_statuses"]["items"]["required"][0] = (
        "changed-terminal"
    )
    event["properties"]["calls"]["items"]["properties"]["operation"]["required"][0] = (
        "changed-coordinate"
    )
    event["properties"]["ordering_key"]["properties"]["phase"]["enum"][0] = (
        "changed-phase"
    )
    assert _encoded(deepcopy(kernel)) == before
    assert project(kernel, "event-trace") != schema


@pytest.mark.parametrize(
    "project",
    [trace_protocol_schema, _consumer_b_trace_schema],
    ids=["production", "independent"],
)
def test_trace_projection_uses_existing_rng_and_resolved_symbol_owners(project):
    kernel, _ = mutable_authorities()
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "trace_structure"
    ]
    draws = law["event"]["field_types"]["rng_draws"]["items"]
    assert "required_members" not in draws
    assert "candidate_hex" not in draws["field_types"]
    assert (
        "target"
        not in law["event"]["field_types"]["schedules"]["items"]["field_types"][
            "state_references"
        ]["items"]["field_types"]
    )
    baseline = project(kernel, "event-trace")
    rng = kernel["meta_format"]["runtime_program"]["named_rng"]
    expected_members = deepcopy(rng["trace_members"])
    # Pure projection probes expose its actual owners; these changed Kernels
    # are not admitted or claimed supported by the fixed implementation.
    rng["candidate_encoding"]["width_bits"] = 32
    symbols = kernel["meta_format"]["fact"]["field_contracts"]
    for role in ("quantity-symbol", "structured-symbol"):
        target = symbols[role]["resolved_symbol"]
        target["field_types"]["scope"] = target["field_types"].pop("module")
        target["required_members"][target["required_members"].index("module")] = "scope"
    event = project(kernel, "event-trace")["properties"]["events"]["items"]
    assert event["properties"]["rng_draws"]["items"]["required"] == sorted(
        expected_members
    )
    assert event["properties"]["rng_draws"]["items"]["properties"]["candidate_hex"] == {
        "type": "string",
        "maxLength": 8,
        "pattern": "^[0123456789abcdef]{8}$",
    }
    projected_target = event["properties"]["schedules"]["items"]["properties"][
        "state_references"
    ]["items"]["properties"]["target"]
    assert projected_target["required"] == ["model", "name", "scope"]
    assert set(projected_target["properties"]) == {"model", "scope", "name"}
    assert project(kernel, "event-trace") != baseline
    rng["trace_members"].append("missing-field-contract")
    with pytest.raises(ValueError):
        project(kernel, "event-trace")
    rng["trace_members"].pop()
    symbols["structured-symbol"]["resolved_symbol"]["field_types"]["scope"] = {
        "type": "integer"
    }
    with pytest.raises(ValueError):
        project(kernel, "event-trace")
