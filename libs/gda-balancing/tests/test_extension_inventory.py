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
    source_formula_requests,
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


@pytest.mark.parametrize("unchanged", ["all", "one"])
def test_bijection_requires_each_non_kernel_name_to_change(witness, unchanged):
    _, _, inventory = witness
    assert inventory.uncovered  # This isolated map check does not waive real gaps.
    names = {
        token: f"renamed.token.{i}"
        for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
    }
    if unchanged == "all":
        names = {token: token.name for token in names}
    else:
        token = next(iter(names))
        names[token] = token.name
    with pytest.raises(InventoryRefusal, match="name unchanged"):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )


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
    assert not any(
        o.pointer == ref_path and o.location == "value" for o in inventory.occurrences
    )
    assert any(
        o.pointer == ref_path
        and o.location == "key"
        and o.token.role == "constructor-member"
        for o in inventory.occurrences
    )
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


def test_operation_inventory_uses_current_closed_definition_contract(witness):
    kernel, graph, _ = witness
    changed = deepcopy(graph)
    operation = next(
        definition
        for package in changed["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
    )
    shape = kernel["meta_format"]["language_definitions"]["collections"]["operations"]
    assert "unknown_reference" not in (
        shape["required_members"] + shape.get("optional_members", [])
    )
    operation["unknown_reference"] = "Quantity"
    with pytest.raises(InventoryRefusal, match="Operation.*Kernel contract"):
        read_extension_inventory(kernel, changed)


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


def test_lawful_constructor_selector_rename_keeps_every_address_owned(witness):
    from schema2_extension_renaming_support import (
        _reseal_authored_graph,
        _rewrite_positions,
    )

    kernel, original, original_inventory = witness
    constructor = next(
        definition
        for package in original["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.constructors"
        for definition in closure["definitions"]
        if definition.get("value_rule", {}).get("operator") == "enum-member"
    )
    original_token = AuthorityToken(
        "constructor-member", (constructor["id"], "definition"), "members"
    )
    addresses = [o for o in original_inventory.occurrences if o.token == original_token]
    keys = [o for o in addresses if o.location == "key"]
    # The selector addresses nominal definitions and all three anonymous Enum
    # declarations in actual vector inputs. Neither surface may retain old keys.
    assert len([o for o in keys if o.pointer.startswith("/vector_sets/")]) == 3
    graph = _rewrite_positions(
        original,
        {o.pointer: "labels" for o in addresses if o.location == "value"},
        {o.pointer: "labels" for o in keys},
    )
    _reseal_authored_graph(kernel, graph)
    _assert_structured_graph_observations(kernel, graph, original=original)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    token = replace(original_token, name="labels")
    assert token in inventory.tokens - inventory.reserved
    declarations = [
        o for o in inventory.occurrences if o.token == token and o.use == "declaration"
    ]
    renamed_keys = [
        o for o in inventory.occurrences if o.token == token and o.location == "key"
    ]
    assert len(declarations) == 1 and len(renamed_keys) == len(keys)
    incomplete = replace(
        inventory,
        occurrences=tuple(o for o in inventory.occurrences if o != renamed_keys[0]),
    )
    with pytest.raises(InventoryRefusal, match="constructor address"):
        validate_extension_inventory(kernel, graph, incomplete)


def test_assignment_modes_follow_selected_policy_and_symbol_role(witness):
    kernel, graph, inventory = witness
    modes = {
        token
        for token in inventory.tokens
        if token.role == "assignment-mode" and token.name == "none"
    }
    assert {token.owner[-1] for token in modes} == {"derived", "output"}
    assert not modes & inventory.reserved
    reference = next(
        o
        for o in inventory.occurrences
        if o.token.role == "assignment-mode"
        and o.pointer.startswith("/source/")
        and o.use == "reference"
    )
    without = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != reference)
    )
    with pytest.raises(InventoryRefusal, match="missing or incorrectly owned"):
        validate_extension_inventory(kernel, graph, without)
    incomplete_class = replace(
        inventory,
        tokens=frozenset(t for t in inventory.tokens if t.role != "assignment-mode"),
        occurrences=tuple(
            o for o in inventory.occurrences if o.token.role != "assignment-mode"
        ),
    )
    with pytest.raises(InventoryRefusal, match="missing or incorrectly owned"):
        validate_extension_inventory(kernel, graph, incomplete_class)


def test_source_value_policy_uses_its_scalar_wire_contract(witness):
    from gda_balancing.domain.model import CheckedModel, check_model_source_value

    kernel, graph, _ = witness
    candidate = deepcopy(graph)
    symbol = candidate["source"]["modules"][0]["symbols"][2]
    symbol["value_policy"] = {"mode": "model-fixed", "value": 3}
    checked = check_model_source_value(candidate["source"])
    assert isinstance(checked, CheckedModel), checked
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    assert not any(
        o.pointer.startswith("/source/modules/0/symbols/2/value_policy/value")
        for o in inventory.occurrences
    )

    # These could be ordinary Record field names elsewhere. This position is
    # closed by the admitted Source schema to an integer, never an envelope.
    symbol["value_policy"]["value"] = {"type": "state", "value": "items"}
    refused = check_model_source_value(candidate["source"])
    assert not isinstance(refused, CheckedModel), refused
    assert any(
        diagnostic.primary.kind == "artifact"
        and diagnostic.primary.pointer.endswith("/symbols/2/value_policy/value")
        for diagnostic in refused.diagnostics
    )
    with pytest.raises(InventoryRefusal, match="closed wire schema"):
        read_extension_inventory(kernel, candidate)


