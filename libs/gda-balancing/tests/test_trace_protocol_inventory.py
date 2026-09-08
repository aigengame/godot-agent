"""Inventory derived protocol bindings without inventing authored schema owners."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _attached_language,
    read_extension_inventory,
    validate_extension_inventory,
)
from test_trace_protocol_structure import _authored, _graph


def _definition(graph, role):
    return next(
        row
        for package in graph["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_wire_schemas"
        for row in closure["definitions"]
        if row.get("protocol_role") == role
    )


def _rename_bindings(graph, role):
    schema = _definition(graph, role)
    old_schema_kind = schema["artifact_kind"]
    binding = next(
        row
        for package in graph["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.artifact_contracts"
        for row in closure["definitions"]
        if row["schema_kind"] == old_schema_kind
    )
    old_kind = binding["artifact_kind"]
    schema["artifact_kind"] = "candidate." + role + ".schema"
    binding["schema_kind"] = schema["artifact_kind"]
    binding["artifact_kind"] = "candidate." + role + ".artifact"
    for package in graph["packages"]:
        for key, old, new in (
            ("artifact_wire_schemas", old_schema_kind, schema["artifact_kind"]),
            ("artifact_contracts", old_kind, binding["artifact_kind"]),
        ):
            package["exports"][key] = [
                new if name == old else name for name in package["exports"][key]
            ]


@pytest.fixture(scope="module", params=["event-trace", "rir-semantic-payload"])
def protocol_role(request):
    return request.param


@pytest.fixture(
    scope="module", params=[False, True], ids=["original", "distinct-kinds"]
)
def protocol_graph(request, protocol_role):
    kernel, language = mutable_authorities()
    graph = _authored(language)
    if request.param:
        _rename_bindings(graph, protocol_role)
    admitted_graph = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, admitted_graph)
        assert result["admitted"], result["diagnostics"]
    return kernel, graph


def test_inventory_preserves_physical_graph_and_open_kind_names(
    protocol_graph, protocol_role, monkeypatch
):
    kernel, graph = protocol_graph
    original = _encoded(graph)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("inventory used a production protocol schema projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.trace_projection.trace_protocol_schema",
        unavailable,
    )
    monkeypatch.setattr(
        "gda_balancing.domain.authority.rir_projection.rir_protocol_schema", unavailable
    )
    schema = _definition(graph, protocol_role)
    assert "schema" not in schema
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    token = AuthorityToken(
        "language.artifact_wire_schemas", (), schema["artifact_kind"]
    )
    declaration = next(
        item
        for item in inventory.occurrences
        if item.token == token and item.use == "declaration"
    )
    pointer = declaration.pointer.removesuffix("/artifact_kind")
    assert not any(
        item.pointer.startswith(pointer + "/schema/") for item in inventory.occurrences
    )
    assert not any(item.pointer == pointer for item in inventory.uncovered)
    assert inventory.uncovered  # This slice does not close the other schema owners.
    view = _attached_language(kernel, graph)["language"]
    derived = next(
        row
        for row in view["artifact_wire_schemas"]
        if row["artifact_kind"] == schema["artifact_kind"]
    )
    producer = next(
        row for row in view["artifact_contracts"] if row["schema_kind"] == token.name
    )
    assert (
        derived["schema"]["properties"]["artifact_kind"]["const"]
        == producer["artifact_kind"]
    )
    assert (
        AuthorityToken("language.artifact_contracts", (), producer["artifact_kind"])
        in inventory.tokens
    )
    assert _encoded(graph) == original


@pytest.mark.parametrize(
    "changed", [False, True], ids=["old-placement", "changed-shape"]
)
def test_inventory_refuses_authored_protocol_schema(
    protocol_graph, protocol_role, changed
):
    kernel, graph = protocol_graph
    candidate = deepcopy(graph)
    view = _attached_language(kernel, graph)["language"]
    schema = deepcopy(
        next(
            row["schema"]
            for row in view["artifact_wire_schemas"]
            if row.get("protocol_role") == protocol_role
        )
    )
    if changed:
        member = "events" if protocol_role == "event-trace" else "formulas"
        schema["properties"]["renamed_rows"] = schema["properties"].pop(member)
        schema["required"][schema["required"].index(member)] = "renamed_rows"
    _definition(candidate, protocol_role)["schema"] = schema
    with pytest.raises(InventoryRefusal, match="wire protocol structure"):
        read_extension_inventory(kernel, candidate)


@pytest.mark.parametrize("mutation", ["missing-authored-schema", "duplicate-binding"])
def test_inventory_does_not_generalize_kernel_ownership_or_guess_binding(
    protocol_graph, protocol_role, mutation
):
    kernel, graph = protocol_graph
    candidate = deepcopy(graph)
    for package in candidate["packages"]:
        for closure in package["semantic_closure"]:
            if mutation == "missing-authored-schema":
                if closure["authority_path"] == "language.artifact_wire_schemas":
                    for row in closure["definitions"]:
                        if row.get("protocol_role") == "runtime-terminal-audit":
                            del row["schema"]
            elif closure["authority_path"] == "language.artifact_contracts":
                matches = [
                    row
                    for row in closure["definitions"]
                    if row["schema_kind"]
                    == _definition(candidate, protocol_role)["artifact_kind"]
                ]
                if matches:
                    duplicate = deepcopy(matches[0])
                    duplicate["artifact_kind"] += ".duplicate"
                    closure["definitions"].append(duplicate)
                    package["exports"]["artifact_contracts"].append(
                        duplicate["artifact_kind"]
                    )
    with pytest.raises(InventoryRefusal, match="wire protocol structure"):
        read_extension_inventory(kernel, candidate)
