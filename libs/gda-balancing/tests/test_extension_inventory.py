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


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "duplicate-law"])
def test_occurrence_guard_refuses_unbound_or_repeated_positions(witness, mutation):
    kernel, graph, inventory = witness
    extra = inventory.occurrences[0]
    if mutation == "extra":
        extra = replace(extra, pointer="/source/manifest/id")
    elif mutation == "duplicate-law":
        extra = replace(extra, law="/another-law")
    candidate = replace(inventory, occurrences=(*inventory.occurrences, extra))
    with pytest.raises(InventoryRefusal):
        validate_inventory_occurrences(kernel, graph, candidate)


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


def test_all_current_runtime_node_references_have_explicit_identity_or_value_roles(
    witness,
):
    kernel, graph, _ = witness
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert not any(
        gap.reason.startswith("node roles not yet covered")
        for gap in inventory.uncovered
    )
    owner = ("game.combat", "game.combat.plan-casts-v1")
    canceled = AuthorityToken("operation-local", owner, "canceled_cast")
    assert any(
        o.token == canceled
        and o.pointer.endswith("/result/name")
        and o.use == "declaration"
        for o in inventory.occurrences
    )
    assert any(
        o.token == canceled
        and o.pointer.endswith("/event/local")
        and o.use == "reference"
        for o in inventory.occurrences
    )
    stream = AuthorityToken("named-stream", (), "selection")
    assert stream in inventory.tokens - inventory.reserved
    omitted = replace(
        inventory,
        tokens=inventory.tokens - {stream},
        occurrences=tuple(o for o in inventory.occurrences if o.token != stream),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, omitted)