def test_projection_collection_names_follow_native_roots_and_not_output_members():
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_conformance_support import _reidentify_package_release
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    lowering = next(
        definition
        for package in language["language"]["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_lowerings"
        for definition in closure["definitions"]
    )
    projection = lowering["runtime_projection"]
    original = projection["operation_roots"]["collection"]
    renamed = "opaque.operation.collection"
    selected = next(c for c in projection["collections"] if c["id"] == original)
    output_member = selected["output_member"]
    selected["id"] = renamed
    projection["operation_roots"]["collection"] = renamed
    for seed in projection["seeds"]:
        if seed["collection"] == original:
            seed["collection"] = renamed
    for edge in projection["edges"]:
        for member in ("source_collection", "target_collection"):
            if edge[member] == original:
                edge[member] = renamed
    for package in language["language"]["packages"]:
        _reidentify_package_release(package)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert len(compile_checked_model(checked)) == 8
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
        "source": source,
    }
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    names = {
        token for token in inventory.tokens if token.role == "projection-collection"
    }
    assert len(names) == len(projection["collections"]) == 16
    token = AuthorityToken("projection-collection", (lowering["id"],), renamed)
    assert token in names - inventory.reserved
    assert selected["output_member"] == output_member != renamed
    root_reference = next(
        occurrence
        for occurrence in inventory.occurrences
        if occurrence.token == token
        and occurrence.pointer.endswith("/operation_roots/collection")
    )
    mutations = (
        replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != root_reference),
        ),
        replace(
            inventory,
            tokens=inventory.tokens - names,
            occurrences=tuple(o for o in inventory.occurrences if o.token not in names),
        ),
        replace(
            inventory,
            occurrences=tuple(
                replace(o, token=replace(token, owner=("foreign.lowering",)))
                if o == root_reference
                else o
                for o in inventory.occurrences
            ),
        ),
    )
    for incomplete in mutations:
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, incomplete)


@pytest.mark.parametrize("target", ["root", "resources", "descriptor"])
def test_ldb_root_framing_has_no_unclassified_authored_members(witness, target):
    kernel, graph, inventory = witness
    assert not any(gap.pointer == "/ldb_root" for gap in inventory.uncovered)
    changed = deepcopy(graph)
    root = changed["ldb_root"]
    container = (
        root
        if target == "root"
        else root["resources"]
        if target == "resources"
        else root["package_descriptors"][0]
    )
    container["shadow_identity"] = "uncovered"
    with pytest.raises(InventoryRefusal, match="LDB"):
        read_extension_inventory(kernel, changed)
    with pytest.raises(InventoryRefusal, match="LDB"):
        validate_extension_inventory(kernel, changed, inventory)


def test_resolution_binders_keep_lexical_owners_distinct_from_kernel_fields():
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_conformance_support import _reidentify_package_release
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    profile = next(
        definition
        for package in language["language"]["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
        for definition in closure["definitions"]
    )
    recipe = next(r for r in profile["relation_recipes"] if r["id"] == "packages")
    binder = recipe["bindings"][0]
    original = binder["name"]
    binder["name"] = "opaque.binding"
    # The existing package recipe has exactly one binding and one field term.
    assert len(recipe["bindings"]) == len(recipe["fields"]) == 1
    term = recipe["fields"][0]["term"]
    assert term["root"] == "binding" and term["binding"] == original
    term["binding"] = binder["name"]
    for i, judgment in enumerate(profile["judgment_chain"]):
        judgment["id"] = f"opaque.judgment.{i}"
    for package in language["language"]["packages"]:
        _reidentify_package_release(package)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert len(compile_checked_model(checked)) == 8
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
        "source": source,
    }
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    selected = AuthorityToken(
        "recipe-binding", (profile["id"], "packages"), binder["name"]
    )
    assert selected in inventory.tokens - inventory.reserved
    assert len([o for o in inventory.occurrences if o.token == selected]) == 2
    same_spelling = {token for token in inventory.tokens if token.name == "module"}
    assert any(t.role == "recipe-binding" for t in same_spelling - inventory.reserved)
    assert any(t.role.startswith("kernel.") for t in same_spelling & inventory.reserved)
    assert len(
        [token for token in inventory.tokens if token.role == "resolution-judgment"]
    ) == len(profile["judgment_chain"])
    reference = next(
        o for o in inventory.occurrences if o.token == selected and o.use == "reference"
    )
    incomplete = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != reference)
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, incomplete)
    omitted = {t for t in inventory.tokens if t.role == "recipe-binding"}
    missing_class = replace(
        inventory,
        tokens=inventory.tokens - omitted,
        occurrences=tuple(o for o in inventory.occurrences if o.token not in omitted),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, missing_class)
    graph_profile = next(
        definition
        for package in graph["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
        for definition in closure["definitions"]
    )
    graph_recipe = next(
        recipe
        for recipe in graph_profile["relation_recipes"]
        if recipe["id"] == "packages"
    )
    graph_recipe["bindings"][0]["source"]["unknown_selector"] = "module"
    with pytest.raises(InventoryRefusal, match="resolution term"):
        read_extension_inventory(kernel, graph)


def test_contract_vector_expected_values_inherit_only_declared_projection_roles(
    witness,
):
    kernel, graph, inventory = witness
    projected = [
        occurrence
        for occurrence in inventory.occurrences
        if occurrence.pointer.startswith("/vector_sets/")
        and "/expect" in occurrence.pointer
    ]
    for role in ("namespace", "operation-port", "runtime-effect", "operation-notation"):
        occurrence = next(o for o in projected if o.token.role == role)
        assert occurrence.use == "reference"
        missing = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != occurrence),
        )
        with pytest.raises(InventoryRefusal, match="projection coverage"):
            validate_extension_inventory(kernel, graph, missing)
    operand = next(
        o
        for o in projected
        if o.token.role == "operation-port" and o.token.name == "left"
    )
    other_owner = next(
        token
        for token in inventory.tokens
        if token.role == operand.token.role
        and token.name == operand.token.name
        and token.owner != operand.token.owner
    )
    extra = replace(
        inventory,
        occurrences=inventory.occurrences + (replace(operand, token=other_owner),),
    )
    with pytest.raises(InventoryRefusal, match="wrong semantic role"):
        validate_extension_inventory(kernel, graph, extra)
    changed = deepcopy(graph)
    numeric = next(
        vector
        for vector_set in changed["vector_sets"]
        for vector in vector_set["vector_definitions"]
        if vector.get("kind") == "operation-contract"
        and vector["probe"]["path"] == "resource_bounds.max_steps"
    )
    assert isinstance(numeric["expect"], int)
    numeric["expect"] += 1
    with pytest.raises(InventoryRefusal, match="expected subtree"):
        read_extension_inventory(kernel, changed)


