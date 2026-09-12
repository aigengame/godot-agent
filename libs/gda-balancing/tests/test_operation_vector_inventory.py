"""Operation vector names follow formals; numeric expectations remain oracles."""

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    TokenOccurrence,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
    validate_token_bijection,
)
from schema2_extension_renaming_support import _rewrite_positions
from schema2_operation_execution_conformance_support import (
    _operation_index,
    candidate_conformance_failures,
    operation_execution_observations,
)
from schema2_operation_execution_production_support import (
    compile_operation_execution_harness,
)
from test_trace_protocol_structure import _authored, _graph, _index


def _vectors(graph):
    for vi, vector_set in enumerate(graph["vector_sets"]):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            if vector.get("kind") == "operation-execution":
                yield (
                    vector_set["package_id"],
                    vector,
                    f"/vector_sets/{vi}/vector_definitions/{di}",
                )


@pytest.fixture(scope="module")
def witness():
    kernel, language = mutable_authorities()
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert result["admitted"], result["diagnostics"]
    graph = _authored(language)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    return kernel, graph, inventory


def _admitted(kernel, authored):
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    language = _index(kernel, graph)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    return language, context


def _rename_scope(kernel, graph, inventory, names):
    # A bounded input-authoring witness; the complete-rename API still refuses
    # the unrelated gaps. Every edited location comes from the actual inventory.
    assert names.keys() <= inventory.tokens - inventory.reserved
    rows = [row for row in inventory.occurrences if row.token in names]
    assert {row.location for row in rows} <= {"key", "value"}
    candidate = _rewrite_positions(
        graph,
        {row.pointer: names[row.token] for row in rows if row.location == "value"},
        {row.pointer: names[row.token] for row in rows if row.location == "key"},
    )
    language, context = _admitted(kernel, candidate)
    renamed = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed)
    assert renamed.uncovered == inventory.uncovered
    assert (
        set(dict(token_bijection_from_names(inventory, names)).values())
        <= renamed.tokens
    )
    return candidate, language, context


def _observe(kernel, language, context, package, identifiers):
    vectors = {
        vector["id"]: vector
        for owner, vector, _ in _vectors(_authored(language))
        if owner == package and vector["id"] in identifiers
    }
    assert set(vectors) == identifiers
    operations = _operation_index(language)
    harnesses = {
        coordinate: compile_operation_execution_harness(
            context, coordinate, operations[coordinate]
        )
        for coordinate in {(package, v["operation"]) for v in vectors.values()}
    }
    return {
        identifier: operation_execution_observations(
            kernel,
            language,
            vector,
            context=context,
            package_id=package,
            harness=harnesses[(package, vector["operation"])],
        )
        for identifier, vector in vectors.items()
    }


def test_nominal_scalar_port_and_completion_rename_uses_real_execution(
    witness, tmp_path
):
    kernel, graph, inventory = witness
    names = {
        AuthorityToken(
            "operation-port",
            ("game.build", "game.build.replace-reward-v1"),
            "build_score",
        ): "points",
        AuthorityToken(
            "operation-outcome",
            ("game.build", "game.build.replace-reward-v1"),
            "replaced",
        ): "accepted",
        AuthorityToken("type", ("game.build",), "BuildState"): "OpaqueState",
        AuthorityToken("record-field", ("game.build", "BuildState"), "power"): "id",
        # The resulting Record has exactly {package, id}; its selected nominal
        # definition still owns both fields, not the Type-coordinate grammar.
        AuthorityToken("record-field", ("game.build", "BuildState"), "slot"): "package",
        AuthorityToken(
            "language.reasons", (), "game.build.reason.invalid-plan"
        ): "game.build.reason.bad-plan",
    }
    baseline, before_context = _admitted(kernel, deepcopy(graph))
    candidate, renamed, after_context = _rename_scope(kernel, graph, inventory, names)
    identifiers = {
        "build.replace.success",
        "build.replace.no-reward-outcome",
        "build.replace.invalid-plan-refusal",
    }
    observations = [
        _observe(kernel, language, context, "game.build", identifiers)
        for language, context in ((baseline, before_context), (renamed, after_context))
    ]
    assert all(
        result["expected"] == result["production"] == result["independent"]
        for graph_results in observations
        for result in graph_results.values()
    )

    # Scalar values, seed, draw bytes and every untouched expectation survive
    # authoring exactly. No actual output is relabelled to fabricate agreement.
    def numeric(value):
        if isinstance(value, dict):
            return [item for child in value.values() for item in numeric(child)]
        if isinstance(value, list):
            return [item for child in value for item in numeric(child)]
        return [value] if type(value) in {int, bool} else []

    assert numeric(graph["vector_sets"]) == numeric(candidate["vector_sets"])
    (tmp_path / "observations.json").write_bytes(
        canonical_bytes(cast(JsonValue, observations))
    )