def test_stream_identity_rename_preserves_execution_law_but_changes_entropy(witness):
    from gda_balancing.application.experiment_execution import (
        ExperimentExecutionRefusal,
        ExperimentExecutionSuccess,
        execute_checked_experiment,
    )
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.canonical import canonical_bytes
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from gda_balancing.domain.model import (
        AdmittedRir,
        CheckedModel,
        admit_rir,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_production_support import (
        _refresh_package_closure_and_reidentify,
    )
    from schema2_operation_execution_conformance_support import (
        independent_operation_execution_projection,
    )
    from schema2_operation_execution_independent_support import reference_rng_draw
    from schema2_operation_execution_production_support import (
        evaluate_operation_execution_vector,
    )

    example = Path(__file__).parents[1] / "examples/schema2/structured-selection"
    source = json.loads((example / "model-source.json").read_bytes())
    original_specification = json.loads((example / "experiment.json").read_bytes())
    source_bytes = canonical_bytes(source)
    unchanged_expectation = None
    observed = []
    for stream, expected_draw in (("selection", 0), ("renamed.selection", 1)):
        kernel, language = mutable_authorities()
        operation = next(
            op
            for op in language["language"]["operations"]
            if op["id"] == "standard.conformance.structured.select-v1"
        )
        draw = next(row for row in operation["body"] if row["node"] == "draw")
        assert draw["stream"] == "selection"
        draw["stream"] = stream
        _refresh_package_closure_and_reidentify(language)
        assert _consumer_a(kernel, language)["admitted"]
        assert _consumer_b(kernel, language)["admitted"]
        context = admit_authority_context(kernel, language)
        assert isinstance(context, AdmittedAuthorityContext), context
        checked_model = check_model_source_value(source, authority_context=context)
        assert isinstance(checked_model, CheckedModel), checked_model
        artifacts = compile_checked_model(checked_model)
        assert len(artifacts) == 8
        program = admit_rir(
            artifacts["rir-semantic-payload"], authority_context=context
        )
        assert isinstance(program, AdmittedRir), program
        specification = deepcopy(original_specification)
        specification["model"] = {"rir_semantic_identity": program.semantic_identity}
        specification["scenarios"][0]["named_streams"] = [stream]
        checked = check_experiment_value(
            specification, program, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        execution = execute_checked_experiment(checked)
        members = {
            name: json.loads(canonical_bytes(member.value))
            for name, member in execution.members.items()
        }
        assert validate_experiment_artifact_set(checked, members)
        independently_drawn = reference_rng_draw(
            kernel["meta_format"]["runtime_program"]["named_rng"],
            specification["seed"]["value"],
            stream,
            0,
            1,
            {},
            {},
        )
        assert independently_drawn["value"] == expected_draw
        vector = next(
            v for v in language["vectors"] if v["id"] == "structured.select.success"
        )
        if unchanged_expectation is None:
            unchanged_expectation = deepcopy(vector["expect"])
        assert vector["expect"] == unchanged_expectation
        operations = {
            (p["id"], op["id"]): op
            for p in language.package_releases
            for e in p["semantic_closure"]
            if e["authority_path"] == "language.operations"
            for op in e["definitions"]
        }
        production = evaluate_operation_execution_vector(
            context, vector, package_id="standard.conformance.structured"
        )
        independent = independent_operation_execution_projection(
            kernel, language, operations, "standard.conformance.structured", vector
        )
        assert production == independent
        if stream == "selection":
            assert isinstance(execution, ExperimentExecutionSuccess)
            actual_draw = members["event-trace"]["events"][0]["rng_draws"][0]
            assert actual_draw == independently_drawn
            assert production == unchanged_expectation
        else:
            assert isinstance(execution, ExperimentExecutionRefusal)
            assert (
                execution.report.stage == "runtime"
                and execution.report.variant == "post-dispatch"
            )
            assert [d.code for d in execution.report.diagnostics] == [
                "standard.conformance.candidate_mismatch"
            ]
            assert production["completion"] == {
                "kind": "refusal",
                "reason": "standard.conformance.reason.candidate-mismatch",
            }
            assert production != unchanged_expectation
            assert "runtime-terminal-audit" in members
        inventory = read_extension_inventory(
            kernel,
            {
                "packages": language.package_releases,
                "ldb_root": language.root,
                "vector_sets": language.package_conformance_vector_sets,
                "source": source,
            },
        )
        assert (
            AuthorityToken("named-stream", (), stream)
            in inventory.tokens - inventory.reserved
        )
        assert canonical_bytes(source) == source_bytes
        observed.append(
            (kernel["content_identity"], program.semantic_identity, production)
        )
    assert observed[0][0] == observed[1][0]
    assert observed[0][1] != observed[1][1]
    assert observed[0][2] != observed[1][2]


def test_kernel_references_do_not_reserve_language_owned_identities(witness):
    _, _, inventory = witness
    for role, name in (
        ("language.quantity.numeric_policies", "exact-int64"),
        ("language.constructors", "standard.schema.enum"),
        ("language.literal_typing_profiles", "standard.schema.nominal-structured"),
        ("language.reasons", "structured.reason.type-mismatch"),
        ("language.runtime_profiles", "standard.exact-int64-event-v1"),
    ):
        token = AuthorityToken(role, (), name)
        assert token in inventory.tokens - inventory.reserved
    assert AuthorityToken("namespace", (), "standard.schema") not in inventory.reserved
    assert AuthorityToken("type", ("kernel",), "Boolean") in inventory.reserved


def test_independent_formula_parser_follows_the_actual_schema_owner(witness):
    from schema2_bootstrap_conformance_support import _bind_package_vector_set
    from schema2_bootstrap_production_support import _reidentify_graph_root
    from schema2_formula_conformance_support import parse_canonical, render_body

    kernel, language = mutable_authorities()
    original = deepcopy(language)
    renamed_owner = "inventory.schema"
    packages = language["language"]["packages"]
    for package in packages:
        if package["id"] == "standard.schema":
            package["id"] = renamed_owner
        for kind in ("required", "optional"):
            package["dependencies"][kind] = [
                renamed_owner if name == "standard.schema" else name
                for name in package["dependencies"][kind]
            ]
    vectors = language.package_conformance_vector_sets
    for vector_set in vectors:
        if vector_set["package_id"] == "standard.schema":
            vector_set["package_id"] = renamed_owner
        for vector in vector_set["vector_definitions"]:
            if vector.get("kind") == "package-contract" and vector.get("probe") == {
                "path": "dependencies.required"
            }:
                vector["expect"] = [
                    renamed_owner if name == "standard.schema" else name
                    for name in vector["expect"]
                ]
    by_owner = {row["package_id"]: row for row in vectors}
    for package in packages:
        _bind_package_vector_set(package, by_owner[package["id"]])
    _reidentify_graph_root(language)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_bytes()
    )
    module = next(row for row in source["modules"] if row.get("formulas"))
    parsed_bodies = []
    for candidate in (original, language):
        a, b = _consumer_a(kernel, candidate), _consumer_b(kernel, candidate)
        assert a["admitted"] and b["admitted"], (a, b)
        for formula in module["formulas"]:
            request = {
                "schema_version": source["schema_version"],
                "package_requirements": source["package_requirements"],
                "module": module,
                "modules": source["modules"],
                "formula": formula,
            }
            parsed = parse_canonical(
                formula["expression"], request, candidate, kernel=kernel
            )
            parsed_bodies.append(parsed)
            assert render_body(parsed, request, candidate) == formula["expression"]
    assert (
        parsed_bodies[: len(module["formulas"])]
        == parsed_bodies[len(module["formulas"]) :]
    )


def test_formula_text_inventory_is_checked_by_independent_ast_projection(witness):
    kernel, graph, _ = witness
    graph = deepcopy(graph)
    graph["source"] = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_bytes()
    )
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    scope = ("example.progression-periodic-effect", "effect", "periodic-magnitude")
    # Use the authored model name, independent of the example directory name.
    scope = (graph["source"]["manifest"]["id"], *scope[1:])
    parameter = AuthorityToken("source-formula-parameter", scope, "current_value")
    formula_local = AuthorityToken("source-formula-local", scope, "raw_magnitude")
    assert {parameter, formula_local} <= inventory.tokens
    text = [
        o
        for o in inventory.occurrences
        if o.location == "formula" and o.token == parameter
    ]
    assert len(text) == 1
    assert text[0].pointer.endswith("/formulas/0/expression")
    assert text[0].projection == "/nodes/0/arguments/0/operand/parameter"
    changed = deepcopy(graph)
    formula = changed["source"]["modules"][0]["formulas"][0]
    formula["expression"] = formula["expression"].replace(
        "current_value - threshold", "threshold - current_value"
    )
    with pytest.raises(InventoryRefusal, match="Formula expression"):
        validate_inventory_occurrences(kernel, changed, inventory)
    assert not any(gap.reason.startswith("Formula text") for gap in inventory.uncovered)


