"""Receipt bindings and transport are derived independently from the supplied Kernel."""

from copy import deepcopy
from dataclasses import replace
import hashlib

from jsonschema import Draft202012Validator
import pytest

from gda_balancing.domain.artifacts import select_artifact_contract
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_artifact_contract_declarations,
    _consumer_b_project_receipt_schema,
    _consumer_b_receipt_schema,
    _encoded,
    _identity,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from test_rir_protocol_structure_independent import _raw_language
from test_trace_protocol_structure import _authored, _graph


def _receipt(language):
    schema = next(
        row
        for row in language["artifact_wire_schemas"]
        if row.get("protocol_role") == "artifact-set-receipt"
    )
    contract = next(
        row
        for row in language["artifact_contracts"]
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def test_receipt_independent_schema_preserves_baseline_bytes_and_opaque_inputs(
    monkeypatch,
):
    kernel, ldb = mutable_authorities()
    raw = _graph(kernel, _authored(ldb))
    language = _raw_language(raw)
    schema, contract = _receipt(language)
    assert "schema" not in schema
    assert all(
        "identity_excluded_members" not in row for row in language["artifact_contracts"]
    )
    projected = _consumer_b_receipt_schema(kernel, contract["artifact_kind"])
    # Exact original wire bytes, captured before deletion of its authored copy.
    assert len(_encoded(projected)) == 950
    assert hashlib.sha256(_encoded(projected)).hexdigest() == (
        "53908bd786b6daf916cd5f8ad2838626fb9413699869d00657a6d6bb45604c38"
    )
    generated_a = _receipt(ldb["language"])[0]["schema"]
    assert _encoded(projected) == _encoded(generated_a)
    assert _identity(contract["wire_schema_identity_domain"], projected) == (
        select_artifact_contract(
            ldb, _receipt(ldb["language"])[1]["artifact_kind"]
        ).wire_schema_identity
    )
    assert _consumer_a(kernel, raw)["admitted"]

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B consumed the production receipt projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.receipt_projection.receipt_protocol_schema",
        unavailable,
    )
    observation = _consumer_b(kernel, raw)
    assert observation["admitted"], observation["diagnostics"]
    before = _encoded(kernel)
    projected["required"].reverse()
    projected["properties"]["member_locators"]["items"]["required"].append("changed")
    assert _encoded(kernel) == before
    assert "schema" not in schema


