"""Independent projection closure exposes only fully validated schema addresses."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b_artifact_semantic_projections_are_closed as projections_are_closed,
)

type _SchemaAddresses = dict[tuple[str | int, ...], tuple[str | int, ...]]


def _projection_view():
    _, ldb = mutable_authorities()
    return {
        "language": {
            name: ldb["language"][name]
            for name in ("artifact_contracts", "artifact_wire_schemas")
        }
    }


def _rir(view):
    language = view["language"]
    schema_index, schema = next(
        (index, schema)
        for index, schema in enumerate(language["artifact_wire_schemas"])
        if schema.get("protocol_role") == "rir-semantic-payload"
    )
    contract_index, contract = next(
        (index, contract)
        for index, contract in enumerate(language["artifact_contracts"])
        if contract["schema_kind"] == schema["artifact_kind"]
    )
    return contract_index, contract, schema_index, schema


def _expected_addresses(view, *, collection="formulas", item="expression"):
    contract_index, _, schema_index, _ = _rir(view)
    reference = (
        "language",
        "artifact_contracts",
        contract_index,
        "semantic_identity_projection",
    )
    properties = (
        "language",
        "artifact_wire_schemas",
        schema_index,
        "schema",
        "properties",
    )
    expected: _SchemaAddresses = {
        (*reference, "excluded_root_members", index): (*properties, member)
        for index, member in enumerate(
            (
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
                "semantic_identity",
            )
        )
    }
    row = (*reference, "collection_member_exclusions", 0)
    expected[(*row, "collection_member")] = (*properties, collection)
    expected[(*row, "excluded_members", 0)] = (
        *properties,
        collection,
        "items",
        "properties",
        item,
    )
    return expected


def _at(value, address):
    for segment in address:
        value = value[segment]
    return value


def test_current_rir_projection_reports_actual_reference_and_property_addresses():
    view = _projection_view()
    addresses: _SchemaAddresses = {("stale",): ("stale",)}

    assert projections_are_closed(view) is True
    assert projections_are_closed(view, schema_addresses=addresses) is True
    assert addresses == _expected_addresses(view)
    for reference, target in addresses.items():
        assert _at(view, reference) == target[-1]
        assert isinstance(_at(view, target), dict)


_INVALID_PATHS = (
    "missing-schema",
    "missing-properties",
    "unknown-root",
    "missing-identity-exclusion",
    "missing-collection",
    "missing-items",
    "missing-item-properties",
    "unknown-item",
    "duplicate-collection",
    "later-invalid-contract",
    "later-malformed-contract",
    "invalid-language",
)


def _invalidate(view, mutation):
    _, contract, _, schema = _rir(view)
    projection = contract["semantic_identity_projection"]
    row = projection["collection_member_exclusions"][0]
    properties = schema["schema"]["properties"]
    if mutation == "missing-schema":
        contract["schema_kind"] = "absent-wire-schema"
    elif mutation == "missing-properties":
        del schema["schema"]["properties"]
    elif mutation == "unknown-root":
        projection["excluded_root_members"].append("absent-root")
    elif mutation == "missing-identity-exclusion":
        projection["excluded_root_members"].remove("semantic_identity")
    elif mutation == "missing-collection":
        row["collection_member"] = "absent-collection"
    elif mutation == "missing-items":
        del properties["formulas"]["items"]
    elif mutation == "missing-item-properties":
        del properties["formulas"]["items"]["properties"]
    elif mutation == "unknown-item":
        row["excluded_members"].append("absent-item")
    elif mutation == "duplicate-collection":
        projection["collection_member_exclusions"].append(deepcopy(row))
    elif mutation == "later-invalid-contract":
        later = deepcopy(contract)
        later["schema_kind"] = "absent-wire-schema"
        view["language"]["artifact_contracts"].append(later)
    elif mutation == "later-malformed-contract":
        view["language"]["artifact_contracts"].append(None)
    else:
        assert mutation == "invalid-language"
        view["language"] = None


@pytest.mark.parametrize("mutation", _INVALID_PATHS)
def test_refused_projection_clears_prior_and_partial_addresses(mutation):
    view = _projection_view()
    addresses = {}
    assert projections_are_closed(view, schema_addresses=addresses) is True
    assert addresses == _expected_addresses(view)
    _invalidate(view, mutation)

    assert projections_are_closed(view) is False
    assert projections_are_closed(view, schema_addresses=addresses) is False
    assert addresses == {}


def test_coherent_projection_field_rename_follows_actual_schema_linkage():
    # This exercises the existing projection judgment, not full authority
    # admission: these local views do not reseal their owning package resources.
    view = _projection_view()
    contract_index, contract, schema_index, schema = _rir(view)
    contract["schema_kind"] = schema["artifact_kind"] = "opaque/wire~schema"
    collection, item, root = (
        "opaque/list~.rows",
        "opaque/item~.text",
        "opaque/root~.key",
    )
    properties = schema["schema"]["properties"]
    properties[collection] = properties.pop("formulas")
    item_properties = properties[collection]["items"]["properties"]
    item_properties[item] = item_properties.pop("expression")
    properties[root] = {"type": "string"}
    projection = contract["semantic_identity_projection"]
    projection["excluded_root_members"].append(root)
    row = projection["collection_member_exclusions"][0]
    row["collection_member"] = collection
    row["excluded_members"] = [item]
    expected = _expected_addresses(view, collection=collection, item=item)
    expected[
        (
            "language",
            "artifact_contracts",
            contract_index,
            "semantic_identity_projection",
            "excluded_root_members",
            5,
        )
    ] = (
        "language",
        "artifact_wire_schemas",
        schema_index,
        "schema",
        "properties",
        root,
    )
    addresses = {}

    assert projections_are_closed(view) is True
    assert projections_are_closed(view, schema_addresses=addresses) is True
    assert addresses == expected
    for reference, target in addresses.items():
        assert _at(view, reference) == target[-1]
        assert isinstance(_at(view, target), dict)


def test_ordinary_identity_exclusions_do_not_gain_unchecked_schema_addresses():
    view = _projection_view()
    _, contract, _, _ = _rir(view)
    # This is an intentionally unverified probe literal, not a shipped value.
    # Ordinary identity exclusions are outside this semantic-projection check.
    contract["identity_excluded_members"] = ["locator.uri"]
    addresses = {}

    assert projections_are_closed(view) is True
    assert projections_are_closed(view, schema_addresses=addresses) is True
    assert addresses == _expected_addresses(view)


def test_no_semantic_projections_succeeds_without_retaining_stale_addresses():
    view = _projection_view()
    for contract in view["language"]["artifact_contracts"]:
        contract.pop("semantic_identity_projection", None)
    addresses: _SchemaAddresses = {("stale",): ("stale",)}

    assert projections_are_closed(view) is True
    assert projections_are_closed(view, schema_addresses=addresses) is True
    assert addresses == {}
