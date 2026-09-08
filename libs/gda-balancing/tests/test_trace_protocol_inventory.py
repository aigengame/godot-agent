"""Inventory the authored Trace binding without inventing a second schema owner."""

from copy import deepcopy

import pytest

from schema2_authority_support import mutable_authorities
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _attached_language,
    read_extension_inventory,
    validate_extension_inventory,
)
from test_trace_protocol_structure import (
    _authored,
    _graph,
    _rename_trace_kinds,
    _trace_definition,
)


@pytest.fixture(
    scope="module", params=[False, True], ids=["original", "distinct-kinds"]
)
def trace_graph(request):
    kernel, language = mutable_authorities()
    graph = _authored(language)
    if request.param:
        _rename_trace_kinds(graph)
    _graph(kernel, graph)
    return kernel, graph


def test_inventory_preserves_physical_graph_and_open_kind_names(
    trace_graph, monkeypatch
):
    kernel, graph = trace_graph
    original = deepcopy(graph)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("inventory used the production Trace schema projector")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.trace_projection.trace_protocol_schema",
        unavailable,
    )
    schema = _trace_definition(graph)
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
    assert graph == original


@pytest.mark.parametrize(
    "changed", [False, True], ids=["old-placement", "changed-shape"]
)
def test_inventory_refuses_authored_trace_schema(trace_graph, changed):
    kernel, graph = trace_graph
    candidate = deepcopy(graph)
    view = _attached_language(kernel, graph)["language"]
    schema = deepcopy(
        next(
            row["schema"]
            for row in view["artifact_wire_schemas"]
            if row.get("protocol_role") == "event-trace"
        )
    )
    if changed:
        schema["properties"]["trace_rows"] = schema["properties"].pop("events")
        schema["required"][schema["required"].index("events")] = "trace_rows"
    _trace_definition(candidate)["schema"] = schema
    with pytest.raises(InventoryRefusal, match="wire protocol structure"):
        read_extension_inventory(kernel, candidate)


@pytest.mark.parametrize("mutation", ["missing-authored-schema", "duplicate-binding"])
def test_inventory_does_not_generalize_kernel_ownership_or_guess_binding(
    trace_graph, mutation
):
    kernel, graph = trace_graph
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
                    == _trace_definition(candidate)["artifact_kind"]
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