@pytest.mark.parametrize(
    "mutation",
    ["schema", "locator-schema", "empty", "binding", "unknown", "other-contract"],
)
def test_receipt_independent_admission_refuses_authored_shadow_and_exclusions(mutation):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    for package in authored["packages"]:
        for entry in package["semantic_closure"]:
            if entry["authority_path"] == "language.artifact_wire_schemas":
                target = next(
                    (
                        row
                        for row in entry["definitions"]
                        if row.get("protocol_role") == "artifact-set-receipt"
                    ),
                    None,
                )
                if target is not None and mutation in {"schema", "locator-schema"}:
                    target["schema"] = _consumer_b_receipt_schema(
                        kernel, binding["artifact_kind"]
                    )
                    if mutation == "locator-schema":
                        target["schema"]["properties"]["transport_manifest"] = target[
                            "schema"
                        ]["properties"].pop("manifest_locator")
                        required = target["schema"]["required"]
                        required[required.index("manifest_locator")] = (
                            "transport_manifest"
                        )
            if entry["authority_path"] == "language.artifact_contracts":
                for target in entry["definitions"]:
                    selected = target["schema_kind"] == schema["artifact_kind"]
                    if selected and mutation in {"empty", "binding", "unknown"}:
                        target["identity_excluded_members"] = {
                            "empty": [],
                            "binding": ["descriptor_identity"],
                            "unknown": ["missing"],
                        }[mutation]
                    elif not selected and mutation == "other-contract":
                        target["identity_excluded_members"] = []
    raw = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, raw)
        assert not observation["admitted"]
        assert observation["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


@pytest.mark.parametrize(
    "mutation",
    ["missing-role", "duplicate-role", "missing-binding", "duplicate-binding"],
)
def test_receipt_independent_projection_requires_unique_actual_binding(mutation):
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    if mutation == "missing-role":
        language["artifact_wire_schemas"].remove(schema)
    elif mutation == "duplicate-role":
        language["artifact_wire_schemas"].append(deepcopy(schema))
    elif mutation == "missing-binding":
        language["artifact_contracts"].remove(binding)
    else:
        language["artifact_contracts"].append(deepcopy(binding))
    with pytest.raises(ValueError):
        _consumer_b_project_receipt_schema(kernel, language)


def test_receipt_binding_hashes_and_transport_relocation_follow_actual_law():
    kernel, ldb = mutable_authorities()
    selected = select_artifact_contract(
        ldb, _receipt(ldb["language"])[1]["artifact_kind"]
    )
    language = _raw_language(ldb)
    schema, binding = _receipt(language)
    schema["artifact_kind"] = binding["schema_kind"] = "receipt.schema.renamed"
    binding["artifact_kind"] = "receipt.artifact.renamed"
    _consumer_b_project_receipt_schema(kernel, language)
    assert schema["schema"]["properties"]["artifact_kind"] == {
        "const": binding["artifact_kind"]
    }
    declarations = _consumer_b_artifact_contract_declarations(
        kernel["meta_format"], language
    )
    assert all("identity_excluded_members" not in row for row in declarations)
    declarations[0]["artifact_kind"] = "caller-mutation"
    assert language["artifact_contracts"][0]["artifact_kind"] != "caller-mutation"
    binding["identity_excluded_members"].append("descriptor_identity")
    with pytest.raises(ValueError):
        _consumer_b_artifact_contract_declarations(kernel["meta_format"], language)

    payload = {
        "descriptor_identity": "descriptor-A",
        "invocation_key": "invocation-A",
        "manifest_identity": "manifest-A",
        "manifest_locator": "file:first-manifest",
        "member_locators": [
            {"logical_name": "opaque-label", "locator": "file:first-member"}
        ],
    }
    artifact = selected.identify(payload)
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "receipt_structure"
    ]
    independent_body = {
        name: value for name, value in artifact.items() if name not in law["transport"]
    }
    assert artifact["content_identity"] == _identity(
        selected.definition["identity_domain"], independent_body
    )
    for field in law["bindings"]:
        altered = deepcopy(payload)
        altered[field] += "-changed"
        assert (
            selected.identify(altered)["content_identity"]
            != artifact["content_identity"]
        )
    relocated = deepcopy(payload)
    relocated["manifest_locator"] = "file:second-manifest"
    relocated["member_locators"][0]["locator"] = "file:second-member"
    assert (
        selected.identify(relocated)["content_identity"] == artifact["content_identity"]
    )
    malformed = deepcopy(artifact)
    malformed["member_locators"] = []
    artifact_kind = artifact["artifact_kind"]
    assert isinstance(artifact_kind, str)
    errors = list(
        Draft202012Validator(
            _consumer_b_receipt_schema(kernel, artifact_kind)
        ).iter_errors(malformed)
    )
    assert [(list(error.path), error.validator) for error in errors] == [
        (["member_locators"], "minItems")
    ]


@pytest.mark.parametrize("corruption", ["omitted", "wrong-owner"])
def test_receipt_inventory_keeps_binding_tokens_without_authored_schema_ghosts(
    corruption,
):
    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    schema, binding = _receipt(_raw_language(ldb))
    schema_token = AuthorityToken(
        "language.artifact_wire_schemas", (), schema["artifact_kind"]
    )
    producer_token = AuthorityToken(
        "language.artifact_contracts", (), binding["artifact_kind"]
    )
    assert {schema_token, producer_token} <= set(inventory.tokens)
    occurrence = next(
        row
        for row in inventory.occurrences
        if row.token == schema_token and row.pointer.endswith("/schema_kind")
    )
    assert not any(
        gap.pointer
        == occurrence.pointer.rsplit("/", 1)[0] + "/identity_excluded_members"
        for gap in inventory.uncovered
    )
    for row in inventory.occurrences:
        if row.token == producer_token:
            assert "/schema/" not in row.pointer
    altered = replace(
        inventory,
        occurrences=tuple(row for row in inventory.occurrences if row != occurrence)
        + (
            (replace(occurrence, token=replace(schema_token, owner=("wrong-owner",))),)
            if corruption == "wrong-owner"
            else ()
        ),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, altered)