def test_contract_projection_includes_late_derived_assignment_modes():
    from schema2_bootstrap_conformance_support import _bind_package_vector_set
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    owner = next(
        package
        for package in language["language"]["packages"]
        if any(
            closure["authority_path"] == "language.model_lowerings"
            and closure["definitions"]
            for closure in package["semantic_closure"]
        )
    )
    vector_set = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == owner["id"]
    )
    vector_id = "inventory.complete-lowering-projection"
    vector_set["vectors"].append(vector_id)
    vector_set["vector_definitions"].append(
        {
            "id": vector_id,
            "category": "positive",
            "kind": "package-contract",
            "probe": {"path": "semantic_closure"},
            "expect": deepcopy(owner["semantic_closure"]),
        }
    )
    _bind_package_vector_set(owner, vector_set)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
    }
    inventory = read_extension_inventory(kernel, graph)
    target = [
        occurrence
        for occurrence in inventory.occurrences
        if occurrence.token.role == "assignment-mode"
        and occurrence.pointer.startswith("/vector_sets/")
        and "/expect/" in occurrence.pointer
    ]
    assert target, "the vector must include roles derived after package traversal"
    validate_extension_inventory(kernel, graph, inventory)
    incomplete = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != target[0])
    )
    with pytest.raises(InventoryRefusal, match="projection coverage"):
        validate_extension_inventory(kernel, graph, incomplete)


def test_protocol_roles_do_not_merge_wire_schema_and_producer_kind_identities():
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_conformance_support import _reidentify_package_release
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    replacements = {
        "language.artifact_contracts": {"debug-map": "opaque.producer"},
        "language.artifact_wire_schemas": {"debug-map": "opaque.schema"},
        "language.wire_schemas": {"model-source-package": "opaque.source"},
    }
    for package in language["language"]["packages"]:
        for closure in package["semantic_closure"]:
            role = closure["authority_path"]
            for row in closure["definitions"]:
                if role in replacements:
                    original = row["artifact_kind"]
                    row["artifact_kind"] = replacements[role].get(original, original)
                    if (
                        role == "language.artifact_contracts"
                        and original == "debug-map"
                    ):
                        row["schema_kind"] = "opaque.schema"
                    if (
                        role == "language.artifact_wire_schemas"
                        and original == "debug-map"
                    ):
                        row["schema"]["properties"]["artifact_kind"]["const"] = (
                            "opaque.producer"
                        )
                        row["schema"]["properties"]["artifact_kind"]["type"] = "string"
                elif role == "language.template_admission_profiles":
                    for member in row["member_roles"]:
                        if member["member_kind"] == "model-source-package":
                            member["member_kind"] = "opaque.source"
            if role in replacements:
                export = role.removeprefix("language.")
                package["exports"][export] = [
                    replacements[role].get(name, name)
                    for name in package["exports"][export]
                ]
        _reidentify_package_release(package)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    artifacts = compile_checked_model(checked)
    assert len(artifacts) == 8
    assert any(row["artifact_kind"] == "opaque.producer" for row in artifacts.values())
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
        "source": source,
    }
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    producer = AuthorityToken("language.artifact_contracts", (), "opaque.producer")
    schema = AuthorityToken("language.artifact_wire_schemas", (), "opaque.schema")
    assert producer in inventory.tokens - inventory.reserved
    assert schema in inventory.tokens - inventory.reserved
    assert any(
        o.token == producer
        and o.pointer.endswith("/schema/properties/artifact_kind/const")
        for o in inventory.occurrences
    )
    link = next(
        o
        for o in inventory.occurrences
        if o.token == schema and o.pointer.endswith("/schema_kind")
    )
    protocol = next(
        o
        for o in inventory.occurrences
        if o.pointer.endswith("/protocol_role") and o.token.name == "debug-map"
    )
    assert protocol.token in inventory.reserved
    for removed in (link, protocol):
        incomplete = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != removed),
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, incomplete)
    wrong = replace(link, token=producer)
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(
            kernel,
            graph,
            replace(
                inventory,
                occurrences=tuple(
                    wrong if o == link else o for o in inventory.occurrences
                ),
            ),
        )
    # The authority boundary is covered; arbitrary nested schema semantics
    # remain an explicit obligation rather than being waived by role binding.
    assert inventory.uncovered
    contract_gaps = [
        gap for gap in inventory.uncovered if "artifact_contracts" in gap.law
    ]
    assert {gap.pointer.rsplit("/", 1)[-1] for gap in contract_gaps} == {
        "identity_excluded_members",
        "semantic_identity_projection",
    }


def test_typed_source_selector_publishes_only_complete_schema_addresses(witness):
    from schema2_bootstrap_conformance_support import (
        _consumer_b_relation_paths_are_typed,
    )

    kernel, language = mutable_authorities()
    profile = language["language"]["resolution_profiles"][0]
    resolution = kernel["meta_format"]["resolution_judgment"]
    addresses = {}
    assert _consumer_b_relation_paths_are_typed(
        profile,
        resolution,
        language,
        kernel["meta_format"]["package_release"],
        schema_addresses=addresses,
    )
    ri, recipe = next(
        (i, row)
        for i, row in enumerate(profile["relation_recipes"])
        if row["id"] == "modules"
    )
    binding = ("relation_recipes", ri, "bindings", 0, "source", "path", 0)
    fi = next(i for i, row in enumerate(recipe["fields"]) if row["name"] == "module")
    field = ("relation_recipes", ri, "fields", fi, "term", "path", 0)
    assert addresses[binding] == ("properties", "modules")
    assert addresses[field] == ("properties", "modules", "items", "properties", "id")
    original = deepcopy(addresses)
    malformed = deepcopy(profile)
    malformed["relation_recipes"][ri]["bindings"][0]["source"]["path"] = ["missing"]
    assert not _consumer_b_relation_paths_are_typed(
        malformed,
        resolution,
        language,
        kernel["meta_format"]["package_release"],
        schema_addresses=addresses,
    )
    assert addresses == {}, "a refused selector must not expose stale or partial proof"
    assert original[binding] == ("properties", "modules")
    kernel, graph, inventory = witness
    module_field = AuthorityToken(
        "source-field", ("language.wire_schemas", "model-source-package"), "modules"
    )
    id_field = AuthorityToken(
        "source-field",
        ("language.wire_schemas", "model-source-package", "member", "modules", "items"),
        "id",
    )
    assert {module_field, id_field} <= inventory.tokens - inventory.reserved
    assert any(
        o.token == module_field
        and o.location == "key"
        and o.pointer == "/source/modules"
        for o in inventory.occurrences
    )
    assert any(
        o.token == id_field
        and o.location == "key"
        and o.pointer == "/source/modules/0/id"
        for o in inventory.occurrences
    )
    occurrence = next(
        o
        for o in inventory.occurrences
        if o.token == id_field and o.use == "reference" and o.location == "value"
    )
    for candidate in (
        replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != occurrence),
        ),
        replace(
            inventory,
            occurrences=tuple(
                replace(o, token=replace(id_field, owner=module_field.owner))
                if o == occurrence
                else o
                for o in inventory.occurrences
            ),
        ),
    ):
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, candidate)