@pytest.mark.parametrize(
    "surface", ["port", "nominal", "record", "enum", "outcome", "reason", "stream"]
)
@pytest.mark.parametrize("mutation", ["missing", "owner"])
def test_operation_vector_coverage_refuses_missing_and_misowned_links(
    witness, surface, mutation
):
    kernel, graph, inventory = witness
    role = {
        "port": "operation-port",
        "nominal": "type",
        "record": "record-field",
        "enum": "enum-member",
        "outcome": "operation-outcome",
        "reason": "language.reasons",
        "stream": "named-stream",
    }[surface]
    roots = {pointer for _, _, pointer in _vectors(graph)}
    selected = next(
        row
        for row in inventory.occurrences
        if row.token.role == role
        and any(row.pointer.startswith(root + "/") for root in roots)
    )
    rows = set(inventory.occurrences)
    rows.remove(selected)
    if mutation == "owner":
        rows.add(
            replace(selected, token=replace(selected.token, owner=("wrong-owner",)))
        )
    forged = replace(
        inventory,
        occurrences=tuple(sorted(rows)),
        tokens=frozenset(row.token for row in rows),
    )
    with pytest.raises(InventoryRefusal, match="Operation vector occurrence"):
        validate_extension_inventory(kernel, graph, forged)


def test_operation_vector_scalar_and_ref_key_values_are_not_name_guesses(witness):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    _, vector, pointer = next(
        row
        for row in _vectors(candidate)
        if row[1]["id"] == "structured.select.success"
    )
    # This is valid Ref instance data that happens to spell a declared Enum name.
    vector["input"]["values"][2]["value"]["value"]["key"] = "primary"
    _admitted(kernel, candidate)
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    opaque = pointer + "/input/values/2/value/value/key"
    scalar = pointer + "/input/values/4/value"
    assert not any(
        row.pointer == scalar or row.pointer == opaque and row.location == "value"
        for row in inventory.occurrences
    )
    token = AuthorityToken(
        "enum-member", ("standard.conformance.structured", "CandidateKind"), "primary"
    )
    assert token in inventory.tokens
    forged = replace(
        inventory,
        occurrences=(
            *inventory.occurrences,
            TokenOccurrence(token, opaque, "reference", "/meta_format/package_vector"),
        ),
    )
    with pytest.raises(InventoryRefusal, match="Operation vector occurrence"):
        validate_extension_inventory(kernel, candidate, forged)


def test_forged_numeric_expectation_admits_structure_but_fails_execution_oracle(
    witness, tmp_path
):
    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    package, vector, _ = next(
        row for row in _vectors(candidate) if row[1]["id"] == "build.replace.success"
    )
    original = deepcopy(vector)
    vector["expect"]["state_after"][-1]["value"] += 1
    language, _ = _admitted(kernel, candidate)
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    failures = candidate_conformance_failures(
        kernel, language, vector_coordinates={(package, vector["id"])}
    )
    assert len(failures) == 1
    failure = failures[0]
    assert failure["kind"] == "vector-divergence"
    assert failure["production"] == failure["independent"] == original["expect"]
    assert failure["expected"] != failure["production"]
    (tmp_path / "forged-numeric.json").write_bytes(
        canonical_bytes(cast(JsonValue, failures))
    )


