"""Snapshot and terminal evidence have one wire owner and real replay obligations."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import admit_rir
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _build, _check, _source, _specification
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph, _index

_ROLES = ("snapshot-series", "runtime-terminal-audit")


def _definition(authored, role):
    return next(
        row
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_wire_schemas"
        for row in closure["definitions"]
        if row.get("protocol_role") == role
    )


def _schema(ldb, role):
    return next(
        row["schema"]
        for row in ldb["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == role
    )


@pytest.mark.parametrize("role", _ROLES)
def test_runtime_evidence_has_no_authored_outer_schema(role):
    _, ldb = mutable_authorities()
    assert "schema" not in _definition(_authored(ldb), role)


@pytest.mark.parametrize("role", _ROLES)
def test_runtime_evidence_rejects_resealed_outer_override_at_public_entry(
    tmp_path, role
):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _definition(authored, role)["schema"] = deepcopy(_schema(ldb, role))
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"]
        assert ("static", "kernel.vector_mismatch", "language.definitions") in result[
            "diagnostics"
        ]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(_source())
    result = candidate.cli("model", "check", str(candidate.source), success=False)
    assert result["error"]["stage"] == "static"
    assert result["error"]["diagnostics"][0]["code"] == "kernel.vector_mismatch"


@pytest.mark.parametrize("role", _ROLES)
def test_runtime_evidence_missing_role_has_no_schema_fallback(role):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _definition(authored, role).pop("protocol_role")
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result


def test_terminal_prefix_is_the_actual_trace_event_schema():
    _, ldb = mutable_authorities()
    trace = _schema(ldb, "event-trace")["properties"]["events"]
    audit = _schema(ldb, "runtime-terminal-audit")["properties"]
    assert _encoded(audit["committed_trace_prefix"]) == _encoded(trace)
    assert (
        audit["refusing_event"]["properties"]["attempted_calls"]
        == trace["items"]["properties"]["calls"]
    )
    snapshot = _schema(ldb, "snapshot-series")["properties"]
    assert snapshot["snapshots"]["items"] == audit["last_snapshot_record"]
    assert snapshot["event_catalog"] == audit["event_catalog_prefix"]


def _renamed(kernel, ldb):
    authored = _authored(ldb)
    for index, role in enumerate(_ROLES):
        schema = _definition(authored, role)
        old = schema["artifact_kind"]
        schema["artifact_kind"] = f"local.schema.{index}"
        for package in authored["packages"]:
            for closure in package["semantic_closure"]:
                if closure["authority_path"] != "language.artifact_contracts":
                    continue
                for row in closure["definitions"]:
                    if row["schema_kind"] == old:
                        row["schema_kind"] = schema["artifact_kind"]
                        # identity_domain is its own authored value; preserve it.
                        row["artifact_kind"] = f"local.output.{index}"
        # Export lists are actual definition references, never arbitrary payload.
        for package in authored["packages"]:
            exports = package["exports"]
            for key in ("artifact_wire_schemas", "artifact_contracts"):
                if key in exports:
                    exports[key] = [
                        schema["artifact_kind"]
                        if x == old and key == "artifact_wire_schemas"
                        else f"local.output.{index}"
                        if x == role and key == "artifact_contracts"
                        else x
                        for x in exports[key]
                    ]
    return _graph(kernel, authored)


@pytest.fixture(scope="module", params=[False, True], ids=["original", "local-kinds"])
def public_evidence(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("runtime-evidence")
    kernel, ldb = mutable_authorities()
    graph = _renamed(kernel, ldb) if request.param else ldb
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    candidate = _PublicCandidate(directory, authorities=(kernel, graph))
    candidate.write_source(_source())
    candidate.cli("model", "check", str(candidate.source))
    rir_path, rir = _build(candidate)
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext), context
    program = admit_rir(rir, authority_context=context)
    cases = {}
    for refusal in (False, True):
        specification = _specification(rir, [1, 2, 3, 4])
        if refusal:
            second = _specification(rir, [(1 << 63) - 1, 1])["scenarios"][0]
            second["id"] = "later-overflow"
            specification["scenarios"].append(second)
        path, _ = _check(candidate, rir_path, specification)
        result = candidate.cli(
            "experiment",
            "run",
            str(path),
            "--rir",
            rir_path,
            "--out",
            str(directory / ("refused" if refusal else "accepted")),
            "--invocation-key",
            ("03" if refusal else "02") * 32,
            success=not refusal,
        )
        members = _members(result["error"]["terminal_audit"] if refusal else result)
        checked = check_experiment_value(
            specification, program, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        assert validate_experiment_artifact_set(checked, members)
        if refusal:
            assert (
                result["error"]["diagnostics"][0]["code"] == "runtime.numeric_overflow"
            )
            assert len(members["runtime-terminal-audit"]["committed_trace_prefix"]) == 3
        (
            directory / ("refused-members.json" if refusal else "accepted-members.json")
        ).write_text(json.dumps(members, indent=2))
        (
            directory
            / (
                "refused-specification.json"
                if refusal
                else "accepted-specification.json"
            )
        ).write_text(json.dumps(specification, indent=2))
        cases[refusal] = (checked, members)
    (directory / "commands.json").write_text(json.dumps(candidate.receipts, indent=2))
    (directory / "rir.json").write_text(json.dumps(rir, indent=2))
    return cases


def test_public_success_and_later_refusal_preserve_complete_journals(public_evidence):
    for refusal, (checked, members) in public_evidence.items():
        role = "runtime-terminal-audit" if refusal else "snapshot-series"
        contract = checked.output_contracts[role]
        assert contract.verify(members[role])
        assert validate_experiment_artifact_set(checked, members)
        if refusal:
            audit = members[role]
            assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
            assert audit["budget_counters"]["node_steps"] == 69
            assert audit["refusing_event"]["call_path"] == "fold/ordered-items/@1"
        else:
            assert len(members[role]["snapshots"]) == 4
            assert len(members[role]["event_catalog"]) == 3


@pytest.mark.parametrize(
    "mutation", ["state", "catalog", "ledger", "path", "reason", "counter", "trace"]
)
def test_runtime_evidence_wire_does_not_replace_semantic_replay(
    public_evidence, mutation
):
    refusal = mutation not in {"state", "catalog"}
    checked, original = public_evidence[refusal]
    members = deepcopy(original)
    role = "runtime-terminal-audit" if refusal else "snapshot-series"
    value = members[role]
    if mutation == "state":
        value["snapshots"][-1]["values"][-1]["value"] = 918
    elif mutation == "catalog":
        value["event_catalog"][0]["event_spec"]["entrypoint"] = "wrong-entrypoint"
    elif mutation == "ledger":
        value["last_snapshot_record"]["continuation"]["resource_ledger"][
            "node_steps"
        ] += 100
    elif mutation == "path":
        value["refusing_event"]["call_path"] = "fold/ordered-items/@0"
    elif mutation == "reason":
        value["refusing_event"]["reason"] = "runtime.step_limit_exceeded"
        value["diagnostic"]["code"] = "runtime.step_limit_exceeded"
    elif mutation == "counter":
        value["budget_counters"]["node_steps"] += 1
    else:
        value["committed_trace_prefix"][0]["outcome"]["id"] = "fabricated"
    if mutation == "ledger":
        from test_bounded_fold_ledger import _reseal_snapshot

        value = _reseal_snapshot(checked, value)
    contract = checked.output_contracts[role]
    members[role] = contract.identify(
        {
            k: v
            for k, v in value.items()
            if k
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
    )
    assert contract.verify(members[role])
    assert not validate_experiment_artifact_set(checked, members)


@pytest.mark.parametrize("role", _ROLES)
def test_runtime_evidence_independent_projection_and_missing_owner(monkeypatch, role):
    from gda_balancing.domain.authority.runtime_evidence_projection import (
        runtime_evidence_protocol_schema,
    )
    from schema2_bootstrap_conformance_support import (
        _consumer_b_runtime_evidence_schema,
    )

    kernel, ldb = mutable_authorities()
    graph = _graph(kernel, _authored(ldb))
    before = _encoded(kernel)
    schema_a = runtime_evidence_protocol_schema(kernel, role, "local.actual.kind")
    schema_b = _consumer_b_runtime_evidence_schema(kernel, role, "local.actual.kind")
    assert _encoded(schema_a) == _encoded(schema_b)
    Draft202012Validator.check_schema(schema_a)
    assert schema_a["properties"]["artifact_kind"] == {"const": "local.actual.kind"}
    assert _encoded(kernel) == before

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B consumed A's protocol projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.runtime_evidence_projection.runtime_evidence_protocol_schema",
        unavailable,
    )
    monkeypatch.setattr(
        "gda_balancing.domain.authority.trace_projection.trace_protocol_contracts",
        unavailable,
    )
    result = _consumer_b(kernel, graph)
    assert result["admitted"], result
    assert (
        _consumer_b_runtime_evidence_schema(kernel, role, "local.actual.kind")
        == schema_b
    )
    for removed in ("snapshot", "event_spec", "continuation"):
        malformed = deepcopy(kernel)
        del malformed["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["runtime_evidence_structure"][removed]
        for project in (
            runtime_evidence_protocol_schema,
            _consumer_b_runtime_evidence_schema,
        ):
            with pytest.raises(ValueError):
                project(malformed, role, "local.actual.kind")
    schema_b["properties"]["root_event_map"]["items"]["required"].clear()
    assert _encoded(kernel) == before


def test_runtime_evidence_preserves_wire_minimum_and_replay_rollback_boundary(
    public_evidence,
):
    checked, members = public_evidence[False]
    empty = deepcopy(members["snapshot-series"])
    empty["snapshots"] = []
    with pytest.raises(ValidationError) as error:
        checked.output_contracts["snapshot-series"].identify(
            {
                key: child
                for key, child in empty.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
        )
    assert error.value.validator == "minItems"
    assert list(error.value.path) == ["snapshots"]
    checked, members = public_evidence[True]
    value = deepcopy(members["runtime-terminal-audit"])
    value["rollback"]["committed"] = True
    contract = checked.output_contracts["runtime-terminal-audit"]
    forged = contract.identify(
        {
            key: child
            for key, child in value.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
    )
    assert contract.verify(forged)
    assert not validate_experiment_artifact_set(
        checked, {**members, "runtime-terminal-audit": forged}
    )


@pytest.mark.parametrize("role", _ROLES)
def test_runtime_evidence_inventory_closes_only_actual_derived_bindings(role):
    from dataclasses import replace

    from schema2_extension_inventory_support import (
        InventoryRefusal,
        _authority_path_rows,
        read_extension_inventory,
        validate_extension_inventory,
    )

    kernel, ldb = mutable_authorities()
    graph = _authored(_renamed(kernel, ldb))
    _, definition, pointer = next(
        row
        for row in _authority_path_rows(
            kernel, graph, "language_bundle.language.artifact_wire_schemas"
        )
        if row[1].get("protocol_role") == role
    )
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert not any(gap.pointer == pointer for gap in inventory.uncovered)
    joined = [
        occurrence
        for occurrence in inventory.occurrences
        if occurrence.token.role == "language.artifact_wire_schemas"
        and occurrence.token.name == definition["artifact_kind"]
        and occurrence.use == "reference"
    ]
    assert any(row.pointer.endswith("/schema_kind") for row in joined)
    omitted = replace(
        inventory,
        occurrences=tuple(
            occurrence
            for occurrence in inventory.occurrences
            if occurrence not in joined
        ),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, omitted)
    _definition(graph, role)["schema"] = deepcopy(_schema(ldb, role))
    with pytest.raises(
        InventoryRefusal, match="wire protocol structure does not close"
    ):
        read_extension_inventory(kernel, graph)