def test_dot_path_renaming_limits_only_its_actual_member_tokens(witness):
    kernel, graph, inventory = witness
    projected = next(o for o in inventory.occurrences if o.location == "member-path")
    sources = sorted(inventory.tokens - inventory.reserved)
    names = {token: f"renamed_{index}" for index, token in enumerate(sources)}
    names[projected.token] = "cannot.encode"
    with pytest.raises(InventoryRefusal, match="declared dot-path"):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )
    names[projected.token] = "encodable"
    namespace = next(token for token in sources if token.role == "namespace")
    names[namespace] = "still.valid.namespace"
    with pytest.raises(InventoryRefusal, match="uncovered semantic role"):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )
    omitted = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != projected)
    )
    with pytest.raises(InventoryRefusal, match="address coverage"):
        validate_extension_inventory(kernel, graph, omitted)
    ordinary = next(
        o
        for o in inventory.occurrences
        if o.token.name == "debug-map"
        and o.location == "value"
        and o.pointer.endswith("/schema_kind")
    )
    forged = replace(ordinary, location="member-path", projection="0")
    with pytest.raises(InventoryRefusal, match="no declared address projection"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(inventory, occurrences=(*inventory.occurrences, forged)),
        )


def test_inventory_consumes_the_complete_declared_source_module_mapping():
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import (
        CheckedModel,
        check_model_source_value,
        compile_checked_model,
    )
    from schema2_bootstrap_conformance_support import _reidentify_package_release
    from schema2_bootstrap_production_support import _reidentify_graph_root

    kernel, language = mutable_authorities()
    original, renamed = "modules", "opaque_modules"
    for package in language["language"]["packages"]:
        for closure in package["semantic_closure"]:
            role = closure["authority_path"]
            for row in closure["definitions"]:
                if (
                    role == "language.wire_schemas"
                    and row.get("protocol_role") == "model-source-package"
                ):
                    schema = row["schema"]
                    schema["properties"][renamed] = schema["properties"].pop(original)
                    schema["required"] = [
                        renamed if name == original else name
                        for name in schema["required"]
                    ]
                elif role == "language.resolution_profiles":
                    row["modules_member"] = renamed
                    for recipe in row["relation_recipes"]:
                        terms = [binding["source"] for binding in recipe["bindings"]]
                        terms.extend(field["term"] for field in recipe["fields"])
                        terms.extend(
                            predicate[side]
                            for predicate in recipe["predicates"]
                            for side in ("left", "right")
                        )
                        for term in terms:
                            if term["root"] == "source" and term["path"][:1] == [
                                original
                            ]:
                                term["path"][0] = renamed
                elif role == "language.model_lowerings":
                    if row["source_selector"][:1] == [original]:
                        row["source_selector"][0] = renamed
                elif role == "language.model_checks":
                    for member in ("selector", "scope_selector"):
                        if row.get(member, [])[:1] == [original]:
                            row[member][0] = renamed
        _reidentify_package_release(package)
    _reidentify_graph_root(language)
    a, b = _consumer_a(kernel, language), _consumer_b(kernel, language)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    source[renamed] = source.pop(original)
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert len(compile_checked_model(checked)) == 8
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
        "source": source,
    }
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    token = AuthorityToken(
        "source-field", ("language.wire_schemas", "model-source-package"), renamed
    )
    references = [o for o in inventory.occurrences if o.token == token]
    assert len([o for o in references if o.pointer.endswith("/source_selector/0")]) == 1
    assert (
        len(
            [
                o
                for o in references
                if o.pointer.endswith(("/selector/0", "/scope_selector/0"))
            ]
        )
        == 5
    )
    assert any(
        o.pointer == "/source/opaque_modules" and o.location == "key"
        for o in references
    )
    assert not any(
        o.pointer.startswith("/source/modules/") for o in inventory.occurrences
    )
    formula_source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/progression-periodic-effect/model-source.json"
        ).read_text()
    )
    formula_source[renamed] = formula_source.pop(original)
    requests = source_formula_requests(kernel, {**graph, "source": formula_source})
    assert requests
    assert all(pointer.startswith("/source/opaque_modules/") for pointer in requests)
    assert all(
        request["modules"] == formula_source[renamed] for request in requests.values()
    )
    assert all(
        request["package_requirements"] == formula_source["package_requirements"]
        for request in requests.values()
    )


def test_negative_inventory_lookup_names_remain_proven_unresolved_references(witness):
    kernel, graph, inventory = witness
    free = [
        o
        for o in inventory.occurrences
        if o.use == "unresolved-reference"
        and o.token.role in {"language.quantity.kinds", "language.quantity.units"}
    ]
    assert {o.token.name for o in free} == {"missing-kind", "missing-unit"}
    assert {o.token.role for o in free} == {
        "language.quantity.kinds",
        "language.quantity.units",
    }
    validate_extension_inventory(kernel, graph, inventory)
    assert not any(
        o.use == "declaration" and o.token in {row.token for row in free}
        for o in inventory.occurrences
    )
    assert not any(
        o.pointer == row.pointer for row in inventory.uncovered for o in free
    )
    for vector_set in graph["vector_sets"]:
        for vector in vector_set["vector_definitions"]:
            if vector.get("input") == {"values": ["health", "mana"]}:
                assert not any(
                    o.token.name in {"health", "mana"} and "/input/values/" in o.pointer
                    for o in inventory.occurrences
                )
    omitted = {row.token for row in free}
    with pytest.raises(InventoryRefusal, match="unresolved-reference"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(
                inventory,
                tokens=inventory.tokens - omitted,
                occurrences=tuple(
                    o for o in inventory.occurrences if o.token not in omitted
                ),
            ),
        )
    ordinary = next(
        o
        for o in inventory.occurrences
        if o.use == "reference" and o.pointer == "/source/entrypoints/0/operation/id"
    )
    forged = replace(ordinary, use="unresolved-reference")
    with pytest.raises(InventoryRefusal, match="unresolved-reference"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(
                inventory,
                occurrences=tuple(
                    forged if o == ordinary else o for o in inventory.occurrences
                ),
            ),
        )


