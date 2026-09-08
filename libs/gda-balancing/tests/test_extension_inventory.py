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
    production = _consumer_a(kernel, language)
    independent = _consumer_b(kernel, language)
    assert production["admitted"], production["diagnostics"]
    assert independent["admitted"], independent["diagnostics"]
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
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
        with pytest.raises(
            InventoryRefusal, match="independent Operation composition did not close"
        ):
            read_extension_inventory(kernel, altered)


def test_source_entrypoint_and_ordinary_invocation_bind_their_actual_owners(witness):
    _, graph, inventory = witness
    entry = AuthorityToken("source-entrypoint", ("example.bounded-fold",), "fold")
    assert entry in inventory.tokens
    assert any(
        o.token.role == "operation-port"
        and o.pointer.startswith("/source/entrypoints/0/arguments/")
        for o in inventory.occurrences
    )
    for package in graph["packages"]:
        for entry in package["semantic_closure"]:
            if entry["authority_path"] != "language.operations":
                continue
            for operation in entry["definitions"]:
                for instruction in operation["body"]:
                    if instruction["node"] == "invoke":
                        site = AuthorityToken(
                            "operation-site",
                            (package["id"], operation["id"]),
                            instruction["site"],
                        )
                        assert site in inventory.tokens


@pytest.mark.parametrize("surface", ["root", "vector", "entrypoint", "callee"])
def test_independent_coverage_detects_omitted_graph_root_vector_and_source_links(
    witness, surface
):
    kernel, graph, inventory = witness
    predicates = {
        "root": lambda o: o.pointer.startswith("/ldb_root/package_descriptors/"),
        "vector": lambda o: (
            o.pointer.startswith("/vector_sets/") and o.use == "declaration"
        ),
        "entrypoint": lambda o: o.token.role == "source-entrypoint",
        "callee": lambda o: o.pointer == "/source/entrypoints/0/arguments/0/port",
    }
    omitted = next(o for o in inventory.occurrences if predicates[surface](o))
    altered = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != omitted)
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, altered)


def test_enum_member_and_same_spelling_ref_key_keep_distinct_meanings(witness):
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )

    kernel, graph, _ = witness
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/structured-selection/model-source.json"
        ).read_text()
    )
    arguments = source["entrypoints"][0]["arguments"]
    enum = next(
        a["operand"]["value"] for a in arguments if a["port"] == "expected_kind"
    )
    reference = next(
        a["operand"]["value"] for a in arguments if a["port"] == "expected_key"
    )
    reference["value"]["key"] = enum["value"]
    checked = check_model_source_value(source)
    assert isinstance(checked, CheckedModel), checked
    assert len(compile_checked_model(checked)) == 8
    candidate = {**graph, "source": source}
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    enum_path = "/source/entrypoints/0/arguments/1/operand/value/value"
    ref_path = "/source/entrypoints/0/arguments/2/operand/value/value/key"
    token = AuthorityToken(
        "enum-member", ("standard.conformance.structured", "CandidateKind"), "primary"
    )
    assert any(
        o.token == token and o.pointer == enum_path for o in inventory.occurrences
    )
    assert not any(o.pointer == ref_path for o in inventory.occurrences)
    assert reference["value"]["key"] == "primary"


def test_lookup_roles_use_closed_independent_types_and_real_guard_paths(witness):
    from schema2_bootstrap_conformance_support import (
        _consumer_b_operation_composition_subjects,
    )
    from schema2_bootstrap_production_support import (
        _refresh_package_closure_and_reidentify,
    )

    kernel, language = mutable_authorities()
    operation = next(
        op
        for op in language["language"]["operations"]
        if op["id"] == "standard.conformance.structured.select-v1"
    )
    for instruction in operation["body"]:
        if instruction["node"] == "draw":
            instruction["target"] = "kind"
        if instruction["node"] == "lookup" and instruction["key"] == "selected_index":
            instruction["key"] = "kind"
    operation["body"][4]["body"].insert(
        0,
        {
            "node": "lookup",
            "value": "selection_state",
            "key": "results",
            "target": "guard_results",
        },
    )
    operation["resource_bounds"]["max_steps"] += 1
    bound_vector = next(
        vector
        for vector_set in language.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "structured.select.resource-bound"
    )
    assert bound_vector["probe"] == {"path": "resource_bounds.max_steps"}
    bound_vector["expect"] = 22
    _refresh_package_closure_and_reidentify(language)
    production = _consumer_a(kernel, language)
    independent = _consumer_b(kernel, language)
    assert production["admitted"], production["diagnostics"]
    assert independent["admitted"], independent["diagnostics"]
    before = deepcopy(language)
    projected = {}
    assert (
        _consumer_b_operation_composition_subjects(
            kernel, language, operand_contracts=projected
        )
        == ()
    )
    owner = ("standard.conformance.structured", operation["id"])
    assert projected[owner, (6,), "value"][0]["type"]["kind"] == "list"
    assert projected[owner, (8,), "value"][0]["type"]["id"] == "Candidate"
    assert projected[owner, (4, 0), "value"][0]["type"]["id"] == "SelectionState"
    assert all("#guard-" not in coordinate[1] for coordinate, _, _ in projected)
    graph = {
        "packages": language.package_releases,
        "vector_sets": language.package_conformance_vector_sets,
        "ldb_root": language.root,
        "source": witness[1]["source"],
    }
    inventory = read_extension_inventory(kernel, graph)
    local = AuthorityToken("operation-local", owner, "kind")
    field = AuthorityToken("record-field", (owner[0], "Candidate"), "kind")
    assert any(
        o.token == local and o.pointer.endswith("/body/6/key")
        for o in inventory.occurrences
    )
    assert any(
        o.token == field and o.pointer.endswith("/body/8/key")
        for o in inventory.occurrences
    )
    assert any(
        o.token.role == "record-field" and o.pointer.endswith("/body/4/body/0/key")
        for o in inventory.occurrences
    )
    assert not any("lookup" in gap.reason for gap in inventory.uncovered)
    projected[owner, (6,), "value"][0]["type"]["kind"] = "caller-mutation"
    assert language == before
    second = {}
    assert (
        _consumer_b_operation_composition_subjects(
            kernel, language, operand_contracts=second
        )
        == ()
    )
    assert second[owner, (6,), "value"][0]["type"]["kind"] == "list"
    invalid = deepcopy(language)
    invalid_operation = next(
        op
        for package in invalid["language"]["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
        for op in entry["definitions"]
        if op["id"] == owner[1]
    )
    invalid_operation["body"][6]["value"] = "unbound"
    refused_projection = {}
    assert _consumer_b_operation_composition_subjects(
        kernel, invalid, operand_contracts=refused_projection
    )
    assert refused_projection == {}


@pytest.mark.parametrize("location", ["root", "module", "symbol"])
def test_unrecognized_source_member_cannot_disappear_from_inventory(witness, location):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    source = candidate["source"]
    target = {
        "root": source,
        "module": source["modules"][0],
        "symbol": source["modules"][0]["symbols"][0],
    }[location]
    target["undeclared_semantic_reference"] = "fold"
    with pytest.raises(InventoryRefusal, match="closed wire schema"):
        read_extension_inventory(kernel, candidate)
