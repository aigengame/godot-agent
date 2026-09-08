"""Receipt transport has one fixed owner and preserves its identified encoding."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.artifacts import select_protocol_artifact_contract
from gda_balancing.domain.authority.publication_projection import (
    publication_protocol_schema,
)
from schema2_authority_support import (
    mutable_authorities,
    refresh_package_semantic_closures,
)
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph


_WIRE_IDENTITY = (
    "sha256:1458071325c647715a5e04f042febc82bbb3efff6b2fe9d783e3b1dd50ca9c5f"
)
_RECEIPT_IDENTITY = (
    "sha256:4fe61635ae11b9c7e209472c91e99b1314adffacf67da6f6dcd3e0316fc17ae3"
)


def _payload():
    return {
        "descriptor_identity": "sha256:" + "1" * 64,
        "invocation_key": "2" * 64,
        "manifest_identity": "sha256:" + "3" * 64,
        "manifest_locator": "/first/artifact-set-manifest.json",
        "member_locators": [{"logical_name": "value", "locator": "/first/value.json"}],
    }


def _definitions(authored, path):
    return [
        definition
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == path
        for definition in closure["definitions"]
    ]


def _receipt_rows(authored):
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == "artifact-set-receipt"
    )
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def _rename_receipt(authored):
    """Rename the two actual declarations and their explicit export references."""
    schema, contract = _receipt_rows(authored)
    old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
    schema["artifact_kind"] = "review.receipt.schema"
    contract["schema_kind"] = schema["artifact_kind"]
    contract["artifact_kind"] = "review.receipt.artifact"
    for package in authored["packages"]:
        for collection, old, new in (
            ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
            ("artifact_contracts", old_kind, contract["artifact_kind"]),
        ):
            package["exports"][collection] = [
                new if value == old else value
                for value in package["exports"][collection]
            ]


def test_receipt_has_no_authored_schema_or_identity_exclusion_policy():
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema, contract = _receipt_rows(authored)
    assert "schema" not in schema
    assert all(
        "identity_excluded_members" not in row
        for row in _definitions(authored, "language.artifact_contracts")
    )
    grammar = kernel["meta_format"]["language_definitions"]["collections"][
        "artifact_contracts"
    ]
    assert "identity_excluded_members" not in grammar["required_members"]
    assert "identity_excluded_members" not in grammar["field_types"]
    selected = select_protocol_artifact_contract(ldb, "artifact-set-receipt")
    assert selected.schema == publication_protocol_schema(
        kernel, "artifact-set-receipt", contract["artifact_kind"]
    )
    assert selected.wire_schema_identity == _WIRE_IDENTITY
    assert list(selected.definition["identity_excluded_members"]) == [
        "manifest_locator",
        "member_locators",
    ]


def test_receipt_preserves_the_original_complete_identity_and_transport_independence():
    _, ldb = mutable_authorities()
    selected = select_protocol_artifact_contract(ldb, "artifact-set-receipt")
    original = selected.identify(_payload())
    assert original["content_identity"] == _RECEIPT_IDENTITY
    assert original["wire_schema_identity"] == _WIRE_IDENTITY
    changed = _payload()
    changed["manifest_locator"] = "/second/artifact-set-manifest.json"
    changed["member_locators"] = [
        {"logical_name": "value", "locator": "/second/value.json"}
    ]
    relocated = selected.identify(changed)
    assert relocated["content_identity"] == original["content_identity"]
    assert selected.verify(original) and selected.verify(relocated)


@pytest.mark.parametrize(
    "member", ["descriptor_identity", "invocation_key", "manifest_identity"]
)
def test_each_receipt_binding_remains_in_content_identity(member):
    _, ldb = mutable_authorities()
    selected = select_protocol_artifact_contract(ldb, "artifact-set-receipt")
    payload = _payload()
    payload[member] = "0" * 64 if member == "invocation_key" else "sha256:" + "0" * 64
    changed = selected.identify(payload)
    assert changed["content_identity"] != _RECEIPT_IDENTITY
    assert selected.verify(changed)


@pytest.mark.parametrize(
    "excluded", [[], ["nonexistent_transport_member"], ["descriptor_identity"]]
)
def test_authored_receipt_identity_exclusion_reentry_refuses(excluded):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _, contract = _receipt_rows(authored)
    contract["identity_excluded_members"] = excluded
    admission = _consumer_a(kernel, _graph(kernel, authored))
    assert admission["admitted"] is False
    assert any(row[1] == "kernel.vector_mismatch" for row in admission["diagnostics"])


@pytest.mark.parametrize("mode", ["derived", "renamed", "authored-override"])
def test_public_build_uses_only_the_derived_receipt_structure(tmp_path, mode):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    if mode == "renamed":
        _rename_receipt(authored)
    schema, contract = _receipt_rows(authored)
    override = mode == "authored-override"
    if override:
        schema["schema"] = deepcopy(
            publication_protocol_schema(
                kernel, "artifact-set-receipt", contract["artifact_kind"]
            )
        )
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.write_source(
        json.loads(
            (
                Path(__file__).parents[1]
                / "examples/schema2/bounded-fold/model-source.json"
            ).read_text()
        )
    )
    result = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "dc" * 32,
        success=not override,
    )
    if override:
        assert public.receipts[-1]["returncode"] == 2
        assert any(
            row["code"] == "kernel.vector_mismatch"
            for row in result["error"]["diagnostics"]
        )
        assert not (public.directory / "build").exists()
    else:
        assert len(_members(result)) == 8
        assert result["artifact_kind"] == contract["artifact_kind"]
        if mode == "derived":
            assert result["wire_schema_identity"] == _WIRE_IDENTITY
        receipt = public.directory / "receipt.json"
        receipt.write_text(json.dumps(result))
        inspected = public.cli("model", "inspect", str(receipt))
        assert inspected


def test_fixture_refresh_does_not_erase_co_mutated_receipt_overrides():
    kernel, ldb = mutable_authorities()
    language = ldb["language"]
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
    schema["schema"]["properties"]["transport_manifest"] = schema["schema"][
        "properties"
    ].pop("manifest_locator")
    schema["schema"]["required"] = [
        "transport_manifest" if member == "manifest_locator" else member
        for member in schema["schema"]["required"]
    ]
    contract["identity_excluded_members"] = ["transport_manifest", "member_locators"]
    refresh_package_semantic_closures(ldb, kernel)
    authored = {
        "packages": ldb["language"]["packages"],
        "vector_sets": ldb.package_conformance_vector_sets,
        "ldb_root": ldb.root,
    }
    stored_schema, stored_contract = _receipt_rows(authored)
    assert stored_schema["schema"] == schema["schema"]
    assert (
        stored_contract["identity_excluded_members"]
        == contract["identity_excluded_members"]
    )
    admission = _consumer_a(kernel, _graph(kernel, authored))
    assert admission["admitted"] is False
    assert any(row[1] == "kernel.vector_mismatch" for row in admission["diagnostics"])