def test_negative_lookup_renaming_refuses_capture_and_reserved_targets(witness):
    kernel, graph, inventory = witness
    selected = next(
        o
        for o in inventory.occurrences
        if o.use == "unresolved-reference" and o.token.role == "language.quantity.kinds"
    )
    sources = sorted(inventory.tokens - inventory.reserved)
    names = {token: f"renamed_{i}" for i, token in enumerate(sources)}
    declared = next(
        o.token
        for o in inventory.occurrences
        if o.use == "declaration" and o.token.role == selected.token.role
    )
    names[selected.token] = names[declared]
    with pytest.raises(InventoryRefusal, match="duplicate source or target"):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )
    names[selected.token] = "fresh.missing"
    pairs = token_bijection_from_names(inventory, names)
    reserved = next(iter(inventory.reserved))
    with pytest.raises(InventoryRefusal, match="Kernel-reserved"):
        validate_token_bijection(
            inventory,
            [
                (source, reserved if source == selected.token else target)
                for source, target in pairs
            ],
        )
    changed = deepcopy(graph)
    pieces = selected.pointer.split("/")
    vector = changed["vector_sets"][int(pieces[2])]["vector_definitions"][
        int(pieces[4])
    ]
    vector["input"]["value"] = declared.name
    with pytest.raises(InventoryRefusal, match="lookup absence"):
        read_extension_inventory(kernel, changed)


def test_value_vector_occurrences_preserve_lexical_and_typed_ownership(witness):
    kernel, graph, inventory = witness
    values = [
        (f"/vector_sets/{vi}/vector_definitions/{di}", vector)
        for vi, vector_set in enumerate(graph["vector_sets"])
        for di, vector in enumerate(vector_set["vector_definitions"])
        if vector.get("kind") in {"value-program", "structured-value"}
    ]
    assert sum(v["kind"] == "value-program" for _, v in values) == 24
    assert sum(v["kind"] == "structured-value" for _, v in values) == 24
    program_path, program = next(
        (p, v) for p, v in values if v["id"] == "formula.runtime.maximum.extrema"
    )
    scope = (program["id"],)
    local = AuthorityToken("vector-local", scope, "left_is_less")
    assert local in inventory.tokens
    assert {(o.pointer, o.use) for o in inventory.occurrences if o.token == local} == {
        (program_path + "/input/instructions/0/instruction/target", "declaration"),
        (program_path + "/input/instructions/1/instruction/condition", "reference"),
    }
    candidate_path, _ = next(
        (p, v) for p, v in values if v["id"] == "structured.accept.candidate"
    )
    enum = AuthorityToken(
        "enum-member", ("standard.conformance.structured", "CandidateKind"), "primary"
    )
    assert any(
        o.token == enum and o.pointer == candidate_path + "/input/left/value/kind"
        for o in inventory.occurrences
    )
    assert not any(
        o.pointer == candidate_path + "/input/left/value/key/key"
        and o.location == "value"
        for o in inventory.occurrences
    )  # A Ref instance key is canonical data, even when it resembles a name.
    validate_extension_inventory(kernel, graph, inventory)
    removed_class = {
        token for token in inventory.tokens if token.role == "vector-local"
    }
    with pytest.raises(InventoryRefusal, match="value vector occurrence coverage"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(
                inventory,
                tokens=inventory.tokens - removed_class,
                occurrences=tuple(
                    o for o in inventory.occurrences if o.token not in removed_class
                ),
            ),
        )
    transported = dict(
        token_bijection_from_names(
            inventory,
            {
                AuthorityToken("vectors", (), program["id"]): "opaque-program",
                local: "opaque-local",
            },
        )
    )
    assert transported[local].owner == ("opaque-program",)
    selected = next(
        o
        for o in inventory.occurrences
        if o.pointer == program_path + "/input/instructions/1/instruction/condition"
    )
    typed = next(
        o
        for o in inventory.occurrences
        if o.pointer == candidate_path + "/input/left/value/kind"
    )
    for occurrence in (selected, typed):
        omitted = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != occurrence),
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, omitted)
        wrong = replace(occurrence.token, owner=("wrong-owner",))
        misowned = replace(
            inventory,
            tokens=inventory.tokens | {wrong},
            occurrences=tuple(
                replace(o, token=wrong) if o == occurrence else o
                for o in inventory.occurrences
            ),
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, misowned)


