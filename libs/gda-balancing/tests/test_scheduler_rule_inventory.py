"""Scoped scheduler references and typed rule-vector Fact carriers."""

from copy import deepcopy
from dataclasses import replace

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    TokenOccurrence,
    _renamed_owner,
    read_extension_inventory,
    validate_extension_inventory,
)
from schema2_extension_renaming_support import _rewrite_positions
from schema2_scheduler_production_support import evaluate_runtime_scheduler_vector
from test_schema2_experiment_cli import _reference_evaluate_scheduler_vector
from test_trace_protocol_structure import _graph


@pytest.fixture(scope="module")
def witness():
    kernel, language = mutable_authorities()
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
    }
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert result["admitted"], result["diagnostics"]
    return kernel, graph, read_extension_inventory(kernel, graph)


def vectors(graph, family):
    return [
        (vector, f"/vector_sets/{si}/vector_definitions/{vi}")
        for si, group in enumerate(graph["vector_sets"])
        for vi, vector in enumerate(group["vector_definitions"])
        if (vector.get("kind") == family if family != "rule" else "rule" in vector)
    ]


def admit_pair(kernel, candidate):
    raw = _graph(kernel, candidate)
    results = [_consumer_a(kernel, raw), _consumer_b(kernel, raw)]
    assert all(result["admitted"] for result in results), results


def test_all_twelve_vectors_have_complete_scoped_references(witness):
    kernel, graph, inventory = witness
    validate_extension_inventory(kernel, graph, inventory)
    assert len(vectors(graph, "scheduler-scenario")) == 8
    assert len(vectors(graph, "rule")) == 4
    for vector, pointer in vectors(graph, "scheduler-scenario"):
        scope = (vector["id"],)
        for index, event in enumerate(vector["input"]["events"]):
            assert any(
                row.token == AuthorityToken("scheduler-event", scope, event["id"])
                and row.pointer == f"{pointer}/input/events/{index}/id"
                and row.use == "declaration"
                for row in inventory.occurrences
            )
    for vector, pointer in vectors(graph, "rule"):
        assert any(
            row.pointer == pointer + "/rule"
            and row.token == AuthorityToken("language.rules", (), vector["rule"])
            for row in inventory.occurrences
        )
    reasons = [
        gap.reason for gap in inventory.uncovered if gap.pointer == "/vector_sets"
    ]
    assert reasons == [
        "remaining vector families: operation-execution, source-or-rule-or-reason"
    ]
    assert inventory.uncovered  # Source Model vectors and other owners remain open.


@pytest.mark.parametrize("family", ["scheduler", "rule"])
@pytest.mark.parametrize(
    "change", ["omit", "owner", "role", "law", "phantom", "reserved"]
)
def test_reverse_check_refuses_forged_or_missing_vector_links(witness, family, change):
    kernel, graph, inventory = witness
    selected = next(
        row
        for row in inventory.occurrences
        if (
            row.token.role == "scheduler-event"
            if family == "scheduler"
            else row.pointer.endswith("/rule")
            and row.pointer.startswith("/vector_sets/")
        )
    )
    rows = list(inventory.occurrences)
    reserved = inventory.reserved
    if change == "reserved":
        reserved = reserved | {selected.token}
    elif change == "omit":
        rows.remove(selected)
    elif change == "owner":
        rows[rows.index(selected)] = replace(
            selected, token=replace(selected.token, owner=("wrong-vector",))
        )
    elif change == "role":
        rows[rows.index(selected)] = replace(
            selected, token=replace(selected.token, role="invented-role")
        )
    elif change == "law":
        rows[rows.index(selected)] = replace(selected, law="/invented-law")
    else:
        vector, pointer = vectors(graph, "rule")[0]
        value = vector["expect"]["fields"]["resolved_symbol"]["model"]
        rows.append(
            TokenOccurrence(
                AuthorityToken("source-model", (), value),
                pointer + "/expect/fields/resolved_symbol/model",
                "declaration",
                "/invented-law",
            )
        )
    changed = replace(
        inventory,
        occurrences=tuple(rows),
        tokens=frozenset(row.token for row in rows),
        reserved=reserved,
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, changed)


def test_coherent_scheduler_rename_preserves_both_real_scheduler_oracles(witness):
    kernel, graph, inventory = witness
    vector_tokens = {
        AuthorityToken("vectors", (), vector["id"])
        for vector, _ in vectors(graph, "scheduler-scenario")
    }
    rows = [
        row
        for row in inventory.occurrences
        if row.token.role in {"scheduler-event", "scheduler-scenario"}
        or row.token in vector_tokens
    ]
    assert rows
    names = {
        token: f"renamed_{index}"
        for index, token in enumerate(sorted({row.token for row in rows}))
    }
    candidate = _rewrite_positions(
        graph, {row.pointer: names[row.token] for row in rows}, {}
    )
    admit_pair(kernel, candidate)
    changed = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, changed)
    for vector, _ in vectors(candidate, "scheduler-scenario"):
        assert evaluate_runtime_scheduler_vector(kernel, vector) == vector["expect"]
        assert _reference_evaluate_scheduler_vector(kernel, vector) == vector["expect"]
        if vector["detects_mutation"] is not None:
            assert (
                evaluate_runtime_scheduler_vector(
                    kernel, vector, mutation=vector["detects_mutation"]
                )
                != vector["expect"]
            )
            assert (
                _reference_evaluate_scheduler_vector(
                    kernel, vector, mutation=vector["detects_mutation"]
                )
                != vector["expect"]
            )
    for token, name in names.items():
        if token.role in {"scheduler-event", "scheduler-scenario"}:
            assert (
                replace(
                    token,
                    name=name,
                    owner=(names[AuthorityToken("vectors", (), token.owner[0])],),
                )
                in changed.tokens
            )
    token = next(row.token for row in rows if row.token.role == "scheduler-event")
    vector = AuthorityToken("vectors", (), token.owner[0])
    assert _renamed_owner(token, {vector: replace(vector, name="renamed_vector")}) == (
        "renamed_vector",
    )


