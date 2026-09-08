"""Owner and occurrence coverage for the evolving extension conformance reader."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
    validate_inventory_occurrences,
    validate_token_bijection,
)


@pytest.fixture(scope="module")
def witness():
    kernel, language = mutable_authorities()
    assert _consumer_a(kernel, language)["admitted"]
    assert _consumer_b(kernel, language)["admitted"]
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    graph = {
        "packages": deepcopy(language.package_releases),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
        "source": source,
    }
    inventory = read_extension_inventory(kernel, graph)
    return kernel, graph, inventory


def test_current_machine_owners_and_nested_lexical_scopes_are_preserved(witness):
    kernel, graph, inventory = witness
    validate_extension_inventory(kernel, graph, inventory)
    assert AuthorityToken("namespace", (), "standard.schema") in inventory.tokens
    assert AuthorityToken("namespace", (), "standard.schema") not in inventory.reserved
    type_token = AuthorityToken(
        "type", ("standard.conformance.structured",), "IntList4"
    )
    assert type_token in inventory.tokens
    assert not any(token.role == "language.nominal_types" for token in inventory.tokens)
    assert (
        AuthorityToken(
            "operation-port",
            ("standard.conformance.structured", "bounded.filter-step"),
            "item",
        )
        in inventory.tokens
    )
    assert (
        AuthorityToken(
            "operation-port",
            ("standard.conformance.structured", "bounded.count-step"),
            "item",
        )
        in inventory.tokens
    )
    assert (
        AuthorityToken(
            "operation-local",
            ("standard.conformance.structured", "bounded-fold-v1"),
            "filtered",
        )
        in inventory.tokens
    )
    assert (
        AuthorityToken("source-type-alias", ("example.bounded-fold", "fold"), "items")
        in inventory.tokens
    )
    assert (
        AuthorityToken("source-symbol", ("example.bounded-fold", "fold"), "items")
        in inventory.tokens
    )
    assert AuthorityToken("type", ("kernel",), "Boolean") in inventory.reserved


@pytest.mark.parametrize("mutation", ["class", "member", "role", "owner", "occurrence"])
def test_independent_coverage_refuses_removed_or_misowned_inventory(witness, mutation):
    kernel, graph, inventory = witness
    selected = next(
        token for token in inventory.tokens if token.role == "operation-port"
    )
    if mutation in {"class", "member"}:
        removed = (
            {token for token in inventory.tokens if token.role == selected.role}
            if mutation == "class"
            else {selected}
        )
        candidate = replace(
            inventory,
            tokens=inventory.tokens - removed,
            occurrences=tuple(
                o for o in inventory.occurrences if o.token not in removed
            ),
        )
    elif mutation in {"role", "owner"}:
        changed = (
            replace(selected, role="wrong-role")
            if mutation == "role"
            else replace(selected, owner=("wrong.owner", *selected.owner[1:]))
        )
        candidate = replace(
            inventory,
            tokens=(inventory.tokens - {selected}) | {changed},
            occurrences=tuple(
                replace(o, token=changed) if o.token == selected else o
                for o in inventory.occurrences
            ),
        )
    else:
        removed = next(
            o
            for o in inventory.occurrences
            if o.token == selected and o.use == "declaration"
        )
        candidate = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != removed),
        )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, candidate)


@pytest.mark.parametrize("mutation", ["extra", "duplicate"])
def test_occurrence_guard_refuses_unbound_or_repeated_positions(witness, mutation):
    _, graph, inventory = witness
    extra = inventory.occurrences[0]
    if mutation == "extra":
        extra = replace(extra, pointer="/source/manifest/id")
    candidate = replace(inventory, occurrences=(*inventory.occurrences, extra))
    with pytest.raises(InventoryRefusal):
        validate_inventory_occurrences(graph, candidate)


@pytest.mark.parametrize(
    "mutation", ["member", "extra", "source", "target", "reserved", "owner", "role"]
)
def test_bijection_refuses_missing_extra_duplicate_reserved_or_misowned_tokens(
    witness, mutation
):
    _, _, inventory = witness
    sources = sorted(inventory.tokens - inventory.reserved)
    pairs = list(
        token_bijection_from_names(
            inventory, {token: f"renamed_{i}" for i, token in enumerate(sources)}
        )
    )
    if mutation == "member":
        pairs.pop()
    elif mutation == "extra":
        pairs.append(
            (
                AuthorityToken("extra", (), "extra"),
                AuthorityToken("extra", (), "renamed_extra"),
            )
        )
    elif mutation == "source":
        pairs.append(pairs[0])
    elif mutation == "target":
        pairs[1] = (pairs[1][0], pairs[0][1])
    elif mutation == "reserved":
        pairs[0] = (pairs[0][0], next(iter(inventory.reserved)))
    elif mutation == "owner":
        pairs[0] = (pairs[0][0], replace(pairs[0][1], owner=("wrong.owner",)))
    else:
        pairs[0] = (pairs[0][0], replace(pairs[0][1], role="wrong-role"))
    with pytest.raises(InventoryRefusal) as error:
        validate_token_bijection(inventory, pairs)
    assert "uncovered" not in str(error.value)


def test_uncovered_roles_cannot_be_certified_by_a_self_consistent_mapping(witness):
    _, _, inventory = witness
    assert any(gap.pointer == "/vector_sets" for gap in inventory.uncovered)
    pairs = token_bijection_from_names(
        inventory,
        {
            token: f"renamed_{i}"
            for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
        },
    )
    with pytest.raises(InventoryRefusal, match="uncovered semantic role"):
        validate_token_bijection(inventory, pairs)
    with pytest.raises(InventoryRefusal, match="uncovered semantic role"):
        inventory.require_complete()


def test_unknown_runtime_node_or_member_is_never_silently_ignored(witness):
    kernel, graph, _ = witness
    for mutation in ("node", "member"):
        altered = deepcopy(graph)
        operation = next(
            entry["definitions"][0]
            for package in altered["packages"]
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "language.operations" and entry["definitions"]
        )
        instruction = operation["body"][0]
        if mutation == "node":
            instruction["node"] = "not-declared-in-kernel"
        else:
            instruction["unknown_callback"] = "hidden"
        with pytest.raises(InventoryRefusal, match="unknown runtime node"):
            read_extension_inventory(kernel, altered)