@pytest.mark.parametrize("family", ["value-program", "structured-value"])
def test_value_vector_renaming_retains_two_actual_consumers(witness, family):
    from itertools import permutations

    from gda_balancing.domain.authority.graph import LanguageBundleGraph
    from gda_balancing.domain.structured_values import evaluate_structured_value_vector
    from schema2_bootstrap_conformance_support import (
        _consumer_b_evaluate_structured_value_vector,
        _encoded,
    )
    from schema2_extension_renaming_support import (
        _reseal_authored_graph,
        _rewrite_positions,
    )
    from schema2_value_program_production_support import evaluate_value_program_vector
    from schema2_value_program_reference_support import (
        reference_evaluate_value_program_vector,
    )

    kernel, graph, inventory = witness
    if family == "structured-value":
        # A fresh attached owner isolates this slice from still-unclassified
        # Operation-execution vectors that consume the maintained Enum types.
        graph = deepcopy(graph)
        namespace = "test.vector.nominal"
        package = deepcopy(graph["packages"][0])
        package["id"] = namespace
        package["capabilities"] = {"provided": [], "required": []}
        package["dependencies"] = {"required": ["standard.schema"], "optional": []}
        package["exports"] = {key: [] for key in package["exports"]}
        package["profiles"] = {key: [] for key in package["profiles"]}
        package["runtime_semantic_excluded_extensions"] = []
        for closure in package["semantic_closure"]:
            closure["definitions"] = []
        prototype = next(
            nominal
            for p in graph["packages"]
            for closure in p["semantic_closure"]
            if closure["authority_path"] == "language.nominal_types"
            for nominal in closure["definitions"]
            if nominal["id"] == "CandidateKind"
        )
        nominal = {**deepcopy(prototype), "id": "Token"}
        package["exports"]["types"] = [
            {"id": "Token", "constructor": nominal["constructor"]}
        ]
        package["exports"]["nominal_types"] = ["Token"]
        next(
            c
            for c in package["semantic_closure"]
            if c["authority_path"] == "language.nominal_types"
        )["definitions"] = [nominal]
        vector = {
            "id": "test.vector.accept-token",
            "kind": "structured-value",
            "category": "positive",
            "input": {
                "action": "admit",
                "key": None,
                "left": {
                    "type": {"package": namespace, "id": "Token"},
                    "value": "primary",
                },
                "right": None,
                "limit": None,
            },
            "expect": {
                "code": None,
                "outcome": "admitted",
                "pointer": "",
                "type": {"package": namespace, "id": "Token"},
                "value": "primary",
            },
        }
        graph["packages"].append(package)
        graph["vector_sets"].append(
            {
                "artifact_kind": graph["vector_sets"][0]["artifact_kind"],
                "package_id": namespace,
                "content_identity": "",
                "vectors": [vector["id"]],
                "vector_definitions": [vector],
            }
        )
        graph["ldb_root"]["package_descriptors"].append(
            {**graph["ldb_root"]["package_descriptors"][0], "id": namespace}
        )
        _reseal_authored_graph(kernel, graph)
        inventory = read_extension_inventory(kernel, graph)
        validate_extension_inventory(kernel, graph, inventory)
    before = deepcopy(graph)
    if family == "value-program":
        selected = {
            token: f"opaque_{i:04d}"
            for i, token in enumerate(sorted(inventory.tokens))
            if token.role in {"vector-local", "vector-site"}
        }
        # A coherent rename need not preserve lexical input-row order.
        scope = ("formula.runtime.maximum.extrema",)
        selected[AuthorityToken("vector-local", scope, "left")] = "z_left"
        selected[AuthorityToken("vector-local", scope, "right")] = "a_right"
    else:
        selected = {
            AuthorityToken(
                "enum-member",
                ("test.vector.nominal", "Token"),
                "primary",
            ): "chosen"
        }
    assert selected and set(selected) <= inventory.tokens - inventory.reserved
    occurrences = [o for o in inventory.occurrences if o.token in selected]
    assert occurrences and all(o.location in {"value", "key"} for o in occurrences)
    candidate = _rewrite_positions(
        graph,
        {o.pointer: selected[o.token] for o in occurrences if o.location == "value"},
        {o.pointer: selected[o.token] for o in occurrences if o.location == "key"},
    )
    _reseal_authored_graph(kernel, candidate)
    assert graph == before
    assert (
        candidate["ldb_root"]["content_identity"]
        != graph["ldb_root"]["content_identity"]
    )
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
    rewritten = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, rewritten)
    # This finite rename does not waive the remaining complete-graph obligations.
    assert rewritten.uncovered
    with pytest.raises(InventoryRefusal, match="uncovered semantic role"):
        rewritten.require_complete()
    for current in (graph, candidate):
        vectors = [
            v
            for vs in current["vector_sets"]
            for v in vs["vector_definitions"]
            if v.get("kind") == family
        ]
        assert len(vectors) == (24 if family == "value-program" else 25)
        for vector in vectors:
            if family == "value-program":
                a = evaluate_value_program_vector(
                    kernel, vector, phase="initialization"
                )
                b = reference_evaluate_value_program_vector(vector)
            else:
                args = dict(
                    nominal_types=current["packages"],
                    kernel=kernel,
                    resource_limit=current["ldb_root"]["resources"][
                        "max_rule_match_steps"
                    ],
                )
                a = evaluate_structured_value_vector(vector, **args)
                b = _consumer_b_evaluate_structured_value_vector(vector, **args)
            assert a == vector["expect"]
            assert b == vector["expect"]
            if family == "value-program":
                # Input bindings are a map. Instruction order still determines
                # results, exact charges, cache behavior and the first refusal.
                for ordering in permutations(vector["input"]["operands"]):
                    permuted = deepcopy(vector)
                    permuted["input"]["operands"] = list(ordering)
                    assert (
                        reference_evaluate_value_program_vector(permuted)
                        == vector["expect"]
                    )
                    for phase in ("initialization", "event", "observation"):
                        assert (
                            evaluate_value_program_vector(kernel, permuted, phase=phase)
                            == vector["expect"]
                        )
    if family == "value-program":
        # Renaming carries identity sites, never recalculates numerical oracles.
        original = {
            v["id"]: v
            for vs in graph["vector_sets"]
            for v in vs["vector_definitions"]
            if v.get("kind") == family
        }
        for vs in candidate["vector_sets"]:
            for v in vs["vector_definitions"]:
                if v.get("kind") == family:
                    assert {k: x for k, x in v["expect"].items() if k != "site"} == {
                        k: x
                        for k, x in original[v["id"]]["expect"].items()
                        if k != "site"
                    }


@pytest.mark.parametrize("position", [0, 2], ids=["first", "last"])
def test_value_vector_duplicate_bindings_refuse_before_order_can_choose_a_value(
    position,
):
    from test_schema2_template_cli import _reidentify_language_bundle

    kernel, language = mutable_authorities()
    vector = next(
        vector
        for vector_set in language.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "formula.runtime.maximum.extrema"
    )
    vector["input"]["operands"].insert(position, {"name": "right", "value": 0})
    _reidentify_language_bundle(kernel, language)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, language)
        assert not result["admitted"]
        assert [row[1] for row in result["diagnostics"]] == ["kernel.vector_mismatch"]
    graph = {
        "packages": language.package_releases,
        "ldb_root": language.root,
        "vector_sets": language.package_conformance_vector_sets,
    }
    with pytest.raises(InventoryRefusal, match="instruction or operand shape"):
        read_extension_inventory(kernel, graph)


