"""Replay checks reference actual Kernel members; policy names remain authored."""

from copy import deepcopy
from dataclasses import replace

import pytest

from gda_balancing.domain.authority.graph import LanguageBundleGraph
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from schema2_extension_renaming_support import (
    _reseal_authored_graph,
    _rewrite_positions,
)


@pytest.fixture(scope="module")
def replay_inventory():
    kernel, language = mutable_authorities()
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
    }
    return kernel, graph, read_extension_inventory(kernel, graph)


def test_replay_inventory_retains_policy_identity_and_closes_kernel_references(
    replay_inventory,
):
    kernel, graph, inventory = replay_inventory
    validate_extension_inventory(kernel, graph, inventory)
    policy = AuthorityToken(
        "language.replay_comparison_policies", (), "exact-replay-v1"
    )
    assert policy in inventory.tokens - inventory.reserved
    kind = next(
        row
        for row in kernel["meta_format"]["package_vector"]["kinds"]
        if row["id"] == "replay-comparison"
    )
    observed = [
        o
        for o in inventory.occurrences
        if o.token.role == "kernel.replay-observation-member"
        and o.pointer.startswith("/packages/")
    ]
    assert [o.token.name for o in sorted(observed, key=lambda o: o.pointer)] == kind[
        "observation_members"
    ]
    policy_pointer = next(
        o.pointer.removesuffix("/id")
        for o in inventory.occurrences
        if o.token == policy and o.use == "declaration"
    )
    assert not any(g.pointer == policy_pointer for g in inventory.uncovered)
    assert not any("replay-comparison" in gap.reason for gap in inventory.uncovered)
    assert inventory.uncovered  # Other unfinished roles are not waived.


@pytest.mark.parametrize("change", ["omitted", "misowned", "unreserved", "false-law"])
def test_replay_inventory_rederives_required_observation_roles(
    replay_inventory, change
):
    kernel, graph, inventory = replay_inventory
    selected = next(
        o
        for o in inventory.occurrences
        if o.token.role == "kernel.replay-observation-member"
    )
    rows = list(inventory.occurrences)
    tokens, reserved = set(inventory.tokens), set(inventory.reserved)
    if change == "omitted":
        rows = [row for row in rows if row.token != selected.token]
        tokens.remove(selected.token)
        reserved.remove(selected.token)
    elif change == "misowned":
        forged = replace(selected.token, owner=("invented-owner",))
        rows = [
            replace(row, token=forged) if row.token == selected.token else row
            for row in rows
        ]
        tokens.remove(selected.token)
        tokens.add(forged)
        reserved.remove(selected.token)
        reserved.add(forged)
    elif change == "unreserved":
        reserved.remove(selected.token)
    else:
        rows[rows.index(selected)] = replace(selected, law="/invented-law")
    forged_inventory = replace(
        inventory,
        occurrences=tuple(rows),
        tokens=frozenset(tokens),
        reserved=frozenset(reserved),
    )
    with pytest.raises(InventoryRefusal, match="Replay observation reference coverage"):
        validate_extension_inventory(kernel, graph, forged_inventory)


def test_inventoried_replay_policy_rename_closes_real_package_and_vector_consumers(
    replay_inventory,
):
    kernel, graph, inventory = replay_inventory
    policy = AuthorityToken(
        "language.replay_comparison_policies", (), "exact-replay-v1"
    )
    occurrences = [o for o in inventory.occurrences if o.token == policy]
    assert sum(o.pointer.endswith("/policy") for o in occurrences) == 2
    assert all(o.location == "value" for o in occurrences)
    candidate = _rewrite_positions(
        graph, {o.pointer: "renamed_replay_policy" for o in occurrences}, {}
    )
    _reseal_authored_graph(kernel, candidate)
    authored = LanguageBundleGraph(
        root=candidate["ldb_root"],
        package_releases=candidate["packages"],
        package_conformance_vector_sets=candidate["vector_sets"],
        root_byte_size=len(_encoded(candidate["ldb_root"])),
        package_byte_sizes=[len(_encoded(p)) for p in candidate["packages"]],
        vector_set_byte_sizes=[len(_encoded(v)) for v in candidate["vector_sets"]],
    )
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    assert policy not in renamed_inventory.tokens
    assert replace(policy, name="renamed_replay_policy") in renamed_inventory.tokens