@pytest.mark.parametrize(
    "change", ["parent", "scenario", "expect-event", "missing-member"]
)
def test_scheduler_inventory_refuses_dangling_or_missing_addresses(witness, change):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    vector, _ = next(
        (v, p)
        for v, p in vectors(candidate, "scheduler-scenario")
        if v["expect"]["event_order"]
    )
    if change == "parent":
        vector["input"]["events"][0]["parent_id"] = "absent-event"
    elif change == "scenario":
        vector["input"]["events"][0]["scenario"] = "absent-scenario"
    elif change == "expect-event":
        vector["expect"]["event_order"][0] = "absent-event"
    else:
        del vector["input"]["events"][0]["scenario"]
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, candidate)


def test_scheduler_numeric_oracle_is_not_mistaken_for_token_coverage(witness):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    vector, _ = vectors(candidate, "scheduler-scenario")[0]
    vector["expect"]["terminal_states"][0]["value"] += 1
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    assert evaluate_runtime_scheduler_vector(kernel, vector) != vector["expect"]
    assert _reference_evaluate_scheduler_vector(kernel, vector) != vector["expect"]


def test_rule_carrier_coordinates_remain_opaque_while_real_refs_are_renamed(witness):
    kernel, graph, inventory = witness
    candidate = deepcopy(graph)
    for vector, _ in vectors(candidate, "rule"):
        for fact in [*vector["input"]["facts"], vector["expect"]]:
            fact["fields"]["type_identity"] = {
                "package": "opaque.unattached",
                "id": "UnattachedFixtureType",
            }
            fact["fields"]["resolved_symbol"]["model"] = "opaque.unattached-model"
            fact["fields"]["value_policy"] = {
                "opaque": [
                    "exact-int64",
                    {"package": "core.quantity", "id": "Quantity"},
                ]
            }
    admit_pair(kernel, candidate)
    opaque = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, opaque)
    assert not any(
        row.pointer.startswith("/vector_sets/")
        and any(
            part in row.pointer
            for part in ("/type_identity/", "/resolved_symbol/", "/value_policy/")
        )
        for row in opaque.occurrences
    )
    vector_tokens = {
        AuthorityToken("vectors", (), vector["id"])
        for vector, _ in vectors(candidate, "rule")
    }
    selected = {
        token
        for token in opaque.tokens
        if token.role
        in {"language.rules", "rule-judgment", "language.quantity.numeric_policies"}
        or token in vector_tokens
    }
    rows = [row for row in opaque.occurrences if row.token in selected]
    assert any(
        row.pointer.startswith("/vector_sets/")
        and row.pointer.endswith("/numeric_policy")
        for row in rows
    )
    names = {
        token: f"renamed_rule_owner_{index}"
        for index, token in enumerate(sorted(selected))
    }
    renamed = _rewrite_positions(
        candidate,
        {row.pointer: names[row.token] for row in rows if row.location == "value"},
        {},
    )
    admit_pair(kernel, renamed)
    validate_extension_inventory(
        kernel, renamed, read_extension_inventory(kernel, renamed)
    )
    for before, after in zip(
        vectors(candidate, "rule"), vectors(renamed, "rule"), strict=True
    ):
        assert (
            after[0]["expect"]["fields"]["value_policy"]
            == before[0]["expect"]["fields"]["value_policy"]
        )


@pytest.mark.parametrize(
    "change",
    [
        "rule",
        "judgment",
        "fact-kind",
        "inventory-member",
        "field-missing",
        "field-extra",
        "ambiguous-rule",
    ],
)
def test_rule_inventory_refuses_unresolved_or_malformed_actual_contracts(
    witness, change
):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    vector, _ = vectors(candidate, "rule")[0]
    if change == "ambiguous-rule":
        definitions = next(
            closure["definitions"]
            for package in candidate["packages"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.rules"
            and any(rule["id"] == vector["rule"] for rule in closure["definitions"])
        )
        duplicate = deepcopy(
            next(rule for rule in definitions if rule["id"] == vector["rule"])
        )
        duplicate["id"] += ".ambiguous"
        definitions.append(duplicate)
    elif change == "rule":
        vector["rule"] = "absent-rule"
    elif change == "judgment":
        vector["input"]["judgment"] = "absent-judgment"
    elif change == "fact-kind":
        vector["input"]["facts"][0]["kind"] = "absent-fact"
    elif change == "inventory-member":
        vector["input"]["facts"][0]["fields"]["numeric_policy"] = "absent-policy"
    elif change == "field-missing":
        del vector["expect"]["fields"]["role"]
    else:
        vector["expect"]["fields"]["unowned"] = "extra"
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, candidate)