def test_formula_reference_coverage_refuses_erased_or_misowned_text_occurrences(
    witness,
):
    kernel, graph, _ = witness
    graph = deepcopy(graph)
    graph["source"] = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_bytes()
    )
    inventory = read_extension_inventory(kernel, graph)
    original = next(
        o
        for o in inventory.occurrences
        if o.location == "formula" and o.token.role == "source-formula-parameter"
    )
    for replacement in (
        None,
        replace(
            original,
            token=replace(
                original.token, owner=(*original.token.owner[:2], "other-formula")
            ),
        ),
    ):
        kept = tuple(o for o in inventory.occurrences if o != original)
        if replacement is not None:
            kept += (replacement,)
        candidate = replace(
            inventory, occurrences=kept, tokens=frozenset(o.token for o in kept)
        )
        with pytest.raises(InventoryRefusal, match="Formula .*coverage"):
            validate_extension_inventory(kernel, graph, candidate)


@pytest.mark.parametrize(
    "role,pointer_suffix",
    [
        ("language.rules", "/rule"),
        ("language.resolution_profiles", "/profiles/resolution/0"),
        ("language.quantity.numeric_policies", "/numeric_policy/const"),
    ],
)
def test_machine_reference_and_schema_equality_laws_require_every_occurrence(
    witness, role, pointer_suffix
):
    kernel, graph, inventory = witness
    selected = next(
        o
        for o in inventory.occurrences
        if o.token.role == role and o.pointer.endswith(pointer_suffix)
    )
    remaining = tuple(o for o in inventory.occurrences if o.pointer != selected.pointer)
    incomplete = replace(
        inventory, occurrences=remaining, tokens=frozenset(o.token for o in remaining)
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, incomplete)


def test_declared_runtime_effects_are_owned_names_and_diagnostics_keep_stage_syntax(
    witness,
):
    _, _, inventory = witness
    for name in ("event.commit", "event.schedule", "metric.observe", "snapshot.commit"):
        token = AuthorityToken("runtime-effect", (), name)
        assert token in inventory.tokens - inventory.reserved
        assert any(
            o.token == token and o.use == "declaration" for o in inventory.occurrences
        )
        assert any(
            o.token == token and o.use == "reference" for o in inventory.occurrences
        )
    assert not any(
        gap.reason == "nested diagnostics roles are not yet traversed"
        for gap in inventory.uncovered
    )
    assert not any(
        gap.reason == "nested language.reasons roles are not yet traversed"
        for gap in inventory.uncovered
    )
    assert not any("signal" in gap.reason for gap in inventory.uncovered)