def test_value_vector_literal_data_and_unclosed_negatives_cannot_claim_identity(
    witness,
):
    from schema2_extension_inventory_support import TokenOccurrence

    kernel, graph, inventory = witness
    vector_path, vector = next(
        (f"/vector_sets/{vi}/vector_definitions/{di}", v)
        for vi, vs in enumerate(graph["vector_sets"])
        for di, v in enumerate(vs["vector_definitions"])
        if v["id"] == "structured.accept.candidate"
    )
    key_path = vector_path + "/input/left/value/key/key"
    fake = AuthorityToken(
        "enum-member",
        ("standard.conformance.structured", "CandidateKind"),
        "candidate_a",
    )
    forged = replace(
        inventory,
        tokens=inventory.tokens | {fake},
        occurrences=(
            *inventory.occurrences,
            TokenOccurrence(fake, key_path, "reference", "/meta_format/package_vector"),
        ),
    )
    with pytest.raises(InventoryRefusal, match="no interpreted identity role"):
        validate_extension_inventory(kernel, graph, forged)
    negative = next(
        f"/vector_sets/{vi}/vector_definitions/{di}"
        for vi, vs in enumerate(graph["vector_sets"])
        for di, v in enumerate(vs["vector_definitions"])
        if v["id"] == "structured.refuse.unknown-enum-member"
    )
    actual = next(
        o for o in inventory.occurrences if o.pointer == negative + "/input/left/value"
    )
    assert actual.use == "unresolved-reference"
    assert actual.token == replace(fake, name="unknown")
    assert not any(g.pointer.startswith(negative + "/") for g in inventory.uncovered)
    # The real lookup proves absence only in its selected nominal owner.
    wrong = replace(
        actual, token=replace(actual.token, owner=("test.other", "CandidateKind"))
    )
    fake_free = replace(
        inventory,
        tokens=(inventory.tokens - {actual.token}) | {wrong.token},
        occurrences=tuple(wrong if o == actual else o for o in inventory.occurrences),
    )
    with pytest.raises(InventoryRefusal, match="unresolved-reference"):
        validate_extension_inventory(kernel, graph, fake_free)
    changed = deepcopy(graph)
    vi, di = (int(vector_path.split("/")[index]) for index in (2, 4))
    changed["vector_sets"][vi]["vector_definitions"][di]["input"]["hidden_owner"] = (
        "standard.schema"
    )
    with pytest.raises(InventoryRefusal, match="unknown declared member"):
        read_extension_inventory(kernel, changed)
    assert vector["input"]["left"]["value"]["key"]["key"] == "candidate_a"


def test_structured_vector_inventory_closes_anonymous_and_negative_roles(witness):
    kernel, graph, inventory = witness
    roots = {
        v["id"]: f"/vector_sets/{vi}/vector_definitions/{di}"
        for vi, vs in enumerate(graph["vector_sets"])
        for di, v in enumerate(vs["vector_definitions"])
        if v.get("kind") == "structured-value"
    }
    assert len(roots) == 24
    assert not [
        gap
        for gap in inventory.uncovered
        if any(
            gap.pointer == root or gap.pointer.startswith(root + "/")
            for root in roots.values()
        )
    ]
    anonymous = {t for t in inventory.tokens if t.role == "vector-enum-member"}
    assert len(anonymous) == 3
    assert {t.name for t in anonymous} == {"value"}
    assert {t.owner[0] for t in anonymous} == {
        "structured.list-empty.nonempty",
        "structured.list-empty.empty",
        "structured.list-empty.refuse-non-list",
    }
    assert not (anonymous & inventory.reserved)
    extra = AuthorityToken(
        "record-field", ("standard.conformance.structured", "Candidate"), "extra"
    )
    rows = [o for o in inventory.occurrences if o.token == extra]
    assert {(o.use, o.location, o.projection) for o in rows} == {
        ("unresolved-reference", "key", ""),
        ("unresolved-reference", "json-pointer", "1"),
    }
    assert {o.pointer for o in rows} == {
        roots["structured.refuse.record-extra-field"] + "/input/left/value/extra",
        roots["structured.refuse.record-extra-field"] + "/expect/pointer",
    }
    validate_extension_inventory(kernel, graph, inventory)
    for selected in (
        rows[0],
        next(o for o in inventory.occurrences if o.token in anonymous),
    ):
        omitted = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != selected),
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, omitted)
    # Anonymous classes cannot disappear or acquire another vector's owner.
    without_class = replace(
        inventory,
        tokens=inventory.tokens - anonymous,
        occurrences=tuple(o for o in inventory.occurrences if o.token not in anonymous),
    )
    with pytest.raises(InventoryRefusal, match="value vector occurrence coverage"):
        validate_extension_inventory(kernel, graph, without_class)
    selected_token = next(iter(anonymous))
    wrong = replace(selected_token, owner=("other-vector", *selected_token.owner[1:]))
    wrong_owner = replace(
        inventory,
        tokens=(inventory.tokens - {selected_token}) | {wrong},
        occurrences=tuple(
            replace(o, token=wrong) if o.token == selected_token else o
            for o in inventory.occurrences
        ),
    )
    with pytest.raises(InventoryRefusal, match="value vector occurrence coverage"):
        validate_extension_inventory(kernel, graph, wrong_owner)


def _assert_structured_graph_observations(kernel, graph, *, original=None):
    """Check legal graph admission and each consumer against authored observations."""
    from gda_balancing.domain.authority.graph import LanguageBundleGraph
    from gda_balancing.domain.structured_values import evaluate_structured_value_vector
    from schema2_bootstrap_conformance_support import (
        _consumer_b_evaluate_structured_value_vector,
        _encoded,
    )

    authored = LanguageBundleGraph(
        root=graph["ldb_root"],
        package_releases=graph["packages"],
        package_conformance_vector_sets=graph["vector_sets"],
        root_byte_size=len(_encoded(graph["ldb_root"])),
        package_byte_sizes=[len(_encoded(p)) for p in graph["packages"]],
        vector_set_byte_sizes=[len(_encoded(v)) for v in graph["vector_sets"]],
    )
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    vectors = [
        v
        for vs in graph["vector_sets"]
        for v in vs["vector_definitions"]
        if v.get("kind") == "structured-value"
    ]
    assert len(vectors) == 24
    expected = (
        None
        if original is None
        else {
            v["id"]: v["expect"]
            for vs in original["vector_sets"]
            for v in vs["vector_definitions"]
            if v.get("kind") == "structured-value"
        }
    )
    args = dict(
        nominal_types=graph["packages"],
        kernel=kernel,
        resource_limit=graph["ldb_root"]["resources"]["max_rule_match_steps"],
    )
    for vector in vectors:
        if expected is not None:
            assert vector["expect"] == expected[vector["id"]]
        for evaluate in (
            evaluate_structured_value_vector,
            _consumer_b_evaluate_structured_value_vector,
        ):
            assert evaluate(vector, **args) == vector["expect"], vector["id"]