def test_operation_port_bijection_cannot_omit_or_change_its_owner(witness):
    _, _, inventory = witness
    names = {
        token: f"renamed_{i}"
        for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
    }
    pairs = list(token_bijection_from_names(inventory, names))
    index = next(i for i, pair in enumerate(pairs) if pair[0].role == "operation-port")
    with pytest.raises(InventoryRefusal, match="complete inventory"):
        validate_token_bijection(inventory, pairs[:index] + pairs[index + 1 :])
    source, target = pairs[index]
    pairs[index] = source, replace(target, owner=("wrong-package", "wrong-operation"))
    with pytest.raises(InventoryRefusal, match="owner changed"):
        validate_token_bijection(inventory, pairs)


def test_operation_vector_stream_is_deterministic_entropy_not_a_numeric_alias(
    witness, tmp_path
):
    kernel, graph, inventory = witness
    language, context = _admitted(kernel, deepcopy(graph))
    identifiers = {"structured.select.success"}
    first = _observe(
        kernel, language, context, "standard.conformance.structured", identifiers
    )
    second = _observe(
        kernel, language, context, "standard.conformance.structured", identifiers
    )
    assert first == second
    result = first["structured.select.success"]
    assert result["expected"] == result["production"] == result["independent"]
    candidate, renamed, _ = _rename_scope(
        kernel,
        graph,
        inventory,
        {AuthorityToken("named-stream", (), "selection"): "renamed.selection"},
    )
    changed = next(v for _, v, _ in _vectors(candidate) if v["id"] in identifiers)
    original = next(v for _, v, _ in _vectors(graph) if v["id"] in identifiers)
    expected = deepcopy(original["expect"])
    expected["rng_draws"][0]["stream"] = "renamed.selection"
    assert changed["expect"] == expected  # No candidate, index or numeric rewrite.
    failures = candidate_conformance_failures(
        kernel,
        renamed,
        vector_coordinates={
            ("standard.conformance.structured", "structured.select.success")
        },
    )
    assert len(failures) == 1 and failures[0]["kind"] == "vector-divergence"
    assert failures[0]["production"] == failures[0]["independent"]
    assert failures[0]["production"] != failures[0]["expected"]
    (tmp_path / "stream-observations.json").write_bytes(
        canonical_bytes(
            cast(
                JsonValue, {"same_stream": [first, second], "renamed_stream": failures}
            )
        )
    )


def test_all_operation_execution_vectors_have_their_selected_owners(witness):
    kernel, graph, inventory = witness
    vectors = list(_vectors(graph))
    assert len(vectors) == 31
    rows = {(row.pointer, row.token) for row in inventory.occurrences}
    for package, vector, pointer in vectors:
        scope = (package, vector["operation"])
        assert (
            pointer + "/operation",
            AuthorityToken("language.operations", (package,), vector["operation"]),
        ) in rows
        for member, values in (
            ("input/values", vector["input"]["values"]),
            ("expect/state_after", vector["expect"]["state_after"]),
        ):
            for i, value in enumerate(values):
                assert (
                    f"{pointer}/{member}/{i}/name",
                    AuthorityToken("operation-port", scope, value["name"]),
                ) in rows
        completion = vector["expect"]["completion"]
        if completion["kind"] == "outcome":
            token = AuthorityToken("operation-outcome", scope, completion["id"])
            member = "id"
        else:
            token = AuthorityToken("language.reasons", (), completion["reason"])
            member = "reason"
        assert (pointer + "/expect/completion/" + member, token) in rows
    assert not any("operation-execution" in gap.reason for gap in inventory.uncovered)
    assert inventory.uncovered  # Model/rule/scheduler and wire slices stay open.
    with pytest.raises(InventoryRefusal, match="uncovered"):
        inventory.require_complete()
    validate_extension_inventory(kernel, graph, inventory)
