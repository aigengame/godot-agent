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
    AuthorityToken,
    InventoryRefusal,
    _formula_projections,
    _pointer_value,
    _source_native_inventory,
    read_extension_inventory,
)
from schema2_extension_renaming_support import (
    _json_pointer_values,
    _renamed_pointer,
    _render_formulas,
    _reseal_authored_graph,
    _rewrite_positions,
    _rewrite_source_set_projections,
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


def test_dotted_keys_are_opaque_json_pointer_segments():
    original = {
        "outer.key": {"inner.key/~": "same.value"},
        "notes": "outer.key.inner.key/~",
    }
    assert _rewrite_positions(
        original,
        {"/outer.key/inner.key~1~0": "changed.value"},
        {"/outer.key": "inner.key/~", "/outer.key/inner.key~1~0": "outer.key"},
    ) == {
        "inner.key/~": {"outer.key": "changed.value"},
        "notes": "outer.key.inner.key/~",
    }
    assert original["outer.key"]["inner.key/~"] == "same.value"


def test_diagnostic_pointer_keeps_all_renamed_segments_and_equal_user_text():
    from schema2_extension_inventory_support import _pointer_value

    pointer = "/value/outer~1key~0/inner~0name"
    graph = {
        "value": {"outer/key~": {"inner~name": 3}},
        "diagnostic": pointer,
        "notes": pointer,
    }
    values = _json_pointer_values(
        graph, {"/diagnostic": {1: "inner~name", 2: "outer/key~"}}
    )
    changed = _rewrite_positions(
        graph,
        values,
        {"/value/outer~1key~0": "inner~name", pointer: "outer/key~"},
    )
    assert changed["diagnostic"] == "/value/inner~0name/outer~1key~0"
    assert _pointer_value(changed, changed["diagnostic"]) == 3
    assert changed["notes"] == graph["diagnostic"] == pointer


def test_source_native_occurrences_rename_simultaneously_and_round_trip(
    authored_graph,
):
    kernel, graph = authored_graph
    before = deepcopy(graph)
    inventory = read_extension_inventory(kernel, graph)
    inventory.require_complete()
    role = AuthorityToken("source-semantic-role", (), "operation-call")
    member = AuthorityToken(
        "source-semantic-member", ("operation-call",), "node"
    )
    discriminator = AuthorityToken(
        "source-discriminator", ("operation-call", "node"), "operation-call"
    )
    domain = AuthorityToken("language.quantity.domains", (), "closed-interval")
    derived_none = next(
        token
        for token in inventory.tokens
        if token.role == "assignment-mode"
        and token.owner[-1] == "derived"
        and token.name == "none"
    )
    output_none = next(
        token
        for token in inventory.tokens
        if token.role == "assignment-mode"
        and token.owner[-1] == "output"
        and token.name == "none"
    )
    correspondence = {
        role: AuthorityToken(role.role, (), "operation-invocation"),
        member: AuthorityToken(member.role, ("operation-invocation",), "dispatch"),
        discriminator: AuthorityToken(
            discriminator.role,
            ("operation-invocation", "dispatch"),
            "invoke-operation",
        ),
        domain: AuthorityToken(domain.role, (), "bounded-range"),
        derived_none: AuthorityToken(
            derived_none.role, derived_none.owner, "derived-none"
        ),
        output_none: AuthorityToken(
            output_none.role, output_none.owner, "output-none"
        ),
    }

    def rewrite(original, mapping, rows):
        values = {
            row.pointer: mapping[row.token].name
            for row in rows
            if row.token in mapping and row.location == "value"
        }
        candidate = _rewrite_positions(original, values, {})
        _rewrite_source_set_projections(
            kernel, original, candidate, {}, mapping
        )
        return candidate

    candidate = rewrite(graph, correspondence, inventory.occurrences)

    native = _source_native_inventory(kernel, candidate)
    assert len(native.set_projections) == 1
    pointer, tokens = next(iter(native.set_projections.items()))
    assert set(_pointer_value(candidate, pointer)) == {token.name for token in tokens}
    assert {"derived-none", "output-none"} <= set(_pointer_value(candidate, pointer))
    for row in inventory.occurrences:
        if row.token in correspondence and row.location == "value":
            assert _pointer_value(candidate, row.pointer) == correspondence[row.token].name

    reverse = {target: source for source, target in correspondence.items()}
    reverse_rows = tuple(
        row
        if row.token not in correspondence
        else type(row)(
            correspondence[row.token],
            row.pointer,
            row.use,
            row.law,
            row.location,
            row.projection,
        )
        for row in inventory.occurrences
    )
    restored = rewrite(candidate, reverse, reverse_rows)
    assert _encoded(restored) == _encoded(graph)
    assert graph == before


@pytest.mark.parametrize("rename_modules", [False, True])
@pytest.mark.parametrize("miss_ast_reference", [False, True])
def test_formula_renaming_renders_actual_ast_and_detects_a_missed_reference(
    authored_graph, miss_ast_reference, rename_modules
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
    keys = {}
    pointer_edits = {}
    if rename_modules:
        modules = next(
            token
            for token in inventory.tokens
            if token.role == "source-field"
            and len(token.owner) == 2
            and token.name == "modules"
        )
        for occurrence in inventory.occurrences:
            if occurrence.token == modules:
                assert occurrence.location in {"key", "value", "json-pointer"}
                if occurrence.location == "json-pointer":
                    pointer_edits.setdefault(occurrence.pointer, {})[
                        int(occurrence.projection)
                    ] = "opaque/modules~"
                else:
                    edits = keys if occurrence.location == "key" else values
                    edits[occurrence.pointer] = "opaque/modules~"
    values.update(_json_pointer_values(graph, pointer_edits))
    candidate = _rewrite_positions(graph, values, keys)
    bodies = _formula_projections(kernel, graph)
    if not miss_ast_reference:
        for pointer, body in bodies.items():
            edits = {
                o.projection: "measured_value"
                for o in occurrences
                if o.location == "formula" and o.pointer == pointer
            }
            bodies[pointer] = _rewrite_positions(body, edits, {})
    bodies = {_renamed_pointer(pointer, keys): body for pointer, body in bodies.items()}
    if miss_ast_reference:
        with pytest.raises(InventoryRefusal, match="does not close independently"):
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