@pytest.mark.parametrize("reason_id", ["step-limit", "2.0.0"])
def test_primitive_signal_reservation_does_not_capture_same_spelling_other_roles(
    witness,
    reason_id,
):
    from schema2_bootstrap_conformance_support import _bind_package_vector_set
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    owner = next(
        p
        for p in language["language"]["packages"]
        if p["id"] == "standard.conformance.structured"
    )
    closure = {
        row["authority_path"]: row["definitions"] for row in owner["semantic_closure"]
    }
    owner["exports"]["reasons"].append(reason_id)
    owner["exports"]["diagnostics"].append("inventory.signal-role")
    closure["language.reasons"].append(
        {
            "id": reason_id,
            "diagnostic": "inventory.signal-role",
            "stage": "approval",
            "signal": "step-limit",
            "predicate": {"operation": "not-equal"},
        }
    )
    closure["diagnostics"].append(
        {"code": "inventory.signal-role", "stage": "approval"}
    )
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == owner["id"]
    )
    for matched in (False, True):
        name = "inventory.signal-role." + str(matched).lower()
        vectors["vectors"].append(name)
        vectors["vector_definitions"].append(
            {
                "id": name,
                "reason": reason_id,
                "diagnostic": "inventory.signal-role",
                "stage": "approval",
                "input": {"actual": int(matched), "expected": 0},
                "matched": matched,
            }
        )
    _bind_package_vector_set(owner, vectors)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
    }
    inventory = read_extension_inventory(kernel, graph)
    assert (
        AuthorityToken("diagnostic-signal", ("runtime",), "step-limit")
        in inventory.reserved
    )
    assert (
        AuthorityToken("diagnostic-signal", ("approval",), "step-limit")
        in inventory.tokens - inventory.reserved
    )
    assert (
        AuthorityToken("language.reasons", (), reason_id)
        in inventory.tokens - inventory.reserved
    )
    assert not any(
        token.role == "language.model_source_schema_versions"
        for token in inventory.tokens | inventory.reserved
    )


def test_source_format_parameters_stay_bound_to_declared_wire_format(witness):
    kernel, graph, inventory = witness
    assert not any(
        token.role == "language.model_source_schema_versions"
        for token in inventory.tokens | inventory.reserved
    )
    graph = deepcopy(graph)
    format_definitions = next(
        closure["definitions"]
        for package in graph["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_source_schema_versions"
        and closure["definitions"]
    )
    format_definitions[0] = "different-format"
    with pytest.raises(InventoryRefusal, match="format parameter"):
        read_extension_inventory(kernel, graph)
    with pytest.raises(InventoryRefusal, match="format parameter"):
        validate_extension_inventory(kernel, graph, inventory)


def test_type_id_projection_edges_preserve_all_actual_nominal_owners(witness):
    from schema2_bootstrap_production_support import (
        _append_empty_namespace,
        _reidentify_graph_root,
    )

    kernel, language = mutable_authorities()
    original = next(
        p
        for p in language["language"]["packages"]
        if p["id"] == "standard.conformance.structured"
    )
    package = _append_empty_namespace(language, "inventory.otheritems")
    package["runtime_semantic_paths"] = ["language.nominal_types"]
    package["dependencies"]["required"] = ["core.quantity", "standard.schema"]
    exported = deepcopy(
        next(t for t in original["exports"]["types"] if t["id"] == "IntList4")
    )
    nominal = deepcopy(
        next(
            d
            for c in original["semantic_closure"]
            if c["authority_path"] == "language.nominal_types"
            for d in c["definitions"]
            if d["id"] == "IntList4"
        )
    )
    nominal["definition"]["maximum_length"] = 2
    package["exports"]["types"].append(exported)
    package["exports"]["nominal_types"].append("IntList4")
    next(
        c
        for c in package["semantic_closure"]
        if c["authority_path"] == "language.nominal_types"
    )["definitions"].append(nominal)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
    }
    inventory = read_extension_inventory(kernel, graph)
    owners = {
        AuthorityToken("type", (name,), "IntList4")
        for name in ("standard.conformance.structured", "inventory.otheritems")
    }
    assert owners <= inventory.tokens
    by_pointer = {}
    for occurrence in inventory.occurrences:
        if occurrence.pointer.endswith("/owner_type") and occurrence.token in owners:
            by_pointer.setdefault(occurrence.pointer, set()).add(occurrence.token)
    assert by_pointer and all(tokens == owners for tokens in by_pointer.values())
    actual_pointer = next(iter(by_pointer))
    withheld = next(
        o
        for o in inventory.occurrences
        if o.pointer == actual_pointer and o.token in owners
    )
    incomplete = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != withheld)
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, incomplete)
    assert not any(
        gap.reason == "Operation owner_type links are not yet complete"
        for gap in inventory.uncovered
    )
    pairs = token_bijection_from_names(
        inventory,
        {
            token: "name_" + str(i)
            for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
        },
    )
    with pytest.raises(InventoryRefusal, match="shared authored reference"):
        validate_token_bijection(inventory, pairs)