@pytest.mark.parametrize("case", ["equal", "unequal", "missing", "extra"])
def test_anonymous_vector_scope_and_fault_paths_follow_actual_type_law(witness, case):
    from schema2_extension_inventory_support import (
        _child,
        _json_pointer_segments,
    )
    from schema2_extension_renaming_support import (
        _json_pointer_values,
        _reseal_authored_graph,
        _rewrite_positions,
    )

    kernel, original, _ = witness
    graph = deepcopy(original)
    pointer, vector = next(
        (f"/vector_sets/{vi}/vector_definitions/{di}", v)
        for vi, vs in enumerate(graph["vector_sets"])
        for di, v in enumerate(vs["vector_definitions"])
        if v["id"] == "structured.list-empty.nonempty"
    )
    field, extra = "part/~value", "extra/~field"
    annotation = {
        "kind": "record",
        "fields": [{"name": field, "type": {"kind": "enum", "members": ["value"]}}],
    }
    if case in {"equal", "unequal"}:
        left = {"type": {"kind": "enum", "members": ["value"]}, "value": "value"}
        right = deepcopy(left)
        if case == "unequal":
            right = {"type": {"kind": "enum", "members": ["other"]}, "value": "other"}
    else:
        left = {"type": annotation, "value": {field: "value"}}
        right = None
        if case == "missing":
            left["value"] = {}
        else:
            left["value"][extra] = {"value": "this payload has no declared type"}
    vector["input"] = {
        "action": "equal" if right is not None else "admit",
        "left": left,
        "right": right,
        "key": None,
        "limit": None,
    }
    vector["category"] = "positive" if case == "equal" else "negative"
    vector["expect"] = (
        {
            "outcome": "admitted",
            "code": None,
            "pointer": "",
            "type": {"package": "kernel", "id": "Boolean"},
            "value": True,
        }
        if case == "equal"
        else {
            "outcome": "refused",
            "code": "language.structured_value_type_mismatch"
            if case == "unequal"
            else "language.structured_value_record_member_mismatch",
            "pointer": "/right/type"
            if case == "unequal"
            else _child("/value", field if case == "missing" else extra),
            "type": None,
            "value": None,
        }
    )
    _reseal_authored_graph(kernel, graph)
    _assert_structured_graph_observations(kernel, graph)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert not any(g.pointer.startswith(pointer) for g in inventory.uncovered)
    scope = (vector["id"], "comparison" if right is not None else "left")
    field_token = AuthorityToken("vector-record-field", scope, field)
    enum_token = AuthorityToken(
        "vector-enum-member",
        (*scope, "field", field) if right is None else scope,
        "value",
    )
    assert enum_token in inventory.tokens - inventory.reserved
    if right is not None:
        declarations = [
            o
            for o in inventory.occurrences
            if o.token == enum_token and o.use == "declaration"
        ]
        assert {o.pointer for o in declarations} == {
            pointer + f"/input/{side}/type/members/0"
            for side in (("left", "right") if case == "equal" else ("left",))
        }
        selected_token = enum_token
        renamed = {enum_token: "renamed-member"}
        other = replace(enum_token, name="other") if case == "unequal" else None
    else:
        assert field_token in inventory.tokens - inventory.reserved
        fault = next(
            o for o in inventory.occurrences if o.pointer == pointer + "/expect/pointer"
        )
        assert (fault.location, fault.projection) == ("json-pointer", "1")
        assert (
            _json_pointer_segments(vector["expect"]["pointer"])[1] == fault.token.name
        )
        assert fault.token == (
            field_token if case == "missing" else replace(field_token, name=extra)
        )
        assert fault.use == (
            "reference" if case == "missing" else "unresolved-reference"
        )
        for changed in (
            replace(
                inventory,
                occurrences=tuple(o for o in inventory.occurrences if o != fault),
            ),
            replace(
                inventory,
                occurrences=tuple(
                    replace(o, projection="0") if o == fault else o
                    for o in inventory.occurrences
                ),
            ),
        ):
            with pytest.raises(InventoryRefusal):
                validate_extension_inventory(kernel, graph, changed)
        selected_token = field_token
        renamed = {field_token: "renamed/~field", enum_token: "renamed-member"}
        other = replace(field_token, name=extra) if case == "extra" else None
    # Shared comparison scope keeps equal annotations compatible and prevents
    # unequal annotations (or an absent Record field) from being captured.
    if other is not None:
        renamed[other] = "renamed/~other"
        names = {
            t: f"renamed_{i}"
            for i, t in enumerate(sorted(inventory.tokens - inventory.reserved))
        }
        names[other] = names[selected_token]
        with pytest.raises(InventoryRefusal, match="duplicate source or target"):
            validate_token_bijection(
                inventory, token_bijection_from_names(inventory, names)
            )
    pairs = dict(
        token_bijection_from_names(
            inventory,
            {**renamed, AuthorityToken("vectors", (), vector["id"]): "new-vector"},
        )
    )
    assert pairs[enum_token].owner == (
        ("new-vector", scope[1], "field", renamed[field_token])
        if right is None
        else ("new-vector", scope[1])
    )
    rows = [o for o in inventory.occurrences if o.token in renamed]
    values = {o.pointer: renamed[o.token] for o in rows if o.location == "value"}
    keys = {o.pointer: renamed[o.token] for o in rows if o.location == "key"}
    paths = {}
    for o in rows:
        if o.location == "json-pointer":
            paths.setdefault(o.pointer, {})[int(o.projection)] = renamed[o.token]
    values.update(_json_pointer_values(graph, paths))
    candidate = _rewrite_positions(graph, values, keys)
    _reseal_authored_graph(kernel, candidate)
    _assert_structured_graph_observations(kernel, candidate)
    after = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, after)
    assert after.uncovered  # This slice does not waive unrelated whole-graph gaps.
    if case == "extra":
        # Undeclared payload strings do not acquire the field's missing-name role.
        assert not any(
            o.pointer.startswith(pointer + "/input/left/value/extra~1~0field/")
            for o in inventory.occurrences
        )
