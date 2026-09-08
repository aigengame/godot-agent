"""Bounded authoring mechanics; full extension acceptance still requires closure."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.graph import LanguageBundleGraph
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    InventoryRefusal,
    _formula_projections,
    read_extension_inventory,
    token_bijection_from_names,
)
from schema2_extension_renaming_support import (
    _render_formulas,
    _reseal_authored_graph,
    _rewrite_positions,
    apply_extension_renaming,
)


@pytest.fixture(scope="module")
def authored_graph():
    kernel, language = mutable_authorities()
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
        "source": json.loads(
            (
                Path(__file__).parents[1]
                / "examples/schema2/progression-periodic-effect/model-source.json"
            ).read_bytes()
        ),
    }
    return kernel, graph


def test_simultaneous_key_swap_keeps_child_positions_and_user_strings():
    original = {"a": {"a": "a"}, "b": "b", "notes": ["a", "b"]}
    renamed = _rewrite_positions(
        original,
        {"/a/a": "renamed", "/b": "also-renamed"},
        {"/a": "b", "/b": "a", "/a/a": "child"},
    )
    assert renamed == {
        "b": {"child": "renamed"},
        "a": "also-renamed",
        "notes": ["a", "b"],
    }
    assert original == {"a": {"a": "a"}, "b": "b", "notes": ["a", "b"]}


@pytest.mark.parametrize("keys", [{"/a": "b"}, {"/a": "c", "/b": "c"}])
def test_key_collision_refuses_instead_of_dropping_a_member(keys):
    with pytest.raises(InventoryRefusal, match="collides"):
        _rewrite_positions({"a": 1, "b": 2}, {}, keys)


def test_positions_decode_json_pointer_escapes_and_array_indices():
    original = {"a/b~": [{"a/b~": "same spelling"}, "user text"]}
    assert _rewrite_positions(
        original,
        {"/a~1b~0/0/a~1b~0": "changed"},
        {"/a~1b~0": "outer", "/a~1b~0/0/a~1b~0": "inner"},
    ) == {"outer": [{"inner": "changed"}, "user text"]}


def test_incomplete_real_graph_cannot_authorize_renaming(authored_graph):
    kernel, graph = authored_graph
    before = deepcopy(graph)
    inventory = read_extension_inventory(kernel, graph)
    assert inventory.uncovered
    pairs = token_bijection_from_names(
        inventory,
        {
            token: f"renamed.token.{i}"
            for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
        },
    )
    with pytest.raises(InventoryRefusal, match="uncovered semantic role"):
        apply_extension_renaming(kernel, graph, pairs)
    assert graph == before


@pytest.mark.parametrize("miss_ast_reference", [False, True])
def test_formula_renaming_renders_actual_ast_and_detects_a_missed_reference(
    authored_graph, miss_ast_reference
):
    kernel, graph = authored_graph
    inventory = read_extension_inventory(kernel, graph)
    parameter = next(
        token
        for token in inventory.tokens
        if token.role == "source-formula-parameter" and token.name == "current_value"
    )
    occurrences = [o for o in inventory.occurrences if o.token == parameter]
    values = {o.pointer: "measured_value" for o in occurrences if o.location == "value"}
    candidate = _rewrite_positions(graph, values, {})
    bodies = _formula_projections(kernel, graph)
    if not miss_ast_reference:
        for pointer, body in bodies.items():
            edits = {
                o.projection: "measured_value"
                for o in occurrences
                if o.location == "formula" and o.pointer == pointer
            }
            bodies[pointer] = _rewrite_positions(body, edits, {})
    if miss_ast_reference:
        with pytest.raises(InventoryRefusal, match="body and expression disagree"):
            _render_formulas(kernel, candidate, bodies)
    else:
        _render_formulas(kernel, candidate, bodies)
        assert _formula_projections(kernel, candidate) == bodies
        assert "measured_value" in json.dumps(candidate["source"])
        assert "measured_value" not in json.dumps(graph["source"])


def test_resealing_current_authored_graph_preserves_exact_envelopes(authored_graph):
    kernel, graph = authored_graph
    candidate = deepcopy(graph)
    _reseal_authored_graph(kernel, candidate)
    assert candidate == graph


def test_changed_rule_binding_reseals_for_both_actual_authority_consumers(
    authored_graph,
):
    kernel, graph = authored_graph
    inventory = read_extension_inventory(kernel, graph)
    token = next(
        t
        for t in sorted(inventory.tokens)
        if t.role == "rule-variable"
        and any(o.token == t and o.use == "reference" for o in inventory.occurrences)
    )
    occurrences = [o for o in inventory.occurrences if o.token == token]
    assert {o.location for o in occurrences} == {"key", "value"}
    candidate = _rewrite_positions(
        graph,
        {o.pointer: "changed_binding" for o in occurrences if o.location == "value"},
        {o.pointer: "changed_binding" for o in occurrences if o.location == "key"},
    )
    _reseal_authored_graph(kernel, candidate)
    assert (
        candidate["ldb_root"]["content_identity"]
        != graph["ldb_root"]["content_identity"]
    )
    assert candidate["vector_sets"] == graph["vector_sets"]
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


@pytest.mark.parametrize("missing", ["vector", "descriptor", "duplicate-vector"])
def test_resealing_never_fabricates_omitted_package_members(authored_graph, missing):
    kernel, graph = authored_graph
    candidate = deepcopy(graph)
    if missing == "vector":
        candidate["vector_sets"].pop()
    elif missing == "descriptor":
        candidate["ldb_root"]["package_descriptors"].pop()
    else:
        candidate["vector_sets"].append(deepcopy(candidate["vector_sets"][0]))
    before = deepcopy(candidate)
    with pytest.raises(InventoryRefusal, match="membership do not close"):
        _reseal_authored_graph(kernel, candidate)
    assert candidate == before


def test_resealing_refuses_an_unsupported_explicit_kernel(authored_graph):
    kernel, graph = deepcopy(authored_graph)
    kernel["canonical_encoding"]["identity_algorithm"] = "sha512"
    with pytest.raises(InventoryRefusal, match="unsupported authored identity"):
        _reseal_authored_graph(kernel, graph)