def test_rule_variables_follow_bind_keys_and_keep_rule_scopes(witness):
    from schema2_bootstrap_conformance_support import _reidentify_package_release
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    rules = [
        rule
        for package in language["language"]["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.rules"
        for rule in closure["definitions"]
        if rule["id"] in {"quantity.declare", "quantity.lower"}
    ]
    assert len(rules) == 2
    for rule in rules:
        bind = rule["premises"][0]["bind"]
        bind["shared_variable"] = bind.pop("domain")
        rule["conclusion"]["fields"]["domain"]["name"] = "shared_variable"
    for package in language["language"]["packages"]:
        _reidentify_package_release(package)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
    }
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    tokens = {
        AuthorityToken("rule-variable", (rule["id"],), "shared_variable")
        for rule in rules
    }
    assert tokens <= inventory.tokens - inventory.reserved
    for token in tokens:
        occurrences = [o for o in inventory.occurrences if o.token == token]
        assert {(o.use, o.location) for o in occurrences} == {
            ("declaration", "key"),
            ("reference", "value"),
        }
        declaration = next(o for o in occurrences if o.use == "declaration")
        assert declaration.pointer.endswith("/bind/shared_variable")
        broken = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != declaration),
        )
        with pytest.raises(InventoryRefusal, match="rule binding"):
            validate_extension_inventory(kernel, graph, broken)
    assert not any("nested language.rules" in gap.reason for gap in inventory.uncovered)


@pytest.mark.parametrize(
    "role", ["operation-slot", "operation-slot-parameter", "source-formula-parameter"]
)
def test_formula_binding_inventory_closes_real_slots_and_independently_detects_omissions(
    witness, role
):
    kernel, graph, _ = witness
    graph = deepcopy(graph)
    graph["source"] = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_bytes()
    )
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert not any(
        gap.pointer == "/source/formula_bindings" for gap in inventory.uncovered
    )
    scope = (
        "game.effect",
        "game.effect.apply-snapshot-periodic-v1",
        "magnitude-policy",
    )
    assert (
        AuthorityToken("operation-slot-parameter", scope, "current_value")
        in inventory.tokens
    )
    assert (
        AuthorityToken("operation-port", scope[:2], "target_health") in inventory.tokens
    )
    # These equal-spelling parameters belong to separate Operation slot scopes.
    assert (
        AuthorityToken(
            "operation-slot-parameter",
            ("game.effect", "game.effect.tick-live-periodic-v1", "magnitude-policy"),
            "current_value",
        )
        in inventory.tokens
    )
    occurrence = next(
        o
        for o in inventory.occurrences
        if o.token.role == role
        and o.pointer.startswith("/source/formula_bindings/")
        and o.use == "reference"
    )
    incomplete = replace(
        inventory,
        occurrences=tuple(o for o in inventory.occurrences if o != occurrence),
    )
    with pytest.raises(
        InventoryRefusal, match="Formula declaration or reference coverage"
    ):
        validate_extension_inventory(kernel, graph, incomplete)
    assert any(
        o.token.role == "operation-notation" and o.token.name == "max"
        for o in inventory.occurrences
    )
    assert any(
        o.token.role == "formula-fixed-alias" and o.token.name == "Boolean"
        for o in inventory.occurrences
    )


def test_constructor_member_addresses_are_closed_and_dimension_identity_is_covered(
    witness,
):
    kernel, graph, _ = witness
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    dimension = AuthorityToken("unit-dimension", (), "dimensionless")
    assert dimension in inventory.tokens - inventory.reserved
    without_dimension = replace(
        inventory,
        tokens=inventory.tokens - {dimension},
        occurrences=tuple(o for o in inventory.occurrences if o.token != dimension),
    )
    with pytest.raises(InventoryRefusal, match="missing or incorrectly owned"):
        validate_extension_inventory(kernel, graph, without_dimension)
    assert not any(
        gap.reason
        in {
            "nested language.quantity.units roles are not yet traversed",
            "nested language.components roles are not yet traversed",
            "nested language.constructors roles are not yet traversed",
            "nested language.structured_operations roles are not yet traversed",
        }
        for gap in inventory.uncovered
    )
    changed = deepcopy(graph)
    nominal = next(
        definition
        for package in changed["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.nominal_types"
        for definition in closure["definitions"]
    )
    nominal["definition"]["unclassified"] = "dimensionless"
    with pytest.raises(InventoryRefusal, match="undeclared members"):
        read_extension_inventory(kernel, changed)
